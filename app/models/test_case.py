from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class AcceptanceCriterion:
    ac_id: str
    description: str
    test_type: str = "integration"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.ac_id,
            "description": self.description,
            "testType": self.test_type,
        }


@dataclass(slots=True)
class UserStory:
    story_id: str
    title: str
    description: str
    priority: int = 2
    depends_on: list[str] = field(default_factory=list)
    context_hints: list[str] = field(default_factory=list)
    design_images: list[str] = field(default_factory=list)
    design_fallback_stories: list[str] = field(default_factory=list)
    design_review_required: bool = False
    notes: str = ""
    acceptance_criteria: list[AcceptanceCriterion] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.story_id,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "dependsOn": list(self.depends_on),
            "contextHints": list(self.context_hints),
            "designImages": list(self.design_images),
            "designFallbackStories": list(self.design_fallback_stories),
            "designReviewRequired": self.design_review_required,
            "notes": self.notes,
            "acceptanceCriteria": [ac.to_dict() for ac in self.acceptance_criteria],
        }


@dataclass(slots=True)
class Requirement:
    req_id: str
    name: str
    feature: str
    description: str
    security_flags: list[str] = field(default_factory=list)
    user_stories: list[UserStory] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.req_id,
            "name": self.name,
            "feature": self.feature,
            "description": self.description,
            "securityFlags": list(self.security_flags),
            "userStories": [story.to_dict() for story in self.user_stories],
        }


@dataclass(slots=True)
class PRDDocument:
    project: str
    version: str
    schema: str = "sage-loop-prd-v1"
    pipeline_config: dict[str, Any] = field(default_factory=dict)
    design_review_policy: dict[str, Any] = field(default_factory=dict)
    requirements: list[Requirement] = field(default_factory=list)

    def find_story(self, story_id: str) -> tuple[Requirement, UserStory]:
        for requirement in self.requirements:
            for story in requirement.user_stories:
                if story.story_id == story_id:
                    return requirement, story
        raise KeyError(f"User story not found in PRD: {story_id}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "$schema": self.schema,
            "project": self.project,
            "version": self.version,
            "pipelineConfig": dict(self.pipeline_config),
            "designReviewPolicy": dict(self.design_review_policy),
            "requirements": [requirement.to_dict() for requirement in self.requirements],
        }


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
    ac_id: str
    story: str
    expected: str
    test_type: str
    steps: list[TestStep]

    def to_dict(self) -> dict[str, Any]:
        return {
            "testCaseId": self.test_case_id,
            "reqId": self.req_id,
            "storyId": self.story_id,
            "acId": self.ac_id,
            "story": self.story,
            "expected": self.expected,
            "testType": self.test_type,
            "steps": [step.to_dict() for step in self.steps],
        }
