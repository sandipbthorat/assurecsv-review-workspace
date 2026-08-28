"""CSVQualReviewer Streamlit Community Cloud entry point."""

from __future__ import annotations

import base64
import csv
from datetime import UTC, datetime
import html
import io
import json
from pathlib import Path
import tempfile
from typing import Any
from uuid import uuid4

import pandas as pd
import streamlit as st

from csv_reviewer import review_package
from csv_reviewer.ingest import parse_request_files
from csv_reviewer.models import FINDING_STATUSES, SEVERITIES, SEVERITY_ORDER
from csv_reviewer.review_store import ReviewCompletionError, ReviewStore
from csv_reviewer.workflow import refresh_review_state


ROOT = Path(__file__).resolve().parent
SAMPLE_ROOT = ROOT / "sample_package"
PAGES = (
    "Executive Summary",
    "Findings",
    "Documents",
    "Traceability",
    "Redlines",
    "Review Decisions",
)
DECISION_OPTIONS = (
    "Select a disposition",
    "Accepted",
    "Rejected",
    "Modified",
    "Deferred",
    "Needs SME Review",
    "Resolved",
)


st.set_page_config(
    page_title="CSVQualReviewer — AI Document Review",
    page_icon="◉",
    layout="wide",
    initial_sidebar_state="expanded",
)


APP_CSS = """
<style>
  :root {
    --ink: #17231e;
    --muted: #617169;
    --line: #d8e0dc;
    --green: #247354;
    --green-dark: #153b2e;
    --soft: #edf2ef;
  }
  [data-testid="stAppViewContainer"] { background: #f5f7f5; color: var(--ink); }
  [data-testid="stSidebar"] { background: var(--green-dark); }
  [data-testid="stSidebar"] * { color: #eef7f2; }
  [data-testid="stSidebar"] .stRadio label { border-radius: 8px; padding: 0.2rem 0.35rem; }
  [data-testid="stSidebar"] hr { border-color: rgba(255,255,255,.14); }
  [data-testid="stHeader"] { background: rgba(245,247,245,.86); }
  .block-container { max-width: 1500px; padding-top: 2rem; padding-bottom: 4rem; }
  h1, h2, h3 { letter-spacing: -0.025em; }
  h1 { font-size: clamp(2rem, 4vw, 3.3rem) !important; }
  .brand { display:flex; gap:.65rem; align-items:center; padding:.25rem 0 1rem; }
  .brand-mark { display:grid; place-items:center; width:2.15rem; height:2.15rem; border:1px solid rgba(255,255,255,.45); border-radius:.65rem; font-family:Georgia,serif; font-weight:800; }
  .brand strong { font-size:1.2rem; }
  .brand b { color:#86d8b1; }
  .eyebrow { color:var(--green); font-size:.7rem; font-weight:800; letter-spacing:.12em; text-transform:uppercase; margin-bottom:.25rem; }
  .hero-copy { color:var(--muted); max-width:860px; font-size:1.02rem; }
  .context-header { display:flex; gap:1rem; align-items:flex-start; justify-content:space-between; margin-bottom:1rem; }
  .context-header h1 { font-size:2rem !important; margin:.1rem 0; }
  .run-line { color:var(--muted); font-size:.78rem; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
  .status-badge,.severity-badge,.category-badge,.confidence-badge { display:inline-flex; width:fit-content; align-items:center; padding:.27rem .52rem; border-radius:999px; font-size:.68rem; font-weight:850; letter-spacing:.045em; white-space:nowrap; }
  .status-badge { color:#4e5b55; background:#e8eeea; }
  .status-badge.accepted,.status-badge.resolved,.status-badge.ready-for-approval,.status-badge.review-completed { color:#17613f; background:#dcf2e5; }
  .status-badge.rejected { color:#842d2d; background:#fbe8e6; }
  .status-badge.modified { color:#285f8f; background:#eaf3fb; }
  .status-badge.deferred { color:#7d5313; background:#fbf0d7; }
  .status-badge.needs-sme-review,.status-badge.reviewer-action-required { color:#5e477c; background:#f1ebf8; }
  .severity-badge { border:1px solid currentColor; text-transform:uppercase; }
  .severity-badge.critical { color:#8d2525; background:#fff1ef; }
  .severity-badge.major { color:#925714; background:#fff5dd; }
  .severity-badge.minor { color:#285e88; background:#edf6fd; }
  .severity-badge.observation { color:#59665f; background:#f0f3f1; }
  .category-badge { color:#496058; background:#edf2ef; }
  .confidence-badge { color:#285f8f; background:#eaf3fb; }
  .finding-head { display:flex; flex-wrap:wrap; align-items:center; gap:.5rem; margin-bottom:.7rem; }
  .finding-id { font:800 .76rem ui-monospace,SFMono-Regular,Menlo,monospace; }
  .finding-title { font:600 1.05rem Georgia,serif; margin:.15rem 0 .35rem; }
  .finding-meta { color:var(--muted); font-size:.76rem; }
  .detail-block { border-left:3px solid #9fb2a7; padding:.65rem .85rem; background:#f7f9f8; border-radius:.25rem; margin:.35rem 0 1rem; }
  .detail-block.risk { border-left-color:#c3913e; background:#fffaf1; }
  .detail-label { color:var(--muted); font-size:.64rem; font-weight:850; letter-spacing:.1em; text-transform:uppercase; margin-bottom:.35rem; }
  .source-text { white-space:pre-wrap; overflow-wrap:anywhere; font: .78rem/1.65 ui-monospace,SFMono-Regular,Menlo,monospace; }
  .redline { white-space:pre-wrap; overflow-wrap:anywhere; font:.82rem/1.8 ui-monospace,SFMono-Regular,Menlo,monospace; padding:1rem; border:1px solid var(--line); border-radius:.55rem; background:white; }
  .redline del { color:#8e3030; background:#fee8e6; text-decoration-thickness:1.5px; }
  .redline ins { color:#17613f; background:#dff4e7; text-decoration:none; }
  .readiness { display:grid; grid-template-columns:minmax(170px,.35fr) 1fr; gap:1.2rem; align-items:center; border:1px solid #b9d0c4; border-radius:.7rem; background:linear-gradient(110deg,#eaf4ef,#fbfcfb); padding:1rem 1.2rem; margin:.4rem 0 1.2rem; }
  .readiness strong { display:block; font:600 1.35rem Georgia,serif; }
  .readiness ul { margin:.2rem 0; color:var(--muted); font-size:.8rem; }
  .notice { display:flex; gap:.7rem; padding:.85rem 1rem; border:1px solid #bcd0df; border-radius:.55rem; color:#32596f; background:#f2f8fc; margin:.6rem 0 1rem; font-size:.8rem; }
  .cloud-note { border:1px solid rgba(255,255,255,.14); background:rgba(255,255,255,.06); border-radius:.55rem; padding:.7rem; font-size:.68rem; line-height:1.5; color:rgba(239,248,243,.75) !important; }
  [data-testid="stMetric"] { background:#fff; border:1px solid var(--line); border-radius:.65rem; padding:.85rem 1rem; min-height:112px; }
  [data-testid="stMetricLabel"] { color:var(--muted); }
  [data-testid="stExpander"] { border-color:var(--line); background:#fff; border-radius:.65rem; }
  [data-testid="stVerticalBlockBorderWrapper"] { border-color:var(--line); background:#fff; border-radius:.7rem; }
  .stButton>button[kind="primary"], .stDownloadButton>button[kind="primary"] { background:var(--green-dark); border-color:var(--green-dark); }
  .stButton>button[kind="primary"]:hover, .stDownloadButton>button[kind="primary"]:hover { background:var(--green); border-color:var(--green); }
  @media(max-width:800px){ .readiness{grid-template-columns:1fr}.context-header{display:block}.block-container{padding-inline:1rem} }
</style>
"""

