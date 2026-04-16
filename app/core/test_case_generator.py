from __future__ import annotations

from app.models.test_case import BDDStory, Requirement, TestCase, TestStep


class TestCaseGenerator:
    def generate(
        self, requirements: list[Requirement], stories: list[BDDStory]
    ) -> list[TestCase]:
        by_req_id = {item.req_id: item for item in requirements}
        test_cases: list[TestCase] = []

        for index, story in enumerate(stories, start=1):
            requirement = by_req_id[story.req_id]
            expected = (
                requirement.acceptance_criteria[0]
                if requirement.acceptance_criteria
                else requirement.description
            )
            steps = [
                TestStep(
                    order=1,
                    instruction="Open the target website as a normal user.",
                    expected="The website loads without a fatal browser error.",
                ),
                TestStep(
                    order=2,
                    instruction=f"Complete the user goal: {requirement.description}",
                    expected=expected,
                ),
                TestStep(
                    order=3,
                    instruction=f"Verify the visible result for: {requirement.description}",
                    expected=expected,
                ),
            ]
            test_cases.append(
                TestCase(
                    test_case_id=f"TC-{index:03d}",
                    req_id=requirement.req_id,
                    story_id=story.story_id,
                    story=story.gherkin,
                    expected=expected,
                    steps=steps,
                )
            )
        return test_cases
