---
description: "Tasks for License Master Unification (spec/012) — rev.2 after Codex review"
---

# Tasks: License Master Unification

**Input**: Design documents from `specs/012-license-master-unification/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md (all present)
**Revised**: 2026-05-27 — incorporates Codex review findings (致命 4 / 重要 5 / 軽微 2)

## Delivery shape (revised)

The original plan called for a single PR. Codex review flagged that 53 tasks spanning migration + backend + frontend + admin UX + enum cleanup in one PR is high-risk given the forward-only nature of the migration. **Revised approach: 2-PR split.**

| PR | Scope | Risk | Rough size |
|---|---|---|---|
| **PR-A** (backend + migration) | Phase 1 + 2 + 3 backend half + 4 + 5 backend half + Phase 6 backend polish | Migration is destructive and forward-only; concentrate the dangerous changes in one well-reviewed PR | ~40 tasks, ~30 files |
| **PR-B** (frontend) | Phase 3 frontend half + Phase 5 frontend half + Phase 6 frontend polish | Pure UI work, easy to revert | ~13 tasks, ~6 files |

PR-B depends on PR-A merging first (frontend will 404/422 against an old backend). Implementer may choose to land PR-A behind a feature flag in dev if more cautious staging is desired.

Phases below remain organized as MVP-first checkpoints; PR-A covers Phases 1–5 backend + Phase 6 backend, PR-B covers Phases 3 + 5 frontend + Phase 6 frontend. Each PR is independently mergeable once its dependency is in place.

## Tests are REQUIRED

Per the Echoroo constitution principle II (Test-Driven Development is NON-NEGOTIABLE), every implementation task in this list has a preceding test task. The test MUST be written first and MUST fail before the corresponding implementation task is started.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: task touches files not shared with any prior incomplete task in the same phase, AND has no dependency on any prior incomplete task
- **[Story]**: which user story the task delivers — US1, US2, US3 (Setup / Foundational / Polish have no Story label)
- File paths are absolute under the repository root (`apps/api/...` or `apps/web/...`)

## Path conventions

- Backend: `apps/api/echoroo/...` + `apps/api/tests/...`
- Frontend: `apps/web/src/...`
- Migrations: `apps/api/alembic/versions/`

### Critical backend paths (verified against the actual codebase during plan review)

- **Admin license CRUD (Bearer)**: `apps/api/echoroo/api/v1/admin.py` — single aggregated admin module, not a per-resource file. The license-handler functions live inside it.
- **Admin license CRUD (BFF, cookie session)**: `apps/api/echoroo/api/web_v1/_admin_licenses.py` — this is what the SvelteKit admin UI calls. **Contract tests and 409 mapping MUST cover BOTH.**
- **Project license history model**: `apps/api/echoroo/models/project.py:271` — `ProjectLicenseHistory`. Has `old_license` + `new_license` columns typed as the `ProjectLicense` enum, both of which require migration to `VARCHAR(50)` (see FR-005a, R8, data-model.md step 8).
- **Detection export FR-086 license column**: `apps/api/echoroo/services/detection_export.py:381` — currently reads `project.license.value` (enum access). Must change to read the joined `short_name` string.

---

## Phase 1: Setup

**Purpose**: One-off checks before writing tests or code.

- [ ] T001 Confirm the next free Alembic revision number. Check `apps/api/alembic/versions/` for current HEAD (`0023` after PR #116 merges; rebase later if other migrations land first). Update the migration filename and `down_revision` accordingly before writing T002+.

---

## Phase 2: Foundational — Migration (Blocking Prerequisites) [PR-A]

**Purpose**: Schema change is a hard prerequisite for every user story. The migration covers BOTH the `projects.license` → `projects.license_id` FK switch AND the `project_license_history.old_license` / `.new_license` type changes (R8). Model annotations also land here so subsequent test fixtures and runtime code can rely on the new shape.

**⚠️ CRITICAL**: No user-story work can begin until Phase 2 is green.

### Tests (write FIRST, must FAIL before implementation)

- [ ] T002 Write failing integration test for migration 0024 happy path in `apps/api/tests/integration/migrations/test_0024_license_unification.py` — mirror the testcontainers pattern from `test_0022_email_subsystem_removal.py`. Assert: (a) seed inserts the four canonical license rows with `ON CONFLICT (short_name) DO NOTHING` (admin-curated rows with same short_name are preserved); (b) every pre-existing `projects.license` enum value maps deterministically to the new `license_id`; (c) `projects.license` column is dropped; (d) `projects.license_id` has an FK constraint with `ON DELETE RESTRICT` AND an index `ix_projects_license_id`; (e) `datasets.license_id` FK constraint switches to `ON DELETE RESTRICT`; (f) `project_license_history.old_license` and `.new_license` are now `VARCHAR(50)`; (g) `alembic_version` advances to the new revision.
- [ ] T003 Write failing integration test for migration 0024 negative path (projects.license) in the same file as T002 — inject an unrecognized `projects.license` value before upgrade; assert `ValueError` (listing the offender) AND verify the schema is fully untouched (no new column, no FK changes, no type changes on history). Sequential after T002 (same file).
- [ ] T004 Write failing integration test for migration 0024 negative path (history columns) in the same file as T002 — inject an unrecognized `project_license_history.new_license` value before upgrade; assert `ValueError` (listing the offender from the history audit) AND schema untouched. Sequential after T003 (same file).
- [ ] T005 Write failing integration test for license history migration (R8 + FR-005a) in the same file as T002 — seed a row in `project_license_history` with `new_license='CC-BY'`, apply the migration, assert the row is preserved verbatim (`new_license` still reads `'CC-BY'` as VARCHAR string). Sequential after T004 (same file).
- [ ] T006 [P] Write failing unit test for migration's `downgrade()` in `apps/api/tests/unit/test_migration_0024.py` — assert `NotImplementedError` (spec/011 step 11 precedent). Parallel-safe with T002-T005 (different file).

### Implementation

- [ ] T007 Implement migration `apps/api/alembic/versions/0024_license_master_unification.py` with the 10-step sequence from data-model.md (audit FIRST → unique constraint → seed via short_name conflict → add column → UPDATE map → FK + index → drop legacy column → history columns ALTER → datasets FK swap → `downgrade()` raises). Use `_LICENSE_ID_FOR_ENUM` constant for the deterministic mapping; audit covers all three columns (`projects.license`, `history.old_license`, `history.new_license`).
- [ ] T008 [P] Update `apps/api/echoroo/models/project.py` `Project` class — remove the `license` enum column declaration, add `license_id: Mapped[str | None]` as FK to `licenses.id` with `ondelete="RESTRICT"`, expose a `license` association proxy or hybrid property that resolves to `License.short_name` for backward-compatible read access.
- [ ] T009 [P] Update `apps/api/echoroo/models/project.py` `ProjectLicenseHistory` class — re-declare `old_license: Mapped[str | None]` and `new_license: Mapped[str]` (no more `Enum(ProjectLicense, ...)`). Keep the relationship to `Project` intact.
- [ ] T010 [P] Update `apps/api/echoroo/models/dataset.py` — annotate the existing `license_id` FK as `ondelete="RESTRICT"` (model metadata only; the actual constraint replacement happens in the migration).
- [ ] T011 Run `docker exec echoroo-backend sh -c 'cd /app && uv run pytest --no-cov apps/api/tests/integration/migrations/test_0024_license_unification.py apps/api/tests/unit/test_migration_0024.py'` and confirm all five tests now pass.

**Checkpoint — Foundation ready**: Migration applies cleanly, model layer reflects the new shape, existing project rows and history rows have been transformed correctly. This already satisfies User Story 2 at the data layer; remaining US2 work is API-shape verification.

---

## Phase 3: User Story 1 — Admin-added licenses appear in project creation (Priority: P1) 🎯 MVP

**Goal**: Closes the user-reported gap. A license added through the admin UI appears in the project creation dropdown immediately (within the SC-001 5-second budget).

**Independent Test**: Per quickstart.md sections 2–5. Sign in as admin → add `CC-BY-ND` row → switch to a non-admin user tab → open `/projects/new` → `CC-BY-ND` appears in the dropdown → submitting creates a project whose `license` API field reports `"CC-BY-ND"`.

### Tests (write FIRST, must FAIL before implementation)

- [X] T012 [P] [US1] Contract test for `GET /web-api/v1/licenses` in `apps/api/tests/contract/test_licenses_web_public.py` — covers: 200 response shape matches `contracts/web-licenses.yaml`, items sorted by `short_name` ascending, empty `items: []` when master is empty, 401 when called without session, **and explicitly: a non-admin authenticated user (e.g. `e2e-member`) receives 200 with the full list (FR-017 — read endpoint MUST NOT require admin privileges)**.
- [X] T013 [P] [US1] Contract test for `GET /api/v1/licenses` in `apps/api/tests/contract/test_licenses_api_public.py` (separate file so T012 + T013 are truly parallel) — covers: 200 response shape matches `contracts/licenses.yaml`, 401 when called without Bearer, **and explicitly: a non-admin Bearer key (no admin scope) receives 200 (FR-017)**.
- [X] T014 [P] [US1] Unit test for `LicenseService.list_public()` in `apps/api/tests/unit/services/test_license_service.py` — covers: returns sorted list, empty master returns empty list.
- [X] T015 [P] [US1] Contract test for `POST /projects` `license_id` resolution in `apps/api/tests/contract/test_projects_create.py` (extend existing file) — covers: valid `license_id: "cc-by"` succeeds and project response reports `license: "CC-BY"`; unknown `license_id: "cc-by-nonsense"` returns 422 with `error_code: "license_not_found"`; missing `license_id` returns 422 (FR-005 — required at create); pre-existing project with `license_id IS NULL` (legacy row) still returns `license: null` on GET.

### Implementation — backend

- [X] T016 [P] [US1] Add `LicensePublicResponse` and `LicenseListResponse` Pydantic schemas in `apps/api/echoroo/schemas/license.py` matching `contracts/web-licenses.yaml`.
- [X] T017 [US1] Implement `LicenseService.list_public()` in `apps/api/echoroo/services/license_service.py` — delegates to `LicenseRepository.list_all()` ordered by `short_name`.
- [X] T018 [P] [US1] Add `GET /licenses` handler in `apps/api/echoroo/api/web_v1/licenses.py` (new file), returning `LicenseListResponse`. Register the router in the BFF aggregator.
- [X] T019 [P] [US1] Add `GET /licenses` handler in `apps/api/echoroo/api/v1/licenses.py` (new file), returning `LicenseListResponse`. Register the router in the v1 aggregator.
- [X] T020 [US1] Run the existing OpenAPI diff check (`apps/api/tests/contract/test_openapi_diff.py`) to confirm the new endpoints are documented and don't break the harness; regenerate the snapshot if expected.
- [ ] T021 [US1] Update `apps/api/echoroo/repositories/project.py` — `create()` / `update()` write via `license_id`; read paths join `licenses` and surface `License.short_name` as `project.license` in the response model.
- [ ] T022 [US1] Update `apps/api/echoroo/services/project_service.py` — on create/update, validate that the submitted `license_id` exists in the master before insert. Unknown id raises a `LicenseNotFoundError` that the API layer maps to 422 with `error_code: "license_not_found"`. License-required validation (FR-005) is enforced via Pydantic on `ProjectCreateRequest`.
- [ ] T023 [US1] Update `apps/api/echoroo/schemas/project.py` — `ProjectCreateRequest` and `ProjectUpdateRequest` replace `license: ProjectLicense` with `license_id: str`. `ProjectResponse.license` continues to expose `str | None` (the joined short_name). Add validator on `license_id` for max length 50.
- [ ] T024 [US1] Update `apps/api/echoroo/services/detection_export.py:381` — replace `project.license.value` with `project.license` (the joined short_name string from the new property). Update the contract test for the export to verify the wire shape is unchanged (still a license short_name in the CSV column).

### Implementation — frontend [PR-B]

- [ ] T025 [P] [US1] Add `apps/web/src/lib/api/licenses.ts` exposing a TanStack Query `useLicenses()` hook that calls `apiClient.request<LicenseListResponse>('/web-api/v1/licenses')` with `staleTime: 0` and `refetchOnMount: 'always'` (per research §R5 revised — SC-001 compliance).
- [ ] T026 [P] [US1] Add `License` and `LicenseListResponse` TypeScript interfaces in `apps/web/src/lib/types/index.ts` matching the backend Pydantic schema. **Also remove the legacy `ProjectLicense` union type** (`'CC0' | 'CC-BY' | 'CC-BY-NC' | 'CC-BY-SA'`); replace usages in `Project`, `ProjectCreateRequest`, `ProjectUpdateRequest` interfaces with `string` (display) and `license_id: string` (submit).
- [ ] T027 [US1] Update `apps/web/src/routes/(app)/projects/new/+page.svelte` — remove the hardcoded `LICENSE_OPTIONS` constant; replace the `<select>` population with the result of `useLicenses()`; the form's value carries `license.id` (not short_name); render visible option text as `{short_name}` with the full `{name}` as `title` tooltip.
- [ ] T028 [US1] Update the form submit handler to send `{ license_id }` to the backend (rename from `{ license }` and value semantics from short_name to id).
- [ ] T029 [P] [US1] Add an empty-state UI for when `useLicenses()` returns an empty array (per spec.md edge case: "No licenses available — ask an administrator to add one"). Use a translation key.
- [ ] T030 [P] [US1] Add translation keys to `apps/web/messages/en.json` and `apps/web/messages/ja.json` — `project_new_license_loading`, `project_new_license_empty`, `project_new_license_unknown_error`. Keep both locale files in lockstep.

### Verification

- [ ] T031 [US1] Run `docker exec echoroo-backend sh -c 'cd /app && uv run pytest --no-cov apps/api/tests/contract/test_licenses_web_public.py apps/api/tests/contract/test_licenses_api_public.py apps/api/tests/unit/services/test_license_service.py apps/api/tests/contract/test_projects_create.py'` and confirm all pass.
- [ ] T032 [US1] Run `docker exec echoroo-frontend sh -c 'cd /app && npm run check'` and confirm 0 new errors / warnings.
- [ ] T033 [US1] Browser smoke per quickstart.md sections 3–5 — capture before/after Network panel snapshots for the PR description.

**Checkpoint — US1 done**: SC-001 (admin add visible to users within 5 s), SC-005 (latency budget), and SC-006 (no hardcoded license strings) are satisfied.

---

## Phase 4: User Story 2 — Existing projects keep their license (Priority: P1) [PR-A]

**Goal**: Confirm zero existing projects lose their license through the migration. Most of the work is done by Phase 2; this phase is verification + a regression-resistant assertion.

**Independent Test**: Per quickstart.md section 1. Snapshot `SELECT id, license FROM projects` before migration, apply migration, snapshot the joined query, `diff` must show zero substantive changes.

### Tests (extend foundational test)

- [ ] T034 [P] [US2] Extend `apps/api/tests/integration/migrations/test_0024_license_unification.py` with a seeded-projects scenario: insert one project per canonical license value AND one project with `license IS NULL`, run the migration, assert every project still resolves to the same `short_name` (or NULL).
- [ ] T035 [P] [US2] Add API-shape regression test in `apps/api/tests/contract/test_projects_license_shape.py` — `GET /projects/{id}` for a project created with `license_id: "cc-by"` returns `license: "CC-BY"` (string, NOT an object). Pins research §R1 to the wire contract.

### Verification

- [ ] T036 [US2] Run the migration on the dev DB and follow quickstart.md section 1's diff-based verification. Save the before/after snapshots in the PR description.

**Checkpoint — US2 done**: SC-002 (zero existing projects lose license) and SC-003 (no orphan license references) are satisfied.

---

## Phase 5: User Story 3 — Licenses in use cannot be deleted accidentally (Priority: P2) [PR-A backend + PR-B UI]

**Goal**: Refuse license delete when referenced; surface dependency counts to the admin UI.

**Independent Test**: Per quickstart.md section 6.

### Tests (write FIRST, must FAIL before implementation)

- [X] T037 [US3] Contract test in `apps/api/tests/contract/test_admin_licenses_delete.py` (extend existing) — 204 success when no dependents (covers BOTH `/api/v1/admin/licenses/{id}` AND `/web-api/v1/admin/licenses/{id}`).
- [X] T038 [US3] Contract test in the same file as T037 — 409 `LicenseInUseError` with project-only dependency (`project_count > 0, dataset_count = 0`). Sequential after T037 (same file).
- [X] T039 [US3] Contract test in the same file as T037 — 409 `LicenseInUseError` with dataset-only dependency (`project_count = 0, dataset_count > 0`). Sequential after T038 (same file).
- [X] T040 [US3] Contract test in the same file as T037 — 409 `LicenseInUseError` with both dependencies. Sequential after T039 (same file).
- [X] T041 [US3] Contract test in the same file as T037 — 404 when `license_id` doesn't exist (preserves existing behavior). Sequential after T040 (same file).
- [X] T042 [US3] Race-condition unit test in `apps/api/tests/unit/services/test_license_service.py` — mock the FK constraint to fire after the service-layer pre-query returns 0/0. Assert that `LicenseService.delete()` catches the `IntegrityError`, re-runs the dependency-count query, and raises `LicenseInUseError` with the freshly-recounted values (no sentinel).
- [X] T043 [P] [US3] Unit test for `LicenseService.delete()` happy refusal path — `count_dependents > 0` raises `LicenseInUseError` without touching the row.

### Implementation — backend [PR-A]

- [X] T044 [P] [US3] Add `LicenseRepository.count_dependents(license_id) -> tuple[int, int]` in `apps/api/echoroo/repositories/license.py`, returning `(project_count, dataset_count)` via two `SELECT COUNT(*)` queries.
- [X] T045 [P] [US3] Add `LicenseInUseError` exception class in `apps/api/echoroo/services/license_service.py` with fields `short_name: str`, `project_count: int`, `dataset_count: int`.
- [X] T046 [US3] Update `LicenseService.delete()` to:
  1. Call `count_dependents` first; if either > 0, raise `LicenseInUseError`.
  2. Otherwise issue the DELETE; if the FK constraint raises `sqlalchemy.exc.IntegrityError`, **re-run `count_dependents`** to get the post-race counts and raise `LicenseInUseError` with those values. No sentinel.
- [X] T047 [US3] Update the admin DELETE handler at `apps/api/echoroo/api/v1/admin.py` (Bearer surface, NOT the non-existent `api/v1/admin/licenses.py`) to catch `LicenseInUseError` and return 409 with the body shape from `contracts/admin-licenses-delete.yaml`.
- [X] T048 [US3] Update the BFF admin DELETE handler at `apps/api/echoroo/api/web_v1/_admin_licenses.py` to do the same translation. Both endpoints share the response shape.

### Implementation — frontend [PR-B]

- [ ] T049 [P] [US3] Add error code translation messages to `apps/web/messages/en.json` and `apps/web/messages/ja.json` — `admin_licenses_delete_in_use` with `{short_name}`, `{project_count}`, `{dataset_count}` interpolation slots.
- [ ] T050 [US3] Update the admin license delete UI handler to extract the 409 body fields and render the translated message (file: `apps/web/src/routes/(admin)/admin/licenses/+page.svelte`, confirm path during implementation).

### Verification

- [ ] T051 [US3] Run `docker exec echoroo-backend sh -c 'cd /app && uv run pytest --no-cov apps/api/tests/contract/test_admin_licenses_delete.py apps/api/tests/unit/services/test_license_service.py'` and confirm all pass.
- [ ] T052 [US3] Browser smoke per quickstart.md section 6.

**Checkpoint — US3 done**: SC-004 (delete refused in 100% of in-use cases) is satisfied.

---

## Phase 6: Polish & Cross-Cutting Concerns

### Backend [PR-A]

- [ ] T053 [P] Run `docker exec echoroo-backend sh -c 'cd /app && uv run mypy echoroo/'` and confirm no new errors.
- [ ] T054 [P] Run `docker exec echoroo-backend sh -c 'cd /app && uv run ruff check echoroo/ tests/'` and fix any new lint warnings.
- [ ] T055 **SC-006 grep gate**: Run a repository-wide grep ensuring no hardcoded license short_name strings remain in user-facing surfaces:
      ```bash
      docker exec echoroo-backend sh -c 'cd /app && grep -rn --include="*.py" -E "\"CC0\"|\"CC-BY\"|\"CC-BY-NC\"|\"CC-BY-SA\"" echoroo/ tests/ | grep -v test_ | grep -v "migration\|migrations\|0024"'
      docker exec echoroo-frontend sh -c 'cd /app && grep -rn -E "\"CC0\"|\"CC-BY\"" src/ messages/ | grep -v test'
      ```
      Expected result: zero matches outside the migration file (`0024_license_master_unification.py`), the historical mapping table, and contract documents. Any leak in app code is a bug.
- [ ] T056 Run quickstart.md section 7 (the FR-010 negative-path test on a throwaway DB) and confirm the migration aborts cleanly with the expected ValueError.

### Frontend [PR-B]

- [ ] T057 [P] Run `docker exec echoroo-frontend sh -c 'cd /app && npm run check'` (final pass after Phase 5 changes).
- [ ] T058 [P] Regenerate frontend OpenAPI types if the project has a generation step (confirm via `apps/web/package.json` scripts) and commit the regenerated types.

### Cross-cutting

- [ ] T059 Run the full quickstart.md sections 1–7 end-to-end after both PRs are merged in dev; verify every "Expected" outcome.
- [ ] T060 [P] Update memory file `~/.claude/projects/-home-okamoto-Projects-echoroo/memory/` with `project_012_completion_<date>.md` summarizing the merge (mirror `project_011_completion_*.md`).
- [ ] T061 Open PR-A with title `feat(spec/012, PR-A): license master unification — migration + backend` referencing plan.md, this tasks.md, and the FRs/SCs satisfied. Open PR-B (`feat(spec/012, PR-B): license master unification — frontend`) once PR-A is in dev so reviewers can exercise the full UX.

---

## Dependencies & execution order

### Phase ordering

- **Phase 1 (Setup)** → no dependencies; do this first.
- **Phase 2 (Foundational migration)** → depends on Phase 1; BLOCKS all user-story phases.
- **Phase 3 (US1)** → depends on Phase 2. Backend half goes in PR-A; frontend half goes in PR-B (after PR-A merges).
- **Phase 4 (US2)** → depends on Phase 2; can run in parallel with Phase 3 (verification work, mostly independent).
- **Phase 5 (US3)** → depends on Phase 2; backend in PR-A, frontend in PR-B.
- **Phase 6 (Polish)** → depends on Phases 3–5 being complete.

### PR ordering

- **PR-A merges first** (Phase 1 + 2 + 3-backend + 4 + 5-backend + 6-backend).
- **PR-B merges second** (Phase 3-frontend + 5-frontend + 6-frontend). PR-B against an un-PR-A'd backend would 404 the new endpoint and 422 on form submit.

### Story independence

- **US1** depends only on the migration (Phase 2) — read endpoint + frontend wiring is otherwise self-contained.
- **US2** depends only on the migration — verification work, no production code changes beyond what Phase 2 lands.
- **US3** depends only on the migration — service-layer change is additive.

### Within each phase

- Test tasks ALWAYS precede their corresponding implementation tasks. Run the test, observe failure, then implement.
- Repository tasks before service tasks. Service tasks before endpoint tasks. Endpoint tasks before frontend tasks.
- Schemas / types can run in parallel with their nearest non-conflicting siblings.

### Parallel safety review (Codex review fix, re-verified by analyze)

All `[P]` markers in this revised tasks.md were verified to touch **distinct files**. Tasks that share a file are explicitly sequential (no `[P]` marker), with a note pointing at the file lock predecessor:

- **Phase 2 tests** — T002, T003, T004, T005 all extend the same file (`test_0024_license_unification.py`); the body of each task explicitly says "in the same file as T002" and "Sequential after T_n_". `[P]` removed from T003/T004/T005. T006 has `[P]` because it targets a different file (`test_migration_0024.py`).
- **Phase 2 implementation** — T008, T009, T010 each touch different model classes / files; safe with `[P]`. T008 and T009 both edit `models/project.py` but different classes (`Project` vs `ProjectLicenseHistory`) — merge-conflict risk is documented and accepted.
- **Phase 3 contract / unit tests** — T012, T013, T014, T015 each in a different file; `[P]` safe.
- **Phase 3 endpoint handlers** — T018, T019 different files; `[P]` safe.
- **Phase 3 frontend** — T025, T026, T029, T030 different files; `[P]` safe.
- **Phase 5 contract tests** — T037, T038, T039, T040, T041 all in the same file (`test_admin_licenses_delete.py`). `[P]` removed from T038-T041; each task body says "in the same file as T037" and "Sequential after T_n_".
- **Phase 5 implementation** — T044, T045 touch different files; `[P]` safe.
- **Phase 6 verification commands** — T053, T054, T057, T058 are read-only against different parts of the tree; `[P]` safe.

### Parallel opportunities (after the corrections)

- Phase 3 contract / unit tests T012-T015 are all [P] — different test files.
- Phase 3 endpoint handlers T018 / T019 are [P] — different router files (both depend on T017 service).
- Phase 3 frontend T025 / T026 / T029 / T030 are [P].
- Phase 5 repo+exception T044 / T045 are [P].
- Phase 6 verification commands T053 / T054 / T057 / T058 are [P].

---

## Implementation strategy

### MVP-first (stop after US1 if needed)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational migration.
3. Complete Phase 3 backend half + frontend half: US1.
4. **STOP AND VALIDATE** per quickstart.md sections 1–5.
5. Decide: ship PR-A + PR-B as MVP, defer US2 / US3 verification to a follow-up. (Not recommended — US2 verification only adds two tests; US3 is a launch-grade safety property that should land with the migration.)

### Standard delivery (2-PR split, revised)

1. PR-A: Phase 1 + 2 + 3-backend + 4 + 5-backend + 6-backend. Lands first, exposed in dev for backend smoke.
2. PR-B: Phase 3-frontend + 5-frontend + 6-frontend. Lands after PR-A green in dev.

---

## Notes

- Memory rule reminders:
  - `docker exec echoroo-backend ... uv run pytest --no-cov ...` for backend tests.
  - Frontend Vite HMR via preview stack (preview frontend bind-mounts `/home/okamoto/Projects/echoroo_preview/apps/web`).
  - Forbidden: `docker commit / save / export`.
  - Forbidden: `git checkout / reset --hard / restore / clean -f` from agents.
- Verify-before-PR: quickstart.md section 7 (FR-010 negative test on throwaway DB) is mandatory before opening PR-A.
- After both PRs merge, run `/speckit-analyze` or equivalent to confirm the spec ↔ implementation traceability matrix is intact.
