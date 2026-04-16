from __future__ import annotations

import sys
import types
from pathlib import Path

from app.config import Settings
from app.integrations.browser_use_client import BrowserUseClient


def test_browser_use_glm_requires_api_key(monkeypatch, tmp_path: Path) -> None:
    for name in ("ZAI_API_KEY", "ZHIPUAI_API_KEY", "GLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    client = BrowserUseClient(_settings_for(tmp_path, provider="glm"))

    llm, note = client._build_browser_use_llm()

    assert llm is None
    assert "ZAI_API_KEY" in note


def test_browser_use_glm_uses_openai_compatible_chat(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "test-key")
    monkeypatch.setenv("ZAI_BASE_URL", "https://example.test/api/paas/v4/")

    class FakeChatOpenAI:
        last_kwargs = {}

        def __init__(self, **kwargs):
            FakeChatOpenAI.last_kwargs = kwargs

    fake_browser_use = types.ModuleType("browser_use")
    fake_browser_use.ChatOpenAI = FakeChatOpenAI
    monkeypatch.setitem(sys.modules, "browser_use", fake_browser_use)
    client = BrowserUseClient(_settings_for(tmp_path, provider="glm"))

    llm, note = client._build_browser_use_llm()

    assert isinstance(llm, FakeChatOpenAI)
    assert note == "browser_use.ChatOpenAI(glm-5v-turbo)"
    assert FakeChatOpenAI.last_kwargs == {
        "model": "glm-5v-turbo",
        "api_key": "test-key",
        "base_url": "https://example.test/api/paas/v4/",
    }


def _settings_for(root: Path, *, provider: str) -> Settings:
    data_dir = root / "data"
    return Settings(
        app_name="Test Agent",
        api_key=None,
        execution_mode="browser_use",
        sqlite_path=data_dir / "test_agent.sqlite",
        screenshot_dir=data_dir / "screenshots",
        evidence_dir=data_dir / "evidence",
        report_dir=data_dir / "reports",
        max_project_concurrency=3,
        default_timeout_seconds=60,
        workspace_root=root,
        browser_use_llm_provider=provider,
        browser_use_llm_model="glm-5v-turbo",
        browser_use_max_steps=20,
        vlm_provider="mock",
        vlm_model="gpt-4o-mini",
        assertion_warning_threshold=0.6,
    )
