from __future__ import annotations

from app.core.bdd_generator import BDDGenerator
from app.core.test_case_generator import TestCaseGenerator
from app.models.test_case import (
    AcceptanceCriterion,
    Requirement,
    UserStory,
)


def _requirement_and_story() -> tuple[Requirement, UserStory]:
    story = UserStory(
        story_id="R-01.US-01",
        title="Chat API 流式对话端点",
        description="用户与 AI 对话时获得流式响应。",
        priority=1,
        context_hints=["使用 Vercel AI SDK streamText"],
        acceptance_criteria=[
            AcceptanceCriterion(
                ac_id="R-01.US-01.AC-01",
                description="POST /api/chat 返回 SSE 流。",
                test_type="integration",
            ),
            AcceptanceCriterion(
                ac_id="R-01.US-01.AC-02",
                description="onFinish 正确触发。",
                test_type="integration",
            ),
        ],
    )
    requirement = Requirement(
        req_id="R-01",
        name="双语对话 — 核心对话流",
        feature="F1",
        description="用户用中文/英文聊天说需求。",
        user_stories=[story],
    )
    return requirement, story


def test_generate_bdd_story_for_single_user_story() -> None:
    requirement, story = _requirement_and_story()
    bdd = BDDGenerator().generate_for_story(requirement, story)

    assert bdd.story_id == "R-01.US-01"
    assert bdd.req_id == "R-01"
    assert "Scenario: Chat API 流式对话端点" in bdd.gherkin
    assert "POST /api/chat 返回 SSE 流" in bdd.gherkin
    assert "onFinish 正确触发" in bdd.gherkin


def test_generate_test_cases_from_acceptance_criteria() -> None:
    requirement, story = _requirement_and_story()
    bdd = BDDGenerator().generate_for_story(requirement, story)

    cases = TestCaseGenerator().generate_for_story(requirement, story, bdd)

    assert len(cases) == 2
    assert cases[0].test_case_id == "TC-001"
    assert cases[0].ac_id == "R-01.US-01.AC-01"
    assert cases[0].story_id == "R-01.US-01"
    assert cases[0].req_id == "R-01"
    assert cases[0].test_type == "integration"
    assert any(
        "使用 Vercel AI SDK streamText" in step.instruction
        for step in cases[0].steps
    )
