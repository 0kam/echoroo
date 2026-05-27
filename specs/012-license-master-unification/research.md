# Research: License Master Unification

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-05-26

This document records the design decisions taken during Phase 0 of `/speckit-plan`,
along with the rationale and alternatives considered for each one. The plan and
data-model documents reference these decisions; the contracts and quickstart
artifacts assume them as ground truth.

---

## R1. API response shape for `project.license`

**Decision**: Keep the `license` field in project API responses as the existing **short-name string** (e.g. `"CC-BY"`). The internal column rename from `projects.license` (enum) to `projects.license_id` (FK to `licenses.id`) is a storage-only change and MUST NOT change the JSON shape that current consumers see.

**Rationale**:
- The user's expectation, framed in the spec, is "the inverse of intuitive ordering — admin master should drive the form" — not "introduce a richer license object everywhere." Tightening the contract to push a `{id, short_name, name, url}` object onto every project response would force coordinated frontend + downstream consumer updates with no offsetting benefit for this feature.
- Constitution principle V (API Versioning) requires backward compatibility within a major version. Changing `project.license` from `"CC-BY"` (string) to `{ "id": "cc-by", "short_name": "CC-BY", ... }` (object) is a breaking change and would force `v2`.
- The license short_name is FR-004's "stable identifier that survives renaming" only insofar as the master treats `id` as the stable key. In responses we still need the human-readable name; `short_name` is the closest match to today's enum string. The Project model resolves the FK on read and emits `short_name`.

**Alternatives considered**:
- *Expand to a full license object on every project response*: Cleaner data model, but breaking and out of scope. Possible as a follow-up under `project.license_details` (optional, additive) if the UI needs more info.
- *Expose `license_id` directly in the API*: Cluttered for clients that only render a label; ids are opaque to most callers. Rejected.

**Impact on plan**:
- `schemas/project.py` keeps the `license: str | None` field, but its source switches from the enum column to a join-and-pluck on `licenses.short_name`. `ProjectResponse.license` is populated by the repository or service layer reading the joined value.
- The `POST /projects` request body keeps `license: str | None` (the short_name). Backend resolves short_name → license_id by looking up the master before insert; an unknown short_name yields a 400 / 422 with a useful message.

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

**Decision**: The migration runs an **audit SELECT** as its first operation against `projects` rows: `SELECT DISTINCT license FROM projects WHERE license IS NOT NULL AND license NOT IN ('CC0','CC-BY','CC-BY-NC','CC-BY-SA')`. If the result is non-empty, raise `ValueError` with the list of offending values. Postgres rolls the migration transaction back; no schema changes are committed. The operator must manually clean up `projects.license` values (or extend the seed list) before re-running.

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

**Decision**: **No caching layer** on launch. The frontend uses TanStack Query with `staleTime: 30s` so rapid revisits within a single user's session deduplicate the network call, but every cold form-open hits the backend fresh. No backend caching (Redis, in-memory) is added.

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
| R1 | `project.license` API shape | Keep short-name string | No breaking change |
| R2 | New endpoint location | Both `/web-api/v1/licenses` and `/api/v1/licenses` | Read-only |
| R3 | Delete-protection | FK ON DELETE RESTRICT + service-layer 409 | Defense in depth |
| R4 | Migration safety | Audit SELECT + ValueError on unknown values | Forward-only, transactional |
| R5 | Caching | None on launch; TanStack staleTime only | A-004 |
| R6 | Localization | Out of scope | A-002 |
| R7 | Datasets FK | Drop+re-add as ON DELETE RESTRICT in same migration | FR-013 resolution |

All Phase 0 unknowns are now resolved. Plan proceeds to Phase 1 (data-model.md + contracts + quickstart).
