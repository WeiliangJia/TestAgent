from __future__ import annotations

from app.analyzer.lightweight_analyzer import LightweightAnalyzer
from app.models.evidence import (
    AssertionResult,
    FunctionalResult,
    StepEvidence,
    UIResult,
)
from app.models.evidence import TestCaseResult as AgentTestCaseResult
from app.models.test_case import TestCase as ModelTestCase


def _tc(tc_id: str = "TC-1", ac_id: str = "AC-1") -> ModelTestCase:
    return ModelTestCase(
        test_case_id=tc_id,
        req_id="R-01",
        story_id="R-01.US-01",
        ac_id=ac_id,
        story="Story",
        expected="Dashboard visible",
        test_type="integration",
        steps=[],
    )


def _passed_step(url: str = "https://example.test") -> StepEvidence:
    return StepEvidence(step="Execute", status="passed", current_url=url)


def test_passed_assertion_returns_none() -> None:
    analyzer = LightweightAnalyzer()
    analysis = analyzer.classify(
        evidence=_passed_step(),
        assertion=AssertionResult(status="passed", confidence=0.9),
        test_case=_tc(),
    )
    assert analysis is None


def test_execution_not_passed_is_environment_error() -> None:
    analyzer = LightweightAnalyzer()
    evidence = StepEvidence(
        step="Execute",
        status="failed",
        current_url="https://example.test",
        notes=["agent exited before reaching page"],
    )
    assertion = AssertionResult(
        status="failed", confidence=0.9, errors=["Browser execution did not complete"]
    )
    analysis = analyzer.classify(
        evidence=evidence, assertion=assertion, test_case=_tc()
    )
    assert analysis is not None
    assert analysis.category == "environment_error"
    assert analysis.scores["environment_error"] >= 3.0


def test_low_confidence_is_test_fragility() -> None:
    analyzer = LightweightAnalyzer(low_confidence_threshold=0.5)
    assertion = AssertionResult(status="failed", confidence=0.3)
    analysis = analyzer.classify(
        evidence=_passed_step(), assertion=assertion, test_case=_tc()
    )
    assert analysis is not None
    assert analysis.category == "test_fragility"


def test_high_confidence_errors_is_product_bug() -> None:
    analyzer = LightweightAnalyzer(low_confidence_threshold=0.5)
    assertion = AssertionResult(
        status="failed",
        confidence=0.85,
        errors=["Expected button not found on rendered page"],
    )
    analysis = analyzer.classify(
        evidence=_passed_step(), assertion=assertion, test_case=_tc()
    )
    assert analysis is not None
    assert analysis.category == "product_bug"
    # test_fragility should not be in contributing since confidence is high
    assert all(
        item["category"] != "test_fragility" for item in analysis.contributing
    )


def test_visual_issues_without_noise_is_spec_drift() -> None:
    analyzer = LightweightAnalyzer(low_confidence_threshold=0.5)
    assertion = AssertionResult(
        status="failed",
        confidence=0.8,
        visual_issues=["Expected a modal but none is visible"],
    )
    analysis = analyzer.classify(
        evidence=_passed_step(), assertion=assertion, test_case=_tc()
    )
    assert analysis is not None
    assert analysis.category == "spec_drift"


def test_contributing_lists_secondary_categories() -> None:
    analyzer = LightweightAnalyzer(low_confidence_threshold=0.5)
    # Failed execution AND low confidence AND network failures → environment wins
    # but test_fragility / product_bug should appear in contributing.
    evidence = StepEvidence(
        step="Execute",
        status="passed",
        current_url="https://example.test",
        network_failures=["Failed to fetch /api/chat"],
        console_errors=["TypeError: Cannot read x"],
    )
    assertion = AssertionResult(
        status="failed",
        confidence=0.3,
        errors=["Chat response never arrived"],
    )
    analysis = analyzer.classify(
        evidence=evidence, assertion=assertion, test_case=_tc()
    )
    assert analysis is not None
    categories_with_score = {
        c for c, s in analysis.scores.items() if s > 0
    }
    assert {"environment_error", "test_fragility"}.issubset(categories_with_score)
    assert analysis.contributing, "expected contributing categories to be populated"


def test_aggregate_run_shared_console_error_escalates_to_product_bug() -> None:
    analyzer = LightweightAnalyzer(
        low_confidence_threshold=0.5, aggregation_min_cases=2
    )
    results: list[AgentTestCaseResult] = []
    for idx in range(3):
        evidence = StepEvidence(
            step="Execute",
            status="passed",
            current_url=f"https://example.test/case-{idx}",
            console_errors=["TypeError: Cannot read property id of undefined"],
        )
        assertion = AssertionResult(
            status="failed",
            confidence=0.3,
            visual_issues=["page looks empty"],
        )
        analysis = analyzer.classify(
            evidence=evidence, assertion=assertion, test_case=_tc(tc_id=f"TC-{idx}")
        )
        assert analysis is not None
        results.append(
            AgentTestCaseResult(
                test_case_id=f"TC-{idx}",
                req_id="R-01",
                story="Story",
                status="failed",
                failure_type=analysis.category,
                confidence=0.3,
                steps=[evidence],
                errors=[],
                visual_issues=[],
                failure_analysis=analysis,
                functional_result=FunctionalResult(result="FAIL"),
                ui_result=UIResult(result="SKIPPED"),
            )
        )

    # Before aggregation: low confidence → test_fragility wins.
    assert all(r.failure_analysis.category == "test_fragility" for r in results)

    analyzer.aggregate_run(results)

    # After aggregation: shared console error boosts product_bug enough to flip.
    assert all(r.failure_analysis.category == "product_bug" for r in results)
    assert all(r.failure_type == "product_bug" for r in results)
    assert all(
        "Cross-case escalation" in r.failure_analysis.root_cause for r in results
    )


def test_aggregate_run_below_min_cases_is_noop() -> None:
    analyzer = LightweightAnalyzer(
        low_confidence_threshold=0.5, aggregation_min_cases=3
    )
    evidence = StepEvidence(
        step="Execute",
        status="passed",
        current_url="https://example.test",
        console_errors=["Boom"],
    )
    assertion = AssertionResult(status="failed", confidence=0.3)
    analysis = analyzer.classify(
        evidence=evidence, assertion=assertion, test_case=_tc()
    )
    result = AgentTestCaseResult(
        test_case_id="TC-1",
        req_id="R-01",
        story="Story",
        status="failed",
        failure_type=analysis.category,
        confidence=0.3,
        steps=[evidence],
        errors=[],
        visual_issues=[],
        failure_analysis=analysis,
    )
    analyzer.aggregate_run([result])
    assert result.failure_analysis.category == "test_fragility"
    assert "Cross-case" not in result.failure_analysis.root_cause


def test_classify_timeout_builds_environment_error() -> None:
    analyzer = LightweightAnalyzer()
    analysis = analyzer.classify_timeout(
        test_case=_tc(tc_id="TC-T", ac_id="AC-T"),
        message="timed out after 180s",
        target_url="https://example.test",
    )
    assert analysis.category == "environment_error"
    assert analysis.scores["environment_error"] == 4.0
    assert any("current_url:" in ref for ref in analysis.evidence)
