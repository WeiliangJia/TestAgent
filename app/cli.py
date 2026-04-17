from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Sequence


LOGGER = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "serve":
        return _serve(args)
    if args.command == "run":
        return _run(args)
    parser.print_help()
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="test-agent",
        description=(
            "Run the Test Agent service or execute one user story from a JSON PRD."
        ),
    )
    subparsers = parser.add_subparsers(dest="command")

    serve = subparsers.add_parser("serve", help="Start the FastAPI service.")
    serve.add_argument("--host", default=os.getenv("TEST_AGENT_HOST", "127.0.0.1"))
    serve.add_argument(
        "--port", type=int, default=int(os.getenv("TEST_AGENT_PORT", "8000"))
    )
    serve.add_argument("--no-reload", action="store_true")
    _add_runtime_overrides(serve)

    run = subparsers.add_parser(
        "run",
        help="Run a single user story from a JSON PRD (no curl required).",
    )
    run.add_argument("--project-id", default=os.getenv("TEST_AGENT_PROJECT_ID", "local-demo"))
    run.add_argument("--target-url", default=None)
    run.add_argument(
        "--prd",
        default=None,
        help=(
            "Path to a sage-loop PRD JSON file (relative paths resolve against the "
            "TestAgent directory). Defaults to prd.json."
        ),
    )
    run.add_argument(
        "--user-story",
        default=os.getenv("TEST_AGENT_USER_STORY_ID"),
        help="User story id to execute, e.g. R-01.US-01.",
    )
    run.add_argument("--json", action="store_true", help="Print the full report JSON.")
    _add_runtime_overrides(run)
    return parser


def _add_runtime_overrides(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--mode",
        choices=["browser_use"],
        help="Override TEST_AGENT_EXECUTION_MODE.",
    )
    parser.add_argument(
        "--vlm",
        choices=["openai", "anthropic", "glm"],
        help="Override TEST_AGENT_VLM_PROVIDER.",
    )
    parser.add_argument("--vlm-model", help="Override TEST_AGENT_VLM_MODEL.")


def _apply_runtime_overrides(args: argparse.Namespace) -> None:
    if getattr(args, "mode", None):
        os.environ["TEST_AGENT_EXECUTION_MODE"] = args.mode
    if getattr(args, "vlm", None):
        os.environ["TEST_AGENT_VLM_PROVIDER"] = args.vlm
    if getattr(args, "vlm_model", None):
        os.environ["TEST_AGENT_VLM_MODEL"] = args.vlm_model


def _serve(args: argparse.Namespace) -> int:
    _apply_runtime_overrides(args)
    import uvicorn

    from app.config import settings

    settings.require_real_integrations()
    LOGGER.info(
        "Starting Test Agent service on http://%s:%s (mode=%s, vlm=%s/%s)",
        args.host,
        args.port,
        settings.execution_mode,
        settings.vlm_provider,
        settings.vlm_model,
    )
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=not args.no_reload,
    )
    return 0


def _run(args: argparse.Namespace) -> int:
    _apply_runtime_overrides(args)

    from app.api.schemas import TestRunRequest
    from app.config import settings
    from app.core.orchestrator import Orchestrator
    from app.storage.sqlite import SQLiteStore

    settings.require_real_integrations()
    target_url = args.target_url or os.getenv("TEST_AGENT_TARGET_URL")
    if not target_url:
        raise SystemExit(
            "Missing target URL. Use --target-url or set TEST_AGENT_TARGET_URL in .env."
        )

    user_story_id = args.user_story
    if not user_story_id:
        raise SystemExit(
            "Missing user story id. Use --user-story or set TEST_AGENT_USER_STORY_ID."
        )

    prd_path = _resolve_prd_path(args.prd, settings.workspace_root)
    settings.ensure_dirs()
    store = SQLiteStore(settings.sqlite_path)
    store.initialize()
    orchestrator = Orchestrator(store=store, settings=settings)
    request = TestRunRequest(
        projectId=args.project_id,
        targetUrl=target_url,
        userStoryId=user_story_id,
        prdPath=str(prd_path),
        sync=True,
    )

    LOGGER.info(
        "Running user story %s project_id=%s target_url=%s prd=%s mode=%s vlm=%s/%s",
        user_story_id,
        args.project_id,
        target_url,
        prd_path,
        settings.execution_mode,
        settings.vlm_provider,
        settings.vlm_model,
    )
    test_id = orchestrator.create_run(request)
    asyncio.run(orchestrator.run(request, test_id))
    row = store.get_run(test_id=test_id, project_id=args.project_id)
    if not row:
        raise SystemExit(f"Test run disappeared: {test_id}")

    report = row.get("report")
    if args.json and report:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print_summary(row, user_story_id)
    return 1 if row.get("status") == "failed" else 0


def _resolve_prd_path(prd_arg: str | None, workspace_root: Path) -> Path:
    if prd_arg:
        path = Path(prd_arg)
        if not path.is_absolute():
            path = workspace_root / path
        return path.resolve()

    env_path = os.getenv("TEST_AGENT_PRD_PATH")
    if env_path:
        return _resolve_prd_path(env_path, workspace_root)

    for name in ("prd.json", "PRD.json"):
        candidate = workspace_root / name
        if candidate.exists():
            return candidate.resolve()
    raise SystemExit(
        "No PRD JSON file found. Put prd.json in the TestAgent directory or pass "
        "--prd path/to/prd.json."
    )


def _print_summary(row: dict, user_story_id: str) -> None:
    report = row.get("report") or {}
    summary = report.get("summary") or {}
    print("")
    print("Test Agent run finished")
    print(f"  user_story: {user_story_id}")
    print(f"  status: {row.get('status')}")
    print(f"  test_id: {row.get('test_id')}")
    print(f"  project_id: {row.get('project_id')}")
    if summary:
        print(
            "  summary: "
            f"{summary.get('passed', 0)} passed, "
            f"{summary.get('failed', 0)} failed, "
            f"{summary.get('warnings', 0)} warnings, "
            f"{summary.get('total', 0)} total"
        )
    if report.get("reportPath"):
        print(f"  report: {report['reportPath']}")
    if row.get("error"):
        print(f"  error: {row['error']}")
    print("")


if __name__ == "__main__":
    raise SystemExit(main())
