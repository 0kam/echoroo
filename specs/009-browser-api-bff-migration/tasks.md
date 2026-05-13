---
description: "Task list for spec/009 — Complete Browser API → BFF Migration"
---

# Tasks: Complete Browser API → BFF Migration

**Input**: Design documents from `/specs/009-browser-api-bff-migration/`
**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/README.md](contracts/README.md), [quickstart.md](quickstart.md)

**Tests**: REQUIRED. The Echoroo constitution mandates TDD (Principle II, NON-NEGOTIABLE). Each new BFF adapter ships with an integration test that asserts the full D-2a contract (audit `actor_kind=session`, rate-limit web bucket, API-key cross-rejection, 403-not-401 on permission denial, CSRF on mutations). Test tasks are written first and MUST fail before the implementation lands.

**Organization**: Tasks are grouped by user story (US1 P1 → US5 P4). The 10-PR sequence from `plan.md` (A → A2 → B → C → D → E/F/G/H → I → J) is mapped onto the user-story phases below. PR B is Foundational (Phase 2). PR J is Polish (Phase 9). US5 (setup wizard verification, Phase 8) is the documented-exception verification step and has no PR. All other PRs map to user stories.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Maps task to a spec.md user story (US1 P1 / US2 P2 / US3 P3 / US4 P3). Setup, Foundational, and Polish tasks have NO story label.
- All paths are relative to repo root unless absolute.

## Path Conventions

