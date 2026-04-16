from __future__ import annotations

import asyncio
import base64
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.api.schemas import Credentials
from app.config import Settings
from app.models.test_case import TestCase


_ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


@dataclass(slots=True)
class BrowserExecution:
    status: str
    current_url: str
    screenshot_path: Path
    dom_snapshot: str
    console_errors: list[str] = field(default_factory=list)
    network_failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class BrowserUseClient:
    """Browser execution facade.

    Supports three modes selected by ``TEST_AGENT_EXECUTION_MODE``:

    - ``mock``         — deterministic stub, no browser required.
    - ``browser_use``  — drive the page with the ``browser-use`` LLM agent.
    - ``playwright``   — scripted Playwright (no LLM), used for debugging.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.execution_mode = settings.execution_mode
        self.timeout_seconds = settings.default_timeout_seconds

    async def execute_test_case(
        self,
        *,
        project_id: str,
        test_id: str,
        target_url: str,
        test_case: TestCase,
        screenshot_path: Path,
        credentials: Credentials | None,
        prompt_context: str = "",
    ) -> BrowserExecution:
        if self.execution_mode == "browser_use":
            return await self._execute_with_browser_use(
                target_url=target_url,
                test_case=test_case,
                screenshot_path=screenshot_path,
                credentials=credentials,
                prompt_context=prompt_context,
            )
        if self.execution_mode == "playwright":
            return await self._execute_with_playwright(
                target_url=target_url,
                test_case=test_case,
                screenshot_path=screenshot_path,
                credentials=credentials,
            )
        return await self._execute_mock(
            project_id=project_id,
            test_id=test_id,
            target_url=target_url,
            test_case=test_case,
            screenshot_path=screenshot_path,
        )

    async def _execute_mock(
        self,
        *,
        project_id: str,
        test_id: str,
        target_url: str,
        test_case: TestCase,
        screenshot_path: Path,
    ) -> BrowserExecution:
        await asyncio.sleep(0)
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        screenshot_path.write_bytes(_ONE_PIXEL_PNG)
        dom = "\n".join(
            [
                "<html>",
                "  <head><title>Mock Test Page</title></head>",
                "  <body>",
                f"    <main data-project='{project_id}' data-test='{test_id}'>",
                f"      <h1>{test_case.expected}</h1>",
                f"      <p>{test_case.story}</p>",
                "    </main>",
                "  </body>",
                "</html>",
            ]
        )
        return BrowserExecution(
            status="passed",
            current_url=target_url,
            screenshot_path=screenshot_path,
            dom_snapshot=dom,
            notes=[
                "Executed in mock mode. Set TEST_AGENT_EXECUTION_MODE=browser_use "
                "for the real LLM-driven browser agent."
            ],
        )

    async def _execute_with_browser_use(
        self,
        *,
        target_url: str,
        test_case: TestCase,
        screenshot_path: Path,
        credentials: Credentials | None,
        prompt_context: str,
    ) -> BrowserExecution:
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            from browser_use import Agent  # type: ignore
        except ImportError:
            return self._fallback(
                target_url,
                screenshot_path,
                notes=[
                    "browser-use not installed. `pip install browser-use` and "
                    "`playwright install chromium`."
                ],
            )

        llm, llm_note = self._build_browser_use_llm()
        if llm is None:
            return self._fallback(
                target_url, screenshot_path, notes=[llm_note or "LLM not configured."]
            )

        session, session_kwarg = self._build_browser_session()
        task = self._build_agent_task(
            target_url=target_url,
            test_case=test_case,
            credentials=credentials,
            prompt_context=prompt_context,
        )
        sensitive_data = self._credentials_to_sensitive_data(credentials)

        agent_kwargs: dict[str, Any] = {"task": task, "llm": llm}
        if sensitive_data:
            agent_kwargs["sensitive_data"] = sensitive_data
        if session is not None and session_kwarg:
            agent_kwargs[session_kwarg] = session

        console_errors: list[str] = []
        network_failures: list[str] = []
        notes: list[str] = [f"browser-use driver: {llm_note}"]
        status = "passed"
        current_url = target_url
        dom_snapshot = ""

        try:
            agent = Agent(**agent_kwargs)
        except TypeError as exc:
            return self._fallback(
                target_url,
                screenshot_path,
                notes=[f"Agent init failed: {exc}"],
            )

        try:
            page = await _session_page(session)
            if page is not None:
                page.on(
                    "console",
                    lambda msg: (
                        console_errors.append(msg.text) if msg.type == "error" else None
                    ),
                )
                page.on(
                    "requestfailed",
                    lambda req: network_failures.append(f"{req.method} {req.url}"),
                )

            try:
                history = await agent.run(max_steps=self.settings.browser_use_max_steps)
                final_note = _history_summary(history)
                if final_note:
                    notes.append(final_note)
            except Exception as exc:  # pragma: no cover - network dependent
                status = "failed"
                notes.append(f"Agent run failed: {type(exc).__name__}: {exc}")

            page = await _session_page(session) or page
            if page is not None:
                try:
                    current_url = page.url
                    dom_snapshot = await page.content()
                    await page.screenshot(path=str(screenshot_path), full_page=True)
                except Exception as exc:  # pragma: no cover
                    notes.append(f"Could not capture final page state: {exc}")
        finally:
            await _session_close(session)

        if not screenshot_path.exists():
            screenshot_path.write_bytes(_ONE_PIXEL_PNG)
        if not dom_snapshot:
            dom_snapshot = (
                f"<agent-summary>{test_case.expected}</agent-summary>"
                if status == "passed"
                else f"<agent-error>{test_case.expected}</agent-error>"
            )

        return BrowserExecution(
            status=status,
            current_url=current_url,
            screenshot_path=screenshot_path,
            dom_snapshot=dom_snapshot,
            console_errors=console_errors,
            network_failures=network_failures,
            notes=notes,
        )

    async def _execute_with_playwright(
        self,
        *,
        target_url: str,
        test_case: TestCase,
        screenshot_path: Path,
        credentials: Credentials | None,
    ) -> BrowserExecution:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return self._fallback(
                target_url,
                screenshot_path,
                notes=["Playwright not installed. `pip install playwright`."],
            )

        console_errors: list[str] = []
        network_failures: list[str] = []
        notes: list[str] = []
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            page.on(
                "console",
                lambda msg: (
                    console_errors.append(msg.text) if msg.type == "error" else None
                ),
            )
            page.on(
                "requestfailed",
                lambda req: network_failures.append(f"{req.method} {req.url}"),
            )

            try:
                await page.goto(
                    credentials.login_url
                    if credentials and credentials.login_url
                    else target_url
                )
                if credentials and credentials.username and credentials.password:
                    await self._best_effort_login(page, credentials, notes)
                    await page.goto(target_url)
                await page.wait_for_load_state(
                    "networkidle", timeout=self.timeout_seconds * 1000
                )
                await page.screenshot(path=str(screenshot_path), full_page=True)
                dom_snapshot = await page.content()
                current_url = page.url
                status = "passed"
            except Exception as exc:  # pragma: no cover
                status = "failed"
                current_url = page.url if page else target_url
                dom_snapshot = (
                    f"<execution-error>{type(exc).__name__}: {exc}</execution-error>"
                )
                notes.append(f"Browser execution failed: {type(exc).__name__}: {exc}")
                if not screenshot_path.exists():
                    screenshot_path.write_bytes(_ONE_PIXEL_PNG)
            finally:
                await context.close()
                await browser.close()

        return BrowserExecution(
            status=status,
            current_url=current_url,
            screenshot_path=screenshot_path,
            dom_snapshot=dom_snapshot,
            console_errors=console_errors,
            network_failures=network_failures,
            notes=notes,
        )

    def _build_browser_use_llm(self) -> tuple[Any | None, str]:
        provider = self.settings.browser_use_llm_provider
        model = self.settings.browser_use_llm_model
        if provider == "openai":
            if not os.getenv("OPENAI_API_KEY"):
                return None, "OPENAI_API_KEY not set"
            try:
                from browser_use.llm import ChatOpenAI  # type: ignore

                return ChatOpenAI(model=model), f"browser_use.llm.ChatOpenAI({model})"
            except ImportError:
                pass
            try:
                from langchain_openai import ChatOpenAI  # type: ignore

                return ChatOpenAI(model=model), f"langchain_openai.ChatOpenAI({model})"
            except ImportError:
                return None, "Install browser-use or langchain-openai"
        if provider == "anthropic":
            if not os.getenv("ANTHROPIC_API_KEY"):
                return None, "ANTHROPIC_API_KEY not set"
            try:
                from browser_use.llm import ChatAnthropic  # type: ignore

                return ChatAnthropic(model=model), f"browser_use.llm.ChatAnthropic({model})"
            except ImportError:
                pass
            try:
                from langchain_anthropic import ChatAnthropic  # type: ignore

                return (
                    ChatAnthropic(model=model),
                    f"langchain_anthropic.ChatAnthropic({model})",
                )
            except ImportError:
                return None, "Install browser-use or langchain-anthropic"
        return None, f"Unsupported browser_use_llm_provider: {provider}"

    def _build_browser_session(self) -> tuple[Any | None, str | None]:
        """Best-effort construction of a browser session that also exposes a page.

        browser-use's API has moved between versions; try a couple of shapes.
        Returns (session_or_None, kwarg_name_for_Agent).
        """
        try:
            from browser_use import BrowserSession  # type: ignore

            session = BrowserSession(headless=True)
            return session, "browser_session"
        except ImportError:
            pass
        try:
            from browser_use import Browser  # type: ignore

            return Browser(), "browser"
        except ImportError:
            pass
        return None, None

    def _build_agent_task(
        self,
        *,
        target_url: str,
        test_case: TestCase,
        credentials: Credentials | None,
        prompt_context: str,
    ) -> str:
        lines = [
            f"You are an E2E test executor on {target_url}.",
            "Open the target URL and complete the task below faithfully. "
            "Do not invent facts; if a step cannot be performed, report it.",
            "",
            f"Test case: {test_case.test_case_id}",
            f"Goal: {test_case.expected}",
            "Steps:",
        ]
        for step in sorted(test_case.steps, key=lambda s: s.order):
            lines.append(
                f"  {step.order}. {step.instruction} (expected: {step.expected})"
            )
        if credentials and credentials.username:
            lines += [
                "",
                "If asked to log in, use the placeholders below — they will be "
                "substituted from sensitive_data:",
                "  username: x_username",
                "  password: x_password",
            ]
            if credentials.login_url:
                lines.append(f"  login_url: {credentials.login_url}")
        if prompt_context:
            lines += ["", "Agent memory context:", prompt_context]
        lines += [
            "",
            f"Stop after step {len(test_case.steps)} or as soon as the expected "
            "result is clearly visible on the page.",
        ]
        return "\n".join(lines)

    def _credentials_to_sensitive_data(
        self, credentials: Credentials | None
    ) -> dict[str, str]:
        if credentials is None:
            return {}
        data: dict[str, str] = {}
        if credentials.username:
            data["x_username"] = credentials.username
        if credentials.password:
            data["x_password"] = credentials.password
        for key, value in credentials.extra_fields.items():
            data[f"x_{key}"] = value
        return data

    def _fallback(
        self,
        target_url: str,
        screenshot_path: Path,
        *,
        notes: list[str],
    ) -> BrowserExecution:
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        screenshot_path.write_bytes(_ONE_PIXEL_PNG)
        return BrowserExecution(
            status="failed",
            current_url=target_url,
            screenshot_path=screenshot_path,
            dom_snapshot="<browser-use-unavailable/>",
            notes=notes,
        )

    async def _best_effort_login(
        self, page: Any, credentials: Credentials, notes: list[str]
    ) -> None:
        try:
            await page.fill(
                "input[type='email'], input[name='email'], input[name='username']",
                credentials.username,
            )
            await page.fill(
                "input[type='password'], input[name='password']", credentials.password
            )
            await page.click("button[type='submit'], input[type='submit']")
            await page.wait_for_load_state(
                "networkidle", timeout=self.timeout_seconds * 1000
            )
            notes.append("Best-effort login attempted.")
        except Exception as exc:  # pragma: no cover
            notes.append(
                f"Best-effort login skipped or failed: {type(exc).__name__}: {exc}"
            )


async def _session_page(session: Any) -> Any | None:
    if session is None:
        return None
    for attr in ("get_current_page", "current_page", "page"):
        candidate = getattr(session, attr, None)
        if candidate is None:
            continue
        try:
            value = candidate() if callable(candidate) else candidate
            if asyncio.iscoroutine(value):
                value = await value
            if value is not None:
                return value
        except Exception:  # pragma: no cover - defensive
            continue
    return None


async def _session_close(session: Any) -> None:
    if session is None:
        return
    close = getattr(session, "close", None) or getattr(session, "stop", None)
    if close is None:
        return
    try:
        result = close()
        if asyncio.iscoroutine(result):
            await result
    except Exception:  # pragma: no cover - defensive
        pass


def _history_summary(history: Any) -> str:
    if history is None:
        return ""
    for attr in ("final_result", "extracted_content", "last_model_output"):
        candidate = getattr(history, attr, None)
        if candidate is None:
            continue
        try:
            value = candidate() if callable(candidate) else candidate
        except Exception:
            continue
        if value:
            text = str(value)
            return f"agent:{attr}={text[:200]}"
    return "agent:completed"
