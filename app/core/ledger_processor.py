from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.config import Settings
from app.models.evidence import TestCaseResult
from app.models.ledger import LedgerACResult, LedgerDocument, LedgerEntry
from app.models.test_case import TestCase, UserStory

LOGGER = logging.getLogger(__name__)

_STUCK_RETRY_THRESHOLD = 3
_OPEN_STATUSES = {"not_implemented", "failing", "warning"}
_STATUS_ORDER = ("failing", "warning", "not_implemented", "passing")


class LedgerProcessor:
    """Loads, queries, and writes the sage-loop ledger.

    Selection priority:
    1. explicit override (user_story_id from .env / CLI / API)
    2. ledger.cursor if still open (not passing)
    3. first not_implemented entry
    4. first failing entry
    5. fall back to first entry
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def load(
        self,
        *,
        ledger_json: dict[str, Any] | None = None,
        ledger_content: str | None = None,
        ledger_path: str | None = None,
    ) -> LedgerDocument | None:
        if ledger_json is not None:
            if not isinstance(ledger_json, dict):
                raise ValueError("ledger_json must be a JSON object.")
            return LedgerDocument.from_dict(ledger_json)

        if ledger_content and ledger_content.strip():
            return LedgerDocument.from_dict(_loads(ledger_content))

        if not ledger_path:
            return None

        resolved = self._resolve_path(ledger_path)
        if not resolved.exists():
            raise FileNotFoundError(f"Ledger file not found: {resolved}")
        LOGGER.info("Loading ledger JSON from %s", resolved)
        raw = _loads(resolved.read_text(encoding="utf-8"))
        return LedgerDocument.from_dict(raw, source_path=str(resolved))

    def select_story_id(
        self, ledger: LedgerDocument, *, override: str | None
    ) -> str | None:
        if override:
            LOGGER.info("Ledger selection overridden by explicit story id %s", override)
            return override
        if not ledger.entries:
            return None

        cursor_id = ledger.cursor
        if cursor_id:
            for story_id, entry in ledger.entries.items():
                if _cursor_matches(cursor_id, story_id) and entry.status in _OPEN_STATUSES:
                    LOGGER.info(
                        "Ledger cursor %s resolved to open story %s", cursor_id, story_id
                    )
                    return story_id

        for target_status in _STATUS_ORDER:
            for story_id, entry in ledger.entries.items():
                if entry.status == target_status and target_status != "passing":
                    LOGGER.info(
                        "Ledger selected story %s (status=%s)", story_id, target_status
                    )
                    return story_id

        first_id = next(iter(ledger.entries), None)
        if first_id:
            LOGGER.info("Ledger fell back to first entry %s", first_id)
        return first_id

    def update_after_run(
        self,
        ledger: LedgerDocument,
        *,
        test_id: str,
        story: UserStory,
        test_cases: Iterable[TestCase],
        results: Iterable[TestCaseResult],
    ) -> LedgerEntry:
        now = _now_iso()
        entry = ledger.entries.get(story.story_id) or LedgerEntry(story_id=story.story_id)
        ledger.entries[story.story_id] = entry

        # Make sure every AC from the PRD has a slot in the ledger.
        for ac in story.acceptance_criteria:
            entry.ac_results.setdefault(ac.ac_id, LedgerACResult())

        tc_by_id = {tc.test_case_id: tc for tc in test_cases}

        for result in results:
            tc = tc_by_id.get(result.test_case_id)
            if tc is None:
                continue
            ac = entry.ac_results.setdefault(tc.ac_id, LedgerACResult())
            ac.status = _ac_status_from_result(result.status)
            ac.last_checked = now
            ac.evidence = _first_screenshot(result)
            ac.failure_reason = _failure_reason(result)

        previous_status = entry.status
        aggregate = _aggregate_status(entry.ac_results.values())
        entry.status = aggregate
        entry.last_checked = now
        entry.checked_by_run = test_id
        entry.summary = _summary_for(aggregate, entry.ac_results.values())

        if aggregate == "failing":
            if previous_status == "failing":
                entry.retry_count += 1
            else:
                entry.retry_count = 1
            if entry.retry_count >= _STUCK_RETRY_THRESHOLD:
                entry.stuck_reason = (
                    f"Failing after {entry.retry_count} consecutive runs."
                )
        else:
            entry.retry_count = 0
            entry.stuck_reason = None

        ledger.cursor = _advance_cursor(ledger)
        ledger.last_updated = now
        return entry

    def save(self, ledger: LedgerDocument, *, path: str | None = None) -> Path:
        target = Path(path) if path else (
            Path(ledger.source_path) if ledger.source_path else None
        )
        if target is None:
            raise ValueError("No ledger path known — cannot save.")
        target = self._resolve_path(str(target))
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        payload = json.dumps(ledger.to_dict(), ensure_ascii=False, indent=2)
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, target)
        LOGGER.info("Saved ledger to %s", target)
        return target

    def _resolve_path(self, raw: str) -> Path:
        path = Path(raw)
        if not path.is_absolute():
            path = self.settings.workspace_root / path
        return path.resolve()


def _loads(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Ledger content is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Ledger JSON must be an object.")
    return data


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cursor_matches(cursor: str, story_id: str) -> bool:
    # Cursor may be a requirement id (e.g. "R-01") or a full story id.
    return story_id == cursor or story_id.startswith(cursor + ".")


def _ac_status_from_result(status: str) -> str:
    status = (status or "").lower()
    if status == "passed":
        return "passing"
    if status == "failed":
        return "failing"
    if status == "warning":
        return "warning"
    return "not_implemented"


def _first_screenshot(result: TestCaseResult) -> str | None:
    for step in result.steps:
        if step.screenshot_path:
            return step.screenshot_path
    return None


def _failure_reason(result: TestCaseResult) -> str | None:
    if result.status == "passed":
        return None
    if result.errors:
        return result.errors[0][:400]
    if result.visual_issues:
        return result.visual_issues[0][:400]
    return None


def _aggregate_status(ac_results: Iterable[LedgerACResult]) -> str:
    statuses = [ac.status for ac in ac_results]
    if not statuses:
        return "not_implemented"
    if any(s == "failing" for s in statuses):
        return "failing"
    if all(s == "passing" for s in statuses):
        return "passing"
    if any(s == "warning" for s in statuses):
        return "warning"
    return "not_implemented"


def _summary_for(aggregate: str, ac_results: Iterable[LedgerACResult]) -> str:
    results = list(ac_results)
    total = len(results)
    passing = sum(1 for ac in results if ac.status == "passing")
    failing = sum(1 for ac in results if ac.status == "failing")
    return f"{aggregate}: {passing}/{total} AC passing, {failing} failing"


def _advance_cursor(ledger: LedgerDocument) -> str | None:
    for story_id, entry in ledger.entries.items():
        if entry.status in _OPEN_STATUSES:
            return story_id
    return ledger.cursor
