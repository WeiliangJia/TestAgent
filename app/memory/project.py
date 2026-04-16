from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ProjectMemory:
    """L1 — short-term memory scoped by project_id.

    Stores PRD summaries and condensed histories of past test runs so the
    orchestrator can recall recent context for a given project_id across
    separate test runs.
    """

    def __init__(self, sqlite_path: Path) -> None:
        self.sqlite_path = sqlite_path
        self._lock = threading.RLock()

    def initialize(self) -> None:
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS project_memory (
                    project_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    key TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (project_id, kind, key)
                )
                """
            )
            conn.commit()

    def put(self, *, project_id: str, kind: str, key: str, content: Any) -> None:
        now = _now()
        payload = json.dumps(content, ensure_ascii=True)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO project_memory (project_id, kind, key, content_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, kind, key) DO UPDATE SET
                    content_json = excluded.content_json,
                    updated_at = excluded.updated_at
                """,
                (project_id, kind, key, payload, now, now),
            )
            conn.commit()

    def list(
        self, *, project_id: str, kind: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            if kind:
                rows = conn.execute(
                    "SELECT project_id, kind, key, content_json, updated_at "
                    "FROM project_memory WHERE project_id = ? AND kind = ? "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (project_id, kind, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT project_id, kind, key, content_json, updated_at "
                    "FROM project_memory WHERE project_id = ? "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (project_id, limit),
                ).fetchall()
        return [
            {
                "project_id": row["project_id"],
                "kind": row["kind"],
                "key": row["key"],
                "content": json.loads(row["content_json"]),
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def remember_prd_summary(
        self, *, project_id: str, summary: str, requirement_count: int
    ) -> None:
        self.put(
            project_id=project_id,
            kind="prd_summary",
            key="latest",
            content={"summary": summary, "requirementCount": requirement_count},
        )

    def remember_run(self, *, project_id: str, test_id: str, digest: dict[str, Any]) -> None:
        self.put(project_id=project_id, kind="run_digest", key=test_id, content=digest)

    def to_prompt_context(self, *, project_id: str, limit: int = 8) -> str:
        entries = self.list(project_id=project_id, limit=limit)
        if not entries:
            return f"L1 (project {project_id}): no prior history."
        lines = [f"L1 (project {project_id}):"]
        for entry in entries:
            lines.append(f"- [{entry['kind']}:{entry['key']}] {_short(entry['content'])}")
        return "\n".join(lines)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short(content: Any, limit: int = 180) -> str:
    text = json.dumps(content, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"
