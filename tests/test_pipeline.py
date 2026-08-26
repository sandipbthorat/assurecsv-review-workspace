from __future__ import annotations

import unittest
from pathlib import Path
import tempfile

from csv_reviewer import review_package
from csv_reviewer.feedback import FeedbackStore
from csv_reviewer.ingest import parse_request_files


def review(files: dict[str, str], name: str = "Test package") -> dict:
    payload = {
        "package_name": name,
        "files": [
            {"name": filename, "content": content, "encoding": "text"}
            for filename, content in files.items()
        ],
    }
    return review_package(parse_request_files(payload), name)


class ValidationReviewPipelineTests(unittest.TestCase):
    def test_complete_low_risk_package_can_be_accepted(self) -> None:
        result = review(
            {
                "system.txt": """
                    Document: System Description
                    System Name: TrainingHub
                    Application Version: 1.0
                    GxP Applicability: Not applicable
                    Part 11 Applicability: Not applicable
                    Intended Use: TrainingHub is used by employees to view non-regulated workplace training materials.
                """,
                "urs.txt": """
                    Document: User Requirements Specification
                    System Name: TrainingHub
                    Application Version: 1.0
                    URS-001 The system shall display the authenticated user's assigned training courses.
                """,
                "uat.txt": """
                    Document: User Acceptance Test
                    System Name: TrainingHub
                    Application Version: 1.0
                    UAT-001 Assigned course display
                    Related Requirement: URS-001
                    Expected Result: The three assigned course titles are displayed for EMP-100.
                    Actual Result: All three assigned course titles were displayed for EMP-100.
                    Evidence: Attachment UAT-001-E1.
                    Result: Pass
                """,
                "vsr.txt": """
                    Document: Validation Summary Report
                    System Name: TrainingHub
                    Application Version: 1.0
                    Validation Conclusion: Testing passed and supports release for the stated intended use.
                """,
            }
        )
        self.assertEqual(result["final_recommendation"]["disposition"], "ACCEPT")
        self.assertEqual(result["metrics"]["traceability_percentage"], 100.0)
        self.assertEqual(result["metrics"]["blocking_findings"], 0)

    def test_cross_document_quantity_conflict_is_blocking(self) -> None:
        result = review(
            {
                "system.txt": """
                    Document: System Description
                    System Name: RecordFlow
                    Application Version: 2.0
                    GxP Applicability: Applicable
                    Intended Use: RecordFlow supports regulated quality record review.
                """,
                "urs.txt": """
                    User Requirements Specification
                    System Name: RecordFlow
                    Application Version: 2.0
                    URS-010 The system shall terminate an inactive session after 10 minutes.
                """,
                "oq.txt": """
                    Operational Qualification
                    System Name: RecordFlow
                    Application Version: 2.0
                    OQ-010 Timeout challenge
                    Related Requirement: URS-010
                    Expected Result: The session ends after 30 minutes.
                    Actual Result: The session ended after 30 minutes.
                    Evidence: Attachment OQ-010-E1.
                    Result: Pass
                """,
                "vsr.txt": """
                    Validation Summary Report
                    System Name: RecordFlow
                    Application Version: 2.0
                    Validation Conclusion: Testing supports release.
                """,
            }
        )
        conflicts = [
            finding for finding in result["findings"]
            if finding["finding_category"] == "Consistency"
            and finding["finding_subcategory"] == "Cross-Document Consistency"
        ]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["severity"], "Major")
        self.assertTrue(conflicts[0]["approval_blocking"])

    def test_missing_high_risk_test_reference_is_not_counted_as_coverage(self) -> None:
        result = review(
            {
                "system.txt": """
                    System Description
                    System Name: LabFlow
                    Version: 3.0
                    GxP Applicability: Applicable
                    Intended Use: LabFlow records regulated laboratory results.
                """,
                "urs.txt": """
                    User Requirements Specification
                    System Name: LabFlow
                    Version: 3.0
                    URS-001 The system shall record result changes in an audit trail.
                """,
                "risk.csv": """Risk ID,Failure Mode,Existing Control,Risk Rating,Requirement,Verification
RA-001,Result change is omitted,Audit trail,High,URS-001,OQ-999""",
                "vsr.txt": """
                    Validation Summary Report
                    System Name: LabFlow
                    Version: 3.0
                    Validation Conclusion: Review pending.
                """,
            }
        )
        self.assertIn("RA-001", result["traceability_analysis"]["risks_without_test_coverage"])
        self.assertIn(
            {"source": "RA-001", "target": "OQ-999", "type": "Missing test"},
            result["traceability_analysis"]["broken_references"],
        )

    def test_findings_follow_the_structured_schema(self) -> None:
        result = review({"notes.txt": "A few unclassified package notes."})
        required_keys = {
            "finding_id",
            "severity",
            "confidence",
            "category",
            "document",
            "location",
            "requirement_ids",
            "risk_ids",
            "observation",
            "impact",
            "recommended_action",
            "approval_blocking",
            "confidence_score",
            "source_text",
            "suggested_redline",
            "finding_category",
            "finding_subcategory",
            "test_ids",
            "status",
        }
        self.assertGreater(len(result["findings"]), 0)
        for finding in result["findings"]:
            self.assertTrue(required_keys.issubset(finding))
            self.assertGreaterEqual(finding["confidence_score"], 25)
            self.assertLessEqual(finding["confidence_score"], 99)

    def test_document_quality_and_redlines_do_not_override_critical_findings(self) -> None:
        result = review(
            {
                "system.txt": """
                    System Description
                    System Name: ReleaseQMS
                    Version: 1.0
                    GxP Applicability: Applicable
                    Intended Use: ReleaseQMS maintains regulated quality release records.
                """,
                "oq.txt": """
                    Operational Qualification
                    System Name: ReleaseQMS
                    Version: 1.0
                    OQ-001 Release record check
                    Expected Result: The record is retained.
                    Actual Result: The record was retained.
                    Evidence: OQ-001-E1
                    Result: Pass
                    DEV-001
                    Severity: Major
                    Status: Open
                """,
                "vsr.txt": """
                    Validation Summary Report
                    System Name: ReleaseQMS
                    Version: 1.0
                    Validation Conclusion: All deviations are closed and the system is ready for release.
                """,
            }
        )
        critical_documents = [
            item for item in result["detailed_document_review"]
            if any(finding["severity"] == "Critical" for finding in item["findings"])
        ]
        self.assertTrue(critical_documents)
        self.assertTrue(all(item["review_confidence"]["score"] <= 44 for item in critical_documents))
        self.assertTrue(any("[CSV COMMENT" in item["redlined_text"] for item in result["redlined_documents"]))

    def test_five_false_positive_precedents_suppress_nonregulatory_pattern(self) -> None:
        files = {
            "system.txt": """
                System Description
                System Name: Helper
                Version: 1.0
                GxP Applicability: Not applicable
                Intended Use: Helper displays non-regulated reference information.
            """,
            "urs.txt": """
                User Requirements Specification
                System Name: Helper
                Version: 1.0
                URS-001 The system shall provide appropriate information as needed.
            """,
            "uat.txt": """
                User Acceptance Test
                System Name: Helper
                Version: 1.0
                UAT-001 Information display
                Related Requirement: URS-001
                Expected Result: Reference content is displayed.
                Actual Result: Reference content was displayed.
                Evidence: UAT-001-E1
                Result: Pass
            """,
            "vsr.txt": """
                Validation Summary Report
                System Name: Helper
                Version: 1.0
                Validation Conclusion: Testing supports release.
            """,
        }
        initial = review(files)
        target = next(finding for finding in initial["findings"] if finding["finding_category"] == "Requirement Quality")
        precedents = [
            {
                "feedback_id": f"FB-{index}",
                "finding_category": target["finding_category"],
                "document_type": target["document_type"],
                "original_finding": target["observation"],
                "reviewer_decision": "Mark as False Positive",
                "reviewer_rationale": "Accepted organizational requirement pattern.",
            }
            for index in range(5)
        ]
        payload = {"files": [{"name": name, "content": content} for name, content in files.items()]}
        result = review_package(parse_request_files(payload), "Feedback test", precedents)
        self.assertFalse(any(finding["finding_category"] == "Requirement Quality" for finding in result["findings"]))
        self.assertEqual(result["feedback_learning"]["suppressed_false_positive_patterns"], 1)

    def test_feedback_store_requires_rationale_for_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = FeedbackStore(Path(directory) / "feedback.json")
            finding = {
                "finding_id": "F-001",
                "finding_category": "Requirement Quality",
                "document_type": "User Requirements Specification",
                "observation": "A requirement is ambiguous.",
            }
            with self.assertRaisesRegex(ValueError, "rationale"):
                store.add({"finding": finding, "reviewer_decision": "Reject"})
            record = store.add({
                "finding": finding,
                "reviewer_decision": "Accept",
                "reviewer_name_role": "Test Reviewer",
            })
            self.assertTrue(record["feedback_id"].startswith("FB-"))
            self.assertEqual(len(store.load()), 1)

    def test_package_limit_is_enforced(self) -> None:
        with self.assertRaisesRegex(ValueError, "at most 75"):
            parse_request_files(
                {"files": [{"name": f"{index}.txt", "content": "x"} for index in range(76)]}
            )


if __name__ == "__main__":
    unittest.main()
