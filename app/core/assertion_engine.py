from __future__ import annotations

from pathlib import Path

from app.integrations.browser_use_client import BrowserExecution
from app.integrations.vlm_client import LayerVerdict, VLMClient
from app.models.evidence import AssertionResult, FunctionalResult, UIResult
from app.models.test_case import TestCase


class AssertionEngine:
    """Two-layer assertion, both VLM-driven.

    - Layer 1 (functional): VLM inspects the screenshot plus console/DOM hints
      and decides whether the expected outcome is visibly reachable.
    - Layer 2 (visual):     VLM inspects layout quality on the same screenshot.

    Layer 2 is SKIPPED when ``skip_visual=True`` (set from
    ``TEST_AGENT_SKIP_VISUAL_TESTS`` or for ACs whose ``testType=="visual"``).
    In that case the combined status is driven by Layer 1 only and ``ui`` in
    the result is a SKIPPED marker.
    """

    def __init__(
        self,
        vlm: VLMClient,
        *,
        warning_threshold: float = 0.6,
        skip_visual: bool = True,
    ) -> None:
        self.vlm = vlm
        self.warning_threshold = warning_threshold
        self.skip_visual = skip_visual

    def assert_test_case(
        self, *, test_case: TestCase, execution: BrowserExecution
    ) -> AssertionResult:
        layer1 = self._assert_functional(test_case=test_case, execution=execution)
        functional = _functional_result_from_verdict(layer1, execution=execution)

        # Per current product decision, UI layer is deferred — always SKIPPED.
        # Keeping the wiring here so re-enabling is a one-line flip.
        if self.skip_visual or (test_case.test_type or "").lower() == "visual":
            ui = UIResult(result="SKIPPED", rationale="UI layer disabled in this run")
            return self._combine(
                layer1=layer1,
                layer2=None,
                functional=functional,
                ui=ui,
                test_case=test_case,
            )

        layer2 = self.vlm.assert_visual(
            expected=test_case.expected,
            screenshot_path=str(execution.screenshot_path),
        )
        ui = _ui_result_from_verdict(layer2)
        return self._combine(
            layer1=layer1,
            layer2=layer2,
            functional=functional,
            ui=ui,
            test_case=test_case,
        )

    def _assert_functional(
        self, *, test_case: TestCase, execution: BrowserExecution
    ) -> LayerVerdict:
        ac_tag = f"AC {test_case.ac_id}" if test_case.ac_id else "assertion"
        if execution.status != "passed":
            note = (execution.notes[-1] if execution.notes else "").strip()[:200]
            msg = (
                f"Browser execution did not complete successfully for {ac_tag} "
                f"(execution.status={execution.status}). Last note: "
                f"{note or '(none)'}. Current URL: {execution.current_url or '(none)'}."
            )
            return LayerVerdict(
                status="failed",
                confidence=0.9,
                errors=[msg],
                rationale="execution-not-passed",
            )
        if execution.network_failures:
            detail = "; ".join(execution.network_failures[:3])
            msg = (
                f"Network failures observed during {ac_tag} execution "
                f"({len(execution.network_failures)} total): {detail}. "
                f"URL: {execution.current_url or '(none)'}."
            )
            return LayerVerdict(
                status="failed",
                confidence=0.85,
                errors=[msg],
                rationale="network-failures",
            )
        if _is_placeholder_screenshot(execution.screenshot_path):
            msg = (
                f"Browser execution did not capture a real screenshot for {ac_tag} "
                f"(placeholder PNG at {execution.screenshot_path}). "
                "Browser-use agent likely exited before reaching the target page."
            )
            return LayerVerdict(
                status="failed",
                confidence=0.9,
                errors=[msg],
                rationale="placeholder-screenshot",
            )

        expected = test_case.expected or ""
        verdict = self.vlm.assert_functional(
            expected=expected,
            screenshot_path=str(execution.screenshot_path),
            dom_hint=execution.dom_snapshot,
            console_errors=list(execution.console_errors),
        )
        # Prefix VLM rationale with concrete context so downstream consumers
        # (ledger failureReason, report) always see WHICH ac/url the verdict is about.
        if verdict.rationale:
            verdict.rationale = (
                f"[{ac_tag} @ {execution.current_url or 'unknown-url'}] "
                + verdict.rationale
            )
        # If the VLM returned an errors list, expand the first entry with context.
        if verdict.errors:
            first = verdict.errors[0]
            verdict.errors[0] = (
                f"{ac_tag}: {first} "
                f"(expected: {expected[:160]}; url: {execution.current_url or 'unknown'})"
            )
        # Surface console errors as advisory signal when VLM didn't already flag them.
        if execution.console_errors and not any(
            "console" in issue.lower() for issue in verdict.visual_issues
        ):
            sample = "; ".join(execution.console_errors[:3])
            verdict.visual_issues.append(
                f"Console errors during execution: {sample}"
            )
        return verdict

    def _combine(
        self,
        *,
        layer1: LayerVerdict,
        layer2: LayerVerdict | None,
        functional: FunctionalResult,
        ui: UIResult,
        test_case: TestCase,
    ) -> AssertionResult:
        if layer2 is None:
            status = layer1.status
            confidence = layer1.confidence
        else:
            test_type = (test_case.test_type or "integration").lower()
            if test_type == "visual":
                status, confidence = _combine_visual(layer1, layer2)
            else:
                status, confidence = _combine_behavioral(layer1, layer2)

        if status == "passed" and confidence < self.warning_threshold:
            status = "warning"

        errors: list[str] = list(layer1.errors)
        visual_issues: list[str] = list(layer1.visual_issues)
        if layer2 is not None:
            errors.extend(layer2.errors)
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
            functional=functional,
            ui=ui,
        )


def _functional_result_from_verdict(
    verdict: LayerVerdict, *, execution: BrowserExecution
) -> FunctionalResult:
    result = {"passed": "PASS", "failed": "FAIL", "warning": "FAIL"}.get(
        verdict.status, "FAIL"
    )
    logs: list[str] = []
    if execution.current_url:
        logs.append(f"INFO: final URL {execution.current_url}")
    if execution.notes:
        logs.extend(f"INFO: {note}" for note in execution.notes[:3])
    return FunctionalResult(
        result=result,
        confidence=round(verdict.confidence, 3),
        errors=list(verdict.errors),
        logs=logs,
        rationale=verdict.rationale,
    )


def _ui_result_from_verdict(verdict: LayerVerdict) -> UIResult:
    mapping = {"passed": "PASS", "failed": "FAIL", "warning": "WARNING"}
    issues: list[dict[str, str]] = [
        {"description": issue} for issue in verdict.visual_issues
    ]
    return UIResult(
        result=mapping.get(verdict.status, "WARNING"),
        confidence=round(verdict.confidence, 3),
        issues=issues,
        rationale=verdict.rationale,
    )


def _combine_visual(
    layer1: LayerVerdict, layer2: LayerVerdict
) -> tuple[str, float]:
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
    confidence = layer2.confidence * 0.8 + layer1.confidence * 0.2
    return status, confidence


def _combine_behavioral(
    layer1: LayerVerdict, layer2: LayerVerdict
) -> tuple[str, float]:
    statuses = {layer1.status, layer2.status}
    if "failed" in statuses:
        status = "failed"
    elif statuses == {"passed"}:
        status = "passed"
    else:
        status = "warning"
    confidence = (layer1.confidence + layer2.confidence) / 2
    return status, confidence


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
