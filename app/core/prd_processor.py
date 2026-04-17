from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.config import Settings
from app.models.test_case import (
    AcceptanceCriterion,
    PRDDocument,
    Requirement,
    UserStory,
)

LOGGER = logging.getLogger(__name__)


class PRDProcessor:
    """Loads and validates sage-loop PRD JSON documents.

    The v0.2 agent only accepts JSON PRDs. A single run targets one user
    story identified by its id (for example ``R-01.US-01``).
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def load_document(
        self,
        *,
        prd_json: dict[str, Any] | None,
        prd_content: str | None,
        prd_path: str | None,
    ) -> PRDDocument:
        payload = self._read_payload(
            prd_json=prd_json, prd_content=prd_content, prd_path=prd_path
        )
        return _parse_prd(payload)

    def select_story(
        self, document: PRDDocument, user_story_id: str
    ) -> tuple[Requirement, UserStory]:
        requirement, story = document.find_story(user_story_id)
        LOGGER.info(
            "Selected user story %s from requirement %s (%s acceptance criteria)",
            story.story_id,
            requirement.req_id,
            len(story.acceptance_criteria),
        )
        return requirement, story

    def build_rtm(
        self, requirement: Requirement, story: UserStory
    ) -> list[dict[str, Any]]:
        return [
            {
                "reqId": requirement.req_id,
                "reqName": requirement.name,
                "feature": requirement.feature,
                "description": requirement.description,
                "storyId": story.story_id,
                "storyTitle": story.title,
                "priority": story.priority,
                "acceptanceCriteria": [ac.to_dict() for ac in story.acceptance_criteria],
            }
        ]

    def _read_payload(
        self,
        *,
        prd_json: dict[str, Any] | None,
        prd_content: str | None,
        prd_path: str | None,
    ) -> dict[str, Any]:
        if prd_json is not None:
            if not isinstance(prd_json, dict):
                raise ValueError("prd_json must be a JSON object.")
            return prd_json

        if prd_content and prd_content.strip():
            return _loads(prd_content)

        if not prd_path:
            raise ValueError("One of prd_json, prd_content, or prd_path is required.")

        path = Path(prd_path)
        if not path.is_absolute():
            path = self.settings.workspace_root / path
        path = path.resolve()

        if (
            self.settings.workspace_root not in path.parents
            and path != self.settings.workspace_root
        ):
            raise ValueError("prd_path must be inside the configured workspace.")
        if not path.exists():
            raise FileNotFoundError(f"PRD file not found: {path}")
        if path.suffix.lower() != ".json":
            raise ValueError(
                f"Unsupported PRD file type {path.suffix!r}. Only .json is supported."
            )

        LOGGER.info("Loading PRD JSON from %s", path)
        return _loads(path.read_text(encoding="utf-8"))


def _loads(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"PRD content is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("PRD JSON must be an object.")
    return data


def _parse_prd(payload: dict[str, Any]) -> PRDDocument:
    project = _require_str(payload, "project")
    version = _require_str(payload, "version")
    schema = str(payload.get("$schema") or "sage-loop-prd-v1")

    raw_requirements = payload.get("requirements")
    if not isinstance(raw_requirements, list) or not raw_requirements:
        raise ValueError("PRD JSON must include a non-empty 'requirements' array.")

    requirements = [_parse_requirement(item) for item in raw_requirements]

    return PRDDocument(
        project=project,
        version=version,
        schema=schema,
        pipeline_config=dict(payload.get("pipelineConfig") or {}),
        design_review_policy=dict(payload.get("designReviewPolicy") or {}),
        requirements=requirements,
    )


def _parse_requirement(raw: Any) -> Requirement:
    if not isinstance(raw, dict):
        raise ValueError("Every requirement must be a JSON object.")
    req_id = _require_str(raw, "id")
    user_stories_raw = raw.get("userStories")
    if not isinstance(user_stories_raw, list) or not user_stories_raw:
        raise ValueError(f"Requirement {req_id} must contain at least one userStory.")
    return Requirement(
        req_id=req_id,
        name=str(raw.get("name") or req_id),
        feature=str(raw.get("feature") or ""),
        description=str(raw.get("description") or ""),
        security_flags=[str(flag) for flag in raw.get("securityFlags") or []],
        user_stories=[_parse_user_story(item) for item in user_stories_raw],
    )


def _parse_user_story(raw: Any) -> UserStory:
    if not isinstance(raw, dict):
        raise ValueError("Every userStory must be a JSON object.")
    story_id = _require_str(raw, "id")
    criteria_raw = raw.get("acceptanceCriteria")
    if not isinstance(criteria_raw, list) or not criteria_raw:
        raise ValueError(
            f"User story {story_id} must contain at least one acceptance criterion."
        )
    return UserStory(
        story_id=story_id,
        title=str(raw.get("title") or story_id),
        description=str(raw.get("description") or ""),
        priority=_coerce_int(raw.get("priority"), default=2),
        depends_on=[str(item) for item in raw.get("dependsOn") or []],
        context_hints=[str(item) for item in raw.get("contextHints") or []],
        design_images=[str(item) for item in raw.get("designImages") or []],
        design_fallback_stories=[
            str(item) for item in raw.get("designFallbackStories") or []
        ],
        design_review_required=bool(raw.get("designReviewRequired") or False),
        notes=str(raw.get("notes") or ""),
        acceptance_criteria=[_parse_ac(item) for item in criteria_raw],
    )


def _parse_ac(raw: Any) -> AcceptanceCriterion:
    if not isinstance(raw, dict):
        raise ValueError("Every acceptanceCriteria entry must be a JSON object.")
    return AcceptanceCriterion(
        ac_id=_require_str(raw, "id"),
        description=str(raw.get("description") or ""),
        test_type=str(raw.get("testType") or "integration"),
    )


def _require_str(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing required string field '{key}'.")
    return value.strip()


def _coerce_int(value: Any, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return default
