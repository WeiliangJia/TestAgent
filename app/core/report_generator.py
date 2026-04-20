from __future__ import annotations

from pathlib import Path
from typing import Any

from app.models.evidence import TestCaseResult
from app.models.test_case import BDDStory, PRDDocument, Requirement, TestCase, UserStory
from app.storage.file_store import FileStore


class ReportGenerator:
    def __init__(self, report_root: Path) -> None:
        self.file_store = FileStore(report_root)

    def generate(
        self,
        *,
        project_id: str,
        test_id: str,
        target_url: str,
        document: PRDDocument,
        requirement: Requirement,
        user_story: UserStory,
        rtm: list[dict[str, Any]],
        bdd_story: BDDStory,
        test_cases: list[TestCase],
        results: list[TestCaseResult],
        ledger_delta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result_dicts = [item.to_dict() for item in results]
        summary = _build_summary(results)
        overall_status = _overall_status(results)
        enriched_rtm = [
            {
                **entry,
                "testCaseIds": [case.test_case_id for case in test_cases],
            }
            for entry in rtm
        ]
        report: dict[str, Any] = {
            "projectId": project_id,
            "testId": test_id,
            "prdProject": document.project,
            "prdVersion": document.version,
            "status": overall_status,
            "targetUrl": target_url,
            "requirement": requirement.to_dict(),
            "userStory": user_story.to_dict(),
            "summary": summary,
            "rtm": enriched_rtm,
            "stories": [bdd_story.to_dict()],
            "testCases": [case.to_dict() for case in test_cases],
            "results": result_dicts,
        }
        if ledger_delta is not None:
            report["ledgerUpdate"] = ledger_delta
        report_path = self.file_store.write_json(f"{project_id}/{test_id}.json", report)
        report["reportPath"] = str(report_path)
        return report


def _build_summary(results: list[TestCaseResult]) -> dict[str, Any]:
    total = len(results)
    # Overall status buckets (pre-split).
    overall_passed = sum(1 for r in results if r.status == "passed")
    overall_failed = sum(1 for r in results if r.status == "failed")
    overall_warnings = sum(1 for r in results if r.status == "warning")
    overall_skipped = sum(1 for r in results if r.status == "skipped")

    # Functional dimension (Layer 1).
    functional_passed = 0
    functional_failed = 0
    functional_skipped = 0
    for result in results:
        fr = result.functional_result
        if fr is None:
            continue
        if fr.result == "PASS":
            functional_passed += 1
        elif fr.result == "FAIL":
            functional_failed += 1
        elif fr.result == "SKIPPED":
            functional_skipped += 1

    # UI dimension (Layer 2).
    ui_passed = 0
    ui_failed = 0
    ui_warning = 0
    ui_skipped = 0
    for result in results:
        ur = result.ui_result
        if ur is None:
            continue
        if ur.result == "PASS":
            ui_passed += 1
        elif ur.result == "FAIL":
            ui_failed += 1
        elif ur.result == "WARNING":
            ui_warning += 1
        elif ur.result == "SKIPPED":
            ui_skipped += 1

    return {
        "total": total,
        "passed": overall_passed,
        "failed": overall_failed,
        "warnings": overall_warnings,
        "skipped": overall_skipped,
        "functionalPassed": functional_passed,
        "functionalFailed": functional_failed,
        "functionalSkipped": functional_skipped,
        "uiPassed": ui_passed,
        "uiWarning": ui_warning,
        "uiFailed": ui_failed,
        "uiSkipped": ui_skipped,
    }


def _overall_status(results: list[TestCaseResult]) -> str:
    if any(r.status == "failed" for r in results):
        return "failed"
    if all(r.status == "skipped" for r in results) and results:
        return "skipped"
    return "completed"
