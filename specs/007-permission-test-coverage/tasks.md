# Tasks: Seeded Permission E2E Coverage

**Input**: Design documents from `specs/007-permission-test-coverage/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/seeded-permission-e2e.md`, `quickstart.md`

**Tests**: Required by the feature specification and Echoroo Constitution. Each user-story slice starts with the Playwright test file and must be verified against the seeded local environment.

**Organization**: Tasks are grouped by user story so Data Surfaces, Vote/Comment, and future risky-surface planning remain independently implementable and testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it touches different files or only reads context
- **[Story]**: User story label for story phases only
- All paths are project-relative to `/home/okamoto/Projects/echoroo`

## Phase 1: Setup (Shared Context)

**Purpose**: Confirm current baseline and avoid overwriting existing in-progress seeded E2E work.

- [X] T001 Review current handoff baseline and green commands in `specs/007-permission-test-coverage/e2e-roadmap.md`
- [X] T002 [P] Review current seeded fixture env output in `apps/api/echoroo/scripts/seed_e2e_permissions.py`
- [X] T003 [P] Review reusable browser login and auth helpers in `apps/web/tests/e2e/permissions/seeded-permissions.helpers.ts`
- [X] T004 [P] Review current seeded API/UI expectation patterns in `apps/web/tests/e2e/permissions/seeded-feature-permissions.spec.ts`
- [X] T005 [P] Review current seeded matrix skip/env conventions in `apps/web/tests/e2e/permissions/seeded-permissions-matrix.spec.ts`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Add shared fixture/env and helper support required by both P1 stories.

**CRITICAL**: Complete this phase before adding either new Playwright suite.

- [X] T006 Add `E2E_PUBLIC_SITE_ID`, `E2E_PUBLIC_RECORDING_ID`, `E2E_PUBLIC_DETECTION_ID`, `E2E_RESTRICTED_SITE_ID`, `E2E_RESTRICTED_RECORDING_ID`, and `E2E_RESTRICTED_DETECTION_ID` to the flat env payload in `apps/api/echoroo/scripts/seed_e2e_permissions.py`
- [X] T007 Update seeded fixture usage documentation for the new flat env values in `apps/api/README.md`
- [X] T008 Refactor shared seeded E2E types, env readers, `backendApiUrl()`, and `expectStatus()` into `apps/web/tests/e2e/permissions/seeded-permissions.helpers.ts`
- [X] T009 Update existing seeded feature suite imports to use shared helpers from `apps/web/tests/e2e/permissions/seeded-feature-permissions.spec.ts`
- [X] T010 Update existing seeded matrix suite imports only if shared type/env changes require it in `apps/web/tests/e2e/permissions/seeded-permissions-matrix.spec.ts`
- [X] T011 Run and record ruff check, ruff format check, py_compile, and mypy checks for `apps/api/echoroo/scripts/seed_e2e_permissions.py`
- [X] T012 Run and record Prettier, ESLint, and `npm run check` for existing seeded E2E files in `apps/web/tests/e2e/permissions/seeded-permissions.helpers.ts`, `apps/web/tests/e2e/permissions/seeded-feature-permissions.spec.ts`, and `apps/web/tests/e2e/permissions/seeded-permissions-matrix.spec.ts`

**Checkpoint**: Seeder emits all shared env values, existing seeded suites still compile, and new suites can consume one helper contract.

---

## Phase 3: User Story 1 - Data Surface Permission Confidence (Priority: P1) MVP

**Goal**: Prove seeded users see only allowed dataset, recording, detection, and public explore data surfaces without asserting media playback.

**Independent Test**: `E2E_DATA_SURFACES_ENABLED=1 npx playwright test tests/e2e/permissions/seeded-data-surfaces.spec.ts --reporter=list --workers=1`

### Tests for User Story 1

- [X] T013 [US1] Create failing opt-in Playwright suite skeleton with required env guards in `apps/web/tests/e2e/permissions/seeded-data-surfaces.spec.ts`
- [X] T014 [US1] Add dataset list/detail read assertions for owner/admin/member/viewer and denial/non-leak expectations for nonmember/trusted in `apps/web/tests/e2e/permissions/seeded-data-surfaces.spec.ts`
- [X] T015 [US1] Add recording list/detail read assertions using `E2E_*_RECORDING_ID` while excluding audio/playback/spectrogram checks in `apps/web/tests/e2e/permissions/seeded-data-surfaces.spec.ts`
- [X] T016 [US1] Add detection list smoke coverage and guarded tag-ID derivation for detail navigation in `apps/web/tests/e2e/permissions/seeded-data-surfaces.spec.ts`
- [X] T017 [US1] Add public explore list/detail guest checks and owner email/non-public member email/API key/TOTP/storage path non-leak assertions in `apps/web/tests/e2e/permissions/seeded-data-surfaces.spec.ts`

### Implementation for User Story 1

- [X] T018 [US1] Implement role and visibility expectation tables for data surfaces in `apps/web/tests/e2e/permissions/seeded-data-surfaces.spec.ts`
- [X] T019 [US1] Implement reusable page assertion helpers for allowed, denied, UI-login session, and non-leak states in `apps/web/tests/e2e/permissions/seeded-data-surfaces.spec.ts`
- [X] T020 [US1] Keep detection service instability isolated by skipping only unstable detection detail assertions with an explicit reason in `apps/web/tests/e2e/permissions/seeded-data-surfaces.spec.ts`
- [X] T021 [US1] Run the local seed command and export latest env from `/tmp/echoroo-e2e-seed.json` for `apps/web/tests/e2e/permissions/seeded-data-surfaces.spec.ts`
- [X] T022 [US1] Run Prettier, ESLint, and `npm run check` for `apps/web/tests/e2e/permissions/seeded-data-surfaces.spec.ts`
- [X] T023 [US1] Run the new data-surfaces Playwright suite with `--workers=1` for `apps/web/tests/e2e/permissions/seeded-data-surfaces.spec.ts`
- [X] T024 [US1] Re-run existing seeded feature and matrix Playwright suites for `apps/web/tests/e2e/permissions/seeded-feature-permissions.spec.ts` and `apps/web/tests/e2e/permissions/seeded-permissions-matrix.spec.ts`
- [X] T025 [US1] Update verified commands and residual risk notes for Data Surfaces in `specs/007-permission-test-coverage/e2e-roadmap.md`

