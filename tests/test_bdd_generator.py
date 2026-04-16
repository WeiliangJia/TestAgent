from __future__ import annotations

from app.core.bdd_generator import BDDGenerator
from app.models.test_case import Requirement


def test_generate_bdd_story() -> None:
    generator = BDDGenerator()
    stories = generator.generate(
        [
            Requirement(
                req_id="REQ-001",
                description="User can open the dashboard.",
                acceptance_criteria=["The dashboard is visible."],
            )
        ]
    )

    assert stories[0].story_id == "STORY-001"
    assert "Scenario" in stories[0].gherkin
    assert "dashboard" in stories[0].gherkin