st.markdown(APP_CSS, unsafe_allow_html=True)


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def slug(value: Any) -> str:
    return "-".join("".join(char.lower() if char.isalnum() else " " for char in str(value)).split())


def fmt_time(value: str | None) -> str:
    if not value or value == "Not Available":
        return "Not Available"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().strftime("%b %d, %Y · %I:%M %p")
    except ValueError:
        return value


def finding_badges(finding: dict[str, Any]) -> str:
    score = finding.get("confidence_score")
    confidence = "Not Available" if score is None else f"AI Confidence {score}%"
    return (
        f'<span class="finding-id">{esc(finding.get("finding_id"))}</span>'
        f'<span class="severity-badge {slug(finding.get("severity"))}">{esc(finding.get("severity", "Observation")).upper()}</span>'
        f'<span class="category-badge">{esc(finding.get("category", "Not Classified"))}</span>'
        f'<span class="status-badge {slug(finding.get("status"))}">{esc(finding.get("status", "Open"))}</span>'
        f'<span class="confidence-badge" title="AI confidence is not reviewer approval.">{esc(confidence)}</span>'
    )


def session_store() -> ReviewStore:
    if "store_token" not in st.session_state:
        st.session_state.store_token = uuid4().hex
    directory = Path(tempfile.gettempdir()) / "csvqualreviewer-streamlit" / st.session_state.store_token
    return ReviewStore(directory)


def set_report(report: dict[str, Any]) -> None:
    refresh_review_state(report)
    session_store().create(report)
    st.session_state.report = report
    st.session_state.selected_finding = report.get("findings", [{}])[0].get("finding_id", "") if report.get("findings") else ""


def current_report() -> dict[str, Any] | None:
    report = st.session_state.get("report")
    if not report:
        return None
    try:
        report = session_store().load(report["review_id"])
        st.session_state.report = report
    except ValueError:
        refresh_review_state(report)
    return report


def sample_payload() -> list[dict[str, str]]:
    return [
        {"name": item.name, "content": item.read_text(encoding="utf-8"), "encoding": "text"}
        for item in sorted(SAMPLE_ROOT.iterdir())
        if item.is_file() and not item.name.startswith(".")
    ]


def uploaded_payload(files: list[Any]) -> list[dict[str, str]]:
    return [
        {
            "name": uploaded.name,
            "content": base64.b64encode(uploaded.getvalue()).decode("ascii"),
            "encoding": "base64",
        }
        for uploaded in files
    ]


def execute_review(package_name: str, files: list[dict[str, str]]) -> None:
    documents = parse_request_files({"files": files})
    report = review_package(documents, package_name, [])
    set_report(report)


def findings_csv(findings: list[dict[str, Any]]) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Finding ID", "Severity", "Category", "Document", "Section", "Finding",
            "Evidence", "Risk Impact", "AI Recommendation", "AI Confidence", "Status",
            "Reviewer", "Reviewer Comment", "Reviewer-Modified Recommendation", "Decision Date",
        ]
    )
    for finding in findings:
        writer.writerow(
            [
                finding.get("finding_id"), finding.get("severity"), finding.get("category"),
                finding.get("document"), finding.get("section"), finding.get("finding"),
                finding.get("evidence"), finding.get("risk_impact"), finding.get("proposed_text"),
                finding.get("confidence_score", "Not Available"), finding.get("status"),
                finding.get("reviewer"), finding.get("reviewer_comment"),
                finding.get("modified_recommendation"), finding.get("reviewed_at"),
            ]
        )
    return output.getvalue().encode("utf-8")


