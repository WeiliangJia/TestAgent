from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from app.api.auth import require_api_key
from app.api.schemas import HealthResponse, TestRunCreated, TestRunRequest
from app.config import settings
from app.core.orchestrator import Orchestrator
from app.storage.sqlite import SQLiteStore

router = APIRouter(dependencies=[Depends(require_api_key)])
store = SQLiteStore(settings.sqlite_path)
settings.ensure_dirs()
store.initialize()
orchestrator = Orchestrator(store=store, settings=settings)


@router.get("/health", response_model=HealthResponse, dependencies=[])
async def health() -> HealthResponse:
    return HealthResponse(status="ok", executionMode=settings.execution_mode)


@router.post("/test/run", response_model=TestRunCreated)
async def create_test_run(
    request: TestRunRequest, background_tasks: BackgroundTasks
) -> TestRunCreated:
    if not request.prd_content and not request.prd_path:
        raise HTTPException(
            status_code=400,
            detail="Either prdContent or prdPath is required.",
        )

    test_id = orchestrator.create_run(request)
    if request.sync:
        await orchestrator.run(request, test_id)
    else:
        background_tasks.add_task(orchestrator.run_sync_entrypoint, request, test_id)

    return TestRunCreated(
        projectId=request.project_id,
        testId=test_id,
        status="queued",
        reportUrl=f"/test/report/{test_id}?project_id={request.project_id}",
    )


@router.get("/test/report/{test_id}")
async def get_test_report(
    test_id: str, project_id: str | None = Query(default=None)
) -> dict:
    row = store.get_run(test_id=test_id, project_id=project_id)
    if not row:
        raise HTTPException(status_code=404, detail="Test run not found.")
    if row.get("report"):
        return row["report"]
    return {
        "projectId": row["project_id"],
        "testId": row["test_id"],
        "status": row["status"],
        "error": row.get("error"),
    }
