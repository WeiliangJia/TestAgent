from __future__ import annotations

import asyncio
from collections import defaultdict
from pathlib import Path

from app.analyzer.lightweight_analyzer import LightweightAnalyzer
from app.api.schemas import Credentials
from app.config import Settings
from app.core.assertion_engine import AssertionEngine
from app.core.evidence_collector import EvidenceCollector
from app.integrations.browser_use_client import BrowserUseClient
from app.integrations.vlm_client import build_vlm_client
from app.memory import MemorySystem, RuntimeMemory
from app.models.evidence import TestCaseResult
from app.models.test_case import TestCase


class ProjectSemaphoreRegistry:
    def __init__(self, per_project_limit: int) -> None:
        self.per_project_limit = per_project_limit
        self._semaphores: dict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(per_project_limit)
        )

    def get(self, project_id: str) -> asyncio.Semaphore:
        return self._semaphores[project_id]


class TestRunner:
    def __init__(
        self,
        settings: Settings,
        semaphore_registry: ProjectSemaphoreRegistry,
        memory: MemorySystem,
    ) -> None:
        self.settings = settings
        self.memory = memory
        self.browser = BrowserUseClient(settings)
        self.evidence_collector = EvidenceCollector(settings.evidence_dir)
        self.vlm = build_vlm_client(settings.vlm_provider, settings.vlm_model)
        self.assertion_engine = AssertionEngine(
            self.vlm, warning_threshold=settings.assertion_warning_threshold
        )
        self.analyzer = LightweightAnalyzer()
        self.semaphore_registry = semaphore_registry

    async def run_all(
        self,
        *,
        project_id: str,
        test_id: str,
        target_url: str,
        test_cases: list[TestCase],
        credentials: Credentials | None,
        runtime: RuntimeMemory,
    ) -> list[TestCaseResult]:
        semaphore = self.semaphore_registry.get(project_id)
        prompt_context = self.memory.to_prompt_context(
            project_id=project_id, runtime=runtime
        )
        tasks = [
            self._run_one(
                semaphore=semaphore,
                project_id=project_id,
                test_id=test_id,
                target_url=target_url,
                test_case=test_case,
                credentials=credentials,
                runtime=runtime,
                prompt_context=prompt_context,
            )
            for test_case in test_cases
        ]
        return await asyncio.gather(*tasks)

    async def _run_one(
        self,
        *,
        semaphore: asyncio.Semaphore,
        project_id: str,
        test_id: str,
        target_url: str,
        test_case: TestCase,
        credentials: Credentials | None,
        runtime: RuntimeMemory,
        prompt_context: str,
    ) -> TestCaseResult:
        async with semaphore:
            screenshot_path = self._screenshot_path(
                project_id, test_id, test_case.test_case_id
            )
            execution = await self.browser.execute_test_case(
                project_id=project_id,
                test_id=test_id,
                target_url=target_url,
                test_case=test_case,
                screenshot_path=screenshot_path,
                credentials=credentials,
                prompt_context=prompt_context,
            )
            evidence = self.evidence_collector.persist(
                project_id=project_id,
                test_id=test_id,
                test_case=test_case,
                execution=execution,
            )
            assertion = self.assertion_engine.assert_test_case(
                test_case=test_case, execution=execution
            )
            failure_type = self.analyzer.classify(
                evidence=evidence, assertion=assertion
            )
            status = "passed" if assertion.status == "passed" else "failed"
            if assertion.status == "warning":
                status = "warning"

            runtime.record(
                f"{test_case.test_case_id}: {status} "
                f"(conf={assertion.confidence:.2f}, failure_type={failure_type})"
            )

            return TestCaseResult(
                test_case_id=test_case.test_case_id,
                req_id=test_case.req_id,
                story=test_case.story,
                status=status,
                failure_type=failure_type,
                confidence=assertion.confidence,
                steps=[evidence],
                errors=assertion.errors,
                visual_issues=assertion.visual_issues,
            )

    def _screenshot_path(
        self, project_id: str, test_id: str, test_case_id: str
    ) -> Path:
        return (
            self.settings.screenshot_dir / project_id / test_id / f"{test_case_id}.png"
        )
