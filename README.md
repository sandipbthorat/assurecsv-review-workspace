# CSVQualReviewer

CSVQualReviewer is a local, risk-based review and redlines workspace for computerized-system validation packages. It evaluates deliverables individually and as one evidence system, then turns AI-identified findings into a structured human decision record.

The current implementation is a deterministic review engine. It uses explicit stages for classification, validation context, document-specific review, requirements, risk, tests, issues, procedure mapping, traceability, consistency, reviewer precedent, finding consolidation, redlining, and final disposition. It does **not** send documents to a cloud service or reduce the package to one generic LLM prompt.

## Enterprise foundation

CSVQualReviewer includes human-in-the-loop decision controls, immutable extracted source content, atomic review persistence, reviewer decision history, audit-relevant events, traceability exports, restrictive browser security headers, and per-request correlation IDs. See [Enterprise Readiness](ENTERPRISE_READINESS.md) for the production architecture, security boundary, validation expectations, and deployment checklist.

## Run locally with Streamlit

Python 3.11 or later is supported. Create an isolated environment, install the pinned deployment dependencies, and start the Streamlit workspace:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/streamlit run streamlit_app.py
```

Open [http://127.0.0.1:8501](http://127.0.0.1:8501). Use **Use realistic sample package** for an immediate guided example.

The original dependency-free local server remains available for offline use:

```bash
python3 app.py
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). Use **Use sample package** for an immediate guided example.

To use a different port:

```bash
python3 app.py 9000
```

The dependency-free server also accepts `CSVQUALREVIEWER_HOST` and `CSVQUALREVIEWER_PORT`. The secure default binds only to `127.0.0.1`; expose it externally only behind organization-managed TLS, SSO, authorization, and network controls.

## Supported files

- PDF
- DOCX
- XLSX/XLSM
- CSV/TSV
- TXT/Markdown
- JSON/XML/HTML/YAML

DOCX and XLSX text extraction use the Python standard library. PDF extraction first uses `pypdf` when available and otherwise uses a limited built-in fallback. For broad PDF font/encoding support, install the optional dependency in an isolated environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install pypdf
.venv/bin/python app.py
```

Scanned PDFs still require OCR before review. The document inventory clearly identifies failed or partial extraction so missing evidence is not silently treated as absent validation content.

## Review outputs

The service returns and locally persists a stable v3 review record containing:

- executive validation assessment and exact disposition;
- validation context and system boundary;
- Green/Yellow/Red scorecard;
- findings with stable IDs, controlled Critical/Major/Minor/Observation severity, category, status, numeric AI confidence, evidence, review basis, risk/impact, and original/proposed wording;
- numerical finding confidence scores, source excerpts, suggested redlines, SME flags, and related test/finding IDs;
- requirements, risks, tests, defects/deviations, and procedure maps;
- forward, backward, and risk-to-test traceability;
- semantic candidate links that require reviewer confirmation;
- Part 11/data-integrity assessment;
- cross-document contradictions and approval open items;
- reviewer dispositions, comments, modified recommendations, timestamps, and decision history;
- review provenance, calculated package readiness, completion blockers, and audit-relevant events;
- final quality-gate declarations.

Each document also receives eight weighted review-confidence dimensions: completeness, accuracy, procedural compliance, internal consistency, cross-document consistency, risk appropriateness, traceability, and objective evidence. The qualitative decision always takes precedence: Critical findings cap the document score below an acceptable disposition.

The workspace provides Executive Summary, Findings, Documents, Traceability, Redlines, and Review Decisions views. Reviewer decisions support Accept, Reject, Modify, Defer, Needs SME Review, and Resolve. Word-level redlines use a whitespace-preserving standard-library diff while immutable extracted source text remains separately available.

Exports are deliberately separated into the review report, findings CSV, selected redlined document, reviewer decision log, traceability report, and complete JSON record. Rejected recommendations are excluded from the final reviewed-document change set; modified findings use reviewer-authored wording.

Review runs and decisions are stored atomically under `data/reviews/` and survive page refresh and tab navigation. The latest review is restored automatically. Reviewer feedback precedents remain stored separately in `data/reviewer_feedback.json`.

## Controlled reviewer feedback

Accepted, rejected, and modified decisions also feed the existing controlled precedent store in `data/reviewer_feedback.json`, which is intentionally ignored by Git.

On later reviews, substantially similar records are retrieved by document type, category, section context, and semantic similarity. Five consistent false-positive/rejection precedents may suppress a repeated **non-regulatory** pattern into reviewer considerations. Conflicting precedents are surfaced for Quality escalation. Current regulations, controlled procedures, and templates always take priority over reviewer history.

## Deploy on Streamlit Community Cloud

This repository is deployment-ready: `streamlit_app.py`, `requirements.txt`, and `.streamlit/config.toml` are all at the repository root. In Streamlit Community Cloud, select this repository, the `main` branch, and `streamlit_app.py` as the entry point.

The cloud workspace isolates decisions to the active Streamlit session. Reviewers should download the complete JSON decision record before ending a session. A regulated, multi-reviewer production deployment should connect the decision store to an organization-controlled, access-controlled, validated persistence layer.

## Test

```bash
.venv/bin/python -m unittest discover -s tests -v
node tests/test_frontend.js
```

## Important use note

This application is decision support for a qualified independent reviewer. Automated classifications, low-confidence procedure matches, applicability conclusions, and regulatory citations must be confirmed against controlled procedures and references before inclusion in an approved validation record. Deploying the application inside a regulated quality process also requires the organization to establish its own intended use, controls, change management, access, record retention, and assurance evidence for this tool.
