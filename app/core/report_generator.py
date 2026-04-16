from __future__ import annotations

from pathlib import Path

from app.models.evidence import TestCaseResult
from app.models.test_case import BDDStory, TestCase
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
        rtm: list[dict],
        stories: list[BDDStory],
        test_cases: list[TestCase],
        results: list[TestCaseResult],
    ) -> dict:
        result_dicts = [item.to_dict() for item in results]
        summary = {
            "total": len(results),
            "passed": sum(1 for item in results if item.status == "passed"),
            "failed": sum(1 for item in results if item.status == "failed"),
            "warnings": sum(1 for item in results if item.status == "warning"),
        }
        test_case_ids_by_req = _map_test_cases_to_requirements(test_cases)
        enriched_rtm = [
            {
                **requirement,
                "testCaseIds": test_case_ids_by_req.get(requirement["reqId"], []),
            }
            for requirement in rtm
        ]
        report = {
            "projectId": project_id,
            "testId": test_id,
            "status": "completed" if summary["failed"] == 0 else "failed",
            "targetUrl": target_url,
            "summary": summary,
            "rtm": enriched_rtm,
            "stories": [story.to_dict() for story in stories],
            "testCases": [test_case.to_dict() for test_case in test_cases],
            "results": result_dicts,
        }
        report_path = self.file_store.write_json(f"{project_id}/{test_id}.json", report)
        report["reportPath"] = str(report_path)
        return report


def _map_test_cases_to_requirements(test_cases: list[TestCase]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for test_case in test_cases:
        mapping.setdefault(test_case.req_id, []).append(test_case.test_case_id)
    return mapping
