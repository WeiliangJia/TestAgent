from __future__ import annotations

import asyncio
import json
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
        prd_snapshot = _serialize_prd_source(request)
        self.store.create_run(
            project_id=request.project_id,
            test_id=test_id,
            target_url=request.target_url,
            prd_content=prd_snapshot,
        )
        LOGGER.info(
            "Created test run project_id=%s test_id=%s target_url=%s user_story=%s",
            request.project_id,
            test_id,
            request.target_url,
            request.user_story_id,
        )
        return test_id

    def run_sync_entrypoint(self, request: TestRunRequest, test_id: str) -> None:
        asyncio.run(self.run(request, test_id))

    async def run(self, request: TestRunRequest, test_id: str) -> None:
        runtime = self.memory.new_runtime(
            project_id=request.project_id, test_id=test_id
        )
        try:
            LOGGER.info(
                "Starting test run project_id=%s test_id=%s user_story=%s",
                request.project_id,
                test_id,
                request.user_story_id,
            )
            self.store.update_run(
                project_id=request.project_id, test_id=test_id, status="running"
            )
            document = self.prd_processor.load_document(
                prd_json=request.prd_json,
                prd_content=request.prd_content,
                prd_path=request.prd_path,
            )
            requirement, story = self.prd_processor.select_story(
                document, request.user_story_id
            )
            rtm = self.prd_processor.build_rtm(requirement, story)
            bdd_story = self.bdd_generator.generate_for_story(requirement, story)
            test_cases = self.test_case_generator.generate_for_story(
                requirement, story, bdd_story
            )
            LOGGER.info(
                "Prepared story %s with %s acceptance criteria → %s test cases",
                story.story_id,
                len(story.acceptance_criteria),
                len(test_cases),
            )

            runtime.put("target_url", request.target_url)
            runtime.put("project", document.project)
            runtime.put("user_story_id", story.story_id)
            runtime.put("acceptance_criteria", len(story.acceptance_criteria))
            runtime.record(
                f"Loaded PRD {document.project} v{document.version}; "
                f"running story {story.story_id} ({len(story.acceptance_criteria)} AC → "
                f"{len(test_cases)} test cases)."
            )

            self.memory.l1.remember_prd_summary(
                project_id=request.project_id,
                summary=_summarize_story(requirement, story),
                requirement_count=1,
            )

            self.store.update_run(
                project_id=request.project_id,
                test_id=test_id,
                rtm=rtm,
                stories=[bdd_story.to_dict()],
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
                document=document,
                requirement=requirement,
                user_story=story,
                rtm=rtm,
                bdd_story=bdd_story,
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
                    "userStoryId": story.story_id,
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


def _serialize_prd_source(request: TestRunRequest) -> str | None:
    if request.prd_json is not None:
        return json.dumps(request.prd_json, ensure_ascii=True)
    if request.prd_content:
        return request.prd_content
    if request.prd_path:
        return f"prdPath={request.prd_path}"
    return None


def _summarize_story(requirement, story) -> str:
    lines = [
        f"- Requirement {requirement.req_id}: {requirement.name}",
        f"- Story {story.story_id} (priority={story.priority}): {story.title}",
    ]
    for criterion in story.acceptance_criteria[:5]:
        lines.append(f"  - [{criterion.test_type}] {criterion.ac_id}: {criterion.description}")
    if len(story.acceptance_criteria) > 5:
        lines.append(f"  - …and {len(story.acceptance_criteria) - 5} more")
    return "\n".join(lines)
