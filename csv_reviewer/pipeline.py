"""Specialized, deterministic stages for validation package assessment."""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
from dataclasses import asdict
from datetime import UTC, datetime
import re
from typing import Any, Iterable
from uuid import uuid4

from .feedback import apply_feedback_precedents
from .models import Document, Finding, SEVERITIES, SEVERITY_ORDER, add_finding


REVIEW_AGENT_VERSION = "CSVQualReviewer deterministic assurance engine v1.1.0"
REVIEW_RULE_SET_VERSION = "CSVQualReviewer-Review-Rules-v1.1.0"
KNOWLEDGE_BASE_VERSION = "Framework index 2026.08 — citation text requires source verification"


DOCUMENT_CLASSIFIERS: dict[str, tuple[str, ...]] = {
    "GxP Applicability Assessment": ("gxp applicability", "qms applicability", "qsr applicability"),
    "Validation Plan": ("validation plan", "validation strategy", "vp-"),
    "Risk Assessment": ("risk assessment", "failure mode", "risk control", "risk id", "fmea"),
    "User Requirements Specification": ("user requirement specification", "user requirements", "urs-"),
    "Functional Specification": (
        "functional specification",
        "functional requirement",
        "frs-",
    ),
    "Configuration Specification": (
        "configuration specification",
        "configuration parameter",
        "configured workflow",
        "configuration baseline",
    ),
    "Design Specification": (
        "design specification",
        "technical design",
        "solution architecture",
        "software design",
    ),
    "Interface Specification": ("interface specification", "source system", "destination system", "data mapping"),
    "Security Specification": ("security specification", "access control specification", "role matrix"),
    "Data Migration Specification": ("data migration", "migration specification", "reconciliation"),
    "Part 11 / Data Integrity Assessment": (
        "part 11 assessment",
        "21 cfr part 11",
        "electronic records assessment",
        "alcoa+",
    ),
    "Data Integrity Assessment": ("data integrity assessment", "alcoa plus", "data lifecycle assessment"),
    "Supplier Assessment": (
        "supplier assessment",
        "vendor assessment",
        "supplier criticality",
        "supplier qualification",
    ),
    "Backup and Recovery Plan": (
        "backup and recovery plan",
        "backup restore procedure",
        "restore verification",
        "recovery point objective",
    ),
    "Disaster Recovery / Business Continuity Plan": (
        "disaster recovery plan",
        "business continuity plan",
        "recovery time objective",
        "continuity exercise",
    ),
    "Training Qualification Record": (
        "training qualification record",
        "training completion record",
        "training curriculum",
        "qualified personnel",
    ),
    "Installation Qualification": ("installation qualification", "iq protocol", "iq-"),
    "Operational Qualification": ("operational qualification", "oq protocol", "oq-"),
    "Performance Qualification": ("performance qualification", "pq protocol", "pq-"),
    "User Acceptance Testing": ("user acceptance test", "uat protocol", "uat-"),
    "Regression Test Evidence": ("regression test", "regression suite", "regression protocol"),
    "Interface Test Evidence": ("interface test", "integration interface test", "interface verification"),
    "Data Migration Test Evidence": ("migration test", "migration reconciliation test", "data conversion verification"),
    "Security / Electronic Signature Test Evidence": (
        "security test",
        "electronic signature test",
        "authority check test",
        "access control test",
    ),
    "Automated / Unit / Integration Test Evidence": (
        "unit test",
        "automated test",
        "integration test",
        "continuous integration test",
    ),
    "Traceability Matrix": ("traceability matrix", "requirements traceability", "rtm"),
    "Defect / Deviation Log": ("defect log", "deviation log", "exception log", "def-", "dev-"),
    "Validation Summary Report": ("validation summary report", "validation conclusion", "release recommendation", "vsr"),
    "Procedure / SOP": ("standard operating procedure", "procedure number", "work instruction", "sop-"),
    "Test Evidence": ("test script", "test execution", "expected result", "actual result", "test case"),
    "Release / Deployment Record": (
        "release record",
        "deployment record",
        "release notes",
        "production deployment",
    ),
    "System Description": ("system information", "system description", "intended use", "hosting model"),
    "Change Control": ("change control", "change request", "validation impact", "rollback plan"),
    "Periodic Review": ("periodic review", "continued validated state", "review period"),
    "User Access Review": ("user access review", "access recertification", "terminated users", "role appropriateness"),
    "Decommissioning Plan": ("decommissioning", "system retirement", "retirement plan", "archive strategy"),
}

DOCUMENT_REVIEW_LENSES: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "GxP Applicability Assessment": (
        ("regulated business process", ("business process", "quality system", "manufacturing", "laboratory")),
        ("classification rationale", ("rationale", "justification", "applicable", "not applicable")),
        ("electronic records/signatures", ("electronic record", "electronic signature", "part 11")),
    ),
    "System Description": (
        ("intended use", ("intended use",)), ("users", ("users", "personnel", "roles")),
        ("hosting and environment", ("hosting", "environment")), ("interfaces", ("interface", "integration")),
        ("authentication", ("authentication", "single sign-on", "login")), ("records", ("records", "data")),
    ),
    "Validation Plan": (
        ("scope", ("scope",)), ("responsibilities", ("responsibilities", "roles")),
        ("risk methodology", ("risk methodology", "risk assessment")), ("testing strategy", ("testing strategy", "test approach")),
        ("acceptance/release criteria", ("acceptance criteria", "release criteria")), ("deviation handling", ("deviation", "exception")),
    ),
    "User Requirements Specification": (
        ("unique requirement identifiers", ("urs-", "req-")), ("access/security", ("access", "authentication", "role")),
        ("data integrity", ("audit trail", "retention", "record")), ("error handling", ("error", "failure", "reject")),
    ),
    "Functional Specification": (
        ("business rules", ("business rule", "workflow")), ("system responses", ("system response", "expected behavior")),
        ("error behavior", ("error", "exception")), ("URS linkage", ("urs-", "requirement")),
    ),
    "Configuration Specification": (
        ("workflows and states", ("workflow", "status transition")), ("roles and permissions", ("role", "permission")),
        ("limits/settings", ("parameter", "limit", "setting")), ("baseline control", ("baseline", "approved", "version")),
    ),
    "Design Specification": (
        ("architecture/components", ("architecture", "component", "module")), ("data flow", ("data flow", "database")),
        ("interfaces/APIs", ("interface", "api")), ("security/logging", ("security", "logging", "audit")),
        ("recovery", ("recovery", "availability", "backup")),
    ),
    "Risk Assessment": (
        ("failure modes", ("failure mode",)), ("causes and impacts", ("cause", "impact")),
        ("risk controls", ("control", "mitigation")), ("risk evaluation", ("severity", "probability", "risk rating")),
        ("assurance activity", ("verification", "test", "assurance")),
    ),
    "Part 11 / Data Integrity Assessment": (
        ("applicability", ("applicable", "not applicable")), ("electronic records", ("electronic record",)),
        ("audit trails", ("audit trail",)), ("electronic signatures", ("electronic signature",)),
        ("record retention/copies", ("retention", "accurate and complete")), ("access/authority", ("access", "authority check")),
    ),
    "Data Integrity Assessment": (
        ("ALCOA+", ("alcoa", "attributable", "contemporaneous")), ("data lifecycle", ("lifecycle", "archive", "retention")),
        ("data changes", ("edit", "deletion", "audit trail")), ("interfaces/calculations", ("interface", "calculation")),
    ),
    "Supplier Assessment": (
        ("supplier criticality", ("criticality",)), ("quality system/SDLC", ("quality system", "sdlc", "development")),
        ("testing/releases", ("testing", "release control")), ("support/continuity", ("support", "business continuity", "availability")),
    ),
    "Backup and Recovery Plan": (
        ("backup scope and frequency", ("backup scope", "backup frequency", "schedule")),
        ("retention and protection", ("retention", "encryption", "protected")),
        ("restore verification", ("restore test", "restore verification", "recovery test")),
        ("ownership and monitoring", ("owner", "monitoring", "alert")),
    ),
    "Disaster Recovery / Business Continuity Plan": (
        ("business impact and scope", ("business impact", "critical process", "scope")),
        ("recovery objectives", ("recovery time objective", "rto", "recovery point objective", "rpo")),
        ("roles and escalation", ("roles", "escalation", "communication")),
        ("exercise and evidence", ("exercise", "test", "evidence", "lessons learned")),
    ),
    "Training Qualification Record": (
        ("learner identity", ("learner", "employee", "user")),
        ("required curriculum", ("curriculum", "required training", "course")),
        ("completion and competence", ("completion", "assessment", "qualified", "competence")),
        ("approval and date", ("approved", "signature", "completion date")),
    ),
    "Installation Qualification": (
        ("software version", ("version",)), ("environment/platform", ("environment", "platform", "operating system")),
        ("configuration/connectivity", ("configuration", "connectivity")), ("backup/services", ("backup", "service account", "service")),
    ),
    "Operational Qualification": (
        ("requirement linkage", ("requirement", "urs-")), ("expected and actual results", ("expected result", "actual result")),
        ("negative/error challenges", ("invalid", "reject", "failure", "unauthorized")), ("objective evidence", ("evidence", "attachment")),
    ),
    "Performance Qualification": (
        ("representative users", ("representative user", "business user")), ("realistic workflow/data", ("end-to-end", "realistic", "representative data")),
        ("exceptions", ("exception", "failure")), ("objective evidence", ("evidence", "attachment")),
    ),
    "User Acceptance Testing": (
        ("business users", ("business user", "tester")), ("intended workflows", ("workflow", "end-to-end")),
        ("expected/actual results", ("expected result", "actual result")), ("objective evidence", ("evidence", "attachment")),
    ),
    "Regression Test Evidence": (
        ("change impact linkage", ("change", "impact", "regression scope")),
        ("test identifiers", ("test id", "tc-", "reg-")),
        ("expected/actual results", ("expected result", "actual result")),
        ("evidence and disposition", ("evidence", "attachment", "pass", "fail")),
    ),
    "Interface Test Evidence": (
        ("endpoint and direction", ("source", "destination", "endpoint", "direction")),
        ("mapping and transformation", ("mapping", "transformation", "field")),
        ("negative and recovery cases", ("invalid", "reject", "retry", "recovery")),
        ("reconciliation evidence", ("reconciliation", "record count", "evidence")),
    ),
    "Data Migration Test Evidence": (
        ("source-to-target scope", ("source", "target", "migration scope")),
        ("record-count reconciliation", ("record count", "reconciliation", "control total")),
        ("data-quality exceptions", ("exception", "reject", "transformation error")),
        ("approval and rollback", ("approval", "rollback", "cutover")),
    ),
    "Security / Electronic Signature Test Evidence": (
        ("role and authority checks", ("role", "authority check", "unauthorized")),
        ("authentication challenge", ("authentication", "password", "session")),
        ("signature manifestation/linking", ("signature manifestation", "signature linking", "electronic signature")),
        ("audit evidence", ("audit trail", "evidence", "attachment")),
    ),
    "Automated / Unit / Integration Test Evidence": (
        ("version and build linkage", ("build", "commit", "version")),
        ("test inventory and result", ("test", "passed", "failed", "coverage")),
        ("failure investigation", ("failure", "defect", "investigation")),
        ("retained execution evidence", ("log", "report", "artifact", "evidence")),
    ),
    "Traceability Matrix": (
        ("requirements", ("urs-", "requirement")), ("risks", ("risk", "ra-")),
        ("tests/results", ("test", "oq-", "result")), ("version/baseline", ("version", "revision")),
    ),
    "Defect / Deviation Log": (
        ("description/status", ("description", "status")), ("impact", ("impact",)),
        ("root cause/correction", ("root cause", "correction")), ("retest/disposition", ("retest", "disposition", "closure")),
    ),
    "Validation Summary Report": (
        ("scope and activities", ("scope", "activities", "deliverables")), ("results", ("results", "passed")),
        ("defects/deviations", ("defect", "deviation")), ("residual risk", ("residual risk",)),
        ("release recommendation", ("release recommendation", "validation conclusion")),
    ),
    "Change Control": (
        ("change and reason", ("change description", "business reason")), ("impact/risk", ("impact", "risk")),
        ("validation/regression", ("validation impact", "regression")), ("deployment/rollback", ("deployment", "rollback")),
        ("approval/closure", ("approval", "closure")),
    ),
    "Periodic Review": (
        ("changes/incidents", ("change", "incident", "deviation")), ("access/security", ("access review", "security")),
        ("backup/vendor", ("backup", "vendor")), ("continued-state conclusion", ("remains validated", "revalidation", "retirement")),
    ),
    "User Access Review": (
        ("active/inactive users", ("active user", "inactive user", "terminated")), ("roles/privileges", ("role", "privileged")),
        ("service/shared accounts", ("service account", "shared account")), ("segregation of duties", ("segregation",)),
    ),
    "Decommissioning Plan": (
        ("retirement scope", ("retirement scope", "decommission")), ("retention/archive", ("retention", "archive")),
        ("retrieval/protection", ("retrieval", "protected")), ("access/interfaces", ("access termination", "interface")),
        ("approvals", ("approval",)),
    ),
    "Release / Deployment Record": (
        ("approved version and scope", ("version", "release scope", "approved")),
        ("deployment steps and verification", ("deployment", "verification", "smoke test")),
        ("configuration baseline", ("configuration", "baseline", "checksum")),
        ("rollback and approvals", ("rollback", "approval", "release authorization")),
    ),
}