**Checkpoint**: Data Surfaces is green independently and existing seeded baseline remains green.

---

## Phase 4: User Story 2 - Vote and Comment Permission Confidence (Priority: P1)

**Goal**: Make vote/comment authorization explicit through `/api/v1` raw API key checks for all seeded roles and both project visibilities.

**Independent Test**: `E2E_VOTE_COMMENT_ENABLED=1 npx playwright test tests/e2e/permissions/seeded-vote-comment.spec.ts --reporter=list --workers=1`

### Tests for User Story 2

- [X] T026 [US2] Create failing opt-in Playwright suite skeleton with required env guards in `apps/web/tests/e2e/permissions/seeded-vote-comment.spec.ts`
- [X] T027 [US2] Add GET vote and GET comment status checks for all roles and visibilities in `apps/web/tests/e2e/permissions/seeded-vote-comment.spec.ts`
- [X] T028 [US2] Add POST vote status checks using seeded raw API keys and `{ vote: "agree", signal_quality: "solo" }` in `apps/web/tests/e2e/permissions/seeded-vote-comment.spec.ts`
- [X] T029 [US2] Add POST comment status checks with unique role/visibility/run body values in `apps/web/tests/e2e/permissions/seeded-vote-comment.spec.ts`
- [X] T030 [US2] Add DELETE vote checks that create a same-user vote before deletion to avoid 404 order coupling in `apps/web/tests/e2e/permissions/seeded-vote-comment.spec.ts`

### Implementation for User Story 2

- [X] T031 [US2] Implement API expectation table for public and restricted vote/comment behavior in `apps/web/tests/e2e/permissions/seeded-vote-comment.spec.ts`
- [X] T032 [US2] Configure the vote/comment suite for serial mutation safety in `apps/web/tests/e2e/permissions/seeded-vote-comment.spec.ts`
- [X] T033 [US2] Add same-user vote replacement coverage such as `agree` to `disagree` before DELETE cleanup in `apps/web/tests/e2e/permissions/seeded-vote-comment.spec.ts`
- [X] T034 [US2] Ensure the vote/comment suite uses only `E2E_*_API_KEY` values for `/api/v1` requests in `apps/web/tests/e2e/permissions/seeded-vote-comment.spec.ts`
- [X] T035 [US2] Assert comment creation by response status/body presence instead of exact list counts in `apps/web/tests/e2e/permissions/seeded-vote-comment.spec.ts`
- [X] T036 [US2] Run the local seed command and export latest env from `/tmp/echoroo-e2e-seed.json` for `apps/web/tests/e2e/permissions/seeded-vote-comment.spec.ts`
- [X] T037 [US2] Run Prettier, ESLint, and `npm run check` for `apps/web/tests/e2e/permissions/seeded-vote-comment.spec.ts`
- [X] T038 [US2] Run the new vote-comment Playwright suite with `--workers=1` for `apps/web/tests/e2e/permissions/seeded-vote-comment.spec.ts`
- [X] T039 [US2] Re-run existing seeded feature and matrix Playwright suites for `apps/web/tests/e2e/permissions/seeded-feature-permissions.spec.ts` and `apps/web/tests/e2e/permissions/seeded-permissions-matrix.spec.ts`
- [X] T040 [US2] Update verified commands and residual risk notes for Vote/Comment in `specs/007-permission-test-coverage/e2e-roadmap.md`

**Checkpoint**: Vote/Comment is green independently and does not destabilize the existing seeded baseline.

---

## Phase 5: User Story 3 - Risky Surface Roadmap (Priority: P2)

**Goal**: Keep trusted overlay, export/search, and media slices ready for later implementation with explicit seed, review, and verification gates.

**Independent Test**: Review `specs/007-permission-test-coverage/e2e-roadmap.md` and confirm each future slice has suite path, seed needs, completion gate, and Claude-review trigger.

### Tests for User Story 3

- [X] T041 [US3] Add future-suite gate checklist entries for trusted overlay, export/search, and media in `specs/007-permission-test-coverage/e2e-roadmap.md`

### Implementation for User Story 3

- [X] T042 [US3] Document disposable trusted-user seed requirements for lifecycle tests in `specs/007-permission-test-coverage/e2e-roadmap.md`
- [X] T043 [US3] Document search-session seed requirements and export contract risks in `specs/007-permission-test-coverage/e2e-roadmap.md`
- [X] T044 [US3] Document media fixture storage requirements and nonblank browser verification gates in `specs/007-permission-test-coverage/e2e-roadmap.md`
- [X] T045 [US3] Document Claude review triggers for lifecycle mutation, export/search contracts, storage, and media auth in `specs/007-permission-test-coverage/e2e-roadmap.md`

**Checkpoint**: Future risky slices have clear prerequisites and do not block US1/US2 implementation.

---

## Phase 6: Polish & Cross-Cutting Verification

**Purpose**: Final validation and documentation after selected user stories are implemented.

