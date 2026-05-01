<!--
Permissions redesign (006) enforces TDD + security review.
Every section below is mandatory. PRs missing fields will not be merged.
-->

## Summary

<!-- 1-3 bullets describing the change. -->
-
-

## Related issue / Spec

<!-- Link to issue, or to spec file under specs/NNN-*/. Required. -->
- Issue / Spec:

## TDD Red phase (PR-006, NON-NEGOTIABLE)

Evidence that tests were written first and failed before implementation.

- [ ] Test commit pushed first, CI ran Red
- [ ] CI Red run URL: `<paste URL>`
- [ ] Implementation commit pushed next, CI ran Green
- [ ] CI Green run URL: `<paste URL>`

## Mutation testing score (PR-004)

Threshold >= 80% for every permission-critical module touched (or transitively covered) by this PR.

| Module | Score | Threshold | Status |
|---|---|---|---|
| `core/permissions.py` | % | 80% | PASS / FAIL |
| `core/response_filter.py` | % | 80% | PASS / FAIL |
| `services/search_gate.py` | % | 80% | PASS / FAIL |
| `core/audit.py` | % | 80% | PASS / FAIL |

## Coverage (PR-005)

- Permission modules (`core/permissions.py`, `core/response_filter.py`, `services/search_gate.py`, `core/audit.py`): >= 95%
- Other modules: >= 85%

## Security test IDs (PR-007)

Tick every OWASP-aligned category this PR touches and list the corresponding tests under `apps/api/tests/security/`.

- [ ] SEC-01 Broken Access Control — tests:
- [ ] SEC-02 Cryptographic Failures — tests:
- [ ] SEC-03 Injection — tests:
- [ ] SEC-04 Insecure Design — tests:
- [ ] SEC-05 Security Misconfiguration — tests:
- [ ] SEC-06 Vulnerable and Outdated Components — tests:
- [ ] SEC-07 Identification and Authentication Failures — tests:
- [ ] SEC-08 Software and Data Integrity Failures — tests:
- [ ] SEC-09 Security Logging and Monitoring Failures — tests:
- [ ] SEC-10 Server-Side Request Forgery — tests:
- [ ] SEC-11 Sensitive Data Exposure (lat/lng, tokens, 2FA secrets) — tests:

## Breaking changes

- [ ] No
- [ ] Yes — description:

## Rollback plan

<!-- One or two lines: how to revert if this breaks production. -->

## Reviewer checklist

Security reviewer ticks these before applying the `security-approved` label.

- [ ] Red -> Green transition visible in CI history
- [ ] No raw lat/lng in any new endpoint response
- [ ] `apply_response_filter` used for Recording / Detection / Site responses
- [ ] Permission guard (`check_action`) on every new endpoint
- [ ] Audit log entries added for state-changing ops
- [ ] Approved by Security review label