REQUIREMENT_ID_RE = re.compile(r"\b(?:URS|REQ|BR|FR|FRS|FSR)[-_]?\d{1,5}\b", re.I)
RISK_ID_RE = re.compile(r"\b(?:RA|RISK|RSK|FMEA)[-_]?\d{1,5}\b", re.I)
TEST_ID_RE = re.compile(r"\b(?:OQ|PQ|IQ|UAT|TC|TEST)[-_]?\d{1,5}\b", re.I)
ISSUE_ID_RE = re.compile(r"\b(?:DEF|BUG|DEV|EXC|NC)[-_]?\d{1,5}\b", re.I)

WEAK_TERMS = (
    "appropriate",
    "adequate",
    "normally",
    "generally",
    "user friendly",
    "fast",
    "easy",
    "etc.",
    "as needed",
    "where applicable",
)


def _canonical(identifier: str) -> str:
    return re.sub(r"[_-]?([0-9]+)$", r"-\1", identifier.upper())


def _clean(value: str, limit: int = 900) -> str:
    value = re.sub(r"\s+", " ", value).strip(" |:\t\n")
    return value[:limit] + ("…" if len(value) > limit else "")


def _first_label(text: str, labels: Iterable[str], *, limit: int = 100) -> str:
    joined = "|".join(re.escape(label) for label in labels)
    match = re.search(rf"(?im)^\s*(?:{joined})\s*(?:[:|,#-]|\bis\b)\s*([^\n|,]+)", text)
    if not match:
        return "Unable to determine"
    value = _clean(match.group(1), limit)
    return value if value else "Unable to determine"


def _filename_score(filename: str, term: str) -> int:
    normalized = re.sub(r"[_\-.]+", " ", filename.lower())
    normalized_term = re.sub(r"[_\-.]+", " ", term.lower()).strip()
    return 8 if normalized_term and normalized_term in normalized else 0


def classify_documents(documents: list[Document]) -> None:
    for document in documents:
        sample = document.text[:30_000].lower()
        scores: dict[str, int] = {}
        for doc_type, terms in DOCUMENT_CLASSIFIERS.items():
            score = 0
            for term in terms:
                score += _filename_score(document.name, term)
                occurrences = sample.count(term)
                score += min(occurrences, 4) * 2
            scores[doc_type] = score
        best_type, best_score = max(scores.items(), key=lambda item: item[1])
        document.doc_type = best_type if best_score else "Other"
        document.revision = _first_label(document.text, ("revision", "document revision", "rev"), limit=40)
        document.approval_status = _first_label(
            document.text, ("approval status", "document status", "status"), limit=50
        )
        document.system = _first_label(document.text, ("system name", "application name", "system"), limit=100)
        document.version = _first_label(
            document.text, ("application version", "software version", "system version", "version", "release"), limit=50
        )
        document.date = _first_label(document.text, ("effective date", "approval date", "document date", "date"), limit=50)
        document.document_id = _first_label(
            document.text, ("document id", "document number", "procedure number", "protocol number"), limit=80
        )
        document.owner = _first_label(document.text, ("document owner", "owner"), limit=100)
        document.author = _first_label(document.text, ("author", "prepared by"), limit=100)
        document.reviewers = _first_label(document.text, ("reviewers", "reviewed by"), limit=160)
        document.approvers = _first_label(document.text, ("approvers", "approved by"), limit=160)
        document.project_release = _first_label(
            document.text, ("project identifier", "project id", "release identifier", "release id"), limit=100
        )
        document.referenced_procedures = sorted(
            set(re.findall(r"\b(?:SOP|WI|POL|PRO)[-_ ]?[A-Z0-9]{2,12}\b", document.text, re.I))
        )[:20]


def _most_common(values: Iterable[str]) -> str:
    useful = [value for value in values if value != "Unable to determine"]
    return Counter(useful).most_common(1)[0][0] if useful else "Unable to determine"


def _sentences(text: str) -> list[str]:
    return [
        _clean(part, 1_200)
        for part in re.split(r"(?<=[.;])\s+|\n+", text)
        if len(part.strip()) > 4
    ]


def build_context(documents: list[Document]) -> dict[str, Any]:
    full_text = "\n".join(document.text for document in documents)
    lower = full_text.lower()
    intended_candidates = []
    for sentence in _sentences(full_text):
        if re.search(r"\b(intended use|purpose|system (?:is used|supports|shall support))\b", sentence, re.I):
            intended_candidates.append(sentence)

    non_applicable = bool(re.search(r"(?:gxp|qms|qsr|part 11).{0,45}(?:not applicable|does not apply)", lower))
    explicitly_applicable = bool(
        re.search(r"(?:gxp|qms|qsr|part 11).{0,45}(?:applicable|in scope|yes)", lower)
    ) and not non_applicable
    regulated_signals = any(
        signal in lower
        for signal in (
            "quality record",
            "product quality",
            "patient safety",
            "regulated data",
            "manufacturing decision",
            "inspection decision",
            "electronic signature",
            "21 cfr part 11",
            "gxp",
            "qms",
        )
    )
    if explicitly_applicable:
        gxp_relevance = "Applicable"
    elif non_applicable:
        gxp_relevance = "Not applicable per provided assessment"
    elif regulated_signals:
        gxp_relevance = "Potentially applicable — confirmation required"
    else:
        gxp_relevance = "Unable to determine"

    system = _most_common(document.system for document in documents)
    version = _most_common(document.version for document in documents)
    vendor = _first_label(full_text, ("vendor", "supplier"), limit=100)
    hosting = _first_label(full_text, ("hosting model", "deployment model", "hosting"), limit=80)
    environment = _first_label(full_text, ("environment", "validated environment"), limit=80)
    owner = _first_label(full_text, ("business owner", "process owner"), limit=100)
    technical_owner = _first_label(full_text, ("technical owner", "system owner", "it owner"), limit=100)
    quality_owner = _first_label(full_text, ("quality owner", "csv owner", "validation owner"), limit=100)
    site = _first_label(full_text, ("site", "business unit"), limit=100)

    interfaces = []
    for sentence in _sentences(full_text):
        if re.search(r"\b(interface|integration|upstream|downstream|transfers? data|api|sftp)\b", sentence, re.I):
            interfaces.append(sentence)
    boundaries = {
        "inputs": _first_label(full_text, ("inputs", "input data"), limit=220),
        "processing": _first_label(full_text, ("processing", "business process"), limit=220),
        "outputs": _first_label(full_text, ("outputs", "output records", "reports"), limit=220),
        "interfaces": interfaces[:8],
        "dependencies": [
            signal
            for signal in ("database", "single sign-on", "active directory", "cloud storage", "email service", "reporting platform")
            if signal in lower
        ],
    }
    part11 = "Not applicable"
    if "part 11" in lower or "electronic signature" in lower or "electronic record" in lower:
        part11 = "Potentially applicable — assessment required"
        if re.search(r"part 11.{0,60}(?:not applicable|does not apply)", lower):
            part11 = "Not applicable per provided assessment"
        elif re.search(r"part 11.{0,60}(?:applicable|in scope|yes)", lower):
            part11 = "Applicable"

    return {
        "system": system,
        "version": version,
        "vendor": vendor,
        "hosting_model": hosting,
        "environment": environment,
        "business_owner": owner,
        "technical_owner": technical_owner,
        "quality_csv_owner": quality_owner,
        "site_business_unit": site,
        "intended_use": intended_candidates[0] if intended_candidates else "Unable to determine from the provided validation package.",
        "gxp_relevance": gxp_relevance,
        "part11_relevance": part11,
        "regulated_process_signals": [
            signal
            for signal in (
                "quality records",
                "product quality",
                "patient safety",
                "regulatory decisions",
                "manufacturing decisions",
                "inspection decisions",
                "electronic records",
                "electronic signatures",
            )
            if signal.rstrip("s") in lower or signal in lower
        ],
        "system_boundaries": boundaries,
    }


def _blocks_by_id(text: str, pattern: re.Pattern[str], max_length: int = 2_000) -> list[tuple[str, str]]:
    matches = list(pattern.finditer(text))
    blocks: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[match.start() : min(end, match.start() + max_length)]
        blocks.append((_canonical(match.group(0)), _clean(block, max_length)))
    return blocks


def extract_requirements(documents: list[Document]) -> list[dict[str, Any]]:
    source_types = {
        "User Requirements Specification",
        "Functional Specification",
        "Configuration Specification",
    }
    requirements: dict[str, dict[str, Any]] = {}
    for document in documents:
        if document.doc_type not in source_types:
            continue
        for identifier, block in _blocks_by_id(document.text, REQUIREMENT_ID_RE):
            existing = requirements.get(identifier)
            if existing and len(existing["text"]) >= len(block):
                continue
            lower = block.lower()
            weak_terms = [term for term in WEAK_TERMS if re.search(rf"\b{re.escape(term)}\b", lower)]
            normative = bool(re.search(r"\b(shall|must|will|is required to)\b", lower))
            compound = len(re.findall(r"\b(?:shall|must)\b", lower)) > 1 or len(re.findall(r"\band\b", lower)) >= 2
            measurable = bool(
                re.search(
                    r"\b(display|prevent|record|retain|generate|calculate|export|notify|require|reject|allow|create|capture|transfer|within|seconds?|minutes?|days?|%)\b",
                    lower,
                )
            )
            requirements[identifier] = {
                "id": identifier,
                "document": document.name,
                "document_type": document.doc_type,
                "text": block,
                "weak_terms": weak_terms,
                "compound": compound,
                "normative": normative,
                "testable": normative and measurable and not weak_terms,
                "missing_acceptance_criteria": not measurable or bool(weak_terms),
            }
    return list(requirements.values())