- [X] T046 Run `git diff --check` for the full working tree rooted at `/home/okamoto/Projects/echoroo`
- [X] T047 Run ruff check, ruff format check, py_compile, and mypy for `apps/api/echoroo/scripts/seed_e2e_permissions.py`
- [X] T048 Run Prettier, ESLint, and `npm run check` for all seeded permission E2E files in `apps/web/tests/e2e/permissions/seeded-permissions.helpers.ts`, `apps/web/tests/e2e/permissions/seeded-permissions-matrix.spec.ts`, `apps/web/tests/e2e/permissions/seeded-feature-permissions.spec.ts`, `apps/web/tests/e2e/permissions/seeded-data-surfaces.spec.ts`, and `apps/web/tests/e2e/permissions/seeded-vote-comment.spec.ts`
- [X] T049 Run the full seeded permission Playwright set for `apps/web/tests/e2e/permissions/seeded-feature-permissions.spec.ts`, `apps/web/tests/e2e/permissions/seeded-permissions-matrix.spec.ts`, `apps/web/tests/e2e/permissions/seeded-data-surfaces.spec.ts`, and `apps/web/tests/e2e/permissions/seeded-vote-comment.spec.ts`
- [X] T050 Update implementation status, verified command output summaries, and remaining risks in `specs/007-permission-test-coverage/e2e-roadmap.md`
- [X] T051 Review final changed-file scope and summarize residual risks in `specs/007-permission-test-coverage/tasks.md`

---

## Phase 7: User Story 4 - Trusted Overlay Read/List Confidence (Priority: P2)

**Goal**: Cover non-destructive Trusted Overlay management visibility and trusted capability behavior before lifecycle mutation tests.

**Independent Test**: `E2E_TRUSTED_OVERLAY_ENABLED=1 npx playwright test tests/e2e/permissions/seeded-trusted-overlay.spec.ts --reporter=list --workers=1`

### Tests for User Story 4

- [X] T052 [US4] Create opt-in Playwright suite with required env guards in `apps/web/tests/e2e/permissions/seeded-trusted-overlay.spec.ts`
- [X] T053 [US4] Add owner UI assertions for active trusted rows, invite form, and enabled row actions in `apps/web/tests/e2e/permissions/seeded-trusted-overlay.spec.ts`
- [X] T054 [US4] Add admin read-only UI assertions for active trusted rows, read-only notice, hidden invite form, and disabled row actions in `apps/web/tests/e2e/permissions/seeded-trusted-overlay.spec.ts`
- [X] T055 [US4] Add member/viewer/nonmember/trusted management UI denial assertions in `apps/web/tests/e2e/permissions/seeded-trusted-overlay.spec.ts`
- [X] T056 [US4] Add restricted project API capability checks proving trusted overlay `export` access without project membership in `apps/web/tests/e2e/permissions/seeded-trusted-overlay.spec.ts`

### Implementation for User Story 4

- [X] T057 [US4] Keep the suite read-only and avoid mutating the baseline trusted overlay in `apps/web/tests/e2e/permissions/seeded-trusted-overlay.spec.ts`
- [X] T058 [US4] Run the local seed command and export latest env from `/tmp/echoroo-e2e-seed.json`
- [X] T059 [US4] Run Prettier, ESLint, and `npm run check` for seeded permission E2E files including `apps/web/tests/e2e/permissions/seeded-trusted-overlay.spec.ts`
- [X] T060 [US4] Run the new trusted-overlay Playwright suite with `--workers=1`
- [X] T061 [US4] Re-run the full seeded permission Playwright set including Trusted Overlay
- [X] T062 [US4] Update verified commands and remaining lifecycle risk notes in `specs/007-permission-test-coverage/e2e-roadmap.md` and `specs/007-permission-test-coverage/quickstart.md`

**Checkpoint**: Trusted Overlay read/list/capability coverage is green independently and with the existing seeded baseline; lifecycle mutation is handled in US5 with disposable seed state and Claude review.

---

## Phase 8: User Story 5 - Trusted Overlay Lifecycle Confidence (Priority: P2)

**Goal**: Cover owner-only trusted overlay lifecycle mutations without mutating the immutable baseline trusted overlay.

**Independent Test**: `E2E_TRUSTED_OVERLAY_ENABLED=1 npx playwright test tests/e2e/permissions/seeded-trusted-overlay.spec.ts --reporter=list --workers=1`

### Tests for User Story 5

- [X] T063 [US5] Add a distinct `trusted_lifecycle` seeded user, API key, and env output in `apps/api/echoroo/scripts/seed_e2e_permissions.py`
- [X] T064 [US5] Seed one restricted-project disposable active trusted lifecycle overlay and one expired lifecycle overlay without changing the baseline trusted overlay in `apps/api/echoroo/scripts/seed_e2e_permissions.py`
- [X] T065 [US5] Add owner PATCH permission-edit and expiry-extension API checks for the disposable overlay in `apps/web/tests/e2e/permissions/seeded-trusted-overlay.spec.ts`
- [X] T066 [US5] Add admin PATCH/DELETE denial checks before owner revocation in `apps/web/tests/e2e/permissions/seeded-trusted-overlay.spec.ts`
- [X] T067 [US5] Add owner DELETE revoke, revoked-filter, and post-revoke capability-denial checks for the lifecycle user in `apps/web/tests/e2e/permissions/seeded-trusted-overlay.spec.ts`
- [X] T068 [US5] Add owner fresh trusted-invitation issuance and expired-filter checks while leaving accept-token activation for future email/outbox coverage

### Implementation for User Story 5

