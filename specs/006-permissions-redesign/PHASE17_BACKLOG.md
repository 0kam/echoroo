# Phase 17 Backlog (xfail / warn-only / deferred items)

**Branch**: `006-permissions-redesign`
**Created**: 2026-05-01 (Phase 16 Batch 6h-4, T999)
**Owner**: Phase 17 driver

This document aggregates every `xfail` / `warn-only` / Phase 17 deferred item
introduced during Phase 16 Batches 6f / 6g / 6h. It is the single canonical
list reviewed at Phase 17 kickoff. Each ticket records:

- **Task ID** — links back to `tasks.md` for the originating Phase 16 entry.
- **Threat** — security / coverage / mutation / runbook / docs gap.
- **Expected behavior** — what the test will assert when the gap closes.
- **Release condition** — concrete checklist that must all be true to remove
  the `xfail` / warn-only marker.

When closing a ticket, **also remove the `@pytest.mark.xfail(strict=True)` /
`PHASE17_PENDING` entry** so the gate flips to a hard fail going forward.

---

## A. Security `xfail` (Phase 16 Batch 6f origin)

These were filed in Phase 16 Batch 6f as TDD-red specifications. The test
already exists in `apps/api/tests/security/**` and is marked
`xfail(strict=True)` with a forward-reference docstring.

### A-5. Streaming endpoint permission re-check (Hybrid Contract)
- **Task**: T973
- **File**: `apps/api/tests/security/race_conditions/test_streaming_permission_change.py`
- **xfail count**: 1 (closed in this PR)
- **Threat**: A long-running CSV / audio stream started before a permission
  revoke continues serving until the stream closes (security H-6).
- **Hybrid Contract** (Phase 17 A-5):
  - **pre-start revoke**: protected stream endpoints run the normal permission
    gate before creating a `StreamingResponse` and return HTTP 403 when denied.
  - **post-start revoke**: status / headers are already on the wire and CANNOT
    be changed. Guarded streams re-check at documented guard boundaries; a
    revoke detected after response start MUST stop yielding protected data,
    write `stream.permission_revoked_mid_stream` audit telemetry, and
    terminate the stream. CSV streams MAY append the sentinel
    `\r\n--PERMISSION-REVOKED--\r\n` so a human/audit reader detects truncation;
    binary audio streams terminate without a sentinel (would corrupt media).
  - **Range responses** are explicitly pre-start guarded only; not covered
    by mid-stream re-check (single-shot `Response`).
- **Release condition**:
  - [x] CSV export (`detection_export.export_csv` + `api/v1/search/sessions.py`
        export path) uses row-by-row streaming guard at configured boundaries.
  - [x] `export_csv(..., search_session_id=...) -> str` signature preserved
        for back-compat with existing `tests/security/search_leak/test_export_csv_no_lat_lng.py:375` etc.
  - [x] Audio full-file streaming paths (`_iter_ogg` / `_iter_file`) are
        guarded at `AUDIO_RECHECK_INTERVAL=8` chunks. Range and generated clip
        `Response` paths are documented as pre-start only.
  - [x] `xfail` removed from `test_streaming_permission_change.py`; tests PASS.

### A-8. DEK rewrap + KMS isolation
- **Task**: T979e
- **File**: `apps/api/tests/security/crypto/test_dek_rewrap_and_kms_isolation.py`
- **xfail count**: 1 (+ 1 skip)
- **Threat**: Direct KMS calls outside `core/kms.py` bypass the alias-isolation
  guard; key material rewrap path may leak DEK to logs (FR-091b, OWASP A02 / A08).
- **Expected behavior**: Static lint + runtime guard ensures only `core/kms.py`
  invokes the boto3 KMS client; DEK rewrap operates on opaque ciphertext
  only.
- **Release condition**:
  - [ ] `scripts/lint_kms_isolation.py` runs in strict mode and passes.
  - [ ] `xfail` + `skip` removed; tests PASS.

