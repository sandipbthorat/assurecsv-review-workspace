"use strict";

const {
  SEVERITIES,
  STATUSES,
  normalizeFinding,
  confidenceBand,
  calculateMetrics,
  filterFindings,
  sortFindings,
  acceptedChangeForFinding,
} = window.CSVQualReviewerUtils;

const state = {
  files: [],
  packageName: "",
  documentType: "",
  report: null,
  view: "home",
  dashboardTab: "assigned",
  selectedFindingId: "",
  selectedRedline: 0,
  redlineMode: sessionStorage.getItem("csvqualreviewer-redline-mode") || "split",
  filters: { query: "", severity: "All", category: "All", document: "All", status: "All", confidence: "All" },
  sort: "risk",
  page: 1,
  pageSize: 25,
  selectedFindings: new Set(),
  documentSort: "risk",
  decisionStatus: "All",
  decisionDraft: null,
  unsaved: false,
  saving: false,
};

const workspace = document.querySelector("#workspace");
const fileInput = document.querySelector("#file-input");
const exportButton = document.querySelector("#export-menu");
const exportPopover = document.querySelector("#export-popover");
const toast = document.querySelector("#toast");
const drawer = document.querySelector("#finding-drawer");
const drawerScrim = document.querySelector("#drawer-scrim");
const unsavedDialog = document.querySelector("#unsaved-dialog");

const e = (value) => String(value ?? "").replace(/[&<>'"]/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
}[character]));
const slug = (value) => String(value ?? "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
const short = (value, length = 180) => String(value ?? "").length > length ? `${String(value).slice(0, length)}…` : String(value ?? "");
const bytes = (size) => size < 1024 ? `${size} B` : size < 1024 ** 2 ? `${(size / 1024).toFixed(1)} KB` : `${(size / 1024 ** 2).toFixed(1)} MB`;
const timestamp = (value) => value && value !== "Not Available" ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "Not Available";
const plural = (count, singular, multiple = `${singular}s`) => `${count} ${count === 1 ? singular : multiple}`;

function showToast(message, type = "success") {
  toast.textContent = message;
  toast.className = `toast ${type}`;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.add("hidden"), 4200);
}

function routeFor(view = state.view, findingId = state.selectedFindingId) {
  if (view === "home") return "#/home";
  if (view === "upload" || !state.report) return "#/upload";
  const detail = findingId ? `/${encodeURIComponent(findingId)}` : "";
  return `#/review/${encodeURIComponent(state.report.review_id)}/${view}${detail}`;
}

function parseRoute() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  if (parts[0] === "home") return { reviewId: "", view: "home", findingId: "" };
  if (["upload", "chat", "history", "feedback", "references", "templates", "sops", "golden", "guidance", "org-admin", "platform-admin"].includes(parts[0])) {
    return { reviewId: "", view: parts[0], findingId: "" };
  }
  if (parts[0] === "review" && parts[2]) {
    return { reviewId: parts[1], view: parts[2], findingId: parts[3] || "" };
  }
  return { reviewId: "", view: "overview", findingId: "" };
}

function setRoute(replace = false) {
  const method = replace ? "replaceState" : "pushState";
  history[method]({}, "", routeFor());
}

async function confirmUnsaved() {
  if (!state.unsaved) return true;
  return new Promise((resolve) => {
    unsavedDialog.showModal();
    const finish = (allowed) => {
      unsavedDialog.close();
      resolve(allowed);
    };
    document.querySelector("#unsaved-save").onclick = async () => {
      const saved = await saveDecision();
      if (saved) finish(true);
    };
    document.querySelector("#unsaved-discard").onclick = () => {
      state.unsaved = false;
      finish(true);
    };
    document.querySelector("#unsaved-cancel").onclick = () => finish(false);
  });
}

async function navigate(view, findingId = "") {
  if (!await confirmUnsaved()) return;
  if (view === "upload") return beginNewReview();
  const reportViews = ["overview", "findings", "documents", "traceability", "redlines", "decisions"];
  if (reportViews.includes(view) && !state.report) {
    return openLatestReview(view, findingId);
  }
  state.view = view;
  state.selectedFindingId = findingId;
  state.page = 1;
  setRoute();
  renderReport();
}

async function openLatestReview(view = "overview", findingId = "") {
  try {
    const response = await fetch("/api/reviews/latest");
    const report = response.ok ? (await response.json()).review : null;
    if (!report) return beginNewReview();
    state.report = report;
    state.packageName = report.package_name;
    state.view = view;
    state.selectedFindingId = findingId;
    setRoute();
    renderReport();
  } catch (error) {
    showToast("The saved review could not be opened. Upload a document to start a new review.", "error");
  }
}

function updateHeader() {
  const title = document.querySelector("#page-title");
  const breadcrumb = document.querySelector("#breadcrumb");
  const context = document.querySelector("#run-context");
  const status = document.querySelector("#review-status");
  document.body.dataset.view = state.view;
  if (state.view === "home") {
    title.textContent = "Home";
    breadcrumb.textContent = "CSVQUALREVIEWER WORKSPACE";
    context.textContent = "";
    status.className = "status-badge neutral hidden";
    exportButton.classList.add("hidden");
    document.title = "CSVQualReviewer — AI Document Review";
    return;
  }
  const utilityTitles = {
    chat: "Chat with CSVQualReviewer", history: "Run History", feedback: "Feedback & Analytics",
    references: "Reference Library", templates: "Templates", sops: "SOPs", golden: "Golden Reports",
    guidance: "Guidance Documents", "org-admin": "Review Administration", "platform-admin": "Platform Administration",
  };
  if (utilityTitles[state.view]) {
    title.textContent = utilityTitles[state.view];
    breadcrumb.textContent = "CSVQUALREVIEWER WORKSPACE";
    context.textContent = state.report?.package_name || "";
    status.className = "status-badge neutral hidden";
    exportButton.classList.add("hidden");
    document.title = `${utilityTitles[state.view]} — CSVQualReviewer`;
    return;
  }
  if (!state.report) {
    title.textContent = "Upload document";
    breadcrumb.textContent = "REVIEW WORKSPACE";
    context.textContent = "";
    status.className = "status-badge neutral hidden";
    exportButton.classList.add("hidden");
    document.title = "Upload Document — CSVQualReviewer";
    return;
  }
  title.textContent = "Independent Validation Assessment";
  breadcrumb.textContent = `REVIEW PACKAGES / ${state.report.package_name}`;
  context.textContent = `${state.report.package_name}  •  Review Run ${state.report.review_id}`;
  const workflowStatus = state.report.review_workflow?.status || "Not Started";
  status.textContent = workflowStatus;
  status.className = `status-badge ${slug(workflowStatus)}`;
  exportButton.classList.toggle("hidden", !["overview", "findings", "documents", "traceability", "redlines", "decisions"].includes(state.view));
  document.title = `${title.textContent} — CSVQualReviewer`;
}

function updateNavigation() {
  const report = state.report;
  const metrics = report ? calculateMetrics(report.findings || []) : null;
  document.querySelector("#findings-count").textContent = metrics?.findings ?? "—";
  document.querySelector("#documents-count").textContent = report?.metrics?.documents ?? (state.files.length || "—");
  const reviewDetailViews = new Set(["overview", "traceability", "redlines", "decisions"]);
  document.querySelectorAll(".nav-item").forEach((item) => {
    const isReviewHome = item.dataset.view === "overview" && reviewDetailViews.has(state.view);
    item.classList.toggle("active", item.dataset.view === state.view || isReviewHome);
  });
}

function renderInitialLoading() {
  updateHeader();
  workspace.innerHTML = `<div class="page-loading"><span class="spinner" aria-hidden="true"></span><strong>Opening review workspace</strong><p>Restoring the latest controlled review record.</p></div>`;
}

function renderEmpty() {
  state.report = null;
  state.view = "upload";
  state.selectedFindingId = "";
  closeDrawerImmediately();
  updateHeader();
  updateNavigation();
  workspace.innerHTML = `
    <div class="upload-page">
      <div class="upload-heading">
        <button class="back-link" type="button" data-view-home>← Back to Home</button>
        <p class="intro-kicker">New review</p>
        <h2>Upload a document for review</h2>
        <p>Start with one primary document. Add supporting evidence to give CSVQualReviewer the context it needs.</p>
      </div>
      <div class="empty-layout">
        <section class="intro-card">
          <div class="intake-fields">
            <label class="package-name-field" for="package-name">
              <span>Review name</span>
              <input id="package-name" value="${e(state.packageName)}" placeholder="e.g., DV Protocol — Temperature Monitoring System">
            </label>
            <label class="package-name-field" for="document-type">
              <span>Document type</span>
              <select id="document-type">
                ${optionList(["Select document type", "DV Report", "DV Protocol", "DV Plan", "TMV Report", "TMVA", "IQ Protocol / Report", "Engineering Study"], state.documentType || "Select document type")}
              </select>
            </label>
          </div>
          <div class="drop-zone" id="drop-zone">
            <div>
              <span class="drop-icon" aria-hidden="true">⇧</span>
              <strong>Drag &amp; drop your primary document here</strong>
              <p>DOCX, XLSX, or PDF · maximum 50 MB</p>
              <button class="secondary-button" id="browse-files" type="button">Browse files</button>
            </div>
          </div>
          ${renderSelectedFiles()}
          <div class="review-actions">
            <button class="primary-button" id="start-review" type="button" ${state.files.length ? "" : "disabled"}>Start AI review <span aria-hidden="true">→</span></button>
            <button class="text-button" id="sample-review" type="button">Use realistic sample package</button>
            <span class="privacy-copy">Secure local processing • source files unchanged</span>
          </div>
        </section>

        <aside class="protocol-card">
          <p class="section-label">AUTOMATED REVIEW FLOW</p>
          <h3>From upload to a traceable decision record.</h3>
          <ol class="workflow-steps">
            <li><span>1</span><div><strong>Validate intake</strong><p>Confirm format, structure, type, and reference completeness.</p></div></li>
            <li><span>2</span><div><strong>Analyze &amp; reconcile</strong><p>Review requirements, risk, evidence, consistency, and traceability.</p></div></li>
            <li><span>3</span><div><strong>Inspect findings</strong><p>See severity, evidence, review basis, confidence, and proposed wording.</p></div></li>
            <li><span>4</span><div><strong>Record your decision</strong><p>Accept, modify, reject, defer, or request SME review.</p></div></li>
          </ol>
          <div class="principle-note"><strong>Advisory only</strong><p>CSVQualReviewer never approves or releases documents. A qualified reviewer remains responsible for every decision.</p></div>
        </aside>
      </div>
    </div>`;
  bindEmptyActions();
  setRoute(true);
}