- **Backend** (FastAPI): `apps/api/echoroo/`, tests at `apps/api/tests/`
- **Frontend** (SvelteKit): `apps/web/src/`
- **Contracts**: `specs/006-permissions-redesign/contracts/<resource>.yaml`
- **Per-feature artifacts**: `specs/009-browser-api-bff-migration/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Baseline checks before any per-resource work begins.

- [X] T001 Confirm feature branch `009-browser-api-bff-migration` is checked out and clean: `git status` shows nothing uncommitted and `git rev-parse --abbrev-ref HEAD` returns `009-browser-api-bff-migration`
- [X] T002 Confirm dev stack starts and current main is green: run `./scripts/docker.sh dev` and verify `docker logs echoroo-backend --tail 20` + `docker logs echoroo-frontend --tail 20` show no startup errors; run `(cd apps/api && uv run pytest -q 2>&1 | tail -20)` and `(cd apps/web && npm run check)` as baseline. **Record the pytest pass / fail / skip counts into `specs/009-browser-api-bff-migration/audit-baseline.md`** (under a "## Pytest baseline 2026-05-13" section, appended after T003's grep snapshot) so T122a (Phase 9 SC-003 evidence) has a concrete numeric baseline to diff against
- [X] T003 [P] Record the 2026-05-13 baseline grep snapshot of `/api/v1/*` browser hits into `specs/009-browser-api-bff-migration/audit-baseline.md`: output of `rg -n '/api/v1/[a-zA-Z0-9/_${}-]+' apps/web/src/ --glob '!**/__tests__/**' --glob '!**/lib/types/**' | sort -u`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared test helpers (D-2a assertion library) + PR B (residual auth follow-up) + parity-allowlist starter file. PR B is here because residual `/api/v1/auth/*` browser callers (`register`, `verify-email`, `password-reset`) must move to BFF before any new user can complete the entry-point flow that US1 builds on. The shared helpers in T005–T010 are dependencies of every subsequent integration test.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

### Shared test infrastructure (D-2a assertion library)

- [X] T004 [P] Add `assert_audit_actor_kind_session(db, action_id)` helper in `apps/api/tests/integration/api/web_v1/_helpers.py` that queries the audit log row for the given action and asserts `actor_kind == 'session'` (D-2a #1)
- [X] T005 [P] Add `assert_rate_limit_bucket_web(response)` helper in `apps/api/tests/integration/api/web_v1/_helpers.py` that inspects the response headers / rate-limit store and confirms the increment landed on the web bucket, not the API-key bucket (D-2a #2)
- [X] T006 [P] Add `assert_api_key_cross_rejected(client, method, path)` helper in `apps/api/tests/integration/api/web_v1/_helpers.py` that sends `Authorization: Bearer echoroo_<test_prefix>_<test_secret>` to a `/web-api/v1/...` route and asserts HTTP 401 with the documented `"API key invalid or revoked"` body (D-2a #3)
- [X] T007 [P] Add `assert_permission_denial_returns_403(client, method, path, headers)` helper in `apps/api/tests/integration/api/web_v1/_helpers.py` that calls the BFF route as an authenticated-but-unauthorized user and asserts 403, NOT 401 (D-2a #4, D-7)
- [X] T008 [P] Add `assert_csrf_required(client, method, path, body)` helper in `apps/api/tests/integration/api/web_v1/_helpers.py` that submits a BFF mutation without `X-CSRF-Token` header and asserts 403 (D-2a #5)
- [X] T009 [P] Add an `__init__.py` (if missing) and a docstring summarising D-2a usage at the top of `apps/api/tests/integration/api/web_v1/_helpers.py`
- [X] T009a [P] Add `assert_legacy_v1_rejects_bff_token(unshimmed_client, method, path)` helper in `apps/api/tests/integration/api/web_v1/_helpers.py`. Implementation MUST use an unshimmed FastAPI test client (the default `client` fixture has an `/api/v1` Bearer-JWT shim that would mask the rejection). Reference patterns: `apps/api/tests/contract/test_auth_separation.py` and `apps/api/tests/security/csrf/test_api_v1_no_cookie.py`. Helper issues a BFF-issued Bearer JWT (existing factory in those test files) against `/api/v1/<resource>` and asserts HTTP 401 with `"API key invalid or revoked"` body. FR-006 (legacy rejects BFF tokens — mirror of T006 in the opposite direction)
- [X] T009b [P] Add `unshimmed_client` and `bff_jwt_factory` fixtures to `apps/api/tests/integration/api/web_v1/conftest.py` (create the file if it does not yet exist). Both fixtures MUST mirror the implementation shapes used by `apps/api/tests/contract/test_auth_separation.py` and `apps/api/tests/security/csrf/test_api_v1_no_cookie.py`. The `unshimmed_client` fixture builds a FastAPI test client WITHOUT the standard `/api/v1` Bearer-JWT shim applied by the integration-suite default `client`; the `bff_jwt_factory` returns a BFF-style access token for use in T009a's helper. T009a + each per-PR test invoking `assert_legacy_v1_rejects_bff_token` (T030 / T057 / T086 / T095 / T101 / T107) MUST import these fixtures from this conftest

### Parity allowlist + per-PR guard script

- [X] T010 [P] Create `apps/api/tests/contract/_bff_path_parity_allowlist.py` containing an empty `BFF_PATHS_DECLARED_BY_SPEC_009: list[str] = []` plus a comment describing how each per-PR appends its paths (consumed by PR J's `test_bff_path_parity.py`)
- [X] T011 [P] Create `scripts/audit_browser_api_v1.sh` that takes a `<resource>` argument and runs `rg -n "/api/v1/${1}" apps/web/src/ --glob '!**/__tests__/**' --glob '!**/lib/types/**'`, exiting non-zero on any hit (per-PR static legacy-call guard from quickstart.md)

### PR B — residual auth follow-up (frontend-only rewire)

- [ ] T012 Rewire `lib/api/auth.ts` `register()` to call `/web-api/v1/auth/register` via `callWebApi()` (CSRF token attached); preserve existing request/response types
- [ ] T013 Rewire `lib/api/auth.ts` `requestEmailVerification()` and `resendEmailVerification()` to BFF (`/web-api/v1/auth/verify-email[/resend]`)
- [ ] T014 Rewire `lib/api/auth.ts` `requestPasswordReset()` and `confirmPasswordReset()` to BFF
- [ ] T015 Audit `apps/web/src/hooks.server.ts` for any direct `/api/v1/auth/*` references; rewire as needed using cookie forwarding to BFF
- [ ] T016 Audit `apps/web/src/lib/api/web-auth.ts` for residual legacy calls; rewire
- [ ] T017 Run `bash scripts/audit_browser_api_v1.sh auth` and confirm zero hits
- [ ] T018 Append `/web-api/v1/auth/register`, `/web-api/v1/auth/verify-email`, `/web-api/v1/auth/verify-email/resend`, `/web-api/v1/auth/password-reset/request`, `/web-api/v1/auth/password-reset/confirm` to `apps/api/tests/contract/_bff_path_parity_allowlist.py`
- [ ] T019 Gate 1/2 for PR B: `(cd apps/api && uv run ruff check . && uv run mypy . && uv run pytest tests/integration/api/web_v1/test_auth.py -q)` and `(cd apps/web && npm run check && npm run test -- --run lib/api/auth)`
- [ ] T020 Gate 3 browser smoke for PR B per quickstart.md PR B row: register a fresh throwaway account, resend verification, request password reset — confirm zero 401s, zero `/api/v1/auth/*` network hits

**Checkpoint**: Foundational phase complete. User story work can proceed in parallel where dependencies allow.

---

## Phase 3: User Story 1 — Authenticated user can view and manage projects (Priority: P1) 🎯 MVP

**Goal**: Restore `/en/projects` and the full project resource family on BFF. PR A unblocks the read entry point; PR A2 closes the resource family by adding the two missing read adapters (members, overview) plus all mutations.

**Independent Test**: Log in as `test@echoroo.app`. After PR A: `/en/projects` lists projects and detail pages render reads from BFF. After PR A2: create / rename / delete a project and add / remove members via BFF; project detail's members panel and overview tile load via BFF. After both PRs, `apps/web/src/lib/api/projects.ts` contains zero `/api/v1/projects*` calls.

---

### PR A — Projects read subset (frontend-only rewire)

> Backend `web_v1/projects/_core.py:132/307/424` already exposes `GET /`, `GET /{project_id}`, `GET /{project_id}/recordings`. PR A is **frontend-only** and migrates exactly these three reads. `listMembers` and `getOverview` remain on legacy until PR A2.

- [ ] T021 [P] [US1] Add a thin smoke test at `apps/api/tests/integration/api/web_v1/test_projects_read_smoke.py` asserting `GET /web-api/v1/projects` returns 200 for `test@echoroo.app` and that `assert_api_key_cross_rejected(...)` passes — uses helpers from T006
- [ ] T022 [US1] Rewire `lib/api/projects.ts` `listProjects()` to call `/web-api/v1/projects` via the existing `callWebApi()` helper (the same pattern PR #71 used for `users/me`); preserve `ProjectSummaryListResponse` typing
- [ ] T023 [US1] Rewire `lib/api/projects.ts` `getProject(projectId)` to `/web-api/v1/projects/{projectId}`
- [ ] T024 [US1] Rewire the recordings list fetch (currently part of `projects.ts` or its callers) to `/web-api/v1/projects/{projectId}/recordings`
- [ ] T025 [US1] Update or verify `routes/(app)/projects/[id]/+page.svelte` retains its existing silent-401 tolerance on `listMembers` / `getOverview` (those calls stay on legacy until PR A2 — must not break the page)
- [ ] T026 [US1] Append `/web-api/v1/projects`, `/web-api/v1/projects/{project_id}`, `/web-api/v1/projects/{project_id}/recordings` to `apps/api/tests/contract/_bff_path_parity_allowlist.py`
- [ ] T027 [US1] Run static guard for projects reads only: confirm `lib/api/projects.ts` `listProjects` / `getProject` / recordings fetch contain no `/api/v1/projects*` strings (members / overview / mutations still tolerated in this PR)
- [ ] T028 [US1] Gate 1/2 for PR A: type check + ruff + mypy + the smoke pytest from T021 + frontend vitest
- [ ] T029 [US1] Gate 3 browser smoke for PR A per quickstart.md PR A row: log in as `test@echoroo.app`, visit `/en/projects`, open a project detail, exercise recordings list. Verify `browser_network_requests` shows BFF paths for the three migrated reads. Record evidence in PR description

**PR A checkpoint**: `/en/projects` unblocked. PR A2 may proceed.

---

### PR A2 — Projects mutations + missing read adapters

> Backend additions required: `GET /web-api/v1/projects/{project_id}/members` listing, `GET /web-api/v1/projects/{project_id}/overview`, plus `POST /web-api/v1/projects`, `PATCH/DELETE /web-api/v1/projects/{project_id}`, and member POST/PATCH/DELETE. CSRF-protected. All adapters reuse existing service-layer functions from `apps/api/echoroo/services/`.

#### Tests for PR A2 (write first, ensure FAIL before implementation) ⚠️

- [ ] T030 [P] [US1] Write integration test `apps/api/tests/integration/api/web_v1/test_projects_members_get.py` covering `GET /web-api/v1/projects/{project_id}/members` — 200 for member/admin, 403 (NOT 401) for non-member, full D-2a assertion set via helpers. **Include one invocation of `assert_legacy_v1_rejects_bff_token(unshimmed_client, "GET", f"/api/v1/projects/{project_id}/members")` to pin FR-006 (legacy mount rejects BFF JWT) for this resource family**
- [ ] T031 [P] [US1] Write integration test `apps/api/tests/integration/api/web_v1/test_projects_overview.py` covering `GET /web-api/v1/projects/{project_id}/overview` — 200 for member, 403 for non-member, full D-2a set
- [ ] T032 [P] [US1] Write integration test `apps/api/tests/integration/api/web_v1/test_projects_create.py` covering `POST /web-api/v1/projects` — 201 with CSRF, 403 without CSRF (`assert_csrf_required`), 403 (not 401) on permission denial, audit `actor_kind=session`, rate-limit web bucket, API-key cross-rejected
- [ ] T033 [P] [US1] Write integration test `apps/api/tests/integration/api/web_v1/test_projects_update.py` covering `PATCH /web-api/v1/projects/{project_id}` with the full D-2a assertion set
- [ ] T034 [P] [US1] Write integration test `apps/api/tests/integration/api/web_v1/test_projects_delete.py` covering `DELETE /web-api/v1/projects/{project_id}` with the full D-2a assertion set
- [ ] T035 [P] [US1] Write integration test `apps/api/tests/integration/api/web_v1/test_projects_members_mutations.py` covering member `POST /web-api/v1/projects/{project_id}/members`, `PATCH .../{user_id}`, `DELETE .../{user_id}` — full D-2a set

#### Implementation for PR A2

- [ ] T036 [US1] Update `specs/006-permissions-redesign/contracts/projects.yaml`: add `GET /projects/{project_id}/members` (BFF security: `sessionCookie + csrfToken` for guest-incompatible read), `GET /projects/{project_id}/overview`, and mutation paths (`POST /projects`, `PATCH /projects/{project_id}`, `DELETE /projects/{project_id}`, member mutation paths). Mutations declare BFF security block `[{sessionCookie: [], csrfToken: []}]` plus legacy `apiKeyAuth`
- [ ] T037 [US1] Add `GET /{project_id}/members` listing handler to `apps/api/echoroo/api/web_v1/projects/_members.py` (existing file, currently only has invitation accept / decline). Reuse `ProjectService.list_members` from `apps/api/echoroo/services/project.py` (single-file service module). `gate_action` for `PROJECT_MEMBER_LIST_ACTION` (or the existing action used by the legacy `/api/v1/projects/{id}/members` GET handler). 403 (not 401) on denial
- [ ] T038 [US1] Create `apps/api/echoroo/api/web_v1/projects/_overview.py` with `GET /{project_id}/overview` handler. Reuse `ProjectService.get_project_overview` from `apps/api/echoroo/services/project.py` (the same method the legacy `/api/v1/projects/{id}/overview` handler calls). `gate_action` using the same action the legacy handler declares. CSRF not required (read)
- [ ] T039 [US1] Wire `_overview` router in `apps/api/echoroo/api/web_v1/projects/__init__.py` (add `from . import _overview` and `router.include_router(_overview.router)`)
- [ ] T040 [US1] Add `POST /` create handler to `apps/api/echoroo/api/web_v1/projects/_core.py`. Reuses `ProjectService.create_project` (NOT `.create` — actual method name in `services/project.py:278`). CSRF-protected. Audit emits `actor_kind=session`
- [ ] T041 [US1] Add `PATCH /{project_id}` update handler to `apps/api/echoroo/api/web_v1/projects/_core.py`. Reuses `ProjectService.update_project` (NOT `.update` — actual method name in `services/project.py:416`). CSRF-protected
- [ ] T042 [US1] Add `DELETE /{project_id}` delete handler to `apps/api/echoroo/api/web_v1/projects/_core.py`. Reuses `ProjectService.delete_project` (NOT `.delete` — actual method name in `services/project.py:479`). CSRF-protected
- [ ] T043 [US1] Add member `POST /{project_id}/members` handler to `apps/api/echoroo/api/web_v1/projects/_members.py`. Reuses `ProjectService.add_member` from `services/project.py:538`. CSRF-protected
- [ ] T044 [US1] Add member `PATCH /{project_id}/members/{user_id}` (reuses `ProjectService.update_member_role`) and `DELETE /{project_id}/members/{user_id}` (reuses `ProjectService.remove_member`) handlers to `apps/api/echoroo/api/web_v1/projects/_members.py`. Both CSRF-protected
- [ ] T045 [US1] Run `(cd apps/api && uv run pytest tests/integration/api/web_v1/test_projects_*.py -q)` — all T030–T035 tests MUST now pass (they failed before implementation)
- [ ] T045a [US1] Run `(cd apps/api && uv run pytest tests/security/authorization/test_endpoint_coverage.py -q)` and confirm the new BFF paths added by PR A2 (`/web-api/v1/projects/{project_id}/members` GET, `/web-api/v1/projects/{project_id}/overview` GET, `POST /web-api/v1/projects`, `PATCH/DELETE /web-api/v1/projects/{project_id}`, member POST/PATCH/DELETE) are picked up as guarded by `gate_action`. SC-007 evidence. **Preferred fix on failure: add `gate_action` to the handler.** Do NOT silently extend the route allowlist (see `scripts/allowlists/permission_guard_allowlist.txt` or equivalent) unless explicitly justified in the PR description
- [ ] T046 [US1] Rewire `lib/api/projects.ts` `listMembers(projectId)` to call `/web-api/v1/projects/{projectId}/members`
- [ ] T047 [US1] Rewire `lib/api/projects.ts` `getOverview(projectId)` to call `/web-api/v1/projects/{projectId}/overview`
- [ ] T048 [US1] Rewire `lib/api/projects.ts` `createProject(data)` to BFF using `callWebApi('POST', ...)` (CSRF token attached)
- [ ] T049 [US1] Rewire `lib/api/projects.ts` `updateProject(projectId, data)` to BFF (PATCH)
- [ ] T050 [US1] Rewire `lib/api/projects.ts` `deleteProject(projectId)` to BFF (DELETE)
- [ ] T051 [US1] Rewire `lib/api/projects.ts` `addProjectMember`, `updateProjectMember`, `removeProjectMember` to BFF
- [ ] T052 [US1] Update `routes/(app)/projects/[id]/+page.svelte`: silent-401 fallback for members / overview is no longer needed since BFF returns 403 on denial. Replace any 401 tolerance for these calls with 403 tolerance, keeping the user-facing behaviour identical
- [ ] T053 [US1] Append the seven new BFF paths to `apps/api/tests/contract/_bff_path_parity_allowlist.py`
- [ ] T054 [US1] Run static guard: `bash scripts/audit_browser_api_v1.sh projects` returns zero hits
- [ ] T055 [US1] Gate 1/2 for PR A2: type check + ruff + mypy + full pytest run of `tests/integration/api/web_v1/test_projects_*.py` + `tests/contract/test_openapi_diff.py` + frontend vitest
- [ ] T056 [US1] Gate 3 browser smoke for PR A2 per quickstart.md PR A2 row: create a new project, rename it, add a member, change the member role, remove the member, delete the project. Verify zero 401s, zero `/api/v1/projects*` hits, and that the audit log shows `actor_kind=session` for each action

**Checkpoint US1**: Project resource family fully on BFF. `lib/api/projects.ts` has zero `/api/v1/*` calls (verified by T054).

---

## Phase 4: User Story 2 — Authenticated user can use core surfaces (Priority: P2)

**Goal**: Migrate taxa search (PR C) and the export / audio playback components (PR D) so the full authenticated core loop works without legacy calls.

**Independent Test**: From a project's annotation review screen, run taxa autocomplete and exercise audio playback / spectrogram seek. Start an annotation export and a data export. All flows succeed with zero `/api/v1/*` calls in the touched files.

---

### PR C — Taxa search + GBIF lookup

#### Tests for PR C ⚠️

- [ ] T057 [P] [US2] Write integration test `apps/api/tests/integration/api/web_v1/test_taxa.py` covering `GET /web-api/v1/taxa/search` and `GET /web-api/v1/taxa/gbif-search`. 200 for authenticated, 403 for guest (if guest is denied) or empty result (if guest is allowed). Full D-2a assertion set on the authenticated path. **Include one invocation of `assert_legacy_v1_rejects_bff_token(unshimmed_client, "GET", "/api/v1/taxa/search")` to pin FR-006 for the taxa surface**

#### Implementation for PR C

- [ ] T058 [US2] Create new contract file `specs/006-permissions-redesign/contracts/taxa.yaml` with prefix-less paths `/taxa/search` and `/taxa/gbif-search`, top-level `servers:` block enumerating `/api/v1` and `/web-api/v1`, request/response schemas mirroring `/api/v1/taxa/*`
- [ ] T059 [US2] Create `apps/api/echoroo/api/web_v1/taxa.py` with router exposing `GET /taxa/search` and `GET /taxa/gbif-search`. Reuse `services/taxa.py` functions. `gate_action` for taxa-read permission (use the same permission key the legacy `/api/v1/taxa` handler uses). Audit `actor_kind=session`
- [ ] T060 [US2] Register taxa router in `apps/api/echoroo/api/web_v1/__init__.py` (add `from echoroo.api.web_v1 import taxa as taxa_module` and `web_v1_router.include_router(taxa_module.router)`)
- [ ] T061 [US2] Run `(cd apps/api && uv run pytest tests/integration/api/web_v1/test_taxa.py -q)` — T057 MUST now pass
- [ ] T061a [US2] Run `(cd apps/api && uv run pytest tests/security/authorization/test_endpoint_coverage.py -q)` and confirm `/web-api/v1/taxa/search`, `/web-api/v1/taxa/gbif-search` are picked up as `gate_action`-guarded (SC-007). Preferred fix on failure: add `gate_action` to the handler
- [ ] T062 [US2] Rewire `lib/api/taxa.ts` `searchTaxa()` and `searchGbif()` to BFF via `apiClient.get('/web-api/v1/taxa/...')`
- [ ] T063 [US2] Audit `lib/components/common/MiniSpectrogram.svelte` for any inline taxa fetches; rewire to BFF if present
- [ ] T064 [US2] Append `/web-api/v1/taxa/search` and `/web-api/v1/taxa/gbif-search` to `apps/api/tests/contract/_bff_path_parity_allowlist.py`
- [ ] T065 [US2] Run static guard: `bash scripts/audit_browser_api_v1.sh taxa` returns zero hits
- [ ] T066 [US2] Gate 1/2 for PR C
- [ ] T067 [US2] Gate 3 browser smoke for PR C per quickstart.md PR C row: open a project's taxa search, type a partial Latin name and a partial Japanese name; both autocompletes return results with zero `/api/v1/taxa/*` calls

---

### PR D — Annotation/data exports + audio playback components

> Per research D-10, run the pre-PR audit BEFORE writing code. Any failed audit item creates a backend-prerequisite split PR (variant of PR D), the same way A→A2 was split for projects mutations.

#### Pre-PR-D audit (D-10 checklist)

- [ ] T068 [P] [US2] D-10 #1: confirm `<audio src="/web-api/v1/projects/{id}/recordings/{rid}/audio">` plays with cookie auth in a logged-in browser tab. Record evidence (network log + audible playback) in `specs/009-browser-api-bff-migration/pr-d-audit.md`
- [ ] T069 [P] [US2] D-10 #2: confirm `Range:` header propagation to storage backend — drag the spectrogram cursor mid-playback and confirm 206 partial-content responses in the network log
- [ ] T070 [P] [US2] D-10 #3: investigate whether the legacy v1 path returns redirects to presigned S3 URLs; confirm BFF equivalent either redirects similarly or returns the same audio data through the BFF mount. Record findings in `pr-d-audit.md`
- [ ] T071 [P] [US2] D-10 #4: confirm streaming export response shape on BFF (chunked transfer or background-job poll). If chunked, verify a token refresh during the export does not corrupt the response
- [ ] T072 [P] [US2] D-10 #5: confirm `vite.config.ts` proxy mappings for `/web-api/v1/projects/{id}/recordings/*` carry audio MIME types correctly in dev
- [ ] T073 [US2] If any of T068–T072 surface a gap, add a backend prerequisite task (new file under `apps/api/echoroo/api/web_v1/projects/_media.py` or extension to existing handlers) and ship it as a split PR before continuing. Otherwise, mark `pr-d-audit.md` as "no backend changes required"

#### Implementation for PR D (after audit passes)

- [ ] T074 [P] [US2] Write integration test `apps/api/tests/integration/api/web_v1/test_projects_recordings_media.py` covering the audio / Range / streaming paths discovered in T068–T072. Full D-2a assertion set. May skip if audit confirms paths are already declared and tested by spec/006 tests
- [ ] T075 [US2] Rewire `lib/components/annotation/AnnotationExportDialog.svelte` inline fetches to `/web-api/v1/projects/{id}/...` (replace `apiClient` / `fetch` calls that hit `/api/v1/*`)
- [ ] T076 [US2] Rewire `lib/components/annotation/ExportDialog.svelte` (annotation export) inline fetches to BFF
- [ ] T077 [US2] Rewire `lib/components/data/ExportDialog.svelte` (data export) inline fetches to BFF
- [ ] T078 [US2] Rewire `lib/components/common/MiniSpectrogram.svelte` audio URL construction to BFF (`<audio src="/web-api/v1/projects/{id}/recordings/{rid}/audio">` — cookie-auth aware)
- [ ] T079 [US2] Rewire `lib/utils/audioPlayback.svelte.ts` URL construction to BFF
- [ ] T080 [US2] Rewire `routes/(app)/projects/[id]/annotations/[annotationProjectId]/+page.svelte` inline fetches to BFF
- [ ] T081 [US2] Append the BFF media/export paths exercised by PR D to `apps/api/tests/contract/_bff_path_parity_allowlist.py`
- [ ] T082 [US2] Run static guard for the touched files: confirm zero `/api/v1/*` strings remain in the six listed frontend files
- [ ] T083 [US2] Gate 1/2 for PR D
- [ ] T083a [US2] Verify FR-002 dataset / recording / detection coverage: open a project's datasets list, a recording detail, and a detections list in the browser. Confirm each screen loads via project-scoped BFF paths (`/web-api/v1/projects/{id}/recordings`, `/web-api/v1/projects/{id}/...`) with zero `/api/v1/*` calls in the network log. These views are project-scoped and already served by `web_v1/projects/_core.py:424` (recordings) + sibling routes — this is a confirmation, not a new migration. Record a network sample in the PR D description
- [ ] T084 [US2] Gate 3 browser smoke for PR D per quickstart.md PR D row: start annotation export, start data export, play a mini-spectrogram, drag cursor mid-playback (verify Range seeking works). Zero 401s, zero unscoped `/api/v1/*` calls

**Checkpoint US2**: Core authenticated loop on BFF.

---

## Phase 5: User Story 3 — Administrator can use administrative screens (Priority: P3)

**Goal**: Add BFF mirrors for `admin/{licenses,recorders,settings,users}` and rewire the admin frontend.

**Independent Test**: As `okamoto.ryotaro@nies.go.jp`, exercise each admin screen end-to-end (list / create / edit / delete) with zero `/api/v1/admin/*` calls outside the documented exceptions.

> **Parallelism note**: PRs E / F / G / H are parallelizable with **at most 2 concurrent worktrees** (memory: prior parallel-SSA git accidents). They share `admin.yaml` and `web_v1/admin/__init__.py`, so worktree isolation is critical. PR-E (licenses) lands first as the template; F / G / H may proceed in pairs after.

---

### Phase 5 prep — refactor admin into a sub-package

- [ ] T085 [US3] Refactor `apps/api/echoroo/api/web_v1/admin.py` (currently a flat module containing superusers / approvals / 2FA / IP-allowlist) into the package `apps/api/echoroo/api/web_v1/admin/__init__.py`. Move existing handlers into a `superusers.py` (or named) submodule with no behavior change. Re-export the same `router` symbol so `from echoroo.api.web_v1 import admin as admin_module; web_v1_router.include_router(admin_module.router)` in `web_v1/__init__.py` still works. Run the full `tests/integration/api/web_v1/test_admin*.py` suite and confirm zero behaviour change

---

### PR E — admin/licenses

- [ ] T086 [P] [US3] Write integration test `apps/api/tests/integration/api/web_v1/test_admin_licenses.py` covering `GET /web-api/v1/admin/licenses[/{id}]` reads + `POST` / `PATCH` / `DELETE` mutations. Full D-2a assertion set, plus `assert_permission_denial_returns_403` for non-admin callers. **Include one invocation of `assert_legacy_v1_rejects_bff_token(unshimmed_client, "GET", "/api/v1/admin/licenses")` to pin FR-006 for the admin surface (covers PRs E/F/G/H by family)**
- [ ] T087 [US3] Update `specs/006-permissions-redesign/contracts/admin.yaml`: add `/admin/licenses` and `/admin/licenses/{license_id}` paths on the BFF security block (CSRF for mutations)
- [ ] T088 [US3] Create `apps/api/echoroo/api/web_v1/admin/licenses.py` with router exposing list / get / create / update / delete. Reuse `services/admin/licenses.py`. Admin-only via `gate_action`. Audit `actor_kind=session`
- [ ] T089 [US3] Wire licenses sub-router in `apps/api/echoroo/api/web_v1/admin/__init__.py`
- [ ] T090 [US3] Run `(cd apps/api && uv run pytest tests/integration/api/web_v1/test_admin_licenses.py -q)` — T086 MUST now pass
- [ ] T090a [US3] Run `(cd apps/api && uv run pytest tests/security/authorization/test_endpoint_coverage.py -q)` and confirm `/web-api/v1/admin/licenses[/{license_id}]` is `gate_action`-guarded (SC-007). Preferred fix on failure: add `gate_action` to the handler
- [ ] T091 [US3] Rewire `lib/api/licenses.ts` to BFF; clean any license-related calls in `lib/api/admin.ts`
- [ ] T092 [US3] Append `/web-api/v1/admin/licenses`, `/web-api/v1/admin/licenses/{license_id}` to `apps/api/tests/contract/_bff_path_parity_allowlist.py`
- [ ] T093 [US3] Static guard: `bash scripts/audit_browser_api_v1.sh admin/licenses` returns zero hits
- [ ] T094 [US3] Gate 1/2 + Gate 3 browser smoke for PR E per quickstart.md PR E row

---

### PR F — admin/recorders (mirrors PR E)

- [ ] T095 [P] [US3] Write integration test `apps/api/tests/integration/api/web_v1/test_admin_recorders.py` — full D-2a set. **Include one invocation of `assert_legacy_v1_rejects_bff_token(unshimmed_client, "GET", "/api/v1/admin/recorders")` for PR F traceability of FR-006**
- [ ] T096 [US3] Update `admin.yaml` with `/admin/recorders[/{recorder_id}]`
- [ ] T097 [US3] Create `apps/api/echoroo/api/web_v1/admin/recorders.py`, reuse `services/admin/recorders.py`
- [ ] T098 [US3] Wire recorders sub-router in `web_v1/admin/__init__.py`
- [ ] T099 [US3] Make T095 pass; rewire `lib/api/recorders.ts` to BFF
- [ ] T099a [US3] Run `(cd apps/api && uv run pytest tests/security/authorization/test_endpoint_coverage.py -q)` and confirm `/web-api/v1/admin/recorders[/{recorder_id}]` is `gate_action`-guarded (SC-007). Preferred fix on failure: add `gate_action` to the handler
- [ ] T100 [US3] Append paths to parity allowlist; static guard zero hits; Gate 1/2 + Gate 3 per quickstart PR F row

---

### PR G — admin/settings (mirrors)

- [ ] T101 [P] [US3] Write integration test `apps/api/tests/integration/api/web_v1/test_admin_settings.py` — full D-2a set. **Include one invocation of `assert_legacy_v1_rejects_bff_token(unshimmed_client, "GET", "/api/v1/admin/settings")` for PR G traceability of FR-006**
- [ ] T102 [US3] Update `admin.yaml` with `/admin/settings`
- [ ] T103 [US3] Create `apps/api/echoroo/api/web_v1/admin/settings.py`, reuse `services/admin/settings.py`
- [ ] T104 [US3] Wire settings sub-router
- [ ] T105 [US3] Make T101 pass; rewire `lib/api/admin.ts` settings calls to BFF
- [ ] T105a [US3] Run `(cd apps/api && uv run pytest tests/security/authorization/test_endpoint_coverage.py -q)` and confirm `/web-api/v1/admin/settings` is `gate_action`-guarded (SC-007). Preferred fix on failure: add `gate_action` to the handler
- [ ] T106 [US3] Append paths to parity allowlist; static guard; Gate 1/2 + Gate 3 per quickstart PR G row

---

### PR H — admin/users (mirrors)

- [ ] T107 [P] [US3] Write integration test `apps/api/tests/integration/api/web_v1/test_admin_users.py` — full D-2a set. **Include one invocation of `assert_legacy_v1_rejects_bff_token(unshimmed_client, "GET", "/api/v1/admin/users")` for PR H traceability of FR-006**
- [ ] T108 [US3] Update `admin.yaml` with `/admin/users[/{user_id}]`
- [ ] T109 [US3] Create `apps/api/echoroo/api/web_v1/admin/users.py`, reuse `services/admin/users.py`
- [ ] T110 [US3] Wire users sub-router
- [ ] T111 [US3] Make T107 pass; rewire `lib/api/admin.ts` user-management calls to BFF
- [ ] T111a [US3] Run `(cd apps/api && uv run pytest tests/security/authorization/test_endpoint_coverage.py -q)` and confirm `/web-api/v1/admin/users[/{user_id}]` is `gate_action`-guarded (SC-007). Preferred fix on failure: add `gate_action` to the handler
- [ ] T112 [US3] Append paths to parity allowlist; static guard; Gate 1/2 + Gate 3 per quickstart PR H row

**Checkpoint US3**: All admin screens on BFF.

---

## Phase 6: User Story 4 — Unauthenticated visitor can browse public content (Priority: P3)

**Goal**: Confirm `/explore` already lands on BFF, and clean up any residual legacy references (`<audio>` / `<img>` src URLs in particular).

**Independent Test**: In an incognito browser (no cookies), visit `/explore/projects` and an `/explore/projects/{id}`. Both render with zero `/api/v1/*` network requests.

### PR I — guest/`/explore` polish

- [ ] T113 [P] [US4] Run `rg -n '/api/v1/' apps/web/src/routes/(public)/ apps/web/src/routes/explore/` — capture current state. Expected: zero (already-true per 2026-05-13 grep). Record in PR description
- [ ] T114 [US4] Audit `routes/(public)/explore/projects/[id]/+page.svelte` and any sibling files for residual legacy references in `<audio>` / `<img>` src URLs, in `+page.server.ts` server-load fetches, and in directly embedded `apiClient` calls. Rewire to `/web-api/v1/projects[/{id}]` where any are found
- [ ] T115 [US4] Confirm the `/projects/feed` reference at `apps/web/src/lib/api/__tests__/client.permissions.test.ts:70` remains (it is the intentional negative-test fixture per D-9); add a one-line code comment `// kept as negative-test fixture per spec/009 D-9` if not already present
- [ ] T116 [US4] Static guard: `bash scripts/audit_browser_api_v1.sh projects` and a glob across the public routes return zero hits
- [ ] T117 [US4] Gate 3 browser smoke for PR I per quickstart.md PR I row: incognito session visiting `/explore/projects` and `/explore/projects/{id}`. Verify zero `/api/v1/*` calls (including audio src)

**Checkpoint US4**: Public surface on BFF.

---

## Phase 8: User Story 5 — Setup wizard verification (Priority: P4)

**Goal**: Confirm the documented `/api/v1/setup/*` exception still works on a fresh install. This phase has no code changes — it exists to verify FR-013 explicitly, since the setup wizard is intentionally out of scope as one of the 5 documented exceptions.

**Independent Test**: On a fresh PostgreSQL database with zero users, visit `/setup` and complete the wizard. Confirm the wizard renders, first-user creation succeeds, and subsequent login via the BFF flow succeeds.

- [ ] T117a [US5] Verify FR-013 / US5 acceptance: **DO NOT drop the running dev database.** The existing `compose.dev.yaml` pins `container_name: echoroo-*` plus fixed volume / network names, so `docker compose -p ...` alone collides with the running stack. Instead, author a small override compose file `compose.setup-test.yaml` (located under the spec directory or `scripts/`) that **explicitly overrides container_name, ports, volumes, and network names** to a unique suffix (e.g. `echoroo-setup-test-backend`, host port `8003`, named volume `pg_setup_test`, network `echoroo-setup-test-net`) and sets `POSTGRES_DB=echoroo_setup_test`. Bring it up with `docker compose -p echoroo-setup-test -f compose.dev.yaml -f compose.setup-test.yaml up`. Open `/setup` against this disposable stack (host port 8003 → :3000 equivalent), complete the wizard (status check + initialize first administrator), then log in and confirm BFF session establishes. Tear down with `docker compose -p echoroo-setup-test down -v`. Record evidence (network log + screenshot summary + the override compose file path + the commands used) in `specs/009-browser-api-bff-migration/sc-evidence.md` under "FR-013 / US5". **No application code changes required** — this task gates that the documented exception's legacy `/api/v1/setup/*` path still functions, and the override compose file is the only new artifact

**Checkpoint US5**: Setup wizard verified. All 5 user stories covered.

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Lock the migration in place with the BFF-parity contract test and the repo-wide CI guard. Audit residual type-only references. Run the SC-001 final walkthrough.

### PR J — CI guard + BFF parity test + cleanup

- [ ] T118 [P] Add `apps/api/tests/contract/test_bff_path_parity.py` that imports `BFF_PATHS_DECLARED_BY_SPEC_009` from `_bff_path_parity_allowlist.py`, constructs the FastAPI app via `create_app()`, and asserts each path in the allowlist appears as a key in the live OpenAPI surface. Test fails when a declared BFF path is missing — closes the shallow-merge limitation of `test_openapi_diff.py` flagged in Constitution Check II
- [ ] T119 [P] Add a CI workflow step (extend an existing job in `.github/workflows/ci.yml` or add a small one) that runs `rg -n '/api/v1/' apps/web/src/ --glob '!**/__tests__/**' --glob '!**/lib/types/**'` and fails if any line matches outside the 5 documented exception groups (encoded as a small allowlist file `apps/web/.api-v1-allowlist`). Document the allowlist's contents inline
- [ ] T120 Audit `apps/web/src/lib/types/detection.ts` and `apps/web/src/lib/types/index.ts` for residual legacy literal references. Type-only references (e.g. `type Endpoint = '/api/v1/...'`) are tolerated if they encode the legacy surface contract for API-key clients; remove or migrate any string literals that are actually used as runtime fetch URLs
- [ ] T121 Audit `apps/web/src/lib/api/__tests__/client.permissions.test.ts` to confirm the only `/api/v1/*` references are intentional negative-test fixtures (specifically the `/projects/feed` example at line ~70). Tag each one with a comment if not already
- [ ] T122 Run the repo-wide final static guard: `rg -n '/api/v1/' apps/web/src/ --glob '!**/__tests__/**' --glob '!**/lib/types/**' --glob '!**/.api-v1-allowlist'`. Output MUST contain only the 5 documented exception groups (`PATCH /api/v1/users/me`, `/api/v1/users/me/api-tokens*`, `/api/v1/users/me/password`, `/api/v1/setup/*`, `/api/v1/test`). Any other hit fails this task
- [ ] T122a Run the legacy `/api/v1/*` regression suite on post-migration HEAD: `(cd apps/api && uv run pytest tests/contract tests/integration -q)` — the full integration tree covers v1 flows (e.g. `test_project_flow.py`, `test_token_auth.py`, `test_admin_flow.py`; there is no separate `tests/integration/api/v1/` subpath). Capture the pass/fail count and diff against the baseline recorded in T002. **Zero new failures required** for SC-003 evidence. Record summary in `specs/009-browser-api-bff-migration/sc-evidence.md` under "SC-003"
- [ ] T123 Gate 3 SC-001 final walkthrough: as `test@echoroo.app`, complete `/en/projects → project detail → datasets → annotations → admin section once`. Confirm zero `/api/v1/*` calls outside the exception list (record `browser_network_requests` log). This is the SC-001 evidence captured in `specs/009-browser-api-bff-migration/sc-evidence.md`
- [ ] T124 [P] Update `memory/MEMORY.md` to add a one-line entry pointing to a new memory file `memory/project_009_completion.md` summarising spec/009 completion (PR list, merged HEADs, residual exceptions). The memory file itself summarises in 10 lines or fewer
- [ ] T125 Run `quickstart.md` Gate 1 / 2 / 3 end-to-end on the final main HEAD after all PRs merged to verify the migration's success criteria SC-001 through SC-008 are met

