# Research: License Master Unification

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-05-26

This document records the design decisions taken during Phase 0 of `/speckit-plan`,
along with the rationale and alternatives considered for each one. The plan and
data-model documents reference these decisions; the contracts and quickstart
artifacts assume them as ground truth.

---

## R1. API shape: response stays a short_name string; **submit moves to license_id**

**Decision (revised after Codex review)**: Keep the `license` field in project API **responses** as the existing **short-name string** (e.g. `"CC-BY"`) — backward compatibility for read paths. The **request** body for `POST /projects` and `PATCH /projects/{id}` changes to accept a stable identifier (`license_id: str`, the `licenses.id` value) **rather than the short_name**, so that admin renames between dropdown render and form submit do not invalidate in-flight requests (FR-004 stable-identifier guarantee).

The transitional accept-either compromise (read `short_name` from request, look it up at insert time) was REJECTED on Codex re-review: it does not actually satisfy FR-004 because an admin renaming `"CC-BY"` to `"CC-BY 4.0"` between the dropdown render and the user clicking submit would cause the submit to 422 with `license_not_found`, even though the underlying license row is unchanged.

**Rationale**:
- The user's expectation, framed in the spec, is "the inverse of intuitive ordering — admin master should drive the form" — not "introduce a richer license object everywhere." Tightening the contract to push a `{id, short_name, name, url}` object onto every project response would force coordinated frontend + downstream consumer updates with no offsetting benefit for this feature.
- Constitution principle V (API Versioning) requires backward compatibility within a major version. Changing `project.license` from `"CC-BY"` (string) to `{ "id": "cc-by", "short_name": "CC-BY", ... }` (object) is a breaking change and would force `v2`.
- The license short_name is FR-004's "stable identifier that survives renaming" only insofar as the master treats `id` as the stable key. In responses we still need the human-readable name; `short_name` is the closest match to today's enum string. The Project model resolves the FK on read and emits `short_name`.

**Alternatives considered**:
- *Expand to a full license object on every project response*: Cleaner data model, but breaking and out of scope. Possible as a follow-up under `project.license_details` (optional, additive) if the UI needs more info.
- *Expose `license_id` directly in the API*: Cluttered for clients that only render a label; ids are opaque to most callers. Rejected.

**Impact on plan**:
- `schemas/project.py` `ProjectResponse.license`: still a `str | None`, but its source switches from the enum column to a join-and-pluck on `licenses.short_name`. Populated by the repository / service layer reading the joined value.
- `schemas/project.py` `ProjectCreateRequest` / `ProjectUpdateRequest`: replace `license: ProjectLicense` with `license_id: str` (FK identifier). Backend validates the id exists in the master before insert/update; an unknown id yields 422 with `error_code: "license_not_found"`. The legacy `license` request field is dropped entirely (spec/006 contract requires `license` at create time but the wire field is renamed to `license_id` since the *semantics* — required, references master — are unchanged; spec/006 contract is regenerated accordingly).
- Frontend: dropdown `<option value="…">` carries `license.id`, the visible text is `license.short_name` (with `name` as `title` tooltip). The form's `license_id` state is submitted verbatim.
- `services/detection_export.py:381-383` switches from `project.license.value` to `project.license` (the joined short_name string). CSV column wire shape unchanged (still a license short_name string).
- `models/project.py::ProjectLicenseHistory`: see R8 below (history snapshot columns are converted to VARCHAR(50), no FK to licenses).

---

## R2. Public-read endpoint location

**Decision**: Register the read endpoint under both routers:
- `GET /web-api/v1/licenses` — cookie-session, used by the project creation form
- `GET /api/v1/licenses` — Bearer, used by any future programmatic caller (e.g. CLI tools, integrations)

Both return the same response shape and read from the same service layer. No write counterparts are added under either router; admin write CRUD stays at `/api/v1/admin/licenses` (existing, unchanged).