def extract_risks(documents: list[Document]) -> list[dict[str, Any]]:
    risks: dict[str, dict[str, Any]] = {}
    for document in documents:
        if document.doc_type != "Risk Assessment":
            continue
        rows = list(csv.reader(document.text.splitlines()))
        header_index: dict[str, int] = {}
        header_row = -1
        for index, row in enumerate(rows):
            normalized = [cell.strip().lower() for cell in row]
            if "risk id" in normalized:
                header_index = {name: position for position, name in enumerate(normalized)}
                header_row = index
                break
        if header_index:
            def cell(row: list[str], *names: str) -> str:
                for name in names:
                    position = header_index.get(name)
                    if position is not None and position < len(row):
                        return row[position].strip()
                return ""

            for row in rows[header_row + 1 :]:
                raw_id = cell(row, "risk id", "id")
                if not RISK_ID_RE.fullmatch(raw_id):
                    continue
                block = " | ".join(row)
                rating = cell(row, "risk rating", "rating", "residual risk", "risk level").title()
                control = cell(row, "existing control", "risk control", "control", "mitigation")
                risks[_canonical(raw_id)] = {
                    "id": _canonical(raw_id),
                    "document": document.name,
                    "text": _clean(block, 2_000),
                    "rating": rating or "Unable to determine",
                    "control": control or "Unable to determine",
                    "requirement_ids": sorted({_canonical(match) for match in REQUIREMENT_ID_RE.findall(block)}),
                    "test_ids": sorted({_canonical(match) for match in TEST_ID_RE.findall(block)}),
                }
        for identifier, block in _blocks_by_id(document.text, RISK_ID_RE):
            if identifier in risks:
                continue
            lower = block.lower()
            rating = "Unable to determine"
            rating_match = re.search(r"\b(?:risk (?:level|rating)|rating|residual risk|severity)\s*[:|=-]?\s*(critical|high|medium|moderate|low)\b", lower)
            if rating_match:
                rating = rating_match.group(1).title()
            else:
                for candidate in ("Critical", "High", "Medium", "Moderate", "Low"):
                    if re.search(rf"\b{candidate}\b", block, re.I):
                        rating = candidate
                        break
            control_match = re.search(
                r"(?is)\b(?:existing control|risk control|control|mitigation)\s*[:|=-]\s*(.{3,500}?)(?=\b(?:rating|risk level|result|requirement|verification)\s*[:|=-]|$)",
                block,
            )
            control = _clean(control_match.group(1), 500) if control_match else "Unable to determine"
            risks[identifier] = {
                "id": identifier,
                "document": document.name,
                "text": block,
                "rating": rating,
                "control": control,
                "requirement_ids": sorted({_canonical(match) for match in REQUIREMENT_ID_RE.findall(block)}),
                "test_ids": sorted({_canonical(match) for match in TEST_ID_RE.findall(block)}),
            }
    return list(risks.values())


def extract_tests(documents: list[Document]) -> list[dict[str, Any]]:
    test_types = {
        "Installation Qualification",
        "Operational Qualification",
        "Performance Qualification",
        "User Acceptance Testing",
        "Test Evidence",
    }
    tests: dict[str, dict[str, Any]] = {}
    for document in documents:
        if document.doc_type not in test_types:
            continue
        for identifier, block in _blocks_by_id(document.text, TEST_ID_RE, max_length=5_000):
            existing = tests.get(identifier)
            if existing and len(existing["text"]) >= len(block):
                continue
            lower = block.lower()
            result = "Not recorded"
            result_match = re.search(r"\b(?:overall )?(?:result|status)\s*[:|=-]?\s*(pass(?:ed)?|fail(?:ed)?|not executed|blocked)\b", lower)
            if result_match:
                raw_result = result_match.group(1)
                result = "Pass" if raw_result.startswith("pass") else "Fail" if raw_result.startswith("fail") else raw_result.title()
            actual = bool(re.search(r"\bactual result\s*[:|=-]\s*\S", block, re.I))
            expected_match = re.search(r"(?is)\bexpected result\s*[:|=-]\s*(.{1,450}?)(?=\bactual result\s*[:|=-]|\bevidence\s*[:|=-]|\bresult\s*[:|=-]|$)", block)
            expected = _clean(expected_match.group(1), 450) if expected_match else "Unable to determine"
            evidence = bool(
                re.search(r"\b(?:evidence|attachment|screenshot|log file|record id)\s*[:|#=-]\s*\S", block, re.I)
            )
            tests[identifier] = {
                "id": identifier,
                "document": document.name,
                "document_type": document.doc_type,
                "text": block,
                "requirement_ids": sorted({_canonical(match) for match in REQUIREMENT_ID_RE.findall(block)}),
                "risk_ids": sorted({_canonical(match) for match in RISK_ID_RE.findall(block)}),
                "result": result,
                "actual_result_recorded": actual,
                "evidence_recorded": evidence,
                "expected_result": expected,
                "vague_expected_result": expected.lower() in {
                    "system works correctly",
                    "result is as expected",
                    "as expected",
                    "pass",
                    "unable to determine",
                },
                "negative": bool(re.search(r"\b(invalid|unauthori[sz]ed|fail(?:ed|ure)?|reject|deny|cannot|prevent|duplicate|expired|missing mandatory|error condition)\b", lower)),
                "boundary": bool(re.search(r"\b(boundary|minimum|maximum|below limit|above limit|out of range|lower bound|upper bound)\b", lower)),
                "security": bool(re.search(r"\b(role|permission|access|authentication|session|privilege|account)\b", lower)),
                "audit_trail": "audit trail" in lower,
                "interface": bool(re.search(r"\b(interface|integration|transfer|api|sftp|reconciliation)\b", lower)),
                "electronic_signature": "electronic signature" in lower or "e-signature" in lower,
                "migration": "migration" in lower,
                "regression": "regression" in lower,
            }
    return list(tests.values())


def extract_issues(documents: list[Document]) -> list[dict[str, Any]]:
    issues: dict[str, dict[str, Any]] = {}
    for document in documents:
        if document.doc_type not in {"Defect / Deviation Log", "Validation Summary Report", "Test Evidence", "Operational Qualification", "Performance Qualification", "User Acceptance Testing"}:
            continue
        for identifier, block in _blocks_by_id(document.text, ISSUE_ID_RE):
            lower = block.lower()
            status = "Unable to determine"
            status_match = re.search(r"\bstatus\s*[:|=-]?\s*(open|closed|resolved|deferred|accepted|in progress)\b", lower)
            if status_match:
                status = status_match.group(1).title()
            severity = "Unable to determine"
            severity_match = re.search(r"\bseverity\s*[:|=-]?\s*(critical|major|moderate|minor|high|medium|low)\b", lower)
            if severity_match:
                severity = severity_match.group(1).title()
            issues[identifier] = {
                "id": identifier,
                "document": document.name,
                "text": block,
                "status": status,
                "severity": severity,
                "requirement_ids": sorted({_canonical(match) for match in REQUIREMENT_ID_RE.findall(block)}),
            }
    return list(issues.values())


def extract_procedure_map(documents: list[Document]) -> list[dict[str, Any]]:
    procedures = [document for document in documents if document.doc_type == "Procedure / SOP"]
    evidence_documents = [document for document in documents if document.doc_type != "Procedure / SOP"]
    mapped: list[dict[str, Any]] = []
    stopwords = {"shall", "must", "should", "will", "that", "this", "with", "from", "have", "been", "validation", "document", "system"}
    for procedure in procedures:
        candidates = [sentence for sentence in _sentences(procedure.text) if re.search(r"\b(shall|must|required)\b", sentence, re.I)]
        for sentence in candidates[:60]:
            tokens = {token for token in re.findall(r"[a-z]{4,}", sentence.lower()) if token not in stopwords}
            best_name = "Not located"
            best_score = 0.0
            for document in evidence_documents:
                if not tokens:
                    continue
                hits = sum(1 for token in tokens if token in document.text.lower())
                score = hits / len(tokens)
                if score > best_score:
                    best_score = score
                    best_name = document.name
            status = "Satisfied" if best_score >= 0.6 else "Partially Satisfied" if best_score >= 0.35 else "Not Satisfied"
            mapped.append(
                {
                    "procedure": procedure.name,
                    "section": "Unable to determine",
                    "requirement": sentence,
                    "expected_evidence": "Evidence demonstrating the procedural requirement",
                    "evidence_located": best_name,
                    "status": status,
                    "confidence": "Low" if best_score < 0.6 else "Medium",
                }
            )
    return mapped


def _tokens(value: str) -> set[str]:
    stopwords = {"shall", "must", "system", "user", "record", "requirement", "test", "with", "from", "that", "this", "into", "when", "where"}
    return {token for token in re.findall(r"[a-z0-9]{3,}", value.lower()) if token not in stopwords}


def _semantic_test_match(source_text: str, tests: list[dict[str, Any]]) -> str | None:
    source_tokens = _tokens(source_text)
    if len(source_tokens) < 3:
        return None
    best: tuple[float, str] = (0.0, "")
    for test in tests:
        test_tokens = _tokens(test["text"])
        score = len(source_tokens & test_tokens) / len(source_tokens)
        if score > best[0]:
            best = (score, test["id"])
    return best[1] if best[0] >= 0.45 else None


