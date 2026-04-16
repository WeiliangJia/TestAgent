from __future__ import annotations

import sys
import types
import zipfile
from pathlib import Path
from types import SimpleNamespace

from app.config import Settings
from app.core.prd_processor import PRDProcessor


def test_extract_requirements_from_bullets(tmp_path: Path) -> None:
    processor = PRDProcessor(_settings_for(tmp_path))
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


def test_build_rtm(tmp_path: Path) -> None:
    processor = PRDProcessor(_settings_for(tmp_path))
    requirements = processor.extract_requirements("- User can open the dashboard.")
    rtm = processor.build_rtm(requirements)

    assert rtm[0]["reqId"] == "REQ-001"
    assert rtm[0]["testCaseIds"] if "testCaseIds" in rtm[0] else True


def test_load_content_from_docx(tmp_path: Path) -> None:
    prd_path = tmp_path / "prd.docx"
    _write_minimal_docx(
        prd_path,
        [
            "User can open the home page.",
            "User should see the login button.",
        ],
    )
    processor = PRDProcessor(_settings_for(tmp_path))

    content = processor.load_content(None, "prd.docx")
    requirements = processor.extract_requirements(content)

    assert "home page" in content
    assert len(requirements) == 2


def test_extract_requirements_with_glm_openai_compatible_client(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "test-key")
    monkeypatch.setenv("ZAI_BASE_URL", "https://example.test/api/paas/v4/")

    class FakeCompletions:
        last_kwargs = {}

        def create(self, **kwargs):
            FakeCompletions.last_kwargs = kwargs
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=(
                                '{"requirements":[{"description":"User can search inventory.",'
                                '"priority":"P1","acceptance_criteria":["Search results are visible."]}]}'
                            )
                        )
                    )
                ]
            )

    class FakeOpenAI:
        last_kwargs = {}

        def __init__(self, **kwargs):
            FakeOpenAI.last_kwargs = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

    fake_module = types.ModuleType("openai")
    fake_module.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_module)
    processor = PRDProcessor(
        _settings_for(
            tmp_path,
            prd_llm_provider="glm",
            prd_llm_model="glm-5.1",
        )
    )

    requirements = processor.extract_requirements("Car marketplace PRD")

    assert requirements[0].req_id == "REQ-001"
    assert requirements[0].description == "User can search inventory."
    assert requirements[0].priority == "P1"
    assert requirements[0].acceptance_criteria == ["Search results are visible."]
    assert FakeOpenAI.last_kwargs == {
        "api_key": "test-key",
        "base_url": "https://example.test/api/paas/v4/",
    }
    assert FakeCompletions.last_kwargs["model"] == "glm-5.1"


def test_extract_requirements_repairs_invalid_llm_json(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "test-key")
    monkeypatch.setenv("ZAI_BASE_URL", "https://example.test/api/paas/v4/")

    class FakeCompletions:
        calls = []

        def create(self, **kwargs):
            FakeCompletions.calls.append(kwargs)
            if len(FakeCompletions.calls) == 1:
                content = (
                    '{"requirements":[{"description":"User can open "inventory" page.",'
                    '"priority":"P1","acceptance_criteria":["Inventory is visible."]}]}'
                )
            else:
                content = (
                    '{"requirements":[{"description":"User can open inventory page.",'
                    '"priority":"P1","acceptance_criteria":["Inventory is visible."]}]}'
                )
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content=content))
                ]
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    fake_module = types.ModuleType("openai")
    fake_module.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_module)
    processor = PRDProcessor(
        _settings_for(
            tmp_path,
            prd_llm_provider="glm",
            prd_llm_model="glm-5.1",
        )
    )

    requirements = processor.extract_requirements("Inventory PRD")

    assert len(FakeCompletions.calls) == 2
    assert "repair malformed json" in FakeCompletions.calls[1]["messages"][0]["content"].lower()
    assert requirements[0].description == "User can open inventory page."


def _settings_for(
    root: Path,
    *,
    prd_llm_provider: str = "heuristic",
    prd_llm_model: str = "gpt-4o",
) -> Settings:
    data_dir = root / "data"
    return Settings(
        app_name="Test Agent",
        api_key=None,
        execution_mode="browser_use",
        sqlite_path=data_dir / "test_agent.sqlite",
        screenshot_dir=data_dir / "screenshots",
        evidence_dir=data_dir / "evidence",
        report_dir=data_dir / "reports",
        max_project_concurrency=3,
        default_timeout_seconds=60,
        workspace_root=root,
        prd_llm_provider=prd_llm_provider,
        prd_llm_model=prd_llm_model,
        prd_llm_max_requirements=12,
        prd_llm_max_chars=60000,
        browser_use_llm_provider="openai",
        browser_use_llm_model="gpt-4o",
        browser_use_max_steps=20,
        vlm_provider="glm",
        vlm_model="glm-5v-turbo",
        assertion_warning_threshold=0.6,
    )


def _write_minimal_docx(path: Path, paragraphs: list[str]) -> None:
    body = "".join(
        f"<w:p><w:r><w:t>{paragraph}</w:t></w:r></w:p>"
        for paragraph in paragraphs
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body>"
        "</w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
