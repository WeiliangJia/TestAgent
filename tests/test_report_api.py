from __future__ import annotations

import asyncio

from app.api.routes import orchestrator, store
from app.api.schemas import TestRunRequest as RunRequest


def test_sync_pipeline_returns_report() -> None:
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