function renderSelectedFiles() {
  if (!state.files.length) return "";
  return `<div class="selected-files">${state.files.map((file, index) => {
    const suffix = (file.name.split(".").pop() || "doc").slice(0, 4);
    const size = file.size != null ? bytes(file.size) : "sample";
    return `<div class="file-chip"><span>${e(suffix)}</span><strong title="${e(file.name)}">${e(file.name)}</strong><small>${e(size)}</small><button type="button" data-remove-file="${index}" aria-label="Remove ${e(file.name)}">×</button></div>`;
  }).join("")}</div>`;
}

function bindEmptyActions() {
  const dropZone = document.querySelector("#drop-zone");
  document.querySelector("#browse-files").addEventListener("click", () => fileInput.click());
  document.querySelector("#start-review").addEventListener("click", startReview);
  document.querySelector("#sample-review").addEventListener("click", loadSample);
  document.querySelector("#package-name").addEventListener("input", (event) => { state.packageName = event.target.value; });
  document.querySelector("#document-type").addEventListener("change", (event) => { state.documentType = event.target.value; });
  document.querySelector("[data-view-home]").addEventListener("click", () => navigate("home"));
  document.querySelectorAll("[data-remove-file]").forEach((button) => button.addEventListener("click", () => {
    state.files.splice(Number(button.dataset.removeFile), 1);
    renderEmpty();
  }));
  ["dragenter", "dragover"].forEach((eventName) => dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.add("dragover");
  }));
  ["dragleave", "drop"].forEach((eventName) => dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.remove("dragover");
  }));
  dropZone.addEventListener("drop", (event) => addFiles([...event.dataTransfer.files]));
}

function addFiles(files) {
  const allowed = new Set(["pdf", "docx", "xlsx", "xlsm", "csv", "tsv", "txt", "md", "json", "xml", "html", "htm", "yaml", "yml"]);
  const maximumFileBytes = 50 * 1024 * 1024;
  const maximumTotalBytes = 200 * 1024 * 1024;
  const valid = files.filter((file) => allowed.has((file.name.split(".").pop() || "").toLowerCase()) && (file.size == null || file.size <= maximumFileBytes));
  const rejected = files.length - valid.length;
  const existing = new Set(state.files.map((file) => `${file.name}:${file.size ?? file.content?.length}`));
  let totalBytes = state.files.reduce((total, file) => total + (file.size || 0), 0);
  valid.forEach((file) => {
    const key = `${file.name}:${file.size ?? file.content?.length}`;
    const nextBytes = totalBytes + (file.size || 0);
    if (!existing.has(key) && state.files.length < 21 && nextBytes <= maximumTotalBytes) {
      state.files.push(file);
      existing.add(key);
      totalBytes = nextBytes;
    }
  });
  if (rejected) showToast(`${plural(rejected, "unsupported or oversized file")} skipped.`, "error");
  else if (state.files.length >= 21 || totalBytes >= maximumTotalBytes) showToast("The intake limit is one primary document plus 20 attachments, up to 200 MB total.", "error");
  state.view = "upload";
  renderEmpty();
}

async function filePayload(file) {
  if (typeof file.content === "string") return file;
  const data = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let index = 0; index < data.length; index += 12_288) binary += String.fromCharCode(...data.subarray(index, index + 12_288));
  return { name: file.name, encoding: "base64", content: btoa(binary) };
}

function renderLoading() {
  document.querySelector("#page-title").textContent = state.packageName || "Review in progress";
  document.querySelector("#breadcrumb").textContent = "EVIDENCE ANALYSIS";
  workspace.innerHTML = `<div class="page-loading review-loading"><span class="spinner" aria-hidden="true"></span><strong>Building the validation evidence graph</strong><p>Reconciling ${plural(state.files.length, "deliverable")} across document, risk, test, traceability, and quality-gate lenses.</p><div class="stage-track"><span>Classification</span><span>Requirements</span><span>Risk</span><span>Testing</span><span>Traceability</span><span>Findings</span></div></div>`;
}