def decisions_csv(report: dict[str, Any]) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Finding ID", "Severity", "Document", "AI Recommendation", "Reviewer Decision",
            "Reviewer Comment", "Reviewer", "Decision Date", "Modified Recommendation",
            "Rejection Reason", "Modification Reason",
        ]
    )
    for finding in report["findings"]:
        if finding["status"] == "Open":
            continue
        writer.writerow(
            [
                finding["finding_id"], finding["severity"], finding["document"],
                finding["proposed_text"], finding["status"], finding.get("reviewer_comment"),
                finding.get("reviewer"), finding.get("reviewed_at"),
                finding.get("modified_recommendation"), finding.get("rejection_reason"),
                finding.get("modification_reason"),
            ]
        )
    return output.getvalue().encode("utf-8")


def traceability_csv(report: dict[str, Any]) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["Finding", "Severity", "Document", "Section", "Review Basis", "Reference Status", "Proposed Change", "Reviewer Decision"]
    )
    for finding in report["findings"]:
        basis = (finding.get("review_basis") or [{}])[0]
        writer.writerow(
            [
                finding["finding_id"], finding["severity"], finding["document"], finding["section"],
                basis.get("source_name", "Not Available"), basis.get("verification_status", "Needs Verification"),
                finding["proposed_text"], finding["status"],
            ]
        )
    return output.getvalue().encode("utf-8")


def report_html(report: dict[str, Any]) -> bytes:
    metrics = report["metrics"]
    provenance = report.get("review_provenance", {})
    finding_blocks = []
    for finding in report["findings"]:
        finding_blocks.append(
            f"""
            <article>
              <p class="label">{esc(finding['finding_id'])} · {esc(finding['severity'])} · {esc(finding['category'])}</p>
              <h3>{esc(finding['title'])}</h3>
              <p><strong>Document / Section:</strong> {esc(finding['document'])} / {esc(finding['section'])}</p>
              <p><strong>Finding:</strong> {esc(finding['finding'])}</p>
              <p><strong>Evidence:</strong> {esc(finding['evidence'])}</p>
              <p><strong>Risk / Impact:</strong> {esc(finding['risk_impact'])}</p>
              <div class="ai"><span class="label">AI GENERATED CONTENT</span><p>{esc(finding['proposed_text'])}</p><p>AI Confidence: {esc(finding.get('confidence_score', 'Not Available'))}%</p></div>
              <div class="human"><span class="label">REVIEWER DECISION</span><p><strong>{esc(finding['status'])}</strong> by {esc(finding.get('reviewer') or 'Not Available')}</p><p>{esc(finding.get('reviewer_comment') or 'No comment recorded')}</p>{f'<p><strong>Reviewer wording:</strong> {esc(finding.get("modified_recommendation"))}</p>' if finding.get('modified_recommendation') else ''}</div>
            </article>
            """
        )
    provenance_rows = "".join(
        f"<tr><th>{esc(key.replace('_', ' ').title())}</th><td>{esc(value)}</td></tr>"
        for key, value in provenance.items()
    )
    document_rows = "".join(
        f"<li>{esc(document['document_name'])} — {document['finding_count']} findings; highest unresolved: {esc(document['highest_unresolved_severity'])}</li>"
        for document in report.get("document_summaries", [])
    )
    content = f"""<!doctype html><html><head><meta charset="utf-8"><title>{esc(report['package_name'])} Review Report</title>
    <style>body{{font:14px/1.55 Arial,sans-serif;color:#17231e;max-width:1050px;margin:40px auto;padding:0 24px}}h1,h2,h3{{font-family:Georgia,serif}}table{{width:100%;border-collapse:collapse}}th,td{{border:1px solid #ccd5d0;padding:8px;text-align:left}}article{{border:1px solid #ccd5d0;padding:18px;margin:18px 0;break-inside:avoid}}.label{{font-size:11px;font-weight:bold;color:#52645b;letter-spacing:.08em}}.ai{{background:#f3f7f5;padding:12px}}.human{{background:#eef5ff;padding:12px}}</style></head><body>
    <p class="label">CSVQUALREVIEWER CONTROLLED REVIEW REPORT</p><h1>{esc(report['package_name'])}</h1>
    <p><strong>Review Run:</strong> {esc(report['review_id'])}<br><strong>Status:</strong> {esc(report['review_workflow']['status'])}<br><strong>Package Readiness:</strong> {esc(report['review_workflow']['package_readiness'])}</p>
    <h2>Review provenance</h2><table>{provenance_rows}</table><h2>Documents reviewed</h2><ul>{document_rows}</ul>
    <h2>Executive summary</h2><p>{esc(report.get('executive_assessment', {}).get('basis', 'Not Available'))}</p>
    <p>Critical: {metrics['severity_counts']['Critical']} · Major: {metrics['severity_counts']['Major']} · Minor: {metrics['severity_counts']['Minor']} · Observation: {metrics['severity_counts']['Observation']}</p>
    <h2>Detailed findings and decisions</h2>{''.join(finding_blocks)}</body></html>"""
    return content.encode("utf-8")


def accepted_change(finding: dict[str, Any]) -> str | None:
    if finding["status"] in {"Rejected", "Open", "Deferred", "Needs SME Review"}:
        return None
    if finding["status"] == "Modified":
        return finding.get("modified_recommendation") or None
    return finding.get("modified_recommendation") or finding.get("proposed_text")


