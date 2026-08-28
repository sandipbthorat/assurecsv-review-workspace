# CSVQualReviewer Enterprise Readiness

CSVQualReviewer is designed as human-in-the-loop decision support for computerized-system validation review. It preserves the distinction between AI-generated recommendations and accountable reviewer decisions. Production use in a regulated process still requires organization-specific intended-use validation, change control, access control, retention, and operating procedures.

## Implemented control foundation

- Deterministic staged review instead of a single opaque prompt.
- Immutable extracted source text separated from proposed wording and reviewer-approved changes.
- Controlled Critical, Major, Minor, and Observation severity levels.
- Explicit Accept, Reject, Modify, Defer, Needs SME Review, and Resolve dispositions.
- Reviewer identity, rationale, timestamps, modification history, and completion blockers.
- Forward, backward, and risk-to-test traceability with exportable records.
- Atomic local persistence for review records and controlled feedback precedents.
- Versioned review-engine and ruleset provenance on newly generated runs.
- Request-size boundaries, path traversal protection, restrictive CSP, anti-framing headers, permissions restrictions, and no-cache API responses.
- Correlation IDs in every HTTP response and request log for operational troubleshooting.

## Recommended production architecture

1. Place the application behind an enterprise ingress or reverse proxy providing TLS 1.2+, approved cipher policy, request throttling, WAF controls, and centralized access logs.
2. Integrate enterprise SSO with MFA and organization-scoped RBAC. Do not treat the local demonstration identity as authentication.
3. Replace local JSON persistence with an access-controlled transactional datastore supporting backups, retention locks, disaster recovery, and tenant isolation.
4. Store uploaded documents and generated artifacts in encrypted organization-managed object storage with malware scanning and lifecycle policies.
5. Route application, audit, security, performance, and cost telemetry to the organization’s approved monitoring and SIEM platform using the emitted correlation ID.
6. Deploy asynchronous workers and a durable queue before supporting concurrent enterprise review volume.
7. Keep approved references, review configurations, model assignments, and activation history in version-controlled governed stores.

## Validation and release gates

- Define intended use, GxP scope, electronic-record applicability, and the advisory-only boundary.
- Establish a version-controlled benchmark dataset with adjudicated findings.
- Verify critical-issue recall, false-positive rate, citation accuracy, and checklist coverage by document type and severity.
- Test positive, negative, boundary, error-handling, authorization, tenant-isolation, recovery, retention, and audit scenarios.
- Validate exports, reviewer decision history, historical reproducibility, reference revision control, and the absence of silent evidence substitution.
- Qualify infrastructure, operating procedures, backup/restore, monitoring, incident handling, change management, and periodic review.

## Operational configuration

The dependency-free local service uses secure workstation defaults:

```bash
CSVQUALREVIEWER_HOST=127.0.0.1 CSVQUALREVIEWER_PORT=8765 .venv/bin/python app.py
```

Binding to a non-loopback interface does not make the built-in server an enterprise perimeter. Use an approved production hosting stack and the controls above before external exposure.