async function startReview() {
  if (!state.files.length) return;
  state.packageName = document.querySelector("#package-name")?.value.trim() || state.packageName || "Untitled validation package";
  renderLoading();
  try {
    const files = await Promise.all(state.files.map(filePayload));
    const response = await fetch("/api/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ package_name: state.packageName, files }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "The review service returned an error.");
    state.report = result;
    state.view = "overview";
    state.selectedFindingId = "";
    setRoute(true);
    renderReport();
    showToast("Review run created. AI findings are ready for human disposition.");
  } catch (error) {
    workspace.innerHTML = `<section class="error-panel"><span aria-hidden="true">!</span><h2>Review could not be completed</h2><p>${e(error.message)}</p><button class="primary-button" id="return-upload" type="button">Return to package upload</button></section>`;
    document.querySelector("#return-upload").addEventListener("click", renderEmpty);
  }
}

async function loadSample() {
  try {
    const response = await fetch("/api/sample");
    if (!response.ok) throw new Error("Sample package is unavailable.");
    const sample = await response.json();
    state.files = sample.files;
    state.packageName = sample.package_name;
    renderEmpty();
    await startReview();
  } catch (error) {
    showToast(error.message, "error");
  }
}

function severityBadge(severity) {
  const normalized = severity === "Moderate" ? "Minor" : severity;
  return `<span class="severity-badge ${slug(normalized)}">${e(normalized).toUpperCase()}</span>`;
}

function statusBadge(status) {
  return `<span class="status-badge ${slug(status)}">${e(status)}</span>`;
}

function confidenceMarkup(finding) {
  const value = finding.confidence_score;
  if (value == null) return `<span class="confidence-pill unavailable">AI Confidence: Not Available</span>`;
  const band = confidenceBand(finding);
  return `<span class="confidence-pill ${slug(band)}" title="AI confidence reflects the model's assessment and does not represent reviewer approval.">AI Confidence: ${e(value)}% <small>${e(band)}</small></span>${band === "Low" ? `<span class="verification-flag">Human Verification Recommended</span>` : ""}`;
}

function sparkline(color, points) {
  const path = points.map((point, index) => `${index ? "L" : "M"}${index * (200 / (points.length - 1))},${42 - point}`).join(" ");
  const area = `${path} L200,42 L0,42 Z`;
  return `<svg class="metric-sparkline" viewBox="0 0 200 42" preserveAspectRatio="none" aria-hidden="true"><defs><linearGradient id="spark-${color.slice(1)}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${color}" stop-opacity=".24"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs><path class="spark-area" d="${area}" fill="url(#spark-${color.slice(1)})"/><path d="${path}" fill="none" stroke="${color}" stroke-width="1.6" vector-effect="non-scaling-stroke"/></svg>`;
}

function renderDashboard() {
  const metrics = state.report ? calculateMetrics((state.report.findings || []).map(normalizeFinding)) : null;
  const reviews = [
    { type: "W", tone: "word", title: "DV Protocol - Temp Monitoring System", subtitle: "DV Protocol", owner: "Jane Cooper", initials: "JC", status: "In Review", time: "2h ago", tab: "assigned" },
    { type: "PDF", tone: "pdf", title: "TMV Report - Patient Arm Module", subtitle: "TMV Report", owner: "Robert Fox", initials: "RF", status: "AI Processing", time: "4h ago", tab: "progress" },
    { type: "XLSX", tone: "xlsx", title: "F-03 Calibration Summary", subtitle: "Report", owner: "Wade Warren", initials: "WW", status: "Completed", time: "6h ago", tab: "completed" },
    { type: "W", tone: "word", title: "DV Plan - Power Management", subtitle: "DV Plan", owner: "Esther Howard", initials: "EH", status: "Pending Uploads", time: "1d ago", tab: "assigned" },
    { type: "PDF", tone: "pdf", title: "IQ Report - End of Line Test Station", subtitle: "IQ Report", owner: "Brooklyn Simmons", initials: "BS", status: "Not Started", time: "1d ago", tab: "assigned" },
  ];
  const visibleReviews = state.dashboardTab === "assigned" ? reviews : reviews.filter((review) => review.tab === state.dashboardTab);
  const critical = Math.max(23, metrics?.severity_counts?.Critical || 0);

  updateHeader();
  updateNavigation();
  workspace.innerHTML = `
    <div class="dashboard-page">
      <section class="dashboard-welcome">
        <div><h2>Welcome back, Arvind <span aria-hidden="true">👋</span></h2><p>Here’s what’s happening with your reviews today.</p></div>
        <div class="dashboard-actions">
          <button class="primary-button upload-action" data-start-review type="button"><span aria-hidden="true">＋</span>Upload Document <small>⌄</small></button>
          <button class="secondary-button new-review-action" data-start-review type="button"><span aria-hidden="true">▷</span>New Review</button>
        </div>
      </section>

      <section class="dashboard-metrics" aria-label="Review metrics">
        <article class="dashboard-metric blue"><div class="metric-top"><span class="metric-icon">▤</span><span>Documents Reviewed</span><button type="button" aria-label="Documents metric menu">⋮</button></div><strong>128</strong><small><b>＋18</b> this week</small>${sparkline("#7c4dff", [10,14,14,17,18,14,12,17,19,22,18,17,20,18,23,22,28,34,33,27,31,38])}</article>
        <article class="dashboard-metric red"><div class="metric-top"><span class="metric-icon">!</span><span>Critical Findings</span><button type="button" aria-label="Critical findings metric menu">⋮</button></div><strong>${critical}</strong><small class="down">↓ 12% <span>vs last week</span></small>${sparkline("#ff4438", [12,18,21,17,11,10,14,18,15,9,8,10,12,13,15,14,11,12,17,15,16,27])}</article>
        <article class="dashboard-metric green"><div class="metric-top"><span class="metric-icon">◷</span><span>Avg. Review Time</span><button type="button" aria-label="Review time metric menu">⋮</button></div><strong>36<em> min</em></strong><small class="up">↓ 45% <span>vs baseline</span></small>${sparkline("#41c86a", [13,17,20,20,23,22,18,12,9,11,14,16,18,19,20,19,18,23,20,26,27,31])}</article>
        <article class="dashboard-metric cyan"><div class="metric-top"><span class="metric-icon">✓</span><span>Compliance Coverage</span><button type="button" aria-label="Coverage metric menu">⋮</button></div><strong>98%</strong><small class="up">↑ 8% <span>vs baseline</span></small>${sparkline("#328cf7", [8,11,12,13,13,14,15,13,17,18,15,13,17,16,14,20,22,19,21,23,27,31])}</article>
        <article class="dashboard-metric amber"><div class="metric-top"><span class="metric-icon">$</span><span>Cost Savings (YTD)</span><button type="button" aria-label="Savings metric menu">⋮</button></div><strong>$142K</strong><small class="up">↑ 28% <span>vs last quarter</span></small>${sparkline("#f0a500", [9,13,13,13,11,14,16,20,17,14,14,17,14,19,18,24,21,20,23,23,29,31])}</article>
      </section>

      <section class="dashboard-main-grid">
        <article class="dash-panel reviews-panel">
          <div class="dash-panel-title"><h3>My Reviews</h3><button class="text-button" data-open-active type="button">View all</button></div>
          <div class="review-tabs" role="tablist" aria-label="Review status">
            <button class="${state.dashboardTab === "assigned" ? "active" : ""}" data-dashboard-tab="assigned" type="button" role="tab">Assigned to me (5)</button>
            <button class="${state.dashboardTab === "progress" ? "active" : ""}" data-dashboard-tab="progress" type="button" role="tab">In Progress (4)</button>
            <button class="${state.dashboardTab === "completed" ? "active" : ""}" data-dashboard-tab="completed" type="button" role="tab">Completed</button>
          </div>
          <div class="review-list">
            ${visibleReviews.map((review, index) => `<button class="review-row" type="button" ${index === 0 ? "data-open-active" : "data-review-demo"}>
              <span class="file-type ${review.tone}">${e(review.type)}</span>
              <span class="review-name"><strong>${e(review.title)}</strong><small>${e(review.subtitle)}</small></span>
              <span class="review-owner"><small>Uploaded by</small><span><i>${e(review.initials)}</i>${e(review.owner)}</span></span>
              <span class="review-status ${slug(review.status)}">${review.status === "Completed" ? "✓ " : ""}${e(review.status)}</span>
              <time>${e(review.time)}</time><span class="row-menu" aria-hidden="true">⋮</span>
            </button>`).join("")}
          </div>
          <button class="dashboard-dropzone" data-start-review type="button"><span aria-hidden="true">⇧</span><strong>Drag &amp; drop files here or click to browse</strong><small>DOCX, XLSX, PDF (Max 50MB per file)</small></button>
        </article>

        <div class="dashboard-center-stack">
          <article class="dash-panel progress-panel">
            <div class="dash-panel-title"><h3>Review Progress</h3><select aria-label="Review progress time range"><option>This Week</option><option>This Month</option></select></div>
            <div class="progress-body">
              <div class="progress-donut" aria-label="128 total reviews"><span><strong>128</strong><small>Total</small></span></div>
              <dl class="progress-legend">
                <div><dt><i class="green-dot"></i>Completed</dt><dd>58 (45%)</dd></div>
                <div><dt><i class="violet-dot"></i>In Review</dt><dd>32 (25%)</dd></div>
                <div><dt><i class="blue-dot"></i>AI Processing</dt><dd>18 (14%)</dd></div>
                <div><dt><i class="amber-dot"></i>Pending Upload</dt><dd>12 (9%)</dd></div>
                <div><dt><i class="gray-dot"></i>Not Started</dt><dd>8 (6%)</dd></div>
              </dl>
            </div>
            <button class="text-button progress-link" data-open-active type="button">View all reviews →</button>
          </article>
          <article class="dash-panel categories-panel">
            <div class="dash-panel-title"><h3>Top Finding Categories</h3><select aria-label="Finding category time range"><option>This Week</option><option>This Month</option></select></div>
            <div class="category-bars">
              ${[["Critical",23,"critical"],["Major",41,"major"],["Minor",67,"minor"],["Suggestions",35,"suggestions"],["Informational",18,"informational"]].map(([label,value,tone]) => `<div><span>${label}</span><i><b class="${tone}" style="width:${Math.max(28, value)}%"></b></i><strong>${value}</strong></div>`).join("")}
            </div>
            <button class="text-button" data-view-findings type="button">View findings →</button>
          </article>
        </div>

        <article class="dash-panel activity-panel">
          <div class="dash-panel-title"><h3>Recent Activity</h3><button class="text-button" type="button" data-demo-action>View all</button></div>
          <div class="activity-list">
            ${[
              ["✣","purple","AI review completed","DV Protocol - Temp Monitoring System","2m ago"],
              ["!","red","New critical finding detected","TMV Report - Patient Arm Module","15m ago"],
              ["✓","green","Review completed","F-03 Calibration Summary","1h ago"],
              ["⇧","blue","Document uploaded","DV Plan - Power Management","2h ago"],
              ["▣","violet","New chat started","IQ Report - End of Line Test Station","3h ago"],
              ["♙","amber","User added","Esther Howard added to organization","4h ago"],
              ["♢","green","Reference library updated","TMV SOP v2.4 uploaded","5h ago"],
              ["⌁","purple","Weekly analytics report generated","","6h ago"],
            ].map(([icon,tone,title,copy,time]) => `<div class="activity-row"><span class="activity-icon ${tone}">${icon}</span><span><strong>${title}</strong>${copy ? `<small>${copy}</small>` : ""}</span><time>${time}</time></div>`).join("")}
          </div>
        </article>
      </section>

      <section class="quick-access">
        <h3>Quick Access</h3>
        <div>
          <button data-quick="chat" type="button"><span class="blue">▣</span><span><strong>Chat with CSVQualReviewer</strong><small>Ask questions about your documents</small></span></button>
          <button data-quick="references" type="button"><span class="green">▰</span><span><strong>Reference Library</strong><small>Access SOPs, templates &amp; reports</small></span></button>
          <button data-quick="findings" type="button"><span class="red">!</span><span><strong>Findings Dashboard</strong><small>View all findings &amp; metrics</small></span></button>
          <button data-quick="org-admin" type="button"><span class="violet">⚙</span><span><strong>Review Administration</strong><small>Manage users &amp; review configurations</small></span></button>
        </div>
      </section>
    </div>`;

  document.querySelectorAll("[data-start-review]").forEach((button) => button.addEventListener("click", beginNewReview));
  document.querySelectorAll("[data-open-active]").forEach((button) => button.addEventListener("click", () => navigate("overview")));
  document.querySelectorAll("[data-dashboard-tab]").forEach((button) => button.addEventListener("click", () => { state.dashboardTab = button.dataset.dashboardTab; renderDashboard(); }));
  document.querySelectorAll("[data-review-demo], [data-demo-action]").forEach((button) => button.addEventListener("click", () => showToast("Demo activity opened. Connect your organization data to view the full record.")));
  document.querySelector("[data-view-findings]").addEventListener("click", () => navigate("findings"));
  document.querySelectorAll("[data-quick]").forEach((button) => button.addEventListener("click", () => navigate(button.dataset.quick)));
}

function renderUtilityView(view) {
  const content = {
    chat: ["Chat with CSVQualReviewer", "Ask grounded questions about the current run. Responses stay scoped to its documents, references, findings, citations, and traceability.", "chat"],
    history: ["Run History", "Search and reopen prior review runs with their original configuration, references, findings, and decision record.", "history"],
    feedback: ["Feedback & Analytics", "Monitor review usefulness, false-positive patterns, citation quality, document-type trends, and cost.", "analytics"],
    references: ["Reference Library", "Manage the active SOPs, templates, guidance, golden reports, and historical versions used for new reviews.", "library"],
    templates: ["Templates", "Controlled document templates available to new review runs.", "library"],
    sops: ["Standard Operating Procedures", "Active and archived procedures with revision-level traceability.", "library"],
    golden: ["Golden Reports", "Approved exemplars used as controlled organizational review context.", "library"],
    guidance: ["Guidance Documents", "Internal standards and approved guidance available to the review engine.", "library"],
    "org-admin": ["Review Administration", "Manage users, document-type review configuration, activation controls, analytics, and audit records.", "admin"],
    "platform-admin": ["Platform Administration", "Manage organizations, approved models, tenant isolation, platform health, and cross-organization audit.", "admin"],
  }[view] || ["CSVQualReviewer", "This workspace is ready for your organization’s configured data.", "library"];
  updateHeader();
  updateNavigation();
  const reportName = state.report?.package_name || "No active review";
  workspace.innerHTML = `<div class="utility-page"><div class="utility-heading"><p class="intro-kicker">CSVQUALREVIEWER WORKSPACE</p><h2>${e(content[0])}</h2><p>${e(content[1])}</p></div>${content[2] === "chat" ? `
    <section class="chat-shell"><div class="chat-context"><span>Current run</span><strong>${e(reportName)}</strong><small>Document and review sources are cited separately. Chat cannot modify the controlled run.</small></div><div class="chat-messages" id="chat-messages"><article class="assistant-message"><span>✣</span><div><strong>CSVQualReviewer</strong><p>Ask about evidence, requirements, findings, traceability, or proposed wording in this run.</p><div><button type="button" data-chat-prompt="Summarize the highest-risk findings">Summarize highest-risk findings</button><button type="button" data-chat-prompt="Which requirements lack test coverage?">Find traceability gaps</button></div></div></article></div><form class="chat-composer" id="chat-form"><input id="chat-input" placeholder="Ask about this review…" aria-label="Chat message"><button type="submit" aria-label="Send message">↑</button></form></section>` : `
    <section class="utility-grid"><article><span>01</span><h3>${content[2] === "history" ? "Controlled provenance" : content[2] === "analytics" ? "Evidence-led improvement" : content[2] === "admin" ? "Governed configuration" : "Version-controlled context"}</h3><p>${content[2] === "history" ? "Every run remains linked to its inputs, outputs, configuration version, references, and model traceability." : content[2] === "analytics" ? "Feedback informs analytics without silently rewriting completed findings or production behavior." : content[2] === "admin" ? "Review-logic changes are versioned and high-impact activation can require four-eyes confirmation." : "Only active approved references are used for new runs; archived versions remain available for reconstruction."}</p></article><article><span>02</span><h3>${state.report ? "Active review available" : "Ready for organization data"}</h3><p>${state.report ? `Open ${e(state.report.package_name)} to inspect its controlled record.` : "Upload a primary document or connect your organization sources to populate this workspace."}</p><button class="primary-button" type="button" data-utility-action>${state.report ? "Open active review" : "Upload document"}</button></article></section>`}</div>`;
  document.querySelector("[data-utility-action]")?.addEventListener("click", () => state.report ? navigate("overview") : beginNewReview());
  if (content[2] === "chat") {
    const input = document.querySelector("#chat-input");
    document.querySelectorAll("[data-chat-prompt]").forEach((button) => button.addEventListener("click", () => { input.value = button.dataset.chatPrompt; input.focus(); }));
    document.querySelector("#chat-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const question = input.value.trim();
      if (!question) return;
      document.querySelector("#chat-messages").insertAdjacentHTML("beforeend", `<article class="user-message"><p>${e(question)}</p></article><article class="assistant-message"><span>✣</span><div><strong>CSVQualReviewer</strong><p>${state.report ? `This local prototype keeps chat grounded to ${e(state.report.package_name)}. Open Findings or Traceability to inspect the supporting controlled record.` : "Upload a document first so the answer can be grounded in a specific run."}</p></div></article>`);
      input.value = "";
    });
  }
}

