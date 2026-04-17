from __future__ import annotations

from app.cli import _terminal_report_summary


def test_terminal_report_summary_omits_large_story_json() -> None:
    payload = _terminal_report_summary(
        {
            "project_id": "local-demo",
            "test_id": "test_123",
            "status": "completed",
            "target_url": "http://127.0.0.1:3000",
            "report": {
                "projectId": "local-demo",
                "testId": "test_123",
                "status": "completed",
                "targetUrl": "http://127.0.0.1:3000",
                "requirement": {
                    "id": "R-01",
                    "name": "Requirement",
                    "description": "Large requirement body",
                    "userStories": [{"id": "R-01.US-01"}],
                },
                "userStory": {
                    "id": "R-01.US-01",
                    "title": "Story title",
                    "description": "Large story body",
                    "acceptanceCriteria": [{"id": "AC-01"}],
                },
                "summary": {"total": 1, "passed": 1, "failed": 0, "warnings": 0},
                "results": [{"testCaseId": "TC-001", "status": "passed"}],
                "reportPath": "data/reports/local-demo/test_123.json",
            },
        },
        "R-01.US-01",
    )

    assert payload["userStory"] == {"id": "R-01.US-01", "title": "Story title"}
    assert payload["requirement"] == {
        "id": "R-01",
        "name": "Requirement",
    }
    assert "acceptanceCriteria" not in payload["userStory"]
    assert "userStories" not in payload["requirement"]
