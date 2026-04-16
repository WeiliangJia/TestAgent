from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class LayerVerdict:
    """Shared verdict shape used by both Layer 1 (functional) and Layer 2 (visual).

    The assertion engine combines two verdicts into the final AssertionResult.
    """

    status: str  # "passed" | "failed" | "warning"
    confidence: float
    errors: list[str] = field(default_factory=list)
    visual_issues: list[str] = field(default_factory=list)
    rationale: str = ""


class VLMClient:
    """Layer 2 visual assertion interface.

    Given an expected outcome and a screenshot path, return a verdict. Real
    implementations call a vision-capable model; the mock returns a deterministic
    positive verdict so the pipeline runs without any API key.
    """

    def assert_visual(
        self, *, expected: str, screenshot_path: str | None
    ) -> LayerVerdict:
        raise NotImplementedError


def build_vlm_client(provider: str, model: str | None = None) -> VLMClient:
    provider = (provider or "mock").lower()
    if provider == "openai":
        return OpenAIVLMClient(model=model or "gpt-4o-mini")
    if provider == "anthropic":
        return AnthropicVLMClient(model=model or "claude-sonnet-4-5")
    if provider in {"glm", "zai", "zhipu", "zhipuai"}:
        return GLMVLMClient(model=model or "glm-5v-turbo")
    return MockVLMClient()


class MockVLMClient(VLMClient):
    """Deterministic stand-in; used when no API key is configured."""

    def assert_visual(self, *, expected: str, screenshot_path: str | None) -> LayerVerdict:
        if not screenshot_path or not Path(screenshot_path).exists():
            return LayerVerdict(
                status="warning",
                confidence=0.4,
                visual_issues=["Screenshot missing; visual check skipped."],
                rationale="mock:no-screenshot",
            )
        return LayerVerdict(
            status="passed",
            confidence=0.75,
            rationale="mock:screenshot-present",
        )


class OpenAIVLMClient(VLMClient):
    def __init__(self, *, model: str) -> None:
        self.model = model

    def assert_visual(self, *, expected: str, screenshot_path: str | None) -> LayerVerdict:
        try:
            from openai import OpenAI
        except ImportError:
            return _import_error_response("openai")
        if not os.getenv("OPENAI_API_KEY"):
            return _missing_key_response("OPENAI_API_KEY")
        if not screenshot_path or not Path(screenshot_path).exists():
            return LayerVerdict(
                status="warning",
                confidence=0.4,
                visual_issues=["Screenshot missing."],
                rationale="no-screenshot",
            )

        client = OpenAI()
        try:
            completion = client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": _build_prompt(expected)},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{_encode_image(screenshot_path)}"
                                },
                            },
                        ],
                    }
                ],
                max_tokens=500,
            )
            text = completion.choices[0].message.content or ""
        except Exception as exc:  # pragma: no cover - network dependent
            return LayerVerdict(
                status="warning",
                confidence=0.3,
                visual_issues=[f"VLM call failed: {type(exc).__name__}"],
                rationale=str(exc)[:200],
            )
        return _parse_verdict(text)


class AnthropicVLMClient(VLMClient):
    def __init__(self, *, model: str) -> None:
        self.model = model

    def assert_visual(self, *, expected: str, screenshot_path: str | None) -> LayerVerdict:
        try:
            from anthropic import Anthropic
        except ImportError:
            return _import_error_response("anthropic")
        if not os.getenv("ANTHROPIC_API_KEY"):
            return _missing_key_response("ANTHROPIC_API_KEY")
        if not screenshot_path or not Path(screenshot_path).exists():
            return LayerVerdict(
                status="warning",
                confidence=0.4,
                visual_issues=["Screenshot missing."],
                rationale="no-screenshot",
            )

        client = Anthropic()
        try:
            msg = client.messages.create(
                model=self.model,
                max_tokens=500,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": _encode_image(screenshot_path),
                                },
                            },
                            {"type": "text", "text": _build_prompt(expected)},
                        ],
                    }
                ],
            )
            text = "".join(
                getattr(block, "text", "") for block in msg.content
            )
        except Exception as exc:  # pragma: no cover - network dependent
            return LayerVerdict(
                status="warning",
                confidence=0.3,
                visual_issues=[f"VLM call failed: {type(exc).__name__}"],
                rationale=str(exc)[:200],
            )
        return _parse_verdict(text)