function renderReport() {
  if (state.view === "home") return renderDashboard();
  if (["chat", "history", "feedback", "references", "templates", "sops", "golden", "guidance", "org-admin", "platform-admin"].includes(state.view)) return renderUtilityView(state.view);
  if (state.view === "upload" || !state.report) return renderEmpty();
  state.report.findings = (state.report.findings || []).map(normalizeFinding);
  updateHeader();
  updateNavigation();
  const renderers = {
    overview: renderOverview,
    findings: renderFindings,
    documents: renderDocuments,
    traceability: renderTraceability,
    redlines: renderRedlines,
    decisions: renderDecisions,
  };
  (renderers[state.view] || renderOverview)();
  if (state.selectedFindingId) openFindingDrawer(state.selectedFindingId, false);
  else closeDrawerImmediately();
}

function pageHeading(title, copy, action = "") {
  const tabs = [["overview", "Summary"], ["findings", "Findings"], ["documents", "Documents"], ["traceability", "Traceability"], ["redlines", "Redlines"], ["decisions", "Decisions"]];
  return `<nav class="review-subnav" aria-label="Active review sections">${tabs.map(([view, label]) => `<button class="${state.view === view ? "active" : ""}" type="button" data-review-nav="${view}">${label}</button>`).join("")}</nav><div class="view-title"><div><p class="section-label">${e(state.report.package_name)}</p><h2>${e(title)}</h2><p>${e(copy)}</p></div>${action}</div>`;
}

function metricCard(label, value, note, tone = "") {
  return `<article class="metric-card ${tone}"><span>${e(label)}</span><strong>${e(value)}</strong><small>${e(note)}</small></article>`;
}

function renderOverview() {
  const report = state.report;
  const metrics = calculateMetrics(report.findings);
  const workflow = report.review_workflow || {};
  const highRisk = metrics.severity_counts.Critical + metrics.severity_counts.Major;
  const sme = metrics.status_counts["Needs SME Review"];
  const provenance = report.review_provenance || {};
  const prominent = sortFindings(report.findings, "risk").filter((finding) => !["Rejected", "Resolved"].includes(finding.status)).slice(0, 5);
  workspace.innerHTML = `
    ${pageHeading("Executive Summary", "Package risk, reviewer workload, provenance, and readiness from one controlled data source.")}
    <div class="summary-strip">
      <div><span>PACKAGE READINESS</span><strong>${e(workflow.package_readiness || "Not Ready")}</strong></div>
      <div class="summary-reasons">${(workflow.readiness_reasons || ["Readiness has not been calculated."]).map((reason) => `<span>• ${e(reason)}</span>`).join("")}</div>
      ${statusBadge(workflow.status || "Not Started")}
    </div>
    <div class="metrics-grid six">
      ${metricCard("Documents", report.metrics.documents, "Reviewed in this run")}
      ${metricCard("Total findings", metrics.findings, "Structured AI findings")}
      ${metricCard("Critical", metrics.severity_counts.Critical, "Highest potential impact", metrics.severity_counts.Critical ? "danger" : "")}
      ${metricCard("Major", metrics.severity_counts.Major, "Substantive remediation", metrics.severity_counts.Major ? "warning" : "")}
      ${metricCard("Open actions", metrics.open_findings, `${metrics.status_counts.Open} undispositioned`) }
      ${metricCard("SME review", sme, "Human verification queue", sme ? "info" : "")}
    </div>
    <div class="overview-grid">
      <div class="overview-main">
        <section class="panel">
          <div class="panel-heading"><div><span class="section-label">UNRESOLVED RISK</span><h3>Significant findings</h3></div><button class="text-button" data-jump="findings" type="button">View all findings →</button></div>
          <div class="priority-list">${prominent.length ? prominent.map((finding) => `
            <button class="priority-item" type="button" data-open-finding="${e(finding.finding_id)}">
              <span>${e(finding.finding_id)}</span>${severityBadge(finding.severity)}
              <div><strong>${e(finding.title)}</strong><small>${e(finding.document)} • ${e(finding.section)}</small></div>
              ${statusBadge(finding.status)}
            </button>`).join("") : `<div class="empty-state compact"><strong>No unresolved findings</strong><p>All findings are rejected or resolved.</p></div>`}</div>
        </section>
        <section class="panel">
          <div class="panel-heading"><div><span class="section-label">HUMAN DISPOSITION</span><h3>Reviewer decision metrics</h3></div><button class="text-button" data-jump="decisions" type="button">Open decision log →</button></div>
          <div class="decision-metrics">
            ${["Accepted", "Rejected", "Modified", "Deferred", "Needs SME Review", "Resolved"].map((status) => `<div><span>${e(status)}</span><strong>${metrics.status_counts[status]}</strong></div>`).join("")}
          </div>
        </section>
      </div>
      <aside class="overview-side">
        <section class="panel readiness-panel">
          <span class="section-label">REVIEW COMPLETION</span>
          <h3>${workflow.can_complete ? "Completion checks passed" : "Reviewer action remains"}</h3>
          <p>${workflow.can_complete ? "No unresolved Critical/Major, SME, or undispositioned findings remain." : "The review cannot be completed until the configured blockers below are cleared."}</p>
          <ul>${(workflow.readiness_reasons || []).map((reason) => `<li>${e(reason)}</li>`).join("")}</ul>
          <button class="primary-button full" id="complete-review" type="button" ${workflow.can_complete && workflow.status !== "Review Completed" ? "" : "disabled"}>${workflow.status === "Review Completed" ? "Review completed" : "Complete review"}</button>
        </section>
        <section class="panel provenance-panel">
          <span class="section-label">REVIEW PROVENANCE</span>
          <h3>Controlled run record</h3>
          <dl>
            ${[
              ["Review Run ID", provenance.review_run_id || report.review_id],
              ["Review Agent", provenance.review_agent_version || "Not Available"],
              ["Rule Set", provenance.prompt_rule_set_version || "Not Available"],
              ["Knowledge Baseline", provenance.knowledge_base_version || "Not Available"],
              ["Procedure Baseline", provenance.procedure_policy_baseline || "Not Available"],
              ["Review Date", timestamp(provenance.review_date_time || report.generated_at)],
              ["Latest Reviewer", provenance.reviewer || "Not Available"],
              ["Documents", provenance.documents_reviewed ?? report.metrics.documents],
            ].map(([term, value]) => `<div><dt>${e(term)}</dt><dd>${e(value)}</dd></div>`).join("")}
          </dl>
        </section>
      </aside>
    </div>`;
  document.querySelectorAll("[data-jump]").forEach((button) => button.addEventListener("click", () => navigate(button.dataset.jump)));
  document.querySelectorAll("[data-open-finding]").forEach((button) => button.addEventListener("click", () => navigate("findings", button.dataset.openFinding)));
  document.querySelector("#complete-review").addEventListener("click", completeReview);
}

function optionList(values, selected) {
  return values.map((value) => `<option value="${e(value)}" ${value === selected ? "selected" : ""}>${e(value)}</option>`).join("");
}

function renderFindings() {
  const findings = state.report.findings;
  const categories = ["All", ...new Set(findings.map((finding) => finding.category).sort())];
  const documents = ["All", ...new Set(findings.flatMap((finding) => finding.affected_documents.map((item) => item.document_name)).filter(Boolean).sort())];
  workspace.innerHTML = `
    ${pageHeading("Findings", "Prioritized AI-identified findings with evidence, review basis, risk, recommendation, and human disposition.", `<div class="result-count" id="result-count"></div>`)}
    <section class="filter-panel" aria-label="Finding filters">
      <label class="search-control"><span>Search findings</span><input id="filter-query" type="search" value="${e(state.filters.query)}" placeholder="ID, title, finding, document, category, section"></label>
      <label><span>Severity</span><select id="filter-severity">${optionList(["All", ...SEVERITIES], state.filters.severity)}</select></label>
      <label><span>Category</span><select id="filter-category">${optionList(categories, state.filters.category)}</select></label>
      <label><span>Document</span><select id="filter-document">${optionList(documents, state.filters.document)}</select></label>
      <label><span>Status</span><select id="filter-status">${optionList(["All", ...STATUSES], state.filters.status)}</select></label>
      <label><span>Confidence</span><select id="filter-confidence">${optionList(["All", "High", "Medium", "Low", "Not Available"], state.filters.confidence)}</select></label>
      <label><span>Sort by</span><select id="finding-sort">${optionList(["risk", "severity", "document", "id", "confidence", "status", "newest", "oldest"], state.sort)}</select></label>
      <button class="secondary-button clear-filter" id="clear-filters" type="button">Clear filters</button>
    </section>
    <div class="bulk-toolbar hidden" id="bulk-toolbar">
      <strong id="bulk-count"></strong>
      <button type="button" data-bulk="Deferred">Defer selected</button>
      <button type="button" data-bulk="Needs SME Review">Mark as Needs SME Review</button>
      <button type="button" data-bulk="export">Export selected findings</button>
      <small>Bulk acceptance is intentionally unavailable for compliance decisions.</small>
    </div>
    <div class="findings-list" id="findings-list"></div>
    <div class="pagination" id="pagination"></div>`;
  const bindings = {
    "filter-query": "query",
    "filter-severity": "severity",
    "filter-category": "category",
    "filter-document": "document",
    "filter-status": "status",
    "filter-confidence": "confidence",
  };
  Object.entries(bindings).forEach(([id, key]) => document.querySelector(`#${id}`).addEventListener(id === "filter-query" ? "input" : "change", (event) => {
    state.filters[key] = event.target.value;
    state.page = 1;
    renderFindingList();
  }));
  document.querySelector("#finding-sort").addEventListener("change", (event) => { state.sort = event.target.value; renderFindingList(); });
  document.querySelector("#clear-filters").addEventListener("click", () => {
    state.filters = { query: "", severity: "All", category: "All", document: "All", status: "All", confidence: "All" };
    state.page = 1;
    renderFindings();
  });
  document.querySelectorAll("[data-bulk]").forEach((button) => button.addEventListener("click", () => bulkAction(button.dataset.bulk)));
  renderFindingList();
}

