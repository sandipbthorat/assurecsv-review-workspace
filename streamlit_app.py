"""CSVQualReviewer Streamlit Community Cloud entry point."""

from __future__ import annotations

import base64
import csv
from datetime import UTC, datetime
import hashlib
import html
import io
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from csv_reviewer import review_package
from csv_reviewer.document_generator import (
    DOCUMENT_BLUEPRINTS,
    build_docx,
    document_text,
    generate_document,
    update_section,
)
from csv_reviewer.feedback import FeedbackStore
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
ROLES = ("Reviewer", "Review Administrator", "Platform Administrator")
CORE_ROUTES = (
    "Home",
    "My Reviews",
    "All Documents",
    "Upload",
    "Document Generation",
    "Chat",
    "Run History",
    "Feedback & Analytics",
)
REFERENCE_ROUTES = ("All References", "Templates", "SOPs", "Golden Reports", "Guidance Documents")
REVIEW_ROUTES = ("Executive Summary", "Findings", "Documents", "Traceability", "Redlines", "Review Decisions")
ROUTE_SLUGS = {
    "Home": "home",
    "My Reviews": "my-reviews",
    "All Documents": "all-documents",
    "Upload": "upload",
    "Document Generation": "document-generation",
    "Chat": "chat",
    "Findings": "findings",
    "Run History": "run-history",
    "Feedback & Analytics": "analytics",
    "All References": "references",
    "Templates": "templates",
    "SOPs": "sops",
    "Golden Reports": "golden-reports",
    "Guidance Documents": "guidance",
    "Review Administrator": "review-administrator",
    "Platform Administrator": "platform-administrator",
    "Executive Summary": "executive-summary",
    "Documents": "review-documents",
    "Traceability": "traceability",
    "Redlines": "redlines",
    "Review Decisions": "review-decisions",
}
SLUG_ROUTES = {value: key for key, value in ROUTE_SLUGS.items()}
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_PACKAGE_BYTES = 200 * 1024 * 1024
OIDC_GROUP_ROLES = {
    "csvqual-reviewers": "Reviewer",
    "csvqual-review-administrators": "Review Administrator",
    "csvqual-platform-administrators": "Platform Administrator",
    "review administrator": "Review Administrator",
    "platform administrator": "Platform Administrator",
}


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
  [data-testid="stHeader"] { background:transparent!important; }
  [data-testid="stSidebarCollapsedControl"] { display:block!important; z-index:1000!important; }
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
  .route-context { margin:-1.2rem 0 .35rem; color:#8194ae; font-size:.66rem; font-weight:800; letter-spacing:.09em; text-transform:uppercase; }
  [class*="st-key-browser_route_"] { display:none!important; }
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
  .login-wrap { max-width:1020px; margin:4vh auto 0; }
  .login-brand { display:flex; gap:.9rem; align-items:center; margin-bottom:2rem; }
  .login-brand .sidebar-brand-mark { width:48px; height:48px; flex-basis:48px; }
  .login-brand .sidebar-brand-mark i { width:19px; height:19px; }
  .login-brand strong { display:block; color:#f5f8ff; font-size:1.45rem; letter-spacing:-.04em; }
  .login-brand small { color:#96a7bf; }
  .login-hero { padding:2rem; border:1px solid #2b4260; border-radius:14px; background:linear-gradient(145deg,#10243c,#0b1b2e); box-shadow:0 30px 70px rgba(0,0,0,.22); }
  .login-hero h1 { max-width:720px; margin:.35rem 0 .8rem; }
  .login-features { display:grid; grid-template-columns:repeat(3,1fr); gap:.8rem; margin:1.4rem 0 0; }
  .login-feature { padding:.85rem; border:1px solid #29415e; border-radius:8px; color:#aebed2; background:#0b1d31; font-size:.76rem; }
  .login-feature strong { display:block; margin-bottom:.25rem; color:#edf4ff; font-size:.82rem; }
  .signed-in-card { margin:.8rem .2rem .4rem; padding:.75rem; border:1px solid #263e59; border-radius:8px; background:#0b1c2f; }
  .signed-in-card strong,.signed-in-card small { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .signed-in-card strong { color:#f1f6ff!important; font-size:.75rem; }
  .signed-in-card small { color:#8fa1ba!important; font-size:.64rem; }
  .access-denied { padding:1.25rem; border:1px solid #6a3c42; border-radius:10px; background:#2a1820; }
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
  [data-testid="stTextAreaRootElement"], [data-testid="stTextInputRootElement"], [data-testid="stSelectbox"] .react-aria-ComboBox > div { color:#e7eef9!important; border-color:#314b68!important; background:#0a192b!important; }
  input, textarea, [data-testid="stSelectbox"] input { color:#e8eef8!important; caret-color:#5baaff!important; }
  [data-testid="stDataFrame"] { border:1px solid #2b4059; border-radius:8px; overflow:hidden; }
  .stButton>button, .stDownloadButton>button { border-color:#314b68; color:#dbe6f5; background:#0f2035; }
  .stButton>button:hover, .stDownloadButton>button:hover { border-color:#4999ed; color:white; background:#173455; }
  .stButton>button[kind="primary"], .stDownloadButton>button[kind="primary"] { color:white; background:#237ce6; border-color:#237ce6; }.stButton>button[kind="primary"]:hover, .stDownloadButton>button[kind="primary"]:hover { background:#3391ff; border-color:#3391ff; }
  [data-testid="stAlert"] { border-color:#2c4765; background:#0e2338; }
  @media(max-width:1100px){.kpi-grid{grid-template-columns:1fr}.module-grid{grid-template-columns:1fr}.top-profile{display:none}.review-row{grid-template-columns:48px minmax(0,1fr) 120px 12px}}
  @media(max-width:800px){[data-testid="stSidebar"]{width:260px!important;min-width:260px!important}.block-container{padding-inline:1rem}.app-topbar{margin-inline:-1rem;padding-inline:1rem;grid-template-columns:28px 1fr auto}.top-profile{display:none}.context-header{display:block}.readiness{grid-template-columns:1fr}.dashboard-intro h1{font-size:2rem!important}.login-features{grid-template-columns:1fr}.login-hero{padding:1.2rem}}
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


def oidc_configured() -> bool:
    """Return whether an OIDC provider is configured in Streamlit secrets."""
    try:
        auth = st.secrets.get("auth", {})
    except Exception:
        return False
    required = ("redirect_uri", "cookie_secret", "client_id", "client_secret", "server_metadata_url")
    return bool(auth and all(auth.get(key) for key in required))


def app_setting(name: str, default: Any = None) -> Any:
    """Read a non-secret deployment setting from secrets or the environment."""

    try:
        configured = st.secrets.get("csvqualreviewer", {})
    except Exception:
        configured = {}
    environment_name = f"CSVQUALREVIEWER_{name.upper()}"
    return configured.get(name, os.getenv(environment_name, default))


def deployment_mode() -> str:
    value = str(app_setting("mode", "demo")).strip().lower()
    return value if value in {"demo", "production"} else "demo"


def demo_admin_roles_enabled() -> bool:
    value = str(app_setting("demo_admin_roles", "false")).strip().lower()
    return value in {"1", "true", "yes", "on"}


def configured_data_root() -> tuple[Path, str]:
    """Return the configured record root and a truthful durability label."""

    configured = str(app_setting("data_dir", "")).strip()
    if configured:
        return Path(configured).expanduser().resolve(), "Configured persistent path"
    return (ROOT / "data" / "runtime").resolve(), "Instance-local durable path"


def safe_namespace(value: str) -> str:
    readable = slug(value)[:48] or "workspace"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{readable}-{digest}"


def oidc_user() -> dict[str, str] | None:
    try:
        if not getattr(st.user, "is_logged_in", False):
            return None
        claims = dict(st.user)
    except Exception:
        return None
    groups_claim = claims.get("groups", [])
    if isinstance(groups_claim, str):
        groups_claim = [groups_claim]
    groups = {str(value).strip().lower() for value in groups_claim}
    claimed_role = str(claims.get("role", ""))
    if claimed_role in ROLES:
        role = claimed_role
    else:
        mapped_roles = {OIDC_GROUP_ROLES[group] for group in groups if group in OIDC_GROUP_ROLES}
        role = (
            "Platform Administrator" if "Platform Administrator" in mapped_roles
            else "Review Administrator" if "Review Administrator" in mapped_roles
            else "Reviewer"
        )
    name = str(claims.get("name") or claims.get("preferred_username") or claims.get("email") or "Authenticated user")
    email = str(claims.get("email") or "")
    tenant = str(
        claims.get("tenant_id")
        or claims.get("tid")
        or claims.get("hd")
        or (email.rsplit("@", 1)[-1] if "@" in email else "organization")
    )
    return {
        "name": name,
        "email": email,
        "role": role,
        "auth_type": "OIDC SSO",
        "tenant_id": tenant,
    }


def authenticated_user() -> dict[str, str] | None:
    return oidc_user() or st.session_state.get("auth_user")


def render_login() -> None:
    st.markdown(
        """
        <style>[data-testid="stSidebar"]{display:none!important}.block-container{max-width:1120px;padding:2rem}</style>
        <div class="login-wrap">
          <div class="login-brand"><span class="sidebar-brand-mark" aria-hidden="true"><i></i><i></i><i></i><i></i></span><span><strong>CSVQualReviewer</strong><small>Controlled AI document review workspace</small></span></div>
          <section class="login-hero"><div class="eyebrow">SECURE WORKSPACE</div><h1>Sign in to review with confidence.</h1><p class="hero-copy">Access is role-scoped. AI recommendations remain advisory until an authorized reviewer records a human decision.</p>
          <div class="login-features"><div class="login-feature"><strong>Human-controlled decisions</strong>Accept, modify, reject, defer, or escalate every recommendation.</div><div class="login-feature"><strong>Traceable evidence</strong>Keep findings connected to sources, requirements, redlines, and audit events.</div><div class="login-feature"><strong>Enterprise identity ready</strong>Use OIDC SSO when an identity provider is configured.</div></div></section>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("### Access options")
    access_tabs = ("Enterprise SSO",) if deployment_mode() == "production" else ("Enterprise SSO", "Demo access")
    tabs = st.tabs(access_tabs)
    sso_tab = tabs[0]
    with sso_tab:
        st.markdown("**Organization identity provider**")
        st.caption("Use your company-managed account. Role claims are mapped to Reviewer, Review Administrator, or Platform Administrator access.")
        if oidc_configured():
            if st.button("Continue with enterprise SSO", type="primary", width="stretch", key="oidc_login"):
                st.login()
        else:
            st.info("Enterprise SSO is ready to connect. Configure OIDC secrets in Streamlit Cloud to enable this option.")
            st.button("Enterprise SSO not configured", disabled=True, width="stretch")
    if deployment_mode() == "production" and not oidc_configured():
        st.error("Production mode requires configured OIDC secrets. Demo identity and role selection are disabled.")
    elif len(tabs) > 1:
        with tabs[1]:
            st.warning("Public demonstration only — entered identity is not verified and must not be used for regulated records.")
            with st.form("demo_login_form"):
                name = st.text_input("Full name", value="Demo Reviewer")
                email = st.text_input("Work email", value="reviewer@example.com")
                role = (
                    st.selectbox("Demo role", ROLES, index=0)
                    if demo_admin_roles_enabled()
                    else "Reviewer"
                )
                if not demo_admin_roles_enabled():
                    st.caption("Public demo access is restricted to the Reviewer role.")
                submitted = st.form_submit_button("Enter demo workspace", type="primary", width="stretch")
            if submitted:
                if not name.strip():
                    st.error("Enter your name.")
                elif "@" not in email or email.startswith("@") or email.endswith("@"):
                    st.error("Enter a valid work email address.")
                else:
                    normalized_email = email.strip().lower()[:240]
                    st.session_state.auth_user = {
                        "name": name.strip()[:120],
                        "email": normalized_email,
                        "role": role,
                        "auth_type": "Unverified demo access",
                        "tenant_id": normalized_email.rsplit("@", 1)[-1],
                    }
                    requested_page = SLUG_ROUTES.get(str(st.query_params.get("page", "")), "Home")
                    navigate(requested_page if page_allowed(requested_page, st.session_state.auth_user) else "Home")
                    st.rerun()


def page_allowed(page: str, user: dict[str, str]) -> bool:
    role = user.get("role", "Reviewer")
    if page == "Platform Administrator":
        return role == "Platform Administrator"
    if page == "Review Administrator":
        return role in {"Review Administrator", "Platform Administrator"}
    return page in ROUTE_SLUGS


def available_routes(user: dict[str, str]) -> tuple[str, ...]:
    pages = [*CORE_ROUTES, *REFERENCE_ROUTES, *REVIEW_ROUTES]
    if user.get("role") in {"Review Administrator", "Platform Administrator"}:
        pages.append("Review Administrator")
    if user.get("role") == "Platform Administrator":
        pages.append("Platform Administrator")
    return tuple(pages)


def _history_state(default_page: str = "Home") -> tuple[list[str], int]:
    history = st.session_state.get("route_history")
    cursor = st.session_state.get("route_history_cursor")
    if not isinstance(history, list) or not history:
        history = [default_page]
        cursor = 0
        st.session_state.route_history = history
        st.session_state.route_history_cursor = cursor
    if not isinstance(cursor, int) or cursor < 0 or cursor >= len(history):
        cursor = len(history) - 1
        st.session_state.route_history_cursor = cursor
    return history, cursor


def _activate_route(
    page: str,
    *,
    push_history: bool = True,
    history_cursor: int | None = None,
    update_query: bool = True,
) -> None:
    if page not in ROUTE_SLUGS:
        page = "Home"
    previous_slug = st.session_state.get("last_route_slug")
    history, cursor = _history_state(page)
    if history_cursor is not None:
        cursor = max(0, min(history_cursor, len(history) - 1))
    elif push_history and history[cursor] != page:
        history = [*history[: cursor + 1], page]
        cursor = len(history) - 1
    st.session_state.route_history = history
    st.session_state.route_history_cursor = cursor
    st.session_state.shell_page = page
    route_slug = ROUTE_SLUGS[page]
    st.session_state.last_route_slug = route_slug
    if update_query and previous_slug != route_slug:
        st.query_params["page"] = route_slug


def navigate(page: str) -> None:
    _activate_route(page)


def request_navigation(
    page: str,
    *,
    history_cursor: int | None = None,
    update_query: bool = True,
) -> bool:
    current = st.session_state.get("shell_page", "Home")
    dirty_prefix = st.session_state.get("unsaved_decision_prefix")
    if dirty_prefix and page != current:
        st.session_state.pending_navigation = page
        if history_cursor is not None:
            st.session_state.pending_history_cursor = history_cursor
        else:
            st.session_state.pop("pending_history_cursor", None)
        return False
    _activate_route(
        page,
        push_history=history_cursor is None,
        history_cursor=history_cursor,
        update_query=update_query,
    )
    return True


def sync_route_from_query(user: dict[str, str]) -> str:
    """Synchronize session routing with URL changes, including browser Back/Forward."""

    query_slug = str(st.query_params.get("page", "")).strip()
    browser_route = st.session_state.pop("browser_history_route_applied", None)
    from_browser_history = browser_route in ROUTE_SLUGS
    if from_browser_history:
        query_slug = ROUTE_SLUGS[browser_route]
    requested = SLUG_ROUTES.get(query_slug, "Home")
    if not page_allowed(requested, user):
        requested = "Home"
    current = st.session_state.get("shell_page")
    last_slug = st.session_state.get("last_route_slug")
    if current is None:
        _activate_route(requested, update_query=query_slug in SLUG_ROUTES)
        if query_slug not in SLUG_ROUTES:
            _activate_route("Home")
        return st.session_state.shell_page
    if query_slug != last_slug:
        history, cursor = _history_state(current)
        target_cursor: int | None = None
        if cursor > 0 and history[cursor - 1] == requested:
            target_cursor = cursor - 1
        elif cursor + 1 < len(history) and history[cursor + 1] == requested:
            target_cursor = cursor + 1
        if st.session_state.get("unsaved_decision_prefix") and requested != current:
            st.session_state.pending_navigation = requested
            if target_cursor is not None:
                st.session_state.pending_history_cursor = target_cursor
            st.session_state.last_route_slug = ROUTE_SLUGS[current]
            st.query_params["page"] = ROUTE_SLUGS[current]
        else:
            _activate_route(
                requested,
                push_history=target_cursor is None,
                history_cursor=target_cursor,
                update_query=not from_browser_history,
            )
    return st.session_state.shell_page


def route_picker_changed() -> None:
    target = st.session_state.get("global_route_picker", "Home")
    st.session_state.route_picker_page = target
    request_navigation(target)


def mark_decision_dirty(prefix: str) -> None:
    """Track an edited decision form until it is saved or explicitly discarded."""

    st.session_state.unsaved_decision_prefix = prefix


def clear_decision_state(prefix: str) -> None:
    for suffix in (
        "disposition", "reviewer", "comment", "modified", "mod_reason",
        "reject_reason", "duplicate",
    ):
        st.session_state.pop(f"{prefix}_{suffix}", None)
    if st.session_state.get("unsaved_decision_prefix") == prefix:
        st.session_state.pop("unsaved_decision_prefix", None)


def sign_out() -> None:
    is_oidc = oidc_user() is not None
    for key in list(st.session_state.keys()):
        st.session_state.pop(key, None)
    st.query_params.clear()
    if is_oidc:
        st.logout()
    st.rerun()


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
    user = authenticated_user() or {"tenant_id": "anonymous", "email": "anonymous"}
    tenant = str(user.get("tenant_id") or user.get("email") or "anonymous").strip().lower()
    root, _ = configured_data_root()
    return ReviewStore(root / safe_namespace(tenant) / "reviews")


def session_feedback_store() -> FeedbackStore:
    directory = session_store().directory.parent
    return FeedbackStore(directory / "reviewer_feedback.json")


def record_controlled_export(review_id: str, export_type: str) -> None:
    user = authenticated_user() or {}
    reviewer = str(user.get("name") or user.get("email") or "Not Available")
    session_store().record_export(review_id, export_type, reviewer)


def set_report(report: dict[str, Any]) -> None:
    refresh_review_state(report)
    session_store().create(report)
    st.session_state.report = report
    navigate("Executive Summary")
    st.session_state.selected_finding = report.get("findings", [{}])[0].get("finding_id", "") if report.get("findings") else ""


def current_report() -> dict[str, Any] | None:
    report = st.session_state.get("report")
    if not report:
        report = session_store().latest()
        if not report:
            return None
        st.session_state.report = report
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
    sizes = [len(uploaded.getvalue()) for uploaded in files]
    oversized = [uploaded.name for uploaded, size in zip(files, sizes) if size > MAX_FILE_BYTES]
    if oversized:
        raise ValueError("Each file must be 50 MB or smaller: " + ", ".join(oversized[:5]))
    if sum(sizes) > MAX_PACKAGE_BYTES:
        raise ValueError("The combined upload must be 200 MB or smaller.")
    return [
        {
            "name": uploaded.name,
            "content": base64.b64encode(uploaded.getvalue()).decode("ascii"),
            "encoding": "base64",
        }
        for uploaded in files
    ]


def csv_cell(value: Any) -> Any:
    """Prevent spreadsheet software from interpreting exported review text as a formula."""
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def write_csv_row(writer: Any, values: list[Any]) -> None:
    writer.writerow([csv_cell(value) for value in values])


def execute_review(package_name: str, files: list[dict[str, str]]) -> None:
    documents = parse_request_files({"files": files})
    report = review_package(documents, package_name, session_feedback_store().load())
    set_report(report)


def source_revision(text: str) -> str:
    for line in text.splitlines()[:25]:
        if line.lower().strip().startswith(("revision:", "revision,", "version:")):
            return line.split(":" if ":" in line else ",", 1)[1].strip()[:100] or "Not identified"
    return "Not identified"


def generation_sources(groups: list[tuple[str, list[Any]]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    files: list[Any] = []
    roles: list[str] = []
    for role, uploaded_files in groups:
        files.extend(uploaded_files)
        roles.extend([role] * len(uploaded_files))
    payloads = uploaded_payload(files)
    documents = parse_request_files({"files": payloads})
    sources = [
        {
            "name": document.name,
            "role": role,
            "revision": source_revision(document.text),
            "text": document.text,
            "extraction_status": document.extraction_status,
            "warnings": document.warnings,
        }
        for document, role in zip(documents, roles)
    ]
    return sources, payloads


def demo_generation_inputs() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, str]]]:
    records = [
        {
            "name": "VP-TEMPLATE-003.docx",
            "role": "Template",
            "revision": "3.1",
            "text": "\n".join((
                "1. Purpose", "2. Scope", "3. System Overview", "4. Roles and Responsibilities",
                "5. Validation Strategy", "6. Deliverables", "7. Risk Management",
                "8. Traceability", "9. Schedule and Milestones", "10. Acceptance Criteria",
                "11. Approval and Release",
            )),
            "extraction_status": "Complete",
            "warnings": [],
        },
        {
            "name": "SOP-CSV-005.txt",
            "role": "Procedure",
            "revision": "5.2",
            "text": (
                "Purpose: Define the risk-based lifecycle for computerized system validation. "
                "The validation owner shall maintain traceability from approved requirements and risks to executed tests. "
                "Quality Assurance shall independently review validation deliverables, deviations, and objective evidence. "
                "Unresolved critical or major deviations shall prevent release. Records shall be retained under the approved retention schedule."
            ),
            "extraction_status": "Complete",
            "warnings": [],
        },
        {
            "name": "NovaQMS-Validation-Plan.txt",
            "role": "Plan",
            "revision": "1.0",
            "text": (
                "NovaQMS version 2.4 supports regulated CAPA and nonconformance records. "
                "The scope includes corporate SSO, audit trails, electronic signatures, retention, and the MES disposition interface. "
                "The CSV Lead owns validation; Quality Systems owns the application; Quality Assurance provides independent approval. "
                "Deliverables include the requirements specification, risk assessment, configuration specification, IQ, OQ, traceability matrix, and validation summary report. "
                "Release requires approved deliverables, complete traceability, passed tests, and closed approval-blocking deviations."
            ),
            "extraction_status": "Complete",
            "warnings": [],
        },
    ]
    payloads = [
        {"name": item["name"], "content": item["text"], "encoding": "text"}
        for item in records
    ]
    metadata = {
        "document_type": "Validation Plan",
        "title": "NovaQMS 2.4 Validation Plan",
        "document_id": "VP-NOVAQMS-002",
        "revision": "0.1",
        "system": "NovaQMS 2.4",
        "owner": "CSV Lead",
        "purpose": "Define the risk-based validation strategy, responsibilities, deliverables, and acceptance criteria for NovaQMS 2.4.",
        "scope": "Corporate SSO, regulated quality workflows, audit trails, electronic signatures, retention, and the MES disposition interface.",
        "risk_classification": "GxP / High",
    }
    return metadata, records, payloads


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
        write_csv_row(writer,
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
        write_csv_row(writer,
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
        write_csv_row(writer,
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


def render_sidebar(report: dict[str, Any] | None, user: dict[str, str]) -> str:
    current = st.session_state.get("shell_page", "Home")
    role = user["role"]
    if current == "Review Administrator" and role not in {"Review Administrator", "Platform Administrator"}:
        navigate("Home")
        current = "Home"
    if current == "Platform Administrator" and role != "Platform Administrator":
        navigate("Home")
        current = "Home"

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
            request_navigation(page)
            st.rerun()

    nav_button("⌂   Home", "Home", "nav_home")
    st.sidebar.markdown('<div class="nav-section">Review workspace</div>', unsafe_allow_html=True)
    nav_button("♧   My Reviews", "My Reviews", "nav_reviews")
    nav_button("▤   All Documents", "All Documents", "nav_documents")
    nav_button("⇩   Upload Document   ＋", "Upload", "nav_upload")
    nav_button("✦   Document Generation", "Document Generation", "nav_generation")
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

    if role in {"Review Administrator", "Platform Administrator"}:
        st.sidebar.markdown('<div class="nav-section">Administration</div>', unsafe_allow_html=True)
        nav_button("⚙   Review Administrator", "Review Administrator", "nav_review_admin")
    if role == "Platform Administrator":
        nav_button("⚙   Platform Administrator", "Platform Administrator", "nav_platform_admin")

    if report:
        st.sidebar.markdown('<div class="nav-section">Active review</div>', unsafe_allow_html=True)
        nav_button("◎   Executive Summary", "Executive Summary", "nav_summary")
        nav_button("▤   Documents", "Documents", "nav_review_documents")
        nav_button("⇄   Traceability", "Traceability", "nav_traceability")
        nav_button("✎   Redlines", "Redlines", "nav_redlines")
        nav_button("✓   Review Decisions", "Review Decisions", "nav_decisions")
        st.sidebar.markdown(
            f'<div class="sidebar-note"><strong>{esc(report["package_name"])}</strong><br>{esc(report["review_id"])}<br>{esc(report["review_workflow"]["status"])}</div>',
            unsafe_allow_html=True,
        )
        with st.sidebar.expander("Export controlled outputs"):
            file_slug = slug(report["package_name"])
            review_id = report["review_id"]
            st.download_button("Review report", report_html(report), f"{file_slug}-review-report.html", "text/html", width="stretch", on_click=record_controlled_export, args=(review_id, "Review report"))
            st.download_button("Findings CSV", findings_csv(report["findings"]), f"{file_slug}-findings.csv", "text/csv", width="stretch", on_click=record_controlled_export, args=(review_id, "Findings CSV"))
            st.download_button("Decision log", decisions_csv(report), f"{file_slug}-decision-log.csv", "text/csv", width="stretch", on_click=record_controlled_export, args=(review_id, "Decision log"))
            st.download_button("Traceability", traceability_csv(report), f"{file_slug}-traceability.csv", "text/csv", width="stretch", on_click=record_controlled_export, args=(review_id, "Traceability CSV"))
            st.download_button("Structured JSON", json.dumps(report, indent=2), f"{file_slug}-{review_id}.json", "application/json", width="stretch", on_click=record_controlled_export, args=(review_id, "Structured JSON"))
    st.sidebar.markdown(
        '<div class="sidebar-note"><strong>Human review required</strong><br>AI findings remain advisory until a qualified reviewer records a disposition.</div>',
        unsafe_allow_html=True,
    )
    _, durability = configured_data_root()
    identity_status = "OIDC SSO" if user.get("auth_type") == "OIDC SSO" else "Unverified demo identity"
    st.sidebar.markdown(
        f'<div class="sidebar-note"><strong>Deployment controls</strong><br>{esc(identity_status)}<br>{esc(durability)}<br>Mode: {esc(deployment_mode().title())}</div>',
        unsafe_allow_html=True,
    )
    st.sidebar.markdown(
        f'<div class="signed-in-card"><strong>{esc(user["name"])}</strong><small>{esc(user["email"])}</small><small>{esc(role)} · {esc(user["auth_type"])}</small></div>',
        unsafe_allow_html=True,
    )
    if st.sidebar.button("Sign out", key="sign_out", width="stretch"):
        if st.session_state.get("unsaved_decision_prefix"):
            st.session_state.pending_navigation = "__sign_out__"
            st.rerun()
        else:
            sign_out()
    return current


def render_topbar(user: dict[str, str], report: dict[str, Any] | None, current_page: str) -> None:
    initials = "".join(part[0] for part in user["name"].split()[:2]).upper() or "U"
    open_actions = report.get("metrics", {}).get("open_findings", 0) if report else 0
    alert = f'<span class="top-alert">♧<b>{int(open_actions)}</b></span>' if open_actions else '<span>♧</span>'
    st.markdown(
        f"""
        <div class="app-topbar">
          <span class="menu-glyph" aria-hidden="true">◉</span>
          <div class="top-search"><span aria-hidden="true">↔</span><strong>{esc(current_page)}</strong><kbd>PAGE</kbd></div>
          <span></span>
          <div class="top-actions">{alert}<span>?</span><span class="top-avatar">{esc(initials)}</span><span class="top-profile"><strong>{esc(user['name'])}</strong><small>{esc(user['role'])}</small></span><span>⌄</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_route_bar(current_page: str, user: dict[str, str]) -> None:
    routes = available_routes(user)
    if st.session_state.get("route_picker_page") != current_page:
        st.session_state.global_route_picker = current_page
        st.session_state.route_picker_page = current_page
    history, cursor = _history_state(current_page)
    st.markdown('<div class="route-context">Always-visible page navigation</div>', unsafe_allow_html=True)
    page_col, back_col, forward_col, sidebar_col = st.columns([4.2, 1, 1, 1])
    page_col.selectbox(
        "Page navigation",
        routes,
        key="global_route_picker",
        on_change=route_picker_changed,
        label_visibility="collapsed",
    )
    if back_col.button("← Back", disabled=cursor <= 0, width="stretch", key="route_back"):
        request_navigation(history[cursor - 1], history_cursor=cursor - 1)
        st.rerun()
    if forward_col.button(
        "Forward →",
        disabled=cursor + 1 >= len(history),
        width="stretch",
        key="route_forward",
    ):
        request_navigation(history[cursor + 1], history_cursor=cursor + 1)
        st.rerun()
    sidebar_col.button("☰ Sidebar", width="stretch", key="sidebar_toggle")


def render_browser_history_bridge() -> None:
    """Ask Streamlit to rerun when the browser itself changes route history."""

    current = st.session_state.get("shell_page", "Home")
    history, cursor = _history_state(current)
    for page in available_routes(st.session_state.auth_user):
        slug = ROUTE_SLUGS[page]
        target_cursor: int | None = None
        if cursor > 0 and history[cursor - 1] == page:
            target_cursor = cursor - 1
        elif cursor + 1 < len(history) and history[cursor + 1] == page:
            target_cursor = cursor + 1
        if st.button(f"Browser route: {slug}", key=f"browser_route_{slug.replace('-', '_')}"):
            if request_navigation(page, history_cursor=target_cursor, update_query=False):
                st.session_state.browser_history_route_applied = page
            else:
                st.query_params["page"] = ROUTE_SLUGS[current]
            st.rerun()
    st.iframe(
        """
        <script>
          (() => {
            const host = window.parent;
            const toggle = host.document.querySelector(".st-key-sidebar_toggle button");
            if (toggle && !toggle.dataset.assureCsvSidebarToggle) {
              toggle.dataset.assureCsvSidebarToggle = "ready";
              toggle.addEventListener("click", () => {
                host.setTimeout(() => {
                  const nativeToggle = host.document.querySelector(
                    '[data-testid="stSidebarCollapseButton"] button',
                  );
                  if (nativeToggle) nativeToggle.click();
                }, 0);
              }, {capture: true});
            }
            const existing = host.__assureCsvRouteHistoryBridge;
            if (existing && existing.version === 5) return;
            if (existing && existing.listener) host.removeEventListener("popstate", existing.listener);
            if (existing && existing.shell && existing.shell !== host && existing.listener) {
              existing.shell.removeEventListener("popstate", existing.listener);
            }
            let shell = host;
            try {
              if (host.parent && host.parent.location.origin === host.location.origin) {
                shell = host.parent;
              }
            } catch (_) {
              shell = host;
            }
            const state = {version: 5, shell};
            const synchronize = () => {
              const source = new URLSearchParams(shell.location.search).has("page") ? shell : host;
              const slug = new URLSearchParams(source.location.search).get("page") || "home";
              host.setTimeout(() => {
                const key = slug.replaceAll("-", "_");
                const button = host.document.querySelector(`.st-key-browser_route_${key} button`);
                if (button) button.click();
              }, 50);
            };
            state.listener = synchronize;
            host.__assureCsvRouteHistoryBridge = state;
            host.addEventListener("popstate", synchronize);
            if (shell !== host) shell.addEventListener("popstate", synchronize);
            host.document.documentElement.dataset.assureCsvHistoryBridge = "ready";
          })();
        </script>
        """,
        height=1,
        tab_index=-1,
    )


def render_pending_navigation() -> None:
    destination = st.session_state.get("pending_navigation")
    if not destination:
        return
    destination_label = "signing out" if destination == "__sign_out__" else f"opening {destination}"
    st.warning(f"You have an unsaved reviewer decision. Discard it before {destination_label}.")
    discard, stay, _ = st.columns([1, 1, 4])
    if discard.button("Discard and continue", key="discard_for_navigation", width="stretch"):
        dirty_prefix = st.session_state.get("unsaved_decision_prefix")
        if dirty_prefix:
            clear_decision_state(dirty_prefix)
        destination = st.session_state.pop("pending_navigation", "Home")
        history_cursor = st.session_state.pop("pending_history_cursor", None)
        if destination == "__sign_out__":
            sign_out()
        else:
            _activate_route(
                destination,
                push_history=history_cursor is None,
                history_cursor=history_cursor,
            )
            st.rerun()
    if stay.button("Stay on page", key="stay_on_decision", width="stretch"):
        st.session_state.pop("pending_navigation", None)
        st.session_state.pop("pending_history_cursor", None)
        st.rerun()


def render_dashboard(report: dict[str, Any] | None, user: dict[str, str]) -> None:
    first_name = user["name"].split()[0] if user["name"].split() else "Reviewer"
    intro, actions = st.columns([1.45, .8], gap="large")
    with intro:
        st.markdown('<div class="dashboard-intro">', unsafe_allow_html=True)
        st.title(f"Welcome back, {first_name} 👋")
        st.markdown("<p>Here’s what’s happening with your reviews today.</p></div>", unsafe_allow_html=True)
    with actions:
        left, right = st.columns(2)
        if left.button("✦  Generate Document", type="primary", width="stretch"):
            navigate("Document Generation")
            st.rerun()
        if right.button("▷  New Review", width="stretch"):
            navigate("Upload")
            st.rerun()

    metrics = report.get("metrics", {}) if report else {}
    document_count = metrics.get("documents", 0)
    critical_count = metrics.get("severity_counts", {}).get("Critical", 0)
    open_count = metrics.get("open_findings", 0)
    decision_count = max(0, metrics.get("findings", 0) - open_count)
    if report:
        workflow = report["review_workflow"]
        review_rows = (
            f'<div class="review-row"><span class="file-chip word">R</span>'
            f'<span class="review-name"><strong>{esc(report["package_name"])}</strong><small>{esc(report["review_id"])}</small></span>'
            f'<span class="review-status review">{esc(workflow["status"])}</span><span>⋮</span></div>'
        )
    else:
        review_rows = '<div class="review-row"><span class="file-chip word">—</span><span class="review-name"><strong>No active review</strong><small>Upload a package or use the sample to begin.</small></span><span class="review-status not-started">Not Started</span><span>⋮</span></div>'
    st.markdown(
        f"""
        <section class="kpi-grid" aria-label="Review metrics">
          <article class="kpi-card"><div class="kpi-head"><span class="kpi-icon blue">▤</span><span class="kpi-copy"><span>Documents in Current Review</span><strong>{document_count}</strong></span><span class="kpi-menu">⋮</span></div><p class="kpi-note">Session-scoped controlled record</p></article>
          <article class="kpi-card"><div class="kpi-head"><span class="kpi-icon red">!</span><span class="kpi-copy"><span>Critical Findings</span><strong>{critical_count}</strong></span><span class="kpi-menu">⋮</span></div><p class="kpi-note">Current independent review</p></article>
          <article class="kpi-card"><div class="kpi-head"><span class="kpi-icon green">✓</span><span class="kpi-copy"><span>Human Decisions</span><strong>{decision_count}</strong></span><span class="kpi-menu">⋮</span></div><p class="kpi-note"><b>{open_count}</b> open reviewer actions</p></article>
        </section>
        <section class="reviews-panel">
          <div class="reviews-head"><strong>My Reviews</strong></div>
          <div class="review-tabs"><span class="active">Current session ({1 if report else 0})</span></div>
          <div class="review-list">{review_rows}</div>
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
        navigate("Executive Summary")
        st.rerun()


def render_workspace_header(title: str, copy: str) -> None:
    st.markdown('<div class="eyebrow">CSVQUALREVIEWER WORKSPACE</div>', unsafe_allow_html=True)
    st.title(title)
    st.markdown(f'<p class="hero-copy">{esc(copy)}</p>', unsafe_allow_html=True)


def render_no_review(copy: str) -> None:
    st.info(copy)
    if st.button("Start a review", type="primary", key=f"empty_{slug(copy)}"):
        navigate("Upload")
        st.rerun()


def render_my_reviews(report: dict[str, Any] | None) -> None:
    render_workspace_header("My Reviews", "Reopen assigned work and continue from the current human-review state.")
    if not report:
        render_no_review("No reviews are assigned in this demo session yet.")
        return
    workflow = report["review_workflow"]
    st.dataframe(
        pd.DataFrame(
            [{
                "Review": report["package_name"],
                "Run ID": report["review_id"],
                "Status": workflow["status"],
                "Readiness": workflow["package_readiness"],
                "Findings": report["metrics"]["findings"],
                "Open actions": report["metrics"]["open_findings"],
            }]
        ),
        hide_index=True,
        width="stretch",
    )
    if st.button("Open review workspace", type="primary"):
        navigate("Executive Summary")
        st.rerun()


def render_all_documents(report: dict[str, Any] | None) -> None:
    render_workspace_header("All Documents", "Browse the source documents in reviews available to this signed-in session.")
    if not report:
        render_no_review("No validation documents are available. Upload a package to build the document inventory.")
        return
    rows = []
    for item in report.get("document_summaries", []):
        rows.append({
            "Document": item["document_name"],
            "Type": item["document_type"],
            "Revision": item["revision"],
            "Extraction": item.get("extraction_status", "Not Available"),
            "Findings": item["finding_count"],
            "Open": item["open_count"],
            "Highest unresolved": item["highest_unresolved_severity"],
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=480)
    if st.button("Open document review details", type="primary"):
        navigate("Documents")
        st.rerun()


def grounded_chat_answer(question: str, report: dict[str, Any]) -> str:
    lowered = question.lower()
    findings = report.get("findings", [])
    for finding in findings:
        if finding["finding_id"].lower() in lowered:
            return (
                f"{finding['finding_id']} is a {finding['severity']} {finding['category']} finding in "
                f"{finding['document']} ({finding['section']}). Current human-review status: {finding['status']}. "
                f"Evidence: {finding['evidence']}"
            )
    for severity in SEVERITIES:
        if severity.lower() in lowered:
            matches = [item for item in findings if item["severity"] == severity]
            ids = ", ".join(item["finding_id"] for item in matches) or "none"
            return f"This review has {len(matches)} {severity.lower()} findings: {ids}."
    if "document" in lowered:
        names = [item["document_name"] for item in report.get("document_summaries", [])]
        return f"The active review contains {len(names)} documents: {', '.join(names)}."
    if "open" in lowered or "status" in lowered:
        workflow = report["review_workflow"]
        return (
            f"The review is {workflow['status']} with {report['metrics']['open_findings']} open actions. "
            f"Package readiness is {workflow['package_readiness']}."
        )
    return (
        f"The active package is {report['package_name']} with {report['metrics']['documents']} documents and "
        f"{report['metrics']['findings']} findings. Ask about a finding ID, severity, document, or review status."
    )


def render_chat(report: dict[str, Any] | None) -> None:
    render_workspace_header("Chat with CSVQualReviewer", "Ask grounded questions about the active package. Answers use only the current review record.")
    if not report:
        render_no_review("Start or reopen a review before asking document-grounded questions.")
        return
    messages = st.session_state.setdefault(
        "chat_messages",
        [{"role": "assistant", "content": f"I’m grounded in {report['package_name']}. Ask about findings, documents, severity, or status."}],
    )
    for message in messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])
    if prompt := st.chat_input("Ask about the active review"):
        messages.append({"role": "user", "content": prompt[:1000]})
        messages.append({"role": "assistant", "content": grounded_chat_answer(prompt, report)})
        st.rerun()
    st.caption("Grounded review assistant · No external sources or model-generated approval decisions")


def render_history(report: dict[str, Any] | None) -> None:
    render_workspace_header("Run History", "Inspect review runs and reopen their original decision records.")
    if not report:
        render_no_review("No review runs have been created in this demo session.")
        return
    events = report.get("audit_events", [])
    st.dataframe(
        pd.DataFrame([{
            "Run ID": report["review_id"],
            "Package": report["package_name"],
            "Status": report["review_workflow"]["status"],
            "Documents": report["metrics"]["documents"],
            "Findings": report["metrics"]["findings"],
            "Audit events": len(events),
        }]),
        hide_index=True,
        width="stretch",
    )
    if events:
        with st.expander("Audit trail"):
            st.dataframe(pd.DataFrame(events), hide_index=True, width="stretch")
    if st.button("Reopen selected run", type="primary"):
        navigate("Executive Summary")
        st.rerun()


def render_analytics(report: dict[str, Any] | None) -> None:
    render_workspace_header("Feedback & Analytics", "Monitor review workload, disposition coverage, severity, and traceability quality.")
    if not report:
        render_no_review("Analytics will populate after the first validation package is reviewed.")
        return
    metrics = report["metrics"]
    cols = st.columns(4)
    cols[0].metric("Findings", metrics["findings"])
    cols[1].metric("Open actions", metrics["open_findings"])
    cols[2].metric("Documents", metrics["documents"])
    cols[3].metric("Human decisions", metrics["findings"] - metrics["open_findings"])
    left, right = st.columns(2)
    left.markdown("#### Severity distribution")
    left.bar_chart(pd.DataFrame.from_dict(metrics["severity_counts"], orient="index", columns=["Findings"]))
    right.markdown("#### Human disposition coverage")
    right.bar_chart(pd.DataFrame.from_dict(metrics["status_counts"], orient="index", columns=["Findings"]))
    learning = report.get("feedback_learning", {})
    st.info(
        f"Controlled reviewer learning: {learning.get('available_precedents', 0)} prior decision examples were available to this run. "
        "Current approved regulations and procedures always take precedence; conflicting feedback is escalated, never resolved automatically."
    )


REFERENCE_ROWS = [
    {"Name": "Validation Plan Template", "Type": "Template", "Revision": "3.1", "Status": "Approved", "Owner": "Quality Systems"},
    {"Name": "Computerized Systems Validation SOP", "Type": "SOP", "Revision": "5.2", "Status": "Effective", "Owner": "Quality Assurance"},
    {"Name": "Approved IQ/OQ Example", "Type": "Golden Report", "Revision": "2.0", "Status": "Approved", "Owner": "Validation CoE"},
    {"Name": "Data Integrity Review Guidance", "Type": "Guidance", "Revision": "1.4", "Status": "Effective", "Owner": "Compliance"},
]


def render_reference_library(page: str) -> None:
    type_map = {"Templates": "Template", "SOPs": "SOP", "Golden Reports": "Golden Report", "Guidance Documents": "Guidance"}
    rows = REFERENCE_ROWS if page == "All References" else [item for item in REFERENCE_ROWS if item["Type"] == type_map[page]]
    render_workspace_header(page, "Controlled reference content with revision, lifecycle status, and accountable ownership.")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("Demo reference inventory. Connect validated persistence before using this library as a production control.")


def render_review_admin(user: dict[str, str]) -> None:
    render_workspace_header("Review Administrator", "Manage organization-scoped users and review access.")
    if user["role"] not in {"Review Administrator", "Platform Administrator"}:
        st.markdown('<div class="access-denied"><strong>Access denied</strong><br>This page requires Review Administrator access.</div>', unsafe_allow_html=True)
        return
    users = st.session_state.setdefault("demo_users", [
        {"Name": user["name"], "Email": user["email"], "Role": user["role"], "Status": "Active"},
        {"Name": "Jane Cooper", "Email": "jane.cooper@example.com", "Role": "Reviewer", "Status": "Active"},
    ])
    st.dataframe(pd.DataFrame(users), hide_index=True, width="stretch")
    with st.expander("Add demo user"):
        with st.form("add_demo_user"):
            name = st.text_input("User name")
            email = st.text_input("User email")
            role = st.selectbox("User role", ROLES)
            add = st.form_submit_button("Add user", type="primary")
        if add:
            if not name.strip() or "@" not in email:
                st.error("Enter a name and valid email address.")
            elif any(item["Email"].lower() == email.strip().lower() for item in users):
                st.error("That user already exists.")
            else:
                users.append({"Name": name.strip(), "Email": email.strip().lower(), "Role": role, "Status": "Invited"})
                st.success(f"{email.strip().lower()} added to the demo directory.")
                st.rerun()
    st.caption("Demo directory only. Production user provisioning must be connected to the organization identity provider and audit store.")


def render_platform_admin(user: dict[str, str]) -> None:
    render_workspace_header("Platform Administrator", "Manage platform-wide controls and service configuration.")
    if user["role"] != "Platform Administrator":
        st.markdown('<div class="access-denied"><strong>Access denied</strong><br>This page requires Platform Administrator access.</div>', unsafe_allow_html=True)
        return
    cols = st.columns(3)
    cols[0].metric("Organizations", 1)
    cols[1].metric("Platform health", "Healthy")
    cols[2].metric("Isolation checks", "Passing")
    settings = st.session_state.get("platform_settings_data", {})
    with st.form("platform_settings_form"):
        retention_options = ("7 years", "10 years", "Indefinite")
        region_options = ("United States", "European Union")
        retention = st.selectbox("Audit retention", retention_options, index=retention_options.index(settings.get("retention", "7 years")))
        region = st.selectbox("Data region", region_options, index=region_options.index(settings.get("region", "United States")))
        require_sso = st.checkbox("Require enterprise SSO", value=settings.get("require_sso", oidc_configured()))
        saved = st.form_submit_button("Save demo settings", type="primary")
    if saved:
        st.session_state.platform_settings_data = {"retention": retention, "region": region, "require_sso": require_sso}
        st.success("Demo platform settings saved for this session.")
    st.caption("Production enforcement requires validated identity, persistence, tenant isolation, monitoring, and change control services.")


def render_document_generation(user: dict[str, str]) -> None:
    render_workspace_header(
        "Document Generation",
        "Create a source-grounded controlled draft from an approved template, procedures, plans, and references—then send it to the independent Review Agent.",
    )
    st.markdown(
        '<div class="notice"><strong>Drafting boundary</strong><span>Uploaded documents provide structure and evidence only. CSVQualReviewer does not execute embedded instructions, approve content, publish records, or release documents.</span></div>',
        unsafe_allow_html=True,
    )
    draft = st.session_state.get("generation_draft")
    if not draft:
        with st.form("document_generation_form"):
            st.markdown("### 1 · Define the controlled document")
            first, second = st.columns(2)
            document_type = first.selectbox("Document type", tuple(DOCUMENT_BLUEPRINTS))
            title = second.text_input("Document title", placeholder="e.g., NovaQMS 2.4 Validation Plan")
            first, second, third = st.columns(3)
            document_id = first.text_input("Document ID", value="DRAFT")
            revision = second.text_input("Draft revision", value="0.1")
            risk = third.selectbox("Risk classification", ("Not classified", "GxP / High", "GxP / Medium", "Business / Low"))
            first, second, third = st.columns(3)
            system = first.text_input("System / project")
            owner = second.text_input("Document owner")
            author = third.text_input("Author", value=user["name"])
            purpose = st.text_area("Purpose", height=90, placeholder="State why this controlled document is being created.")
            scope = st.text_area("Scope", height=90, placeholder="State systems, processes, sites, interfaces, and exclusions.")

            st.markdown("### 2 · Add the controlled source set")
            st.caption("50 MB per file, 200 MB combined. Exact file names, roles, revisions, extraction status, and section citations are retained in the draft record.")
            template = st.file_uploader("Approved template · DOCX (optional)", type=["docx"], key="generation_template")
            procedures = st.file_uploader(
                "Procedures / SOPs",
                type=["pdf", "docx", "xlsx", "xlsm", "csv", "tsv", "txt", "md", "json", "xml", "html", "htm", "yaml", "yml"],
                accept_multiple_files=True,
                key="generation_procedures",
            )
            plans = st.file_uploader(
                "Plans / project inputs",
                type=["pdf", "docx", "xlsx", "xlsm", "csv", "tsv", "txt", "md", "json", "xml", "html", "htm", "yaml", "yml"],
                accept_multiple_files=True,
                key="generation_plans",
            )
            references = st.file_uploader(
                "Other references",
                type=["pdf", "docx", "xlsx", "xlsm", "csv", "tsv", "txt", "md", "json", "xml", "html", "htm", "yaml", "yml"],
                accept_multiple_files=True,
                key="generation_references",
            )
            generate = st.form_submit_button("Generate controlled draft", type="primary", width="stretch")

        demo, _ = st.columns([1, 2])
        use_demo = demo.button("Use controlled demo sources", width="stretch")
        if generate:
            if not title.strip():
                st.error("Enter a document title.")
            else:
                try:
                    groups = [
                        ("Template", [template] if template else []),
                        ("Procedure", list(procedures or [])),
                        ("Plan", list(plans or [])),
                        ("Reference", list(references or [])),
                    ]
                    sources, payloads = generation_sources(groups) if any(files for _, files in groups) else ([], [])
                    metadata = {
                        "document_type": document_type,
                        "title": title,
                        "document_id": document_id,
                        "revision": revision,
                        "system": system,
                        "owner": owner,
                        "author": author,
                        "purpose": purpose,
                        "scope": scope,
                        "risk_classification": risk,
                    }
                    st.session_state.generation_draft = generate_document(metadata, sources)
                    st.session_state.generation_source_payloads = payloads
                    st.session_state.generation_template_bytes = template.getvalue() if template else None
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.rerun()
        if use_demo:
            metadata, sources, payloads = demo_generation_inputs()
            metadata["author"] = user["name"]
            st.session_state.generation_draft = generate_document(metadata, sources)
            st.session_state.generation_source_payloads = payloads
            st.session_state.generation_template_bytes = None
            st.rerun()
        return

    metadata = draft["metadata"]
    reviewed_count = sum(section["status"] == "Human Reviewed" for section in draft["sections"])
    metrics = st.columns(4)
    metrics[0].metric("Draft status", draft["status"])
    metrics[1].metric("Sections reviewed", f"{reviewed_count} / {len(draft['sections'])}")
    metrics[2].metric("Controlled sources", len(draft["sources"]))
    metrics[3].metric("Revision events", len(draft["revision_history"]))
    st.progress(reviewed_count / max(1, len(draft["sections"])), text="Human author-review progress")

    editor, context = st.columns([1.45, .7], gap="large")
    with editor:
        st.markdown("### 3 · Review and edit each section")
        section_id = st.selectbox(
            "Draft section",
            [section["section_id"] for section in draft["sections"]],
            format_func=lambda value: next(
                f"{item['number']}. {item['title']} · {item['status']}"
                for item in draft["sections"] if item["section_id"] == value
            ),
        )
        selected = next(section for section in draft["sections"] if section["section_id"] == section_id)
        content = st.text_area(
            "Section content",
            value=selected["content"],
            height=390,
            key=f"generation_editor_{section_id}_{len(draft['revision_history'])}",
        )
        st.caption("Section provenance: " + (", ".join(selected["source_ids"]) or "No direct source match — author confirmation required"))
        save, review, reopen = st.columns(3)
        if save.button("Save section revision", width="stretch"):
            try:
                st.session_state.generation_draft = update_section(draft, section_id, content, user["name"], reviewed=False)
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.rerun()
        if review.button("Mark human reviewed", type="primary", width="stretch"):
            try:
                st.session_state.generation_draft = update_section(draft, section_id, content, user["name"], reviewed=True)
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.rerun()
        if reopen.button("Reopen section", width="stretch"):
            st.session_state.generation_draft = update_section(draft, section_id, content, user["name"], reviewed=False)
            st.rerun()

    with context:
        st.markdown("### Draft controls")
        st.write(f"**{metadata['title']}**")
        st.caption(f"{metadata['document_type']} · {metadata['document_id']} · revision {metadata['revision']}")
        if draft["assumptions"]:
            with st.expander(f"Open author actions ({len(draft['assumptions'])})", expanded=True):
                for assumption in draft["assumptions"]:
                    st.write("• " + assumption)
        try:
            generated_docx = build_docx(draft, st.session_state.get("generation_template_bytes"))
        except Exception as exc:
            st.error(f"The Word draft could not be assembled: {exc}")
        else:
            st.download_button(
                "Download controlled Word draft",
                generated_docx,
                f"{slug(metadata['title'])}-{metadata['revision']}.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                type="primary",
                width="stretch",
            )
        st.download_button(
            "Download generation trace JSON",
            json.dumps(draft, indent=2),
            f"{slug(metadata['title'])}-{draft['draft_id']}.json",
            "application/json",
            width="stretch",
        )
        if st.button("Send draft to Review Agent", width="stretch"):
            primary = {
                "name": f"{slug(metadata['title'])}-generated-draft.md",
                "content": document_text(draft),
                "encoding": "text",
            }
            supporting = list(st.session_state.get("generation_source_payloads", []))[:20]
            with st.spinner("Starting an independent review of the generated draft…"):
                execute_review(f"Independent review · {metadata['title']}", [primary, *supporting])
            st.rerun()
        if reviewed_count < len(draft["sections"]):
            st.warning("The draft can be independently reviewed now, but author review is not complete.")
        if st.button("Start a new draft", width="stretch"):
            for key in [item for item in st.session_state.keys() if item.startswith("generation_")]:
                st.session_state.pop(key, None)
            st.rerun()

    st.markdown("### Source and generation provenance")
    if draft["sources"]:
        st.dataframe(pd.DataFrame(draft["sources"]), hide_index=True, width="stretch")
    else:
        st.info("No external controlled sources were supplied. Every section requiring source confirmation is identified in the draft.")
    with st.expander("Revision history"):
        st.dataframe(pd.DataFrame(draft["revision_history"]), hide_index=True, width="stretch")


def render_module_shell(page: str, report: dict[str, Any] | None, user: dict[str, str]) -> None:
    if page == "My Reviews":
        render_my_reviews(report)
    elif page == "All Documents":
        render_all_documents(report)
    elif page == "Chat":
        render_chat(report)
    elif page == "Run History":
        render_history(report)
    elif page == "Feedback & Analytics":
        render_analytics(report)
    elif page == "Document Generation":
        render_document_generation(user)
    elif page in {"All References", "Templates", "SOPs", "Golden Reports", "Guidance Documents"}:
        render_reference_library(page)
    elif page == "Review Administrator":
        render_review_admin(user)
    elif page == "Platform Administrator":
        render_platform_admin(user)
    elif page in {"Executive Summary", "Documents", "Findings", "Traceability", "Redlines", "Review Decisions"}:
        render_workspace_header(page, "This destination requires an active review package.")
        render_no_review("Upload a validation package before opening review-specific content.")
    else:
        render_workspace_header("Page not found", "The requested destination is not available to this account.")


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
    severity_counts = metrics.get("severity_counts", {})
    status_counts = metrics.get("status_counts", {})
    first_row = st.columns(6)
    first_row[0].metric("Documents", metrics.get("documents", 0), help="Documents reviewed in this run")
    first_row[1].metric("Total findings", metrics.get("findings", 0))
    first_row[2].metric("Critical", severity_counts.get("Critical", 0))
    first_row[3].metric("Major", severity_counts.get("Major", 0))
    first_row[4].metric("Minor", severity_counts.get("Minor", 0))
    first_row[5].metric("Observations", severity_counts.get("Observation", 0))
    second_row = st.columns(5)
    second_row[0].metric("Open actions", metrics.get("open_findings", 0))
    second_row[1].metric("Accepted", status_counts.get("Accepted", 0))
    second_row[2].metric("Rejected", status_counts.get("Rejected", 0))
    second_row[3].metric("Needs SME", status_counts.get("Needs SME Review", 0))
    second_row[4].metric("Overall status", workflow.get("status", "Not Available"))

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


def clear_finding_filters() -> None:
    for key in (
        "finding_search", "severity_filter", "category_filter", "document_filter",
        "status_filter", "confidence_filter", "finding_sort", "findings_page",
    ):
        st.session_state.pop(key, None)


def filtered_findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    findings = report["findings"]
    query = st.text_input("Search findings", placeholder="ID, title, text, document, category, or section", key="finding_search").strip().lower()
    f1, f2, f3, f4, f5 = st.columns(5)
    severities = f1.multiselect("Severity", SEVERITIES, default=[], key="severity_filter")
    categories = f2.multiselect("Category", sorted({item["category"] for item in findings}), default=[], key="category_filter")
    documents = f3.multiselect("Document", sorted({reference["document_name"] for item in findings for reference in item.get("affected_documents", [])}), default=[], key="document_filter")
    statuses = f4.multiselect("Status", FINDING_STATUSES, default=[], key="status_filter")
    confidence = f5.multiselect("Confidence", ("High (≥90%)", "Medium (70–89%)", "Low (<70%)", "Not Available"), default=[], key="confidence_filter")
    sort_col, clear_col = st.columns([4, 1])
    sort_choice = sort_col.selectbox("Sort findings", ("Unresolved risk", "Severity", "Document", "Finding ID", "Confidence", "Status", "Newest", "Oldest"), key="finding_sort")
    clear_col.markdown("<div style='height:1.78rem'></div>", unsafe_allow_html=True)
    clear_col.button("Clear filters", on_click=clear_finding_filters, width="stretch")

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
    disposition = st.selectbox(
        "Disposition", DECISION_OPTIONS, index=DECISION_OPTIONS.index(current),
        key=f"{prefix}_disposition", on_change=mark_decision_dirty, args=(prefix,),
    )
    reviewer_default = finding.get("reviewer") if finding.get("reviewer") not in {"", "Not Available"} else st.session_state.get("reviewer_name", "")
    reviewer = st.text_input(
        "Reviewer name / role", value=reviewer_default, key=f"{prefix}_reviewer",
        on_change=mark_decision_dirty, args=(prefix,),
    )
    if reviewer:
        st.session_state.reviewer_name = reviewer
    comment = st.text_area(
        "Reviewer comment" + (" (required)" if disposition in {"Rejected", "Needs SME Review"} else ""),
        value=finding.get("reviewer_comment", ""),
        placeholder="Record the rationale, supporting evidence, context, or SME question.",
        key=f"{prefix}_comment",
        on_change=mark_decision_dirty,
        args=(prefix,),
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
            on_change=mark_decision_dirty,
            args=(prefix,),
        )
        modification_reason = st.selectbox(
            "Modification reason",
            ("", "Technical Accuracy", "Procedure Alignment", "Regulatory Interpretation", "Clarity", "Business Context", "Scope Correction", "Other"),
            key=f"{prefix}_mod_reason",
            on_change=mark_decision_dirty,
            args=(prefix,),
        )
    if disposition == "Rejected":
        rejection_reason = st.selectbox(
            "Structured rejection reason",
            ("", "Not Applicable", "Incorrect Interpretation", "Requirement Already Addressed", "Duplicate Finding", "Insufficient Evidence", "Incorrect Severity", "Incorrect Recommendation", "Other"),
            key=f"{prefix}_reject_reason",
            on_change=mark_decision_dirty,
            args=(prefix,),
        )
        duplicate_of = st.text_input(
            "Duplicate of finding (optional)", placeholder="e.g., F-002", key=f"{prefix}_duplicate",
            on_change=mark_decision_dirty, args=(prefix,),
        )
    if st.session_state.get("unsaved_decision_prefix") == prefix:
        st.warning("You have unsaved changes in this reviewer decision. Save or discard them before navigating away.")
        if st.button("Discard unsaved changes", key=f"{prefix}_discard"):
            clear_decision_state(prefix)
            st.rerun()
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
            clear_decision_state(prefix)
            st.session_state.report = updated
            feedback_mapping = {
                "Accepted": "Accept",
                "Rejected": "Reject",
                "Modified": "Accept with Modification",
            }
            if disposition in feedback_mapping:
                try:
                    session_feedback_store().add(
                        {
                            "review_id": report["review_id"],
                            "finding": finding,
                            "reviewer_decision": feedback_mapping[disposition],
                            "reviewer_rationale": comment or modification_reason,
                            "reviewer_name_role": reviewer,
                            "preferred_wording": modified,
                            "final_resolution": disposition,
                        }
                    )
                except ValueError:
                    # The decision record is authoritative; optional learning
                    # feedback must never invalidate a saved disposition.
                    pass
            st.success(f"{finding['finding_id']} saved as {disposition}.")
            st.rerun()


def render_finding_detail(report: dict[str, Any], finding: dict[str, Any], prefix: str = "finding") -> None:
    with st.container(border=True):
        st.markdown(f'<div class="finding-head">{finding_badges(finding)}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="finding-title">{esc(finding["title"])}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="finding-meta">{esc(finding["document"])} · {esc(finding["section"])}</div>', unsafe_allow_html=True)
        score = finding.get("confidence_score")
        if score is not None and score < 70:
            st.warning(
                f"Human Verification Recommended — AI confidence is {score}%. Confirm the evidence, applicability, and review basis before disposition."
            )
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
    with st.expander("Bulk reviewer actions"):
        st.caption("Bulk acceptance, rejection, modification, and resolution are intentionally disabled. Only safe triage actions are available.")
        bulk_ids = st.multiselect("Selected findings", selected_ids, key="bulk_finding_ids")
        if bulk_ids:
            st.download_button(
                "Export selected findings",
                findings_csv([finding for finding in findings if finding["finding_id"] in bulk_ids]),
                f"{slug(report['package_name'])}-selected-findings.csv",
                "text/csv",
                width="stretch",
                on_click=record_controlled_export,
                args=(report["review_id"], "Selected findings CSV"),
            )
        bulk_action = st.selectbox("Safe bulk action", ("Select an action", "Deferred", "Needs SME Review"), key="bulk_action")
        bulk_reviewer = st.text_input("Reviewer name / role", value=st.session_state.get("reviewer_name", ""), key="bulk_reviewer")
        bulk_comment = st.text_area(
            "Shared rationale / SME question",
            placeholder="Required for the audit trail and for SME escalation.",
            key="bulk_comment",
        )
        bulk_confirm = st.checkbox(
            f"I confirm this action applies to all {len(bulk_ids)} selected findings.",
            key="bulk_confirm",
            disabled=not bulk_ids,
        )
        if st.button(
            "Apply safe bulk action",
            type="primary",
            disabled=not bulk_ids or bulk_action == "Select an action" or not bulk_confirm,
            key="bulk_apply",
        ):
            if not bulk_reviewer.strip():
                st.error("Enter the accountable reviewer name or role.")
            elif not bulk_comment.strip():
                st.error("Record a shared rationale or SME question for the bulk action.")
            else:
                updated_report = session_store().load(report["review_id"])
                errors: list[str] = []
                for finding_id in bulk_ids:
                    stored = next(item for item in updated_report["findings"] if item["finding_id"] == finding_id)
                    try:
                        updated_report, _ = session_store().decide(
                            report["review_id"],
                            finding_id,
                            {
                                "disposition": bulk_action,
                                "reviewer": bulk_reviewer,
                                "reviewer_comment": bulk_comment,
                                "expected_updated_at": stored.get("updated_at"),
                            },
                        )
                    except ValueError as exc:
                        errors.append(f"{finding_id}: {exc}")
                st.session_state.report = updated_report
                if errors:
                    st.error("Some actions were not saved: " + "; ".join(errors))
                else:
                    st.success(f"{len(bulk_ids)} findings updated to {bulk_action}.")
                    st.session_state.bulk_finding_ids = []
                    st.session_state.bulk_confirm = False
                    st.rerun()
    current = st.session_state.get("selected_finding")
    if current not in selected_ids:
        current = selected_ids[0]
    has_unsaved_decision = bool(st.session_state.get("unsaved_decision_prefix"))
    selected_id = st.selectbox(
        "Focused finding",
        selected_ids,
        index=selected_ids.index(current),
        key="focused_finding",
        disabled=has_unsaved_decision,
        help="Save or discard the current reviewer decision before changing findings."
        if has_unsaved_decision else None,
    )
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
                if st.button("Open document findings", key=f"open_document_{slug(summary['document_name'])}", width="stretch"):
                    st.session_state.document_filter = [summary["document_name"]]
                    related = [
                        finding["finding_id"] for finding in report["findings"]
                        if summary["document_name"] in {
                            item.get("document_name") for item in finding.get("affected_documents", [])
                        }
                    ]
                    if related:
                        st.session_state.selected_finding = related[0]
                    navigate("Findings")
                    st.rerun()


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
    st.download_button(
        "Download traceability CSV",
        traceability_csv(report),
        f"{slug(report['package_name'])}-traceability.csv",
        "text/csv",
        on_click=record_controlled_export,
        args=(report["review_id"], "Traceability CSV"),
    )


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
        on_click=record_controlled_export,
        args=(report["review_id"], f"Redlined document: {document['document_name']}"),
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
        has_unsaved_decision = bool(st.session_state.get("unsaved_decision_prefix"))
        selected = st.selectbox(
            "Decision detail",
            [finding["finding_id"] for finding in decided],
            disabled=has_unsaved_decision,
            help="Save or discard the current reviewer decision before changing findings."
            if has_unsaved_decision else None,
        )
        render_finding_detail(report, next(finding for finding in decided if finding["finding_id"] == selected), f"decision_{selected}")
    else:
        st.info("No reviewer decisions match the selected status filters. Open Findings to record a disposition.")
    st.download_button(
        "Download reviewer decision log",
        decisions_csv(report),
        f"{slug(report['package_name'])}-decision-log.csv",
        "text/csv",
        on_click=record_controlled_export,
        args=(report["review_id"], "Decision log"),
    )


user = authenticated_user()
if user is None:
    render_login()
    st.stop()

page = sync_route_from_query(user)
report = current_report()
page = render_sidebar(report, user)
render_topbar(user, report, page)
render_route_bar(page, user)
render_browser_history_bridge()
render_pending_navigation()

if page == "Home":
    render_dashboard(report, user)
elif page == "Upload":
    render_upload()
elif report is None:
    render_module_shell(page, report, user)
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
    render_module_shell(page, report, user)