---

## Dependencies & Execution Order

### Phase dependencies

- **Phase 1 (Setup)**: no dependencies — start immediately
- **Phase 2 (Foundational)**: depends on Phase 1; blocks ALL Phase 3+
- **Phase 3 (US1)**: depends on Phase 2. PR A unblocks PR A2 (A2's frontend rewires assume A's read pattern is in place)
- **Phase 4 (US2)**: depends on Phase 2. PR C and PR D may proceed in parallel after their respective tests are written. PR D depends on its own D-10 pre-audit (T068–T073)
- **Phase 5 (US3)**: depends on Phase 2 AND T085 (admin package refactor). PRs E / F / G / H share `admin.yaml` and `web_v1/admin/__init__.py` — limit to 2 concurrent worktrees. PR E lands first as template
- **Phase 6 (US4)**: depends on Phase 2. Independent of US1/US2/US3
- **Phase 8 (US5 setup verification)**: depends on Phase 2. Independent of all other US phases — single verification task with no code changes
- **Phase 9 (Polish)**: depends on every prior phase including Phase 8. T118 (parity test) ratifies the parity allowlist appended throughout the migration; T122a captures SC-003 evidence on the post-migration HEAD

### User story dependencies

- **US1 (P1)**: depends only on Foundational. MVP scope — STOP and validate after PR A2
- **US2 (P2)**: independent of US1 once Foundational completes. May proceed in parallel
- **US3 (P3)**: independent of US1/US2. Depends on the admin package refactor (T085)
- **US4 (P3)**: independent of US1/US2/US3. Smallest surface
- **US5 (P4)**: independent of all other stories. Verification-only task, no code changes (FR-013 / documented exception)