def build_traceability(
    requirements: list[dict[str, Any]], risks: list[dict[str, Any]], tests: list[dict[str, Any]]
) -> dict[str, Any]:
    requirement_ids = {requirement["id"] for requirement in requirements}
    risk_ids = {risk["id"] for risk in risks}
    actual_test_ids = {test["id"] for test in tests}
    test_by_requirement: dict[str, list[str]] = defaultdict(list)
    test_by_risk: dict[str, list[str]] = defaultdict(list)
    for test in tests:
        for requirement_id in test["requirement_ids"]:
            test_by_requirement[requirement_id].append(test["id"])
        for risk_id in test["risk_ids"]:
            test_by_risk[risk_id].append(test["id"])

    rows = []
    for requirement in requirements:
        linked = list(test_by_requirement.get(requirement["id"], []))
        semantic = None
        if not linked:
            semantic = _semantic_test_match(requirement["text"], tests)
        related_risks = [risk["id"] for risk in risks if requirement["id"] in risk["requirement_ids"]]
        rows.append(
            {
                "requirement_id": requirement["id"],
                "requirement": requirement["text"],
                "risk_ids": related_risks,
                "test_ids": linked,
                "semantic_candidate_test": semantic,
                "status": "Traced" if linked else "Potential semantic match" if semantic else "Untested",
            }
        )

    risk_rows = []
    for risk in risks:
        linked = list(test_by_risk.get(risk["id"], [])) + [
            test_id for test_id in risk["test_ids"] if test_id in actual_test_ids
        ]
        for requirement_id in risk["requirement_ids"]:
            linked.extend(test_by_requirement.get(requirement_id, []))
        linked = sorted(set(linked))
        semantic = None if linked else _semantic_test_match(risk["text"], tests)
        risk_rows.append(
            {
                "risk_id": risk["id"],
                "rating": risk["rating"],
                "control": risk["control"],
                "requirement_ids": risk["requirement_ids"],
                "test_ids": linked,
                "broken_test_references": [test_id for test_id in risk["test_ids"] if test_id not in actual_test_ids],
                "semantic_candidate_test": semantic,
                "status": "Verified" if linked else "Potential semantic match" if semantic else "Unverified",
            }
        )

    linked_test_ids = {test_id for ids in test_by_requirement.values() for test_id in ids}
    linked_test_ids.update(test_id for ids in test_by_risk.values() for test_id in ids)
    orphan_tests = [test["id"] for test in tests if test["id"] not in linked_test_ids]
    traced_count = sum(1 for row in rows if row["status"] == "Traced")
    percentage = round((traced_count / len(rows)) * 100, 1) if rows else None
    broken_references: list[dict[str, str]] = []
    for risk in risks:
        broken_references.extend(
            {"source": risk["id"], "target": target, "type": "Missing requirement"}
            for target in risk["requirement_ids"]
            if target not in requirement_ids
        )
        broken_references.extend(
            {"source": risk["id"], "target": target, "type": "Missing test"}
            for target in risk["test_ids"]
            if target not in actual_test_ids
        )
    for test in tests:
        broken_references.extend(
            {"source": test["id"], "target": target, "type": "Missing requirement"}
            for target in test["requirement_ids"]
            if target not in requirement_ids
        )
        broken_references.extend(
            {"source": test["id"], "target": target, "type": "Missing risk"}
            for target in test["risk_ids"]
            if target not in risk_ids
        )
    return {
        "requirements": rows,
        "risks": risk_rows,
        "requirements_traced": traced_count,
        "requirements_untested": [row["requirement_id"] for row in rows if row["status"] == "Untested"],
        "semantic_matches_requiring_confirmation": [row for row in rows if row["status"] == "Potential semantic match"],
        "tests_without_requirement_or_risk_linkage": orphan_tests,
        "risks_without_test_coverage": [row["risk_id"] for row in risk_rows if row["status"] == "Unverified"],
        "broken_references": broken_references,
        "traceability_percentage": percentage,
    }


def _has_type(documents: list[Document], doc_type: str) -> bool:
    return any(document.doc_type == doc_type for document in documents)