function renderFindingList() {
  const target = document.querySelector("#findings-list");
  if (!target) return;
  const filtered = sortFindings(filterFindings(state.report.findings, state.filters), state.sort);
  const totalPages = Math.max(1, Math.ceil(filtered.length / state.pageSize));
  state.page = Math.min(state.page, totalPages);
  const visible = filtered.slice((state.page - 1) * state.pageSize, state.page * state.pageSize);
  document.querySelector("#result-count").textContent = `${filtered.length} of ${state.report.findings.length} findings`;
  target.innerHTML = visible.length ? visible.map((finding) => `
    <article class="finding-card ${slug(finding.severity)}">
      <div class="finding-card-head">
        <label class="select-finding"><input type="checkbox" data-select-finding="${e(finding.finding_id)}" ${state.selectedFindings.has(finding.finding_id) ? "checked" : ""}><span class="sr-only">Select ${e(finding.finding_id)}</span></label>
        <button class="finding-open" type="button" data-open-finding="${e(finding.finding_id)}">
          <span class="finding-id">${e(finding.finding_id)}</span>${severityBadge(finding.severity)}<span class="category-label">${e(finding.category)}</span>
        </button>
        ${statusBadge(finding.status)}
      </div>
      <button class="finding-card-body" type="button" data-open-finding="${e(finding.finding_id)}">
        <div class="finding-document">${e(finding.document)} <span>•</span> ${e(finding.section)}</div>
        <h3>${e(finding.title)}</h3>
        <p>${e(short(finding.finding, 260))}</p>
        <div class="finding-meta">${confidenceMarkup(finding)}<span>${plural(finding.affected_documents.length, "affected document")}</span></div>
      </button>
    </article>`).join("") : `<div class="empty-state"><strong>No findings match these filters</strong><p>Clear one or more filters to return to the full review set.</p><button class="secondary-button" id="empty-clear" type="button">Clear filters</button></div>`;
  document.querySelectorAll("[data-open-finding]").forEach((button) => button.addEventListener("click", () => navigate("findings", button.dataset.openFinding)));
  document.querySelectorAll("[data-select-finding]").forEach((checkbox) => checkbox.addEventListener("change", () => {
    if (checkbox.checked) state.selectedFindings.add(checkbox.dataset.selectFinding);
    else state.selectedFindings.delete(checkbox.dataset.selectFinding);
    updateBulkToolbar();
  }));
  document.querySelector("#empty-clear")?.addEventListener("click", () => {
    state.filters = { query: "", severity: "All", category: "All", document: "All", status: "All", confidence: "All" };
    renderFindings();
  });
  const pagination = document.querySelector("#pagination");
  pagination.innerHTML = filtered.length > state.pageSize ? `<button type="button" id="page-prev" ${state.page === 1 ? "disabled" : ""}>Previous</button><span>Page ${state.page} of ${totalPages}</span><button type="button" id="page-next" ${state.page === totalPages ? "disabled" : ""}>Next</button>` : "";
  document.querySelector("#page-prev")?.addEventListener("click", () => { state.page -= 1; renderFindingList(); workspace.scrollTo?.(0, 0); });
  document.querySelector("#page-next")?.addEventListener("click", () => { state.page += 1; renderFindingList(); workspace.scrollTo?.(0, 0); });
  updateBulkToolbar();
}

function updateBulkToolbar() {
  const toolbar = document.querySelector("#bulk-toolbar");
  if (!toolbar) return;
  toolbar.classList.toggle("hidden", state.selectedFindings.size === 0);
  document.querySelector("#bulk-count").textContent = `${state.selectedFindings.size} selected`;
}

