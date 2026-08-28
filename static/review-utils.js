(function attachReviewUtilities(root, factory) {
  const utilities = factory();
  if (typeof module === "object" && module.exports) module.exports = utilities;
  if (root) root.CSVQualReviewerUtils = utilities;
}(typeof window !== "undefined" ? window : globalThis, function createReviewUtilities() {
  "use strict";

  const SEVERITIES = ["Critical", "Major", "Minor", "Observation"];
  const STATUSES = ["Open", "Accepted", "Rejected", "Modified", "Deferred", "Needs SME Review", "Resolved"];
  const severityRank = { Critical: 0, Major: 1, Minor: 2, Moderate: 2, Observation: 3 };
  const statusRank = { Open: 0, "Needs SME Review": 1, Deferred: 2, Accepted: 3, Modified: 4, Rejected: 5, Resolved: 6 };

  function normalizeFinding(value, index = 0) {
    const finding = { ...value };
    finding.finding_id = finding.finding_id || finding.display_id || finding.displayId || `F-${String(index + 1).padStart(3, "0")}`;
    finding.display_id = finding.display_id || finding.finding_id;
    finding.severity = finding.severity === "Moderate" ? "Minor" : (SEVERITIES.includes(finding.severity) ? finding.severity : "Observation");
    finding.status = STATUSES.includes(finding.status) ? finding.status : "Open";
    finding.category = finding.category || finding.finding_category || "Not Classified";
    finding.title = finding.title || finding.finding || finding.observation || finding.category;
    finding.finding = finding.finding || finding.observation || "Finding details are not available in this historical record.";
    finding.evidence = finding.evidence || finding.source_text || "Not Available";
    finding.risk_impact = finding.risk_impact || finding.riskImpact || finding.impact || "Not Available";
    finding.original_text = finding.original_text || finding.originalText || finding.evidence;
    finding.proposed_text = finding.proposed_text || finding.proposedText || finding.suggested_redline || finding.recommended_action || "Not Available";
    finding.document = finding.document || finding.documentName || "Not Available";
    finding.section = finding.section || finding.location || "Not Available";
    finding.review_basis = finding.review_basis || finding.reviewBasis || [];
    finding.affected_documents = finding.affected_documents || finding.affectedDocuments || [{
      document_id: finding.document_id || finding.document,
      document_name: finding.document,
      section: finding.section,
    }];
    finding.confidence_score = Number.isFinite(Number(finding.confidence_score)) ? Number(finding.confidence_score) : null;
    finding.reviewer_comment = finding.reviewer_comment || "";
    finding.modified_recommendation = finding.modified_recommendation || "";
    finding.decision_history = finding.decision_history || [];
    finding.reviewer_comments = finding.reviewer_comments || [];
    return finding;
  }

  function confidenceBand(finding) {
    const score = Number(finding.confidence_score);
    if (!Number.isFinite(score)) return "Not Available";
    if (score >= 90) return "High";
    if (score >= 70) return "Medium";
    return "Low";
  }

  function calculateMetrics(values) {
    const findings = values.map(normalizeFinding);
    const severity_counts = Object.fromEntries(SEVERITIES.map((severity) => [severity, 0]));
    const status_counts = Object.fromEntries(STATUSES.map((status) => [status, 0]));
    findings.forEach((finding) => {
      severity_counts[finding.severity] += 1;
      status_counts[finding.status] += 1;
    });
    return {
      findings: findings.length,
      severity_counts,
      status_counts,
      open_findings: findings.filter((finding) => !["Rejected", "Resolved"].includes(finding.status)).length,
    };
  }

  function filterFindings(values, filters = {}) {
    const query = String(filters.query || "").trim().toLowerCase();
    return values.map(normalizeFinding).filter((finding) => {
      const documents = finding.affected_documents.map((item) => item.document_name).filter(Boolean);
      const searchable = [
        finding.finding_id,
        finding.title,
        finding.finding,
        finding.document,
        ...documents,
        finding.category,
        finding.section,
      ].join(" ").toLowerCase();
      return (!filters.severity || filters.severity === "All" || finding.severity === filters.severity)
        && (!filters.category || filters.category === "All" || finding.category === filters.category)
        && (!filters.document || filters.document === "All" || documents.includes(filters.document) || finding.document === filters.document)
        && (!filters.status || filters.status === "All" || finding.status === filters.status)
        && (!filters.confidence || filters.confidence === "All" || confidenceBand(finding) === filters.confidence)
        && (!query || searchable.includes(query));
    });
  }

  function sortFindings(values, sort = "risk") {
    const findings = [...values];
    const byId = (left, right) => left.finding_id.localeCompare(right.finding_id, undefined, { numeric: true });
    const comparators = {
      risk: (left, right) => {
        const leftClosed = ["Rejected", "Resolved"].includes(left.status) ? 1 : 0;
        const rightClosed = ["Rejected", "Resolved"].includes(right.status) ? 1 : 0;
        return leftClosed - rightClosed || severityRank[left.severity] - severityRank[right.severity] || byId(left, right);
      },
      severity: (left, right) => severityRank[left.severity] - severityRank[right.severity] || byId(left, right),
      document: (left, right) => left.document.localeCompare(right.document) || byId(left, right),
      id: byId,
      confidence: (left, right) => (right.confidence_score ?? -1) - (left.confidence_score ?? -1) || byId(left, right),
      status: (left, right) => statusRank[left.status] - statusRank[right.status] || byId(left, right),
      newest: (left, right) => String(right.created_at || "").localeCompare(String(left.created_at || "")),
      oldest: (left, right) => String(left.created_at || "").localeCompare(String(right.created_at || "")),
    };
    return findings.sort(comparators[sort] || comparators.risk);
  }

  function acceptedChangeForFinding(value) {
    const finding = normalizeFinding(value);
    if (["Rejected", "Open", "Deferred", "Needs SME Review"].includes(finding.status)) return null;
    if (finding.status === "Modified") return finding.modified_recommendation || null;
    if (["Accepted", "Resolved"].includes(finding.status)) {
      return finding.modified_recommendation || finding.proposed_text;
    }
    return null;
  }

  return {
    SEVERITIES,
    STATUSES,
    severityRank,
    statusRank,
    normalizeFinding,
    confidenceBand,
    calculateMetrics,
    filterFindings,
    sortFindings,
    acceptedChangeForFinding,
  };
}));
