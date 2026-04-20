from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from app.api.auth import AuthContext, require_api_key
from app.api.schemas import HealthResponse, TestRunCreated, TestRunRequest
from app.config import settings
from app.core.orchestrator import Orchestrator
from app.storage.sqlite import SQLiteStore

router = APIRouter()
store = SQLiteStore(settings.sqlite_path)
settings.ensure_dirs()
store.initialize()
orchestrator = Orchestrator(store=store, settings=settings)


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", executionMode=settings.execution_mode)


@router.post("/test/run", response_model=TestRunCreated)
async def create_test_run(
    request: TestRunRequest,
    background_tasks: BackgroundTasks,
    auth: AuthContext = Depends(require_api_key),
) -> TestRunCreated:
    if request.prd_json is None and not request.prd_content and not request.prd_path:
        raise HTTPException(
            status_code=400,
            detail="One of prdJson, prdContent, or prdPath is required.",
        )

    resolved = _resolve_project_id(request=request, auth=auth)
    request = request.model_copy(update={"project_id": resolved})

    test_id = orchestrator.create_run(request)
    if request.sync:
        await orchestrator.run(request, test_id)
    else:
        background_tasks.add_task(orchestrator.run_sync_entrypoint, request, test_id)

    return TestRunCreated(
        projectId=request.project_id,
        testId=test_id,
        userStoryId=request.user_story_id,
        status="queued",
        reportUrl=f"/test/report/{test_id}?project_id={request.project_id}",
    )


@router.get("/test/report/{test_id}")
async def get_test_report(
    test_id: str,
    project_id: str | None = Query(default=None),
    auth: AuthContext = Depends(require_api_key),
) -> dict:
    resolved_project = auth.project_id or project_id
    if auth.project_id and project_id and project_id != auth.project_id:
        raise HTTPException(
            status_code=403,
            detail="project_id does not match the project bound to this API key.",
        )
    row = store.get_run(test_id=test_id, project_id=resolved_project)
    if not row:
        raise HTTPException(status_code=404, detail="Test run not found.")
    if auth.project_id and row.get("project_id") != auth.project_id:
        raise HTTPException(
            status_code=403,
            detail="Test run does not belong to the project bound to this API key.",
        )
    if row.get("report"):
        return row["report"]
    return {
        "projectId": row["project_id"],
        "testId": row["test_id"],
        "status": row["status"],
        "error": row.get("error"),
    }


def _resolve_project_id(*, request: TestRunRequest, auth: AuthContext) -> str:
    if auth.project_id:
        if request.project_id and request.project_id != auth.project_id:
            raise HTTPException(
                status_code=403,
                detail="projectId in body does not match the project bound to this API key.",
            )
        return auth.project_id
    if not request.project_id:
        raise HTTPException(
            status_code=422,
            detail="projectId is required when PROJECT_KEYS is not configured.",
        )
    return request.project_id
