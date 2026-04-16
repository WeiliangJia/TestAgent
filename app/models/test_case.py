from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Requirement:
    req_id: str
    description: str
    priority: str = "P2"
    acceptance_criteria: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BDDStory:
    story_id: str
    req_id: str
    title: str
    gherkin: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TestStep:
    order: int
    instruction: str
    expected: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TestCase:
    test_case_id: str
    req_id: str
    story_id: str
    story: str
    expected: str
    steps: list[TestStep]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["steps"] = [step.to_dict() for step in self.steps]
        return data