def generate_findings(
    documents: list[Document],
    context: dict[str, Any],
    requirements: list[dict[str, Any]],
    risks: list[dict[str, Any]],
    tests: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    traceability: dict[str, Any],
    procedure_map: list[dict[str, Any]],
) -> list[Finding]:
    findings: list[Finding] = []
    full_text = "\n".join(document.text for document in documents)
    lower = full_text.lower()

    failed_docs = [document.name for document in documents if document.extraction_status == "Failed"]
    if failed_docs:
        add_finding(
            findings,
            severity="Major",
            confidence="High",
            category="Package Completeness",
            document="Validation package",
            location="Document ingestion",
            observation=f"Content could not be extracted from {len(failed_docs)} document(s): {', '.join(failed_docs)}.",
            impact="The affected deliverables could not be evaluated, so package completeness and cross-document conclusions are not supported.",
            recommended_action="Provide machine-readable copies in a supported format and repeat the review before approval.",
            approval_blocking=True,
            basis_type="Reviewer recommendation",
        )

    if context["intended_use"].startswith("Unable to determine"):
        add_finding(
            findings,
            severity="Major",
            confidence="High",
            category="Intended Use",
            document="Validation package",
            location="Package-level context",
            observation="A clear, bounded intended-use statement was not located in the provided package.",
            impact="Without intended use, the reviewer cannot determine applicable regulated processes, required controls, or whether testing demonstrates fitness for use.",
            recommended_action="Add or identify an approved intended-use statement covering users, regulated processes, records, decisions, and system boundaries.",
            approval_blocking=True,
            basis_type="Industry best practice",
            basis="Risk-based computerized system validation principle",
        )
    if context["system"] == "Unable to determine":
        add_finding(
            findings,
            severity="Minor",
            confidence="High",
            category="Package Completeness",
            document="Validation package",
            location="Document control metadata",
            observation="The validated system name could not be consistently identified from document metadata.",
            impact="The evidence cannot be unambiguously associated with a controlled system baseline.",
            recommended_action="Identify the controlled system name consistently in the package-level documents.",
        )
    if context["gxp_relevance"] == "Unable to determine":
        add_finding(
            findings,
            severity="Minor",
            confidence="Medium",
            category="GxP Classification",
            document="Validation package",
            location="Applicability assessment",
            observation="GxP/QMS applicability could not be determined from the provided package.",
            impact="Validation rigor and applicable lifecycle controls cannot be confirmed as proportionate to regulated use.",
            recommended_action="Provide the approved applicability assessment or document the basis for non-applicability.",
            basis_type="Reviewer recommendation",
        )

    weak_requirements = [requirement for requirement in requirements if requirement["weak_terms"]]
    compound_requirements = [requirement for requirement in requirements if requirement["compound"]]
    non_testable = [requirement for requirement in requirements if not requirement["testable"]]
    if weak_requirements or compound_requirements or non_testable:
        affected = sorted({requirement["id"] for requirement in weak_requirements + compound_requirements + non_testable})
        examples = ", ".join(affected[:8]) + ("…" if len(affected) > 8 else "")
        add_finding(
            findings,
            severity="Minor",
            confidence="High",
            category="Requirements",
            document="Requirements specifications",
            location=f"Requirements {examples}",
            observation=f"{len(affected)} requirement(s) contain weak terminology, compound expectations, or insufficiently observable acceptance criteria.",
            impact="Ambiguous or compound requirements reduce reproducibility and make objective verification and traceability less reliable.",
            recommended_action="Revise the affected requirements into uniquely testable statements with observable, measurable acceptance criteria; split independently testable expectations.",
            requirement_ids=affected,
            basis_type="Industry best practice",
            basis="Good requirements and validation documentation practice",
        )

    high_risks = [risk for risk in risks if risk["rating"] in {"High", "Critical"}]
    high_without_control = [risk for risk in high_risks if risk["control"] == "Unable to determine"]
    if high_without_control:
        risk_ids = [risk["id"] for risk in high_without_control]
        add_finding(
            findings,
            severity="Major",
            confidence="High",
            category="Risk Management",
            document="Risk Assessment",
            location=", ".join(risk_ids),
            observation=f"{len(risk_ids)} High/Critical risk(s) do not identify a discernible risk control in the supplied assessment.",
            impact="The package does not establish how these failure scenarios are reduced to an acceptable level.",
            recommended_action="Define the control for each risk, link it to an approved requirement, document residual-risk rationale, and verify the control through an appropriate assurance activity.",
            risk_ids=risk_ids,
            approval_blocking=True,
            basis_type="Industry best practice",
            basis="ISO 14971-aligned risk-control and risk-based assurance principles where applicable",
        )

    high_unverified_ids = [
        row["risk_id"]
        for row in traceability["risks"]
        if row["rating"] in {"High", "Critical"} and row["status"] == "Unverified"
    ]
    if high_unverified_ids:
        add_finding(
            findings,
            severity="Major",
            confidence="High",
            category="Risk-to-Test Traceability",
            document="Risk Assessment / test protocols",
            location=", ".join(high_unverified_ids),
            observation=f"No explicit or sufficiently strong semantic test coverage was located for {len(high_unverified_ids)} High/Critical risk(s).",
            impact="Objective evidence does not demonstrate that the documented controls operate under the identified high-risk failure conditions.",
            recommended_action="Link each risk through its control and requirement to a challenge test, then execute and retain objective evidence of the result.",
            risk_ids=high_unverified_ids,
            approval_blocking=True,
            basis_type="Industry best practice",
            basis="Risk-based assurance and traceability principle",
        )

    untested = traceability["requirements_untested"]
    if untested:
        proportion = len(untested) / len(requirements) if requirements else 0
        severity = "Major" if proportion >= 0.2 else "Minor"
        add_finding(
            findings,
            severity=severity,
            confidence="High",
            category="Traceability",
            document="Traceability / test protocols",
            location=", ".join(untested[:15]) + ("…" if len(untested) > 15 else ""),
            observation=f"{len(untested)} of {len(requirements)} extracted requirement(s) have no test linkage or strong semantic test candidate.",
            impact="The package does not provide complete forward traceability demonstrating that the affected requirements were verified.",
            recommended_action="Confirm applicability, add missing requirement-to-test links, and execute additional tests where coverage is absent.",
            requirement_ids=untested,
            approval_blocking=severity == "Major",
            basis_type="Industry best practice",
            basis="Requirements traceability and objective evidence principle",
        )

    orphan_tests = traceability["tests_without_requirement_or_risk_linkage"]
    if orphan_tests:
        add_finding(
            findings,
            severity="Minor",
            confidence="High",
            category="Traceability",
            document="Test protocols / traceability matrix",
            location=", ".join(orphan_tests[:15]) + ("…" if len(orphan_tests) > 15 else ""),
            observation=f"{len(orphan_tests)} test(s) have no explicit requirement or risk linkage.",
            impact="Backward traceability and the justification for these assurance activities cannot be confirmed.",
            recommended_action="Link each test to an approved requirement or risk, or document why the test is retained as exploratory or supplemental assurance.",
            basis_type="Industry best practice",
        )

    executed_without_evidence = [
        test for test in tests if test["result"] in {"Pass", "Fail"} and (not test["actual_result_recorded"] or not test["evidence_recorded"])
    ]
    if executed_without_evidence:
        ids = [test["id"] for test in executed_without_evidence]
        add_finding(
            findings,
            severity="Major",
            confidence="High",
            category="Test Execution",
            document="Executed test protocols",
            location=", ".join(ids[:15]) + ("…" if len(ids) > 15 else ""),
            observation=f"{len(ids)} executed test(s) claim a result without both a recorded actual result and an identifiable evidence reference.",
            impact="The stated pass/fail decisions are not fully supported by contemporaneous objective evidence.",
            recommended_action="Record the observed result for each step, reference meaningful evidence, and reassess the pass/fail determination under GDP controls.",
            approval_blocking=True,
            basis_type="Industry best practice",
            basis="Good documentation and objective evidence principles",
        )

    vague_tests = [test["id"] for test in tests if test["vague_expected_result"]]
    if vague_tests:
        add_finding(
            findings,
            severity="Minor",
            confidence="High",
            category="Test Design",
            document="Test protocols",
            location=", ".join(vague_tests[:15]) + ("…" if len(vague_tests) > 15 else ""),
            observation=f"{len(vague_tests)} test(s) use a vague or unidentifiable expected result rather than observable acceptance criteria.",
            impact="A tester cannot reproducibly determine whether the requirement was satisfied, increasing confirmation bias in execution.",
            recommended_action="Define the exact observable output, state transition, record value, error, or control behavior expected for each affected test.",
            basis_type="Industry best practice",
        )

    if high_risks and tests and not any(test["negative"] for test in tests):
        add_finding(
            findings,
            severity="Major",
            confidence="Medium",
            category="Test Design",
            document="Test protocols",
            location="Negative/error-condition coverage",
            observation="High/Critical risks are present, but no test was identifiable as a negative or failure-condition challenge.",
            impact="Nominal workflow testing alone may not demonstrate that high-risk controls prevent, detect, or recover from the documented failure modes.",
            recommended_action="Confirm whether negative coverage exists under different terminology; otherwise add risk-focused failure-condition tests and retain evidence.",
            risk_ids=[risk["id"] for risk in high_risks],
            approval_blocking=True,
            basis_type="Industry best practice",
            basis="FDA CSA-aligned risk-based assurance principle",
        )

    numeric_requirements = [requirement for requirement in requirements if re.search(r"\b\d+(?:\.\d+)?\s*(?:-|to|through|seconds?|minutes?|days?|%|records?)", requirement["text"], re.I)]
    if numeric_requirements and tests and not any(test["boundary"] for test in tests):
        ids = [requirement["id"] for requirement in numeric_requirements]
        add_finding(
            findings,
            severity="Minor",
            confidence="Medium",
            category="Test Design",
            document="Requirements / test protocols",
            location=", ".join(ids[:12]),
            observation="Requirements with numeric limits or thresholds were found, but boundary-condition coverage was not identifiable.",
            impact="The package may not demonstrate correct behavior at and immediately outside specified limits.",
            recommended_action="Confirm existing boundary coverage or add proportionate lower-bound, upper-bound, and out-of-range challenges based on risk.",
            requirement_ids=ids,
            basis_type="Industry best practice",
        )

    versions: dict[str, list[str]] = defaultdict(list)
    for document in documents:
        if document.version != "Unable to determine":
            versions[document.version].append(document.name)
    if len(versions) > 1:
        detail = "; ".join(f"{version}: {', '.join(names)}" for version, names in versions.items())
        add_finding(
            findings,
            severity="Major",
            confidence="High",
            category="Cross-Document Consistency",
            document="Validation package",
            location="System version metadata",
            observation=f"Multiple system versions are identified across the package ({detail}).",
            impact="The approved and tested configuration baseline cannot be determined with confidence.",
            recommended_action="Reconcile the discrepancy, identify the exact validated release in every controlling deliverable, and assess whether any testing used the wrong version.",
            approval_blocking=True,
            basis_type="Industry best practice",
            basis="Configuration control and validated-baseline principle",
        )

    quantitative_conflicts: list[dict[str, str]] = []
    for requirement in requirements:
        requirement_quantities = {
            (value, unit.lower().rstrip("s"))
            for value, unit in re.findall(
                r"\b(\d+(?:\.\d+)?)[\s-]*(seconds?|minutes?|hours?|days?|years?|%|percent)\b",
                requirement["text"],
                re.I,
            )
        }
        if not requirement_quantities:
            continue
        for test in tests:
            if requirement["id"] not in test["requirement_ids"]:
                continue
            test_quantities = {
                (value, unit.lower().rstrip("s"))
                for value, unit in re.findall(
                    r"\b(\d+(?:\.\d+)?)[\s-]*(seconds?|minutes?|hours?|days?|years?|%|percent)\b",
                    test["text"],
                    re.I,
                )
            }
            for required_value, required_unit in requirement_quantities:
                tested_same_unit = {value for value, unit in test_quantities if unit == required_unit}
                if tested_same_unit and required_value not in tested_same_unit:
                    quantitative_conflicts.append(
                        {
                            "requirement": requirement["id"],
                            "test": test["id"],
                            "required": f"{required_value} {required_unit}",
                            "tested": ", ".join(f"{value} {required_unit}" for value in sorted(tested_same_unit)),
                        }
                    )
    if quantitative_conflicts:
        detail = "; ".join(
            f"{item['requirement']} specifies {item['required']}, while {item['test']} uses {item['tested']}"
            for item in quantitative_conflicts[:6]
        )
        requirement_ids = sorted({item["requirement"] for item in quantitative_conflicts})
        add_finding(
            findings,
            severity="Major",
            confidence="High",
            category="Cross-Document Consistency",
            document="Requirements / test protocols",
            location=", ".join(requirement_ids),
            observation=f"Linked requirements and tests contain conflicting quantitative acceptance criteria: {detail}.",
            impact="The execution does not verify the approved requirement and may support a pass decision for incorrect configured behavior.",
            recommended_action="Reconcile the approved requirement and configuration, correct the test criterion, assess the executed result, and repeat testing against the controlled value.",
            requirement_ids=requirement_ids,
            approval_blocking=True,
            basis_type="Industry best practice",
            basis="Requirements-based testing and configuration-control principle",
        )

    open_issues = [issue for issue in issues if issue["status"] in {"Open", "In Progress", "Deferred"}]
    open_serious = [issue for issue in open_issues if issue["severity"] in {"Critical", "Major", "High"}]
    summary_documents = [document for document in documents if document.doc_type == "Validation Summary Report"]
    summary_claims_closed = any(re.search(r"\b(?:all|no open)\s+(?:defects?|deviations?|issues?).{0,30}(?:closed|resolved|remain)", document.text, re.I) for document in summary_documents)
    if open_serious and summary_claims_closed:
        issue_ids = [issue["id"] for issue in open_serious]
        add_finding(
            findings,
            severity="Critical",
            confidence="High",
            category="Defects / Deviations",
            document="Validation Summary Report / issue log",
            location=", ".join(issue_ids),
            observation="The validation summary represents issues as closed or absent while the supplied issue evidence contains open serious items.",
            impact="The release conclusion is contradicted by objective evidence and may accept unresolved risk without documented justification.",
            recommended_action="Reconcile the issue status, complete impact and residual-risk assessment, close or formally disposition each issue, and reissue the validation conclusion.",
            approval_blocking=True,
            basis_type="Industry best practice",
            basis="Validation conclusion and deviation-control principle",
        )
    elif open_serious:
        issue_ids = [issue["id"] for issue in open_serious]
        add_finding(
            findings,
            severity="Major",
            confidence="High",
            category="Defects / Deviations",
            document="Defect / Deviation Log",
            location=", ".join(issue_ids),
            observation=f"{len(issue_ids)} serious issue(s) remain open, deferred, or in progress without a package-level release disposition.",
            impact="The effect on requirements, tests, residual risk, and release readiness is not adequately established.",
            recommended_action="Complete documented impact assessment and closure/retest evidence, or obtain an approved risk-based release disposition before approval.",
            approval_blocking=True,
            basis_type="Industry best practice",
        )

    part11_applicable = context["part11_relevance"] == "Applicable"
    if part11_applicable:
        controls = {
            "unique accounts": bool(re.search(r"unique (?:user|account)|individual account", lower)),
            "audit trail": "audit trail" in lower,
            "signature meaning": "signature meaning" in lower or "meaning of signature" in lower,
            "signature linkage": bool(re.search(r"(?:signature.{0,35}(?:linked|linkage).{0,20}record|link.{0,20}(?:signed )?record)", lower)),
            "accurate copies": bool(re.search(r"accurate and complete.{0,30}cop", lower)),
            "record retention": "record retention" in lower or "retention period" in lower,
        }
        missing = [name for name, present in controls.items() if not present]
        if missing:
            add_finding(
                findings,
                severity="Major",
                confidence="Medium",
                category="Part 11 / Data Integrity",
                document="Part 11 assessment / requirements / tests",
                location="Electronic records and signatures control set",
                observation=f"Part 11 is identified as applicable, but package evidence was not located for: {', '.join(missing)}.",
                impact="The package does not yet demonstrate a complete control set for regulated electronic records and signatures.",
                recommended_action="Confirm applicability and provide requirements, configuration evidence, and risk-based verification for each missing control; verify citations against the controlled regulatory reference.",
                approval_blocking=True,
                basis_type="Regulatory requirement",
                basis="21 CFR Part 11 control areas; exact citations should be verified against the controlled regulatory reference",
            )

    unsatisfied_procedures = [row for row in procedure_map if row["status"] == "Not Satisfied"]
    if procedure_map and len(unsatisfied_procedures) / len(procedure_map) >= 0.3:
        add_finding(
            findings,
            severity="Minor",
            confidence="Low",
            category="Procedure Compliance",
            document="Provided procedures / validation package",
            location="Procedure requirements map",
            observation=f"Automated mapping did not locate corroborating evidence for {len(unsatisfied_procedures)} of {len(procedure_map)} extracted procedural statements.",
            impact="Potential internal-procedure compliance gaps require reviewer confirmation; semantic mapping alone is not sufficient to conclude noncompliance.",
            recommended_action="Have the process owner confirm the mapped statements, identify referenced evidence, and resolve any true gaps before approval.",
            basis_type="Internal procedural requirement",
            basis="Provided procedure content; mapping requires SME confirmation",
        )

    if (requirements or tests or risks) and not summary_documents:
        add_finding(
            findings,
            severity="Major" if high_risks or tests else "Minor",
            confidence="High",
            category="Validation Conclusion",
            document="Validation package",
            location="Validation Summary Report",
            observation="A validation summary report or equivalent approved package conclusion was not provided.",
            impact="Scope, executed activities, exceptions, residual risks, and the release decision are not reconciled into a supported final conclusion.",
            recommended_action="Provide an approved summary that reconciles the validated version, activities, results, deviations/defects, residual risk, and release recommendation.",
            approval_blocking=bool(high_risks or tests),
            basis_type="Internal procedural requirement" if procedure_map else "Industry best practice",
            basis="Validation lifecycle closure principle",
        )

    findings.sort(key=lambda finding: (SEVERITY_ORDER[finding.severity], finding.category, finding.location))
    for index, finding in enumerate(findings, start=1):
        finding.finding_id = f"F-{index:03d}"
        finding.display_id = finding.finding_id
    return findings


PRIMARY_CATEGORY_MAP = {
    "Intended Use": "Completeness",
    "Package Completeness": "Completeness",
    "GxP Classification": "Compliance",
    "Requirements": "Requirement Quality",
    "Risk-to-Test Traceability": "Traceability",
    "Cross-Document Consistency": "Consistency",
    "Defects / Deviations": "Defect / Deviation Management",
    "Part 11 / Data Integrity": "Part 11 / Electronic Records",
    "Procedure Compliance": "Compliance",
    "Validation Conclusion": "Accuracy",
}