- [X] T069 [US5] Run seed, Python static/type checks, E2E file Prettier/ESLint, `npm run check`, the trusted suite, and the full seeded permission Playwright set
- [X] T070 [US5] Run bounded Claude review for trusted lifecycle changes and apply active-overlay lookup polish
- [X] T071 [US5] Update verified commands, lifecycle seed notes, and residual risks in `specs/007-permission-test-coverage/e2e-roadmap.md`, `specs/007-permission-test-coverage/quickstart.md`, and related planning docs

**Checkpoint**: Trusted Overlay lifecycle coverage is green independently and with the full seeded baseline; invitation accept/re-grant activation remains future scope because the signed token is delivered through email/outbox rather than the API response.

---

## Phase 9: User Story 6 - Export/Search Permission Confidence (Priority: P2)

**Goal**: Cover API-primary export and search permission behavior without storage-backed export body assertions.

**Independent Test**: `E2E_EXPORT_SEARCH_ENABLED=1 npx playwright test tests/e2e/permissions/seeded-export-search.spec.ts --reporter=list --workers=1`

### Tests for User Story 6

- [X] T072 [US6] Create opt-in Playwright suite with required env guards in `apps/web/tests/e2e/permissions/seeded-export-search.spec.ts`
- [X] T073 [US6] Add stable completed `SearchSession` seed rows and `E2E_PUBLIC_SEARCH_SESSION_ID` / `E2E_RESTRICTED_SEARCH_SESSION_ID` env output in `apps/api/echoroo/scripts/seed_e2e_permissions.py`
- [X] T074 [US6] Add search session list/detail role and visibility checks in `apps/web/tests/e2e/permissions/seeded-export-search.spec.ts`
- [X] T075 [US6] Add detection CSV and search session CSV export status/content-type checks in `apps/web/tests/e2e/permissions/seeded-export-search.spec.ts`
- [X] T076 [US6] Keep `export-recordings`, reference-audio, dataset export with audio, and CSV row/body assertions out of scope until contract/storage review

### Implementation for User Story 6

- [X] T077 [US6] Run the local seed command, Python static/type checks, E2E file Prettier/ESLint, `npm run check`, the export/search suite, and the full seeded permission Playwright set
- [X] T078 [US6] Run bounded Claude review for the seed and export/search suite changes and record that no blocking findings remain
- [X] T079 [US6] Update verified commands, seed contract notes, and residual risks in `specs/007-permission-test-coverage/e2e-roadmap.md`, `specs/007-permission-test-coverage/quickstart.md`, and related planning docs

**Checkpoint**: Export/Search API-primary coverage is green independently and with the full seeded baseline; storage-backed export bodies remain future slices requiring contract review. `export-recordings` and reference-audio permission-boundary guards are handled later in US9.

---

## Phase 10: User Story 7 - Media Permission Confidence (Priority: P2)

**Goal**: Cover recording and clip media endpoints plus representative browser media wiring with a real seeded WAV fixture.

**Independent Test**: `E2E_MEDIA_ENABLED=1 npx playwright test tests/e2e/permissions/seeded-media.spec.ts --reporter=list --workers=1`

### Tests for User Story 7

- [X] T080 [US7] Add deterministic WAV fixture generation and idempotent local storage seeding for seeded recording paths in `apps/api/echoroo/scripts/seed_e2e_permissions.py`
- [X] T081 [US7] Create opt-in Playwright suite with required env guards in `apps/web/tests/e2e/permissions/seeded-media.spec.ts`
- [X] T082 [US7] Add API-primary byte/content-type checks for recording `/audio`, `/playback`, `/spectrogram`, and `/download` in `apps/web/tests/e2e/permissions/seeded-media.spec.ts`
- [X] T083 [US7] Add explicit role/visibility/endpoint status expectation tables, including current `VIEW_MEDIA`-gated recording download behavior
- [X] T084 [US7] Add guest public/restricted media checks and owner/trusted restricted browser media smoke coverage
- [X] T089 [US7] Seed one stable clip per seeded recording and expose `E2E_PUBLIC_CLIP_ID` / `E2E_RESTRICTED_CLIP_ID` in `apps/api/echoroo/scripts/seed_e2e_permissions.py`
- [X] T090 [US7] Add API-primary byte/content-type checks for clip `/audio`, `/spectrogram`, and `/download` in `apps/web/tests/e2e/permissions/seeded-media.spec.ts`
- [X] T091 [US7] Align clip media endpoints with S3-first recording fixtures by resolving parent recording paths through `AudioService.ensure_file_local()` in `apps/api/echoroo/api/v1/clips.py`
- [X] T095 [US7] Add guest clip media authentication checks and document restricted nonmember clip media expectations in `apps/web/tests/e2e/permissions/seeded-media.spec.ts`

### Implementation for User Story 7

- [X] T085 [US7] Run seed, Python static/type checks, E2E file Prettier/ESLint, `npm run check`, the media suite, and the full seeded permission Playwright set
- [X] T086 [US7] Run bounded Claude review for storage setup, media auth, and browser rendering assertions; apply explicit status-matrix follow-up
- [X] T087 [US7] Re-run the media suite after review follow-up and confirm it remains green
- [X] T088 [US7] Update verified commands, media seed notes, and residual risks in `specs/007-permission-test-coverage/e2e-roadmap.md`, `specs/007-permission-test-coverage/quickstart.md`, and related planning docs
- [X] T092 [US7] Re-run seed, API static/type checks, E2E file Prettier/ESLint, `npm run check`, the expanded media suite, and the full seeded permission Playwright set after clip coverage
- [X] T093 [US7] Run bounded Claude review for clip seed/spec/backend media changes and record that no blocking findings remain
- [X] T094 [US7] Update verified commands, clip media seed notes, and residual risks in `specs/007-permission-test-coverage/e2e-roadmap.md`, `specs/007-permission-test-coverage/quickstart.md`, and related planning docs
- [X] T096 [US7] Re-run the expanded media suite and full seeded permission Playwright set after Claude review follow-up

