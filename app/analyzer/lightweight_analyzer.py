from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from app.models.evidence import (
    AssertionResult,
    FailureAnalysis,
    StepEvidence,
    TestCaseResult,
)
from app.models.test_case import TestCase


_CATEGORIES = ("environment_error", "product_bug", "test_fragility", "spec_drift")


class LightweightAnalyzer:
    """Weighted multi-signal failure attribution.

    Each evidence signal contributes a score to one or more categories; the
    argmax becomes ``primary`` and the other non-zero categories become
    ``contributing``. Thresholds are wired through Settings so tuning does
    not require a code edit.

    Categories:
      - product_bug       — high-confidence assertion errors, console errors on
                            a fully-loaded page, VLM visibly says the expected
                            outcome is wrong.
      - test_fragility    — VLM confidence is low; screenshot/DOM is
                            non-diagnostic, the test itself may be the cause.
      - environment_error — browser execution failed, network errors, timeout.
      - spec_drift        — rendered page is clean but does not match the AC;
                            AC may be outdated.
    """

    def __init__(
        self,
        *,
        low_confidence_threshold: float = 0.5,
        aggregation_min_cases: int = 2,
    ) -> None:
        self.low_confidence_threshold = low_confidence_threshold
        self.aggregation_min_cases = aggregation_min_cases

    def classify(
        self,
        *,
        evidence: StepEvidence,
        assertion: AssertionResult,
        test_case: TestCase | None = None,
    ) -> FailureAnalysis | None:
        if assertion.status == "passed":
            return None

        scores = self._score(evidence=evidence, assertion=assertion)
        if max(scores.values()) <= 0.0:
            # Assertion failed but no signal pointed anywhere — default to product_bug.
            scores["product_bug"] = 1.0

        primary = _argmax(scores)
        contributing = _contributing(scores, primary)
        root_cause = self._build_root_cause(
            primary=primary,
            test_case=test_case,
            evidence=evidence,
            assertion=assertion,
        )
        return FailureAnalysis(
            category=primary,
            root_cause=root_cause,
            evidence=_evidence_refs(evidence, assertion),
            contributing=contributing,
            scores={c: round(s, 2) for c, s in scores.items()},
        )

    def classify_timeout(
        self,
        *,
        test_case: TestCase,
        message: str,
        target_url: str,
    ) -> FailureAnalysis:
        scores = {c: 0.0 for c in _CATEGORIES}
        scores["environment_error"] = 4.0
        refs = [f"current_url:{target_url}"] if target_url else []
        if test_case.test_case_id:
            refs.append(f"test_case:{test_case.test_case_id}")
        return FailureAnalysis(
            category="environment_error",
            root_cause=message,
            evidence=refs,
            contributing=[],
            scores=scores,
        )

    def aggregate_run(self, results: list[TestCaseResult]) -> None:
        """Second pass: escalate attribution using cross-case shared signals.

        Mutates ``results`` in place. Any case whose scores shift to a new
        primary category gets its ``failure_type`` updated to match.
        """
        failing = [r for r in results if r.failure_analysis is not None]
        if len(failing) < self.aggregation_min_cases:
            return

        url_groups: dict[str, list[TestCaseResult]] = defaultdict(list)
        console_groups: dict[str, list[TestCaseResult]] = defaultdict(list)
        network_groups: dict[str, list[TestCaseResult]] = defaultdict(list)

        for r in failing:
            seen_urls: set[str] = set()
            seen_console: set[str] = set()
            seen_network: set[str] = set()
            for step in r.steps:
                url = (step.current_url or "").strip()
                if url and url not in seen_urls:
                    url_groups[url].append(r)
                    seen_urls.add(url)
                for err in step.console_errors:
                    key = _normalize_signal(err)
                    if key and key not in seen_console:
                        console_groups[key].append(r)
                        seen_console.add(key)
                for net in step.network_failures:
                    key = _normalize_signal(net)
                    if key and key not in seen_network:
                        network_groups[key].append(r)
                        seen_network.add(key)

        for url, group in url_groups.items():
            if len(group) >= self.aggregation_min_cases:
                note = (
                    f"shared URL {url} across {len(group)} failing cases — "
                    "likely environmental / same endpoint"
                )
                for r in group:
                    _boost(r, "environment_error", 1.5, note)

        for err, group in console_groups.items():
            if len(group) >= self.aggregation_min_cases:
                note = (
                    f"shared console error across {len(group)} cases: "
                    f"{err[:120]}"
                )
                for r in group:
                    _boost(r, "product_bug", 2.0, note)

        for net, group in network_groups.items():
            if len(group) >= self.aggregation_min_cases:
                note = (
                    f"shared network failure across {len(group)} cases: "
                    f"{net[:120]}"
                )
                for r in group:
                    _boost(r, "environment_error", 2.0, note)

    def _score(
        self, *, evidence: StepEvidence, assertion: AssertionResult
    ) -> dict[str, float]:
        scores = {c: 0.0 for c in _CATEGORIES}
        low = self.low_confidence_threshold

        if evidence.status != "passed":
            scores["environment_error"] += 3.0
        if evidence.network_failures:
            scores["environment_error"] += min(len(evidence.network_failures), 3) * 0.8

        if assertion.confidence < low:
            scores["test_fragility"] += 2.0 + (low - assertion.confidence) * 2.0

        if assertion.errors and assertion.confidence >= low:
            scores["product_bug"] += 2.0 + (assertion.confidence - low)
        if evidence.console_errors and evidence.status == "passed":
            scores["product_bug"] += min(len(evidence.console_errors), 3) * 0.5

        if (
            assertion.visual_issues
            and not evidence.console_errors
            and not evidence.network_failures
            and evidence.status == "passed"
            and assertion.confidence >= low
            and not assertion.errors
        ):
            scores["spec_drift"] += 1.5

        return scores

    def _build_root_cause(
        self,
        *,
        primary: str,
        test_case: TestCase | None,
        evidence: StepEvidence,
        assertion: AssertionResult,
    ) -> str:
        ctx = _context_prefix(test_case, evidence)
        tail = _rationale_tail(assertion)

        if primary == "environment_error":
            if evidence.status != "passed":
                last = (evidence.notes[-1] if evidence.notes else "").strip()[:240]
                body = (
                    f"Browser execution did not reach the assertion stage "
                    f"(step.status={evidence.status}). Last note: {last or '(none)'}."
                )
            elif evidence.network_failures:
                sample = "; ".join(evidence.network_failures[:3])
                body = (
                    f"Network failures observed during execution "
                    f"({len(evidence.network_failures)} total): {sample}."
                )
            else:
                body = "Execution-layer signals indicate an environment failure."
            return f"{ctx}{body}{tail}"

        if primary == "test_fragility":
            body = (
                f"Assertion verdict has low confidence "
                f"({assertion.confidence:.2f}); the screenshot or DOM may be "
                "non-diagnostic (page not fully loaded, wrong URL, lazy content)."
            )
            return f"{ctx}{body}{tail}"

        if primary == "spec_drift":
            sample = "; ".join(issue[:160] for issue in assertion.visual_issues[:2])
            body = (
                "Rendered page is error-free but does not visibly match the "
                f"expected outcome. VLM observations: {sample}."
            )
            return f"{ctx}{body}{tail}"

        # product_bug
        if assertion.errors:
            body = (
                f"{assertion.errors[0][:360]} "
                f"(confidence={assertion.confidence:.2f})"
            )
        else:
            body = (
                f"Assertion failed without a more specific signal "
                f"(confidence={assertion.confidence:.2f})."
            )
        return f"{ctx}{body}{tail}"


