from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_DEFAULT_SEED: list[dict[str, Any]] = [
    {
        "kind": "spec_template",
        "key": "gherkin_basic",
        "content": {
            "description": "Default BDD scenario shape.",
            "structure": ["Feature", "Scenario", "Given", "When", "Then"],
            "notes": "Use one Then per acceptance criterion.",
        },
    },
    {
        "kind": "assertion_rule",
        "key": "login_success",
        "content": {
            "pattern": "successful_login",
            "expected_signals": ["logout", "dashboard", "welcome", "my account"],
            "negative_signals": ["invalid", "incorrect", "try again"],
        },
    },
    {
        "kind": "assertion_rule",
        "key": "search_success",
        "content": {
            "pattern": "search_results_visible",
            "expected_signals": ["result", "found", "matches", "items"],
            "negative_signals": ["no results", "not found", "0 results"],
        },
    },
    {
        "kind": "lesson",
        "key": "network_failures_are_environment",
        "content": {
            "rule": "Treat requestfailed signals as environment_error before blaming the product.",
        },
    },
]


class PermanentMemory:
    """L0 — agent-wide permanent memory.

    Stores spec templates, assertion patterns, and cross-project lessons that
    apply to every project and every run. Seeded on first initialize.
    """

    def __init__(self, sqlite_path: Path) -> None:
        self.sqlite_path = sqlite_path
        self._lock = threading.RLock()

    def initialize(self) -> None:
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS permanent_memory (
                    kind TEXT NOT NULL,
                    key TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (kind, key)
                )
                """
            )
            conn.commit()
        self._seed_defaults()

    def put(self, *, kind: str, key: str, content: Any) -> None:
        now = _now()
        payload = json.dumps(content, ensure_ascii=True)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO permanent_memory (kind, key, content_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(kind, key) DO UPDATE SET
                    content_json = excluded.content_json,
                    updated_at = excluded.updated_at
                """,
                (kind, key, payload, now, now),
            )
            conn.commit()

    def get(self, *, kind: str, key: str) -> Any | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT content_json FROM permanent_memory WHERE kind = ? AND key = ?",
                (kind, key),
            ).fetchone()
        return json.loads(row["content_json"]) if row else None

    def list_by_kind(self, kind: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT kind, key, content_json, updated_at FROM permanent_memory "
                "WHERE kind = ? ORDER BY updated_at DESC",
                (kind,),
            ).fetchall()
        return [
            {
                "kind": row["kind"],
                "key": row["key"],
                "content": json.loads(row["content_json"]),
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def to_prompt_context(self) -> str:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT kind, key, content_json FROM permanent_memory ORDER BY kind, key"
            ).fetchall()
        if not rows:
            return "L0 (permanent): empty."
        lines = ["L0 (permanent):"]
        for row in rows:
            lines.append(
                f"- [{row['kind']}:{row['key']}] {_short(json.loads(row['content_json']))}"
            )
        return "\n".join(lines)

    def _seed_defaults(self) -> None:
        with self._lock, self._connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM permanent_memory"
            ).fetchone()["n"]
        if count:
            return
        for item in _DEFAULT_SEED:
            self.put(kind=item["kind"], key=item["key"], content=item["content"])

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short(content: Any, limit: int = 180) -> str:
    text = json.dumps(content, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"
