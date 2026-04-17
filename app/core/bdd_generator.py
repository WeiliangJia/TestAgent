from __future__ import annotations

from app.models.test_case import BDDStory, Requirement, UserStory


class BDDGenerator:
    def generate_for_story(
        self, requirement: Requirement, story: UserStory
    ) -> BDDStory:
        goal = (story.description or story.title).rstrip(".")
        feature_line = requirement.name or requirement.req_id

        lines: list[str] = [
            f"Feature: {feature_line}",
            "",
            f"  Scenario: {story.title}",
            "    Given I am a user on the target website",
            f"    When I try to: {goal}",
        ]
        if story.acceptance_criteria:
            for ac in story.acceptance_criteria:
                lines.append(f"    Then {ac.description}")
        else:
            lines.append(f"    Then {goal}")

        return BDDStory(
            story_id=story.story_id,
            req_id=requirement.req_id,
            title=story.title,
            gherkin="\n".join(lines),
        )