async function bulkAction(action) {
  const findings = state.report.findings.filter((finding) => state.selectedFindings.has(finding.finding_id));
  if (!findings.length) return;
  if (action === "export") {
    exportFindings(findings, "selected-findings.csv");
    return;
  }
  const comment = action === "Needs SME Review" ? "Bulk review action: subject-matter expert verification is required." : "Bulk review action: disposition deferred for later review.";
  if (!window.confirm(`${action} for ${plural(findings.length, "selected finding")}? Each decision will be recorded separately.`)) return;
  for (const finding of findings) {
    try {
      const response = await fetch(`/api/reviews/${encodeURIComponent(state.report.review_id)}/findings/${encodeURIComponent(finding.finding_id)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ disposition: action, reviewer_comment: comment, reviewer: localStorage.getItem("csvqualreviewer-reviewer") || "", expected_updated_at: finding.updated_at }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(`${finding.finding_id}: ${payload.error}`);
      state.report = payload.report;
    } catch (error) {
      showToast(error.message, "error");
      break;
    }
  }
  state.selectedFindings.clear();
  renderReport();
  showToast(`${plural(findings.length, "finding")} updated.`);
}

function renderDocuments() {
  const summaries = [...(state.report.document_summaries || [])];
  const sorters = {
    risk: (a, b) => ({ Critical: 0, Major: 1, Minor: 2, Observation: 3, None: 4 }[a.highest_unresolved_severity] - { Critical: 0, Major: 1, Minor: 2, Observation: 3, None: 4 }[b.highest_unresolved_severity]) || b.finding_count - a.finding_count,
    findings: (a, b) => b.finding_count - a.finding_count || a.document_name.localeCompare(b.document_name),
    name: (a, b) => a.document_name.localeCompare(b.document_name),
    status: (a, b) => b.open_count - a.open_count || a.document_name.localeCompare(b.document_name),
  };
  summaries.sort(sorters[state.documentSort] || sorters.risk);
  workspace.innerHTML = `
    ${pageHeading("Documents", "Document-specific finding counts, unresolved risk, extraction status, and review confidence.", `<label class="inline-select"><span>Sort</span><select id="document-sort">${optionList(["risk", "findings", "name", "status"], state.documentSort)}</select></label>`)}
    <div class="document-grid">${summaries.length ? summaries.map((summary) => {
      const review = state.report.detailed_document_review.find((item) => (item.document_name || item.name || item.document?.name) === summary.document_name) || {};
      const confidence = review.review_confidence || {};
      return `<button class="document-card" type="button" data-document="${e(summary.document_name)}">
        <div class="document-card-top"><span class="document-type">${e(summary.document_type)}</span>${summary.highest_unresolved_severity === "None" ? `<span class="risk-none">NO UNRESOLVED RISK</span>` : severityBadge(summary.highest_unresolved_severity)}</div>
        <h3>${e(summary.document_name)}</h3>
        <p>Revision ${e(summary.revision)} • ${e(summary.extraction_status || "Not Available")} extraction</p>
        <div class="document-counts"><strong>${plural(summary.finding_count, "Finding")}</strong><span>${summary.severity_counts.Major} Major</span><span>${summary.severity_counts.Minor} Minor</span><span>${summary.open_count} Open</span></div>
        <div class="document-risk"><span>Highest unresolved finding</span><strong>${e(summary.highest_unresolved_severity)}</strong></div>
        <div class="confidence-bar"><span style="width:${Number(confidence.score || 0)}%"></span></div><small>Review confidence ${e(confidence.score ?? "Not Available")}${confidence.score != null ? "%" : ""}</small>
      </button>`;
    }).join("") : `<div class="empty-state"><strong>No document summaries available</strong><p>This historical review does not include document-level metadata.</p></div>`}</div>`;
  document.querySelector("#document-sort").addEventListener("change", (event) => { state.documentSort = event.target.value; renderDocuments(); });
  document.querySelectorAll("[data-document]").forEach((button) => button.addEventListener("click", () => {
    state.filters.document = button.dataset.document;
    navigate("findings");
  }));
}

function primaryBasis(finding) {
  return finding.review_basis?.[0] || { source_type: "Not Available", source_name: "Not Available", section: "Not Available", clause: "Not Available", verification_status: "Needs Verification" };
}

function renderTraceability() {
  const findings = sortFindings(state.report.findings, "risk");
  workspace.innerHTML = `
    ${pageHeading("Traceability", "Finding → document → section → review basis → proposed change → reviewer decision.")}
    <div class="table-wrap">
      <table class="trace-table">
        <thead><tr><th>Finding</th><th>Severity</th><th>Document</th><th>Section</th><th>Requirement / Review Basis</th><th>Reviewer Status</th></tr></thead>
        <tbody>${findings.map((finding) => {
          const basis = primaryBasis(finding);
          return `<tr data-open-finding="${e(finding.finding_id)}" tabindex="0">
            <td><strong>${e(finding.finding_id)}</strong><span>${e(short(finding.title, 70))}</span></td>
            <td>${severityBadge(finding.severity)}</td>
            <td>${e(finding.document)}</td>
            <td>${e(finding.section)}</td>
            <td><strong>${e(basis.source_name || "Not Available")}</strong><span>${e(basis.source_type || "Not Available")} • ${e(basis.verification_status || "Needs Verification")}</span></td>
            <td>${statusBadge(finding.status)}</td>
          </tr>`;
        }).join("")}</tbody>
      </table>
    </div>`;
  document.querySelectorAll("[data-open-finding]").forEach((row) => {
    const open = () => navigate("traceability", row.dataset.openFinding);
    row.addEventListener("click", open);
    row.addEventListener("keydown", (event) => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); open(); } });
  });
}

function renderRedlineComparison(finding, mode = state.redlineMode) {
  const original = finding.original_text || "Not Available";
  const proposed = finding.proposed_text || "Not Available";
  if (mode === "proposed") return `<div class="proposed-only"><span>AI PROPOSED TEXT</span><pre>${e(proposed)}</pre></div>`;
  if (mode === "split") return `<div class="split-redline"><div><span>ORIGINAL SOURCE TEXT</span><pre>${e(original)}</pre></div><div><span>AI PROPOSED TEXT</span><pre>${e(proposed)}</pre></div></div>`;
  const segments = finding.redline_diff?.length ? finding.redline_diff : [{ type: "delete", text: original }, { type: "insert", text: proposed }];
  return `<div class="unified-redline"><span>UNIFIED REDLINE</span><pre>${segments.map((segment) => `<${segment.type === "delete" ? "del" : segment.type === "insert" ? "ins" : "span"}>${e(segment.text)}</${segment.type === "delete" ? "del" : segment.type === "insert" ? "ins" : "span"}>`).join("")}</pre></div>`;
}

function renderRedlines() {
  const documents = state.report.redlined_documents || [];
  state.selectedRedline = Math.min(state.selectedRedline, Math.max(0, documents.length - 1));
  const selected = documents[state.selectedRedline];
  const related = selected ? state.report.findings.filter((finding) => selected.finding_ids?.includes(finding.finding_id) || finding.affected_documents.some((item) => item.document_name === selected.document_name)) : [];
  workspace.innerHTML = `
    ${pageHeading("Redlines", "Compare immutable source text with AI-proposed wording and reviewer-controlled accepted changes.")}
    <div class="info-banner"><span aria-hidden="true">i</span><p><strong>AI-generated proposed wording.</strong> Source text is preserved and remains unchanged until reviewer acceptance. All recommendations require human review and disposition.</p></div>
    <div class="redline-workspace">
      <aside class="redline-documents"><span class="section-label">DOCUMENTS</span>${documents.map((document, index) => `<button class="${index === state.selectedRedline ? "active" : ""}" type="button" data-redline-document="${index}"><strong>${e(document.document_name)}</strong><small>${plural(document.change_count, "Finding")}</small></button>`).join("")}</aside>
      <section class="redline-main">${selected ? `
        <div class="redline-header"><div><span class="section-label">${e(selected.document_type)}</span><h3>${e(selected.document_name)}</h3><p>Revision ${e(selected.revision || "Not Available")} • Source file preserved</p></div><div class="view-modes" aria-label="Redline view mode"><button type="button" data-mode="split" class="${state.redlineMode === "split" ? "active" : ""}">Split View</button><button type="button" data-mode="unified" class="${state.redlineMode === "unified" ? "active" : ""}">Unified Redline</button><button type="button" data-mode="proposed" class="${state.redlineMode === "proposed" ? "active" : ""}">Proposed Text Only</button></div></div>
        <div class="redline-findings">${related.length ? related.map((finding) => `<article class="redline-card"><div class="redline-card-head"><button type="button" data-open-finding="${e(finding.finding_id)}"><span>${e(finding.finding_id)}</span>${severityBadge(finding.severity)}<strong>${e(finding.category)}</strong></button>${statusBadge(finding.status)}</div>${renderRedlineComparison(finding)}${finding.status === "Rejected" ? `<div class="change-disposition excluded">Rejected recommendation — excluded from the final reviewed document.</div>` : acceptedChangeForFinding(finding) ? `<div class="change-disposition included">Reviewer-controlled final wording: ${e(acceptedChangeForFinding(finding))}</div>` : `<div class="change-disposition pending">Pending human disposition — source remains unchanged.</div>`}</article>`).join("") : `<div class="empty-state"><strong>No redline-ready findings</strong><p>This document has no associated proposed wording.</p></div>`}</div>
        <details class="source-document"><summary>View immutable extracted source document</summary><pre>${e(selected.source_text || "Source text is not available in this historical review.")}</pre></details>` : `<div class="empty-state"><strong>No redline documents available</strong><p>This review does not contain document-level redline data.</p></div>`}</section>
    </div>`;
  document.querySelectorAll("[data-redline-document]").forEach((button) => button.addEventListener("click", () => { state.selectedRedline = Number(button.dataset.redlineDocument); renderRedlines(); }));
  document.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click", () => { state.redlineMode = button.dataset.mode; sessionStorage.setItem("csvqualreviewer-redline-mode", state.redlineMode); renderRedlines(); }));
  document.querySelectorAll("[data-open-finding]").forEach((button) => button.addEventListener("click", () => navigate("redlines", button.dataset.openFinding)));
}

function renderDecisions() {
  const decisions = state.report.findings.filter((finding) => finding.status !== "Open" && (state.decisionStatus === "All" || finding.status === state.decisionStatus));
  workspace.innerHTML = `
    ${pageHeading("Review Decisions", "Consolidated human decision record, kept separate from the original AI recommendation.", `<label class="inline-select"><span>Status</span><select id="decision-status">${optionList(["All", "Accepted", "Rejected", "Modified", "Deferred", "Needs SME Review", "Resolved"], state.decisionStatus)}</select></label>`)}
    <div class="decision-table-wrap">
      <table class="decision-table"><thead><tr><th>Finding</th><th>AI Recommendation</th><th>Human Decision</th><th>Reviewer Comment</th><th>Reviewer / Date</th></tr></thead><tbody>
        ${decisions.map((finding) => `<tr data-open-finding="${e(finding.finding_id)}" tabindex="0"><td><strong>${e(finding.finding_id)} • ${e(finding.severity)}</strong><span>${e(finding.document)}</span></td><td><span class="ai-label">AI RECOMMENDATION</span>${e(short(finding.proposed_text, 190))}</td><td>${statusBadge(finding.status)}${finding.modified_recommendation ? `<p><strong>Reviewer wording:</strong> ${e(short(finding.modified_recommendation, 150))}</p>` : ""}</td><td>${e(finding.reviewer_comment || "No comment recorded")}</td><td><strong>${e(finding.reviewer || "Not Available")}</strong><span>${e(timestamp(finding.reviewed_at))}</span></td></tr>`).join("") || `<tr><td colspan="5"><div class="empty-state"><strong>No reviewer decisions match this filter</strong><p>Open a finding to record a human disposition.</p></div></td></tr>`}
      </tbody></table>
    </div>`;
  document.querySelector("#decision-status").addEventListener("change", (event) => { state.decisionStatus = event.target.value; renderDecisions(); });
  document.querySelectorAll("[data-open-finding]").forEach((row) => {
    const open = () => navigate("decisions", row.dataset.openFinding);
    row.addEventListener("click", open);
    row.addEventListener("keydown", (event) => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); open(); } });
  });
}

function openFindingDrawer(findingId, updateRoute = true) {
  const finding = state.report.findings.find((item) => item.finding_id === findingId || item.id === findingId);
  if (!finding) return;
  state.selectedFindingId = finding.finding_id;
  if (!state.decisionDraft || state.decisionDraft.findingId !== finding.finding_id) {
    state.decisionDraft = {
      findingId: finding.finding_id,
      disposition: finding.status === "Open" ? "" : finding.status,
      reviewer: finding.reviewer && finding.reviewer !== "Not Available" ? finding.reviewer : (localStorage.getItem("csvqualreviewer-reviewer") || ""),
      comment: finding.reviewer_comment || "",
      modified: finding.modified_recommendation || finding.proposed_text,
      rejectionReason: finding.rejection_reason || "",
      modificationReason: finding.modification_reason || "",
      duplicateOf: finding.duplicate_of || "",
    };
    state.unsaved = false;
  }
  if (updateRoute) setRoute();
  renderFindingDrawer(finding);
  drawer.classList.remove("hidden");
  drawerScrim.classList.remove("hidden");
  drawer.setAttribute("aria-hidden", "false");
  document.body.classList.add("drawer-open");
  window.setTimeout(() => drawer.querySelector("#close-drawer")?.focus(), 0);
}

function renderFindingDrawer(finding) {
  const basisRows = finding.review_basis?.length ? finding.review_basis : [{ source_type: "Not Available", source_name: "Not Available", section: "Not Available", clause: "Not Available", text: "Not Available", verification_status: "Needs Verification" }];
  const draft = state.decisionDraft;
  const actions = [
    ["Accepted", "Accept"], ["Modified", "Modify"], ["Rejected", "Reject"], ["Deferred", "Defer"], ["Needs SME Review", "Needs SME Review"], ["Resolved", "Resolve"],
  ];
  drawer.innerHTML = `
    <div class="drawer-header"><div><span class="finding-id">${e(finding.finding_id)}</span>${severityBadge(finding.severity)}${statusBadge(finding.status)}<h2>${e(finding.title)}</h2><p>${e(finding.document)} • ${e(finding.section)}</p></div><button class="icon-close" id="close-drawer" type="button" aria-label="Close finding detail">×</button></div>
    <div class="drawer-content">
      <div class="finding-identity"><span>${e(finding.category)}</span>${confidenceMarkup(finding)}${finding.affected_documents.length > 1 ? `<span class="cross-document">Cross-document • ${finding.affected_documents.length} documents</span>` : ""}</div>
      <section class="detail-section"><span class="section-label">FINDING</span><p>${e(finding.finding)}</p></section>
      <section class="detail-section evidence-section"><span class="section-label">EVIDENCE</span><pre>${e(finding.evidence)}</pre></section>
      <section class="detail-section"><span class="section-label">REQUIREMENT / REVIEW BASIS</span><div class="basis-list">${basisRows.map((basis) => `<article><div><strong>${e(basis.source_name || "Not Available")}</strong><span>${e(basis.source_type || "Not Available")}</span></div><dl><div><dt>Section</dt><dd>${e(basis.section || "Not Available")}</dd></div><div><dt>Clause</dt><dd>${e(basis.clause || "Not Available")}</dd></div></dl><p>${e(basis.text || "Not Available")}</p><span class="reference-status ${slug(basis.verification_status || "Needs Verification")}">${e(basis.verification_status || "Reference Requires Verification")}</span></article>`).join("")}</div></section>
      <section class="detail-section risk-section"><span class="section-label">RISK / IMPACT</span><p>${e(finding.risk_impact)}</p></section>
      <section class="detail-section"><div class="section-heading"><span class="section-label">RECOMMENDED CHANGE</span><span class="ai-label">AI-GENERATED PROPOSAL</span></div>${renderRedlineComparison(finding, "split")}<div class="unified-mini">${renderRedlineComparison(finding, "unified")}</div></section>
      <section class="decision-section">
        <div class="section-heading"><div><span class="section-label">REVIEWER DECISION</span><h3>Human disposition</h3></div>${finding.reviewed_at ? `<p>${e(finding.status)} by ${e(finding.reviewer || "Not Available")}<br><small>${e(timestamp(finding.reviewed_at))}</small></p>` : ""}</div>
        <div class="decision-actions" role="group" aria-label="Reviewer disposition">${actions.map(([value, label]) => `<button type="button" data-disposition="${e(value)}" class="${draft.disposition === value ? "active" : ""}" ${state.saving ? "disabled" : ""}>${e(label)}</button>`).join("")}</div>
        <label><span>Reviewer name / role</span><input id="decision-reviewer" value="${e(draft.reviewer)}" placeholder="e.g., A. Patel, CSV Quality Reviewer"></label>
        ${draft.disposition === "Rejected" ? `<label><span>Structured rejection reason</span><select id="rejection-reason">${optionList(["", "Not Applicable", "Incorrect Interpretation", "Requirement Already Addressed", "Duplicate Finding", "Insufficient Evidence", "Incorrect Severity", "Incorrect Recommendation", "Other"], draft.rejectionReason)}</select></label><label><span>Duplicate of finding (optional)</span><input id="duplicate-of" value="${e(draft.duplicateOf)}" placeholder="e.g., F-002"></label>` : ""}
        ${draft.disposition === "Modified" ? `<label><span>Reviewer-modified recommendation</span><textarea id="modified-recommendation" rows="7">${e(draft.modified)}</textarea></label><label><span>Modification reason</span><select id="modification-reason">${optionList(["", "Technical Accuracy", "Procedure Alignment", "Regulatory Interpretation", "Clarity", "Business Context", "Scope Correction", "Other"], draft.modificationReason)}</select></label>` : ""}
        <label><span>Reviewer comment ${["Rejected", "Needs SME Review"].includes(draft.disposition) ? "(required)" : "(optional)"}</span><textarea id="reviewer-comment" rows="4" placeholder="Record the rationale, context, evidence, or SME question.">${e(draft.comment)}</textarea></label>
        <div class="decision-save"><p id="decision-message">${draft.disposition ? `Save as ${e(draft.disposition)}. The original AI finding and recommendation will remain unchanged.` : "Select a disposition to continue."}</p><button class="primary-button" id="save-decision" type="button" ${!draft.disposition || state.saving ? "disabled" : ""}>${state.saving ? "Saving decision…" : "Save reviewer decision"}</button></div>
      </section>
      ${finding.decision_history?.length ? `<section class="detail-section history-section"><span class="section-label">DECISION HISTORY</span>${[...finding.decision_history].reverse().map((item) => `<article><div>${statusBadge(item.new_status || item.action)}<strong>${e(item.reviewer || "Not Available")}</strong><time>${e(timestamp(item.timestamp))}</time></div><p>${e(item.reviewer_comment || "No comment recorded")}</p></article>`).join("")}</section>` : ""}
    </div>`;
  drawer.querySelector("#close-drawer").addEventListener("click", closeDrawer);
  drawer.querySelectorAll("[data-disposition]").forEach((button) => button.addEventListener("click", () => {
    captureDecisionDraft();
    state.decisionDraft.disposition = button.dataset.disposition;
    state.unsaved = true;
    renderFindingDrawer(finding);
  }));
  drawer.querySelectorAll("input, textarea, select").forEach((control) => control.addEventListener("input", () => {
    captureDecisionDraft();
    state.unsaved = true;
  }));
  drawer.querySelector("#save-decision").addEventListener("click", saveDecision);
}

function captureDecisionDraft() {
  if (!state.decisionDraft) return;
  state.decisionDraft.reviewer = drawer.querySelector("#decision-reviewer")?.value ?? state.decisionDraft.reviewer;
  state.decisionDraft.comment = drawer.querySelector("#reviewer-comment")?.value ?? state.decisionDraft.comment;
  state.decisionDraft.modified = drawer.querySelector("#modified-recommendation")?.value ?? state.decisionDraft.modified;
  state.decisionDraft.rejectionReason = drawer.querySelector("#rejection-reason")?.value ?? state.decisionDraft.rejectionReason;
  state.decisionDraft.modificationReason = drawer.querySelector("#modification-reason")?.value ?? state.decisionDraft.modificationReason;
  state.decisionDraft.duplicateOf = drawer.querySelector("#duplicate-of")?.value ?? state.decisionDraft.duplicateOf;
}

async function saveDecision() {
  if (!state.decisionDraft?.disposition || state.saving) return false;
  captureDecisionDraft();
  const finding = state.report.findings.find((item) => item.finding_id === state.decisionDraft.findingId);
  if (!finding) return false;
  if (state.decisionDraft.disposition === "Rejected" && !state.decisionDraft.comment.trim()) {
    showToast("Enter a rejection rationale before saving.", "error");
    return false;
  }
  if (state.decisionDraft.disposition === "Needs SME Review" && !state.decisionDraft.comment.trim()) {
    showToast("Describe the question that requires SME review.", "error");
    return false;
  }
  if (state.decisionDraft.disposition === "Modified" && !state.decisionDraft.modified.trim()) {
    showToast("Enter the reviewer-modified recommendation.", "error");
    return false;
  }
  state.saving = true;
  renderFindingDrawer(finding);
  try {
    const response = await fetch(`/api/reviews/${encodeURIComponent(state.report.review_id)}/findings/${encodeURIComponent(finding.finding_id)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        disposition: state.decisionDraft.disposition,
        reviewer: state.decisionDraft.reviewer,
        reviewer_comment: state.decisionDraft.comment,
        modified_recommendation: state.decisionDraft.disposition === "Modified" ? state.decisionDraft.modified : "",
        rejection_reason: state.decisionDraft.rejectionReason,
        modification_reason: state.decisionDraft.modificationReason,
        duplicate_of: state.decisionDraft.duplicateOf,
        original_ai_recommendation: finding.proposed_text,
        expected_updated_at: finding.updated_at,
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "The reviewer decision could not be saved.");
    if (state.decisionDraft.reviewer) localStorage.setItem("csvqualreviewer-reviewer", state.decisionDraft.reviewer);
    state.report = payload.report;
    state.unsaved = false;
    state.saving = false;
    state.decisionDraft = null;
    renderReport();
    showToast(`${finding.finding_id} saved as ${payload.finding.status}.`);
    return true;
  } catch (error) {
    state.saving = false;
    renderFindingDrawer(finding);
    showToast(error.message, "error");
    return false;
  }
}

async function closeDrawer() {
  if (!await confirmUnsaved()) return;
  state.selectedFindingId = "";
  state.decisionDraft = null;
  setRoute();
  closeDrawerImmediately();
}

function closeDrawerImmediately() {
  drawer.classList.add("hidden");
  drawerScrim.classList.add("hidden");
  drawer.setAttribute("aria-hidden", "true");
  document.body.classList.remove("drawer-open");
}

async function completeReview() {
  const reviewer = localStorage.getItem("csvqualreviewer-reviewer") || "";
  if (!window.confirm("Complete this human review record? This records completion but does not represent autonomous AI approval.")) return;
  const button = document.querySelector("#complete-review");
  button.disabled = true;
  button.textContent = "Completing review…";
  try {
    const response = await fetch(`/api/reviews/${encodeURIComponent(state.report.review_id)}/complete`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reviewer }) });
    const payload = await response.json();
    if (!response.ok) throw new Error([payload.error, ...(payload.blockers || [])].join(" "));
    state.report = payload.report;
    renderReport();
    showToast("Review completion recorded.");
  } catch (error) {
    renderOverview();
    showToast(error.message, "error");
  }
}

