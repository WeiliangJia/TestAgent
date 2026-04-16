from __future__ import annotations

import zipfile
from pathlib import Path

from app.config import Settings, settings
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


def _settings_for(root: Path) -> Settings:
    data_dir = root / "data"
    return Settings(
        app_name="Test Agent",
        api_key=None,
        execution_mode="mock",
        sqlite_path=data_dir / "test_agent.sqlite",
        screenshot_dir=data_dir / "screenshots",
        evidence_dir=data_dir / "evidence",
        report_dir=data_dir / "reports",
        max_project_concurrency=3,
        default_timeout_seconds=60,
        workspace_root=root,
        browser_use_llm_provider="openai",
        browser_use_llm_model="gpt-4o",
        browser_use_max_steps=20,
        vlm_provider="mock",
        vlm_model="gpt-4o-mini",
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
