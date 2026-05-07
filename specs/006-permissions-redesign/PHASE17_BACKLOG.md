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

### A-13. Operator free-form fields: PII / email plaintext detector — DONE (2026-05-04)
- **Origin**: A-11 close review Round 1-9 carry-over. The operator
  `reason` and `support_ticket_id` fields accept arbitrary strings; an
  operator may paste a target user's email or other PII, which then
  reaches `platform_audit_log.detail.reason_excerpt` in plaintext (and,
  more critically, also lands in business tables and outbox payloads
  that are NOT routed through `AuditLogSanitizer`).
- **Threat**: PII leakage into long-retained audit rows AND business
  tables / outbox payloads breaches the PII-hash contract (FR-091a)
  for incidental operator-supplied content.
- **Resolution (P1 — API-boundary 422 reject)**:
  - `echoroo/core/operator_pii_detector.py` exposes reusable Pydantic
    `Annotated` types (`OperatorReasonText`, `OperatorSupportTicketId`)
    that reject PII via `AfterValidator` at the API boundary.
  - `echoroo/core/audit.py` now exports `contains_pii()` so detector +
    sanitizer share a single regex catalogue (FR-091a contract).
  - 5 admin schemas updated: `ResetTwoFactorRequest`,
    `TaxonOverrideRejectRequest`, `ArchiveRequest`,
    `SuperuserRejectRequest`, `SuperuserBreakGlassEnterRequest`.
  - 33 unit tests + 5 API-boundary integration tests confirm reject +
    no-side-effect behavior. `tests/contract/test_openapi_diff.py`
    21/21 pass — the change is wire-compatible.
- **Release condition**:
  - [x] Detector that rejects plausible email addresses / phone numbers
        / national IDs / credit cards / API tokens in operator
        free-form fields with HTTP 422 (P1 strategy chosen — business
        tables and outbox sinks rule out P2 redact-on-audit).
  - [ ] Admin UI helper text discouraging PII paste-in *(deferred to
        a frontend-only follow-up; the schema `description` already
        documents the constraint and the 422 message is educational)*.

---

## B. Pre-existing Phase 1-15 `xfail`

### B-1. Superuser response-filter raw forbidden — DONE (2026-05-07)
- **File**: `apps/api/tests/security/authorization/test_superuser_response_filter_raw_forbidden.py`
- **Resolution**: Already-satisfied + xfail cleanup.
  - **Audit (2026-05-07)**: `core/response_filter.py:apply_response_filter`
    calls `_scrub_raw_coordinates(obj)` unconditionally as the first step;
    no superuser short-circuit exists. Every API caller
    (`echoroo/api/web_v1/projects/_core.py`,
    `echoroo/api/v1/{detections,sites}.py`, etc.) routes through
    `apply_response_filter` regardless of `is_superuser`. The release-
    blocker portion of B-1 was already met — likely closed implicitly by
    Phase 15 / 16 hardening work.
  - **xfail cleanup**: The remaining
    `test_superuser_raw_export_endpoint_bypasses_coordinate_scrub`
    placeholder asserted that a *new* `/admin/projects/{id}/raw-export`
    endpoint should bypass the scrub for superuser callers. Per Codex
    review, this is **not release-blocking**: the spec body (FR-112a)
    directs operators who genuinely need raw lat/lng to a documented
    DB-direct runbook rather than a new public API surface. The xfail
    was deleted (rather than promoted) so the suite stops carrying a
    placeholder for a feature that isn't planned. If a sanctioned raw
    export channel is needed in the future it should land as a fresh
    spec / ticket with its own threat model.

### B-2. Upload EXIF + S3 metadata strip — DONE (2026-05-07)
- **File**: `apps/api/tests/security/authorization/test_upload_exif_and_s3_metadata_strip.py`
- **xfail count**: 0 (was 1; xfail removed and test now strict-passes).
- **Threat**: EXIF GPS / S3 user-metadata coordinates leak (FR-028a + FR-028e).
- **Expected behavior**: Upload pipeline strips EXIF GPS tags and S3
  user-defined metadata containing coordinate keys before persisting.
- **Release condition**:
  - [x] EXIF strip + S3 metadata sanitizer wired pre-upload.
  - [x] `xfail` markers removed; tests PASS.
- **Implementation summary**:
  - `echoroo/services/upload.py::strip_audio_gps_metadata(stream)` — format
    auto-detect (RIFF/WAVE chunk filter, FLAC/Ogg Vorbis/Ogg Opus Vorbis
    comment delete via mutagen, MP3 ID3v2 GPS-prefixed TXXX/GEOB delete via
    mutagen). Unknown formats pass through.
  - `echoroo/workers/upload_tasks.py::_sanitize_uploaded_object_gps()` — runs
    after ffprobe inside `_run_validate`: head_object → strip → put_object
    using `sanitize_put_object_kwargs` (FR-028e); persists new
    `file_size`/`checksum_sha256` via `UploadFileRepository.update_status`
    (allowed-keys list extended).
  - `echoroo/workers/audit_log_export.py` and
    `echoroo/api/v1/search/batch.py`: every `s3_client.put_object(...)`
    call now funnels through `sanitize_put_object_kwargs(...)` for
    defense in depth.
  - Tests: WAV (3 cases), FLAC, Ogg Vorbis, MP3 (ffmpeg-skippable),
    unknown-format passthrough, worker helper integration (head/strip/put
    + clean passthrough), and wiring guards on audit_log_export and
    search/batch — 27 tests all pass (20 Round 1 + 7 Round 2).
  - **Round 2 (Codex review)**: blockers + 3 high addressed.
    - Fail-closed in `_sanitize_uploaded_object_gps`: head_object /
      get_object / put_object failures now re-raise so the per-file
      handler marks ``INVALID`` instead of letting unsanitized payloads
      pass to ``VALID``.
    - Import-time SHA-256 re-verification: `verify_object_exists`
      gained an ``expected_sha256`` parameter that streams the body and
      compares with ``hmac.compare_digest``. ``_run_import`` calls it
      with the post-sanitize digest persisted by validation, closing
      the TOCTOU window opened by long-lived presigned PUT URLs.
    - Supported-format mutagen failures raise :class:`AudioGpsStripError`
      (a new ``RuntimeError`` subclass) instead of passing through; the
      validation worker catches it and marks the file ``INVALID``.
    - WAV ``LIST/INFO`` sub-chunks remain out of scope; documented in
      ``strip_audio_gps_metadata`` docstring.
    - **Image upload EXIF strip is out of scope** for this audio-only
      release blocker. Image-format EXIF (JPEG / WebP / TIFF) will be
      addressed by a follow-up backlog item when image uploads are
      implemented.

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
