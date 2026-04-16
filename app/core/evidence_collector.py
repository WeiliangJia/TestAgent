from __future__ import annotations

from pathlib import Path

from app.integrations.browser_use_client import BrowserExecution
from app.models.evidence import StepEvidence
from app.models.test_case import TestCase
from app.storage.file_store import FileStore


class EvidenceCollector:
    def __init__(self, evidence_root: Path) -> None:
        self.file_store = FileStore(evidence_root)

    def persist(
        self,
        *,
        project_id: str,
        test_id: str,
        test_case: TestCase,
        execution: BrowserExecution,
    ) -> StepEvidence:
        base = f"{project_id}/{test_id}/{test_case.test_case_id}"
        dom_path = self.file_store.write_text("".join([base, "-dom.html"]), execution.dom_snapshot)
        meta_path = self.file_store.write_json(
            "".join([base, "-meta.json"]),
            {
                "currentUrl": execution.current_url,
                "consoleErrors": execution.console_errors,
                "networkFailures": execution.network_failures,
                "notes": execution.notes,
            },
        )
        return StepEvidence(
            step=f"Execute {test_case.test_case_id}",
            status=execution.status,
            current_url=execution.current_url,
            screenshot_path=str(execution.screenshot_path),
            dom_snapshot_path=str(dom_path),
            console_errors=execution.console_errors,
            network_failures=execution.network_failures,
            notes=[*execution.notes, f"Metadata: {meta_path}"],
        )
