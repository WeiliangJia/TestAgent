from __future__ import annotations

from app.integrations.browser_use_client import BrowserExecution
from app.integrations.vlm_client import LayerVerdict, VLMClient
from app.models.evidence import AssertionResult
from app.models.test_case import TestCase


class AssertionEngine:
    """Two-layer assertion.

    - Layer 1 (functional): inspects execution status, DOM, console, and network
      to decide whether the expected outcome is reachable and reported.
    - Layer 2 (visual / layout): delegates to a VLM that looks at the screenshot.

    The two verdicts are combined: any "failed" wins; otherwise both "passed"
    yields "passed"; mixed states yield "warning". If the averaged confidence
    falls below ``warning_threshold`` a final "passed" is downgraded to
    "warning" so the report surfaces the uncertainty.
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
        return self._combine(layer1, layer2)

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

        visual_issues: list[str] = []
        if execution.console_errors:
            visual_issues.append("Console errors were present during execution.")

        tokens = _important_tokens(test_case.expected)
        if not tokens:
            return LayerVerdict(
                status="warning",
                confidence=0.5,
                visual_issues=visual_issues,
                rationale="no-expected-tokens",
            )

        normalized_dom = execution.dom_snapshot.lower()
        matched = [token for token in tokens if token in normalized_dom]
        ratio = len(matched) / len(tokens)
        if ratio >= 0.35:
            return LayerVerdict(
                status="passed",
                confidence=min(0.95, 0.55 + ratio / 2),
                visual_issues=visual_issues,
                rationale=f"token-ratio {ratio:.2f}",
            )
        return LayerVerdict(
            status="failed",
            confidence=0.75,
            errors=[f"Expected content was not visible enough: {test_case.expected}"],
            visual_issues=visual_issues,
            rationale=f"token-ratio {ratio:.2f}",
        )

    def _combine(self, layer1: LayerVerdict, layer2: LayerVerdict) -> AssertionResult:
        statuses = {layer1.status, layer2.status}
        if "failed" in statuses:
            status = "failed"
        elif statuses == {"passed"}:
            status = "passed"
        else:
            status = "warning"

        confidence = (layer1.confidence + layer2.confidence) / 2
        if status == "passed" and confidence < self.warning_threshold:
            status = "warning"

        errors = list(layer1.errors) + list(layer2.errors)
        visual_issues = list(layer1.visual_issues) + list(layer2.visual_issues)
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
        token = "".join(ch for ch in raw if ch.isalnum())
        if len(token) >= 3 and token not in stop_words:
            tokens.append(token)
    return tokens[:12]