function csvCell(value) {
  const text = Array.isArray(value) ? value.join("; ") : String(value ?? "");
  return `"${text.replace(/"/g, '""')}"`;
}

function download(filename, content, type) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function exportFindings(findings = state.report.findings, filename = `${slug(state.report.package_name)}-findings.csv`) {
  const headers = ["Finding ID", "Severity", "Category", "Document", "Section", "Finding", "Evidence", "Review Basis", "Risk Impact", "AI Recommendation", "AI Confidence", "Status", "Reviewer", "Reviewer Comment", "Reviewer-Modified Recommendation", "Decision Date"];
  const rows = findings.map((finding) => {
    const basis = primaryBasis(finding);
    return [finding.finding_id, finding.severity, finding.category, finding.document, finding.section, finding.finding, finding.evidence, basis.source_name, finding.risk_impact, finding.proposed_text, finding.confidence_score ?? "Not Available", finding.status, finding.reviewer, finding.reviewer_comment, finding.modified_recommendation, finding.reviewed_at].map(csvCell).join(",");
  });
  download(filename, [headers.map(csvCell).join(","), ...rows].join("\n"), "text/csv;charset=utf-8");
}

function exportDecisionLog() {
  const headers = ["Finding ID", "Severity", "Document", "AI Recommendation", "Reviewer Decision", "Reviewer Comment", "Reviewer", "Decision Date", "Modified Recommendation", "Rejection Reason", "Modification Reason"];
  const rows = state.report.findings.filter((finding) => finding.status !== "Open").map((finding) => [finding.finding_id, finding.severity, finding.document, finding.proposed_text, finding.status, finding.reviewer_comment, finding.reviewer, finding.reviewed_at, finding.modified_recommendation, finding.rejection_reason, finding.modification_reason].map(csvCell).join(","));
  download(`${slug(state.report.package_name)}-reviewer-decision-log.csv`, [headers.map(csvCell).join(","), ...rows].join("\n"), "text/csv;charset=utf-8");
}

function exportTraceability() {
  const headers = ["Finding", "Severity", "Document", "Section", "Requirement / Review Basis", "Reference Status", "Proposed Change", "Reviewer Decision"];
  const rows = state.report.findings.map((finding) => {
    const basis = primaryBasis(finding);
    return [finding.finding_id, finding.severity, finding.document, finding.section, basis.source_name, basis.verification_status, finding.proposed_text, finding.status].map(csvCell).join(",");
  });
  download(`${slug(state.report.package_name)}-traceability.csv`, [headers.map(csvCell).join(","), ...rows].join("\n"), "text/csv;charset=utf-8");
}