**Checkpoint**: Media coverage is green independently and with the full seeded baseline for recording and clip API-primary media. Clip browser UI wiring is handled in US14; broader storage-backed export media flows remain future scope.

---

## Phase 11: User Story 8 - Dataset Export ZIP Confidence (Priority: P2)

**Goal**: Cover dataset export ZIP permissions and minimal archive shape without adding audio-storage requirements.

**Independent Test**: `E2E_EXPORT_SEARCH_ENABLED=1 npx playwright test tests/e2e/permissions/seeded-export-search.spec.ts --reporter=list --workers=1`

### Tests for User Story 8

- [X] T097 [US8] Review export/search storage-backed follow-up candidates and select dataset export `include_audio=false` as the smallest stable slice
- [X] T098 [US8] Add `E2E_PUBLIC_DATASET_ID` / `E2E_RESTRICTED_DATASET_ID` requirements to `apps/web/tests/e2e/permissions/seeded-export-search.spec.ts`
- [X] T099 [US8] Add dataset export ZIP role/visibility expectations using the existing `EXPORT`-gated matrix in `apps/web/tests/e2e/permissions/seeded-export-search.spec.ts`
- [X] T100 [US8] Assert dataset export ZIP content type, `.zip` disposition, `PK` magic bytes, and `datapackage.json` / `deployments.csv` / `media.csv` entries for allowed roles

### Implementation for User Story 8

- [X] T101 [US8] Run export/search suite, Prettier, ESLint, `npm run check`, and the full seeded permission Playwright set after dataset ZIP coverage
- [X] T102 [US8] Re-run seed after lifecycle full-suite verification and update roadmap/tasks/contracts residual risks

**Checkpoint**: Dataset export ZIP coverage is green independently and with the full seeded baseline for `include_audio=false`; dataset export with audio is handled later in US12. `export-recordings` and reference-audio permission-boundary guards are handled later in US9.

---

## Phase 12: User Story 9 - Search Storage Gate Guard Confidence (Priority: P2)

**Goal**: Cover search-session storage-backed endpoints at the permission boundary without requiring seeded result archives or reference-audio objects.

**Independent Test**: `E2E_EXPORT_SEARCH_ENABLED=1 npx playwright test tests/e2e/permissions/seeded-export-search.spec.ts --reporter=list --workers=1`

### Tests for User Story 9

- [X] T103 [US9] Review `export-recordings` and `reference-audio` gate order and confirm the current seeded sessions intentionally have `results=null` and `reference_audio_keys=null`
- [X] T104 [US9] Add explicit backend `gate_action()` checks for `reference-audio` (`VIEW_MEDIA`) and `export-recordings` (`EXPORT`) before storage-backed session processing in `apps/api/echoroo/api/v1/search/sessions.py`
- [X] T105 [US9] Add E2E expectations for allowed fixture-missing 404 details and denied 403 responses in `apps/web/tests/e2e/permissions/seeded-export-search.spec.ts`

### Implementation for User Story 9

- [X] T106 [US9] Run seed, API static/type checks, E2E file Prettier/ESLint, `npm run check`, the export/search suite, and the full seeded permission Playwright set
- [X] T107 [US9] Update roadmap, tasks, contracts, data model, quickstart, plan, and spec notes for search storage gate guard coverage and remaining payload risks

**Checkpoint**: Search storage-backed endpoints are covered at the permission boundary: allowed callers reach deterministic fixture-missing 404 responses, denied callers stop at 403, and successful storage payload assertions remain future scope.

---

## Phase 13: User Story 10 - Export-recordings CSV Payload Confidence (Priority: P2)

**Goal**: Cover one deterministic successful `export-recordings` CSV payload without changing the storage-free guard sessions.

**Independent Test**: `E2E_EXPORT_SEARCH_ENABLED=1 npx playwright test tests/e2e/permissions/seeded-export-search.spec.ts --reporter=list --workers=1`

### Tests for User Story 10

- [X] T108 [US10] Review `export-recordings` payload requirements and select a DB-only exportable session fixture over S3-backed reference-audio or audio ZIP slices
- [X] T109 [US10] Seed one deterministic `Embedding` per seeded recording and one exportable `SearchSession` per project with one `BatchSearchResponse`-shaped result in `apps/api/echoroo/scripts/seed_e2e_permissions.py`
- [X] T110 [US10] Emit `E2E_PUBLIC_EXPORTABLE_SEARCH_SESSION_ID` and `E2E_RESTRICTED_EXPORTABLE_SEARCH_SESSION_ID` in the seed JSON env payload
- [X] T111 [US10] Add an owner API E2E assertion for successful exportable `/export-recordings` CSV header, seeded recording row, species labels, and `1.0000` similarity aggregates in `apps/web/tests/e2e/permissions/seeded-export-search.spec.ts`

### Implementation for User Story 10

- [X] T112 [US10] Run seed, API static/type checks, E2E file Prettier/ESLint, `npm run check`, the export/search suite, and the full seeded permission Playwright set
- [X] T113 [US10] Run bounded Claude review for the export-recordings seed/spec payload contract and update roadmap/tasks/contracts/data-model/quickstart/plan/spec notes

**Checkpoint**: `export-recordings` is covered both at the permission boundary and through one deterministic successful CSV payload; reference-audio streaming is handled in US11 and dataset export with audio is handled in US12.

---

## Phase 14: User Story 11 - Reference-audio Stream Confidence (Priority: P2)

**Goal**: Cover one deterministic successful S3-backed `reference-audio` stream without changing the storage-free guard sessions.

