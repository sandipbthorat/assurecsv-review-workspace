"""Shared schemas and constants for the validation review pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from difflib import SequenceMatcher
import re
from typing import Any
from uuid import uuid4


SEVERITIES = ("Critical", "Major", "Minor", "Observation")
SEVERITY_ORDER = {
    "Critical": 0,
    "Major": 1,
    "Minor": 2,
    "Observation": 3,
    # Historical records used Moderate. Keep it sortable while new reviews use
    # the four-value controlled taxonomy above.
    "Moderate": 2,
}

FINDING_STATUSES = (
    "Open",
    "Accepted",
    "Rejected",
    "Modified",
    "Deferred",
    "Needs SME Review",
    "Resolved",
)


def word_diff(original: str, proposed: str) -> list[dict[str, str]]:
    """Return a whitespace-preserving, word-level comparison.

    SequenceMatcher is part of the Python standard library and avoids making
    the browser responsible for a second, potentially inconsistent diff.
    """

    if not original and not proposed:
        return []
    token_pattern = re.compile(r"\s+|[\w]+(?:['’.-][\w]+)*|[^\w\s]", re.UNICODE)
    before = token_pattern.findall(original or "")
    after = token_pattern.findall(proposed or "")
    matcher = SequenceMatcher(a=before, b=after, autojunk=False)
    segments: list[dict[str, str]] = []
    for operation, a_start, a_end, b_start, b_end in matcher.get_opcodes():
        if operation in {"equal", "delete", "replace"} and a_start != a_end:
            segments.append(
                {
                    "type": "equal" if operation == "equal" else "delete",
                    "text": "".join(before[a_start:a_end]),
                }
            )
        if operation in {"insert", "replace"} and b_start != b_end:
            segments.append({"type": "insert", "text": "".join(after[b_start:b_end])})
    return segments


def plain_proposal(value: str) -> str:
    """Convert legacy markdown redline markers into proposed final wording."""

    text = str(value or "").strip()
    text = re.sub(r"~~.*?~~\s*", "", text, flags=re.DOTALL)
    text = text.replace("**", "").strip()
    text = re.sub(r"^\[(?:ADD|REPLACE WITH):\s*", "", text, flags=re.IGNORECASE)
    if text.endswith("]"):
        text = text[:-1]
    return text.strip()


@dataclass
class Document:
    id: str
    name: str
    text: str
    doc_type: str = "Other"
    revision: str = "Unable to determine"
    approval_status: str = "Unable to determine"
    system: str = "Unable to determine"
    version: str = "Unable to determine"
    date: str = "Unable to determine"
    document_id: str = "Unable to determine"
    owner: str = "Unable to determine"
    author: str = "Unable to determine"
    reviewers: str = "Unable to determine"
    approvers: str = "Unable to determine"
    project_release: str = "Unable to determine"
    referenced_procedures: list[str] = field(default_factory=list)
    extraction_status: str = "Complete"
    warnings: list[str] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        result = asdict(self)
        result.pop("text", None)
        result["character_count"] = len(self.text)
        return result


@dataclass
class Finding:
    severity: str
    confidence: str
    category: str
    document: str
    location: str
    observation: str
    impact: str
    recommended_action: str
    requirement_ids: list[str] = field(default_factory=list)
    risk_ids: list[str] = field(default_factory=list)
    approval_blocking: bool = False
    basis_type: str = "Reviewer recommendation"
    basis: str = "Risk-based validation review"
    finding_id: str = ""
    document_id: str = "Unable to determine"
    document_type: str = "Unable to determine"
    document_revision: str = "Unable to determine"
    section: str = "Unable to determine"
    page: int | None = None
    source_text: str = "Unable to determine from available evidence."
    finding_subcategory: str = "General"
    confidence_score: int = 0
    applicable_reference: str = "Risk-based validation principle"
    suggested_redline: str = ""
    sme_confirmation_required: bool = False
    test_ids: list[str] = field(default_factory=list)
    related_finding_ids: list[str] = field(default_factory=list)
    feedback_precedent_ids: list[str] = field(default_factory=list)
    related_documents: list[str] = field(default_factory=list)
    status: str = "Open"
    id: str = field(default_factory=lambda: str(uuid4()))
    display_id: str = ""
    title: str = ""
    reviewer_disposition: str = ""
    reviewer_comment: str = ""
    modified_recommendation: str = ""
    reviewer: str = ""
    reviewed_at: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    rejection_reason: str = ""
    modification_reason: str = ""
    duplicate_of: str = ""
    decision_history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        # Preserve the original application keys while exposing the expanded
        # controlled machine schema requested for downstream integrations.
        result["confidence_level"] = self.confidence
        result["finding_category"] = self.category
        result["recommended_change"] = self.recommended_action
        result["why_it_matters"] = self.impact
        result["finding"] = self.observation
        result["evidence"] = self.source_text
        result["risk_impact"] = self.impact
        result["original_text"] = self.source_text
        result["proposed_text"] = plain_proposal(self.suggested_redline) or self.recommended_action
        result["display_id"] = self.display_id or self.finding_id
        result["title"] = self.title or self.finding_subcategory or self.category
        verification_status = (
            "Internal Rule"
            if self.basis_type == "Internal procedural requirement"
            else "Needs Verification"
            if self.basis_type in {"Regulatory requirement", "Industry best practice"}
            else "Internal Rule"
        )
        result["review_basis"] = [
            {
                "source_type": self.basis_type or "Review rule",
                "source_name": self.applicable_reference or self.basis or "Not Available",
                "section": self.section or "Not Available",
                "clause": "Not Available",
                "text": self.basis or "Not Available",
                "verification_status": verification_status,
            }
        ]
        result["affected_documents"] = [
            {
                "document_id": name,
                "document_name": name,
                "section": self.section or self.location or "Not Available",
            }
            for name in self.related_documents
        ] or [
            {
                "document_id": self.document_id,
                "document_name": self.document,
                "section": self.section or self.location or "Not Available",
            }
        ]
        result["redline_diff"] = word_diff(result["original_text"], result["proposed_text"])

        # Camel-case aliases make the structured record convenient for typed
        # clients without breaking the original snake-case API contract.
        result["displayId"] = result["display_id"]
        result["documentName"] = self.document
        result["riskImpact"] = result["risk_impact"]
        result["originalText"] = result["original_text"]
        result["proposedText"] = result["proposed_text"]
        result["reviewBasis"] = result["review_basis"]
        result["affectedDocuments"] = result["affected_documents"]
        return result


def add_finding(
    findings: list[Finding],
    *,
    severity: str,
    confidence: str,
    category: str,
    document: str,
    location: str,
    observation: str,
    impact: str,
    recommended_action: str,
    requirement_ids: list[str] | None = None,
    risk_ids: list[str] | None = None,
    approval_blocking: bool = False,
    basis_type: str = "Reviewer recommendation",
    basis: str = "Risk-based validation review",
    finding_subcategory: str = "General",
    confidence_score: int | None = None,
    applicable_reference: str | None = None,
    suggested_redline: str = "",
    sme_confirmation_required: bool = False,
    test_ids: list[str] | None = None,
) -> None:
    findings.append(
        Finding(
            severity=severity,
            confidence=confidence,
            category=category,
            document=document,
            location=location,
            observation=observation,
            impact=impact,
            recommended_action=recommended_action,
            requirement_ids=requirement_ids or [],
            risk_ids=risk_ids or [],
            approval_blocking=approval_blocking,
            basis_type=basis_type,
            basis=basis,
            finding_subcategory=finding_subcategory,
            confidence_score=confidence_score or 0,
            applicable_reference=applicable_reference or basis,
            suggested_redline=suggested_redline,
            sme_confirmation_required=sme_confirmation_required,
            test_ids=test_ids or [],
        )
    )
