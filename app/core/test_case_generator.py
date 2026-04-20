from __future__ import annotations

from app.models.test_case import (
    BDDStory,
    Requirement,
    TestCase,
    TestStep,
    UserStory,
)


class TestCaseGenerator:
    def generate_for_story(
        self,
        requirement: Requirement,
        story: UserStory,
        bdd_story: BDDStory,
    ) -> list[TestCase]:
        test_cases: list[TestCase] = []
        for index, criterion in enumerate(story.acceptance_criteria, start=1):
            expected = criterion.description or story.description
            context_line = "; ".join(story.context_hints) if story.context_hints else ""
            steps: list[TestStep] = [
                TestStep(
                    order=1,
                    instruction="Open the target website as a normal user.",
                    expected="The website loads without a fatal browser error.",
                ),
                TestStep(
                    order=2,
                    instruction=_story_instruction(story, context_line),
                    expected=story.description or story.title,
                ),
                TestStep(
                    order=3,
                    instruction=f"Verify acceptance criterion {criterion.ac_id}: {expected}",
                    expected=expected,
                ),
            ]
            test_cases.append(
                TestCase(
                    test_case_id=f"TC-{index:03d}",
                    req_id=requirement.req_id,
                    story_id=story.story_id,
                    ac_id=criterion.ac_id,
                    story=bdd_story.gherkin,
                    expected=expected,
                    test_type=(criterion.test_type or "integration").strip() or "integration",
                    steps=steps,
                )
            )
        return test_cases


def _story_instruction(story: UserStory, context_line: str) -> str:
    instruction = f"Complete user story {story.story_id}: {story.description or story.title}"
    if context_line:
        instruction = f"{instruction} (context: {context_line})"
    if story.notes:
        instruction = f"{instruction} — notes: {story.notes}"
    return instruction