**Independent Test**: `E2E_EXPORT_SEARCH_ENABLED=1 npx playwright test tests/e2e/permissions/seeded-export-search.spec.ts --grep "owner can stream reference audio" --reporter=list --workers=1`

### Tests for User Story 11

- [X] T114 [US11] Review `reference-audio` storage contract and confirm the route reads `SearchSession.reference_audio_keys` directly through S3 rather than `AUDIO_ROOT`
- [X] T115 [US11] Seed one deterministic reference WAV S3 object per exportable search session while leaving storage-free guard sessions at `reference_audio_keys=null`
- [X] T116 [US11] Add owner E2E assertions for full `200` audio responses and `Range: bytes=0-3` `206` responses in `apps/web/tests/e2e/permissions/seeded-export-search.spec.ts`

### Implementation for User Story 11

- [X] T117 [US11] Run seed, API static/type checks, E2E file Prettier/ESLint, `npm run check`, the focused reference-audio test, and the export/search suite
- [X] T118 [US11] Update roadmap, tasks, contracts, data model, quickstart, plan, and spec notes for reference-audio success coverage and remaining dataset audio ZIP risk

**Checkpoint**: `reference-audio` is covered both at the permission boundary and through one deterministic successful full/Range WAV payload; dataset export with audio is handled in US12.

---

## Phase 15: User Story 12 - Dataset Export Audio ZIP Confidence (Priority: P2)

**Goal**: Cover one deterministic successful dataset ZIP export with audio using the seeded S3-backed recording fixture.

**Independent Test**: `E2E_EXPORT_SEARCH_ENABLED=1 npx playwright test tests/e2e/permissions/seeded-export-search.spec.ts --grep "owner can export seeded datasets with audio" --reporter=list --workers=1`

### Tests for User Story 12

- [X] T119 [US12] Review dataset export audio storage contract and confirm S3-only seeded recordings are skipped by the old `get_absolute_path()` path
- [X] T120 [US12] Align dataset export `AudioService` construction with S3 cache settings in `apps/api/echoroo/api/v1/datasets.py`
- [X] T121 [US12] Resolve `include_audio=true` recordings through `AudioService.ensure_file_local()` in `apps/api/echoroo/services/export.py`
- [X] T122 [US12] Add role/visibility matrix E2E assertions for dataset ZIP `include_audio=true`, expected audio entry path, and inflated WAV `RIFF` bytes in `apps/web/tests/e2e/permissions/seeded-export-search.spec.ts`

### Implementation for User Story 12

- [X] T123 [US12] Run API static/type checks, E2E file Prettier/ESLint, the focused dataset-audio test, and the export/search suite
- [X] T124 [US12] Update roadmap, tasks, contracts, data model, quickstart, plan, and spec notes for dataset audio ZIP success coverage and remaining broader payload risks

**Checkpoint**: Dataset export is covered through role/status matrix checks with `include_audio=false` and through role/visibility matrix `include_audio=true` ZIP payload assertions for allowed cases.

---

## Phase 16: User Story 13 - Seeder Hygiene Follow-up (Priority: P2)

**Goal**: Resolve Claude hygiene notes without changing seeded permission expectations.

**Independent Test**: Run the seeder, inspect the emitted payload contract, and run the full seeded permission E2E set.

### Tests for User Story 13

- [X] T125 [US13] Review Claude hygiene notes for seeded API key grants, raw secret stdout duplication, fixture-user lockout state, and project lookup scope
- [X] T126 [US13] Verify the updated seed payload keeps raw secrets in `env` while top-level users/API keys expose env-name metadata only

### Implementation for User Story 13

- [X] T127 [US13] Replace one-size seeded API key grants with role-scoped allowlists in `apps/api/echoroo/scripts/seed_e2e_permissions.py`
- [X] T128 [US13] Narrow seeded project lookup by owner ID in `apps/api/echoroo/scripts/seed_e2e_permissions.py`
- [X] T129 [US13] Reset fixture-user Redis 2FA failure and lockout keys best-effort on seed rerun in `apps/api/echoroo/scripts/seed_e2e_permissions.py`
- [X] T130 [US13] Remove duplicated raw TOTP/API key values from top-level seed JSON while preserving `env`
- [X] T131 [US13] Run seeder, API static/type checks, export/search E2E, full seeded permission E2E, and post-run seeder state restoration
- [X] T132 [US13] Update README, roadmap, tasks, contracts, data model, quickstart, plan, and spec notes for the hygiene contract

**Checkpoint**: Claude hygiene notes are resolved with the full seeded suite still green.

---

## Phase 17: User Story 14 - Clip Browser BFF Media Wiring (Priority: P2)

**Goal**: Cover the recording-detail clip browser path through session BFF
routes and scoped media-token URLs.

**Independent Test**: `E2E_MEDIA_ENABLED=1 npx playwright test tests/e2e/permissions/seeded-media.spec.ts --grep "restricted recording detail wires media UI" --reporter=list --workers=1`

### Tests for User Story 14

- [X] T133 [US14] Review clip browser data flow and confirm browser code should use `/web-api/v1` session routes for clip list/detail rather than `/api/v1` API-key routes
- [X] T134 [US14] Add owner/trusted E2E assertions for tokenized clip preview spectrogram, detail spectrogram, and playback wiring in `apps/web/tests/e2e/permissions/seeded-media.spec.ts`

### Implementation for User Story 14

