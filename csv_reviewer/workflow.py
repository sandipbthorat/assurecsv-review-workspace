"""Derived review-workflow state shared by generation and persistence."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .models import FINDING_STATUSES, SEVERITIES, SEVERITY_ORDER


CLOSED_STATUSES = {"Rejected", "Resolved"}
DECIDED_STATUSES = set(FINDING_STATUSES) - {"Open"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def normalize_finding(finding: dict[str, Any], review_id: str, index: int) -> dict[str, Any]:
    """Make new and historical finding records safe for the current UI."""

    display_id = str(
        finding.get("display_id")
        or finding.get("displayId")
        or finding.get("finding_id")
        or f"F-{index:03d}"
    )
    finding["finding_id"] = display_id
    finding["display_id"] = display_id
    finding["displayId"] = display_id
    finding.setdefault("id", str(uuid5(NAMESPACE_URL, f"{review_id}:{display_id}")))

    severity = str(finding.get("severity") or "Observation")
    if severity == "Moderate":
        severity = "Minor"
    if severity not in SEVERITIES:
        severity = "Observation"
    finding["severity"] = severity

    status = str(finding.get("status") or "Open")
    finding["status"] = status if status in FINDING_STATUSES else "Open"
    finding.setdefault("category", finding.get("finding_category") or "Not Classified")
    finding.setdefault("finding_category", finding["category"])
    finding.setdefault("finding_subcategory", "Not Classified")
    finding.setdefault("title", finding.get("finding") or finding.get("observation") or finding["category"])
    finding.setdefault("finding", finding.get("observation") or "Finding details are not available in this historical record.")
    finding.setdefault("observation", finding["finding"])
    finding.setdefault("evidence", finding.get("source_text") or "Not Available")
    finding.setdefault("source_text", finding["evidence"])
    finding.setdefault("risk_impact", finding.get("impact") or "Not Available")
    finding.setdefault("impact", finding["risk_impact"])
    finding.setdefault("original_text", finding.get("originalText") or finding["evidence"])
    finding.setdefault(
        "proposed_text",
        finding.get("proposedText") or finding.get("suggested_redline") or finding.get("recommended_action") or "Not Available",
    )
    finding.setdefault("recommended_action", finding["proposed_text"])
    finding.setdefault("confidence_score", None)
    finding.setdefault("confidence", "Not Available")
    finding.setdefault("section", finding.get("location") or "Not Available")
    finding.setdefault("document", finding.get("document_name") or "Not Available")
    finding.setdefault("document_id", finding.get("document") or "Not Available")
    finding.setdefault("review_basis", finding.get("reviewBasis") or [])
    finding.setdefault("affected_documents", finding.get("affectedDocuments") or [])
    if not finding["affected_documents"]:
        related_documents = finding.get("related_documents") or [finding["document"]]
        finding["affected_documents"] = [
            {"document_id": name, "document_name": name, "section": finding["section"]}
            for name in related_documents
        ]
    finding.setdefault("reviewer_disposition", "")
    finding.setdefault("reviewer_comment", "")
    finding.setdefault("modified_recommendation", "")
    finding.setdefault("reviewer", "")
    finding.setdefault("reviewed_at", "")
    finding.setdefault("created_at", _now())
    finding.setdefault("updated_at", finding["created_at"])
    finding.setdefault("rejection_reason", "")
    finding.setdefault("modification_reason", "")
    finding.setdefault("duplicate_of", "")
    finding.setdefault("decision_history", [])
    finding.setdefault("reviewer_comments", [])
    finding.setdefault("sme_confirmation_required", False)
    finding.setdefault("approval_blocking", severity in {"Critical", "Major"})

    # Maintain both naming conventions for backward-compatible clients.
    finding["documentName"] = finding["document"]
    finding["riskImpact"] = finding["risk_impact"]
    finding["originalText"] = finding["original_text"]
    finding["proposedText"] = finding["proposed_text"]
    finding["reviewBasis"] = finding["review_basis"]
    finding["affectedDocuments"] = finding["affected_documents"]
    return finding


def refresh_review_state(report: dict[str, Any]) -> dict[str, Any]:
    """Recalculate every visible count and readiness decision from findings."""

    review_id = str(report.get("review_id") or report.get("review_run_id") or "HISTORICAL-REVIEW")
    findings = report.setdefault("findings", [])
    for index, finding in enumerate(findings, start=1):
        normalize_finding(finding, review_id, index)

    severity_counts = Counter(finding["severity"] for finding in findings)
    status_counts = Counter(finding["status"] for finding in findings)
    category_counts = Counter(finding["category"] for finding in findings)

    unresolved_risk = [
        finding
        for finding in findings
        if finding["severity"] in {"Critical", "Major"} and finding["status"] not in CLOSED_STATUSES
    ]
    sme_items = [finding for finding in findings if finding["status"] == "Needs SME Review"]
    undispositioned = [finding for finding in findings if finding["status"] == "Open"]

    blocker_messages: list[str] = []
    critical_open = sum(1 for finding in unresolved_risk if finding["severity"] == "Critical")
    major_open = sum(1 for finding in unresolved_risk if finding["severity"] == "Major")
    if critical_open:
        blocker_messages.append(
            f"{critical_open} Critical finding{'s' if critical_open != 1 else ''} "
            f"{'remain' if critical_open != 1 else 'remains'} unresolved"
        )
    if major_open:
        blocker_messages.append(
            f"{major_open} Major finding{'s' if major_open != 1 else ''} "
            f"{'remain' if major_open != 1 else 'remains'} unresolved"
        )
    if sme_items:
        blocker_messages.append(
            f"{len(sme_items)} finding{'s' if len(sme_items) != 1 else ''} "
            f"{'require' if len(sme_items) != 1 else 'requires'} SME review"
        )
    open_nonrisk = sum(1 for finding in undispositioned if finding["severity"] not in {"Critical", "Major"})
    if open_nonrisk:
        blocker_messages.append(
            f"{open_nonrisk} finding{'s' if open_nonrisk != 1 else ''} "
            f"{'await' if open_nonrisk != 1 else 'awaits'} reviewer disposition"
        )

    decisions = sum(status_counts[status] for status in DECIDED_STATUSES)
    completed_at = report.get("review_workflow", {}).get("completed_at")
    approved_at = report.get("review_workflow", {}).get("approved_at")
    if approved_at:
        review_status = "Approved"
    elif completed_at:
        review_status = "Review Completed"
    elif not findings:
        review_status = "Ready for Approval"
    elif decisions == 0:
        review_status = "Not Started"
    elif blocker_messages:
        review_status = "Reviewer Action Required"
    elif undispositioned:
        review_status = "Review In Progress"
    else:
        review_status = "Ready for Approval"

    if approved_at:
        readiness = "Approved"
    elif blocker_messages:
        readiness = "Action Required"
    elif undispositioned:
        readiness = "Not Ready"
    else:
        readiness = "Ready for Approval"

    metrics = report.setdefault("metrics", {})
    metrics["documents"] = len(report.get("detailed_document_review", [])) or int(metrics.get("documents") or 0)
    metrics["findings"] = len(findings)
    metrics["blocking_findings"] = len(unresolved_risk)
    metrics["severity_counts"] = {severity: severity_counts.get(severity, 0) for severity in SEVERITIES}
    metrics["status_counts"] = {status: status_counts.get(status, 0) for status in FINDING_STATUSES}
    metrics["category_counts"] = dict(sorted(category_counts.items()))
    metrics["open_findings"] = sum(1 for finding in findings if finding["status"] not in CLOSED_STATUSES)
    metrics["reviewer_decisions"] = decisions
    metrics["ai_recommendations_accepted"] = status_counts["Accepted"]
    metrics["ai_recommendations_rejected"] = status_counts["Rejected"]
    metrics["ai_recommendations_modified"] = status_counts["Modified"]
    metrics["ai_recommendations_requiring_sme"] = status_counts["Needs SME Review"]

    report["critical_and_major_findings"] = [
        finding for finding in findings if finding["severity"] in {"Critical", "Major"}
    ]
    report["open_items_before_approval"] = {
        "approval_blocking": unresolved_risk,
        "non_blocking": [
            finding
            for finding in findings
            if finding not in unresolved_risk and finding["status"] not in CLOSED_STATUSES
        ],
    }

    summaries: list[dict[str, Any]] = []
    documents = report.get("detailed_document_review", [])
    for document in documents:
        source_document = document.get("document") if isinstance(document.get("document"), dict) else {}
        name = (
            document.get("document_name")
            or document.get("name")
            or source_document.get("name")
            or "Not Available"
        )
        related = [
            finding
            for finding in findings
            if any(
                reference.get("document_name") == name
                for reference in finding.get("affected_documents", [])
                if isinstance(reference, dict)
            )
            or name in finding.get("related_documents", [])
        ]
        unresolved = [finding for finding in related if finding["status"] not in CLOSED_STATUSES]
        highest = min(
            (finding["severity"] for finding in unresolved),
            key=lambda severity: SEVERITY_ORDER.get(severity, 99),
            default="None",
        )
        summary = {
            "document_id": document.get("document_id") or source_document.get("document_id") or source_document.get("id") or name,
            "document_name": name,
            "document_type": document.get("document_type") or source_document.get("doc_type") or "Not Classified",
            "revision": document.get("revision") or source_document.get("revision") or "Not Available",
            "extraction_status": document.get("extraction_status") or source_document.get("extraction_status") or "Not Available",
            "finding_count": len(related),
            "open_count": len(unresolved),
            "highest_unresolved_severity": highest,
            "severity_counts": {
                severity: sum(1 for finding in related if finding["severity"] == severity)
                for severity in SEVERITIES
            },
        }
        document["finding_metrics"] = summary
        summaries.append(summary)
    report["document_summaries"] = summaries

    workflow = report.setdefault("review_workflow", {})
    workflow.update(
        {
            "status": review_status,
            "package_readiness": readiness,
            "readiness_reasons": blocker_messages or ["All findings have reviewer dispositions and no configured blockers remain."],
            "can_complete": not blocker_messages and not undispositioned,
            "blocking_finding_ids": sorted({finding["display_id"] for finding in unresolved_risk + sme_items + undispositioned}),
            "completed_at": completed_at,
            "approved_at": approved_at,
        }
    )
    provenance = report.setdefault("review_provenance", {})
    provenance["review_run_id"] = report.get("review_run_id") or review_id
    provenance["review_date_time"] = report.get("generated_at") or "Not Available"
    provenance["reviewer"] = next(
        (finding["reviewer"] for finding in reversed(findings) if finding.get("reviewer")),
        provenance.get("reviewer") or "Not Available",
    )
    provenance["documents_reviewed"] = metrics["documents"]
    provenance["review_status"] = review_status
    return report
