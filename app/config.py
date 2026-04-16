from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path


def _load_env_file() -> None:
    configured_path = os.getenv("TEST_AGENT_ENV_FILE")
    if configured_path:
        candidates = [Path(configured_path)]
    else:
        cwd = Path.cwd().resolve()
        package_root = Path(__file__).resolve().parents[1]
        candidates = [cwd / ".env", package_root / ".env"]

    seen: set[Path] = set()
    for candidate in candidates:
        path = candidate.expanduser().resolve()
        if path in seen:
            continue
        seen.add(path)
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)


def _configure_logging() -> None:
    level_name = os.getenv("TEST_AGENT_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


_load_env_file()
_configure_logging()


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

    # PRD requirement extraction LLM
    prd_llm_provider: str
    prd_llm_model: str
    prd_llm_max_requirements: int
    prd_llm_max_chars: int

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
            execution_mode=os.getenv("TEST_AGENT_EXECUTION_MODE", "browser_use").lower(),
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
            prd_llm_provider=os.getenv("TEST_AGENT_PRD_PROVIDER", "glm").lower(),
            prd_llm_model=os.getenv(
                "TEST_AGENT_PRD_MODEL",
                os.getenv("TEST_AGENT_BROWSER_USE_MODEL", "glm-5.1"),
            ),
            prd_llm_max_requirements=int(
                os.getenv("TEST_AGENT_PRD_MAX_REQUIREMENTS", "12")
            ),
            prd_llm_max_chars=int(os.getenv("TEST_AGENT_PRD_MAX_CHARS", "60000")),
            browser_use_llm_provider=os.getenv("TEST_AGENT_BROWSER_USE_PROVIDER", "glm").lower(),
            browser_use_llm_model=os.getenv("TEST_AGENT_BROWSER_USE_MODEL", "glm-5.1"),
            browser_use_max_steps=int(os.getenv("TEST_AGENT_BROWSER_USE_MAX_STEPS", "20")),
            vlm_provider=os.getenv("TEST_AGENT_VLM_PROVIDER", "glm").lower(),
            vlm_model=os.getenv("TEST_AGENT_VLM_MODEL", "glm-5v-turbo"),
            assertion_warning_threshold=float(
                os.getenv("TEST_AGENT_ASSERTION_WARNING_THRESHOLD", "0.6")
            ),
        )

    def ensure_dirs(self) -> None:
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)

    def require_real_integrations(self) -> None:
        simulated: list[str] = []
        if self.execution_mode != "browser_use":
            simulated.append(
                f"TEST_AGENT_EXECUTION_MODE must be browser_use, got {self.execution_mode!r}"
            )
        if self.prd_llm_provider in {"", "heuristic", "mock", "rules"}:
            simulated.append(
                f"TEST_AGENT_PRD_PROVIDER must be a real LLM provider, got {self.prd_llm_provider!r}"
            )
        if self.vlm_provider in {"", "mock"}:
            simulated.append(
                f"TEST_AGENT_VLM_PROVIDER must be a real VLM provider, got {self.vlm_provider!r}"
            )
        if simulated:
            raise ValueError("Simulation is disabled for this run: " + "; ".join(simulated))


settings = Settings.from_env()