- [X] T135 [US14] Add read-only clip list/detail BFF adapters in `apps/api/echoroo/api/web_v1/projects/_media.py`
- [X] T136 [US14] Wire clip list/detail browser calls and clip preview/detail media URLs through scoped recording media-token helpers in `apps/web/src/lib/api/clips.ts`, `apps/web/src/lib/components/data/ClipList.svelte`, `apps/web/src/lib/components/data/ClipDetail.svelte`, and `apps/web/src/routes/(app)/projects/[id]/recordings/[recordingId]/+page.svelte`
- [X] T137 [US14] Run API static/type checks for the BFF adapter and frontend checks for changed clip/media files
- [X] T138 [US14] Run the focused clip browser media test and the full media suite
- [X] T139 [US14] Update roadmap, tasks, contracts, data model, quickstart, plan, and spec notes for completed clip browser BFF media-token coverage

**Checkpoint**: Clip browser list/detail requests use session BFF routes, and the restricted recording detail smoke verifies tokenized clip preview, detail spectrogram, and playback URLs for owner/trusted users.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup and blocks US1/US2.
- **US1 Data Surfaces (Phase 3)**: Depends on Foundational.
- **US2 Vote/Comment (Phase 4)**: Depends on Foundational. It can run in parallel with US1 after shared helpers/env are stable, but mutation tests must remain serial within the suite.
- **US3 Risky Roadmap (Phase 5)**: Depends on Rev.6 planning context only and can run after Setup; it does not block US1/US2.
- **Polish (Phase 6)**: Depends on whichever user stories are implemented.
- **US4 Trusted Overlay read/list (Phase 7)**: Depends on the seeded trusted overlay from Foundational and should remain read-only until disposable lifecycle seed state exists.
- **US5 Trusted Overlay lifecycle (Phase 8)**: Depends on disposable trusted lifecycle seed state and should run after a fresh seed because it revokes the disposable active overlay.
- **US6 Export/Search API-primary (Phase 9)**: Depends on seeded API keys and completed `SearchSession` env output. It is independent of Media but requires Claude review for search/export contracts.
- **US7 Media (Phase 10)**: Depends on seeded recording/clip IDs and real WAV fixture storage. It is independent of Export/Search but requires Claude review for storage/media auth/browser wiring.
- **US8 Dataset Export ZIP (Phase 11)**: Depends on seeded dataset IDs and API keys. It extends Export/Search but deliberately avoids audio-storage requirements.
- **US9 Search Storage Gate Guards (Phase 12)**: Depends on seeded search sessions and explicit backend action registration. It extends Export/Search while deliberately avoiding successful storage-backed payload assertions.
- **US10 Export-recordings CSV Payload (Phase 13)**: Depends on seeded recordings, deterministic embeddings, and exportable search sessions. It extends Export/Search with one successful CSV body assertion while leaving S3 reference-audio storage to US11.
- **US11 Reference-audio Stream (Phase 14)**: Depends on deterministic WAV fixtures, S3/LocalStack availability, and exportable search sessions. It extends Export/Search with one successful S3-backed full/Range stream assertion.
- **US12 Dataset Export Audio ZIP (Phase 15)**: Depends on seeded recording WAV objects, S3 cache configuration, and the Export/Search suite harness. It extends dataset ZIP coverage with role/visibility matrix audio payload assertions for allowed cases.
- **US13 Seeder Hygiene (Phase 16)**: Depends on the completed seeded suite surface. It must preserve all existing E2E expectations while tightening fixture output and API key grants.
- **US14 Clip Browser BFF Media Wiring (Phase 17)**: Depends on US7 media fixtures and the recording-detail browser surface. It extends Media with session BFF list/detail and media-token assertions.

### User Story Dependencies

- **US1 (P1)**: MVP. Requires flat recording/detection/site env and shared helpers from Phase 2.
- **US2 (P1)**: Requires shared API helper and annotation/API-key env from Phase 2. Does not depend on US1.
- **US3 (P2)**: Documentation-only roadmap refinement. Does not depend on US1 or US2.
- **US4 (P2)**: Requires active baseline trusted overlays and seeded API keys. Does not depend on Export/Search or Media.
- **US5 (P2)**: Requires disposable trusted lifecycle target state. Does not depend on Export/Search or Media.
- **US6 (P2)**: Requires seeded search sessions and API keys. Does not depend on Trusted Overlay lifecycle or Media.
- **US7 (P2)**: Requires seeded recording paths backed by real media fixtures and stable clip IDs. Does not depend on Export/Search or Trusted Overlay lifecycle.
- **US8 (P2)**: Requires seeded dataset IDs. It depends on the Export/Search suite harness but not on search result storage, reference audio, or media fixtures.
- **US9 (P2)**: Requires seeded storage-free search sessions and API keys. It depends on the Export/Search suite harness and backend action gates but not on seeded result archives or reference-audio objects.
- **US10 (P2)**: Requires seeded deterministic embeddings and exportable search sessions. It depends on the Export/Search suite harness and seeded recordings but not on S3 audio objects.
- **US11 (P2)**: Requires seeded deterministic reference WAV objects in S3 and exportable search sessions. It depends on the Export/Search suite harness and should remain separate from dataset audio ZIP work.
- **US12 (P2)**: Requires seeded deterministic recording WAV objects in S3 and the dataset export audio path to use `AudioService.ensure_file_local()`. It depends on the Export/Search suite harness and remains separate from broader dataset ZIP payload breadth beyond the seeded single-recording fixture.
- **US13 (P2)**: Requires all seeded API key users and suites so role-scoped grants can be verified against the complete matrix.
- **US14 (P2)**: Requires seeded clips, browser-session auth, and the existing recording media-token helper path.

### Within Each User Story

- Tests and suite skeleton first.
- Expectation tables before assertion helpers.
- Mutating tests must be serial or self-contained.
- Verification and roadmap updates complete the story.

## Parallel Opportunities

