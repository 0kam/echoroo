# xfail tracking — spec/007

Per plan Rev.5.1 Prereq-3 and Phase 4.2: every `@pytest.mark.xfail(strict=True)` introduced by this PR MUST have a tracking entry here so reviewers can verify the xfail represents a known gap (not a swept regression).

## Active xfails introduced by spec/007

### XFL-1: xeno_canto streaming mid-revoke

- **Location**: TBD (Phase 4.2 creates this in `apps/web/tests/permissions/smoke-matrix.test.ts` or backend equivalent — likely `apps/api/tests/security/streaming/test_xeno_canto_revoke.py`)
- **Scenario**: User streaming from `/api/v1/xeno-canto/proxy_audio` is demoted/removed mid-stream. Expected: stream aborts within next chunk interval. Actual: stream completes (only connection-time check exists in `xeno_canto.proxy_audio()`).
- **Reason text**: `"phase17-A5-mid-revoke-followup: xeno_canto.proxy_audio() lacks mid-stream re-check (tracked in #<ISSUE_NUMBER>)"`
- **Tracking issue**: To be opened at PR creation time. Suggested title: `Phase 17 A-5 followup: xeno_canto streaming mid-revoke guard`. Labels: `kind/security`, `area/permissions`, `phase/18`.
- **Why xfail (not skip)**: We want CI to alert us if someone accidentally implements this and starts passing — `strict=True` will then fail the xfail-pass case, triggering removal of the xfail.

### XFL-2: Pending invitation UI (B-4 scenario)

- **Location**: `apps/web/tests/e2e/permissions/smoke-matrix.spec.ts` — test B-4 (marked `test.skip(...)`)
- **Scenario**: User navigating to `/projects/{id}` with `authState: 'pending_invitation'` (invitation token in URL but not yet accepted) should see a "Accept invitation" CTA instead of project content.
- **Reason text**: `"TODO: implement when the pending_invitation authState UI surface is added to the project detail page (spec/007 Phase 4.2 follow-up)"`
- **Tracking issue**: To be opened when the pending_invitation UI surface is planned. Suggested title: `spec/007 follow-up: pending_invitation authState CTA on project detail`. Labels: `kind/feature`, `area/permissions`, `area/frontend`.
- **Why skip (not xfail strict=True)**: This is a missing UI feature (not a test that can currently run and produce a meaningful failure). Using `test.skip()` rather than `test.xfail()` because Playwright's `test.skip()` is the idiomatic mechanism for a test whose subject doesn't exist yet. Backend permission logic for `pending_invitation` is correct; only the frontend CTA rendering is unimplemented.

### XFL-3: datasets/+page.svelte permission gate for "+ New Dataset" (Screen 5, member/viewer)

- **Location**: `apps/web/tests/e2e/permissions/smoke-matrix.spec.ts` — Screen 5 tests for role=member and role=viewer (marked `test.skip(...)`)
- **Scenario**: Member and viewer should NOT see the "+ New Dataset" button on the dataset list page. The button is gated by `manage_dataset_admin` (§ 4A rule 2). Currently `datasets/+page.svelte` has no permission gate — the button is visible to all authenticated users.
- **Reason text**: `"TODO: datasets/+page.svelte lacks manage_dataset_admin gate — New Dataset button visible for all authenticated members (spec/007 Phase 2B follow-up)"`
- **Tracking issue**: To be opened as a follow-up to spec/007 Phase 2B. Suggested title: `spec/007 follow-up: gate New Dataset button on manage_dataset_admin in datasets/+page.svelte`. Labels: `kind/bug`, `area/permissions`, `area/frontend`.
- **Why skip (not xfail strict=True)**: The frontend gate is not yet implemented. The test is skipped until `datasets/+page.svelte` is updated to gate the button on `can('manage_dataset_admin', ctx)`.

## Out of scope (NOT in this PR's xfails)

Reference: Phase 17 A-5 audit (2026-05-12) confirmed the following are ALREADY passing tests, not xfails:
- recordings.py audio stream mid-revoke (OGG/WAV) — covered by `tests/security/test_stream_guard.py::test_recheck_action_permission_detects_api_key_revoke_mid_stream`
- CSV export mid-revoke — covered by `tests/security/race_conditions/test_streaming_permission_change.py::test_csv_stream_aborts_when_permission_revoked_mid_stream`
- API key fresh-load detection — covered by `test_refresh_api_key_scopes_fresh_load`
- Project delete mid-stream — `recheck_action_permission()` raises `PermissionRevokedMidStream`
- Audio Range responses (HTTP 206) — designed pre-start only, NOT xfail

## DoD check

Phase 4 final review verifies:
- [ ] Every xfail in this PR is `strict=True`
- [ ] Every xfail reason text contains an issue-number tracking ID
- [ ] This file lists every active xfail with location + scenario + reason
