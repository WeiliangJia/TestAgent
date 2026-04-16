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
class AssertionResult:
    status: str
    confidence: float
    errors: list[str] = field(default_factory=list)
    visual_issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "testCaseId": self.test_case_id,
            "reqId": self.req_id,
            "story": self.story,
            "status": self.status,
            "failureType": self.failure_type,
            "confidence": self.confidence,
            "steps": [step.to_dict() for step in self.steps],
            "errors": self.errors,
            "visualIssues": self.visual_issues,
        }
