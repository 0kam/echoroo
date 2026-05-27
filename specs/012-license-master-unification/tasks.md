---
description: "Tasks for License Master Unification (spec/012)"
---

# Tasks: License Master Unification

**Input**: Design documents from `specs/012-license-master-unification/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md (all present)

## Delivery shape

This feature is **a single implementation PR** — the user (`spec/012` author) explicitly directed against multi-PR splitting because the surface is small: one migration, one new read-endpoint pair, one admin endpoint behavior tightening, one frontend page change, plus tests and translations.

Phases below are still organized as MVP-first checkpoints so the implementer can pause and validate after Phase 3 (US1, the headline outcome), but everything ships in one PR rather than three.

## Tests are REQUIRED

Per the Echoroo constitution principle II (Test-Driven Development is NON-NEGOTIABLE), every implementation task in this list has a preceding test task. The test MUST be written first and MUST fail before the corresponding implementation task is started.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: task touches files not shared with the immediately prior task and has no incomplete dependency in the same phase
- **[Story]**: which user story the task delivers — US1, US2, US3 (Setup / Foundational / Polish have no Story label)
- File paths are absolute under the repository root (`apps/api/...` or `apps/web/...`)

## Path conventions

- Backend: `apps/api/echoroo/...` + `apps/api/tests/...`
- Frontend: `apps/web/src/...`
- Migrations: `apps/api/alembic/versions/`

---

## Phase 1: Setup

**Purpose**: One-off checks before writing tests or code.

- [ ] T001 Confirm the next free Alembic revision number. Check `apps/api/alembic/versions/` for current HEAD (`0023` after PR #116 merges; rebase later if other migrations land first). Update the migration filename and `down_revision` accordingly before writing T002+.

---

## Phase 2: Foundational — Migration (Blocking Prerequisites)

**Purpose**: Schema change is a hard prerequisite for every user story. Both the destructive migration and the model annotations land here so that subsequent test fixtures and runtime code can rely on the new shape.

**⚠️ CRITICAL**: No user-story work can begin until Phase 2 is green.

### Tests (write FIRST, must FAIL before implementation)

- [ ] T002 [P] Write failing integration test for migration 0024 happy path in `apps/api/tests/integration/migrations/test_0024_license_unification.py` — mirror the testcontainers pattern from `test_0022_email_subsystem_removal.py`. Assert: (a) seed inserts the four canonical license rows, (b) every pre-existing `projects.license` enum value maps deterministically to the new `license_id` column, (c) `projects.license` column is dropped, (d) FK constraints on both `projects.license_id` and `datasets.license_id` are `ON DELETE RESTRICT`, (e) `alembic_version` advances to the new revision.
- [ ] T003 [P] Write failing integration test for migration 0024 negative path in `apps/api/tests/integration/migrations/test_0024_license_unification.py` — inject an unrecognized `projects.license` value before upgrade; assert `ValueError` (listing the offender) and verify the schema is fully rolled back (no new column, no new FK, no dropped column).
- [ ] T004 [P] Write failing unit test for migration's `downgrade()` in `apps/api/tests/unit/test_migration_0024.py` — assert `NotImplementedError` (spec/011 step 11 precedent).

### Implementation

- [ ] T005 Implement migration `apps/api/alembic/versions/0024_license_master_unification.py` with the 9-step sequence from data-model.md (unique constraint → seed → add column → audit → UPDATE map → FK ON DELETE RESTRICT → drop legacy column → replace datasets FK → `downgrade()` raises). Use `_LICENSE_ID_FOR_ENUM` constant for the deterministic mapping.
- [ ] T006 [P] Update `apps/api/echoroo/models/project.py` — remove the `license` enum column declaration, add `license_id: Mapped[str | None]` as FK to `licenses.id`, expose a `license` association proxy or property that resolves to `License.short_name` for backward-compatible read access.
- [ ] T007 [P] Update `apps/api/echoroo/models/dataset.py` — annotate the existing `license_id` FK as `ondelete="RESTRICT"` (model metadata only; the actual constraint replacement happens in the migration).
- [ ] T008 Run `docker exec echoroo-backend sh -c 'cd /app && uv run pytest --no-cov apps/api/tests/integration/migrations/test_0024_license_unification.py apps/api/tests/unit/test_migration_0024.py'` and confirm all three tests now pass.

**Checkpoint — Foundation ready**: Migration applies cleanly, model layer reflects the new shape, existing project rows have been transformed to the FK representation. This already satisfies User Story 2 at the data layer; remaining US2 work is API-shape verification only.

---

## Phase 3: User Story 1 — Admin-added licenses appear in project creation (Priority: P1) 🎯 MVP

**Goal**: Closes the user-reported gap. A license added through the admin UI appears in the project creation dropdown immediately, without code change or service restart.

**Independent Test**: Per quickstart.md sections 2–5. Sign in as admin → add `CC-BY-ND` row → switch to a non-admin user tab → open `/projects/new` → `CC-BY-ND` appears in the dropdown → submitting creates a project whose `license` API field reports `"CC-BY-ND"`.

### Tests (write FIRST, must FAIL before implementation)

- [ ] T009 [P] [US1] Contract test for `GET /web-api/v1/licenses` in `apps/api/tests/contract/test_licenses_public.py` — covers: 200 response shape matches `contracts/web-licenses.yaml`, items sorted by `short_name` ascending, empty `items: []` when master is empty, 401 when called without session.
- [ ] T010 [P] [US1] Contract test for `GET /api/v1/licenses` in `apps/api/tests/contract/test_licenses_public.py` — covers: 200 response shape matches `contracts/licenses.yaml`, 401 when called without Bearer.
- [ ] T011 [P] [US1] Unit test for `LicenseService.list_public()` in `apps/api/tests/unit/services/test_license_service.py` — covers: returns sorted list, empty master returns empty list.
- [ ] T012 [P] [US1] Contract test for `POST /projects` license resolution in `apps/api/tests/contract/test_projects_create.py` (extend existing file) — covers: valid `license: "CC-BY"` resolves to `license_id="cc-by"` and project response reports `license: "CC-BY"`; unknown `license: "CC-BY-NONSENSE"` returns 422 with a friendly error message; omitted `license` succeeds and project response reports `license: null`.

### Implementation — backend

- [ ] T013 [P] [US1] Add `LicensePublicResponse` and `LicenseListResponse` Pydantic schemas in `apps/api/echoroo/schemas/license.py` matching the OpenAPI contract.
- [ ] T014 [US1] Implement `LicenseService.list_public()` in `apps/api/echoroo/services/license_service.py` — delegates to `LicenseRepository.list_all()` ordered by `short_name`.
- [ ] T015 [P] [US1] Add `GET /licenses` handler in `apps/api/echoroo/api/web_v1/licenses.py` (new file), returning `LicenseListResponse`.
- [ ] T016 [P] [US1] Add `GET /licenses` handler in `apps/api/echoroo/api/v1/licenses.py` (new file), returning `LicenseListResponse`.
- [ ] T017 [US1] Register both new routers in `apps/api/echoroo/main.py` (or wherever the existing license routers are included). Run the existing OpenAPI diff check (`apps/api/tests/contract/test_openapi_diff.py`) to confirm the new endpoints are documented.
- [ ] T018 [P] [US1] Update `apps/api/echoroo/repositories/project.py` — `create()`, `update()`, and read paths write/read via `license_id`. Read paths join `licenses` and surface `License.short_name` as `project.license` in the response model.
- [ ] T019 [US1] Update `apps/api/echoroo/services/project_service.py` — on create/update, resolve incoming `license: str | None` (a short_name) to `license_id` by looking up the master. Unknown short_name raises a `ValueError` that the API layer maps to 422 with `error_code: "license_not_found"` + the offending short_name in the message.
- [ ] T020 [US1] Update `apps/api/echoroo/schemas/project.py` — keep `license: str | None` in both `ProjectCreate` (short_name) and `ProjectResponse` (joined short_name). Add validator on `ProjectCreate.license` for max length 50 to match `licenses.short_name`.

### Implementation — frontend

- [ ] T021 [P] [US1] Add `apps/web/src/lib/api/licenses.ts` exposing a TanStack Query `useLicenses()` hook that calls `apiClient.request<LicenseListResponse>('/web-api/v1/licenses')` with `staleTime: 30000` (30 s, per research §R5).
- [ ] T022 [P] [US1] Add `License` and `LicenseListResponse` TypeScript interfaces in `apps/web/src/lib/types/index.ts` (or the appropriate types file) matching the backend Pydantic schema.
- [ ] T023 [US1] Update `apps/web/src/routes/(app)/projects/new/+page.svelte` — remove the hardcoded `LICENSE_OPTIONS` constant; replace the `<select>` population with the result of `useLicenses()`; preserve the existing "unselected" empty-option semantics; render the dropdown options as `{short_name}` (primary) with the full `{name}` as `title` tooltip.
- [ ] T024 [P] [US1] Add an empty-state UI for when `useLicenses()` returns an empty array (per edge case in spec.md: "No licenses available — ask an administrator to add one"). Use a translation key.
- [ ] T025 [P] [US1] Add translation keys to `apps/web/messages/en.json` and `apps/web/messages/ja.json` — `project_new_license_loading`, `project_new_license_empty`, `project_new_license_unknown_error`. Make sure both locale files stay in sync.

### Verification

- [ ] T026 [US1] Run `docker exec echoroo-backend sh -c 'cd /app && uv run pytest --no-cov apps/api/tests/contract/test_licenses_public.py apps/api/tests/unit/services/test_license_service.py apps/api/tests/contract/test_projects_create.py'` and confirm all tests pass.
- [ ] T027 [US1] Run `docker exec echoroo-frontend sh -c 'cd /app && npm run check'` and confirm 0 new errors / warnings.
- [ ] T028 [US1] Browser smoke per quickstart.md sections 3–5 (read endpoints serve master → form shows live master → admin add reaches the form). Capture before/after Network panel snapshots for the PR description.

**Checkpoint — US1 done**: SC-001 (admin add visible to users within 5 s), SC-005 (latency budget), and SC-006 (no hardcoded license strings) are satisfied.

---

## Phase 4: User Story 2 — Existing projects keep their license (Priority: P1)

**Goal**: Confirm zero existing projects lose their license through the migration. Most of the work is already done by Phase 2's migration; this phase is verification + a regression-resistant assertion.

**Independent Test**: Per quickstart.md section 1. Snapshot `SELECT id, license FROM projects` before migration, apply migration, snapshot `SELECT p.id, l.short_name AS license FROM projects p LEFT JOIN licenses l ON l.id = p.license_id`, `diff` must show zero substantive changes.

### Tests (extend foundational test)

- [ ] T029 [P] [US2] Extend `apps/api/tests/integration/migrations/test_0024_license_unification.py` with a seeded-projects scenario: insert one project per canonical license value into the pre-migration DB, run the migration, assert every project still resolves to the same `short_name` via the join.
- [ ] T030 [P] [US2] Add API-shape regression test in `apps/api/tests/contract/test_projects_create.py` (or a new `test_projects_license_shape.py`) — `GET /projects/{id}` for a project created with `license: "CC-BY"` returns `license: "CC-BY"` (string, NOT an object). Pins research §R1 to a wire contract.

### Verification

- [ ] T031 [US2] Run the migration on the dev DB (`docker exec echoroo-backend uv run alembic upgrade head`) and follow quickstart.md section 1's diff-based verification. Save the before/after snapshots in the PR description.

**Checkpoint — US2 done**: SC-002 (zero existing projects lose license) and SC-003 (no project references a non-existent license) are satisfied.

---

## Phase 5: User Story 3 — Licenses in use cannot be deleted accidentally (Priority: P2)

**Goal**: Refuse `DELETE /api/v1/admin/licenses/{id}` when the license is still referenced; surface dependency counts to the admin UI for an actionable error.

**Independent Test**: Per quickstart.md section 6. With at least one project referencing `CC-BY-ND`, `DELETE /api/v1/admin/licenses/cc-by-nd` returns 409 + JSON `{error_code: "license_in_use", short_name, project_count, dataset_count, message}`; the license remains visible in admin + dropdown afterwards.

### Tests (write FIRST, must FAIL before implementation)

- [ ] T032 [P] [US3] Contract test in `apps/api/tests/contract/test_admin_licenses_delete.py` (extend existing file or create new) — 204 success when no dependents.
- [ ] T033 [P] [US3] Contract test — 409 `LicenseInUseError` with project-only dependency (`project_count > 0, dataset_count = 0`).
- [ ] T034 [P] [US3] Contract test — 409 `LicenseInUseError` with dataset-only dependency (`project_count = 0, dataset_count > 0`).
- [ ] T035 [P] [US3] Contract test — 409 `LicenseInUseError` with both dependencies (`project_count > 0, dataset_count > 0`).
- [ ] T036 [P] [US3] Contract test — 404 when `license_id` doesn't exist (preserves existing behavior).
- [ ] T037 [P] [US3] Unit test in `apps/api/tests/unit/services/test_license_service.py` for `LicenseService.delete()` — verifies the service raises `LicenseInUseError` when `count_dependents > 0` without touching the row.
- [ ] T038 [P] [US3] Concurrency-safety unit test — mock the FK constraint to fire after the service-layer pre-query (race scenario); assert the FK `IntegrityError` is mapped to the same 409 response (defense-in-depth per research §R3).

### Implementation

- [ ] T039 [P] [US3] Add `LicenseRepository.count_dependents(license_id) -> tuple[int, int]` in `apps/api/echoroo/repositories/license.py`, returning `(project_count, dataset_count)` via two `SELECT COUNT(*)` queries (low volume; either fine vs UNION ALL).
- [ ] T040 [P] [US3] Add `LicenseInUseError` exception class in `apps/api/echoroo/services/license_service.py` (or `core/errors.py` if the project has a central errors module) with `short_name`, `project_count`, `dataset_count` fields.
- [ ] T041 [US3] Update `LicenseService.delete()` in `apps/api/echoroo/services/license_service.py` to call `count_dependents` first; if either count > 0, raise `LicenseInUseError`. Catch `sqlalchemy.exc.IntegrityError` as the race-condition fallback and translate to `LicenseInUseError` with `project_count=-1, dataset_count=-1` sentinel (UI shows generic "in use" message).
- [ ] T042 [US3] Update the admin `DELETE /api/v1/admin/licenses/{id}` handler in `apps/api/echoroo/api/v1/admin/licenses.py` to catch `LicenseInUseError` and return 409 with the body shape from `contracts/admin-licenses-delete.yaml`.
- [ ] T043 [P] [US3] Add error code translation messages to `apps/web/messages/en.json` and `apps/web/messages/ja.json` — `admin_licenses_delete_in_use` with `{short_name}`, `{project_count}`, `{dataset_count}` interpolation slots.
- [ ] T044 [US3] Update the admin license delete UI handler to extract the 409 body fields and render the translated message (file: existing admin license page, likely `apps/web/src/routes/(admin)/admin/licenses/+page.svelte` — confirm path).

### Verification

- [ ] T045 [US3] Run `docker exec echoroo-backend sh -c 'cd /app && uv run pytest --no-cov apps/api/tests/contract/test_admin_licenses_delete.py apps/api/tests/unit/services/test_license_service.py'` and confirm all pass.
- [ ] T046 [US3] Browser smoke per quickstart.md section 6.

**Checkpoint — US3 done**: SC-004 (delete refused in 100% of in-use cases) is satisfied.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T047 [P] Run `docker exec echoroo-backend sh -c 'cd /app && uv run mypy echoroo/'` (or whatever the project's mypy invocation is) and confirm no new errors. Memory: known false positives in legacy modules are allowed; only NEW errors block the PR.
- [ ] T048 [P] Run `docker exec echoroo-frontend sh -c 'cd /app && npm run check'` (final pass after Phase 5 changes).
- [ ] T049 [P] Run `docker exec echoroo-backend sh -c 'cd /app && uv run ruff check echoroo/ tests/'` and fix any new lint warnings.
- [ ] T050 [P] Regenerate frontend OpenAPI types (if the project has a generation step — confirm in `apps/web/package.json` scripts) and commit the regenerated types.
- [ ] T051 Run the full quickstart.md sections 1–7 (including the negative test in section 7 against a throwaway DB) and verify every "Expected" outcome passes. Add a "Smoke verified" line to the PR description listing the section outcomes.
- [ ] T052 [P] Update memory file `~/.claude/projects/-home-okamoto-Projects-echoroo/memory/` with a new `project_012_completion_<date>.md` summarizing the merge (mirror the pattern of existing `project_011_completion_*.md`).
- [ ] T053 Open the PR (single PR per delivery shape) with title `feat(spec/012): license master unification (migration + endpoints + admin delete protection + frontend)` and the description should reference plan.md, list the FRs / SCs satisfied, and link this tasks.md.

---

## Dependencies & execution order

### Phase ordering

- **Phase 1 (Setup)** → no dependencies; do this first.
- **Phase 2 (Foundational migration)** → depends on Phase 1; BLOCKS all user-story phases.
- **Phase 3 (US1)** → depends on Phase 2 complete (model + migration must be in place).
- **Phase 4 (US2)** → depends on Phase 2; can run in parallel with Phase 3 (verification work is mostly independent).
- **Phase 5 (US3)** → depends on Phase 2; can run in parallel with Phases 3 / 4.
- **Phase 6 (Polish)** → depends on Phases 3-5 being complete.

### Story independence

- **US1** depends only on the migration (Phase 2) — read endpoint + frontend wiring is otherwise self-contained.
- **US2** depends only on the migration (Phase 2) — verification work, no production code changes beyond what Phase 2 already lands.
- **US3** depends only on the migration (Phase 2) — the new FK constraint is the foundation; service-layer change is additive.

### Within each phase

- Test tasks ALWAYS precede their corresponding implementation tasks. Run the test, observe failure, then implement.
- Repository tasks before service tasks. Service tasks before endpoint tasks. Endpoint tasks before frontend tasks.
- Schemas and types can run in parallel with their nearest non-conflicting siblings.

### Parallel opportunities

- Phase 2 tests T002 / T003 / T004 are all [P] — different test files.
- Phase 2 model annotations T006 / T007 are [P] — different model files.
- Phase 3 contract / unit tests T009-T012 are all [P] — different test files.
- Phase 3 endpoint handlers T015 / T016 are [P] — different router files (both depend on T014's service).
- Phase 3 frontend T021 / T022 are [P], T024 / T025 are [P].
- Phase 4 tests T029 / T030 are [P].
- Phase 5 contract tests T032-T036 are [P], unit tests T037 / T038 are [P], repo+exception T039 / T040 are [P].
- Phase 6 verification commands T047 / T048 / T049 / T050 are [P] (they read different things; no shared write).

---

## Parallel example — Phase 3 entry

After Phase 2 completes, US1 work can fan out:

```text
# All Phase-3 tests can be drafted in parallel:
- T009 Contract test GET /web-api/v1/licenses
- T010 Contract test GET /api/v1/licenses
- T011 Unit test LicenseService.list_public()
- T012 Contract test POST /projects license resolution

