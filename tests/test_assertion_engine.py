from __future__ import annotations

from pathlib import Path

from app.core.assertion_engine import AssertionEngine
from app.integrations.browser_use_client import BrowserExecution
from app.integrations.vlm_client import LayerVerdict, VLMClient
from app.models.test_case import TestCase as ModelTestCase
from app.models.test_case import TestStep as ModelTestStep


_ONE_PIXEL_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x04\x00\x00\x00\xb5\x1c\x0c\x02"
    b"\x00\x00\x00\x0bIDATx\xdac\xfc\xff\x1f\x00\x03\x03"
    b"\x02\x00\xef\xbf\xa7\xdb\x00\x00\x00\x00IEND\xaeB`\x82"
)


class FakeVLM(VLMClient):
    def assert_visual(
        self, *, expected: str, screenshot_path: str | None
    ) -> LayerVerdict:
        return LayerVerdict(status="warning", confidence=0.3)


def test_placeholder_screenshot_fails_functional_assertion(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    screenshot.write_bytes(_ONE_PIXEL_PNG)
    test_case = ModelTestCase(
        test_case_id="TC-001",
        req_id="R-01",
        story_id="R-01.US-01",
        ac_id="R-01.US-01.AC-01",
        story="Story",
        expected="Dashboard visible",
        test_type="integration",
        steps=[ModelTestStep(order=1, instruction="Open page", expected="Loaded")],
    )
    execution = BrowserExecution(
        status="passed",
        current_url="https://example.test",
        screenshot_path=screenshot,
        dom_snapshot="<main>Dashboard visible</main>",
    )

    result = AssertionEngine(FakeVLM()).assert_test_case(
        test_case=test_case,
        execution=execution,
    )

    assert result.status == "failed"
    assert "Browser execution did not capture a real screenshot." in result.errors
    assert "Functional: placeholder-screenshot" in result.visual_issues
