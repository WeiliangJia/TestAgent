from __future__ import annotations

import asyncio
from pathlib import Path

from app.api.schemas import Credentials
from app.api.schemas import TestRunRequest as RunRequest
from app.config import Settings
from app.core.orchestrator import Orchestrator
from app.memory import RuntimeMemory
from app.models.evidence import StepEvidence, TestCaseResult as AgentTestCaseResult
from app.models.test_case import TestCase as AgentTestCase
from app.storage.sqlite import SQLiteStore


def test_sync_pipeline_returns_report(tmp_path: Path) -> None:
    settings = _settings_for(tmp_path)
    store = SQLiteStore(settings.sqlite_path)
    store.initialize()
    orchestrator = Orchestrator(store=store, settings=settings)

    async def fake_run_all(
        *,
        project_id: str,
        test_id: str,
        target_url: str,
        test_cases: list[AgentTestCase],
        credentials: Credentials | None,
        runtime: RuntimeMemory,
    ) -> list[AgentTestCaseResult]:
        return [
            AgentTestCaseResult(
                test_case_id=case.test_case_id,
                req_id=case.req_id,
                story=case.story,
                status="passed",
                failure_type=None,
                confidence=0.9,
                steps=[
                    StepEvidence(
                        step=f"Execute {case.test_case_id}",
                        status="passed",
                        current_url=target_url,
                    )
                ],
            )
            for case in test_cases
        ]

    orchestrator.test_runner.run_all = fake_run_all
    request = RunRequest(
        projectId="demo",
        targetUrl="https://example.com",
        userStoryId="R-01.US-01",
        prdJson=_sample_prd(),
        sync=True,
    )
    test_id = orchestrator.create_run(request)
    asyncio.run(orchestrator.run(request, test_id))

    row = store.get_run(test_id=test_id, project_id="demo")
    assert row is not None
    report = row["report"]
    assert report["projectId"] == "demo"
    assert report["userStory"]["id"] == "R-01.US-01"
    assert report["prdProject"] == "CarSage"
    assert report["summary"]["total"] == 2
    assert report["results"][0]["status"] == "passed"


def _sample_prd() -> dict:
    return {
        "$schema": "sage-loop-prd-v1",
        "project": "CarSage",
        "version": "1.0.0",
        "pipelineConfig": {},
        "designReviewPolicy": {},
        "requirements": [
            {
                "id": "R-01",
                "name": "双语对话",
                "feature": "F1",
                "description": "核心对话流",
                "userStories": [
                    {
                        "id": "R-01.US-01",
                        "title": "Chat API 流式对话端点",
                        "description": "用户与 AI 对话时获得流式响应。",
                        "priority": 1,
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
                    }
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
