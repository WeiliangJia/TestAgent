from __future__ import annotations

import base64
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

LOGGER = logging.getLogger(__name__)
_DEFAULT_ZAI_BASE_URL = "https://api.z.ai/api/paas/v4/"


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
    """VLM-backed assertion interface.

    Two call sites:
    - ``assert_functional``: Layer 1 — does the screenshot match the expected outcome?
    - ``assert_visual``:     Layer 2 — is the rendered UI free of layout defects?

    Both take a screenshot and return a LayerVerdict. Implementations may share
    transport but MUST use different prompts because the questions differ.
    """

    def assert_visual(
        self, *, expected: str, screenshot_path: str | None
    ) -> LayerVerdict:
        raise NotImplementedError

    def assert_functional(
        self,
        *,
        expected: str,
        screenshot_path: str | None,
        dom_hint: str = "",
        console_errors: list[str] | None = None,
    ) -> LayerVerdict:
        """Default shim delegates to assert_visual with a functional prompt.

        Subclasses can override to tailor the prompt or model choice; the base
        implementation keeps provider code compact.
        """
        prompt = _build_functional_prompt(
            expected=expected,
            dom_hint=dom_hint,
            console_errors=console_errors or [],
        )
        return _call_with_prompt(self, prompt=prompt, screenshot_path=screenshot_path)


def _call_with_prompt(
    client: "VLMClient", *, prompt: str, screenshot_path: str | None
) -> LayerVerdict:
    """Route through the concrete client's transport by re-using assert_visual.

    Each provider's assert_visual builds its own prompt internally from
    ``_build_prompt``. To inject a different prompt without duplicating all
    three provider classes, we temporarily swap the builder. This is a small
    hack justified by keeping provider classes unchanged.
    """
    import app.integrations.vlm_client as mod

    original = mod._build_prompt
    mod._build_prompt = lambda _expected: prompt
    try:
        return client.assert_visual(expected="", screenshot_path=screenshot_path)
    finally:
        mod._build_prompt = original


def _build_functional_prompt(
    *, expected: str, dom_hint: str, console_errors: list[str]
) -> str:
    dom_line = (
        f"\nDOM excerpt (auxiliary, may be partial):\n{dom_hint[:1200]}"
        if dom_hint
        else ""
    )
    console_line = (
        "\nConsole errors observed: " + "; ".join(console_errors[:5])
        if console_errors
        else ""
    )
    return (
        "You are a functional QA assistant verifying an E2E test screenshot "
        "from the perspective of a non-technical end user.\n"
        f"Expected outcome: {expected}\n"
        "Decide ONLY whether the expected outcome is visible on the page. "
        "Ignore visual polish; a rough-looking page that still shows the "
        "expected content is PASSED. Fail if the page shows a 4xx/5xx error, "
        "a blank page, an error dialog, or if the expected outcome is clearly "
        "absent."
        f"{dom_line}{console_line}\n\n"
        "Answer ONLY with strict JSON in this shape:\n"
        '{"verdict":"passed|failed|warning","confidence":0.0-1.0,'
        '"errors":["..."],"visual_issues":[],"rationale":"one sentence"}'
    )


def build_vlm_client(provider: str, model: str | None = None) -> VLMClient:
    provider = (provider or "glm").lower()
    if provider == "openai":
        return OpenAIVLMClient(model=model or "gpt-4o-mini")
    if provider == "anthropic":
        return AnthropicVLMClient(model=model or "claude-sonnet-4-5")
    if provider in {"glm", "zai", "zhipu", "zhipuai"}:
        return GLMVLMClient(model=model or "glm-5v-turbo")
    raise ValueError(f"Unsupported real VLM provider: {provider}")


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
        placeholder = _placeholder_screenshot_response(screenshot_path)
        if placeholder is not None:
            return placeholder

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
        placeholder = _placeholder_screenshot_response(screenshot_path)
        if placeholder is not None:
            return placeholder

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
            LOGGER.warning("GLM visual assertion skipped because no API key is set")
            return _missing_key_response("ZAI_API_KEY/ZHIPUAI_API_KEY/GLM_API_KEY")

        try:
            from openai import OpenAI
        except ImportError:
            LOGGER.warning("GLM visual assertion skipped because openai is not installed")
            return _import_error_response("openai")

        if not screenshot_path or not Path(screenshot_path).exists():
            return LayerVerdict(
                status="warning",
                confidence=0.4,
                visual_issues=["Screenshot missing."],
                rationale="no-screenshot",
            )
        placeholder = _placeholder_screenshot_response(screenshot_path)
        if placeholder is not None:
            return placeholder

        base_url = _glm_base_url()

        LOGGER.info(
            "Calling GLM visual assertion through OpenAI-compatible API model=%s screenshot=%s",
            self.model,
            screenshot_path,
        )
        client = OpenAI(api_key=api_key, base_url=base_url)

        try:
            completion = _create_glm_completion(
                client=client,
                model=self.model,
                expected=expected,
                screenshot_path=screenshot_path,
                max_tokens=1200,
            )
            text = _extract_completion_text(completion)
        except Exception as exc:  # pragma: no cover - network dependent
            LOGGER.exception("GLM visual assertion failed")
            return LayerVerdict(
                status="warning",
                confidence=0.3,
                visual_issues=[f"VLM call failed: {type(exc).__name__}"],
                rationale=str(exc)[:200],
            )

        if not text.strip():
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


def _glm_base_url() -> str:
    return (
        _first_env("ZAI_BASE_URL", "ZHIPUAI_BASE_URL", "GLM_BASE_URL")
        or _DEFAULT_ZAI_BASE_URL
    )


def _create_glm_completion(
    *,
    client: object,
    model: str,
    expected: str,
    screenshot_path: str,
    max_tokens: int = 500,
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
        "max_tokens": max_tokens,
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


def _placeholder_screenshot_response(screenshot_path: str) -> LayerVerdict | None:
    dimensions = _png_dimensions(Path(screenshot_path))
    if dimensions and dimensions[0] <= 1 and dimensions[1] <= 1:
        return LayerVerdict(
            status="warning",
            confidence=0.3,
            visual_issues=["Screenshot is a placeholder, not a real page capture."],
            rationale="placeholder-screenshot",
        )
    return None


def _png_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return width, height
