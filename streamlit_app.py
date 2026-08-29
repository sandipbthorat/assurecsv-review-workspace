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
    --ink: #eef4ff;
    --muted: #98a9c1;
    --line: #263b55;
    --line-strong: #344d6a;
    --panel: #0d1c2f;
    --panel-soft: #102238;
    --navy: #071426;
    --blue: #2c86f7;
    --green: #42d982;
    --red: #ff5b5b;
    --amber: #ffb21e;
    --violet: #8e5cff;
    --soft: #13273e;
  }
  html, body, [class*="css"] { font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
  body { background: var(--navy); }
  #MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"] { display:none !important; }
  [data-testid="stHeader"] { display:none; }
  [data-testid="stAppViewContainer"] { background: linear-gradient(145deg,#091629 0%,#081525 45%,#0a192b 100%); color:var(--ink); }
  [data-testid="stMain"] { background: transparent; }
  [data-testid="stSidebar"] { width: 300px !important; min-width: 300px !important; background:linear-gradient(180deg,#061322,#081729); border-right:1px solid #1f324a; }
  [data-testid="stSidebar"] > div:first-child { padding: 1.1rem 1rem 2rem; }
  [data-testid="stSidebar"] * { color:#c8d5e8; }
  [data-testid="stSidebar"] hr { border-color:#1f334c; margin:.65rem 0; }
  [data-testid="stSidebar"] .stButton { margin:0 0 .18rem; }
  [data-testid="stSidebar"] .stButton > button { width:100%; min-height:42px; justify-content:flex-start; padding:.55rem .8rem; border:1px solid transparent; border-radius:8px; color:#c5d2e5; background:transparent; font-size:.88rem; font-weight:520; box-shadow:none; }
  [data-testid="stSidebar"] .stButton > button:hover { color:#f3f7ff; border-color:#24415f; background:#0f2741; }
  [data-testid="stSidebar"] .stButton > button[kind="primary"] { color:#79b9ff; border-color:#194b80; border-left:3px solid #2c91ff; background:linear-gradient(90deg,#153b66,#123155); }
  .block-container { max-width:none; padding:0 2rem 4rem; }
  h1, h2, h3 { letter-spacing: -0.025em; }
  h1 { color:#f3f7ff !important; font-size:clamp(2rem,3vw,3rem) !important; line-height:1.05 !important; }
  h2, h3 { color:#eef4ff !important; }
  p, label, .stCaption, [data-testid="stMarkdownContainer"] { color:#c3cee0; }
  .sidebar-brand { display:flex; gap:.7rem; align-items:center; padding:.15rem .45rem 1rem; }
  .sidebar-brand-mark { position:relative; width:38px; height:38px; flex:0 0 38px; }
  .sidebar-brand-mark i { position:absolute; width:15px; height:15px; border-radius:7px 9px 7px 9px; transform:rotate(-12deg); }
  .sidebar-brand-mark i:nth-child(1){left:1px;top:1px;background:#5a85ff}.sidebar-brand-mark i:nth-child(2){right:1px;top:7px;background:#865dff}.sidebar-brand-mark i:nth-child(3){left:0;bottom:0;background:#2da8ff}.sidebar-brand-mark i:nth-child(4){right:2px;bottom:1px;background:#2867dc}
  .sidebar-brand-copy { display:grid; min-width:0; }
  .sidebar-brand-copy strong { color:#f5f8ff; font-size:1.05rem; letter-spacing:-.03em; white-space:nowrap; }
  .sidebar-brand-copy small { color:#b4c2d8; font-size:.72rem; }
  .nav-section { margin:1rem .45rem .35rem; color:#8191aa; font-size:.62rem; font-weight:850; letter-spacing:.13em; text-transform:uppercase; }
  .sidebar-note { margin:.8rem .45rem 0; padding:.7rem; border:1px solid #243a53; border-radius:7px; color:#8596ae; background:#0a1a2c; font-size:.64rem; line-height:1.5; }
  .app-topbar { position:sticky; top:0; z-index:20; display:grid; grid-template-columns:44px minmax(280px,640px) 1fr auto; gap:1rem; align-items:center; min-height:74px; margin:0 -2rem 2rem; padding:0 2rem; border-bottom:1px solid #203650; background:rgba(6,18,33,.95); backdrop-filter:blur(14px); }
  .menu-glyph { color:#b9c7da; font-size:1.45rem; }
  .top-search { display:flex; gap:.65rem; align-items:center; height:42px; padding:0 .85rem; border:1px solid #2b4260; border-radius:9px; color:#8fa2bd; background:#0b1b2e; }
  .top-search strong { color:#aebbd0; font-size:1rem; font-weight:500; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .top-search kbd { margin-left:auto; padding:.2rem .35rem; border:1px solid #38506e; border-radius:5px; color:#b8c5d8; background:#11243a; font:600 .72rem ui-monospace,monospace; }
  .top-actions { display:flex; gap:1.25rem; align-items:center; color:#b9c7da; }
  .top-alert { position:relative; font-size:1.1rem; }.top-alert b{position:absolute;top:-12px;right:-10px;display:grid;width:18px;height:18px;place-items:center;border-radius:50%;color:white;background:#f0504b;font-size:.6rem}
  .top-avatar { display:grid; width:40px; height:40px; place-items:center; border:3px solid #edf2fb; border-radius:50%; color:#102035; background:#d7a37d; font-size:.78rem; font-weight:900; }
  .top-profile { display:grid; line-height:1.2; }.top-profile strong{color:#f1f5fc;font-size:.76rem}.top-profile small{color:#91a1b7;font-size:.64rem}
  .eyebrow { color:#5ea9ff; font-size:.68rem; font-weight:850; letter-spacing:.12em; text-transform:uppercase; margin-bottom:.25rem; }
  .hero-copy { color:var(--muted); max-width:860px; font-size:1rem; }
  .context-header { display:flex; gap:1rem; align-items:flex-start; justify-content:space-between; margin-bottom:1rem; }
  .context-header h1 { font-size:2rem !important; margin:.1rem 0; }
  .run-line { color:var(--muted); font-size:.78rem; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
  .dashboard-intro { margin:.25rem 0 .9rem; }.dashboard-intro p{margin:.35rem 0 0;color:#aebbd0}
  .dashboard-actions [data-testid="stButton"] > button { min-height:48px; font-size:.92rem; font-weight:800; }
  .kpi-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:1rem; margin:1.15rem 0; }
  .kpi-card { position:relative; min-height:180px; overflow:hidden; padding:1.1rem; border:1px solid #2c4260; border-radius:10px; background:linear-gradient(155deg,#102239,#0d1b2e); box-shadow:0 12px 30px rgba(0,0,0,.12); }
  .kpi-head { display:grid; grid-template-columns:52px 1fr 16px; gap:.8rem; align-items:center; }
  .kpi-icon { display:grid; width:48px; height:48px; place-items:center; border-radius:50%; font-size:1.25rem; }.kpi-icon.blue{color:#55a7ff;background:#12386a}.kpi-icon.red{color:#ff6464;background:#51282c}.kpi-icon.green{color:#51dc88;background:#154b36}
  .kpi-copy { display:grid; }.kpi-copy span{color:#aebbd0;font-size:.82rem}.kpi-copy strong{color:#f2f6ff;font-size:1.72rem;line-height:1.1}.kpi-menu{color:#9dabc0;font-size:1.2rem}
  .kpi-note { margin:.75rem 0 0 64px; color:#bac6d8; font-size:.78rem }.kpi-note b{color:#dce5f2}.kpi-note .down{color:#ff6262}.kpi-note .up{color:#52dc88}
  .sparkline { position:absolute; left:1rem; right:1rem; bottom:.45rem; width:calc(100% - 2rem); height:48px; }
  .reviews-panel { margin:1rem 0; border:1px solid #2a405c; border-radius:10px; background:#0e1f34; overflow:hidden; }
  .reviews-head { display:flex; align-items:center; justify-content:space-between; padding:1rem 1.1rem .6rem; }.reviews-head strong{color:#f1f5ff;font-size:1.05rem}.reviews-head a{color:#4fa8ff;font-size:.75rem;font-weight:800}
  .review-tabs { display:flex; gap:2rem; padding:0 1.1rem; border-bottom:1px solid #2a405b; }.review-tabs span{padding:.75rem .5rem;color:#b6c3d6;font-size:.78rem}.review-tabs .active{color:#46a1ff;border-bottom:2px solid #348fff}
  .review-list { padding:0 1.1rem; }.review-row{display:grid;grid-template-columns:52px minmax(0,1fr) 150px 20px;gap:.8rem;align-items:center;min-height:74px;border-bottom:1px solid #2a405b}.review-row:last-child{border-bottom:0}.file-chip{display:grid;width:44px;height:44px;place-items:center;border-radius:7px;color:white;font-size:.72rem;font-weight:850}.file-chip.word{background:#2075e5}.file-chip.pdf{background:#db3e49}.file-chip.xlsx{background:#1b9d52}.review-name{display:grid}.review-name strong{color:#eef4ff;font-size:.82rem}.review-name small{color:#8fa1b9;font-size:.72rem}.review-status{justify-self:end;padding:.32rem .55rem;border:1px solid transparent;border-radius:6px;font-size:.7rem;white-space:nowrap}.review-status.review{color:#c087ff;background:#312453;border-color:#49316b}.review-status.processing{color:#55a9ff;background:#123660;border-color:#184678}.review-status.complete{color:#42dc7f;background:#123f2c;border-color:#185a3b}.review-status.pending{color:#ffb41f;background:#493715;border-color:#5f4717}.review-status.not-started{color:#b8c4d6;background:#1b2b41;border-color:#2a3c55}
  .module-shell { min-height:360px; padding:1.3rem; border:1px solid #2a405c; border-radius:10px; background:#0d1e32; }.module-shell p{max-width:760px;color:#9fb0c7}.module-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem;margin-top:1rem}.module-card{padding:1rem;border:1px solid #293f5a;border-radius:8px;background:#10233a}.module-card span{color:#4fa8ff;font-size:.7rem;font-weight:850;letter-spacing:.08em}.module-card strong{display:block;margin:.4rem 0;color:#eef4ff}.module-card small{color:#91a3ba;line-height:1.5}
  .status-badge,.severity-badge,.category-badge,.confidence-badge { display:inline-flex; width:fit-content; align-items:center; padding:.27rem .52rem; border-radius:999px; font-size:.68rem; font-weight:850; letter-spacing:.045em; white-space:nowrap; }
  .status-badge { color:#b8c5d6; background:#1c2c42; }
  .status-badge.accepted,.status-badge.resolved,.status-badge.ready-for-approval,.status-badge.review-completed { color:#45df83; background:#133e2c; }
  .status-badge.rejected { color:#ff7474; background:#4a2529; }
  .status-badge.modified { color:#62b0ff; background:#14385e; }
  .status-badge.deferred { color:#ffc04b; background:#493719; }
  .status-badge.needs-sme-review,.status-badge.reviewer-action-required { color:#c58cff; background:#352651; }
  .severity-badge { border:1px solid currentColor; text-transform:uppercase; }
  .severity-badge.critical { color:#ff6868; background:#472428; }.severity-badge.major { color:#ffb536; background:#493619; }.severity-badge.minor { color:#59aaff; background:#14365a; }.severity-badge.observation { color:#b4c1d2; background:#1c2c41; }
  .category-badge { color:#b5c2d4; background:#1b2c42; }.confidence-badge { color:#63b3ff; background:#15375a; }
  .finding-head { display:flex; flex-wrap:wrap; align-items:center; gap:.5rem; margin-bottom:.7rem; }
  .finding-id { font:800 .76rem ui-monospace,SFMono-Regular,Menlo,monospace; }
  .finding-title { color:#eff4fc; font:700 1.05rem Inter,sans-serif; margin:.15rem 0 .35rem; }
  .finding-meta { color:var(--muted); font-size:.76rem; }
  .detail-block { border-left:3px solid #4b8ac7; padding:.65rem .85rem; background:#0c1b2d; border-radius:.25rem; margin:.35rem 0 1rem; }.detail-block.risk { border-left-color:#d49936; background:#241f18; }
  .detail-label { color:var(--muted); font-size:.64rem; font-weight:850; letter-spacing:.1em; text-transform:uppercase; margin-bottom:.35rem; }
  .source-text { white-space:pre-wrap; overflow-wrap:anywhere; font: .78rem/1.65 ui-monospace,SFMono-Regular,Menlo,monospace; }
  .redline { white-space:pre-wrap; overflow-wrap:anywhere; font:.82rem/1.8 ui-monospace,SFMono-Regular,Menlo,monospace; padding:1rem; border:1px solid var(--line); border-radius:.55rem; color:#dbe5f3;background:#09182a; }
  .redline del { color:#8e3030; background:#fee8e6; text-decoration-thickness:1.5px; }
  .redline ins { color:#17613f; background:#dff4e7; text-decoration:none; }
  .readiness { display:grid; grid-template-columns:minmax(170px,.35fr) 1fr; gap:1.2rem; align-items:center; border:1px solid #2b4563; border-radius:.7rem; background:linear-gradient(110deg,#10283d,#0c1b2e); padding:1rem 1.2rem; margin:.4rem 0 1.2rem; }.readiness strong { display:block; color:#eef4ff;font:700 1.35rem Inter,sans-serif; }
  .readiness ul { margin:.2rem 0; color:var(--muted); font-size:.8rem; }
  .notice { display:flex; gap:.7rem; padding:.85rem 1rem; border:1px solid #31506f; border-radius:.55rem; color:#b9d8f2; background:#10283d; margin:.6rem 0 1rem; font-size:.8rem; }
  [data-testid="stMetric"] { background:#0e1f34; border:1px solid var(--line); border-radius:.65rem; padding:.85rem 1rem; min-height:112px; }
  [data-testid="stMetricLabel"] { color:var(--muted); }
  [data-testid="stExpander"], [data-testid="stVerticalBlockBorderWrapper"] { border-color:var(--line)!important; background:#0e1f34!important; border-radius:.7rem; }
  [data-testid="stFileUploaderDropzone"] { min-height:120px; border:1px dashed #4a6587; border-radius:9px; background:#0a1a2d; }
  [data-baseweb="input"] > div, [data-baseweb="textarea"] > div, [data-baseweb="select"] > div { color:#e7eef9!important; border-color:#314b68!important; background:#0a192b!important; }
  input, textarea { color:#e8eef8!important; caret-color:#5baaff!important; }
  [data-testid="stDataFrame"] { border:1px solid #2b4059; border-radius:8px; overflow:hidden; }
  .stButton>button, .stDownloadButton>button { border-color:#314b68; color:#dbe6f5; background:#0f2035; }
  .stButton>button:hover, .stDownloadButton>button:hover { border-color:#4999ed; color:white; background:#173455; }
  .stButton>button[kind="primary"], .stDownloadButton>button[kind="primary"] { color:white; background:#237ce6; border-color:#237ce6; }.stButton>button[kind="primary"]:hover, .stDownloadButton>button[kind="primary"]:hover { background:#3391ff; border-color:#3391ff; }
  [data-testid="stAlert"] { border-color:#2c4765; background:#0e2338; }
  @media(max-width:1100px){.kpi-grid{grid-template-columns:1fr}.module-grid{grid-template-columns:1fr}.top-profile{display:none}.review-row{grid-template-columns:48px minmax(0,1fr) 120px 12px}}
  @media(max-width:800px){[data-testid="stSidebar"]{width:260px!important;min-width:260px!important}.block-container{padding-inline:1rem}.app-topbar{margin-inline:-1rem;padding-inline:1rem;grid-template-columns:28px 1fr auto}.top-profile{display:none}.context-header{display:block}.readiness{grid-template-columns:1fr}.dashboard-intro h1{font-size:2rem!important}}
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
    st.session_state.shell_page = "Executive Summary"
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
    if "shell_page" not in st.session_state:
        st.session_state.shell_page = "Home"
    current = st.session_state.shell_page

    st.sidebar.markdown(
        """
        <div class="sidebar-brand">
          <span class="sidebar-brand-mark" aria-hidden="true"><i></i><i></i><i></i><i></i></span>
          <span class="sidebar-brand-copy"><strong>CSVQualReviewer</strong><small>AI Document Review</small></span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    def nav_button(label: str, page: str, key: str) -> None:
        if st.sidebar.button(
            label,
            key=key,
            type="primary" if current == page else "secondary",
            width="stretch",
        ):
            st.session_state.shell_page = page
            st.rerun()

    nav_button("⌂   Home", "Home", "nav_home")
    st.sidebar.markdown('<div class="nav-section">Review workspace</div>', unsafe_allow_html=True)
    nav_button("♧   My Reviews  ·  12", "Executive Summary", "nav_reviews")
    nav_button("▤   All Documents", "Documents", "nav_documents")
    nav_button("⇩   Upload Document   ＋", "Upload", "nav_upload")
    nav_button("◌   Chat with CSVQualReviewer", "Chat", "nav_chat")
    nav_button("◷   Findings", "Findings", "nav_findings")
    nav_button("↶   Run History", "Run History", "nav_history")
    nav_button("⌁   Feedback & Analytics", "Feedback & Analytics", "nav_feedback")

    st.sidebar.markdown('<div class="nav-section">Reference library</div>', unsafe_allow_html=True)
    nav_button("▱   All References", "All References", "nav_references")
    nav_button("▣   Templates", "Templates", "nav_templates")
    nav_button("♧   SOPs", "SOPs", "nav_sops")
    nav_button("▧   Golden Reports", "Golden Reports", "nav_golden")
    nav_button("▤   Guidance Documents", "Guidance Documents", "nav_guidance")

    st.sidebar.markdown('<div class="nav-section">Administration</div>', unsafe_allow_html=True)
    nav_button("⚙   Review Administrator", "Review Administrator", "nav_review_admin")
    nav_button("⚙   Platform Administrator", "Platform Administrator", "nav_platform_admin")

    if report:
        st.sidebar.markdown('<div class="nav-section">Active review</div>', unsafe_allow_html=True)
        nav_button("◎   Executive Summary", "Executive Summary", "nav_summary")
        nav_button("⇄   Traceability", "Traceability", "nav_traceability")
        nav_button("✎   Redlines", "Redlines", "nav_redlines")
        nav_button("✓   Review Decisions", "Review Decisions", "nav_decisions")
        st.sidebar.markdown(
            f'<div class="sidebar-note"><strong>{esc(report["package_name"])}</strong><br>{esc(report["review_id"])}<br>{esc(report["review_workflow"]["status"])}</div>',
            unsafe_allow_html=True,
        )
        with st.sidebar.expander("Export controlled outputs"):
            file_slug = slug(report["package_name"])
            st.download_button("Review report", report_html(report), f"{file_slug}-review-report.html", "text/html", width="stretch")
            st.download_button("Findings CSV", findings_csv(report["findings"]), f"{file_slug}-findings.csv", "text/csv", width="stretch")
            st.download_button("Decision log", decisions_csv(report), f"{file_slug}-decision-log.csv", "text/csv", width="stretch")
            st.download_button("Traceability", traceability_csv(report), f"{file_slug}-traceability.csv", "text/csv", width="stretch")
            st.download_button("Structured JSON", json.dumps(report, indent=2), f"{file_slug}-{report['review_id']}.json", "application/json", width="stretch")
    st.sidebar.markdown(
        '<div class="sidebar-note"><strong>Human review required</strong><br>AI findings remain advisory until a qualified reviewer records a disposition.</div>',
        unsafe_allow_html=True,
    )
    return current


def render_topbar() -> None:
    st.markdown(
        """
        <div class="app-topbar">
          <span class="menu-glyph" aria-hidden="true">☰</span>
          <div class="top-search"><span aria-hidden="true">⌕</span><strong>Search documents, findings, users…</strong><kbd>⌘K</kbd></div>
          <span></span>
          <div class="top-actions"><span class="top-alert">♧<b>8</b></span><span>?</span><span class="top-avatar">AN</span><span class="top-profile"><strong>Arvind Narayanamurthy</strong><small>Review Administrator</small></span><span>⌄</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_dashboard(report: dict[str, Any] | None) -> None:
    intro, actions = st.columns([1.45, .8], gap="large")
    with intro:
        st.markdown('<div class="dashboard-intro">', unsafe_allow_html=True)
        st.title("Welcome back, Arvind 👋")
        st.markdown("<p>Here’s what’s happening with your reviews today.</p></div>", unsafe_allow_html=True)
    with actions:
        left, right = st.columns(2)
        if left.button("＋  Upload Document", type="primary", width="stretch"):
            st.session_state.shell_page = "Upload"
            st.rerun()
        if right.button("▷  New Review", width="stretch"):
            st.session_state.shell_page = "Upload"
            st.rerun()

    st.markdown(
        """
        <section class="kpi-grid" aria-label="Review metrics">
          <article class="kpi-card"><div class="kpi-head"><span class="kpi-icon blue">▤</span><span class="kpi-copy"><span>Documents Reviewed</span><strong>128</strong></span><span class="kpi-menu">⋮</span></div><p class="kpi-note"><b>+18</b> this week</p><svg class="sparkline" viewBox="0 0 300 50" preserveAspectRatio="none"><defs><linearGradient id="violetFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7b48ff" stop-opacity=".35"/><stop offset="1" stop-color="#7b48ff" stop-opacity="0"/></linearGradient></defs><path d="M0 40 L22 35 L44 32 L66 38 L88 28 L110 22 L132 30 L154 25 L176 29 L198 18 L220 21 L242 7 L266 19 L300 2 L300 50 L0 50Z" fill="url(#violetFill)"/><path d="M0 40 L22 35 L44 32 L66 38 L88 28 L110 22 L132 30 L154 25 L176 29 L198 18 L220 21 L242 7 L266 19 L300 2" fill="none" stroke="#8a59ff" stroke-width="1.6"/></svg></article>
          <article class="kpi-card"><div class="kpi-head"><span class="kpi-icon red">!</span><span class="kpi-copy"><span>Critical Findings</span><strong>23</strong></span><span class="kpi-menu">⋮</span></div><p class="kpi-note"><span class="down">↓ 12%</span> vs last week</p><svg class="sparkline" viewBox="0 0 300 50" preserveAspectRatio="none"><defs><linearGradient id="redFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ff4646" stop-opacity=".3"/><stop offset="1" stop-color="#ff4646" stop-opacity="0"/></linearGradient></defs><path d="M0 28 L24 12 L48 27 L72 33 L96 18 L120 31 L144 37 L168 31 L192 27 L216 23 L240 30 L266 20 L286 24 L300 5 L300 50 L0 50Z" fill="url(#redFill)"/><path d="M0 28 L24 12 L48 27 L72 33 L96 18 L120 31 L144 37 L168 31 L192 27 L216 23 L240 30 L266 20 L286 24 L300 5" fill="none" stroke="#ff4545" stroke-width="1.6"/></svg></article>
          <article class="kpi-card"><div class="kpi-head"><span class="kpi-icon green">◷</span><span class="kpi-copy"><span>Avg. Review Time</span><strong>36<small> min</small></strong></span><span class="kpi-menu">⋮</span></div><p class="kpi-note"><span class="up">↓ 45%</span> vs baseline</p><svg class="sparkline" viewBox="0 0 300 50" preserveAspectRatio="none"><defs><linearGradient id="greenFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#38d77a" stop-opacity=".3"/><stop offset="1" stop-color="#38d77a" stop-opacity="0"/></linearGradient></defs><path d="M0 28 L24 18 L48 15 L72 22 L96 34 L120 27 L144 19 L168 17 L192 14 L216 18 L240 13 L264 9 L286 11 L300 4 L300 50 L0 50Z" fill="url(#greenFill)"/><path d="M0 28 L24 18 L48 15 L72 22 L96 34 L120 27 L144 19 L168 17 L192 14 L216 18 L240 13 L264 9 L286 11 L300 4" fill="none" stroke="#38d77a" stroke-width="1.6"/></svg></article>
        </section>
        <section class="reviews-panel">
          <div class="reviews-head"><strong>My Reviews</strong><a>View all</a></div>
          <div class="review-tabs"><span class="active">Assigned to me (5)</span><span>In Progress (4)</span><span>Completed</span></div>
          <div class="review-list">
            <div class="review-row"><span class="file-chip word">W</span><span class="review-name"><strong>DV Protocol - Temp Monitoring System</strong><small>DV Protocol</small></span><span class="review-status review">In Review</span><span>⋮</span></div>
            <div class="review-row"><span class="file-chip pdf">PDF</span><span class="review-name"><strong>TMV Report - Patient Arm Module</strong><small>TMV Report</small></span><span class="review-status processing">AI Processing</span><span>⋮</span></div>
            <div class="review-row"><span class="file-chip xlsx">XLSX</span><span class="review-name"><strong>F-03 Calibration Summary</strong><small>Report</small></span><span class="review-status complete">✓ Completed</span><span>⋮</span></div>
            <div class="review-row"><span class="file-chip word">W</span><span class="review-name"><strong>DV Plan - Power Management</strong><small>DV Plan</small></span><span class="review-status pending">Pending Uploads</span><span>⋮</span></div>
            <div class="review-row"><span class="file-chip pdf">PDF</span><span class="review-name"><strong>IQ Report - End of Line Test Station</strong><small>IQ Report</small></span><span class="review-status not-started">Not Started</span><span>⋮</span></div>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("### Start a review")
    package_name = st.text_input("Package name", placeholder="e.g., MARS 6.2 validation package", key="dashboard_package_name")
    files = st.file_uploader(
        "Drag and drop files here or click to browse",
        type=["pdf", "docx", "xlsx", "xlsm", "csv", "tsv", "txt", "md", "json", "xml", "html", "htm", "yaml", "yml"],
        accept_multiple_files=True,
        key="dashboard_files",
    )
    start, sample, active = st.columns([1, 1, 1.2])
    if start.button("Start independent review", type="primary", disabled=not files, width="stretch"):
        if len(files) > 21:
            st.error("Add one primary document and no more than 20 supporting documents.")
        else:
            with st.spinner("Building the validation evidence graph…"):
                try:
                    execute_review(package_name.strip() or "Untitled validation package", uploaded_payload(files))
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.rerun()
    if sample.button("Use realistic sample package", width="stretch"):
        with st.spinner("Reviewing the sample validation package…"):
            execute_review("NovaQMS 2.4 validation package", sample_payload())
        st.rerun()
    if report and active.button("Open active review", width="stretch"):
        st.session_state.shell_page = "Executive Summary"
        st.rerun()


def render_module_shell(page: str, report: dict[str, Any] | None) -> None:
    descriptions = {
        "Chat": "Ask grounded questions about the active review. Chat remains scoped to its documents, evidence, findings, and traceability.",
        "Run History": "Search and reopen review runs with their original inputs, configuration, findings, and reviewer decision record.",
        "Feedback & Analytics": "Monitor usefulness, false-positive patterns, citation quality, review volume, and cost trends.",
        "All References": "Manage controlled SOPs, templates, guidance, golden reports, and archived reference versions.",
        "Templates": "Maintain active and archived document templates used as controlled review context.",
        "SOPs": "Maintain approved procedures with revision-level traceability and lifecycle status.",
        "Golden Reports": "Curate approved exemplars used to calibrate review quality and comparison patterns.",
        "Guidance Documents": "Maintain approved internal standards and guidance used by the review engine.",
        "Review Administrator": "Manage users, document-type configuration, activation controls, analytics, and organization-scoped audit records.",
        "Platform Administrator": "Manage organizations, approved models, platform health, tenant isolation, and cross-organization audit.",
    }
    copy = descriptions.get(page, "This enterprise workspace is ready for configured organization data.")
    st.markdown(
        f"""
        <section class="module-shell">
          <div class="eyebrow">CSVQUALREVIEWER WORKSPACE</div><h1>{esc(page)}</h1><p>{esc(copy)}</p>
          <div class="module-grid"><article class="module-card"><span>01 · CONTROL</span><strong>Governed workspace</strong><small>Role-scoped actions, traceable changes, and human review boundaries remain visible.</small></article><article class="module-card"><span>02 · CONTEXT</span><strong>{'Active review available' if report else 'Ready for organization data'}</strong><small>{esc(report['package_name']) if report else 'Upload a validation package or connect approved enterprise sources.'}</small></article><article class="module-card"><span>03 · STATUS</span><strong>Enterprise integration point</strong><small>This module shell is prepared for validated persistence, SSO, RBAC, and controlled services.</small></article></div>
        </section>
        """,
        unsafe_allow_html=True,
    )
    if report and st.button("Open active review", type="primary"):
        st.session_state.shell_page = "Executive Summary"
        st.rerun()
    elif not report and st.button("Upload a validation package", type="primary"):
        st.session_state.shell_page = "Upload"
        st.rerun()


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
render_topbar()

if page == "Home":
    render_dashboard(report)
elif page == "Upload":
    render_upload()
elif report is None:
    render_module_shell(page, report)
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
elif page == "Review Decisions":
    render_decisions(report)
else:
    render_module_shell(page, report)
