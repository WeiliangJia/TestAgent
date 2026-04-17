from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class LedgerACResult:
    status: str = "not_implemented"
    last_checked: str | None = None
    evidence: str | None = None
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "lastChecked": self.last_checked,
            "evidence": self.evidence,
            "failureReason": self.failure_reason,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "LedgerACResult":
        raw = raw or {}
        return cls(
            status=str(raw.get("status") or "not_implemented"),
            last_checked=_opt_str(raw.get("lastChecked")),
            evidence=_opt_str(raw.get("evidence")),
            failure_reason=_opt_str(raw.get("failureReason")),
        )


@dataclass(slots=True)
class LedgerEntry:
    story_id: str
    status: str = "not_implemented"
    summary: str | None = None
    last_checked: str | None = None
    checked_by_run: str | None = None
    retry_count: int = 0
    stuck_reason: str | None = None
    ac_results: dict[str, LedgerACResult] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "lastChecked": self.last_checked,
            "checkedByRun": self.checked_by_run,
            "retryCount": self.retry_count,
            "stuckReason": self.stuck_reason,
            "acResults": {ac_id: ac.to_dict() for ac_id, ac in self.ac_results.items()},
        }

    @classmethod
    def from_dict(cls, story_id: str, raw: dict[str, Any] | None) -> "LedgerEntry":
        raw = raw or {}
        ac_raw = raw.get("acResults") or {}
        ac_results: dict[str, LedgerACResult] = {}
        if isinstance(ac_raw, dict):
            for ac_id, ac_val in ac_raw.items():
                ac_results[str(ac_id)] = LedgerACResult.from_dict(
                    ac_val if isinstance(ac_val, dict) else None
                )
        retry = raw.get("retryCount")
        return cls(
            story_id=story_id,
            status=str(raw.get("status") or "not_implemented"),
            summary=_opt_str(raw.get("summary")),
            last_checked=_opt_str(raw.get("lastChecked")),
            checked_by_run=_opt_str(raw.get("checkedByRun")),
            retry_count=int(retry) if isinstance(retry, int) else 0,
            stuck_reason=_opt_str(raw.get("stuckReason")),
            ac_results=ac_results,
        )


@dataclass(slots=True)
class LedgerDocument:
    project_id: str
    cursor: str | None = None
    last_updated: str | None = None
    schema: str = "sage-loop-ledger-v1"
    entries: dict[str, LedgerEntry] = field(default_factory=dict)
    source_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "$schema": self.schema,
            "projectId": self.project_id,
            "cursor": self.cursor,
            "lastUpdated": self.last_updated,
            "entries": {sid: entry.to_dict() for sid, entry in self.entries.items()},
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any], *, source_path: str | None = None) -> "LedgerDocument":
        if not isinstance(raw, dict):
            raise ValueError("Ledger JSON must be an object.")
        entries_raw = raw.get("entries") or {}
        if not isinstance(entries_raw, dict):
            raise ValueError("Ledger 'entries' must be a JSON object.")
        entries: dict[str, LedgerEntry] = {}
        for story_id, entry_raw in entries_raw.items():
            entries[str(story_id)] = LedgerEntry.from_dict(
                str(story_id), entry_raw if isinstance(entry_raw, dict) else None
            )
        return cls(
            project_id=str(raw.get("projectId") or ""),
            cursor=_opt_str(raw.get("cursor")),
            last_updated=_opt_str(raw.get("lastUpdated")),
            schema=str(raw.get("$schema") or "sage-loop-ledger-v1"),
            entries=entries,
            source_path=source_path,
        )


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