def unified_redline(finding: dict[str, Any]) -> str:
    segments = finding.get("redline_diff") or [
        {"type": "delete", "text": finding.get("original_text", "")},
        {"type": "insert", "text": finding.get("proposed_text", "")},
    ]
    output: list[str] = []
    for segment in segments:
        text = esc(segment.get("text", ""))
        if segment.get("type") == "delete":
            output.append(f"<del>{text}</del>")
        elif segment.get("type") == "insert":
            output.append(f"<ins>{text}</ins>")
        else:
            output.append(text)
    return f'<div class="redline">{"".join(output)}</div>'


def render_sidebar(report: dict[str, Any] | None) -> str:
    st.sidebar.markdown(
        '<div class="brand"><span class="brand-mark">D</span><strong>Docu<b>Mind</b></strong></div>',
        unsafe_allow_html=True,
    )
    if report:
        page = st.sidebar.radio("Review workspace", PAGES, key="workspace_page")
        st.sidebar.markdown("---")
        st.sidebar.caption("REVIEW RUN")
        st.sidebar.code(report["review_id"], language=None)
        st.sidebar.markdown(
            f'<span class="status-badge {slug(report["review_workflow"]["status"])}">{esc(report["review_workflow"]["status"])}</span>',
            unsafe_allow_html=True,
        )
        st.sidebar.markdown("---")
        with st.sidebar.expander("Export controlled outputs"):
            file_slug = slug(report["package_name"])
            st.download_button("Review report", report_html(report), f"{file_slug}-review-report.html", "text/html", width="stretch")
            st.download_button("Findings CSV", findings_csv(report["findings"]), f"{file_slug}-findings.csv", "text/csv", width="stretch")
            st.download_button("Decision log", decisions_csv(report), f"{file_slug}-decision-log.csv", "text/csv", width="stretch")
            st.download_button("Traceability", traceability_csv(report), f"{file_slug}-traceability.csv", "text/csv", width="stretch")
            st.download_button("Structured JSON", json.dumps(report, indent=2), f"{file_slug}-{report['review_id']}.json", "application/json", width="stretch")
        if st.sidebar.button("Start a new review", width="stretch"):
            st.session_state.pop("report", None)
            st.session_state.pop("selected_finding", None)
            st.rerun()
    else:
        page = "Upload"
        st.sidebar.markdown("**AI identifies · Human decides**")
    st.sidebar.markdown(
        '<div class="cloud-note"><strong>Streamlit Cloud workspace</strong><br>Reviewer actions are isolated to this active session. Download the structured record before closing. Configure a validated external datastore before regulated production use.</div>',
        unsafe_allow_html=True,
    )
    return page


