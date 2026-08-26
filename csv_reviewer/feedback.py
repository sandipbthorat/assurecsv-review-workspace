"""Controlled local reviewer feedback and precedent matching.

Feedback is deliberately stored separately from the review rules. It can guide
future findings, but it cannot override a current regulation or approved
procedure and it never silently rewrites source documents.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import re
from threading import Lock
from typing import Any
from uuid import uuid4

from .models import Finding


ALLOWED_DECISIONS = {
    "Accept",
    "Accept with Modification",
    "Reject",
    "Downgrade Severity",
    "Upgrade Severity",
    "Change Category",
    "Change Suggested Wording",
    "Mark as False Positive",
    "Mark as Duplicate",
    "Convert to Observation",
    "Mark as Organization-Specific Rule",
}

POSITIVE_DECISIONS = {
    "Accept",
    "Accept with Modification",
    "Upgrade Severity",
    "Change Category",
    "Change Suggested Wording",
    "Mark as Organization-Specific Rule",
}

REJECTION_DECISIONS = {"Reject", "Mark as False Positive"}


class FeedbackStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = Lock()

    def load(self) -> list[dict[str, Any]]:
        with self._lock:
            if not self.path.exists():
                return []
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return []
            records = payload.get("records", []) if isinstance(payload, dict) else []
            return records if isinstance(records, list) else []

    def add(self, payload: dict[str, Any]) -> dict[str, Any]:
        decision = str(payload.get("reviewer_decision") or "").strip()
        if decision not in ALLOWED_DECISIONS:
            raise ValueError("Select a valid reviewer decision.")
        finding = payload.get("finding")
        if not isinstance(finding, dict) or not finding.get("finding_id"):
            raise ValueError("The feedback record must reference a finding.")
        rationale = _limited(payload.get("reviewer_rationale"), 4_000)
        if decision not in {"Accept", "Mark as Duplicate"} and not rationale:
            raise ValueError("Reviewer rationale is required for this decision.")

        now = datetime.now(UTC)
        record = {
            "feedback_id": f"FB-{now.strftime('%Y%m%d')}-{uuid4().hex[:8].upper()}",
            "review_id": _limited(payload.get("review_id"), 80),
            "finding_id": _limited(finding.get("finding_id"), 40),
            "document_type": _limited(finding.get("document_type") or finding.get("document"), 160),
            "section": _limited(finding.get("section") or finding.get("location"), 200),
            "finding_category": _limited(finding.get("finding_category") or finding.get("category"), 100),
            "original_finding": _limited(finding.get("observation"), 5_000),
            "original_severity": _limited(finding.get("severity"), 30),
            "original_confidence": _limited(finding.get("confidence_level") or finding.get("confidence"), 30),
            "original_confidence_score": int(finding.get("confidence_score") or 0),
            "original_suggested_change": _limited(finding.get("suggested_redline"), 5_000),
            "reviewer_decision": decision,
            "reviewer_revised_finding": _limited(payload.get("reviewer_revised_finding"), 5_000),
            "reviewer_revised_severity": _limited(payload.get("reviewer_revised_severity"), 30),
            "reviewer_revised_category": _limited(payload.get("reviewer_revised_category"), 100),
            "reviewer_rationale": rationale,
            "reviewer_name_role": _limited(payload.get("reviewer_name_role"), 240),
            "date": now.isoformat(),
            "applicable_procedure": _limited(payload.get("applicable_procedure"), 300),
            "procedure_revision": _limited(payload.get("procedure_revision"), 80),
            "system_type": _limited(payload.get("system_type"), 160),
            "risk_classification": _limited(payload.get("risk_classification"), 80),
            "preferred_wording": _limited(payload.get("preferred_wording"), 5_000),
            "final_resolution": _limited(payload.get("final_resolution"), 1_000) or "Recorded",
            "finding_fingerprint": _fingerprint(finding),
        }

        with self._lock:
            records: list[dict[str, Any]] = []
            if self.path.exists():
                try:
                    existing = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(existing, dict) and isinstance(existing.get("records"), list):
                        records = existing["records"]
                except (json.JSONDecodeError, OSError):
                    records = []
            records.append(record)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps({"schema_version": "1.0", "records": records}, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            temporary.replace(self.path)
        return record


def _limited(value: Any, length: int) -> str:
    return str(value or "").strip()[:length]


def _tokens(value: str) -> set[str]:
    stopwords = {
        "the", "and", "that", "this", "with", "from", "into", "does", "not",
        "finding", "system", "document", "validation", "provided", "package",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9]{3,}", value.lower())
        if token not in stopwords
    }


def _fingerprint(finding: dict[str, Any]) -> str:
    category = finding.get("finding_category") or finding.get("category") or ""
    document_type = finding.get("document_type") or finding.get("document") or ""
    observation_tokens = sorted(_tokens(str(finding.get("observation") or "")))[:24]
    return "|".join([str(document_type).lower(), str(category).lower(), ",".join(observation_tokens)])


def precedent_similarity(finding: Finding, record: dict[str, Any]) -> float:
    score = 0.0
    if record.get("finding_category", "").lower() == finding.category.lower():
        score += 0.3
    if record.get("document_type", "").lower() in {
        finding.document_type.lower(), finding.document.lower()
    }:
        score += 0.2
    finding_tokens = _tokens(finding.observation)
    precedent_tokens = _tokens(str(record.get("original_finding") or ""))
    if finding_tokens and precedent_tokens:
        score += 0.5 * (len(finding_tokens & precedent_tokens) / len(finding_tokens | precedent_tokens))
    return round(score, 3)


def apply_feedback_precedents(
    findings: list[Finding], records: list[dict[str, Any]]
) -> tuple[list[Finding], list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply controlled precedent and return active, suppressed, and conflicts.

    Five substantially similar false-positive/rejection decisions suppress a
    repeated non-regulatory finding into reviewer considerations. Conflicting
    guidance is surfaced and never resolved automatically.
    """
    active: list[Finding] = []
    considerations: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for finding in findings:
        matches = [
            (record, precedent_similarity(finding, record))
            for record in records
        ]
        matches = [(record, score) for record, score in matches if score >= 0.52]
        matches.sort(key=lambda item: item[1], reverse=True)
        accepted = [record for record, _ in matches if record.get("reviewer_decision") in POSITIVE_DECISIONS]
        rejected = [record for record, _ in matches if record.get("reviewer_decision") in REJECTION_DECISIONS]
        finding.feedback_precedent_ids = [record.get("feedback_id", "") for record, _ in matches[:8]]

        if accepted and rejected:
            conflicts.append(
                {
                    "finding_category": finding.category,
                    "document_type": finding.document_type,
                    "message": "Conflicting historical reviewer guidance identified.",
                    "interpretation_a": accepted[0].get("reviewer_rationale") or accepted[0].get("reviewer_decision"),
                    "interpretation_b": rejected[0].get("reviewer_rationale") or rejected[0].get("reviewer_decision"),
                    "current_governing_procedure": finding.applicable_reference,
                    "recommended_interpretation": "Apply the current controlled requirement and escalate the precedent conflict to a human Quality reviewer.",
                    "confidence_score": 50,
                    "precedent_ids": finding.feedback_precedent_ids,
                }
            )
            active.append(finding)
            continue

        may_suppress = finding.basis_type not in {"Regulatory requirement", "Internal procedural requirement"}
        if len(rejected) >= 5 and not accepted and may_suppress:
            considerations.append(
                {
                    "type": "Reviewer consideration requiring additional context",
                    "original_finding": finding.to_dict(),
                    "reason": "Five or more substantially similar findings were rejected or marked false positive by reviewers.",
                    "precedent_ids": finding.feedback_precedent_ids,
                }
            )
            continue

        if accepted:
            finding.confidence_score = min(99, finding.confidence_score + min(4, len(accepted)))
        active.append(finding)
    return active, considerations, conflicts

