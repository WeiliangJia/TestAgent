from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_name: str
    api_key: str | None
    execution_mode: str
    sqlite_path: Path
    screenshot_dir: Path
    evidence_dir: Path
    report_dir: Path
    max_project_concurrency: int
    default_timeout_seconds: int
    workspace_root: Path

    # Browser-use driver LLM
    browser_use_llm_provider: str
    browser_use_llm_model: str
    browser_use_max_steps: int

    # Visual assertion (VLM)
    vlm_provider: str
    vlm_model: str
    assertion_warning_threshold: float

    @classmethod
    def from_env(cls) -> "Settings":
        workspace_root = Path(os.getenv("TEST_AGENT_WORKSPACE", Path.cwd())).resolve()
        data_dir = workspace_root / "data"
        return cls(
            app_name=os.getenv("TEST_AGENT_APP_NAME", "Test Agent"),
            api_key=os.getenv("TEST_AGENT_API_KEY") or None,
            execution_mode=os.getenv("TEST_AGENT_EXECUTION_MODE", "mock").lower(),
            sqlite_path=Path(
                os.getenv("TEST_AGENT_SQLITE_PATH", data_dir / "test_agent.sqlite")
            ).resolve(),
            screenshot_dir=Path(
                os.getenv("TEST_AGENT_SCREENSHOT_DIR", data_dir / "screenshots")
            ).resolve(),
            evidence_dir=Path(
                os.getenv("TEST_AGENT_EVIDENCE_DIR", data_dir / "evidence")
            ).resolve(),
            report_dir=Path(
                os.getenv("TEST_AGENT_REPORT_DIR", data_dir / "reports")
            ).resolve(),
            max_project_concurrency=int(os.getenv("TEST_AGENT_PROJECT_CONCURRENCY", "3")),
            default_timeout_seconds=int(os.getenv("TEST_AGENT_TIMEOUT_SECONDS", "60")),
            workspace_root=workspace_root,
            browser_use_llm_provider=os.getenv("TEST_AGENT_BROWSER_USE_PROVIDER", "openai").lower(),
            browser_use_llm_model=os.getenv("TEST_AGENT_BROWSER_USE_MODEL", "gpt-4o"),
            browser_use_max_steps=int(os.getenv("TEST_AGENT_BROWSER_USE_MAX_STEPS", "20")),
            vlm_provider=os.getenv("TEST_AGENT_VLM_PROVIDER", "mock").lower(),
            vlm_model=os.getenv("TEST_AGENT_VLM_MODEL", "gpt-4o-mini"),
            assertion_warning_threshold=float(
                os.getenv("TEST_AGENT_ASSERTION_WARNING_THRESHOLD", "0.6")
            ),
        )

    def ensure_dirs(self) -> None:
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)


settings = Settings.from_env()