class GLMVLMClient(VLMClient):
    def __init__(self, *, model: str) -> None:
        self.model = model

    def assert_visual(self, *, expected: str, screenshot_path: str | None) -> LayerVerdict:
        api_key = _first_env("ZAI_API_KEY", "ZHIPUAI_API_KEY", "GLM_API_KEY")
        if not api_key:
            return _missing_key_response("ZAI_API_KEY/ZHIPUAI_API_KEY/GLM_API_KEY")

        client_cls = _import_glm_client()
        if client_cls is None:
            return _import_error_response("zai-sdk")

        if not screenshot_path or not Path(screenshot_path).exists():
            return LayerVerdict(
                status="warning",
                confidence=0.4,
                visual_issues=["Screenshot missing."],
                rationale="no-screenshot",
            )

        base_url = _first_env("ZAI_BASE_URL", "ZHIPUAI_BASE_URL", "GLM_BASE_URL")
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url

        try:
            try:
                client = client_cls(**client_kwargs)
            except TypeError:
                client_kwargs.pop("base_url", None)
                client = client_cls(**client_kwargs)
            completion = _create_glm_completion(
                client=client,
                model=self.model,
                expected=expected,
                screenshot_path=screenshot_path,
            )
            text = _extract_completion_text(completion)
        except Exception as exc:  # pragma: no cover - network dependent
            return LayerVerdict(
                status="warning",
                confidence=0.3,
                visual_issues=[f"VLM call failed: {type(exc).__name__}"],
                rationale=str(exc)[:200],
            )
        if not text:
            return LayerVerdict(
                status="warning",
                confidence=0.4,
                visual_issues=["VLM returned an empty response."],
                rationale="empty-response",
            )
        return _parse_verdict(text)


def _build_prompt(expected: str) -> str:
    return (
        "You are a visual QA assistant verifying an E2E test screenshot.\n"
        f"Expected outcome: {expected}\n\n"
        "Examine the screenshot. Focus on:\n"
        "1. Functional visibility — is the expected outcome present on the page?\n"
        "2. Layout quality — any broken images, overflow, misaligned elements?\n\n"
        "Answer ONLY with strict JSON in this shape:\n"
        '{"verdict":"passed|failed|warning","confidence":0.0-1.0,'
        '"errors":["..."],"visual_issues":["..."],"rationale":"one sentence"}'
    )


def _parse_verdict(text: str) -> LayerVerdict:
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        return LayerVerdict(
            status="warning",
            confidence=0.4,
            visual_issues=["VLM returned non-JSON output."],
            rationale=text[:200],
        )
    try:
        data = json.loads(match.group(0))
    except Exception:
        return LayerVerdict(
            status="warning",
            confidence=0.4,
            visual_issues=["VLM JSON parse error."],
            rationale=match.group(0)[:200],
        )
    verdict = str(data.get("verdict", "warning")).lower()
    if verdict not in {"passed", "failed", "warning"}:
        verdict = "warning"
    try:
        confidence = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    return LayerVerdict(
        status=verdict,
        confidence=max(0.0, min(1.0, confidence)),
        errors=[str(x) for x in (data.get("errors") or [])],
        visual_issues=[str(x) for x in (data.get("visual_issues") or [])],
        rationale=str(data.get("rationale", ""))[:400],
    )


def _encode_image(path: str) -> str:
    with open(path, "rb") as handle:
        return base64.b64encode(handle.read()).decode("ascii")


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def _import_glm_client() -> object | None:
    try:
        from zai import ZhipuAiClient  # type: ignore

        return ZhipuAiClient
    except ImportError:
        pass
    try:
        from zhipuai import ZhipuAI  # type: ignore

        return ZhipuAI
    except ImportError:
        return None


def _create_glm_completion(
    *, client: object, model: str, expected: str, screenshot_path: str
) -> object:
    completion_kwargs = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _build_prompt(expected)},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{_encode_image(screenshot_path)}"
                        },
                    },
                ],
            }
        ],
        "max_tokens": 500,
        "thinking": {"type": "disabled"},
    }
    completions = getattr(getattr(client, "chat"), "completions")
    try:
        return completions.create(**completion_kwargs)
    except TypeError:
        completion_kwargs.pop("thinking", None)
        return completions.create(**completion_kwargs)


def _extract_completion_text(completion: object) -> str:
    choices = _field(completion, "choices")
    choice = choices[0] if choices else None
    message = _field(choice, "message") if choice is not None else None
    content = _field(message, "content") if message is not None else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(_content_block_text(block) for block in content)
    return str(content) if content else ""


def _content_block_text(block: object) -> str:
    if isinstance(block, dict):
        return str(block.get("text") or block.get("content") or "")
    return str(getattr(block, "text", "") or getattr(block, "content", "") or "")


def _field(value: object, name: str) -> object:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _import_error_response(package: str) -> LayerVerdict:
    return LayerVerdict(
        status="warning",
        confidence=0.3,
        visual_issues=[f"{package} package is not installed."],
        rationale=f"pip install {package}",
    )


def _missing_key_response(env_var: str) -> LayerVerdict:
    return LayerVerdict(
        status="warning",
        confidence=0.3,
        visual_issues=[f"{env_var} is not set."],
        rationale="missing-api-key",
    )
