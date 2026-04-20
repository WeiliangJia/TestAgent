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
# Canonical enum per sage-loop-ledger-v1.
STATUS_PASSING = "implemented_passing"
STATUS_BROKEN = "implemented_broken"
STATUS_NOT_IMPLEMENTED = "not_implemented"
_OPEN_STATUSES = {STATUS_NOT_IMPLEMENTED, STATUS_BROKEN}
_STATUS_ORDER = (STATUS_BROKEN, STATUS_NOT_IMPLEMENTED, STATUS_PASSING)

# Legacy statuses from older ledgers; normalized on load.
_LEGACY_STATUS_ALIASES = {
    "passing": STATUS_PASSING,
    "failing": STATUS_BROKEN,
    "warning": STATUS_BROKEN,
}


class LedgerProcessor:
    """Loads, queries, and writes the sage-loop ledger.

    Selection priority:
    1. explicit override (user_story_id from .env / CLI / API)
    2. ledger.cursor if still open (not passing)
    3. first not_implemented entry
    4. first implemented_broken entry
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
            return _normalize(LedgerDocument.from_dict(ledger_json))

        if ledger_content and ledger_content.strip():
            return _normalize(LedgerDocument.from_dict(_loads(ledger_content)))

        if not ledger_path:
            return None

        resolved = self._resolve_path(ledger_path)
        if not resolved.exists():
            raise FileNotFoundError(f"Ledger file not found: {resolved}")
        LOGGER.info("Loading ledger JSON from %s", resolved)
        raw = _loads(resolved.read_text(encoding="utf-8"))
        return _normalize(LedgerDocument.from_dict(raw, source_path=str(resolved)))

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
            if target_status == STATUS_PASSING:
                continue
            for story_id, entry in ledger.entries.items():
                if entry.status == target_status:
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
            # Skipped ACs retain their prior state so we don't overwrite a known
            # passing AC with not_implemented just because this run skipped UI.
            if result.status == "skipped":
                continue
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

        if aggregate == STATUS_BROKEN:
            if previous_status == STATUS_BROKEN:
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

    def story_delta(self, ledger: LedgerDocument, story_id: str) -> dict[str, Any]:
        """Emit a compact view of one story's ledger entry for reporting."""
        entry = ledger.entries.get(story_id)
        if entry is None:
            return {"storyId": story_id, "status": STATUS_NOT_IMPLEMENTED, "acResults": {}}
        return {
            "storyId": story_id,
            "status": entry.status,
            "summary": entry.summary,
            "lastChecked": entry.last_checked,
            "checkedByRun": entry.checked_by_run,
            "retryCount": entry.retry_count,
            "stuckReason": entry.stuck_reason,
            "acResults": {
                ac_id: ac.to_dict() for ac_id, ac in entry.ac_results.items()
            },
        }

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


def _normalize(ledger: LedgerDocument) -> LedgerDocument:
    """Convert legacy ``passing/failing/warning`` statuses to v1 canonical enum."""
    for entry in ledger.entries.values():
        entry.status = _LEGACY_STATUS_ALIASES.get(entry.status, entry.status)
        for ac in entry.ac_results.values():
            ac.status = _LEGACY_STATUS_ALIASES.get(ac.status, ac.status)
    return ledger


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cursor_matches(cursor: str, story_id: str) -> bool:
    return story_id == cursor or story_id.startswith(cursor + ".")


def _ac_status_from_result(status: str) -> str:
    status = (status or "").lower()
    if status == "passed":
        return STATUS_PASSING
    if status in {"failed", "warning", "timeout"}:
        return STATUS_BROKEN
    return STATUS_NOT_IMPLEMENTED


def _first_screenshot(result: TestCaseResult) -> str | None:
    for step in result.steps:
        if step.screenshot_path:
            return step.screenshot_path
    return None


def _failure_reason(result: TestCaseResult) -> str | None:
    if result.status == "passed":
        return None

    parts: list[str] = []
    analysis = result.failure_analysis
    if analysis is not None:
        parts.append(f"[{analysis.category}]")
        if analysis.root_cause:
            parts.append(analysis.root_cause)
    elif result.failure_type:
        parts.append(f"[{result.failure_type}]")

    if result.errors:
        primary = result.errors[0]
        if not parts or primary not in parts[-1]:
            parts.append(primary)
    elif result.visual_issues:
        parts.append(result.visual_issues[0])

    functional = result.functional_result
    if functional is not None and functional.rationale:
        if not parts or functional.rationale not in parts[-1]:
            parts.append(f"VLM: {functional.rationale}")

    if result.confidence is not None:
        parts.append(f"confidence={result.confidence:.2f}")

    text = " — ".join(part.strip() for part in parts if part and part.strip())
    return text[:800] if text else None


def _aggregate_status(ac_results: Iterable[LedgerACResult]) -> str:
    statuses = [ac.status for ac in ac_results]
    if not statuses:
        return STATUS_NOT_IMPLEMENTED
    if any(s == STATUS_BROKEN for s in statuses):
        return STATUS_BROKEN
    if all(s == STATUS_PASSING for s in statuses):
        return STATUS_PASSING
    return STATUS_NOT_IMPLEMENTED


def _summary_for(aggregate: str, ac_results: Iterable[LedgerACResult]) -> str:
    results = list(ac_results)
    total = len(results)
    passing = sum(1 for ac in results if ac.status == STATUS_PASSING)
    broken = sum(1 for ac in results if ac.status == STATUS_BROKEN)
    return f"{aggregate}: {passing}/{total} AC passing, {broken} broken"


def _advance_cursor(ledger: LedgerDocument) -> str | None:
    for story_id, entry in ledger.entries.items():
        if entry.status in _OPEN_STATUSES:
            return story_id
    return ledger.cursor
