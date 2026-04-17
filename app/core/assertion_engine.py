from __future__ import annotations

from pathlib import Path

from app.integrations.browser_use_client import BrowserExecution
from app.integrations.vlm_client import LayerVerdict, VLMClient
from app.models.evidence import AssertionResult
from app.models.test_case import TestCase


class AssertionEngine:
    """Two-layer assertion.

    - Layer 1 (functional): inspects execution status, DOM, console, and network
      to decide whether the expected outcome is reachable and reported.
    - Layer 2 (visual / layout): delegates to a VLM that looks at the screenshot.

    Combining rules depend on test_type:
    - For "visual" ACs the VLM verdict is authoritative; Layer 1 is advisory only.
    - For behavioral/integration ACs any "failed" wins, but a strong VLM pass
      (confidence >= 0.8) can overturn a Layer 1 text-match failure.
    """

    def __init__(self, vlm: VLMClient, *, warning_threshold: float = 0.6) -> None:
        self.vlm = vlm
        self.warning_threshold = warning_threshold

    def assert_test_case(
        self, *, test_case: TestCase, execution: BrowserExecution
    ) -> AssertionResult:
        layer1 = self._assert_functional(test_case=test_case, execution=execution)
        layer2 = self.vlm.assert_visual(
            expected=test_case.expected,
            screenshot_path=str(execution.screenshot_path),
        )
        return self._combine(layer1, layer2, test_case=test_case)

    def _assert_functional(
        self, *, test_case: TestCase, execution: BrowserExecution
    ) -> LayerVerdict:
        if execution.status != "passed":
            return LayerVerdict(
                status="failed",
                confidence=0.9,
                errors=["Browser execution failed before assertion."],
                rationale="execution-not-passed",
            )
        if execution.network_failures:
            return LayerVerdict(
                status="failed",
                confidence=0.85,
                errors=["Network failures observed during execution."],
                rationale="network-failures",
            )
        if _is_placeholder_screenshot(execution.screenshot_path):
            return LayerVerdict(
                status="failed",
                confidence=0.9,
                errors=["Browser execution did not capture a real screenshot."],
                rationale="placeholder-screenshot",
            )

        visual_issues: list[str] = []
        if execution.console_errors:
            visual_issues.append("Console errors were present during execution.")

        expected = test_case.expected or ""
        normalized_dom = execution.dom_snapshot.lower()

        ratio, strategy = _expected_match_ratio(expected, normalized_dom)
        if strategy == "none":
            return LayerVerdict(
                status="warning",
                confidence=0.5,
                visual_issues=visual_issues,
                rationale="no-expected-tokens",
            )
        if strategy == "cjk-no-dom-match":
            return LayerVerdict(
                status="warning",
                confidence=0.5,
                visual_issues=visual_issues
                + [
                    "Expected text is CJK but DOM is mostly non-CJK; "
                    "functional text match skipped, relying on VLM."
                ],
                rationale="cjk-dom-mismatch",
            )
        if ratio >= 0.35:
            return LayerVerdict(
                status="passed",
                confidence=min(0.95, 0.55 + ratio / 2),
                visual_issues=visual_issues,
                rationale=f"{strategy} {ratio:.2f}",
            )
        return LayerVerdict(
            status="failed",
            confidence=0.75,
            errors=[f"Expected content was not visible enough: {expected}"],
            visual_issues=visual_issues,
            rationale=f"{strategy} {ratio:.2f}",
        )

    def _combine(
        self,
        layer1: LayerVerdict,
        layer2: LayerVerdict,
        *,
        test_case: TestCase,
    ) -> AssertionResult:
        test_type = (test_case.test_type or "integration").lower()
        is_visual = test_type == "visual"

        if is_visual:
            status, confidence = _combine_visual(layer1, layer2)
        else:
            status, confidence = _combine_behavioral(layer1, layer2)

        if status == "passed" and confidence < self.warning_threshold:
            status = "warning"

        errors: list[str] = []
        visual_issues: list[str] = []

        if is_visual:
            # For visual ACs, surface Layer 1 only as supplementary signal.
            if layer2.status == "failed":
                errors.extend(layer2.errors)
            if status == "failed" and not errors:
                errors.extend(layer1.errors or layer2.errors)
            visual_issues.extend(layer2.visual_issues)
            if layer1.visual_issues:
                visual_issues.extend(layer1.visual_issues)
        else:
            errors.extend(layer1.errors)
            errors.extend(layer2.errors)
            visual_issues.extend(layer1.visual_issues)
            visual_issues.extend(layer2.visual_issues)

        if layer2.rationale:
            visual_issues.append(f"VLM: {layer2.rationale}")
        if layer1.rationale:
            visual_issues.append(f"Functional: {layer1.rationale}")

        return AssertionResult(
            status=status,
            confidence=round(confidence, 3),
            errors=errors,
            visual_issues=visual_issues,
        )


