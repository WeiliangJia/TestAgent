from __future__ import annotations

import builtins
import sys
import types
from pathlib import Path
from types import SimpleNamespace

from app.integrations.vlm_client import GLMVLMClient, build_vlm_client


_ONE_PIXEL_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x04\x00\x00\x00\xb5\x1c\x0c\x02"
    b"\x00\x00\x00\x0bIDATx\xdac\xfc\xff\x1f\x00\x03\x03"
    b"\x02\x00\xef\xbf\xa7\xdb\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_build_vlm_client_supports_glm_provider() -> None:
    client = build_vlm_client("glm", "glm-5v-turbo")

    assert isinstance(client, GLMVLMClient)
    assert client.model == "glm-5v-turbo"


def test_glm_vlm_reports_missing_key(monkeypatch, tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    screenshot.write_bytes(b"fake-png")
    for name in ("ZAI_API_KEY", "ZHIPUAI_API_KEY", "GLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    verdict = GLMVLMClient(model="glm-5v-turbo").assert_visual(
        expected="Dashboard is visible.",
        screenshot_path=str(screenshot),
    )

    assert verdict.status == "warning"
    assert "ZAI_API_KEY" in verdict.visual_issues[0]


def test_glm_vlm_reports_missing_openai_sdk(monkeypatch, tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    screenshot.write_bytes(b"fake-png")
    monkeypatch.setenv("ZAI_API_KEY", "test-key")
    monkeypatch.delitem(sys.modules, "openai", raising=False)
    original_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "openai":
            raise ImportError(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    verdict = GLMVLMClient(model="glm-5v-turbo").assert_visual(
        expected="Dashboard is visible.",
        screenshot_path=str(screenshot),
    )

    assert verdict.status == "warning"
    assert "openai package is not installed." in verdict.visual_issues


def test_glm_vlm_skips_placeholder_screenshot(monkeypatch, tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    screenshot.write_bytes(_ONE_PIXEL_PNG)
    monkeypatch.setenv("ZAI_API_KEY", "test-key")

    verdict = GLMVLMClient(model="glm-5v-turbo").assert_visual(
        expected="Dashboard is visible.",
        screenshot_path=str(screenshot),
    )

    assert verdict.status == "warning"
    assert verdict.rationale == "placeholder-screenshot"
    assert "placeholder" in verdict.visual_issues[0]


def test_glm_vlm_parses_openai_sdk_response(monkeypatch, tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    screenshot.write_bytes(b"fake-png")
    monkeypatch.setenv("ZAI_API_KEY", "test-key")
    monkeypatch.setenv("ZAI_BASE_URL", "https://example.test/v4/")

    class FakeCompletions:
        last_kwargs = {}

        def create(self, **kwargs):
            FakeCompletions.last_kwargs = kwargs
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=(
                                '{"verdict":"passed","confidence":0.91,'
                                '"errors":[],"visual_issues":[],"rationale":"ok"}'
                            )
                        )
                    )
                ]
            )

    class FakeOpenAI:
        last_kwargs = {}

        def __init__(self, **kwargs):
            FakeOpenAI.last_kwargs = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

    fake_module = types.ModuleType("openai")
    fake_module.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_module)

    verdict = GLMVLMClient(model="glm-5v-turbo").assert_visual(
        expected="Dashboard is visible.",
        screenshot_path=str(screenshot),
    )

    assert verdict.status == "passed"
    assert verdict.confidence == 0.91
    assert FakeOpenAI.last_kwargs == {
        "api_key": "test-key",
        "base_url": "https://example.test/v4/",
    }
    assert FakeCompletions.last_kwargs["model"] == "glm-5v-turbo"
    assert FakeCompletions.last_kwargs["thinking"] == {"type": "disabled"}
    content = FakeCompletions.last_kwargs["messages"][0]["content"]
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_glm_vlm_handles_non_json_response(monkeypatch, tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    screenshot.write_bytes(b"fake-png")
    monkeypatch.setenv("ZAI_API_KEY", "test-key")

    class FakeCompletions:
        def create(self, **kwargs):
            return {
                "choices": [
                    {
                        "message": {
                            "content": "The screenshot appears to match."
                        }
                    }
                ]
            }

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    fake_module = types.ModuleType("openai")
    fake_module.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_module)

    verdict = GLMVLMClient(model="glm-5v-turbo").assert_visual(
        expected="Dashboard is visible.",
        screenshot_path=str(screenshot),
    )

    assert verdict.status == "warning"
    assert "VLM returned non-JSON output." in verdict.visual_issues
