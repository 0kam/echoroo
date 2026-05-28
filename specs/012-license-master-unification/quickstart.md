# Quickstart: License Master Unification

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-05-26

This document is the manual smoke runbook for verifying the feature end-to-end after the implementation
lands. Use it (a) after applying the migration locally, (b) before merging a feature PR, (c) as the basis
for the eventual Playwright e2e test that automates these checks.

**Delivery shape (revised per tasks.md after Codex review)**: the feature ships in **2 PRs**:

- **PR-A** (backend + migration): exercise sections 1–3 + 6 (admin delete refusal — raw API only) + 7
  immediately after PR-A merges to dev.
- **PR-B** (frontend): exercise sections 4–5 + 6 (admin UI delete refusal — browser path) after PR-B
  merges; PR-B against an un-PR-A'd backend would 404 the new endpoint and 422 on form submit.

---

## Prerequisites

- Docker stack running (`./scripts/docker.sh dev` or preview equivalent)
- Logged-in admin account (e.g. `okamoto.ryotaro@nies.go.jp` on preview, or `test@echoroo.app` on dev)
- Logged-in non-admin account for one cross-check (e.g. a preview `e2e-member@echoroo.app`)
- Database snapshot of `projects.license` values from before the migration (so you can verify zero drift in section 1)

---

## 1. Migration applies cleanly and existing projects keep their license

**Goal**: SC-002 (zero existing projects lose their previously-assigned license).

```bash
# Take the "before" snapshot
docker exec echoroo-db psql -U echoroo -d echoroo \
  -c "SELECT id, license FROM projects ORDER BY id" > /tmp/license_before.txt

# Apply the migration
docker exec echoroo-backend uv run alembic upgrade head

# Take the "after" snapshot
docker exec echoroo-db psql -U echoroo -d echoroo \
  -c "SELECT p.id, l.short_name AS license
        FROM projects p
        LEFT JOIN licenses l ON l.id = p.license_id
       ORDER BY p.id" > /tmp/license_after.txt
```

**Expected**:
- `alembic upgrade head` exits 0 with no errors and no warnings.
- `diff /tmp/license_before.txt /tmp/license_after.txt` shows **zero substantive differences** — column header may differ in formatting but the rows must match short_name for short_name.

If the diff shows any project losing its license value, abort and investigate before proceeding.

## 2. Master is seeded with the four canonical licenses

**Goal**: FR-007.

```bash
docker exec echoroo-db psql -U echoroo -d echoroo \
  -c "SELECT id, short_name FROM licenses ORDER BY short_name"
```

**Expected** (four rows, in some order):

| id | short_name |
|---|---|
| cc-by | CC-BY |
| cc-by-nc | CC-BY-NC |
| cc-by-sa | CC-BY-SA |
| cc0 | CC0 |

If the master had admin-curated rows pre-migration, those rows are preserved and the four canonical rows are added only where the `id` was free (idempotent seed; FR-007).

## 3. Read endpoints serve the master

**Goal**: FR-001, FR-002, FR-016, FR-017.

```bash
# As an authenticated user (cookie session example below assumes
# you've logged in via the browser and have a valid `echoroo_session`
# cookie). Easier path: open the dev tools network panel during the
# next section's UI test and inspect the request.
curl -sS \
  -b "echoroo_session=<your-session>; echoroo_csrf=<your-csrf>" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  http://localhost:3001/web-api/v1/licenses | jq

# Parallel Bearer-only endpoint (if you have an API key)
curl -sS -H "Authorization: Bearer $API_KEY" \
  http://localhost:8102/api/v1/licenses | jq
```

**Expected**: both calls return 200 with a JSON body shaped like

```json
{
  "items": [
    { "id": "cc-by",    "short_name": "CC-BY",    "name": "...", "url": "...", "description": null },
    { "id": "cc-by-nc", "short_name": "CC-BY-NC", "name": "...", "url": "...", "description": null },
    { "id": "cc-by-sa", "short_name": "CC-BY-SA", "name": "...", "url": "...", "description": null },
    { "id": "cc0",      "short_name": "CC0",      "name": "...", "url": "...", "description": null }
  ]
}
```

