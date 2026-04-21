from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class StepEvidence:
    step: str
    status: str
    current_url: str
    screenshot_path: str | None = None
    dom_snapshot_path: str | None = None
    console_errors: list[str] = field(default_factory=list)
    network_failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FunctionalResult:
    """Layer 1 functional verdict per test case."""

    result: str  # "PASS" | "FAIL" | "SKIPPED"
    confidence: float = 0.0
    errors: list[str] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "result": self.result,
            "confidence": self.confidence,
            "errors": list(self.errors),
            "logs": list(self.logs),
            "rationale": self.rationale,
        }


@dataclass(slots=True)
class UIResult:
    """Layer 2 visual verdict per test case. Populated only when visual review runs."""

    result: str  # "PASS" | "WARNING" | "FAIL" | "SKIPPED"
    confidence: float = 0.0
    issues: list[dict[str, Any]] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "result": self.result,
            "confidence": self.confidence,
            "issues": list(self.issues),
            "rationale": self.rationale,
        }


@dataclass(slots=True)
class AssertionResult:
    """Combined verdict after Layer 1 + Layer 2 are merged.

    ``status`` is the overall test case status (passed/failed/warning/skipped).
    ``functional`` and ``ui`` hold the per-layer detail.
    """

    status: str
    confidence: float
    errors: list[str] = field(default_factory=list)
    visual_issues: list[str] = field(default_factory=list)
    functional: FunctionalResult | None = None
    ui: UIResult | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "confidence": self.confidence,
            "errors": list(self.errors),
            "visualIssues": list(self.visual_issues),
            "functional": self.functional.to_dict() if self.functional else None,
            "ui": self.ui.to_dict() if self.ui else None,
        }


@dataclass(slots=True)
class FailureAnalysis:
    category: str
    root_cause: str
    evidence: list[str] = field(default_factory=list)
    contributing: list[dict[str, Any]] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "rootCause": self.root_cause,
            "evidence": list(self.evidence),
            "contributing": [dict(item) for item in self.contributing],
            "scores": dict(self.scores),
        }


@dataclass(slots=True)
class TestCaseResult:
    test_case_id: str
    req_id: str
    story: str
    status: str
    failure_type: str | None
    confidence: float
    steps: list[StepEvidence]
    errors: list[str] = field(default_factory=list)
    visual_issues: list[str] = field(default_factory=list)
    ac_id: str | None = None
    functional_result: FunctionalResult | None = None
    ui_result: UIResult | None = None
    failure_analysis: FailureAnalysis | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "testCaseId": self.test_case_id,
            "reqId": self.req_id,
            "acId": self.ac_id,
            "story": self.story,
            "status": self.status,
            "failureType": self.failure_type,
            "confidence": self.confidence,
            "steps": [step.to_dict() for step in self.steps],
            "errors": list(self.errors),
            "visualIssues": list(self.visual_issues),
            "functionalResult": (
                self.functional_result.to_dict() if self.functional_result else None
            ),
            "uiResult": self.ui_result.to_dict() if self.ui_result else None,
            "failureAnalysis": (
                self.failure_analysis.to_dict() if self.failure_analysis else None
            ),
        }
