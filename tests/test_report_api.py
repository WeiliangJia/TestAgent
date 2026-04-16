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
                test_case_id=test_cases[0].test_case_id,
                req_id=test_cases[0].req_id,
                story=test_cases[0].story,
                status="passed",
                failure_type=None,
                confidence=0.9,
                steps=[
                    StepEvidence(
                        step=f"Execute {test_cases[0].test_case_id}",
                        status="passed",
                        current_url=target_url,
                    )
                ],
            )
        ]

    orchestrator.test_runner.run_all = fake_run_all
    request = RunRequest(
        projectId="demo",
        targetUrl="https://example.com",
        prdContent="- User can open the home page.",
        sync=True,
    )
    test_id = orchestrator.create_run(request)
    asyncio.run(orchestrator.run(request, test_id))

    row = store.get_run(test_id=test_id, project_id="demo")
    assert row is not None
    report = row["report"]
    assert report["projectId"] == "demo"
    assert report["summary"]["total"] == 1
    assert report["results"][0]["status"] == "passed"


def _settings_for(root: Path) -> Settings:
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
        prd_llm_provider="heuristic",
        prd_llm_model="gpt-4o",
        prd_llm_max_requirements=12,
        prd_llm_max_chars=60000,
        browser_use_llm_provider="glm",
        browser_use_llm_model="glm-5.1",
        browser_use_max_steps=20,
        vlm_provider="glm",
        vlm_model="glm-5v-turbo",
        assertion_warning_threshold=0.6,
    )