- T002-T005 can run in parallel as read-only setup review.
- T014-T017 all write `seeded-data-surfaces.spec.ts`; implement them sequentially or assign one worker owner for the file.
- T027-T029 all write `seeded-vote-comment.spec.ts`; implement them sequentially or assign one worker owner for the file.
- US1 and US2 can proceed in parallel after T006-T012 if each worker owns a disjoint suite file.
- T041-T045 can run in parallel with US1/US2 because they only update roadmap documentation, but coordinate writes to `e2e-roadmap.md`.
- Never run the vote/comment mutation suite in parallel with another suite that mutates the same seeded annotations.
- Trusted Overlay lifecycle mutates only disposable lifecycle overlays and should be run after a fresh seed. Do not run it in parallel with tests that assume the lifecycle overlay remains active.
- Export/Search is API-primary and read-only in the completed slice. Dataset ZIP `include_audio=false` is also read-only and storage-light. Search storage gate guards are read-only and assert 403 vs fixture-missing 404 only. The exportable search session covers one deterministic successful `export-recordings` CSV body and one deterministic S3-backed `reference-audio` full/Range stream. Dataset ZIP `include_audio=true` covers role/visibility matrix payload assertions for allowed cases. Keep broader CSV body checks separate until those contracts are reviewed.
- Media is read-only after seeding and can run with other read-only suites. Clip browser UI/BFF media-token coverage is complete; keep future storage-backed export media checks separate until those contracts are reviewed.

## Parallel Example: After Foundational

```text
Worker A owns:
- apps/web/tests/e2e/permissions/seeded-data-surfaces.spec.ts
- Data Surfaces verification and roadmap notes

Worker B owns:
- apps/web/tests/e2e/permissions/seeded-vote-comment.spec.ts
- Vote/Comment verification and roadmap notes

Both workers must not revert existing seeded helper, seed script, or README changes.
```

## Implementation Strategy

### MVP First: User Story 1

1. Complete T001-T012.
2. Complete T013-T025.
3. Stop and validate Data Surfaces with seed, static checks, new suite, and existing baseline suites.

### Incremental Delivery

1. Deliver US1 Data Surfaces.
2. Deliver US2 Vote/Comment.
3. Refresh US3 risky-surface roadmap.
4. Deliver US4 Trusted Overlay read/list/capability coverage.
5. Deliver US5 Trusted Overlay lifecycle coverage.
6. Deliver US6 Export/Search API-primary permission coverage.
7. Deliver US7 Media and Clip API-primary permission coverage.
8. Deliver US8 Dataset Export ZIP permission coverage.
9. Deliver US9 Search Storage Gate Guard coverage.
10. Deliver US10 Export-recordings CSV Payload coverage.
11. Deliver US11 Reference-audio Stream coverage.
12. Deliver US12 Dataset Export Audio ZIP coverage.
13. Deliver US13 Seeder Hygiene follow-up.
14. Deliver US14 Clip Browser BFF Media Wiring coverage.
15. Run cross-cutting verification for implemented stories.

### Verification Commands

Use the command set in `specs/007-permission-test-coverage/quickstart.md` and record exact pass/fail summaries in `specs/007-permission-test-coverage/e2e-roadmap.md`.

## Final Implementation Notes

Changed-file scope reviewed on 2026-05-18:

- Seeder/docs/helper baseline: `apps/api/echoroo/scripts/seed_e2e_permissions.py`, `apps/api/README.md`, and shared seeded E2E helpers.
- New E2E suites: `seeded-data-surfaces.spec.ts`, `seeded-vote-comment.spec.ts`, `seeded-trusted-overlay.spec.ts`, `seeded-export-search.spec.ts`, and `seeded-media.spec.ts`.
- Clip browser media wiring: `apps/api/echoroo/api/web_v1/projects/_media.py`, `apps/web/src/lib/api/clips.ts`, `apps/web/src/lib/components/data/ClipList.svelte`, `apps/web/src/lib/components/data/ClipDetail.svelte`, and `apps/web/src/routes/(app)/projects/[id]/recordings/[recordingId]/+page.svelte`.
- Planning and handoff docs: this tasks file plus the feature plan, spec, contracts, quickstart, data model, research notes, and roadmap.
- Tooling ignore/config updates: web Docker, Prettier, and ESLint ignores for generated coverage/log/env output.

Residual risks:

- Data Surfaces detection detail cases are explicit skips because the current detection list path returns no seeded minimal annotation rows.
- Trusted Overlay lifecycle covers owner edit/extend/revoke, admin mutation denial, expired-filter listing, fresh invite issuance, and post-revoke capability denial. Invitation accept/re-grant activation remains future scope because the signed token is delivered through email/outbox.
- Export/Search currently validates search session status, CSV content type, dataset ZIP shape for `include_audio=false`, role/visibility matrix dataset ZIP audio payloads for `include_audio=true`, search storage guard 403/404 boundaries, one deterministic successful `export-recordings` CSV body, and one deterministic successful `reference-audio` full/Range WAV stream.
- Media covers seeded recording audio/playback/spectrogram/download bytes, clip audio/spectrogram/download bytes, representative owner/trusted recording browser media wiring, and clip browser UI/BFF media-token wiring.
- Broader dataset audio ZIP payload checks beyond the seeded single-recording fixture remain out of scope pending storage and payload contract review.
- Clip browser UI/BFF media-token wiring is covered through restricted recording detail smoke tests for owner/trusted users; broader UX behavior beyond list/select/detail media loading remains out of scope.
- Guest public explore list currently includes restricted project metadata; current tests assert private metadata non-leak rather than restricted ID absence.
- `npm run check` passes with 0 errors and existing Svelte warnings unrelated to this slice.
