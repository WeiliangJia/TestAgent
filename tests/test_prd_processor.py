from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import Settings
from app.core.prd_processor import PRDProcessor


def test_load_document_from_json_object(tmp_path: Path) -> None:
    processor = PRDProcessor(_settings_for(tmp_path))
    document = processor.load_document(
        prd_json=_sample_prd(), prd_content=None, prd_path=None
    )

    assert document.project == "CarSage"
    assert document.version == "1.0.0"
    assert len(document.requirements) == 1
    story = document.requirements[0].user_stories[0]
    assert story.story_id == "R-01.US-01"
    assert story.acceptance_criteria[0].ac_id == "R-01.US-01.AC-01"


def test_select_story_returns_matching_story(tmp_path: Path) -> None:
    processor = PRDProcessor(_settings_for(tmp_path))
    document = processor.load_document(
        prd_json=_sample_prd(), prd_content=None, prd_path=None
    )

    requirement, story = processor.select_story(document, "R-01.US-02")

    assert requirement.req_id == "R-01"
    assert story.title == "对话输入 UI 与双语切换"
    assert story.design_review_required is True


def test_select_story_missing_raises(tmp_path: Path) -> None:
    processor = PRDProcessor(_settings_for(tmp_path))
    document = processor.load_document(
        prd_json=_sample_prd(), prd_content=None, prd_path=None
    )

    with pytest.raises(KeyError):
        processor.select_story(document, "R-99.US-99")


def test_load_document_from_path(tmp_path: Path) -> None:
    prd_path = tmp_path / "prd.json"
    prd_path.write_text(json.dumps(_sample_prd()), encoding="utf-8")
    processor = PRDProcessor(_settings_for(tmp_path))

    document = processor.load_document(
        prd_json=None, prd_content=None, prd_path="prd.json"
    )

    assert document.project == "CarSage"


def test_load_document_rejects_non_json_extension(tmp_path: Path) -> None:
    prd_path = tmp_path / "prd.md"
    prd_path.write_text("- not json", encoding="utf-8")
    processor = PRDProcessor(_settings_for(tmp_path))

    with pytest.raises(ValueError):
        processor.load_document(prd_json=None, prd_content=None, prd_path="prd.md")


def test_load_document_requires_some_source(tmp_path: Path) -> None:
    processor = PRDProcessor(_settings_for(tmp_path))

    with pytest.raises(ValueError):
        processor.load_document(prd_json=None, prd_content=None, prd_path=None)


def test_build_rtm_surfaces_acceptance_criteria(tmp_path: Path) -> None:
    processor = PRDProcessor(_settings_for(tmp_path))
    document = processor.load_document(
        prd_json=_sample_prd(), prd_content=None, prd_path=None
    )
    requirement, story = processor.select_story(document, "R-01.US-01")

    rtm = processor.build_rtm(requirement, story)

    assert rtm[0]["reqId"] == "R-01"
    assert rtm[0]["storyId"] == "R-01.US-01"
    assert rtm[0]["acceptanceCriteria"][0]["id"] == "R-01.US-01.AC-01"


def _sample_prd() -> dict:
    return {
        "$schema": "sage-loop-prd-v1",
        "project": "CarSage",
        "version": "1.0.0",
        "pipelineConfig": {"branchPattern": "feature/{requirementId}"},
        "designReviewPolicy": {"reviewMode": "design_conformance"},
        "requirements": [
            {
                "id": "R-01",
                "name": "双语对话 — 核心对话流",
                "feature": "F1",
                "description": "用户用中文/英文聊天说需求。",
                "securityFlags": [],
                "userStories": [
                    {
                        "id": "R-01.US-01",
                        "title": "Chat API 流式对话端点",
                        "description": "作为用户，我希望与 AI 对话时获得流式响应。",
                        "priority": 1,
                        "dependsOn": [],
                        "contextHints": ["使用 Vercel AI SDK streamText"],
                        "designImages": [],
                        "designReviewRequired": False,
                        "notes": "后端故事。",
                        "acceptanceCriteria": [
                            {
                                "id": "R-01.US-01.AC-01",
                                "description": "POST /api/chat 返回 SSE 流。",
                                "testType": "integration",
                            },
                            {
                                "id": "R-01.US-01.AC-02",
                                "description": "onFinish 正确触发。",
                                "testType": "integration",
                            },
                        ],
                    },
                    {
                        "id": "R-01.US-02",
                        "title": "对话输入 UI 与双语切换",
                        "description": "作为用户，我希望看到居中大输入框。",
                        "priority": 2,
                        "dependsOn": ["R-01.US-01"],
                        "contextHints": ["输入框占 viewport 60%"],
                        "designImages": [],
                        "designReviewRequired": True,
                        "notes": "前端 UI。",
                        "acceptanceCriteria": [
                            {
                                "id": "R-01.US-02.AC-01",
                                "description": "输入框渲染居中。",
                                "testType": "visual",
                            }
                        ],
                    },
                ],
            }
        ],
    }


def _settings_for(root: Path) -> Settings:
    data_dir = root / "data"
    return Settings(
        app_name="Test Agent",
        api_key=None,
        project_keys={},
        execution_mode="browser_use",
        sqlite_path=data_dir / "test_agent.sqlite",
        screenshot_dir=data_dir / "screenshots",
        evidence_dir=data_dir / "evidence",
        report_dir=data_dir / "reports",
        max_project_concurrency=3,
        default_timeout_seconds=60,
        workspace_root=root,
        browser_use_llm_provider="glm",
        browser_use_llm_model="glm-5.1",
        browser_use_max_steps=20,
        browser_headless=True,
        vlm_provider="glm",
        vlm_model="glm-5v-turbo",
        assertion_warning_threshold=0.6,
        inter_test_delay_seconds=0.0,
        skip_visual_tests=True,
    )
