from __future__ import annotations

from app.models.evidence import AssertionResult, FailureAnalysis, StepEvidence
from app.models.test_case import TestCase


class LightweightAnalyzer:
    """Four-category failure attribution aligned with the architecture doc.

    Categories:
      - product_bug       — page returns an expected outcome that is visibly wrong,
                            VLM reports high-confidence failure, or UI defect is
                            critical while execution succeeded.
      - test_fragility    — VLM reports low confidence or the screenshot/DOM is
                            non-diagnostic; the test itself may be the cause.
      - environment_error — browser execution failed, network errors, or per-story
                            timeout fired.
      - spec_drift        — expected outcome does not correspond to anything visible
                            on a rendered, error-free page (heuristic: VLM fails
                            cleanly with low-severity signals and no console/network
                            noise).
    """

    def classify(
        self,
        *,
        evidence: StepEvidence,
        assertion: AssertionResult,
        test_case: TestCase | None = None,
    ) -> FailureAnalysis | None:
        if assertion.status == "passed":
            return None

        ctx = _context_prefix(test_case, evidence)
        rationale_tail = _rationale_tail(assertion)

        # Environment first — it pre-empts anything else.
        if evidence.status != "passed":
            last_note = (evidence.notes[-1] if evidence.notes else "").strip()[:240]
            return FailureAnalysis(
                category="environment_error",
                root_cause=(
                    f"{ctx}Browser execution did not reach the assertion stage "
                    f"(step.status={evidence.status}). "
                    f"Last note: {last_note or '(none)'}.{rationale_tail}"
                ),
                evidence=_evidence_refs(evidence, assertion),
            )
        if evidence.network_failures:
            sample = "; ".join(evidence.network_failures[:3])
            return FailureAnalysis(
                category="environment_error",
                root_cause=(
                    f"{ctx}Network failures observed during execution "
                    f"({len(evidence.network_failures)} total): {sample}."
                    f"{rationale_tail}"
                ),
                evidence=_evidence_refs(evidence, assertion),
            )
        if assertion.status == "timeout":
            return FailureAnalysis(
                category="environment_error",
                root_cause=(
                    f"{ctx}Per-case timeout fired before the assertion returned a verdict."
                    f"{rationale_tail}"
                ),
                evidence=_evidence_refs(evidence, assertion),
            )

        # Confidence-based split between product_bug and test_fragility.
        if assertion.confidence < 0.5:
            return FailureAnalysis(
                category="test_fragility",
                root_cause=(
                    f"{ctx}Assertion verdict has low confidence "
                    f"({assertion.confidence:.2f}); the screenshot or DOM may be "
                    "non-diagnostic (e.g. page not fully loaded, wrong URL, lazy "
                    f"content).{rationale_tail}"
                ),
                evidence=_evidence_refs(evidence, assertion),
            )

        if assertion.errors:
            # High-confidence hard failure with concrete errors → product bug.
            return FailureAnalysis(
                category="product_bug",
                root_cause=(
                    f"{ctx}{assertion.errors[0][:360]}"
                    f" (confidence={assertion.confidence:.2f}){rationale_tail}"
                ),
                evidence=_evidence_refs(evidence, assertion),
            )

        # No concrete errors, VLM flagged only visual issues → spec drift candidate.
        if assertion.visual_issues and not evidence.console_errors:
            issue_sample = "; ".join(
                issue[:160] for issue in assertion.visual_issues[:2]
            )
            return FailureAnalysis(
                category="spec_drift",
                root_cause=(
                    f"{ctx}Rendered page is error-free but does not visibly match "
                    f"the expected outcome. VLM observations: {issue_sample}."
                    f"{rationale_tail}"
                ),
                evidence=_evidence_refs(evidence, assertion),
            )

        return FailureAnalysis(
            category="product_bug",
            root_cause=(
                f"{ctx}Assertion failed without a more specific signal "
                f"(confidence={assertion.confidence:.2f}).{rationale_tail}"
            ),
            evidence=_evidence_refs(evidence, assertion),
        )


def _context_prefix(test_case: TestCase | None, evidence: StepEvidence) -> str:
    parts: list[str] = []
    if test_case is not None:
        if test_case.test_case_id:
            parts.append(test_case.test_case_id)
        if test_case.ac_id:
            parts.append(f"ac={test_case.ac_id}")
        expected = (test_case.expected or "").strip()
        if expected:
            parts.append(f"expected={expected[:120]}")
    if evidence.current_url:
        parts.append(f"url={evidence.current_url}")
    return f"[{' | '.join(parts)}] " if parts else ""


def _rationale_tail(assertion: AssertionResult) -> str:
    # Pull the "Functional: …" marker produced by AssertionEngine so the
    # verbatim VLM rationale is always visible in the root cause.
    for issue in assertion.visual_issues:
        if isinstance(issue, str) and issue.startswith("Functional: "):
            return f" VLM rationale: {issue[len('Functional: '):][:240]}"
    return ""


def _evidence_refs(evidence: StepEvidence, assertion: AssertionResult) -> list[str]:
    refs: list[str] = []
    if evidence.screenshot_path:
        refs.append(f"screenshot:{evidence.screenshot_path}")
    if evidence.dom_snapshot_path:
        refs.append(f"dom:{evidence.dom_snapshot_path}")
    for network in evidence.network_failures[:3]:
        refs.append(f"network:{network}")
    for console in evidence.console_errors[:3]:
        refs.append(f"console:{console}")
    for err in assertion.errors[:3]:
        refs.append(f"assertion:{err[:160]}")
    return refs