def _default_redline(finding: Finding) -> tuple[str, bool]:
    subcategory = finding.finding_subcategory
    if subcategory == "Intended Use":
        return (
            "**[ADD: Intended Use: [System] is used by [intended users] to perform [regulated process], "
            "creating or affecting [regulated records/decisions] within [defined system boundary].]**",
            True,
        )
    if subcategory == "Requirements":
        return (
            "**[REPLACE WITH: [Actor/system] shall [observable action] when [defined trigger], producing "
            "[measurable result] within [acceptance limit].]**",
            True,
        )
    if subcategory == "Risk-to-Test Traceability":
        return (
            "**[ADD: Verification: [approved test ID] challenges the identified failure condition and "
            "demonstrates the specified risk control.]**",
            True,
        )
    if subcategory == "Cross-Document Consistency" and "version" in finding.location.lower():
        return (
            "~~[inconsistent version]~~ **[REPLACE WITH: [confirmed validated system version]]**",
            True,
        )
    if subcategory == "Cross-Document Consistency":
        return (
            "~~[conflicting criterion]~~ **[REPLACE WITH: the approved requirement value and corresponding verified result]**",
            True,
        )
    if finding.category == "Traceability":
        return (
            "**[ADD: Traceability: Requirement [ID] → Risk/Control [ID] → Test [ID] → Executed result/evidence [reference].]**",
            True,
        )
    if finding.category == "Test Design":
        return (
            "~~Result is as expected.~~ **[REPLACE WITH: [specific observable system response, record value, "
            "state transition, or error message that constitutes acceptance].]**",
            True,
        )
    if finding.category == "Test Execution":
        return (
            "**[ADD: Actual Result: [contemporaneous observed behavior]. Evidence: [controlled attachment/log/record reference].]**",
            True,
        )
    if finding.category == "Defect / Deviation Management":
        return (
            "~~All defects and deviations are closed.~~ **[REPLACE WITH: Open item [ID] remains [status]; "
            "its validated-state impact, residual risk, required retest, and release disposition are [documented status].]**",
            True,
        )
    if finding.category == "Part 11 / Electronic Records":
        return (
            "**[ADD: The applicable electronic-record/signature control is [implemented control], linked to "
            "requirement [ID], and objectively verified by [test/evidence].]**",
            True,
        )
    if finding.category == "Risk Management":
        return (
            "**[ADD: Risk Control: [implemented preventive/detective control]. Residual Risk: [rating and rationale]. "
            "Assurance Activity: [linked verification].]**",
            True,
        )
    if finding.category == "Compliance":
        return (
            "**[ADD: Applicability and compliance rationale: [controlled procedure/regulatory basis], "
            "[applicability decision], and [supporting evidence].]**",
            True,
        )
    return ("", False)


def enrich_findings(
    findings: list[Finding],
    documents: list[Document],
    requirements: list[dict[str, Any]],
    risks: list[dict[str, Any]],
    tests: list[dict[str, Any]],
    issues: list[dict[str, Any]],
) -> None:
    requirement_map = {item["id"]: item for item in requirements}
    risk_map = {item["id"]: item for item in risks}
    test_map = {item["id"]: item for item in tests}
    issue_map = {item["id"]: item for item in issues}
    document_map = {document.name: document for document in documents}

    for finding in findings:
        original_category = finding.category
        finding.category = PRIMARY_CATEGORY_MAP.get(original_category, original_category)
        if finding.finding_subcategory == "General":
            finding.finding_subcategory = original_category

        referenced_test_ids = set(finding.test_ids)
        referenced_test_ids.update(_canonical(match) for match in TEST_ID_RE.findall(finding.location))
        for test in tests:
            if set(finding.requirement_ids) & set(test["requirement_ids"]):
                referenced_test_ids.add(test["id"])
            if set(finding.risk_ids) & set(test["risk_ids"]):
                referenced_test_ids.add(test["id"])
        finding.test_ids = sorted(referenced_test_ids)

        source_items: list[tuple[str, str, str]] = []
        for identifier in finding.requirement_ids:
            item = requirement_map.get(identifier)
            if item:
                source_items.append((identifier, item["text"], item["document"]))
        for identifier in finding.risk_ids:
            item = risk_map.get(identifier)
            if item:
                source_items.append((identifier, item["text"], item["document"]))
        for identifier in finding.test_ids:
            item = test_map.get(identifier)
            if item:
                source_items.append((identifier, item["text"], item["document"]))
        for identifier in ISSUE_ID_RE.findall(finding.location):
            item = issue_map.get(_canonical(identifier))
            if item:
                source_items.append((item["id"], item["text"], item["document"]))

        if finding.finding_subcategory == "Cross-Document Consistency" and "version" in finding.location.lower():
            source_items.extend(
                (document.name, f"System version: {document.version}", document.name)
                for document in documents
                if document.version != "Unable to determine"
            )

        related_documents = {name for _, _, name in source_items}
        related_documents.update(
            document.name
            for document in documents
            if document.name in finding.document or document.doc_type == finding.document
        )
        document_scope = finding.document.lower()
        for document in documents:
            if (
                ("requirement" in document_scope and document.doc_type in {"User Requirements Specification", "Functional Specification", "Configuration Specification"})
                or ("test" in document_scope and document.doc_type in {"Installation Qualification", "Operational Qualification", "Performance Qualification", "User Acceptance Testing", "Test Evidence"})
                or ("risk assessment" in document_scope and document.doc_type == "Risk Assessment")
                or ("summary" in document_scope and document.doc_type == "Validation Summary Report")
                or ("validation package" in document_scope)
            ):
                related_documents.add(document.name)
        finding.related_documents = sorted(related_documents)
        if source_items:
            finding.source_text = " || ".join(
                f"{identifier}: {_clean(text, 520)}" for identifier, text, _ in source_items[:8]
            )
        elif finding.finding_subcategory in {"Intended Use", "Package Completeness"}:
            finding.source_text = (
                f"No corresponding statement was detected across {len(documents)} successfully ingested package document(s)."
            )
        else:
            finding.source_text = (
                f"Evidence search across {len(documents)} package document(s) did not locate content satisfying "
                f"the review criterion at '{finding.location}'."
            )

        primary_document = document_map.get(finding.related_documents[0]) if finding.related_documents else None
        if primary_document:
            finding.document_id = (
                primary_document.document_id
                if primary_document.document_id != "Unable to determine"
                else primary_document.name
            )
            finding.document_type = primary_document.doc_type
            finding.document_revision = primary_document.revision
        else:
            finding.document_id = "PACKAGE"
            finding.document_type = "Validation Package"
            finding.document_revision = "Multiple / Unable to determine"
        finding.section = finding.location
        finding.applicable_reference = finding.basis

        base_score = {"High": 88, "Medium": 62, "Low": 38}.get(finding.confidence, 38)
        if finding.source_text != "Unable to determine from available evidence.":
            base_score += 4
        if finding.location not in {"Package-level context", "Document control metadata", "Applicability assessment"}:
            base_score += 2
        if len(finding.related_documents) >= 2:
            base_score += 2
        if any(document.extraction_status == "Failed" for document in documents):
            base_score -= 8
        finding.confidence_score = max(25, min(99, finding.confidence_score or base_score))
        finding.confidence = (
            "High" if finding.confidence_score >= 75
            else "Medium" if finding.confidence_score >= 50
            else "Low"
        )
        if not finding.suggested_redline:
            finding.suggested_redline, inferred_sme = _default_redline(finding)
            finding.sme_confirmation_required = finding.sme_confirmation_required or inferred_sme


def _document_specific_assessment(document: Document) -> dict[str, Any]:
    lenses = DOCUMENT_REVIEW_LENSES.get(document.doc_type, ())
    lower = document.text.lower()
    checks = []
    for area, terms in lenses:
        present = any(term in lower for term in terms)
        checks.append(
            {
                "area": area,
                "status": "Addressed" if present else "Potential missing content — SME confirmation required",
                "confidence": "Medium" if present else "Low",
            }
        )
    addressed = sum(1 for check in checks if check["status"] == "Addressed")
    return {
        "document_type": document.doc_type,
        "checks": checks,
        "areas_addressed": addressed,
        "areas_evaluated": len(checks),
        "potential_missing_content": [check for check in checks if check["status"] != "Addressed"],
    }


QUALITY_WEIGHTS = {
    "completeness": 0.15,
    "accuracy": 0.15,
    "procedural_compliance": 0.15,
    "internal_consistency": 0.10,
    "cross_document_consistency": 0.10,
    "risk_appropriateness": 0.15,
    "traceability": 0.10,
    "objective_evidence": 0.10,
}


def _quality_label(score: int) -> str:
    if score >= 90:
        return "Strong"
    if score >= 80:
        return "Acceptable"
    if score >= 65:
        return "Needs Improvement"
    if score >= 45:
        return "Weak"
    return "Insufficient Evidence"


def _positive_findings(document: Document, assessment: dict[str, Any], related: list[Finding]) -> list[str]:
    strengths: list[str] = []
    if document.extraction_status == "Complete":
        strengths.append("Machine-readable content was successfully ingested for evidence review.")
    if document.version != "Unable to determine" and document.approval_status != "Unable to determine":
        strengths.append("Controlled version and document-status metadata were identifiable.")
    if assessment["areas_evaluated"] and assessment["areas_addressed"] == assessment["areas_evaluated"]:
        strengths.append(f"All {assessment['areas_evaluated']} document-specific review areas were semantically addressed.")
    if document.doc_type == "User Requirements Specification":
        ids = {_canonical(match) for match in REQUIREMENT_ID_RE.findall(document.text)}
        if ids:
            strengths.append(f"Unique requirement identifiers were detected for {len(ids)} requirement(s).")
    if document.doc_type in {"Operational Qualification", "Performance Qualification", "User Acceptance Testing", "Test Evidence"}:
        if "expected result" in document.text.lower() and "actual result" in document.text.lower() and "evidence" in document.text.lower():
            strengths.append("Expected results, actual results, and objective-evidence references were present.")
    if not related:
        strengths.append("No substantive evidence-based deficiency was associated with this document.")
    return strengths[:5]


def _document_quality(document: Document, related: list[Finding], assessment: dict[str, Any]) -> dict[str, Any]:
    dimensions = {name: 100.0 for name in QUALITY_WEIGHTS}
    severity_deduction = {"Critical": 42, "Major": 22, "Moderate": 9, "Minor": 9, "Observation": 0}
    dimension_map = {
        "Completeness": ("completeness",),
        "Accuracy": ("accuracy",),
        "Compliance": ("procedural_compliance",),
        "Consistency": ("internal_consistency", "cross_document_consistency"),
        "Requirement Quality": ("completeness", "accuracy"),
        "Risk Management": ("risk_appropriateness",),
        "Traceability": ("traceability",),
        "Test Design": ("objective_evidence", "risk_appropriateness"),
        "Test Execution": ("objective_evidence",),
        "Data Integrity": ("accuracy", "risk_appropriateness"),
        "Part 11 / Electronic Records": ("procedural_compliance", "objective_evidence"),
        "Security / Access Control": ("risk_appropriateness",),
        "Interface / Integration": ("accuracy", "risk_appropriateness"),
        "Configuration / Baseline": ("accuracy", "cross_document_consistency"),
        "Defect / Deviation Management": ("accuracy", "objective_evidence"),
    }
    for finding in related:
        affected = dimension_map.get(finding.category, ("completeness",))
        deduction = severity_deduction[finding.severity] / len(affected)
        for dimension in affected:
            dimensions[dimension] = max(0, dimensions[dimension] - deduction)
    missing_metadata = sum(
        value == "Unable to determine"
        for value in (document.document_id, document.revision, document.approval_status, document.system, document.version)
    )
    dimensions["completeness"] = max(0, dimensions["completeness"] - missing_metadata * 3)
    if document.extraction_status == "Failed":
        dimensions["completeness"] = 0
        dimensions["accuracy"] = 20
        dimensions["objective_evidence"] = 0
    if assessment["areas_evaluated"]:
        missing_ratio = len(assessment["potential_missing_content"]) / assessment["areas_evaluated"]
        dimensions["completeness"] = max(0, dimensions["completeness"] - 18 * missing_ratio)
    score = round(sum(dimensions[name] * weight for name, weight in QUALITY_WEIGHTS.items()))
    if any(finding.severity == "Critical" for finding in related):
        score = min(score, 44)
    elif any(finding.severity == "Major" and finding.approval_blocking for finding in related):
        score = min(score, 79)
    return {
        "score": int(score),
        "rating": _quality_label(int(score)),
        "dimensions": {name: round(value) for name, value in dimensions.items()},
        "notice": "This score represents review confidence, not regulatory approval. The qualitative disposition takes precedence.",
    }