# After T013 (schemas), endpoint handlers can run in parallel:
- T015 GET /web-api/v1/licenses handler
- T016 GET /api/v1/licenses handler

# Frontend types and API client can run in parallel with backend implementation:
- T021 useLicenses() hook
- T022 License TS interface
```

---

## Implementation strategy

### MVP-first (stop after US1 if needed)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational migration
3. Complete Phase 3: US1 (the headline outcome)
4. **STOP AND VALIDATE** per quickstart.md sections 1–5
5. Decide: ship the MVP PR now, or keep going to US2 + US3 in the same PR

For spec/012 the user has directed a single-PR delivery, so MVP-first is a checkpoint, not a release boundary.

### Single-PR delivery (the convention for this feature)

1. Phase 1 + Phase 2 land first as scaffolding commits.
2. Phase 3, 4, 5 land as cohesive commits within the same PR.
3. Phase 6 polish lands as the final commit before opening the PR for review.
4. PR title and description reference plan.md and this tasks.md; PR body lists the FRs and SCs satisfied per quickstart.md.

---

## Notes

- The user (`spec/012` author) explicitly opted for a single implementation PR — do not split into 3 PRs even though the user-story structure could permit it.
- Memory rule reminders the implementer should observe while executing this list:
  - `docker exec echoroo-backend ... uv run pytest --no-cov ...` for backend tests (host `uv run` is broken in this repo).
  - Frontend Vite HMR can be exercised via the preview stack (`docker logs echoroo-preview-frontend`).
  - Forbidden: `docker commit / save / export` (host disk fill incident).
  - Forbidden: `git checkout / reset --hard / restore / clean -f` from agents on the main worktree (use the laughing-stonebraker-c612bf worktree).
- Verify-before-PR is mandatory: quickstart.md section 7 (negative-path migration test) MUST be exercised on a throwaway DB before opening the PR.