### Within each PR

- Tests (T021, T030–T035, T057, T074, T086, T095, T101, T107, T118) are written FIRST and MUST FAIL before the corresponding handler / rewire is implemented (per constitution Principle II)
- Backend handlers MUST land before frontend rewires that target them
- The parity allowlist append MUST happen in the same PR as the rewire (otherwise PR J's `test_bff_path_parity.py` cannot ratify the migration)
- The static guard task MUST be the last task before Gate 3 (catches forgotten legacy literals)
- Gate 3 browser smoke MUST be the final task before marking the PR ready for merge (per CLAUDE.md definition-of-done)

### Parallel opportunities (per memory: max 2 concurrent SSAs with worktree isolation)

- T004–T011 are mutually independent (different test-helper functions). Run in one parallel batch
- T030–T035 (PR A2 tests) are mutually independent — different test files
- T040, T041, T042 (PR A2 core mutations) touch the same `_core.py` and MUST run sequentially within a single SSA invocation
- T086, T095, T101, T107 (PR E/F/G/H tests) are file-independent — schedule pairs (E+F, then G+H) under worktree isolation
- T068–T072 (PR D pre-audit items) are independent investigations

---

## Parallel example: Phase 2 foundational

```bash
# Launch all D-2a helper additions in one batch (different functions in the same _helpers.py file):
Task: "T004 Add assert_audit_actor_kind_session helper..."
Task: "T005 Add assert_rate_limit_bucket_web helper..."
Task: "T006 Add assert_api_key_cross_rejected helper..."
Task: "T007 Add assert_permission_denial_returns_403 helper..."
Task: "T008 Add assert_csrf_required helper..."
```

These all write to `_helpers.py` so coordinate as a single SSA invocation; not literally separate worktrees.

```bash
# T010 + T011 + T003 are independent files — true parallel:
Task: "T003 Record audit-baseline.md"
Task: "T010 Create _bff_path_parity_allowlist.py"
Task: "T011 Create audit_browser_api_v1.sh"
```

---

## Implementation strategy

### MVP first (US1 only)

1. Complete Phase 1: Setup (3 tasks)
2. Complete Phase 2: Foundational (17 tasks — PR B ships as its own PR mid-phase)
3. Complete Phase 3: US1 (PR A then PR A2 — 36 tasks)
4. **STOP and VALIDATE**: `/en/projects` and full project mutation lifecycle on BFF
5. Deploy / demo if ready — this is the MVP

### Incremental delivery (recommended)

1. Setup + Foundational + US1 (MVP)
2. + US2 (PR C taxa, PR D exports) → validate annotation workflow
3. + US3 (PR E/F/G/H admin) → validate admin workflows
4. + US4 (PR I explore) → validate public surface
5. + Polish (PR J parity test + CI guard) — locks the migration

### Parallel team strategy

With two SSAs (memory: max 2 worktrees):

1. After Phase 2 completes, SSA-A takes PR A → PR A2 (US1 cannot parallelize across PRs)
2. In parallel: SSA-B takes PR C (US2 taxa)
3. After PR A2 lands: SSA-A takes PR D (US2 exports), SSA-B takes PR E (US3 licenses)
4. After PR E lands as template: pairs of PRs F+G then H run sequentially within each SSA, with worktree isolation
5. PR I (US4) and PR J (Polish) ship single-SSA at the end

---

## Notes

- `[P]` tasks may run in parallel only when they touch different files. Tasks touching the same file (e.g. multiple handlers in `_core.py`) MUST be sequential within a single SSA invocation
- `[Story]` label maps tasks to spec.md user stories for traceability through PR reviews
- Per the constitution: tests MUST fail before implementation begins (`pytest -q` should show RED on the test task before the matching handler task starts; GREEN after)
- Commit cadence: one commit per PR boundary minimum, optionally one commit per logical task group within a PR
- Stop at any checkpoint (end of US phase) to validate independently — this is the MVP-mode preview before continuing
- The 5 documented exceptions (PATCH `/users/me`, `/users/me/api-tokens*`, `/users/me/password`, `/setup/*`, `/test`) MUST never be touched by this migration and MUST never be removed by PR J — they remain on legacy by design
- Avoid: rewiring `/users/me/password` or `/users/me/api-tokens*` (those are out of scope per spec FR-011 / SC-004)