def _combine_visual(
    layer1: LayerVerdict, layer2: LayerVerdict
) -> tuple[str, float]:
    # For visual ACs Layer 2 is authoritative.
    # Layer 1 can only demote a "passed" to "warning" if it sees a hard signal
    # (network/console), never force a "failed".
    status = layer2.status
    if status == "passed" and layer1.status == "failed" and layer1.errors:
        blocking = any(
            "execution failed" in err.lower()
            or "network failure" in err.lower()
            or "placeholder" in err.lower()
            for err in layer1.errors
        )
        if blocking:
            status = "failed"
    # Confidence weight: 80% VLM, 20% functional.
    confidence = layer2.confidence * 0.8 + layer1.confidence * 0.2
    return status, confidence


def _combine_behavioral(
    layer1: LayerVerdict, layer2: LayerVerdict
) -> tuple[str, float]:
    statuses = {layer1.status, layer2.status}
    if "failed" in statuses:
        # Allow a strong VLM pass to overturn a Layer 1 token-ratio miss,
        # but only when Layer 1 failed on pure text matching.
        only_text_mismatch = (
            layer1.status == "failed"
            and layer2.status == "passed"
            and layer2.confidence >= 0.8
            and layer1.rationale.startswith(("token-ratio", "bigram-ratio"))
        )
        status = "warning" if only_text_mismatch else "failed"
    elif statuses == {"passed"}:
        status = "passed"
    else:
        status = "warning"
    confidence = (layer1.confidence + layer2.confidence) / 2
    return status, confidence


def _expected_match_ratio(expected: str, normalized_dom: str) -> tuple[float, str]:
    """Return (ratio, strategy). Strategy is one of:
    'token-ratio', 'bigram-ratio', 'cjk-no-dom-match', 'none'.
    """
    if not expected.strip() or not normalized_dom:
        return 0.0, "none"

    cjk_ratio = _cjk_char_ratio(expected)
    if cjk_ratio >= 0.3:
        # CJK-heavy expected text: use bigram matching because Chinese doesn't
        # split by whitespace and single characters are too noisy.
        dom_cjk = _cjk_char_ratio(normalized_dom)
        if dom_cjk < 0.02:
            # Expected is CJK but the rendered DOM has essentially no CJK —
            # means the site is not localised to match the AC wording.
            # Don't fail on text; let VLM decide.
            return 0.0, "cjk-no-dom-match"
        bigrams = _cjk_bigrams(expected)
        if not bigrams:
            return 0.0, "none"
        matched = sum(1 for bg in bigrams if bg in normalized_dom)
        return matched / len(bigrams), "bigram-ratio"

    tokens = _important_tokens(expected)
    if not tokens:
        return 0.0, "none"
    matched = sum(1 for token in tokens if token in normalized_dom)
    return matched / len(tokens), "token-ratio"


def _cjk_char_ratio(text: str) -> float:
    total = 0
    cjk = 0
    for ch in text:
        if ch.isspace():
            continue
        total += 1
        if _is_cjk(ch):
            cjk += 1
    return cjk / total if total else 0.0


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (
        0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0x20000 <= code <= 0x2A6DF
        or 0x3040 <= code <= 0x30FF  # Japanese kana — treat as CJK
        or 0xAC00 <= code <= 0xD7AF  # Hangul
    )


def _cjk_bigrams(text: str) -> list[str]:
    cjk_chars = [ch for ch in text if _is_cjk(ch)]
    if len(cjk_chars) < 2:
        return []
    seen: set[str] = set()
    bigrams: list[str] = []
    for i in range(len(cjk_chars) - 1):
        bg = cjk_chars[i] + cjk_chars[i + 1]
        if bg not in seen:
            seen.add(bg)
            bigrams.append(bg)
    return bigrams[:20]


def _important_tokens(text: str) -> list[str]:
    stop_words = {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "user",
        "can",
        "complete",
        "visible",
        "expected",
        "result",
        "page",
        "provides",
        "feedback",
    }
    tokens: list[str] = []
    for raw in text.lower().replace(".", " ").replace(",", " ").split():
        token = "".join(ch for ch in raw if ch.isalnum() and not _is_cjk(ch))
        if len(token) >= 3 and token not in stop_words:
            tokens.append(token)
    return tokens[:12]


def _is_placeholder_screenshot(path: Path) -> bool:
    try:
        data = path.read_bytes()
    except OSError:
        return False
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return False
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return width <= 1 and height <= 1
