"""Durable local review records and human decision history."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import re
from threading import Lock
from typing import Any
from uuid import uuid4

from .models import FINDING_STATUSES
from .workflow import refresh_review_state


class ReviewNotFoundError(ValueError):
    pass


class ReviewConflictError(ValueError):
    pass


class ReviewCompletionError(ValueError):
    def __init__(self, message: str, blockers: list[str]):
        super().__init__(message)
        self.blockers = blockers


def _limited(value: Any, length: int) -> str:
    return str(value or "").strip()[:length]


class ReviewStore:
    """Atomic JSON persistence suitable for the app's current single-user scope."""

    def __init__(self, directory: Path):
        self.directory = directory
        self._lock = Lock()

    def _path(self, review_id: str) -> Path:
        safe_id = re.sub(r"[^A-Za-z0-9_.-]", "", review_id)
        if not safe_id or safe_id != review_id:
            raise ReviewNotFoundError("Review run was not found.")
        return self.directory / f"{safe_id}.json"

    def _write_unlocked(self, report: dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(str(report["review_id"]))
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    def create(self, report: dict[str, Any]) -> dict[str, Any]:
        refresh_review_state(report)
        with self._lock:
            self._write_unlocked(report)
        return report

    def load(self, review_id: str) -> dict[str, Any]:
        path = self._path(review_id)
        with self._lock:
            if not path.is_file():
                raise ReviewNotFoundError("Review run was not found.")
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                raise ValueError("The stored review record could not be read.") from exc
            refresh_review_state(report)
            self._write_unlocked(report)
        return report

    def latest(self) -> dict[str, Any] | None:
        with self._lock:
            if not self.directory.is_dir():
                return None
            paths = sorted(self.directory.glob("REV-*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        return self.load(paths[0].stem) if paths else None

    def decide(self, review_id: str, finding_id: str, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        disposition = _limited(payload.get("disposition"), 40)
        if disposition not in FINDING_STATUSES or disposition == "Open":
            raise ValueError("Select a valid reviewer disposition.")
        comment = _limited(payload.get("reviewer_comment"), 4_000)
        reviewer = _limited(payload.get("reviewer"), 240)
        modified = _limited(payload.get("modified_recommendation"), 8_000)
        rejection_reason = _limited(payload.get("rejection_reason"), 120)
        modification_reason = _limited(payload.get("modification_reason"), 120)
        duplicate_of = _limited(payload.get("duplicate_of"), 40)
        if disposition == "Rejected" and not comment:
            raise ValueError("A rejection rationale is required.")
        if disposition == "Modified" and not modified:
            raise ValueError("Enter the reviewer-modified recommendation before saving.")
        if disposition == "Modified" and modified == _limited(payload.get("original_ai_recommendation"), 8_000):
            raise ValueError("The modified recommendation must differ from the AI recommendation.")
        if disposition == "Needs SME Review" and not comment:
            raise ValueError("Describe the question that requires SME review.")

        with self._lock:
            path = self._path(review_id)
            if not path.is_file():
                raise ReviewNotFoundError("Review run was not found.")
            report = json.loads(path.read_text(encoding="utf-8"))
            refresh_review_state(report)
            finding = next(
                (
                    item
                    for item in report.get("findings", [])
                    if item.get("finding_id") == finding_id or item.get("id") == finding_id
                ),
                None,
            )
            if finding is None:
                raise ReviewNotFoundError("Finding was not found in this review run.")
            expected_updated_at = _limited(payload.get("expected_updated_at"), 80)
            if expected_updated_at and expected_updated_at != finding.get("updated_at"):
                raise ReviewConflictError(
                    "This finding was updated by another review action. Reload it before saving your decision."
                )

            timestamp = datetime.now(UTC).isoformat()
            old_status = finding.get("status") or "Open"
            event = {
                "event_id": f"EVT-{uuid4().hex[:12].upper()}",
                "reviewer": reviewer or "Not Available",
                "timestamp": timestamp,
                "action": disposition,
                "finding_id": finding["finding_id"],
                "old_status": old_status,
                "new_status": disposition,
                "reviewer_comment": comment,
                "rejection_reason": rejection_reason,
                "modification_reason": modification_reason,
                "modified_recommendation": modified,
                "duplicate_of": duplicate_of,
            }
            finding["status"] = disposition
            finding["reviewer_disposition"] = disposition
            finding["reviewer_comment"] = comment
            finding["modified_recommendation"] = modified
            finding["reviewer"] = reviewer or "Not Available"
            finding["reviewed_at"] = timestamp
            finding["updated_at"] = timestamp
            finding["rejection_reason"] = rejection_reason
            finding["modification_reason"] = modification_reason
            finding["duplicate_of"] = duplicate_of
            finding.setdefault("decision_history", []).append(event)
            if comment:
                finding.setdefault("reviewer_comments", []).append(
                    {"reviewer": reviewer or "Not Available", "timestamp": timestamp, "comment": comment}
                )
            report.setdefault("audit_events", []).append(
                {
                    "event_id": event["event_id"],
                    "user": reviewer or "Not Available",
                    "timestamp": timestamp,
                    "action": {
                        "Accepted": "Recommendation accepted",
                        "Rejected": "Recommendation rejected",
                        "Modified": "Recommendation modified",
                        "Deferred": "Finding deferred",
                        "Needs SME Review": "SME review requested",
                        "Resolved": "Finding resolved",
                    }[disposition],
                    "finding_id": finding["finding_id"],
                    "old_value": old_status,
                    "new_value": disposition,
                }
            )
            refresh_review_state(report)
            self._write_unlocked(report)
        return report, finding

    def complete(self, review_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        reviewer = _limited(payload.get("reviewer"), 240)
        with self._lock:
            path = self._path(review_id)
            if not path.is_file():
                raise ReviewNotFoundError("Review run was not found.")
            report = json.loads(path.read_text(encoding="utf-8"))
            refresh_review_state(report)
            workflow = report["review_workflow"]
            if not workflow["can_complete"]:
                raise ReviewCompletionError(
                    "Review cannot be completed while blocking findings remain.",
                    workflow["readiness_reasons"],
                )
            timestamp = datetime.now(UTC).isoformat()
            workflow["completed_at"] = timestamp
            report.setdefault("audit_events", []).append(
                {
                    "event_id": f"EVT-{uuid4().hex[:12].upper()}",
                    "user": reviewer or "Not Available",
                    "timestamp": timestamp,
                    "action": "Review status changed",
                    "finding_id": None,
                    "old_value": workflow["status"],
                    "new_value": "Review Completed",
                }
            )
            refresh_review_state(report)
            self._write_unlocked(report)
        return report

    def record_export(self, review_id: str, export_type: str, reviewer: str = "") -> None:
        with self._lock:
            path = self._path(review_id)
            if not path.is_file():
                return
            report = json.loads(path.read_text(encoding="utf-8"))
            timestamp = datetime.now(UTC).isoformat()
            report.setdefault("audit_events", []).append(
                {
                    "event_id": f"EVT-{uuid4().hex[:12].upper()}",
                    "user": _limited(reviewer, 240) or "Not Available",
                    "timestamp": timestamp,
                    "action": "Export generated",
                    "finding_id": None,
                    "old_value": None,
                    "new_value": _limited(export_type, 80),
                }
            )
            self._write_unlocked(report)