**Rationale**:
- The project creation form runs in the browser and uses the BFF cookie session via the existing `apiClient` (see today's fix in PR #119 for the analogous superusers issue). It MUST call a `/web-api/v1` endpoint.
- Adding the parallel `/api/v1` variant costs essentially nothing — both routers share the service layer — and keeps the auth router's path classification clean: any future "programmatic license list" need (e.g. a CI script seeding test data, an external integration querying available licenses) has a well-known endpoint to call.
- Both endpoints are GET-only, read-only, and idempotent. Rate-limiting and CSRF are inherited from the existing middleware chain.

**Alternatives considered**:
- *Only add `/web-api/v1/licenses`*: Sufficient for this spec, but pessimistically blocks programmatic callers behind an admin endpoint they shouldn't need. Rejected.
- *Reuse the admin endpoint with a permission relaxation*: Mixing "anyone authenticated can list" with "only admins can write" in one router is the typical source of permission gate bugs (see spec/007 history in memory). Rejected.

**Impact on plan**:
- Two new files: `apps/api/echoroo/api/v1/licenses.py` and `apps/api/echoroo/api/web_v1/licenses.py`. Both delegate to `services/license_service.py::list_public()` which returns a list ordered by `short_name`.

---

## R3. Delete-protection mechanism

**Decision**: PostgreSQL `FOREIGN KEY ... ON DELETE RESTRICT` on both `projects.license_id` and `datasets.license_id`. Service layer (`license_service.delete()`) additionally pre-computes the dependency counts and returns 409 Conflict with an actionable error body before the FK constraint would have raised an `IntegrityError`.

**Rationale**:
- The defense-in-depth pattern: the FK gives a hard guarantee at the DB layer (the only level at which referential integrity can be enforced under concurrent writes); the service-layer check exists purely to surface a friendly error message (count of dependents, identifying short_name, suggested next steps) before the IntegrityError fires.
- FR-015 requires the admin UI error to name (a) the license, (b) the project dependency count, (c) the dataset dependency count, (d) a concrete next step. A bare `IntegrityError` from a FK constraint does not give us those fields; the service layer's pre-query does.
- ON DELETE RESTRICT (rather than NO ACTION) makes the constraint check happen at statement time rather than transaction-commit time, so the service-layer check and the FK behavior are aligned.

**Alternatives considered**:
- *Service-layer check only, no FK*: Race condition window between the count query and the DELETE statement allows orphaned references under concurrent inserts. Rejected.
- *Soft delete (set a `deleted_at` column on licenses)*: Adds complexity (admin UI needs to hide soft-deleted rows, project creation needs to exclude them, etc.) for no benefit at our scale. Rejected per A-003 in the spec.
- *Cascade delete (set project.license_id to NULL on license delete)*: Silently strips license attribution from existing projects — explicitly rejected by the spec's "no silent orphan" rule (FR-006).

**Impact on plan**:
- Migration adds FK constraint with ON DELETE RESTRICT for `projects.license_id`.
- Migration drops and re-adds the existing `datasets.license_id` FK constraint with ON DELETE RESTRICT (was SET NULL).
- `repositories/license.py` gains `count_dependents(license_id) -> tuple[int, int]` returning `(project_count, dataset_count)`. Single query using `UNION ALL` or two `SELECT COUNT(*)` (low-volume; either fine).
- `services/license_service.py::delete()` calls `count_dependents` first; if either count > 0, raises a `LicenseInUseError` that the API layer maps to 409 Conflict.

---

## R4. Migration safety against unrecognized enum values

**Decision**: The migration runs the **audit SELECT** as **step 1, before any schema or seed change**: `SELECT DISTINCT license FROM projects WHERE license IS NOT NULL AND license NOT IN ('CC0','CC-BY','CC-BY-NC','CC-BY-SA')` (plus the analogous query on `project_license_history.old_license` and `new_license` after R8). If either result is non-empty, raise `ValueError` listing the offending values. Postgres rolls the entire transaction back; no schema changes, no seed inserts, no constraint mutations are committed. The operator must clean up offending rows (or extend the migration's mapping table) before re-running.

Doing this as step 1 means the safety belt fires on the earliest cheap signal — well before we touch the schema. This also makes the test fixture's "negative path" assertion stable: after a ValueError, the schema is verifiably untouched (no new column, no unique constraint, no FK changes).

**Rationale**:
- FR-010 explicitly forbids silent mapping or dropping. An abort with a clear error message gives the operator the information they need to act.
- Doing this check inside the migration (rather than in a pre-migration script) means the safety belt is automatically applied wherever the migration runs — local dev, preview, CI, production — without depending on operator discipline.
- The four canonical enum values match the existing `ProjectLicense` enum in code and the four hardcoded values in the frontend constant. We have high confidence (per A-001) that production / preview snapshots contain only those four values, but the safety belt is cheap insurance for an irreversible migration.

**Alternatives considered**:
- *Skip the check, rely on A-001*: Defensible but risky; we have non-zero history of test/preview environments accumulating debug values that don't exist in the canonical enum. Rejected.
- *Map unknown values to a synthetic "Unknown" seed row*: Hides the issue from the operator instead of surfacing it, contradicting FR-010. Rejected.
- *Move the check to a pre-migration sanity script (separate from the Alembic revision)*: Splits the safety belt from the action it protects; operator could skip the script. Rejected.

**Impact on plan**:
- Migration `upgrade()` first block: the audit SELECT. Failure mode: raise ValueError, transaction rolls back.
- Test plan: `test_0024_license_unification.py` includes a positive case (only canonical values, migration succeeds) and a negative case (insert an unrecognized value, expect ValueError + no schema changes committed).

---

## R5. Caching strategy

**Decision (revised after Codex review)**: **No caching layer** on launch. The frontend uses TanStack Query with `staleTime: 0` and `refetchOnMount: 'always'` so every time the `/projects/new` form mounts, a fresh fetch fires (admin updates land within the SC-001 "5 second" budget without any cache-invalidation choreography). In-flight deduplication still works (concurrent mounts share one network call), so this is not a "no caching at all" stance — just no *stale* caching.

The original 30-second `staleTime` would have violated SC-001 in a common scenario: admin opens admin tab → adds license → switches to user tab that already had the form open within the last 30s → user sees the stale dropdown. Cutting staleTime to zero closes that gap.

**Rationale**:
- Per A-004 in the spec, project creation traffic is low (pre-launch) and license master is a small table (~4–10 rows). A single indexed `SELECT * FROM licenses ORDER BY short_name` is ~1 ms inside the DB; the network roundtrip dominates and is well within the 200 ms p95 budget (SC-005).
- Adding caching now creates two problems: (1) admin write actions must invalidate the cache, which is a bug surface; (2) cache-related complexity that won't pay back at launch volumes. If profiling post-launch shows the read endpoint is a bottleneck, caching is a follow-up.

**Alternatives considered**:
- *Backend in-memory cache with TTL*: Tempting but premature. Rejected.
- *HTTP `Cache-Control: max-age=...` headers*: Lets browsers cache for free, but admin updates wouldn't invalidate in users' tabs until the TTL expires — surprising UX. Rejected for now; could be added later if needed.
- *Push the master into a frontend build-time constant*: That is precisely the anti-pattern this spec is fixing. Rejected.

**Impact on plan**:
- No caching infrastructure to add. TanStack Query is already in the frontend dependency set.
- The frontend hook just calls `fetch(/web-api/v1/licenses)` via `apiClient.request()` and lets TanStack Query handle in-flight deduplication and staleness.

---

## R6. Localization of license names

**Decision**: **Out of scope for v1**. License `short_name` and `name` are treated as stable identifiers and human-readable labels respectively, shown verbatim regardless of the user's UI locale. The existing `licenses` table schema has no per-locale columns; no per-locale fields are added in this feature.

**Rationale**:
- Per A-002 in the spec, the four canonical CC licenses have universally-recognized short names ("CC-BY", "CC0", etc.) that do not localize meaningfully. The full `name` ("Creative Commons Attribution 4.0 International") is the canonical English text from the license author and is generally not translated in legal contexts.
- Adding `name_en` / `name_ja` columns would force admins to enter both versions, adding friction with no clear user benefit at launch.
- If localization becomes a real need post-launch, it can be added as a separate, opt-in feature without breaking this one (additive columns + per-locale fallback resolution).

**Alternatives considered**:
- *Add `name_locale` JSONB column*: Premature optimization; rejected.
- *Translate `name` via Paraglide messages*: Would put license names in app translation files, which is not where license text belongs (and Paraglide can't translate arbitrary database content cleanly). Rejected.

**Impact on plan**: No localization-specific changes required. Frontend renders `license.short_name` (primary) with optional `license.name` (secondary, e.g. tooltip) in the user's UI locale chrome but with the license text itself untouched.

---

## R8. `project_license_history` schema migration

**Decision (added after Codex review)**: The existing `project_license_history.old_license` and `.new_license` columns are typed as the `ProjectLicense` enum and are tracked by the FR-086/FR-087 license-history surface. The migration converts both columns from the enum type to `VARCHAR(50)` and copies the existing enum string values verbatim. **The history columns are NOT FK-referenced** to `licenses(id)` — they are immutable historical snapshots and would silently lose meaning if a later admin rename rewrote their visible values.

This decision is intentionally asymmetric with `projects.license_id` (which IS a FK with rename-survivable semantics, per FR-004). The two columns serve different roles: the live FK on `projects` must follow admin renames; the snapshot columns on `project_license_history` must NOT.

**Rationale**:
- FR-005a explicitly distinguishes the live value (FK-bound) from the history snapshot (string).
- Treating history snapshots as FK references would mean a rename rewrites every audit-log entry showing the old name — equivalent to falsifying historical records. Unacceptable.
- The CSV export consumed by FR-086 reads the live value (`project.license`) not the history value; the history surface is presented as-is to admins via FR-087.

**Alternatives considered**:
- *FK both `old_license` and `new_license`*: violates "history is immutable". Rejected.
- *Delete `project_license_history` table outright as out-of-scope debt*: would silently drop the FR-086/FR-087 license-history surface. Rejected.
- *Leave history columns as the legacy enum type*: blocks admin-added license values from ever appearing in history transitions (an admin adding `CC-BY-ND` and then changing a project to it would crash the history insert). Rejected.

**Impact on plan**:
- Migration includes two `ALTER COLUMN ... TYPE VARCHAR(50)` statements (`old_license` + `new_license`) using `USING old_license::text` to convert without data loss.
- The legacy Postgres `projectlicense` enum type is **kept** in the DB schema after migration (the enum was originally created as a separate Postgres type and remains referenced only by potentially-future migrations; dropping it requires verifying nothing else references it and is deferred as cleanup debt).
- `models/project.py::ProjectLicenseHistory.old_license` / `.new_license`: redeclared as `Mapped[str | None]` / `Mapped[str]` respectively.
- Test scenarios include: insert a history row recording a transition from a seeded license to an admin-added license; verify the row survives and `GET /projects/{id}/license-history` returns it correctly.

---

## R7. Existing schema / FR-013 detail — `datasets.license_id`

**Decision**: In the same migration that introduces `projects.license_id`, drop and re-add the `datasets.license_id` FK constraint as `ON DELETE RESTRICT` (was `ON DELETE SET NULL`). No data migration on the dataset side is required — the column itself, its values, and the FK relationship are unchanged in shape.

**Rationale**:
- The user's Q1 answer ("Refuse で揃える") for FR-013 directly requires this.
- Dropping and re-adding the constraint is a near-instant operation (no row scan; PostgreSQL just rewrites the constraint metadata) so it adds negligible migration time.
- Doing both changes in one migration keeps the "refuse delete on in-use license" rule atomic across both reference types — there is no in-between state where projects refuse but datasets allow.

**Alternatives considered**:
- *Separate migration for datasets*: Two migrations to land before the rule is uniform. Marginally simpler diffs, but creates a window of inconsistent behavior. Rejected.
- *Leave datasets FK as SET NULL*: Contradicts the spec FR-013 resolution. Rejected.

**Impact on plan**:
- Migration includes constraint drop+add for `datasets.license_id`.
- `count_dependents` in the repository layer queries both `projects` and `datasets`.
- Contract test for `DELETE /api/v1/admin/licenses/{id}` exercises three cases: project-only dependency, dataset-only dependency, both.

---

## Summary table

| # | Topic | Decision | Notes |
|---|---|---|---|
| R1 | API shape | **Request: `license_id` (FK)**; response: still `short_name` string | FR-004 stable identifier requires this |
| R2 | New endpoint location | Both `/web-api/v1/licenses` and `/api/v1/licenses` | Read-only |
| R3 | Delete-protection | FK ON DELETE RESTRICT + service-layer 409 with re-count fallback on race | Defense in depth |
| R4 | Migration safety | Audit SELECT **as step 1**, ValueError on unknown values | Forward-only, transactional |
| R5 | Caching | TanStack `staleTime: 0` + `refetchOnMount: 'always'` | SC-001 (5 s) compliance |
| R6 | Localization | Out of scope | A-002 |
| R7 | Datasets FK | Drop+re-add as ON DELETE RESTRICT in same migration | FR-013 resolution |
| R8 | History snapshot columns | Enum → VARCHAR(50); NOT FK-referenced | FR-005a + immutability of history |

All Phase 0 unknowns are now resolved. Plan proceeds to Phase 1 (data-model.md + contracts + quickstart).
