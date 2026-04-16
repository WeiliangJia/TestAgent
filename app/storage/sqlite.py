from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SQLiteStore:
    def __init__(self, sqlite_path: Path) -> None:
        self.sqlite_path = sqlite_path
        self._lock = threading.RLock()

    def initialize(self) -> None:
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS test_runs (
                    project_id TEXT NOT NULL,
                    test_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    target_url TEXT NOT NULL,
                    prd_content TEXT,
                    rtm_json TEXT,
                    stories_json TEXT,
                    test_cases_json TEXT,
                    results_json TEXT,
                    evidence_json TEXT,
                    report_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (project_id, test_id)
                )
                """
            )
            conn.commit()

    def create_run(
        self,
        *,
        project_id: str,
        test_id: str,
        target_url: str,
        prd_content: str | None,
    ) -> None:
        now = _now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO test_runs (
                    project_id, test_id, status, target_url, prd_content,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (project_id, test_id, "queued", target_url, prd_content, now, now),
            )
            conn.commit()

    def update_run(
        self,
        *,
        project_id: str,
        test_id: str,
        status: str | None = None,
        rtm: Any | None = None,
        stories: Any | None = None,
        test_cases: Any | None = None,
        results: Any | None = None,
        evidence: Any | None = None,
        report: Any | None = None,
        error: str | None = None,
    ) -> None:
        fields: list[str] = []
        values: list[Any] = []
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if rtm is not None:
            fields.append("rtm_json = ?")
            values.append(json.dumps(rtm, ensure_ascii=True))
        if stories is not None:
            fields.append("stories_json = ?")
            values.append(json.dumps(stories, ensure_ascii=True))
        if test_cases is not None:
            fields.append("test_cases_json = ?")
            values.append(json.dumps(test_cases, ensure_ascii=True))
        if results is not None:
            fields.append("results_json = ?")
            values.append(json.dumps(results, ensure_ascii=True))
        if evidence is not None:
            fields.append("evidence_json = ?")
            values.append(json.dumps(evidence, ensure_ascii=True))
        if report is not None:
            fields.append("report_json = ?")
            values.append(json.dumps(report, ensure_ascii=True))
        if error is not None:
            fields.append("error = ?")
            values.append(error)

        fields.append("updated_at = ?")
        values.append(_now())
        values.extend([project_id, test_id])

        with self._lock, self._connect() as conn:
            conn.execute(
                f"""
                UPDATE test_runs
                SET {", ".join(fields)}
                WHERE project_id = ? AND test_id = ?
                """,
                values,
            )
            conn.commit()

    def get_run(self, *, test_id: str, project_id: str | None = None) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            if project_id:
                row = conn.execute(
                    "SELECT * FROM test_runs WHERE project_id = ? AND test_id = ?",
                    (project_id, test_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM test_runs WHERE test_id = ? ORDER BY created_at DESC LIMIT 1",
                    (test_id,),
                ).fetchone()
        if not row:
            return None
        return _row_to_dict(row)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    for source, target in [
        ("rtm_json", "rtm"),
        ("stories_json", "stories"),
        ("test_cases_json", "test_cases"),
        ("results_json", "results"),
        ("evidence_json", "evidence"),
        ("report_json", "report"),
    ]:
        raw = data.pop(source, None)
        data[target] = json.loads(raw) if raw else None
    return data


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
