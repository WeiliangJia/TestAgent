from __future__ import annotations

from app.models.test_case import BDDStory, Requirement


class BDDGenerator:
    def generate(self, requirements: list[Requirement]) -> list[BDDStory]:
        stories: list[BDDStory] = []
        for index, requirement in enumerate(requirements, start=1):
            title = f"Validate {requirement.req_id}"
            goal = requirement.description.rstrip(".")
            expected = requirement.acceptance_criteria[0] if requirement.acceptance_criteria else goal
            gherkin = "\n".join(
                [
                    f"Feature: {goal}",
                    "",
                    f"  Scenario: {title}",
                    "    Given I am a normal user on the target website",
                    f"    When I try to complete: {goal}",
                    f"    Then {expected}",
                ]
            )
            stories.append(
                BDDStory(
                    story_id=f"STORY-{index:03d}",
                    req_id=requirement.req_id,
                    title=title,
                    gherkin=gherkin,
                )
            )
        return stories