def render_header(report: dict[str, Any], title: str, copy: str) -> None:
    st.markdown(
        f"""
        <div class="context-header">
          <div><div class="eyebrow">{esc(report['package_name'])}</div><h1>{esc(title)}</h1><div class="hero-copy">{esc(copy)}</div><div class="run-line">Review Run {esc(report['review_id'])}</div></div>
          <span class="status-badge {slug(report['review_workflow']['status'])}">{esc(report['review_workflow']['status'])}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_upload() -> None:
    st.markdown('<div class="eyebrow">AI-ASSISTED INDEPENDENT QUALITY REVIEW</div>', unsafe_allow_html=True)
    st.title("Turn a validation package into a defensible decision record.")
    st.markdown(
        '<p class="hero-copy">CSVQualReviewer connects findings to source evidence, review basis, risk, proposed wording, and explicit human disposition. Uploaded source documents are never silently overwritten.</p>',
        unsafe_allow_html=True,
    )
    st.markdown("")
    left, right = st.columns([1.45, .75], gap="large")
    with left:
        with st.container(border=True):
            package_name = st.text_input("Package name", placeholder="e.g., MARS 6.2 validation package", key="package_name")
            files = st.file_uploader(
                "Upload the complete validation package",
                type=["pdf", "docx", "xlsx", "xlsm", "csv", "tsv", "txt", "md", "json", "xml", "html", "htm", "yaml", "yml"],
                accept_multiple_files=True,
                help="One primary document plus up to 20 supporting documents. Files are processed by the deterministic review engine.",
            )
            start_col, sample_col = st.columns(2)
            if start_col.button("Start independent review", type="primary", width="stretch"):
                if not files:
                    st.error("Add at least one validation document before starting the review.")
                elif len(files) > 21:
                    st.error("Add one primary document and no more than 20 supporting documents.")
                else:
                    with st.spinner("Building the validation evidence graph…"):
                        try:
                            execute_review(package_name.strip() or "Untitled validation package", uploaded_payload(files))
                        except ValueError as exc:
                            st.error(str(exc))
                        else:
                            st.rerun()
            if sample_col.button("Use realistic sample package", width="stretch"):
                with st.spinner("Reviewing the sample validation package…"):
                    execute_review("NovaQMS 2.4 validation package", sample_payload())
                st.rerun()
    with right:
        with st.container(border=True):
            st.subheader("Controlled review flow")
            for number, title, copy in (
                ("01", "Establish package risk", "Classify documents, intended use, regulated scope, and evidence gaps."),
                ("02", "Trace every finding", "Connect evidence, review basis, risk, and recommended correction."),
                ("03", "Record human disposition", "Accept, modify, reject, defer, escalate, and resolve."),
                ("04", "Export controlled outputs", "Separate reports, findings, redlines, traceability, and decisions."),
            ):
                st.markdown(f"**{number} · {title}**  \n<small>{copy}</small>", unsafe_allow_html=True)
                st.divider()
            st.info("AI confidence is not reviewer approval. All recommendations require human evaluation.")


def render_summary(report: dict[str, Any]) -> None:
    render_header(report, "Executive Summary", "Package risk, reviewer workload, provenance, and readiness from one controlled data source.")
    workflow = report["review_workflow"]
    reasons = "".join(f"<li>{esc(reason)}</li>" for reason in workflow["readiness_reasons"])
    st.markdown(
        f'<div class="readiness"><div><div class="detail-label">Package readiness</div><strong>{esc(workflow["package_readiness"])}</strong></div><ul>{reasons}</ul></div>',
        unsafe_allow_html=True,
    )
    metrics = report["metrics"]
    cols = st.columns(6)
    cols[0].metric("Documents", metrics["documents"], help="Documents reviewed in this run")
    cols[1].metric("Total findings", metrics["findings"])
    cols[2].metric("Critical", metrics["severity_counts"]["Critical"])
    cols[3].metric("Major", metrics["severity_counts"]["Major"])
    cols[4].metric("Open actions", metrics["open_findings"])
    cols[5].metric("Needs SME", metrics["status_counts"]["Needs SME Review"])

    left, right = st.columns([1.55, .7], gap="large")
    with left:
        st.subheader("Significant unresolved findings")
        unresolved = [
            finding for finding in report["findings"]
            if finding["status"] not in {"Rejected", "Resolved"}
        ]
        unresolved.sort(key=lambda item: (SEVERITY_ORDER.get(item["severity"], 99), item["finding_id"]))
        if not unresolved:
            st.success("No unresolved findings remain.")
        for finding in unresolved[:6]:
            with st.container(border=True):
                st.markdown(f'<div class="finding-head">{finding_badges(finding)}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="finding-title">{esc(finding["title"])}</div>', unsafe_allow_html=True)
                st.caption(f"{finding['document']} · {finding['section']}")
                st.write(finding["finding"])
    with right:
        with st.container(border=True):
            st.subheader("Review completion")
            if workflow["can_complete"]:
                st.success("Completion checks passed. This records human review completion; it does not represent AI approval.")
            else:
                st.warning("The review cannot be completed until configured blockers are cleared.")
            reviewer = st.text_input("Completing reviewer", value=st.session_state.get("reviewer_name", ""), key="summary_reviewer")
            if st.button("Complete review", type="primary", disabled=not workflow["can_complete"] or workflow["status"] == "Review Completed", width="stretch"):
                try:
                    completed = session_store().complete(report["review_id"], {"reviewer": reviewer})
                except ReviewCompletionError as exc:
                    st.error(f"{exc} {'; '.join(exc.blockers)}")
                else:
                    st.session_state.report = completed
                    st.rerun()
        with st.container(border=True):
            st.subheader("Review provenance")
            provenance = report.get("review_provenance", {})
            rows = [
                ("Run ID", report["review_id"]),
                ("Agent", provenance.get("review_agent_version", "Not Available")),
                ("Rule set", provenance.get("prompt_rule_set_version", "Not Available")),
                ("Knowledge baseline", provenance.get("knowledge_base_version", "Not Available")),
                ("Procedure baseline", provenance.get("procedure_policy_baseline", "Not Available")),
                ("Review date", fmt_time(provenance.get("review_date_time"))),
                ("Latest reviewer", provenance.get("reviewer", "Not Available")),
            ]
            st.dataframe(pd.DataFrame(rows, columns=["Field", "Value"]), hide_index=True, width="stretch")


def filtered_findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    findings = report["findings"]
    query = st.text_input("Search findings", placeholder="ID, title, text, document, category, or section", key="finding_search").strip().lower()
    f1, f2, f3, f4, f5 = st.columns(5)
    severities = f1.multiselect("Severity", SEVERITIES, default=[], key="severity_filter")
    categories = f2.multiselect("Category", sorted({item["category"] for item in findings}), default=[], key="category_filter")
    documents = f3.multiselect("Document", sorted({reference["document_name"] for item in findings for reference in item.get("affected_documents", [])}), default=[], key="document_filter")
    statuses = f4.multiselect("Status", FINDING_STATUSES, default=[], key="status_filter")
    confidence = f5.multiselect("Confidence", ("High (≥90%)", "Medium (70–89%)", "Low (<70%)", "Not Available"), default=[], key="confidence_filter")
    sort_choice = st.selectbox("Sort findings", ("Unresolved risk", "Severity", "Document", "Finding ID", "Confidence", "Status", "Newest", "Oldest"), key="finding_sort")

    def confidence_label(finding: dict[str, Any]) -> str:
        score = finding.get("confidence_score")
        if score is None:
            return "Not Available"
        if score >= 90:
            return "High (≥90%)"
        if score >= 70:
            return "Medium (70–89%)"
        return "Low (<70%)"

    output = []
    for finding in findings:
        affected = [item.get("document_name") for item in finding.get("affected_documents", [])]
        searchable = " ".join(
            str(value) for value in (
                finding["finding_id"], finding["title"], finding["finding"], finding["document"],
                finding["category"], finding["section"], " ".join(affected),
            )
        ).lower()
        if severities and finding["severity"] not in severities:
            continue
        if categories and finding["category"] not in categories:
            continue
        if documents and not set(documents) & set(affected):
            continue
        if statuses and finding["status"] not in statuses:
            continue
        if confidence and confidence_label(finding) not in confidence:
            continue
        if query and query not in searchable:
            continue
        output.append(finding)

    if sort_choice == "Unresolved risk":
        output.sort(key=lambda item: (item["status"] in {"Rejected", "Resolved"}, SEVERITY_ORDER.get(item["severity"], 99), item["finding_id"]))
    elif sort_choice == "Severity":
        output.sort(key=lambda item: (SEVERITY_ORDER.get(item["severity"], 99), item["finding_id"]))
    elif sort_choice == "Document":
        output.sort(key=lambda item: (item["document"], item["finding_id"]))
    elif sort_choice == "Finding ID":
        output.sort(key=lambda item: item["finding_id"])
    elif sort_choice == "Confidence":
        output.sort(key=lambda item: (-(item.get("confidence_score") or -1), item["finding_id"]))
    elif sort_choice == "Status":
        output.sort(key=lambda item: (item["status"], item["finding_id"]))
    elif sort_choice == "Newest":
        output.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    else:
        output.sort(key=lambda item: item.get("created_at", ""))
    return output


def render_decision_editor(report: dict[str, Any], finding: dict[str, Any], prefix: str) -> None:
    st.markdown("### Human reviewer decision")
    st.caption("The source text and original AI recommendation remain immutable. Accepted and Resolved are distinct states.")
    current = finding["status"] if finding["status"] != "Open" else "Select a disposition"
    disposition = st.selectbox("Disposition", DECISION_OPTIONS, index=DECISION_OPTIONS.index(current), key=f"{prefix}_disposition")
    reviewer_default = finding.get("reviewer") if finding.get("reviewer") not in {"", "Not Available"} else st.session_state.get("reviewer_name", "")
    reviewer = st.text_input("Reviewer name / role", value=reviewer_default, key=f"{prefix}_reviewer")
    if reviewer:
        st.session_state.reviewer_name = reviewer
    comment = st.text_area(
        "Reviewer comment" + (" (required)" if disposition in {"Rejected", "Needs SME Review"} else ""),
        value=finding.get("reviewer_comment", ""),
        placeholder="Record the rationale, supporting evidence, context, or SME question.",
        key=f"{prefix}_comment",
    )
    modified = ""
    modification_reason = ""
    rejection_reason = ""
    duplicate_of = ""
    if disposition == "Modified":
        modified = st.text_area(
            "Reviewer-modified recommendation",
            value=finding.get("modified_recommendation") or finding["proposed_text"],
            height=160,
            key=f"{prefix}_modified",
        )
        modification_reason = st.selectbox(
            "Modification reason",
            ("", "Technical Accuracy", "Procedure Alignment", "Regulatory Interpretation", "Clarity", "Business Context", "Scope Correction", "Other"),
            key=f"{prefix}_mod_reason",
        )
    if disposition == "Rejected":
        rejection_reason = st.selectbox(
            "Structured rejection reason",
            ("", "Not Applicable", "Incorrect Interpretation", "Requirement Already Addressed", "Duplicate Finding", "Insufficient Evidence", "Incorrect Severity", "Incorrect Recommendation", "Other"),
            key=f"{prefix}_reject_reason",
        )
        duplicate_of = st.text_input("Duplicate of finding (optional)", placeholder="e.g., F-002", key=f"{prefix}_duplicate")
    if st.button("Save reviewer decision", type="primary", disabled=disposition == "Select a disposition", key=f"{prefix}_save"):
        try:
            updated, _ = session_store().decide(
                report["review_id"],
                finding["finding_id"],
                {
                    "disposition": disposition,
                    "reviewer": reviewer,
                    "reviewer_comment": comment,
                    "modified_recommendation": modified,
                    "rejection_reason": rejection_reason,
                    "modification_reason": modification_reason,
                    "duplicate_of": duplicate_of,
                    "original_ai_recommendation": finding["proposed_text"],
                    "expected_updated_at": finding.get("updated_at"),
                },
            )
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.session_state.report = updated
            st.success(f"{finding['finding_id']} saved as {disposition}.")
            st.rerun()


def render_finding_detail(report: dict[str, Any], finding: dict[str, Any], prefix: str = "finding") -> None:
    with st.container(border=True):
        st.markdown(f'<div class="finding-head">{finding_badges(finding)}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="finding-title">{esc(finding["title"])}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="finding-meta">{esc(finding["document"])} · {esc(finding["section"])}</div>', unsafe_allow_html=True)
        st.markdown("#### Finding")
        st.write(finding["finding"])
        st.markdown(f'<div class="detail-block"><div class="detail-label">Evidence</div><div class="source-text">{esc(finding["evidence"])}</div></div>', unsafe_allow_html=True)
        basis_items = finding.get("review_basis") or []
        st.markdown("#### Requirement / Review Basis")
        if basis_items:
            for basis in basis_items:
                source = basis.get("source_name") or "Not Available"
                with st.expander(f"{source} · {basis.get('verification_status', 'Needs Verification')}"):
                    st.write(f"**Source type:** {basis.get('source_type', 'Not Available')}")
                    st.write(f"**Section / Clause:** {basis.get('section', 'Not Available')} / {basis.get('clause', 'Not Available')}")
                    st.write(basis.get("text", "Not Available"))
        else:
            st.caption("Review basis is not available in this historical record.")
        st.markdown(f'<div class="detail-block risk"><div class="detail-label">Risk / Impact</div>{esc(finding["risk_impact"])}</div>', unsafe_allow_html=True)
        st.markdown("#### Recommended Change")
        st.info("AI-generated proposed wording. The source remains unchanged until human acceptance and implementation.")
        original_tab, proposed_tab, redline_tab = st.tabs(("Original", "AI Proposed", "Unified Redline"))
        original_tab.markdown(f'<div class="redline">{esc(finding["original_text"])}</div>', unsafe_allow_html=True)
        proposed_tab.markdown(f'<div class="redline">{esc(finding["proposed_text"])}</div>', unsafe_allow_html=True)
        redline_tab.markdown(unified_redline(finding), unsafe_allow_html=True)
        render_decision_editor(report, finding, prefix)
        if finding.get("decision_history"):
            st.markdown("#### Decision history")
            history = pd.DataFrame(finding["decision_history"])
            columns = [column for column in ("timestamp", "reviewer", "new_status", "reviewer_comment", "modification_reason", "rejection_reason") if column in history.columns]
            st.dataframe(history[columns], hide_index=True, width="stretch")


def render_findings(report: dict[str, Any]) -> None:
    render_header(report, "Findings", "Prioritized AI-identified findings with evidence, review basis, risk, recommendation, and human disposition.")
    findings = filtered_findings(report)
    st.caption(f"Showing {len(findings)} of {len(report['findings'])} findings")
    if not findings:
        st.info("No findings match the selected filters.")
        return
    selected_ids = [finding["finding_id"] for finding in findings]
    current = st.session_state.get("selected_finding")
    if current not in selected_ids:
        current = selected_ids[0]
    selected_id = st.selectbox("Focused finding", selected_ids, index=selected_ids.index(current), key="focused_finding")
    st.session_state.selected_finding = selected_id
    selected = next(finding for finding in findings if finding["finding_id"] == selected_id)
    render_finding_detail(report, selected, f"finding_{selected_id}")
    st.markdown("### Findings register")
    page_size = 20
    total_pages = max(1, (len(findings) + page_size - 1) // page_size)
    page = st.selectbox("Register page", tuple(range(1, total_pages + 1)), key="findings_page")
    for finding in findings[(page - 1) * page_size : page * page_size]:
        label = f"{finding['finding_id']} · {finding['severity'].upper()} · {finding['category']} · {finding['status']}"
        with st.expander(label):
            st.markdown(f"**{finding['title']}**")
            st.caption(f"{finding['document']} · {finding['section']}")
            st.write(finding["finding"])


def render_documents(report: dict[str, Any]) -> None:
    render_header(report, "Documents", "Document-specific finding counts, unresolved risk, extraction status, and review confidence.")
    summaries = list(report.get("document_summaries", []))
    sort_choice = st.selectbox("Sort documents", ("Highest Risk", "Most Findings", "Document Name", "Review Status"))
    if sort_choice == "Highest Risk":
        summaries.sort(key=lambda item: (SEVERITY_ORDER.get(item["highest_unresolved_severity"], 99), -item["finding_count"]))
    elif sort_choice == "Most Findings":
        summaries.sort(key=lambda item: (-item["finding_count"], item["document_name"]))
    elif sort_choice == "Document Name":
        summaries.sort(key=lambda item: item["document_name"])
    else:
        summaries.sort(key=lambda item: (-item["open_count"], item["document_name"]))
    reviews = {
        (item.get("document_name") or item.get("name") or (item.get("document") or {}).get("name")): item
        for item in report.get("detailed_document_review", [])
    }
    for row in range(0, len(summaries), 3):
        columns = st.columns(3)
        for column, summary in zip(columns, summaries[row : row + 3]):
            with column.container(border=True):
                highest = summary["highest_unresolved_severity"]
                risk_badge = (
                    f'<span class="severity-badge {slug(highest)}">{esc(highest).upper()}</span>'
                    if highest != "None"
                    else ""
                )
                st.markdown(
                    f'<div class="finding-head"><span class="category-badge">{esc(summary["document_type"])}</span>{risk_badge}</div>',
                    unsafe_allow_html=True,
                )
                st.markdown(f"**{summary['document_name']}**")
                st.caption(f"Revision {summary['revision']} · {summary.get('extraction_status', 'Not Available')} extraction")
                metric_cols = st.columns(3)
                metric_cols[0].metric("Findings", summary["finding_count"])
                metric_cols[1].metric("Major", summary["severity_counts"]["Major"])
                metric_cols[2].metric("Open", summary["open_count"])
                review = reviews.get(summary["document_name"], {})
                confidence = review.get("review_confidence", {})
                st.progress((confidence.get("score") or 0) / 100, text=f"Review confidence: {confidence.get('score', 'Not Available')}{'%' if confidence.get('score') is not None else ''}")


def render_traceability(report: dict[str, Any]) -> None:
    render_header(report, "Traceability", "Finding → document → section → review basis → proposed change → reviewer decision.")
    rows = []
    for finding in report["findings"]:
        basis = (finding.get("review_basis") or [{}])[0]
        rows.append(
            {
                "Finding": finding["finding_id"],
                "Severity": finding["severity"],
                "Document": finding["document"],
                "Section": finding["section"],
                "Review Basis": basis.get("source_name", "Not Available"),
                "Reference Status": basis.get("verification_status", "Needs Verification"),
                "Reviewer Status": finding["status"],
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=560)
    st.download_button("Download traceability CSV", traceability_csv(report), f"{slug(report['package_name'])}-traceability.csv", "text/csv")


def redline_export(report: dict[str, Any], document: dict[str, Any], findings: list[dict[str, Any]]) -> bytes:
    accepted = [finding for finding in findings if accepted_change(finding)]
    changes = "".join(
        f"<article><h3>{esc(finding['finding_id'])} · {esc(finding['status'])}</h3><p><strong>Original:</strong> {esc(finding['original_text'])}</p><p><strong>Final accepted wording:</strong> {esc(accepted_change(finding))}</p><p><strong>Reviewer:</strong> {esc(finding.get('reviewer') or 'Not Available')}</p></article>"
        for finding in accepted
    ) or "<p>No accepted or modified recommendations are available for incorporation. The source remains unchanged.</p>"
    content = f"""<!doctype html><html><head><meta charset="utf-8"><title>{esc(document['document_name'])} Reviewed Redline</title><style>body{{font:14px/1.6 Arial,sans-serif;max-width:1000px;margin:40px auto;padding:0 24px;color:#17231e}}pre{{white-space:pre-wrap;border:1px solid #d2dbd6;background:#f8faf9;padding:16px}}article{{border-top:1px solid #ccd5d0;padding:16px 0}}</style></head><body><h1>{esc(document['document_name'])}</h1><p>Review Run: {esc(report['review_id'])} · Source document preserved · Rejected recommendations excluded</p><h2>Immutable extracted source</h2><pre>{esc(document.get('source_text', 'Not Available'))}</pre><h2>Reviewer-accepted change set</h2>{changes}</body></html>"""
    return content.encode("utf-8")


def render_redlines(report: dict[str, Any]) -> None:
    render_header(report, "Redlines", "Compare immutable source text with AI-proposed wording and reviewer-controlled accepted changes.")
    st.markdown('<div class="notice"><strong>AI-generated proposed wording.</strong><span>Source text is preserved and remains unchanged until reviewer acceptance. All recommendations require human review and disposition.</span></div>', unsafe_allow_html=True)
    documents = report.get("redlined_documents", [])
    if not documents:
        st.info("No redline documents are available in this review.")
        return
    selected_name = st.selectbox("Document", [item["document_name"] for item in documents])
    document = next(item for item in documents if item["document_name"] == selected_name)
    related = [
        finding for finding in report["findings"]
        if finding["finding_id"] in document.get("finding_ids", [])
        or any(reference.get("document_name") == selected_name for reference in finding.get("affected_documents", []))
    ]
    if related:
        selected_finding_id = st.selectbox("Finding", [finding["finding_id"] for finding in related], format_func=lambda value: f"{value} · {next(item['title'] for item in related if item['finding_id'] == value)}")
        finding = next(item for item in related if item["finding_id"] == selected_finding_id)
        st.markdown(f'<div class="finding-head">{finding_badges(finding)}</div>', unsafe_allow_html=True)
        mode = st.radio("View mode", ("Split View", "Unified Redline", "Proposed Text Only"), horizontal=True)
        if mode == "Split View":
            left, right = st.columns(2)
            left.markdown("**Original source text**")
            left.markdown(f'<div class="redline">{esc(finding["original_text"])}</div>', unsafe_allow_html=True)
            right.markdown("**AI proposed text**")
            right.markdown(f'<div class="redline">{esc(finding["proposed_text"])}</div>', unsafe_allow_html=True)
        elif mode == "Unified Redline":
            st.markdown(unified_redline(finding), unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="redline">{esc(finding["proposed_text"])}</div>', unsafe_allow_html=True)
        final_text = accepted_change(finding)
        if finding["status"] == "Rejected":
            st.error("Rejected recommendation — excluded from the final reviewed document.")
        elif final_text:
            st.success(f"Reviewer-controlled final wording: {final_text}")
        else:
            st.warning("Pending human disposition — source remains unchanged.")
    else:
        st.info("This document has no associated proposed changes.")
    with st.expander("View immutable extracted source document"):
        st.code(document.get("source_text", "Source text is not available in this historical review."), language=None)
    st.download_button(
        "Export selected redlined document",
        redline_export(report, document, related),
        f"{slug(document['document_name'])}-reviewed-redline.html",
        "text/html",
    )


def render_decisions(report: dict[str, Any]) -> None:
    render_header(report, "Review Decisions", "Consolidated human decision record, kept separate from the original AI recommendation.")
    decided = [finding for finding in report["findings"] if finding["status"] != "Open"]
    statuses = st.multiselect("Decision status", DECISION_OPTIONS[1:], default=list(DECISION_OPTIONS[1:]))
    decided = [finding for finding in decided if finding["status"] in statuses]
    rows = [
        {
            "Finding": finding["finding_id"],
            "Severity": finding["severity"],
            "Document": finding["document"],
            "AI Recommendation": finding["proposed_text"],
            "Human Decision": finding["status"],
            "Reviewer Comment": finding.get("reviewer_comment") or "",
            "Reviewer": finding.get("reviewer") or "Not Available",
            "Decision Date": fmt_time(finding.get("reviewed_at")),
        }
        for finding in decided
    ]
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=520)
        selected = st.selectbox("Decision detail", [finding["finding_id"] for finding in decided])
        render_finding_detail(report, next(finding for finding in decided if finding["finding_id"] == selected), f"decision_{selected}")
    else:
        st.info("No reviewer decisions match the selected status filters. Open Findings to record a disposition.")
    st.download_button("Download reviewer decision log", decisions_csv(report), f"{slug(report['package_name'])}-decision-log.csv", "text/csv")


report = current_report()
page = render_sidebar(report)

if report is None:
    render_upload()
elif page == "Executive Summary":
    render_summary(report)
elif page == "Findings":
    render_findings(report)
elif page == "Documents":
    render_documents(report)
elif page == "Traceability":
    render_traceability(report)
elif page == "Redlines":
    render_redlines(report)
else:
    render_decisions(report)