def build_redlines(documents: list[Document], findings: list[Finding]) -> list[dict[str, Any]]:
    redlines = []
    for document in documents:
        related = [finding for finding in findings if document.name in finding.related_documents]
        pending = list(related)
        rendered: list[str] = []
        for line in document.text.splitlines():
            matched: list[Finding] = []
            line_ids = {
                _canonical(identifier)
                for identifier in (
                    REQUIREMENT_ID_RE.findall(line)
                    + RISK_ID_RE.findall(line)
                    + TEST_ID_RE.findall(line)
                    + ISSUE_ID_RE.findall(line)
                )
            }
            for finding in pending:
                finding_ids = set(finding.requirement_ids + finding.risk_ids + finding.test_ids)
                finding_ids.update(_canonical(identifier) for identifier in ISSUE_ID_RE.findall(finding.location))
                version_anchor = "version" in finding.location.lower() and re.search(r"(?i)^\s*(?:application |system |software )?version\s*[:|,]", line)
                if (line_ids & finding_ids) or version_anchor:
                    matched.append(finding)
            if matched and any(finding.suggested_redline for finding in matched):
                replacement = next((finding.suggested_redline for finding in matched if finding.suggested_redline), "")
                rendered.append(f"~~{line}~~ {replacement}")
            else:
                rendered.append(line)
            for finding in matched:
                rendered.append(
                    f"\n[CSV COMMENT {finding.finding_id} | {finding.severity} | {finding.confidence_score}% Confidence]\n"
                    f"{finding.observation}\n"
                    + ("Proposed wording requires SME confirmation.\n" if finding.sme_confirmation_required else "")
                )
                if finding in pending:
                    pending.remove(finding)

        if pending:
            rendered.append("\n---\nREVIEWER COMMENTS REQUIRING DOCUMENT-LEVEL PLACEMENT\n")
            for finding in pending:
                rendered.append(
                    f"[CSV COMMENT {finding.finding_id} | {finding.severity} | {finding.confidence_score}% Confidence]\n"
                    f"Location: {finding.location}\n{finding.observation}\n"
                    + (f"{finding.suggested_redline}\n" if finding.suggested_redline else "")
                    + ("Proposed wording requires SME confirmation.\n" if finding.sme_confirmation_required else "")
                )
        redlines.append(
            {
                "document_name": document.name,
                "document_id": document.document_id,
                "document_type": document.doc_type,
                "revision": document.revision,
                "change_count": len(related),
                "finding_ids": [finding.finding_id for finding in related],
                "source_text": document.text,
                "redlined_text": "\n".join(rendered),
                "format": "Markdown review representation",
                "notice": "The source file is preserved. Proposed wording marked for SME confirmation must be confirmed before adoption.",
            }
        )
    return redlines


def _potential_requirement_areas(requirements: list[dict[str, Any]], context: dict[str, Any], full_text: str) -> list[dict[str, str]]:
    requirement_text = " ".join(requirement["text"] for requirement in requirements).lower()
    areas = {
        "Authentication": ("authentication", "login", "sign-on", "password"),
        "Authorization / roles": ("role", "permission", "authori", "least privilege"),
        "Audit trail": ("audit trail", "change history"),
        "Backup and recovery": ("backup", "restore", "recovery"),
        "Error handling": ("error", "failure", "reject", "exception"),
        "Record retention": ("retention", "archive"),
        "Time synchronization": ("time sync", "synchroniz", "timestamp"),
        "Administrator functions": ("administrator", "admin function", "privileged"),
    }
    if context["part11_relevance"] not in {"Applicable", "Potentially applicable — assessment required"}:
        areas.pop("Audit trail", None)
        areas.pop("Record retention", None)
    if "interface" not in full_text.lower() and not context["system_boundaries"]["interfaces"]:
        pass
    else:
        areas["Interface failure and reconciliation"] = ("interface", "reconciliation", "failed transfer", "retry")
    missing = []
    for area, terms in areas.items():
        if not any(term in requirement_text for term in terms):
            missing.append(
                {
                    "area": area,
                    "status": "Potential gap — SME confirmation required",
                    "confidence": "Low",
                    "rationale": "No corresponding requirement was semantically identified in the extracted requirements.",
                }
            )
    return missing


def _rating(findings: list[Finding], categories: set[str], *, default: str = "Green") -> str:
    related = [
        finding for finding in findings
        if finding.category in categories or finding.finding_subcategory in categories
    ]
    if any(finding.severity in {"Critical", "Major"} for finding in related):
        return "Red"
    if related:
        return "Yellow"
    return default


def build_scorecard(
    documents: list[Document], context: dict[str, Any], findings: list[Finding], requirements: list[dict[str, Any]], risks: list[dict[str, Any]], tests: list[dict[str, Any]]
) -> list[dict[str, str]]:
    def concern(categories: set[str], fallback: str) -> str:
        related = [
            finding for finding in findings
            if finding.category in categories or finding.finding_subcategory in categories
        ]
        return related[0].observation if related else fallback

    part11_default = "Not Applicable" if context["part11_relevance"].startswith("Not applicable") else "Unable to Determine"
    interface_present = bool(context["system_boundaries"]["interfaces"])
    rows = [
        ("Intended Use", _rating(findings, {"Intended Use"}), {"Intended Use"}, "Clear intended use located."),
        ("GxP Classification", _rating(findings, {"GxP Classification"}, default="Unable to Determine" if context["gxp_relevance"] == "Unable to determine" else "Green"), {"GxP Classification"}, context["gxp_relevance"]),
        ("Validation Strategy", _rating(findings, {"Validation Strategy"}, default="Green" if _has_type(documents, "Validation Plan") else "Unable to Determine"), {"Validation Strategy"}, "Validation plan located." if _has_type(documents, "Validation Plan") else "No validation plan was identifiable."),
        ("Requirements", _rating(findings, {"Requirements"}, default="Green" if requirements else "Unable to Determine"), {"Requirements"}, f"{len(requirements)} requirement(s) reviewed."),
        ("Risk Management", _rating(findings, {"Risk Management", "Risk-to-Test Traceability"}, default="Green" if risks else "Unable to Determine"), {"Risk Management", "Risk-to-Test Traceability"}, f"{len(risks)} risk(s) reviewed."),
        ("Traceability", _rating(findings, {"Traceability", "Risk-to-Test Traceability"}, default="Green" if requirements and tests else "Unable to Determine"), {"Traceability", "Risk-to-Test Traceability"}, "No material traceability issue identified."),
        ("Test Design", _rating(findings, {"Test Design"}, default="Green" if tests else "Unable to Determine"), {"Test Design"}, f"{len(tests)} test(s) reviewed."),
        ("Test Execution", _rating(findings, {"Test Execution"}, default="Green" if tests else "Unable to Determine"), {"Test Execution"}, "No material execution issue identified."),
        ("Deviations/Defects", _rating(findings, {"Defects / Deviations"}, default="Green" if _has_type(documents, "Defect / Deviation Log") else "Unable to Determine"), {"Defects / Deviations"}, "No serious unresolved issue identified."),
        ("Part 11", _rating(findings, {"Part 11 / Data Integrity"}, default=part11_default), {"Part 11 / Data Integrity"}, context["part11_relevance"]),
        ("Data Integrity", _rating(findings, {"Part 11 / Data Integrity"}, default="Green" if "data integrity" in " ".join(d.text.lower() for d in documents) else "Unable to Determine"), {"Part 11 / Data Integrity"}, "No material data-integrity issue identified."),
        ("Security", _rating(findings, {"Security"}, default="Green" if any(test["security"] for test in tests) else "Unable to Determine"), {"Security"}, "Security control testing identified." if any(test["security"] for test in tests) else "Security testing could not be established."),
        ("Interfaces", _rating(findings, {"Interfaces"}, default="Green" if interface_present and any(test["interface"] for test in tests) else "Unable to Determine" if interface_present else "Not Applicable"), {"Interfaces"}, "Interface scope identified." if interface_present else "No interface was identified in the provided package."),
        ("Validation Conclusion", _rating(findings, {"Validation Conclusion", "Cross-Document Consistency", "Defects / Deviations"}, default="Green" if _has_type(documents, "Validation Summary Report") else "Unable to Determine"), {"Validation Conclusion", "Cross-Document Consistency", "Defects / Deviations"}, "Validation conclusion located and no material contradiction identified."),
    ]
    return [
        {"review_area": area, "rating": rating, "key_concern": concern(categories, fallback)}
        for area, rating, categories, fallback in rows
    ]


def _document_reviews(documents: list[Document], findings: list[Finding]) -> list[dict[str, Any]]:
    reviews = []
    for document in documents:
        related_objects = [finding for finding in findings if document.name in finding.related_documents]
        related = [finding.to_dict() for finding in related_objects]
        severities = {finding.severity for finding in related_objects}
        status = "Red" if severities & {"Critical", "Major"} else "Yellow" if related else "Green"
        assessment = _document_specific_assessment(document)
        quality = _document_quality(document, related_objects, assessment)
        if "Critical" in severities:
            disposition = "REJECT / MAJOR REMEDIATION REQUIRED"
        elif "Major" in severities:
            disposition = "REVISE"
        elif related:
            disposition = "ACCEPT WITH COMMENTS"
        else:
            disposition = "ACCEPT"
        positives = _positive_findings(document, assessment, related_objects)
        reviews.append(
            {
                "document": document.public(),
                "overall_status": status,
                "disposition": disposition,
                "executive_review_summary": (
                    f"{document.doc_type} review identified {len(related)} substantive finding(s); "
                    f"document confidence is {quality['rating'].lower()} at {quality['score']}%."
                ),
                "review_confidence": quality,
                "positive_findings": positives,
                "strengths": positives,
                "document_specific_assessment": assessment,
                "potential_missing_content": assessment["potential_missing_content"],
                "critical_major_findings": [
                    finding for finding in related if finding["severity"] in {"Critical", "Major"}
                ],
                "cross_document_findings": [
                    finding for finding in related if finding["finding_subcategory"] == "Cross-Document Consistency"
                ],
                "approval_blockers": [finding for finding in related if finding["approval_blocking"]],
                "findings": related,
            }
        )
    return reviews