def _argmax(scores: dict[str, float]) -> str:
    return max(scores, key=lambda c: (scores[c], _CATEGORIES.index(c) * -1))


def _contributing(scores: dict[str, float], primary: str) -> list[dict[str, float]]:
    return sorted(
        (
            {"category": c, "score": round(s, 2)}
            for c, s in scores.items()
            if c != primary and s > 0
        ),
        key=lambda item: item["score"],
        reverse=True,
    )


def _boost(
    result: TestCaseResult, category: str, delta: float, note: str
) -> None:
    analysis = result.failure_analysis
    if analysis is None:
        return
    analysis.scores[category] = round(analysis.scores.get(category, 0.0) + delta, 2)
    new_primary = _argmax(analysis.scores)
    analysis.contributing = _contributing(analysis.scores, new_primary)
    if new_primary != analysis.category:
        analysis.root_cause = (
            f"{analysis.root_cause} | Cross-case escalation "
            f"({analysis.category} → {new_primary}): {note}"
        )
        analysis.category = new_primary
        result.failure_type = new_primary
    else:
        analysis.root_cause = f"{analysis.root_cause} | Cross-case signal: {note}"


def _normalize_signal(raw: str) -> str:
    # Strip URLs/ids so "Failed to fetch /api/chat?id=123" and
    # "Failed to fetch /api/chat?id=456" collapse to one group.
    import re

    text = (raw or "").strip()
    if not text:
        return ""
    text = re.sub(r"\b[0-9a-fA-F]{8,}\b", "<hex>", text)
    text = re.sub(r"\b\d{3,}\b", "<n>", text)
    text = re.sub(r"\s+", " ", text)
    return text[:200]


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


__all__: Iterable[str] = ("LightweightAnalyzer",)
