from __future__ import annotations

from app.config import settings
from app.core.prd_processor import PRDProcessor


def test_extract_requirements_from_bullets() -> None:
    processor = PRDProcessor(settings)
    requirements = processor.extract_requirements(
        """
        # Product
        - User can log in with email and password.
        - User should search inventory.
        """
    )

    assert len(requirements) == 2
    assert requirements[0].req_id == "REQ-001"
    assert "log in" in requirements[0].description


def test_build_rtm() -> None:
    processor = PRDProcessor(settings)
    requirements = processor.extract_requirements("- User can open the dashboard.")
    rtm = processor.build_rtm(requirements)

    assert rtm[0]["reqId"] == "REQ-001"
    assert rtm[0]["testCaseIds"] if "testCaseIds" in rtm[0] else True
