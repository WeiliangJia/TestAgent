from __future__ import annotations

import asyncio
import logging
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
from app.models.evidence import (
    FunctionalResult,
    StepEvidence,
    TestCaseResult,
    UIResult,
)
from app.models.test_case import TestCase

LOGGER = logging.getLogger(__name__)


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
            self.vlm,
            warning_threshold=settings.assertion_warning_threshold,
            skip_visual=settings.skip_visual_tests,
        )
        self.analyzer = LightweightAnalyzer(
            low_confidence_threshold=settings.analyzer_low_confidence_threshold,
            aggregation_min_cases=settings.analyzer_aggregation_min_cases,
        )
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
        LOGGER.info(
            "Running %s test cases for project_id=%s test_id=%s target_url=%s",
            len(test_cases),
            project_id,
            test_id,
            target_url,
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
        results = await asyncio.gather(*tasks)
        self.analyzer.aggregate_run(results)
        return results

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
        # Skip decision does not need the semaphore or the timeout budget.
        if self._should_skip(test_case):
            LOGGER.info(
                "Skipping %s because UI-only ACs are deferred (test_type=%s)",
                test_case.test_case_id,
                test_case.test_type,
            )
            runtime.record(
                f"{test_case.test_case_id}: skipped (visual AC deferred, ac={test_case.ac_id})"
            )
            return _skipped_visual_result(test_case=test_case)

        async with semaphore:
            LOGGER.info(
                "Starting test case %s (%s) for test_id=%s",
                test_case.test_case_id,
                test_case.req_id,
                test_id,
            )
            timeout = self.settings.default_timeout_seconds
            try:
                return await asyncio.wait_for(
                    self._execute_case(
                        project_id=project_id,
                        test_id=test_id,
                        target_url=target_url,
                        test_case=test_case,
                        credentials=credentials,
                        runtime=runtime,
                        prompt_context=prompt_context,
                    ),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                LOGGER.warning(
                    "Test case %s timed out after %ss for test_id=%s (ac=%s, target=%s)",
                    test_case.test_case_id,
                    timeout,
                    test_id,
                    test_case.ac_id,
                    target_url,
                )
                runtime.record(
                    f"{test_case.test_case_id}: timeout after {timeout}s "
                    f"(ac={test_case.ac_id})"
                )
                return _timeout_result(
                    test_case=test_case,
                    timeout=timeout,
                    target_url=target_url,
                    analyzer=self.analyzer,
                )

    async def _execute_case(
        self,
        *,
        project_id: str,
        test_id: str,
        target_url: str,
        test_case: TestCase,
        credentials: Credentials | None,
        runtime: RuntimeMemory,
        prompt_context: str,
    ) -> TestCaseResult:
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
        failure_analysis = self.analyzer.classify(
            evidence=evidence, assertion=assertion, test_case=test_case
        )
        status = "passed" if assertion.status == "passed" else "failed"
        if assertion.status == "warning":
            status = "warning"

        runtime.record(
            f"{test_case.test_case_id}: {status} "
            f"(ac={test_case.ac_id}, conf={assertion.confidence:.2f}, "
            f"category={failure_analysis.category if failure_analysis else 'none'})"
        )
        LOGGER.info(
            "Finished test case %s status=%s confidence=%.2f category=%s screenshot=%s",
            test_case.test_case_id,
            status,
            assertion.confidence,
            failure_analysis.category if failure_analysis else "none",
            execution.screenshot_path,
        )

        result = TestCaseResult(
            test_case_id=test_case.test_case_id,
            req_id=test_case.req_id,
            story=test_case.story,
            status=status,
            failure_type=(
                failure_analysis.category if failure_analysis else None
            ),
            confidence=assertion.confidence,
            steps=[evidence],
            errors=assertion.errors,
            visual_issues=assertion.visual_issues,
            ac_id=test_case.ac_id,
            functional_result=assertion.functional,
            ui_result=assertion.ui,
            failure_analysis=failure_analysis,
        )
        if self.settings.inter_test_delay_seconds > 0:
            await asyncio.sleep(self.settings.inter_test_delay_seconds)
        return result

    def _should_skip(self, test_case: TestCase) -> bool:
        return (
            self.settings.skip_visual_tests
            and (test_case.test_type or "").lower() == "visual"
        )

    def _screenshot_path(
        self, project_id: str, test_id: str, test_case_id: str
    ) -> Path:
        return (
            self.settings.screenshot_dir / project_id / test_id / f"{test_case_id}.png"
        )


def _skipped_visual_result(*, test_case: TestCase) -> TestCaseResult:
    rationale = (
        f"Visual AC {test_case.ac_id} (test_type={test_case.test_type}) skipped: "
        "UI layer is disabled for this run (TEST_AGENT_SKIP_VISUAL_TESTS=true). "
        f"Expected outcome was: {(test_case.expected or '').strip()[:200]}"
    )
    step = StepEvidence(
        step=f"Skip {test_case.test_case_id}",
        status="skipped",
        current_url="",
        notes=[rationale],
    )
    return TestCaseResult(
        test_case_id=test_case.test_case_id,
        req_id=test_case.req_id,
        story=test_case.story,
        status="skipped",
        failure_type=None,
        confidence=0.0,
        steps=[step],
        errors=[],
        visual_issues=[],
        ac_id=test_case.ac_id,
        functional_result=FunctionalResult(
            result="SKIPPED",
            rationale=rationale,
        ),
        ui_result=UIResult(
            result="SKIPPED",
            rationale="UI layer disabled in this run",
        ),
        failure_analysis=None,
    )


def _timeout_result(
    *,
    test_case: TestCase,
    timeout: int,
    target_url: str,
    analyzer: LightweightAnalyzer,
) -> TestCaseResult:
    expected = (test_case.expected or "").strip()
    first_step = ""
    if test_case.steps:
        first_step = (test_case.steps[0].instruction or "").strip()[:120]
    message = (
        f"Per-case execution timeout fired after {timeout}s while running "
        f"test case {test_case.test_case_id} (ac={test_case.ac_id}) "
        f"against {target_url}. "
        f"First step was: {first_step or '(no steps recorded)'}. "
        f"Expected: {expected[:200] or '(none)'}. "
        "The browser-use agent did not return a verdict before the deadline — "
        "raise TEST_AGENT_TIMEOUT_SECONDS or reduce test_case scope if this recurs."
    )
    step = StepEvidence(
        step=f"Timeout {test_case.test_case_id}",
        status="timeout",
        current_url=target_url,
        notes=[message],
    )
    failure_analysis = analyzer.classify_timeout(
        test_case=test_case, message=message, target_url=target_url
    )
    return TestCaseResult(
        test_case_id=test_case.test_case_id,
        req_id=test_case.req_id,
        story=test_case.story,
        status="failed",
        failure_type=failure_analysis.category,
        confidence=0.0,
        steps=[step],
        errors=[message],
        visual_issues=[],
        ac_id=test_case.ac_id,
        functional_result=FunctionalResult(
            result="FAIL",
            rationale=message,
            errors=[message],
        ),
        ui_result=UIResult(result="SKIPPED", rationale="UI layer not reached"),
        failure_analysis=failure_analysis,
    )