The items must be sorted by `short_name` ascending. Latency for `/web-api/v1/licenses` should be < 50 ms locally (well under the 200 ms p95 SC-005 budget).

## 4. Project creation form shows the live master

**Goal**: User Story 1 (P1) acceptance scenario.

1. Open a browser tab as the non-admin authenticated user.
2. Navigate to `/en/projects/new` (or `/ja/projects/new`).
3. Open the network panel.

**Expected**:
- A `GET /web-api/v1/licenses` request fires on form open (TanStack Query `refetchOnMount: 'always'`).
- The license dropdown displays exactly the four seeded options (CC0 / CC-BY / CC-BY-NC / CC-BY-SA), sorted by `short_name`. The hardcoded `LICENSE_OPTIONS` constant should no longer exist in the page source.
- Each `<option>` carries `value={license.id}` (e.g. `value="cc-by"`) with the visible text being `license.short_name`. **The form submit body MUST contain `license_id` (not `license`)** — verify in the Network panel that the POST /projects request body has `"license_id": "cc-by"` or similar.
- Selecting one of them and submitting creates a project whose API response field `license` reports the joined `short_name` string (e.g. `"CC-BY"`) — the response shape stays backward-compatible per research §R1; only the **request** shape changed.

## 5. Admin additions reach project creation immediately

**Goal**: User Story 1 (P1) — the headline outcome.

1. As an admin, open `/admin/licenses` in one tab.
2. Add a new license with these values:
   - `id`: `cc-by-nd`
   - `short_name`: `CC-BY-ND`
   - `name`: `Creative Commons Attribution-NoDerivatives 4.0 International`
   - `url`: `https://creativecommons.org/licenses/by-nd/4.0/`
3. Save.
4. In a second browser tab (different non-admin user), open `/en/projects/new`.

**Expected**: `CC-BY-ND` appears in the dropdown alongside the other four. No code change, no service restart, no cache flush.

Selecting `CC-BY-ND` and submitting the form must successfully create a project whose `license` reports as `"CC-BY-ND"`.

## 6. Delete-protection refuses an in-use license

**Goal**: User Story 3 (P2) and FR-006, FR-012, FR-015.

1. With the project from section 5 still referencing `CC-BY-ND`, return to the admin `/admin/licenses` tab.
2. Attempt to delete the `CC-BY-ND` row.

**Expected**:
- The deletion is refused with an actionable error message.
- The message must include the license short_name (`CC-BY-ND`), the project dependency count (at least 1), and the dataset dependency count (likely 0 in this scenario).
- The `CC-BY-ND` row remains visible in both the admin UI and the project creation dropdown.

Cross-check (raw API) — exercise **BOTH** the Bearer endpoint and the cookie-session BFF endpoint (the SvelteKit admin UI actually calls the BFF):

```bash
# Bearer-authenticated programmatic endpoint
curl -i -X DELETE -H "Authorization: Bearer $API_KEY" \
  http://localhost:8102/api/v1/admin/licenses/cc-by-nd

# Cookie-session BFF endpoint (what /admin/licenses page uses)
curl -i -X DELETE \
  -b "echoroo_session=$SESSION; echoroo_csrf=$CSRF" \
  -H "X-CSRF-Token: $CSRF" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  http://localhost:3001/web-api/v1/admin/licenses/cc-by-nd
```

**Expected response** (status 409 for both, identical body shape per `contracts/admin-licenses-delete.yaml`):

```json
{
  "error_code": "license_in_use",
  "message": "License 'CC-BY-ND' is still in use; reassign or remove dependents first",
  "short_name": "CC-BY-ND",
  "project_count": 1,
  "dataset_count": 0
}
```

Notes:
- `project_count` and `dataset_count` are both ≥ 0 with at least one ≥ 1 (per contract `minimum: 0` after Codex review).
- If a race condition fires (concurrent INSERT lands a referencing row between the service-layer pre-count and the DELETE), the backend re-runs `count_dependents` before returning 409 — the counts in the body reflect the post-race state. There is no `-1` sentinel.

