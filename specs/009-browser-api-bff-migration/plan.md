# Implementation Plan: Complete Browser API → BFF Migration

**Branch**: `009-browser-api-bff-migration` | **Date**: 2026-05-12 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/009-browser-api-bff-migration/spec.md`

## Summary

Migrate every browser-side call from the legacy `/api/v1/*` (API-key) surface to the BFF `/web-api/v1/*` (session + Bearer) surface, in independent per-resource increments. The migration is delivered as a sequence of small reviewable PRs, each one (a) adding any missing BFF adapter on the backend (thin handler that reuses the existing service layer + the user/project/permission model), (b) rewiring the frontend caller, and (c) carrying a documented Gate 3 browser smoke. Out of scope: the legacy surface itself (continues to serve API-key clients unchanged), profile mutations and API-token endpoints (`PATCH /users/me`, `/users/me/api-tokens*`, `/users/me/password`), the setup wizard (`/setup/*`), and the dev `/api/v1/test` endpoint — these stay on the legacy surface as documented exceptions.

The technical approach was de-risked by Codex consultation (2026-05-12, 2 rounds) and refined by codebase audits on 2026-05-12 and 2026-05-13. **Existing BFF mirrors** (frontend rewire only): `auth/*` (login, logout, register, refresh, verify-email, password-reset, 2FA) and projects **reads** for list, detail, and recordings. **New BFF adapters required** in this migration: projects **mutations** (create / update / delete / member CRUD), projects **missing reads** (members listing, overview), `taxa/*` (search + GBIF lookup), and `admin/{licenses,recorders,settings,users}`. `projects/feed` was confirmed non-existent on 2026-05-13 (the only repo reference is a negative-test fixture) and is no longer in scope.

## Technical Context

**Language/Version**: Python 3.11 (backend), TypeScript 5.x (frontend, SvelteKit 2 / Svelte 5)
**Primary Dependencies**: FastAPI, SQLAlchemy 2.0 (async), Pydantic v2; TanStack Query, Vitest, Playwright
**Storage**: PostgreSQL 16+ — no schema changes (this is a transport-and-routing migration)
**Testing**: pytest + pytest-asyncio (backend integration / contract), vitest (frontend unit), Playwright (frontend E2E), `tests/contract/test_openapi_diff.py` (both surfaces gated)
**Target Platform**: Linux server (Docker), browser (modern Chromium / Firefox / Safari)
**Project Type**: Web monorepo (`apps/api`, `apps/web`)
**Performance Goals**: BFF endpoints MUST be ≤ legacy v1 latency (they reuse the same service layer). p95 latency for `GET /web-api/v1/projects` ≤ p95 for `GET /api/v1/projects` measured on identical fixtures.
**Constraints**: Zero observable regression on `/api/v1/*` (response shape / status code / rate limit unchanged). Zero new 401-driven auto-logouts in the browser console during a logged-in walkthrough of migrated screens. Each merged PR MUST be independently revertable without breaking other migrated screens.
**Scale/Scope**: ~28 unique endpoints across ~28 frontend files (audit snapshot 2026-05-12, main HEAD `b8d522b5`). Five documented exception groups remain on legacy.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Compliance | Evidence |
|-----------|------------|----------|
| **I. Clean Architecture** | ✅ Pass | Every new BFF handler is a thin adapter that delegates to the existing service layer (e.g. `build_project_summaries(db, projects)` shared between `web_v1/projects/_core.py` and `api/v1/projects.py`). No business logic duplication. |
| **II. TDD (NON-NEGOTIABLE)** | ✅ Pass | Per-resource PR sequence: integration test for the new BFF route is written first (must fail), then the handler, then frontend rewiring. The existing OpenAPI diff contract test (`apps/api/tests/contract/test_openapi_diff.py`, `_API_MOUNT_PREFIXES = ("/web-api/v1", "/api/v1")`) walks both mount prefixes — **but normalises them to a single prefix-stripped path and shallow-merges with `setdefault`**, so a method present on one surface and missing on the other is NOT caught. Each per-resource PR therefore adds an explicit integration test that asserts the BFF path responds (`200` for the migrated GET, `403` for unauthorised callers), and PR J adds a contract-level guard test that fails when a `/web-api/v1/<resource>` path declared by this migration is missing from the live OpenAPI surface. |
| **III. Type Safety** | ✅ Pass | Pydantic v2 schemas reused from existing v1 routers; frontend types come from the shared contract YAMLs. No new `any` types. `npm run check` + `uv run mypy .` are part of each per-resource PR's Gate 1. |
| **IV. ML Pipeline Architecture** | ➖ Not applicable | This migration touches only the HTTP transport and routing layer. No Celery / GPU / ML changes. |
| **V. API Versioning** | ✅ Pass (with note) | Both the legacy (`/api/v1/*`) and BFF (`/web-api/v1/*`) surfaces follow `v{major}` versioning. The BFF prefix is a separate mount established by spec/006 specifically to enforce actor-type / audit / rate-limit isolation; it is not a versioning of the legacy surface. No breaking changes to legacy v1 — all migrated callers move to the BFF mount, which is additive. **Wording note**: Constitution Principle V's literal `Format: /api/v{major}/...` does not explicitly enumerate the BFF prefix. This is a wording gap (the BFF surface still follows `v{major}` versioning on its own axis), not a substantive versioning violation. Renaming the BFF mount to `/api/v1` was rejected by spec/006 because the two surfaces require disjoint auth identities and disjoint audit / rate-limit semantics. **Recommended follow-up (out of this spec's scope)**: a separate constitution PATCH amendment to explicitly permit `/web-api/v{major}/...` browser-BFF surfaces under Principle V. |
| **Security: Auth & RBAC** | ✅ Pass | BFF endpoints use the shared `CurrentUser` dependency (`apps/api/echoroo/middleware/auth.py:324`) which resolves session cookie OR Bearer JWT, then runs RBAC via `gate_action` (spec/007). The two surfaces remain mutually rejecting (legacy v1 rejects BFF Bearer JWTs with "API key invalid or revoked" by design — preserved). |
| **Security: Input Validation** | ✅ Pass | Pydantic schemas reused; new BFF handlers do not introduce new input shapes. |
| **Security: Data Protection** | ✅ Pass | No new logging surfaces; transport unchanged. |
| **Security: OWASP / CSRF** | ✅ Pass | BFF mutating verbs enforce `X-CSRF-Token` via existing middleware (main.py:168 + frontend `callWebApi()` helper). Rate limits on legacy v1 unchanged. |

**Result**: PASS. No Complexity Tracking entries required.

## Project Structure

### Documentation (this feature)

```text
specs/009-browser-api-bff-migration/
├── plan.md              # This file (/speckit-plan output)
├── spec.md              # Feature specification (/speckit-specify output)
├── research.md          # Phase 0 output (resolved sequencing, missing mirrors, audit method)
├── data-model.md        # Phase 1 output (no new entities; documents the routing-only nature)
├── quickstart.md        # Phase 1 output (per-resource Gate 3 smoke recipe)
├── contracts/           # Phase 1 output (list of resource contracts that gain /web-api/v1 paths)
├── checklists/
│   └── requirements.md  # /speckit-specify quality checklist
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

This is the existing Echoroo monorepo; no new top-level layout is introduced.

```text
apps/api/echoroo/                                  # FastAPI backend
├── api/
│   ├── v1/                                        # LEGACY surface (API-key auth) — UNCHANGED
│   │   ├── projects.py
│   │   ├── admin.py                               # ← service-layer functions reused by new BFF mirrors
│   │   ├── taxa.py                                # ← service-layer functions reused by new BFF mirror
│   │   ├── auth.py
│   │   └── setup.py                               # exception: stays on legacy
│   └── web_v1/                                    # BFF surface — additions land here
│       ├── __init__.py                            # router aggregator (prefix /web-api/v1)
│       ├── auth.py                                # already complete
│       ├── users.py                               # /me read (PR #71)
│       ├── admin.py                               # currently: superusers/approvals/2fa/IP — needs: licenses/recorders/settings/users
│       ├── projects/                              # reads list/detail/recordings exist; PR A2 ADDS members listing + overview + mutations
│       │   ├── __init__.py
│       │   ├── _core.py                            # list / detail / recordings (existing) — PR A2 adds POST/PATCH/DELETE
│       │   ├── _members.py                        # invitation accept/decline (existing) — PR A2 adds GET /members + member POST/PATCH/DELETE
│       │   ├── _ownership.py
│       │   ├── _restricted_config.py
│       │   ├── _license.py
│       │   └── _overview.py                       # ← NEW (PR A2): GET /{project_id}/overview
│       ├── taxa.py                                # ← NEW (to add): /search, /gbif-search
│       └── admin/                                 # ← may split into a package for licenses / recorders / settings / users
│           ├── licenses.py                        # ← NEW
│           ├── recorders.py                       # ← NEW
│           ├── settings.py                        # ← NEW
│           └── users.py                           # ← NEW
├── services/                                       # service layer — reused unchanged by BFF adapters
│   ├── project.py                                  # build_project_summaries(...)
│   ├── admin/                                      # licenses/recorders/settings/users service helpers
│   ├── taxa.py
│   └── ...
├── middleware/
│   ├── auth.py                                     # get_current_user / CurrentUser — unchanged
│   └── auth_router.py                              # legacy v1 API-key gate — unchanged
└── main.py                                         # /web-api/v1 already mounted (line 225)

apps/api/tests/
├── contract/test_openapi_diff.py                   # gates both surfaces — already covers /web-api/v1 additions
├── contract/api/web_v1/                            # add one per new BFF resource
└── integration/api/web_v1/                         # add one per new BFF resource (test_taxa.py, test_admin_licenses.py, ...)

apps/web/src/                                        # SvelteKit frontend
├── lib/api/
│   ├── client.ts                                   # apiClient — handles both surfaces; no rewrite needed
│   ├── query-client.ts                             # TanStack Query — already URL-pattern-tolerant
│   ├── projects.ts                                 # ← REWIRE (P1): replace /api/v1/projects → /web-api/v1/projects via existing callWebApi() helper
│   ├── auth.ts                                     # ← REWIRE: register/verify-email/password-reset → BFF (login/refresh/me already on BFF)
│   ├── web-auth.ts                                 # ← review for leftover legacy calls
│   ├── admin.ts                                    # ← REWIRE after backend BFF admin mirrors land
│   ├── licenses.ts                                 # ← REWIRE
│   ├── recorders.ts                                # ← REWIRE
│   ├── taxa.ts                                     # ← REWIRE after backend BFF /taxa lands
│   ├── tokens.ts                                   # exception (users/me/api-tokens stays on legacy) — NO CHANGE
│   ├── setup.ts                                    # exception (setup wizard stays on legacy) — NO CHANGE
│   ├── users.ts                                    # exception PATCH + password stay on legacy; /me read already on BFF
│   └── types/                                      # types reused from contract YAMLs
├── lib/components/
│   ├── annotation/{AnnotationExportDialog,ExportDialog}.svelte   # ← REWIRE inline fetch calls
│   ├── common/MiniSpectrogram.svelte               # ← REWIRE
│   └── data/ExportDialog.svelte                    # ← REWIRE
├── lib/utils/audioPlayback.svelte.ts               # ← REWIRE
├── lib/stores/auth.svelte.ts                       # PR #71 already migrated /me; verify no leftover legacy calls
├── hooks.server.ts                                 # ← REWIRE: server-side prefetches must use BFF (cookie reachable from server)
├── routes/setup/+page.server.ts                    # exception — NO CHANGE
├── routes/(app)/projects/[id]/annotations/[annotationProjectId]/+page.svelte   # ← REWIRE
├── routes/(public)/explore/projects/[id]/+page.svelte                          # ← REWIRE (anonymous BFF read; web_v1/projects already Guest-aware)
└── routes/+layout.svelte                           # ← review for any direct /api/v1 call
```

**Structure Decision**: Use the existing monorepo layout. All backend additions land under `apps/api/echoroo/api/web_v1/` (mirroring the established split). Frontend rewiring stays inside `apps/web/src/lib/api/` and the few components that bypass the API client. No new top-level directories or packages are introduced.

## Migration sequence (per-resource PR plan)

The work is delivered as **independent PRs**, each gated by a Gate 3 browser smoke against the test dataset (per `CLAUDE.md` definition-of-done). The proposed sequence (final ordering will be set in `/speckit-tasks`):

| PR | Resource family | Backend change | Frontend change | Spec story | Notes |
|----|-----------------|----------------|-----------------|------------|-------|
| **A** | projects — **read subset only** (list, detail, recordings) | None — BFF already has `GET /`, `GET /{project_id}`, `GET /{project_id}/recordings` in `web_v1/projects/_core.py`. **Members listing and overview are deliberately NOT migrated here** — they have no BFF adapter yet and ship in PR A2. | Rewire only `listProjects`, `getProject`, and the recordings fetch in `lib/api/projects.ts` + the corresponding callers in `routes/(app)/projects/...`. **Do not** rewire `listMembers` or `getOverview` in this PR; they remain on legacy until PR A2. | US1 (P1) | Unblocks `/en/projects` and the read portions of project detail. Template-setting PR — establishes the frontend rewire pattern with **no new backend**. Mutations and the two missing reads (members, overview) stay on legacy here so this PR is small and revertable. Project detail page tolerates 401 on the legacy members/overview reads silently (already implemented per `routes/(app)/projects/[id]/+page.svelte` error handling). |
| **A2** | projects — **mutations + missing reads** | Add: BFF read adapters for `GET /web-api/v1/projects/{project_id}/members` and `GET /web-api/v1/projects/{project_id}/overview`. Add: BFF mutation adapters `POST /web-api/v1/projects`, `PATCH /web-api/v1/projects/{project_id}`, `DELETE /web-api/v1/projects/{project_id}`, plus member POST / PATCH / DELETE. CSRF-protected for all mutations. | Rewire the remaining frontend functions in `lib/api/projects.ts`: `listMembers`, `getOverview`, `createProject`, `updateProject`, `deleteProject`, `addProjectMember`, `updateProjectMember`, `removeProjectMember`. After this PR `projects.ts` has zero `/api/v1/*` calls. | US1 (P1) | First "new BFF adapter" PR. **Cannot ship before A.** Verifies CSRF + 403-not-401 + audit `actor_kind=session` end-to-end for project-scoped reads and mutations. Two read adapters (members, overview) bundled with mutations because they share the resource family and `gate_action` permission shape. |
| **B** | auth follow-up | None (BFF exists) | Rewire register / verify-email / password-reset / refresh in `lib/api/auth.ts` + `hooks.server.ts` | Foundation (supports US1+) | Closes residual legacy-auth callers. |
| **C** | taxa | Add `web_v1/taxa.py` (`/search`, `/gbif-search`) + tests | Rewire `lib/api/taxa.ts` + MiniSpectrogram | US2 (P2) | "New BFF adapter" template for D / E / F / G. Read-only — no CSRF surface. |
| **D** | annotation/data export + audio playback components | Verify per Phase 0 D-10 checklist whether existing project-scoped BFF paths cover the components' actual fetch shapes (Range header, `<audio src>` cookie auth, streaming, signed URL). Add backend adapters if any gap surfaces. | Rewire inline fetches in `AnnotationExportDialog.svelte`, `ExportDialog.svelte` (annotation + data), `audioPlayback.svelte.ts` | US2 (P2) | **Pre-PR audit required** (see Phase 0 D-10). Component rewiring may not be enough — audio especially is non-trivial because `<audio src>` cannot attach Bearer headers and relies on cookie-auth + signed URL paths. |
| **E** | admin/licenses | Add `web_v1/admin/licenses.py` + tests | Rewire `lib/api/licenses.ts` (+ relevant `lib/api/admin.ts` calls) | US3 (P3) | Small surface, good standalone PR. |
| **F** | admin/recorders | Add `web_v1/admin/recorders.py` + tests | Rewire `lib/api/recorders.ts` | US3 (P3) | Mirrors E. |
| **G** | admin/settings | Add `web_v1/admin/settings.py` + tests | Rewire `lib/api/admin.ts` settings calls | US3 (P3) | Mirrors E. |
| **H** | admin/users | Add `web_v1/admin/users.py` + tests | Rewire `lib/api/admin.ts` users calls | US3 (P3) | Mirrors E. |
| **I** | guest/`/explore` polish | None expected | Confirm `routes/(public)/explore/projects[/{id}]` calls land on `/web-api/v1/projects[/{id}]` (already true per 2026-05-13 grep) and remove any residual legacy references; audit `<audio>` / `<img>` URLs on public detail | US4 (P3) | **Reframed from earlier "projects/feed mirror" idea** — `projects/feed` is NOT a live endpoint (only appears as a test fixture in `lib/api/__tests__/client.permissions.test.ts:70` as an example of "rejected non-UUID segment"). See Phase 0 D-9. |
| **J** | cleanup + lint guard + contract-parity test | Add a contract test asserting every `/web-api/v1/<resource>` path declared by this migration appears in the live OpenAPI surface (covers the shallow-merge limitation of `test_openapi_diff.py` flagged in Constitution Check II) | Add a CI guard that rejects new `/api/v1/*` string literals in `apps/web/src/` outside the documented exception list; audit `lib/api/__tests__/client.permissions.test.ts` (note that the `/projects/feed` reference there is an intentional negative-test fixture and should be kept) and `lib/types/{detection,index}.ts` for residual legacy references | SC-001 / SC-004 / SC-006 | Final PR — locks the migration in place. |

Each PR is independently revertable. **A blocks A2** (A2's tests assume the BFF read-path adapter pattern from A is in place). **B is independent** of A/A2. PRs **C–H** are parallelizable with worktree isolation (memory: parallel SSA needs worktree isolation, max 2 parallel). **D depends on D-10 pre-audit completing in Phase 0 (research)**.

### Per-PR exception-list guard (mandatory)

To avoid leaving stale legacy callers behind until PR J, every PR in this sequence MUST satisfy the following before merge:

> For the resource family this PR migrates, `rg -n '/api/v1/<resource>' apps/web/src/` returns **zero hits outside the documented exception list** (see FR-011, SC-004).

This per-PR check is in addition to PR J's repo-wide guard, not a replacement for it.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No violations. Constitution Check PASSED on first evaluation. Section intentionally left empty.
