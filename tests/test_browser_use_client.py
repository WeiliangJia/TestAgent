from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from app.config import Settings
from app.integrations.browser_use_client import (
    BrowserUseClient,
    _build_compatible_browser_profile,
)
from app.models.test_case import TestCase as ModelTestCase
from app.models.test_case import TestStep as ModelTestStep


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
    assert note == "browser_use.ChatOpenAI(glm-5.1)"
    assert FakeChatOpenAI.last_kwargs == {
        "model": "glm-5.1",
        "api_key": "test-key",
        "base_url": "https://example.test/api/paas/v4/",
    }


def test_browser_use_glm_falls_back_to_llm_module(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "test-key")
    monkeypatch.setenv("ZAI_BASE_URL", "https://example.test/api/paas/v4/")

    class FakeChatOpenAI:
        last_kwargs = {}

        def __init__(self, **kwargs):
            FakeChatOpenAI.last_kwargs = kwargs

    fake_browser_use = types.ModuleType("browser_use")
    fake_browser_use.__path__ = []
    fake_llm = types.ModuleType("browser_use.llm")
    fake_llm.ChatOpenAI = FakeChatOpenAI
    monkeypatch.setitem(sys.modules, "browser_use", fake_browser_use)
    monkeypatch.setitem(sys.modules, "browser_use.llm", fake_llm)
    client = BrowserUseClient(_settings_for(tmp_path, provider="glm"))

    llm, note = client._build_browser_use_llm()

    assert isinstance(llm, FakeChatOpenAI)
    assert note == "browser_use.llm.ChatOpenAI(glm-5.1)"
    assert FakeChatOpenAI.last_kwargs == {
        "model": "glm-5.1",
        "api_key": "test-key",
        "base_url": "https://example.test/api/paas/v4/",
    }


def test_browser_session_profile_filters_unsupported_devtools_kwarg(
    monkeypatch, tmp_path: Path
) -> None:
    class FakeArgs:
        def __init__(self, payload):
            self.payload = payload

        def model_dump(self, *args, **kwargs):
            return dict(self.payload)

    class FakeBrowserProfile:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def kwargs_for_launch_persistent_context(self):
            return FakeArgs({"headless": True, "devtools": False})

        def kwargs_for_launch(self):
            return FakeArgs({"headless": True, "devtools": False})

    class FakeBrowserSession:
        last_kwargs = {}

        def __init__(self, **kwargs):
            FakeBrowserSession.last_kwargs = kwargs

    fake_browser_use = types.ModuleType("browser_use")
    fake_browser_use.__path__ = []
    fake_browser_use.BrowserSession = FakeBrowserSession
    fake_browser_pkg = types.ModuleType("browser_use.browser")
    fake_browser_pkg.__path__ = []
    fake_profile_module = types.ModuleType("browser_use.browser.profile")
    fake_profile_module.BrowserProfile = FakeBrowserProfile
    monkeypatch.setitem(sys.modules, "browser_use", fake_browser_use)
    monkeypatch.setitem(sys.modules, "browser_use.browser", fake_browser_pkg)
    monkeypatch.setitem(sys.modules, "browser_use.browser.profile", fake_profile_module)

    client = BrowserUseClient(_settings_for(tmp_path, provider="glm"))

    session, session_kwarg = client._build_browser_session()

    assert isinstance(session, FakeBrowserSession)
    assert session_kwarg == "browser_session"
    profile = FakeBrowserSession.last_kwargs["browser_profile"]
    assert profile.kwargs == {"headless": True}
    assert profile.kwargs_for_launch_persistent_context().model_dump() == {
        "headless": True
    }
    assert profile.kwargs_for_launch().model_dump() == {"headless": True}


def test_installed_browser_profile_filters_unsupported_devtools_kwarg() -> None:
    pytest.importorskip("browser_use.browser.profile")

    profile = _build_compatible_browser_profile()

    assert profile is not None
    assert "devtools" not in profile.kwargs_for_launch().model_dump()
    assert "devtools" not in profile.kwargs_for_launch_persistent_context().model_dump()


@pytest.mark.asyncio
async def test_browser_use_agent_disables_builtin_memory(
    monkeypatch, tmp_path: Path
) -> None:
    class FakeAgent:
        last_kwargs = {}

        def __init__(self, **kwargs):
            FakeAgent.last_kwargs = kwargs

        async def run(self, max_steps: int):
            return None

    fake_browser_use = types.ModuleType("browser_use")
    fake_browser_use.Agent = FakeAgent
    monkeypatch.setitem(sys.modules, "browser_use", fake_browser_use)

    client = BrowserUseClient(_settings_for(tmp_path, provider="glm"))
    monkeypatch.setattr(
        client,
        "_build_browser_use_llm",
        lambda: (object(), "fake llm"),
    )
    monkeypatch.setattr(client, "_build_browser_session", lambda: (None, None))

    execution = await client._execute_with_browser_use(
        target_url="https://example.test",
        test_case=ModelTestCase(
            test_case_id="TC-001",
            req_id="R-01",
            story_id="R-01.US-01",
            ac_id="R-01.US-01.AC-01",
            story="Story",
            expected="Expected",
            test_type="integration",
            steps=[
                ModelTestStep(order=1, instruction="Open page", expected="Loaded")
            ],
        ),
        screenshot_path=tmp_path / "screenshot.png",
        credentials=None,
        prompt_context="",
    )

    assert FakeAgent.last_kwargs["enable_memory"] is False
    assert execution.status == "failed"
    assert execution.dom_snapshot == "<browser-execution-failed/>"
    assert "Expected" not in execution.dom_snapshot
    assert any("placeholder screenshot" in note for note in execution.notes)


def _settings_for(root: Path, *, provider: str) -> Settings:
    data_dir = root / "data"
    return Settings(
        app_name="Test Agent",
        api_key=None,
        project_keys={},
        execution_mode="browser_use",
        sqlite_path=data_dir / "test_agent.sqlite",
        screenshot_dir=data_dir / "screenshots",
        evidence_dir=data_dir / "evidence",
        report_dir=data_dir / "reports",
        max_project_concurrency=3,
        default_timeout_seconds=60,
        workspace_root=root,
        browser_use_llm_provider=provider,
        browser_use_llm_model="glm-5.1",
        browser_use_max_steps=20,
        browser_headless=True,
        vlm_provider="glm",
        vlm_model="glm-5v-turbo",
        assertion_warning_threshold=0.6,
        inter_test_delay_seconds=0.0,
        skip_visual_tests=True,
        analyzer_low_confidence_threshold=0.5,
        analyzer_aggregation_min_cases=2,
    )