### A-13. Operator free-form fields: PII / email plaintext detector
- **Origin**: A-11 close review Round 1-9 carry-over. The operator
  `reason` and `support_ticket_id` fields accept arbitrary strings; an
  operator may paste a target user's email or other PII, which then
  reaches `platform_audit_log.detail.reason_excerpt` in plaintext.
- **Threat**: PII leakage into long-retained audit rows breaches the
  PII-hash contract (FR-091a) for incidental operator-supplied content.
- **Release condition**:
  - [ ] Lightweight detector that flags plausible email addresses /
        phone numbers / national IDs in operator free-form fields and
        either rejects the request (P1) or auto-redacts before audit
        write (P2).
  - [ ] Admin UI helper text discouraging PII paste-in.

---

## B. Pre-existing Phase 1-15 `xfail`

### B-1. Superuser response-filter raw forbidden
- **File**: `apps/api/tests/security/authorization/test_superuser_response_filter_raw_forbidden.py`
- **xfail count**: indicated in module docstring ("not yet implemented in Phase 15")
- **Threat**: Superusers currently bypass the response filter and may receive
  raw lat/lng/coordinate keys (FR-112a, SC-016).
- **Expected behavior**: Even superuser principals are subject to
  `ResponseFilter`; explicit raw access is a separate Path-Operation switch.
- **Release condition**:
  - [ ] `core/response_filter.py` removes the superuser short-circuit.
  - [ ] `xfail` removed; tests PASS.

### B-2. Upload EXIF + S3 metadata strip
- **File**: `apps/api/tests/security/authorization/test_upload_exif_and_s3_metadata_strip.py`
- **xfail count**: indicated where current implementation has gaps.
- **Threat**: EXIF GPS / S3 user-metadata coordinates leak (FR-028a).
- **Expected behavior**: Upload pipeline strips EXIF GPS tags and S3
  user-defined metadata containing coordinate keys before persisting.
- **Release condition**:
  - [ ] EXIF strip + S3 metadata sanitizer wired pre-upload.
  - [ ] `xfail` markers removed; tests PASS.

### B-3. Search-index ready toggle (T981b residual)
- **File**: `apps/api/tests/security/search_leak/test_search_index_ready_on_toggle_on.py`
- **xfail status**: NONE remaining as of Batch 6g-2 R2; listed here for
  awareness only — the file appeared in the 6f xfail grep but the actual
  markers were removed when the fixture trigger landed.

---

## C. Coverage `PHASE17_PENDING` + `backend-tests` warn-ratchet (Batch 6h-2 origin)

The `scripts/check_coverage_threshold.py` script ships with a
`PHASE17_PENDING` frozenset of ~90 modules whose statement coverage is below
the 95% / 85% threshold. They are **warn-only** rather than hard-fail.

In addition, the enclosing `backend-tests` CI job in
`.github/workflows/ci.yml` runs with **`continue-on-error: true`** in
Phase 16, so a coverage gate failure (or a pre-existing test failure) only
surfaces as a yellow-warn in the PR check summary. The Phase 16 close
report calls this **warn-ratchet** posture.

- **Task**: T996
- **Threat**: Coverage gaps mean regressions land without a failing test
  (PR-005, SC-013). The job-level `continue-on-error: true` further means
  a regression that drops a permission-critical module below 95% does
  not block the PR until Phase 17 promotes the gate.
- **Expected behavior**: Each pending module reaches its tier threshold
  (permission-critical → 95%, all other → 85%); the `backend-tests` job
  itself becomes a hard fail on every push.
- **Release condition (per module)**:
  - [ ] Dedicated test file or integration suite added.
  - [ ] Module removed from `PHASE17_PENDING` in
        `scripts/check_coverage_threshold.py`.
  - [ ] CI green at hard-fail mode.
- **Release condition (job-level promotion)**:
  - [ ] Pre-existing test failures (33F + 94E baseline as of 2026-05-01)
        burnt down or quarantined into a dedicated `slow` / xfail suite.
  - [ ] Postgres testcontainer fixture stabilised on GitHub-hosted runners
        (or migrated to a service container).
  - [ ] `continue-on-error: true` deleted from the `backend-tests` job in
        `.github/workflows/ci.yml`.

