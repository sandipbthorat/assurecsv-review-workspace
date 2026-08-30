from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from csv_reviewer.models import Finding
from csv_reviewer.review_store import ReviewCompletionError, ReviewStore
from csv_reviewer.workflow import refresh_review_state


FIXTURE = Path(__file__).parent / "fixtures" / "review_v3_fixture.json"


def fixture_report() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class ReviewWorkflowTests(unittest.TestCase):
    def test_fixture_has_controlled_severity_and_status_coverage(self) -> None:
        report = refresh_review_state(fixture_report())
        self.assertEqual(
            report["metrics"]["severity_counts"],
            {"Critical": 1, "Major": 2, "Minor": 2, "Observation": 1},
        )
        self.assertEqual(report["metrics"]["status_counts"]["Rejected"], 1)
        self.assertEqual(report["metrics"]["status_counts"]["Accepted"], 1)
        self.assertEqual(report["metrics"]["status_counts"]["Modified"], 1)
        self.assertEqual(report["metrics"]["status_counts"]["Needs SME Review"], 1)
        self.assertEqual(report["document_summaries"][1]["highest_unresolved_severity"], "Critical")

    def test_historical_finding_defaults_are_backward_compatible(self) -> None:
        report = {
            "review_id": "HISTORICAL-1",
            "metrics": {"documents": 0},
            "findings": [{"finding_id": "OLD-1", "observation": "Legacy finding", "severity": "Moderate"}],
        }
        refresh_review_state(report)
        finding = report["findings"][0]
        self.assertEqual(finding["severity"], "Minor")
        self.assertEqual(finding["category"], "Not Classified")
        self.assertEqual(finding["confidence"], "Not Available")
        self.assertEqual(finding["review_basis"], [])
        self.assertEqual(finding["status"], "Open")

    def test_finding_model_preserves_source_ai_proposal_and_word_diff(self) -> None:
        finding = Finding(
            severity="Major",
            confidence="High",
            category="Deviation Handling",
            document="OQ.txt",
            location="Section 6",
            observation="Closure criteria are incomplete.",
            impact="Open exceptions may be accepted.",
            recommended_action="Add controlled closure criteria.",
            source_text="Unexpected results must be linked to a deviation.",
            suggested_redline="Unexpected results shall be assessed and closed before protocol approval.",
        ).to_dict()
        self.assertEqual(finding["original_text"], "Unexpected results must be linked to a deviation.")
        self.assertEqual(finding["proposed_text"], "Unexpected results shall be assessed and closed before protocol approval.")
        self.assertTrue(any(segment["type"] == "delete" for segment in finding["redline_diff"]))
        self.assertTrue(any(segment["type"] == "insert" for segment in finding["redline_diff"]))

    def test_all_reviewer_dispositions_persist_with_history(self) -> None:
        report = fixture_report()
        with tempfile.TemporaryDirectory() as directory:
            store = ReviewStore(Path(directory))
            store.create(report)
            actions = {
                "F-001": {"disposition": "Accepted"},
                "F-002": {"disposition": "Rejected", "reviewer_comment": "Covered by controlled deviation DEV-017."},
                "F-003": {
                    "disposition": "Modified",
                    "modified_recommendation": "Confirm the approved timeout with the Security SME and align URS and OQ.",
                    "modification_reason": "Technical Accuracy",
                },
                "F-004": {"disposition": "Deferred", "reviewer_comment": "Awaiting baseline owner."},
                "F-005": {"disposition": "Needs SME Review", "reviewer_comment": "Confirm the performance limit with the process owner."},
                "F-006": {"disposition": "Resolved", "reviewer_comment": "Editorial update incorporated."},
            }
            for finding_id, payload in actions.items():
                payload["reviewer"] = "Test CSV Reviewer"
                persisted, finding = store.decide(report["review_id"], finding_id, payload)
                self.assertEqual(finding["status"], payload["disposition"])
                self.assertEqual(finding["decision_history"][-1]["new_status"], payload["disposition"])
                report = persisted

            reloaded = store.load(report["review_id"])
            by_id = {finding["finding_id"]: finding for finding in reloaded["findings"]}
            self.assertEqual(by_id["F-002"]["status"], "Rejected")
            self.assertEqual(by_id["F-003"]["modified_recommendation"], actions["F-003"]["modified_recommendation"])
            self.assertEqual(by_id["F-003"]["proposed_text"], "Use the approved session timeout consistently in the URS, configuration baseline, and OQ.")
            self.assertEqual(reloaded["metrics"]["status_counts"]["Resolved"], 1)

    def test_completion_is_blocked_by_open_critical_major_sme_and_undispositioned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ReviewStore(Path(directory))
            report = store.create(fixture_report())
            with self.assertRaises(ReviewCompletionError) as context:
                store.complete(report["review_id"], {"reviewer": "Quality Reviewer"})
            self.assertTrue(any("Critical" in blocker for blocker in context.exception.blockers))
            self.assertTrue(any("SME" in blocker for blocker in context.exception.blockers))

    def test_document_counts_are_derived_from_same_finding_source(self) -> None:
        report = refresh_review_state(fixture_report())
        summary_total = sum(summary["finding_count"] for summary in report["document_summaries"])
        affected_total = sum(len(finding["affected_documents"]) for finding in report["findings"])
        self.assertEqual(summary_total, affected_total)
        self.assertEqual(report["metrics"]["findings"], len(report["findings"]))

    def test_controlled_export_is_recorded_in_audit_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ReviewStore(Path(directory))
            report = store.create(fixture_report())
            store.record_export(report["review_id"], "Traceability CSV", "Quality Reviewer")
            reloaded = store.load(report["review_id"])
            event = reloaded["audit_events"][-1]
            self.assertEqual(event["action"], "Export generated")
            self.assertEqual(event["new_value"], "Traceability CSV")
            self.assertEqual(event["user"], "Quality Reviewer")

    def test_store_instances_share_the_same_directory_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = ReviewStore(Path(directory))
            second = ReviewStore(Path(directory))
            self.assertIs(first._lock, second._lock)


if __name__ == "__main__":
    unittest.main()