Final cleanup: change the test project's license to something else, then re-attempt the delete. It should now succeed with 204 No Content on both endpoints.

## 7. Migration safety belt rejects unknown enum values (negative test)

**Goal**: FR-010. The migration's audit step 1 scans **three columns**: `projects.license`, `project_license_history.old_license`, and `project_license_history.new_license`. Each is independently tested below.

This step is destructive to license columns and SHOULD be run only on a throwaway test DB
(testcontainers fixture, scratch dev DB), NEVER on dev / preview / production.

### 7a. Negative test — projects.license

```bash
# 1. Roll back to before migration 0024 in a throwaway DB
# 2. Inject an unrecognized license value:
docker exec test-db psql -U echoroo -d echoroo \
  -c "UPDATE projects SET license = 'CC-BY-ND' WHERE id = '<some-id>'"
# 3. Attempt to apply migration 0024
docker exec test-backend uv run alembic upgrade head
```

**Expected**: the migration aborts with a clear ValueError listing the offending value (`CC-BY-ND`). The transaction rolls back, leaving the schema fully untouched (no new column, no FK changes, no history-column type changes). The operator can either:
- Manually map the offender to one of the canonical values, or
- Extend the migration's mapping table to recognize the new value (requires a code change).

After cleanup, the migration applies normally.

### 7b. Negative test — project_license_history.{old_license, new_license}

```bash
# 1. Roll back to before migration 0024 (or use a fresh throwaway DB)
# 2. Inject an unrecognized value into history (NOT projects.license):
docker exec test-db psql -U echoroo -d echoroo \
  -c "INSERT INTO project_license_history
        (id, project_id, old_license, new_license, changed_at, changed_by_id, created_at, updated_at)
      VALUES
        (gen_random_uuid(), '<existing-project-id>', NULL, 'CC-BY-ND',
         now(), '<existing-user-id>', now(), now())"
# 3. Attempt to apply migration 0024
docker exec test-backend uv run alembic upgrade head
```

**Expected**: same as 7a — ValueError listing the offending history value, schema untouched. This proves the audit's coverage of all three license-typed columns (data-model.md migration step 1).

Cleanup: delete the synthetic history row, then the migration applies normally.

---

## What to do if a step fails

| Step | Failure | Investigation |
|---|---|---|
| 1 | Migration exits non-zero | Inspect `alembic upgrade head` stderr. Most likely FR-010 (unknown enum value in `projects.license` or `project_license_history.{old,new}_license`) — clean up and re-run. The audit covers all three columns. |
| 1 | After-snapshot diff shows changed licenses | Migration mapping table is wrong. Roll back, fix, re-run. |
| 2 | Seed rows missing | Seed step (migration step 3) failed before reaching it; check migration log. Verify the `ON CONFLICT (short_name)` clause references the unique constraint added in step 2. |
| 3 | Endpoint returns 401 | Verify session is fresh (`/web-api/v1/auth/refresh` if access token expired); cookies AND Bearer header must both reach the backend per existing auth middleware. |
| 3 | Endpoint returns 200 but body is empty | Master was emptied by an admin between sections 2 and 3 — re-run section 2. |
| 4 | Form shows the old hardcoded options | Frontend bundle stale or the page change has not shipped. Verify `LICENSE_OPTIONS` constant is no longer present in `apps/web/src/routes/(app)/projects/new/+page.svelte`. |
| 5 | Admin add does not appear in `/projects/new` | Verify `useLicenses()` hook was called with `staleTime: 0` and `refetchOnMount: 'always'` (research §R5 revised). If those are set, force a hard page reload — TanStack Query will refetch on mount. |
| 6 | Delete succeeds against an in-use license | DB FK constraint is wrong or missing — check migration step 6 (`projects.license_id` FK) and step 9 (`datasets.license_id` FK), both with `ON DELETE RESTRICT`. |
| 7 | Migration succeeds despite unknown value | Step 1 audit SELECT is missing or wrong — check migration source (audit MUST be the first step, BEFORE any schema or seed change, per data-model.md). |