The full list of ~90 modules is enumerated inline in the script under
`PHASE17_PENDING: frozenset[str]`. Phase 17 should triage by directory
(API routers → integration suite, services → service-level fixture suite, ML →
GPU-backed fixture decision).

---

## D. Mutation-testing `--warn-only` allowlist + `mutation-testing` job
       trigger gate (Batch 6h-1 origin)

The `mutation-testing` CI job currently only runs when one of three
conditions holds:
  a) main branch push,
  b) the `run-mutation-testing` PR label is attached, OR
  c) the workflow is dispatched manually from the Actions UI.
That makes it a **warn-ratchet** in Phase 16: when the job runs it is a
hard-fail (`continue-on-error` is not set), but a default PR build does
not exercise it.

- **Task**: T995
- **File**: `apps/api/mutmut.toml` (`paths_to_mutate` lists 11 modules) +
  `.github/workflows/ci.yml` (`mutation-testing` job `if:` guard).
- **Threat**: Surviving mutants in permission-critical modules indicate
  weak test assertions (PR-004, SC-012). The trigger gate further means
  a PR can land that introduces a regression in mutation score without
  CI ever exercising mutmut against the candidate.
- **Expected behavior**: Each of the 11 modules reaches **≥80% mutation
  score**, and the `mutation-testing` job runs on every push.
- **Release condition (per module)**:
  - [ ] Each surviving mutant analysed; new test added or mutant proven
        equivalent.
  - [ ] `scripts/check_mutation_score.py --threshold 80` exits 0 against
        the full module list without `--warn-only`.
- **Release condition (job-level promotion)**:
  - [ ] `if:` guard on the `mutation-testing` job loosened to fire on
        every push (delete the conditional). Operators continue to
        retain `workflow_dispatch` for manual runs.
  - [ ] Mutmut runtime profiled and confirmed acceptable for default PR
        latency; otherwise split into "fast" (≤2 modules per PR) +
        "full" (post-merge nightly) jobs.

---

## E. Runbook `requires_runbook` marker (Batch 6h-3 origin)

- **Task**: T998
- **File**: `apps/api/tests/runbook/test_quickstart_phase3_smoke.py` (the
  single `requires_runbook` test inside)
- **Threat**: Quickstart §3 bootstrap (`wipe_database` / `init_superuser` /
  `initial_iucn_sync` / `seed_moe_rdb`) end-to-end flow is not exercised in CI;
  silent regression risk (FR-113, FR-114).
- **Expected behavior**: A live-infra E2E that boots a temporary Compose
  stack, runs the four scripts in order, and asserts the resulting DB state.
- **Release condition**:
  - [ ] CI job (Phase 17 infra task) provisions the live infra stack.
  - [ ] `requires_runbook` marker removed or promoted to hard gate by adding
        a dedicated CI job that runs `pytest -m requires_runbook`.

---

## F. Traceability orphan (Batch 6h-4, this batch)

- **Task**: T999
- **Symptom**: `scripts/check_traceability.py` reports 1 informational orphan
  (`FR-011a`) — present in `requirements-traceability.md` but no longer in
  `spec.md` Rev.3.2.
- **Threat**: None (informational); orphans do not fail the gate.
- **Expected behavior**: When the orphan ID is genuinely retired, its row is
  removed from `requirements-traceability.md`. When it is renamed, both the
  spec and trace are updated together.
- **Release condition**:
  - [ ] Decide whether `FR-011a` is retired or renamed.
  - [ ] Update `requirements-traceability.md` accordingly; orphan count → 0.

---

## Maintenance

- When introducing a new `xfail` / warn-only / deferred item, **add a ticket
  here at the same time**.
- When closing a ticket, **delete the section** rather than crossing it out;
  the git history is the audit trail.
- The CI gate `requirements-traceability` (T999) does NOT enforce this
  document's completeness — it only enforces spec ↔ traceability sync. This
  backlog is reviewed at Phase 17 kickoff and as part of every release
  retrospective.
