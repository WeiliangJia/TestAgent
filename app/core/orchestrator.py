from __future__ import annotations

import asyncio
import logging
import uuid

from app.api.schemas import TestRunRequest
from app.config import Settings
from app.core.bdd_generator import BDDGenerator
from app.core.prd_processor import PRDProcessor
from app.core.report_generator import ReportGenerator
from app.core.test_case_generator import TestCaseGenerator
from app.core.test_runner import ProjectSemaphoreRegistry, TestRunner
from app.memory import MemorySystem
from app.storage.sqlite import SQLiteStore

LOGGER = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, *, store: SQLiteStore, settings: Settings) -> None:
        self.store = store
        self.settings = settings
        self.memory = MemorySystem(sqlite_path=settings.sqlite_path)
        self.memory.initialize()
        self.prd_processor = PRDProcessor(settings)
        self.bdd_generator = BDDGenerator()
        self.test_case_generator = TestCaseGenerator()
        self.semaphore_registry = ProjectSemaphoreRegistry(
            settings.max_project_concurrency
        )
        self.test_runner = TestRunner(
            settings, self.semaphore_registry, self.memory
        )
        self.report_generator = ReportGenerator(settings.report_dir)

    def create_run(self, request: TestRunRequest) -> str:
        test_id = f"test_{uuid.uuid4().hex[:12]}"
        prd_content = None
        if request.prd_content:
            prd_content = request.prd_content
        self.store.create_run(
            project_id=request.project_id,
            test_id=test_id,
            target_url=request.target_url,
            prd_content=prd_content,
        )
        LOGGER.info(
            "Created test run project_id=%s test_id=%s target_url=%s",
            request.project_id,
            test_id,
            request.target_url,
        )
        return test_id

    def run_sync_entrypoint(self, request: TestRunRequest, test_id: str) -> None:
        asyncio.run(self.run(request, test_id))

    async def run(self, request: TestRunRequest, test_id: str) -> None:
        runtime = self.memory.new_runtime(
            project_id=request.project_id, test_id=test_id
        )
        try:
            LOGGER.info("Starting test run project_id=%s test_id=%s", request.project_id, test_id)
            self.store.update_run(
                project_id=request.project_id, test_id=test_id, status="running"
            )
            prd_content = self.prd_processor.load_content(
                request.prd_content, request.prd_path
            )
            LOGGER.info(
                "Loaded PRD for test_id=%s (%s characters)",
                test_id,
                len(prd_content),
            )
            runtime.put("target_url", request.target_url)
            runtime.put("prd_size", len(prd_content))

            requirements = self.prd_processor.extract_requirements(prd_content)
            rtm = self.prd_processor.build_rtm(requirements)
            stories = self.bdd_generator.generate(requirements)
            test_cases = self.test_case_generator.generate(requirements, stories)
            LOGGER.info(
                "Generated %s requirements, %s stories, %s test cases for test_id=%s",
                len(requirements),
                len(stories),
                len(test_cases),
                test_id,
            )

            runtime.record(
                f"Parsed {len(requirements)} requirements → "
                f"{len(stories)} stories → {len(test_cases)} test cases."
            )
            self.memory.l1.remember_prd_summary(
                project_id=request.project_id,
                summary=_summarize_prd(requirements),
                requirement_count=len(requirements),
            )

            self.store.update_run(
                project_id=request.project_id,
                test_id=test_id,
                rtm=rtm,
                stories=[story.to_dict() for story in stories],
                test_cases=[case.to_dict() for case in test_cases],
            )

            results = await self.test_runner.run_all(
                project_id=request.project_id,
                test_id=test_id,
                target_url=request.target_url,
                test_cases=test_cases,
                credentials=request.credentials,
                runtime=runtime,
            )
            report = self.report_generator.generate(
                project_id=request.project_id,
                test_id=test_id,
                target_url=request.target_url,
                rtm=rtm,
                stories=stories,
                test_cases=test_cases,
                results=results,
            )

            self.memory.l1.remember_run(
                project_id=request.project_id,
                test_id=test_id,
                digest={
                    "status": report["status"],
                    "summary": report["summary"],
                    "targetUrl": request.target_url,
                },
            )

            self.store.update_run(
                project_id=request.project_id,
                test_id=test_id,
                status=report["status"],
                results=[result.to_dict() for result in results],
                evidence={
                    "memory": self.memory.snapshot(
                        project_id=request.project_id, runtime=runtime
                    )
                },
                report=report,
            )
            LOGGER.info(
                "Completed test run project_id=%s test_id=%s status=%s report=%s",
                request.project_id,
                test_id,
                report["status"],
                report.get("reportPath"),
            )
        except Exception as exc:
            LOGGER.exception(
                "Test run failed project_id=%s test_id=%s",
                request.project_id,
                test_id,
            )
            self.store.update_run(
                project_id=request.project_id,
                test_id=test_id,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )


def _summarize_prd(requirements: list) -> str:
    if not requirements:
        return "(empty)"
    lines = [f"- [{req.priority}] {req.description}" for req in requirements[:5]]
    if len(requirements) > 5:
        lines.append(f"- …and {len(requirements) - 5} more")
    return "\n".join(lines)
