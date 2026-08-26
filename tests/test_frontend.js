"use strict";

const assert = require("node:assert/strict");
const utils = require("../static/review-utils.js");

const findings = [
  { finding_id: "F-001", severity: "Critical", category: "Validation Evidence", document: "VSR.txt", section: "Conclusion", observation: "Open failed test contradicts release.", confidence_score: 98, status: "Open", affected_documents: [{ document_name: "VSR.txt" }] },
  { finding_id: "F-002", severity: "Major", category: "Deviation Handling", document: "OQ.txt", section: "6", observation: "Closure criteria are missing.", confidence_score: 91, status: "Accepted", affected_documents: [{ document_name: "OQ.txt" }] },
  { finding_id: "F-003", severity: "Minor", category: "Configuration Management", document: "OQ.txt", section: "Prerequisites", observation: "Baseline is not named.", confidence_score: 82, status: "Modified", proposed_text: "Name the approved baseline.", modified_recommendation: "Name CFG-002 and attach comparison evidence.", affected_documents: [{ document_name: "OQ.txt" }] },
  { finding_id: "F-004", severity: "Observation", category: "Editorial", document: "OQ.txt", section: "Multiple", observation: "Repeated wording.", confidence_score: 61, status: "Rejected", proposed_text: "Consolidate wording.", affected_documents: [{ document_name: "OQ.txt" }] },
];

assert.equal(utils.filterFindings(findings, { severity: "Major" }).length, 1);
assert.equal(utils.filterFindings(findings, { status: "Modified" })[0].finding_id, "F-003");
assert.equal(utils.filterFindings(findings, { category: "Editorial" })[0].finding_id, "F-004");
assert.equal(utils.filterFindings(findings, { document: "VSR.txt" })[0].finding_id, "F-001");
assert.equal(utils.filterFindings(findings, { confidence: "High" }).length, 2);
assert.equal(utils.filterFindings(findings, { query: "baseline" })[0].finding_id, "F-003");
assert.equal(utils.filterFindings(findings, {}).length, 4);

const metrics = utils.calculateMetrics(findings);
assert.deepEqual(metrics.severity_counts, { Critical: 1, Major: 1, Minor: 1, Observation: 1 });
assert.equal(metrics.status_counts.Accepted, 1);
assert.equal(utils.sortFindings(findings, "risk")[0].finding_id, "F-001");

assert.equal(utils.acceptedChangeForFinding(findings[1]), findings[1].proposed_text || "Not Available");
assert.equal(utils.acceptedChangeForFinding(findings[2]), "Name CFG-002 and attach comparison evidence.");
assert.equal(utils.acceptedChangeForFinding(findings[3]), null);

const historical = utils.normalizeFinding({ finding_id: "OLD-1", severity: "Moderate", observation: "Legacy record" });
assert.equal(historical.severity, "Minor");
assert.equal(historical.category, "Not Classified");
assert.equal(historical.status, "Open");
assert.equal(historical.confidence_score, null);

console.log("Frontend review utilities: 18 assertions passed.");