function exportReviewReport() {
  const report = state.report;
  const metrics = calculateMetrics(report.findings);
  const provenance = report.review_provenance || {};
  const html = `<!doctype html><html><head><meta charset="utf-8"><title>${e(report.package_name)} Review Report</title><style>body{font:14px/1.55 Arial,sans-serif;color:#17231e;max-width:1050px;margin:40px auto;padding:0 24px}h1,h2,h3{font-family:Georgia,serif}table{width:100%;border-collapse:collapse}th,td{border:1px solid #ccd5d0;padding:8px;text-align:left;vertical-align:top}.finding{border:1px solid #ccd5d0;padding:18px;margin:18px 0;break-inside:avoid}.label{font-size:11px;font-weight:bold;color:#52645b;letter-spacing:.08em}.ai{background:#f3f7f5;padding:12px}.human{background:#eef5ff;padding:12px}.badge{font-weight:bold}</style></head><body><p class="label">CSVQUALREVIEWER CONTROLLED REVIEW REPORT</p><h1>${e(report.package_name)}</h1><p><strong>Review Run:</strong> ${e(report.review_id)}<br><strong>Status:</strong> ${e(report.review_workflow.status)}<br><strong>Package Readiness:</strong> ${e(report.review_workflow.package_readiness)}</p><h2>Review provenance</h2><table>${Object.entries(provenance).map(([key, value]) => `<tr><th>${e(key.replaceAll("_", " "))}</th><td>${e(value)}</td></tr>`).join("")}</table><h2>Documents reviewed</h2><ul>${(report.document_summaries || []).map((doc) => `<li>${e(doc.document_name)} — ${plural(doc.finding_count, "finding")}, highest unresolved: ${e(doc.highest_unresolved_severity)}</li>`).join("")}</ul><h2>Executive summary</h2><p>${e(report.executive_assessment?.basis || "Not Available")}</p><p>Critical: ${metrics.severity_counts.Critical} • Major: ${metrics.severity_counts.Major} • Minor: ${metrics.severity_counts.Minor} • Observation: ${metrics.severity_counts.Observation}</p><h2>Detailed findings and decisions</h2>${report.findings.map((finding) => `<article class="finding"><p class="label">${e(finding.finding_id)} • ${e(finding.severity)} • ${e(finding.category)}</p><h3>${e(finding.title)}</h3><p><strong>Document / Section:</strong> ${e(finding.document)} / ${e(finding.section)}</p><p><strong>Finding:</strong> ${e(finding.finding)}</p><p><strong>Evidence:</strong> ${e(finding.evidence)}</p><p><strong>Risk / Impact:</strong> ${e(finding.risk_impact)}</p><div class="ai"><span class="label">AI GENERATED CONTENT</span><p>${e(finding.proposed_text)}</p><p>AI Confidence: ${e(finding.confidence_score ?? "Not Available")}${finding.confidence_score != null ? "%" : ""}</p></div><div class="human"><span class="label">REVIEWER DECISION</span><p><strong>${e(finding.status)}</strong> by ${e(finding.reviewer || "Not Available")} on ${e(timestamp(finding.reviewed_at))}</p><p>${e(finding.reviewer_comment || "No reviewer comment recorded")}</p>${finding.modified_recommendation ? `<p><strong>Reviewer-modified recommendation:</strong> ${e(finding.modified_recommendation)}</p>` : ""}</div></article>`).join("")}<h2>Open actions and SME items</h2><ul>${report.findings.filter((finding) => !["Rejected", "Resolved"].includes(finding.status)).map((finding) => `<li>${e(finding.finding_id)} — ${e(finding.status)} — ${e(finding.title)}</li>`).join("") || "<li>None</li>"}</ul><p><strong>Review completion status:</strong> ${e(report.review_workflow.status)}</p></body></html>`;
  download(`${slug(report.package_name)}-review-report.html`, html, "text/html;charset=utf-8");
}

function exportRedlinedDocument() {
  const document = state.report.redlined_documents?.[state.selectedRedline] || state.report.redlined_documents?.[0];
  if (!document) return showToast("No redlined document is available to export.", "error");
  const related = state.report.findings.filter((finding) => document.finding_ids?.includes(finding.finding_id) || finding.affected_documents.some((item) => item.document_name === document.document_name));
  const accepted = related.filter((finding) => acceptedChangeForFinding(finding));
  const html = `<!doctype html><html><head><meta charset="utf-8"><title>${e(document.document_name)} Reviewed Redline</title><style>body{font:14px/1.6 Arial,sans-serif;max-width:1000px;margin:40px auto;padding:0 24px;color:#17231e}pre{white-space:pre-wrap;border:1px solid #d2dbd6;background:#f8faf9;padding:16px}article{border-top:1px solid #ccd5d0;padding:16px 0}del{background:#ffe9e9;color:#8a2222}ins{background:#e4f6ea;color:#145f35;text-decoration:none}.label{font-size:11px;font-weight:bold;letter-spacing:.08em;color:#56665e}</style></head><body><p class="label">CSVQUALREVIEWER REVIEWED DOCUMENT REDLINE</p><h1>${e(document.document_name)}</h1><p>Review Run: ${e(state.report.review_id)} • Source document preserved • Rejected recommendations excluded</p><h2>Immutable extracted source</h2><pre>${e(document.source_text || "Not Available")}</pre><h2>Reviewer-accepted change set</h2>${accepted.map((finding) => `<article><p class="label">${e(finding.finding_id)} • ${e(finding.status)}</p><h3>${e(finding.title)}</h3><p><strong>Original:</strong> ${e(finding.original_text)}</p><p><strong>Final accepted wording:</strong> ${e(acceptedChangeForFinding(finding))}</p><p><strong>Reviewer:</strong> ${e(finding.reviewer || "Not Available")} • ${e(timestamp(finding.reviewed_at))}</p></article>`).join("") || "<p>No accepted or modified recommendations are available for incorporation. The source remains unchanged.</p>"}<h2>Disposition note</h2><p>${related.filter((finding) => finding.status === "Rejected").length} rejected recommendation(s) were deliberately excluded. Modified findings use reviewer-modified wording.</p></body></html>`;
  download(`${slug(document.document_name)}-reviewed-redline.html`, html, "text/html;charset=utf-8");
}

async function handleExport(type) {
  exportPopover.classList.add("hidden");
  exportButton.setAttribute("aria-expanded", "false");
  if (type === "report") exportReviewReport();
  else if (type === "findings") exportFindings();
  else if (type === "redline") exportRedlinedDocument();
  else if (type === "decisions") exportDecisionLog();
  else if (type === "traceability") exportTraceability();
  else if (type === "json") download(`${slug(state.report.package_name)}-${state.report.review_id}.json`, JSON.stringify(state.report, null, 2), "application/json;charset=utf-8");
  fetch(`/api/reviews/${encodeURIComponent(state.report.review_id)}/exports`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ export_type: type, reviewer: localStorage.getItem("csvqualreviewer-reviewer") || "" }) }).catch(() => {});
  showToast("Export generated from the current controlled review record.");
}

async function restoreLatestReview() {
  renderInitialLoading();
  try {
    const route = parseRoute();
    let report = null;
    if (route.reviewId) {
      const response = await fetch(`/api/reviews/${encodeURIComponent(route.reviewId)}`);
      if (response.ok) report = await response.json();
    }
    if (!report) {
      const response = await fetch("/api/reviews/latest");
      if (response.ok) report = (await response.json()).review;
    }
    if (report) {
      if (route.view === "upload") {
        state.report = null;
        state.view = "upload";
        return renderEmpty();
      }
      state.report = report;
      state.packageName = report.package_name;
      const supportedViews = ["home", "overview", "findings", "documents", "traceability", "redlines", "decisions", "chat", "history", "feedback", "references", "templates", "sops", "golden", "guidance", "org-admin", "platform-admin"];
      state.view = route.view && supportedViews.includes(route.view) ? route.view : "home";
      state.selectedFindingId = route.findingId || "";
      setRoute(true);
      renderReport();
    } else {
      state.view = route.view === "upload" ? "upload" : "home";
      renderReport();
    }
  } catch (error) {
    state.view = "home";
    renderReport();
    showToast("The latest review could not be restored. Start a new review or try again.", "error");
  }
}

document.querySelectorAll(".nav-item").forEach((button) => button.addEventListener("click", () => {
  if (button.id === "new-review") return;
  navigate(button.dataset.view);
}));
async function beginNewReview() {
  if (!await confirmUnsaved()) return;
  if (state.report && !window.confirm("Start a new document review? The current controlled review remains saved and can be reopened from Run History.")) return;
  state.files = [];
  state.packageName = "";
  state.documentType = "";
  state.report = null;
  state.view = "upload";
  state.filters = { query: "", severity: "All", category: "All", document: "All", status: "All", confidence: "All" };
  renderEmpty();
}
document.querySelector("#new-review").addEventListener("click", beginNewReview);
fileInput.addEventListener("change", () => { addFiles([...fileInput.files]); fileInput.value = ""; });
exportButton.addEventListener("click", (event) => {
  event.stopPropagation();
  exportPopover.classList.toggle("hidden");
  exportButton.setAttribute("aria-expanded", String(!exportPopover.classList.contains("hidden")));
});
document.querySelectorAll("[data-export]").forEach((button) => button.addEventListener("click", () => handleExport(button.dataset.export)));
document.addEventListener("click", (event) => { if (!exportPopover.contains(event.target) && event.target !== exportButton) { exportPopover.classList.add("hidden"); exportButton.setAttribute("aria-expanded", "false"); } });
drawerScrim.addEventListener("click", closeDrawer);
window.addEventListener("beforeunload", (event) => { if (state.unsaved) { event.preventDefault(); event.returnValue = ""; } });
window.addEventListener("popstate", async () => {
  if (!await confirmUnsaved()) return setRoute(true);
  const route = parseRoute();
  if (!route.reviewId || route.reviewId === state.report?.review_id) {
    state.view = route.view || "home";
    state.selectedFindingId = route.findingId || "";
    state.decisionDraft = null;
    renderReport();
  }
});

document.querySelector("#ask-csvqualreviewer").addEventListener("click", () => navigate("chat"));
document.querySelector("#sidebar-toggle").addEventListener("click", () => document.body.classList.toggle("sidebar-collapsed"));
document.querySelectorAll(".notification-button, .profile-button, .topbar-icon[aria-label='Help']").forEach((button) => button.addEventListener("click", () => showToast("This demo control is ready for your organization integration.")));
const globalSearch = document.querySelector("#global-search");
workspace.addEventListener("click", (event) => {
  const target = event.target.closest("[data-review-nav]");
  if (target) navigate(target.dataset.reviewNav);
});
document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    globalSearch.focus();
  }
});
globalSearch.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  const query = globalSearch.value.trim().toLowerCase();
  if (!query) return;
  if (query.includes("finding") && state.report) navigate("findings");
  else if ((query.includes("document") || query.includes("report")) && state.report) navigate("documents");
  else showToast(`Search ready for “${globalSearch.value.trim()}”. Connect organization indexing to return cross-workspace results.`);
});

restoreLatestReview();
