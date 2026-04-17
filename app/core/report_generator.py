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
    ) -> dict[str, Any]:
        result_dicts = [item.to_dict() for item in results]
        summary = {
            "total": len(results),
            "passed": sum(1 for item in results if item.status == "passed"),
            "failed": sum(1 for item in results if item.status == "failed"),
            "warnings": sum(1 for item in results if item.status == "warning"),
        }
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
            "status": "completed" if summary["failed"] == 0 else "failed",
            "targetUrl": target_url,
            "requirement": requirement.to_dict(),
            "userStory": user_story.to_dict(),
            "summary": summary,
            "rtm": enriched_rtm,
            "stories": [bdd_story.to_dict()],
            "testCases": [case.to_dict() for case in test_cases],
            "results": result_dicts,
        }
        report_path = self.file_store.write_json(f"{project_id}/{test_id}.json", report)
        report["reportPath"] = str(report_path)
        return report