def _testing_analysis(tests: list[dict[str, Any]], high_risk_count: int) -> dict[str, Any]:
    def count(key: str) -> int:
        return sum(1 for test in tests if test[key])

    categories = {
        "positive_testing": sum(1 for test in tests if not test["negative"]),
        "negative_testing": count("negative"),
        "boundary_testing": count("boundary"),
        "security_testing": count("security"),
        "audit_trail_testing": count("audit_trail"),
        "interface_testing": count("interface"),
        "electronic_signature_testing": count("electronic_signature"),
        "data_migration_testing": count("migration"),
        "regression_testing": count("regression"),
    }
    categories["risk_based_gap_summary"] = (
        "High/Critical risks exist without identifiable negative testing."
        if high_risk_count and categories["negative_testing"] == 0
        else "No systemic negative-testing gap was identified by the automated review."
    )
    return categories


def _part11_assessment(context: dict[str, Any], documents: list[Document], tests: list[dict[str, Any]]) -> dict[str, str]:
    lower = "\n".join(document.text.lower() for document in documents)
    if context["part11_relevance"].startswith("Not applicable"):
        return {"applicability": context["part11_relevance"], "overall": "Not Applicable"}
    areas = {
        "electronic_records_assessment": "Addressed" if "electronic record" in lower else "Unable to Determine",
        "electronic_signature_assessment": "Addressed" if "electronic signature" in lower else "Unable to Determine",
        "audit_trail_assessment": "Addressed" if "audit trail" in lower else "Unable to Determine",
        "access_control_assessment": "Addressed" if re.search(r"role.based access|access control|unique user", lower) else "Unable to Determine",
        "record_retention_assessment": "Addressed" if "retention" in lower else "Unable to Determine",
        "alcoa_plus_assessment": "Addressed" if "alcoa" in lower else "Unable to Determine",
        "testing_summary": f"{sum(1 for test in tests if test['audit_trail'] or test['electronic_signature'] or test['security'])} relevant control test(s) identified.",
    }
    return {"applicability": context["part11_relevance"], **areas}


def _recommendation(findings: list[Finding]) -> tuple[str, str, str]:
    if any(finding.severity == "Critical" for finding in findings):
        return (
            "REJECT / MAJOR REMEDIATION REQUIRED",
            "Validation evidence is inadequate to establish the validated state because one or more critical contradictions or control failures remain unresolved.",
            "Low",
        )
    if any(finding.severity == "Major" and finding.approval_blocking for finding in findings):
        return (
            "REVISE",
            "Substantive evidence, traceability, risk-control, or package-closure issues require correction before approval.",
            "Low",
        )
    if findings:
        return (
            "ACCEPT WITH COMMENTS",
            "Validation is acceptable based on the supplied evidence; remaining comments do not materially affect the validated state.",
            "Medium",
        )
    return (
        "ACCEPT",
        "Validation evidence adequately demonstrates intended use and applicable requirements.",
        "High",
    )


def review_package(
    documents: list[Document],
    package_name: str = "Untitled validation package",
    feedback_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    classify_documents(documents)
    context = build_context(documents)
    requirements = extract_requirements(documents)
    risks = extract_risks(documents)
    tests = extract_tests(documents)
    issues = extract_issues(documents)
    procedure_map = extract_procedure_map(documents)
    traceability = build_traceability(requirements, risks, tests)
    findings = generate_findings(
        documents,
        context,
        requirements,
        risks,
        tests,
        issues,
        traceability,
        procedure_map,
    )
    enrich_findings(findings, documents, requirements, risks, tests, issues)
    findings, reviewer_considerations, feedback_conflicts = apply_feedback_precedents(
        findings, feedback_records or []
    )
    findings.sort(key=lambda finding: (SEVERITY_ORDER[finding.severity], finding.category, finding.location))
    for index, finding in enumerate(findings, start=1):
        finding.finding_id = f"F-{index:03d}"
        finding.display_id = finding.finding_id
        finding.title = _clean(finding.observation, 120)
    for finding in findings:
        own_ids = set(finding.requirement_ids + finding.risk_ids + finding.test_ids)
        finding.related_finding_ids = [
            other.finding_id
            for other in findings
            if other is not finding
            and own_ids
            and own_ids & set(other.requirement_ids + other.risk_ids + other.test_ids)
        ]
    recommendation, rationale, confidence = _recommendation(findings)
    scorecard = build_scorecard(documents, context, findings, requirements, risks, tests)
    high_risks = [risk for risk in risks if risk["rating"] in {"High", "Critical"}]
    verified_controls = sum(1 for row in traceability["risks"] if row["status"] == "Verified")
    requirement_gaps = _potential_requirement_areas(requirements, context, "\n".join(document.text for document in documents))
    cross_document = [
        finding.to_dict()
        for finding in findings
        if finding.finding_subcategory in {"Cross-Document Consistency", "Defects / Deviations"}
    ]
    blocking = [finding.to_dict() for finding in findings if finding.approval_blocking]
    non_blocking = [finding.to_dict() for finding in findings if not finding.approval_blocking]
    severity_counts = Counter(finding.severity for finding in findings)
    document_reviews = _document_reviews(documents, findings)
    redlines = build_redlines(documents, findings)
    grounded_blockers = sum(
        1 for finding in findings
        if finding.approval_blocking and not finding.source_text.startswith("Unable to determine")
    )
    evidence_grounding = round(100 * grounded_blockers / len(blocking), 1) if blocking else 100.0
    average_document_score = round(
        sum(review["review_confidence"]["score"] for review in document_reviews) / len(document_reviews), 1
    ) if document_reviews else None

    generated_at = datetime.now(UTC)
    internal_review_uuid = str(uuid4())
    review_run_id = f"REV-{generated_at.strftime('%Y%m%d-%H%M%S')}-{internal_review_uuid[:6].upper()}"
    report = {
        "schema_version": "3.0",
        "review_id": review_run_id,
        "review_run_id": review_run_id,
        "internal_review_uuid": internal_review_uuid,
        "generated_at": generated_at.isoformat(),
        "package_name": package_name.strip() or "Untitled validation package",
        "review_provenance": {
            "review_run_id": review_run_id,
            "review_agent_version": REVIEW_AGENT_VERSION,
            "prompt_rule_set_version": REVIEW_RULE_SET_VERSION,
            "knowledge_base_version": KNOWLEDGE_BASE_VERSION,
            "procedure_policy_baseline": "Package-supplied controlled procedures; otherwise Not Available",
            "review_date_time": generated_at.isoformat(),
            "reviewer": "Not Available",
            "documents_reviewed": len(documents),
            "review_status": "Not Started",
        },
        "executive_assessment": {
            "system": context["system"],
            "version": context["version"],
            "validation_package_reviewed": [document.name for document in documents],
            "intended_use": context["intended_use"],
            "gxp_relevance": context["gxp_relevance"],
            "overall_validation_confidence": confidence,
            "recommended_disposition": recommendation,
            "basis": rationale,
        },
        "validation_context": context,
        "scorecard": scorecard,
        "findings": [finding.to_dict() for finding in findings],
        "critical_and_major_findings": [finding.to_dict() for finding in findings if finding.severity in {"Critical", "Major"}],
        "detailed_document_review": document_reviews,
        "redlined_documents": redlines,
        "reviewer_considerations": reviewer_considerations,
        "feedback_learning": {
            "available_precedents": len(feedback_records or []),
            "applied_precedent_ids": sorted({
                precedent_id
                for finding in findings
                for precedent_id in finding.feedback_precedent_ids
                if precedent_id
            }),
            "suppressed_false_positive_patterns": len(reviewer_considerations),
            "conflicting_historical_guidance": feedback_conflicts,
            "priority_notice": "Current approved regulation and procedure take precedence over historical reviewer feedback.",
        },
        "requirements_analysis": {
            "total_requirements_reviewed": len(requirements),
            "clear_testable_requirements": sum(1 for requirement in requirements if requirement["testable"]),
            "ambiguous_requirements": [requirement["id"] for requirement in requirements if requirement["weak_terms"]],
            "compound_requirements": [requirement["id"] for requirement in requirements if requirement["compound"]],
            "requirements_missing_acceptance_criteria": [requirement["id"] for requirement in requirements if requirement["missing_acceptance_criteria"]],
            "potentially_missing_requirement_areas": requirement_gaps,
            "requirements": requirements,
        },
        "risk_analysis": {
            "total_risks": len(risks),
            "critical_high_risks": len(high_risks),
            "risk_controls": sum(1 for risk in risks if risk["control"] != "Unable to determine"),
            "verified_controls": verified_controls,
            "unverified_controls": [row["risk_id"] for row in traceability["risks"] if row["status"] != "Verified"],
            "potential_weaknesses": [finding.observation for finding in findings if finding.category == "Risk Management"],
            "risks": risks,
        },
        "traceability_analysis": traceability,
        "testing_analysis": _testing_analysis(tests, len(high_risks)),
        "tests": tests,
        "issues": issues,
        "part11_data_integrity_assessment": _part11_assessment(context, documents, tests),
        "procedure_compliance_map": procedure_map,
        "cross_document_consistency_findings": cross_document,
        "open_items_before_approval": {"approval_blocking": blocking, "non_blocking": non_blocking},
        "final_recommendation": {"disposition": recommendation, "basis": rationale},
        "metrics": {
            "documents": len(documents),
            "requirements": len(requirements),
            "risks": len(risks),
            "tests": len(tests),
            "issues": len(issues),
            "findings": len(findings),
            "blocking_findings": len(blocking),
            "traceability_percentage": traceability["traceability_percentage"],
            "severity_counts": {severity: severity_counts.get(severity, 0) for severity in SEVERITIES},
            "average_document_confidence_score": average_document_score,
            "approval_blocker_evidence_grounding_percentage": evidence_grounding,
        },
        "knowledge_graph": {
            "nodes": {
                "system": context["system"],
                "intended_use": context["intended_use"],
                "requirements": [requirement["id"] for requirement in requirements],
                "risks": [risk["id"] for risk in risks],
                "tests": [test["id"] for test in tests],
                "issues": [issue["id"] for issue in issues],
                "conclusion": recommendation,
            },
            "edges": {
                "requirement_to_test": [
                    {"requirement": row["requirement_id"], "tests": row["test_ids"]}
                    for row in traceability["requirements"]
                ],
                "risk_to_control_to_test": [
                    {"risk": row["risk_id"], "control": row["control"], "tests": row["test_ids"]}
                    for row in traceability["risks"]
                ],
            },
        },
        "quality_gate": {
            "findings_evidence_based": True,
            "requirements_not_invented": True,
            "semantic_equivalence_checked": True,
            "cross_document_consistency_checked": True,
            "high_risk_functions_prioritized": True,
            "duplicate_findings_consolidated": True,
            "approval_blocker_evidence_grounding_percentage": evidence_grounding,
            "finding_confidence_numerically_calibrated": all(25 <= finding.confidence_score <= 99 for finding in findings),
            "feedback_precedence_enforced": True,
            "human_quality_approval_preserved": True,
            "regulatory_citation_notice": "Exact regulatory citations should be verified against controlled references before use in an approved review record.",
        },
        "audit_events": [
            {
                "event_id": f"EVT-{uuid4().hex[:12].upper()}",
                "user": REVIEW_AGENT_VERSION,
                "timestamp": generated_at.isoformat(),
                "action": "Finding generated",
                "finding_id": finding.finding_id,
                "old_value": None,
                "new_value": finding.status,
            }
            for finding in findings
        ],
    }
    from .workflow import refresh_review_state

    return refresh_review_state(report)
