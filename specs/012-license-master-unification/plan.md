# Implementation Plan: License Master Unification

**Branch**: `012-license-master-unification` | **Date**: 2026-05-26 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/012-license-master-unification/spec.md`

## Summary

Promote the existing `licenses` master table to be the single source of truth for project license assignment.
Today `projects.license` is an enum string column populated by a four-element hardcoded constant on the
frontend; the admin `licenses` table (with full CRUD) ships empty and never reaches users. This plan converts
`projects.license` into a FK referencing `licenses.id` (mirroring the existing `datasets.license_id` shape),
seeds the master with the four canonical CC licenses, exposes a public-read endpoint that the project
creation form fetches live, and tightens the delete-protection rule on both `projects.license_id` and
`datasets.license_id` so an in-use license can never be deleted out from under a referencing row.

Technical approach: one forward-only Alembic migration (0024 unless other migrations land first) that (a)
audits all license-typed columns for unrecognized values first, (b) seeds the master with the four canonical
licenses via `ON CONFLICT (short_name)`, (c) adds `projects.license_id` FK with `ON DELETE RESTRICT` and an
explicit index, (d) drops the legacy `projects.license` enum column, (e) converts the enum-typed
`project_license_history.old_license` / `.new_license` columns to `VARCHAR(50)` (history snapshots, NOT
FK-referenced), and (f) tightens the `datasets.license_id` FK from SET NULL to RESTRICT. Backend gains one
new read endpoint under both `/web-api/v1/licenses` (BFF, cookie session) and `/api/v1/licenses` (Bearer).
The existing admin DELETE handler (at `apps/api/echoroo/api/v1/admin.py` and BFF
`apps/api/echoroo/api/web_v1/_admin_licenses.py` — NOT a per-resource file) gains a service-layer
dependency-count check that refuses with 409 Conflict + counts when the license is referenced; FK race
conditions trigger a re-count fallback rather than a sentinel value. Frontend project creation form replaces
its hardcoded constant with a TanStack Query call (`staleTime: 0`, `refetchOnMount: 'always'`) and submits
the stable `license_id` value instead of the short_name. The JSON shape returned by `projects` endpoints
keeps the `license` field as a short-name string (no breaking change to read consumers); the **request**
body for `POST /projects` switches from `license: ProjectLicense` to `license_id: str`. The CSV export
(`apps/api/echoroo/services/detection_export.py:381`) switches from `project.license.value` to
`project.license` (joined short_name) — wire shape unchanged.

**Delivery shape (revised after Codex review)**: 2 PRs (PR-A backend + migration, PR-B frontend) rather
than a single PR. Risk concentration in PR-A is the rationale; see tasks.md for the split detail.

## Technical Context

**Language/Version**: Python 3.11+ (backend, `requires-python = ">=3.11"`), TypeScript 5 + Svelte 5 (frontend)
**Primary Dependencies**: FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2, asyncpg + SvelteKit, Paraglide-JS v2 (URL strategy), TanStack Query
**Storage**: PostgreSQL 16 (existing `licenses` table; `projects.license` enum column → `projects.license_id` FK column)
**Testing**: pytest (contract / unit / integration with testcontainers PostgreSQL 16 + pgvector), `svelte-check`, optional Playwright smoke
**Target Platform**: Linux server (Docker); SvelteKit SSR + static client
**Project Type**: Web application (FastAPI backend + SvelteKit frontend, monorepo under `apps/api/` and `apps/web/`)
**Performance Goals**: License master fetch ≤ 200 ms p95 added on top of project-creation form open (SC-005); admin license CRUD response time unchanged from today
**Constraints**:
- Forward-only migration (precedent: spec/011 step 11 / migration 0022); `downgrade()` raises `NotImplementedError`
- Existing `datasets.license_id` FK with ON DELETE SET NULL must transition to ON DELETE RESTRICT in the same migration (FR-013)
- API response shape for project `license` field must stay a stable short-name string — no breaking change to existing consumers
- Migration aborts loudly on unrecognized enum values (FR-010); silent dropping or guessing is forbidden
- Admin license CRUD endpoints (`/api/v1/admin/licenses` create/read/update) untouched except for the dependency check added to DELETE
**Scale/Scope**: Pre-launch — small handful of dev/preview projects, low-cardinality license set (~4 seeded + admin additions over time). One backend migration, one new public-read endpoint pair, two service-layer changes, one frontend page modification.

## Constitution Check

*GATE: must pass before Phase 0 research. Re-evaluated after Phase 1 design — see end of file.*

| Principle | Status | Notes |
|---|---|---|
| **I. Clean Architecture** | Pass | License master already follows layered API → service → repository → model decomposition. New public-read endpoint slots into the same layering (handler in `api/v1/` + `api/web_v1/`, business logic in `services/license_service.py`, data access via existing `LicenseRepository`). |
| **II. TDD (non-negotiable)** | Pass | Plan calls for contract tests for the new read endpoints, an integration test for the migration (mirroring the `test_0022_email_subsystem_removal.py` testcontainers pattern), and unit tests for the dependency-count refusal in the admin DELETE service path. Tests precede implementation. |
| **III. Type Safety** | Pass | All new request/response shapes flow through Pydantic schemas. Frontend regenerates types from the updated OpenAPI surface; the project creation form's hardcoded `LICENSE_OPTIONS` constant is replaced by the typed query result. |
| **IV. ML Pipeline Architecture** | N/A | Feature is unrelated to ML; no Celery work involved. |
| **V. API Versioning** | Pass | All new endpoints land under existing `/web-api/v1/*` and `/api/v1/*` prefixes. The wire shape of project responses' `license` field stays a string (no breaking change). The internal `projects.license` enum column rename to `projects.license_id` is a storage-only change invisible to API consumers. |
| **Security — AuthN/Z** | Pass | New public-read endpoint is gated by the existing session middleware (cookie session at BFF, Bearer at programmatic) and requires only "authenticated user with permission to create a project" per FR-017 — i.e. any authenticated user. No admin escalation. |
| **Security — Input Validation** | Pass | License id submitted by project creation is validated as a string ≤ 50 chars (matching the existing `licenses.id` column) and verified to exist in the master before insert. |
| **Security — Data Protection** | N/A | No sensitive data introduced. |
| **Security — OWASP Compliance** | Pass | Rate limiting and CSRF protection inherited from the existing web-api router stack — no new public surface that needs bespoke rate limiting. |

No violations to justify. Complexity Tracking section omitted.

## Project Structure

### Documentation (this feature)

```text
specs/012-license-master-unification/
├── spec.md                          # Feature specification (already written, this PR)
├── plan.md                          # This file
├── research.md                      # Phase 0 output
├── data-model.md                    # Phase 1 output
├── quickstart.md                    # Phase 1 output
├── contracts/
│   ├── web-licenses.yaml            # GET /web-api/v1/licenses
│   ├── licenses.yaml                # GET /api/v1/licenses
│   └── admin-licenses-delete.yaml   # DELETE /api/v1/admin/licenses/{id} (409 shape)
├── checklists/
│   └── requirements.md              # Spec quality checklist (already written)
└── tasks.md                         # Phase 2 output (/speckit-tasks command — NOT created here)
```

### Source Code (repository root)

```text
apps/api/                                              # FastAPI backend (Python 3.11)
├── echoroo/
│   ├── models/
│   │   ├── license.py                                 # EXISTING — unchanged
│   │   ├── project.py                                 # MODIFIED — Project: license column → license_id FK; ProjectLicenseHistory: enum cols → VARCHAR(50)
│   │   ├── enums.py                                   # MODIFIED — ProjectLicense enum kept temporarily for legacy data migration mapping only
│   │   └── dataset.py                                 # MODIFIED — annotate FK ondelete=RESTRICT (constraint replaced via migration)
│   ├── schemas/
│   │   ├── license.py                                 # MODIFIED — add LicensePublicResponse + LicenseListResponse
│   │   └── project.py                                 # MODIFIED — ProjectCreateRequest.license → license_id (str); ProjectResponse.license stays short_name string
│   ├── repositories/
│   │   ├── license.py                                 # MODIFIED — add count_dependents()
│   │   └── project.py                                 # MODIFIED — write/read via license_id, join licenses for short_name
│   ├── services/
│   │   ├── license_service.py                         # MODIFIED — list_public(), delete (refuse-on-dependents + race re-count)
│   │   ├── project_service.py                         # MODIFIED — validate license_id existence on create/update
│   │   └── detection_export.py                        # MODIFIED — `project.license.value` → `project.license` (joined short_name)
│   ├── api/
│   │   ├── v1/
│   │   │   ├── licenses.py                            # NEW — GET /api/v1/licenses (Bearer, public-read)
│   │   │   └── admin.py                               # MODIFIED — DELETE refuses 409 when in use (NOT a per-resource file; this is the aggregated admin module)
│   │   └── web_v1/
│   │       ├── licenses.py                            # NEW — GET /web-api/v1/licenses (cookie session)
│   │       └── _admin_licenses.py                     # MODIFIED — BFF DELETE refuses 409 with same body shape (parallel to legacy admin)
│   └── alembic/versions/
│       └── 0024_license_master_unification.py         # NEW — audit-first migration (10 steps): audit → unique → seed (short_name conflict) → add column → UPDATE map → FK+index → drop legacy column → history cols ALTER → datasets FK swap → downgrade=NotImplementedError
└── tests/
    ├── contract/
    │   ├── test_licenses_public.py                    # NEW — both /web-api/v1/licenses and /api/v1/licenses
    │   └── test_admin_licenses_delete.py              # MODIFIED — adds 409 Conflict cases
    ├── unit/
    │   └── services/test_license_service.py           # NEW — dependency-count + refusal logic
    └── integration/
        └── migrations/test_0024_license_unification.py # NEW — full migration: seed + FK + drop enum + datasets FK swap

apps/web/                                              # SvelteKit frontend (Svelte 5)
├── src/
│   ├── routes/(app)/projects/new/+page.svelte         # MODIFIED — fetch from master, drop LICENSE_OPTIONS
│   ├── lib/
│   │   ├── api/
│   │   │   └── licenses.ts                            # NEW — TanStack Query hook for GET /web-api/v1/licenses
│   │   └── types/
│   │       └── index.ts                               # MODIFIED — License type aligned with backend schema
│   └── messages/
│       ├── en.json                                    # MODIFIED — new error / empty-state messages
│       └── ja.json                                    # MODIFIED — same
└── tests/                                             # No new tests required for this slice
```

**Structure Decision**: Existing monorepo split (`apps/api` for backend, `apps/web` for frontend). All new code lives in established directories; no new top-level structure required. Migration follows the per-revision file pattern in `apps/api/alembic/versions/`.

## Phase 0 / Research

Resolved unknowns and design decisions are captured in [research.md](./research.md). High-level outline:

1. **API response shape for `project.license`** — keep as short-name string (no breaking change). Internal storage moves to FK.
2. **Public-read endpoint location** — register under both `/web-api/v1/licenses` (cookie session for the form) and `/api/v1/licenses` (Bearer for parity / future programmatic callers).
3. **Delete-protection mechanism** — PostgreSQL FK `ON DELETE RESTRICT` for both projects and datasets references; service layer pre-computes dependency counts to provide actionable error messages (FR-015).
4. **Migration safety against unknown enum values** — explicit `SELECT DISTINCT` audit step inside the migration that aborts with `ValueError` listing the offenders if any unrecognized values exist (FR-010).
5. **Caching strategy** — no caching layer on launch; rely on TanStack Query's per-session staleness handling (A-004). License master is low-cardinality and changes rarely.
6. **i18n for license names** — out of scope (A-002); short_name treated as a stable identifier shown in user's UI locale but not translated.

## Phase 1 / Design & Contracts

### Data model

See [data-model.md](./data-model.md). Summary:

- `License` (existing) — unchanged columns; new in-feature unique constraint on `short_name` (idempotent if it already happened to be unique pre-launch).
- `Project` — `license` enum column dropped; `license_id VARCHAR(50)` FK to `licenses(id)` added with ON DELETE RESTRICT.
- `Dataset` — FK constraint on `license_id` changed from ON DELETE SET NULL to ON DELETE RESTRICT (column itself unchanged).

### Contracts

See [contracts/](./contracts/):

- **`web-licenses.yaml`** — `GET /web-api/v1/licenses` (cookie session). Returns array of `{id, short_name, name, url, description}` sorted by `short_name`. Status 200 always (empty array if master is empty).
- **`licenses.yaml`** — `GET /api/v1/licenses` (Bearer). Same response shape as web-api variant; included for parity and to keep the auth router's path classification clean.
- **`admin-licenses-delete.yaml`** — Documents the new 409 Conflict response body shape for `DELETE /api/v1/admin/licenses/{id}` when the license is still referenced. Existing 204 / 404 responses are unchanged.

### Quickstart

See [quickstart.md](./quickstart.md). Runbook for verifying the feature end-to-end after the migration applies (apply migration → verify seed → verify dropdown → verify admin add roundtrip → verify delete refusal).

### Agent context update

Plan reference between the `<!-- SPECKIT START -->` and `<!-- SPECKIT END -->` markers in CLAUDE.md (project root) points to `specs/012-license-master-unification/plan.md` after this command runs.

## Re-evaluation — Constitution Check (post-design)

Re-checked after writing data-model.md, contracts, and quickstart. No new violations introduced. The design adds:

- One new endpoint pair (covered by versioning principle V — under existing `/api/v1` and `/web-api/v1` prefixes).
- One additive column (`projects.license_id`) and one constraint replacement (`datasets.license_id` FK) — both invisible to API consumers per the wire-shape stability decision in research.md.
- Test coverage expansion in contract + integration + unit layers (covered by principle II).

Still passing across the board. Ready for `/speckit-tasks`.

## Next phases

- **`/speckit-tasks`** — generates `tasks.md` enumerating concrete tasks (backend migration, model, schema, repo, service, two endpoints, admin delete check, frontend page change, frontend API client, translations, contract tests, unit tests, integration test, smoke verification).
- **`/speckit-implement`** — executes tasks.md as **2 PRs** (PR-A backend + migration, PR-B frontend; see tasks.md "Delivery shape" for the split rationale after Codex review).
