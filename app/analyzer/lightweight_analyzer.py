from __future__ import annotations

from app.models.evidence import AssertionResult, StepEvidence


class LightweightAnalyzer:
    def classify(self, *, evidence: StepEvidence, assertion: AssertionResult) -> str | None:
        if assertion.status == "passed":
            return None
        if evidence.status != "passed":
            return "execution_error"
        if evidence.network_failures:
            return "environment_error"
        if assertion.errors:
            return "assertion_failed"
        if assertion.visual_issues:
            return "visual_warning"
        return "unknown"
