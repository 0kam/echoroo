# Feature Specification: Complete Browser API → BFF Migration

**Feature Branch**: `009-browser-api-bff-migration`
**Created**: 2026-05-12
**Status**: Draft
**Input**: Solve the broken browser-facing API path problem discovered during PR #70 Gate 3 smoke (2026-05-12): the SvelteKit web UI is still calling legacy `/api/v1/*` Bearer-JWT endpoints, but spec/006 moved browser auth to BFF (`/web-api/v1/*` with session + BFF-issued access token). Legacy endpoints now reject BFF tokens by design, so the browser UI surfaces "API key invalid or revoked" errors and empty states. PR #71 fixed only `/users/me`; ~28 other endpoints remain. Complete the migration so the browser UI no longer touches `/api/v1/*` (modulo a small, documented exception list), without weakening the actor / audit / rate-limit isolation between the BFF surface (browser users) and the legacy v1 surface (API-key clients).

## User Scenarios & Testing *(mandatory)*

<!-- User stories ordered by priority. Each story is independently shippable — implementing only one still produces a viable, demonstrable improvement. -->

### User Story 1 — Authenticated user can view the project list (Priority: P1)

A logged-in user opens the browser, completes login + 2FA, and navigates to the projects index. They expect the page to render their projects — the very entry point of the application. Today (2026-05-12), the page renders an "API key invalid or revoked" alert and an empty state, because the front-end fetcher targets the legacy v1 surface that no longer accepts BFF tokens.

**Why this priority**: This is the confirmed-broken entry point of the authenticated experience surfaced during Gate 3 manual smoke. Until this works, no authenticated user can reach any project-scoped feature. Migrating projects also establishes the per-resource adapter pattern that every later resource will copy, so it is the natural template-setter.

**Independent Test**: Log in as `test@echoroo.app`, visit `/en/projects`, and confirm the user's projects render with zero `/api/v1/*` calls and zero 401s in the browser console. Verify no regression on API-key-authenticated `/api/v1/projects` clients (existing legacy callers continue to work).

**Acceptance Scenarios**:

1. **Given** the user is logged in with a valid browser session, **When** they navigate to `/en/projects`, **Then** the projects list renders with the user's projects and no 401 errors appear in the console.
2. **Given** the user is logged in and on `/en/projects`, **When** the page completes loading, **Then** the browser made zero requests to any `/api/v1/*` path for project data.
3. **Given** an API-key client calls `GET /api/v1/projects` with a valid API key, **When** the request is processed, **Then** it succeeds exactly as before (no regression on the legacy surface).

---

### User Story 2 — Authenticated user can browse core project surfaces (Priority: P2)

Once the project list works, the user expects every screen they can navigate into from a project — project detail, datasets, recordings, detections, annotations, taxa search, audio playback — to also work without 401s. These are the high-traffic surfaces that form the "core loop" of the product.

**Why this priority**: This is where users spend the bulk of their time. Without these, the projects list is a dead end. P2 because the entry point (P1) must be unblocked first, and because these are larger in surface area so should land after the adapter pattern is validated on a smaller PR.

**Independent Test**: From a working `/en/projects`, open a project's detail page, walk through datasets → recordings → detections → annotations → run a taxa search and a mini-spectrogram playback. Each screen must load without 401s and the browser must make zero `/api/v1/*` calls for these surfaces.

**Acceptance Scenarios**:

1. **Given** a project list with at least one project, **When** the user opens a project's detail page, **Then** project metadata, datasets, recordings, and detections all render with no 401s.
2. **Given** a project with detections, **When** the user opens the annotation review screen and exports an annotation, **Then** the export starts successfully with no 401s.
3. **Given** the user is using taxa search (autocomplete + GBIF lookup), **When** they type a query, **Then** results return with no 401s.
4. **Given** the user clicks play on a mini-spectrogram, **When** audio is requested, **Then** playback works with no 401s.

---

### User Story 3 — Administrator can use administrative screens (Priority: P3)

A user with administrative role opens the admin section to manage licenses, recorders, application settings, and user accounts. They expect every admin screen to load and accept mutations.

**Why this priority**: Admin screens are used by a small number of staff users and the project is pre-launch, so admin operations can run in parallel with end-user features being unblocked. They are still required before launch.

**Independent Test**: Log in as an admin (`okamoto.ryotaro@nies.go.jp`), visit each admin screen (`/en/admin/licenses`, `/en/admin/recorders`, `/en/admin/settings`, `/en/admin/users`), and confirm they list data, support edits, and produce no 401s. Browser makes zero `/api/v1/*` calls.

**Acceptance Scenarios**:

1. **Given** an admin user is logged in, **When** they open each admin index screen, **Then** data loads with no 401s.
2. **Given** an admin is on an admin detail screen, **When** they perform a write (create / update / delete) supported by that screen, **Then** the action succeeds with no 401s.

---

### User Story 4 — Unauthenticated visitor can browse public content (Priority: P3)

A guest (no session) visits public `/explore` routes — public project feed, public project detail — and expects them to render. spec/006 introduced the Public visibility tier; the front-end calls into it must use the consolidated browser-facing surface, not the legacy v1 paths.

**Why this priority**: Public content is a launch requirement (the catalog is part of the product's external value), but it is a smaller surface than the authenticated core loop. Can land in parallel with US3.

**Independent Test**: In an incognito browser (no cookies), visit `/explore/projects` and an `/explore/projects/{id}`. Both must render public content with no `/api/v1/*` calls and no 401s.

**Acceptance Scenarios**:

1. **Given** no session, **When** a guest visits `/explore/projects`, **Then** the public project feed renders without 401s.
2. **Given** no session, **When** a guest opens a public project's detail page, **Then** project data renders without 401s.

---

### User Story 5 — Setup wizard remains functional on first-run install (Priority: P4)

A fresh deployment with no users yet runs the setup wizard at `/setup`. The wizard must initialize the first administrator and configure baseline settings before any session exists.

**Why this priority**: This path runs once per deployment and is invisible to end users after the first run, but it must not regress. Lower priority because there is no plausible BFF session during setup (no user exists yet) — the simplest correct outcome is to leave setup on the legacy v1 surface, treated as a documented exception.

**Independent Test**: On a fresh database with no users, visit `/setup`, complete the wizard, and confirm the first user is created and login succeeds afterwards.

**Acceptance Scenarios**:

1. **Given** no users exist, **When** a visitor opens `/setup`, **Then** the setup status loads and the wizard renders.
2. **Given** the wizard is completed, **When** the user logs in afterwards, **Then** login succeeds using the BFF flow.

---

### Edge Cases

- **Mixed-migration window**: a partially-migrated page may still call one legacy endpoint and one new BFF endpoint. The page MUST keep working during the transition — neither surface is removed before its callers are migrated.
- **Cross-tab session refresh**: when the BFF access token expires and is refreshed in one tab, other open tabs that re-issue requests after refresh must not surface a transient 401.
- **403 vs 401 disambiguation**: a migrated endpoint reached without sufficient permission should return 403 (forbidden) rather than 401 (unauthenticated). 401 should be reserved for genuine auth failure so the UI's "auto-logout on 401" behavior is not triggered by permission errors.
- **Permission semantics parity**: a BFF mirror MUST evaluate authorization against the same project/role/permission model as its v1 equivalent — never against the API-key `granted_permissions` model — so that what a user can see and do is identical on both surfaces.
- **Audit log continuity**: actions performed via the BFF mirror must be audited under the user actor type, not the API-key actor type, preserving the actor-type separation spec/006 established.
- **Legacy v1 callers untouched**: programmatic API-key clients calling `/api/v1/*` must continue to receive the same responses, status codes, and rate-limit behavior they receive today — the migration is purely additive on the BFF side.
- **CSRF on BFF mutations**: BFF mutations relying on session cookies must remain CSRF-protected; adding new BFF write endpoints must not skip the project's existing CSRF posture.
- **Out-of-scope endpoints still callable**: `PATCH /api/v1/users/me` and `/api/v1/users/me/api-tokens` remain on the legacy surface (documented exception). The browser UI's calls to these from the account screen must keep working — they are not in this migration's scope but must not regress.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The browser UI MUST be able to fetch the authenticated user's project list and project detail, AND to create / update / delete a project and manage its members, without using any `/api/v1/*` path.
- **FR-002**: The browser UI MUST be able to perform every read and write on dataset, recording, detection, annotation, taxa search, and audio playback surfaces without using any `/api/v1/*` path.
- **FR-003**: The browser UI MUST be able to perform every administrative read and write (licenses, recorders, application settings, user accounts) without using any `/api/v1/*` path.
- **FR-004**: Public/guest `/explore` routes MUST render public content without using any `/api/v1/*` path.
- **FR-005**: The legacy `/api/v1/*` surface MUST remain reachable for clients authenticating with an API key, with identical response shapes, status codes, and rate-limit behavior as before this migration.
- **FR-006**: The legacy `/api/v1/*` surface MUST continue to reject browser-issued BFF tokens — the migration MUST NOT relax that isolation as a shortcut for unmigrated callers.
- **FR-007**: Each migrated endpoint MUST evaluate authorization using the user/project/role/permission model, never against the API-key `granted_permissions` model.
- **FR-008**: Each migrated endpoint MUST emit audit-log entries under the user actor type, preserving the actor-type separation between BFF and API-key surfaces.
- **FR-009**: A migrated endpoint MUST return 403 (not 401) when the authenticated user lacks the required permission, so that the UI does not trigger auto-logout on a permission denial.
- **FR-010**: The migration MUST be deliverable as a series of independent per-resource increments. Each increment MUST leave the system in a working state for both migrated and un-migrated screens.
- **FR-011**: A documented exception list MUST identify any browser-side calls intentionally left on the legacy surface, with the reason for each. Default exceptions: profile-mutation `PATCH /users/me`, `/users/me/api-tokens*`, `/users/me/password`, the setup wizard (`/setup/*`), and the dev-only `/api/v1/test` endpoint.
- **FR-012**: After full migration, an automated audit MUST be able to verify the exception list is exhaustive — i.e. no browser-side code reaches `/api/v1/*` outside of the documented exceptions.
- **FR-013**: The setup wizard MUST continue to function on a fresh install with no users present.
- **FR-014**: During the migration window, a screen that has been partially migrated (some endpoints moved, some not) MUST still render and operate without producing 401-driven auto-logouts.
- **FR-015**: Each per-resource migration MUST be verified end-to-end in a real browser session against the test dataset before being declared done (per the project's Gate 3 policy).

### Key Entities *(none — this is a transport-and-routing migration with no new domain entities)*

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After migration, a logged-in user using the web UI for a typical session (project list → project detail → datasets → recordings → detections → annotations → taxa search → audio playback → logout) triggers zero requests to any `/api/v1/*` path outside the documented exception list.
- **SC-002**: After migration, an authenticated user can complete the same typical session with zero 401 errors visible in the browser console.
- **SC-003**: API-key clients calling `/api/v1/*` see no observable change in response shape, status code, or rate-limit behavior across the migration (regression rate: 0).
- **SC-004**: The exception list documenting browser-side calls that intentionally remain on `/api/v1/*` contains no more than five distinct endpoint groups, and each entry includes a one-sentence reason.
- **SC-005**: For every migrated endpoint, browser smoke evidence is recorded (URL visited, screen confirmed to render, console error count) before the corresponding change is merged.
- **SC-006**: The migration ships as multiple reviewable increments; no single merged change touches more than one logical resource family (e.g. "projects", "datasets", "admin/licenses").
- **SC-007**: Authorization decisions for any migrated endpoint match the user's project/role/permission state — verified by a permission-matrix test pass — and never depend on API-key `granted_permissions`.
- **SC-008**: The `test@echoroo.app` account completes Gate 3 manual smoke on the migrated surfaces without any "auto-logout on permission denial" regressions (permission denials surface as 403, not 401).

## Assumptions

- Per-resource incremental delivery is preferred over a single large merge, to keep diffs reviewable and Gate 3 browser smoke tractable. (Aligns with the 2026-05-12 Codex consultation captured in the original stub.)
- Adding a BFF mirror means writing a thin adapter under the BFF API surface that reuses the existing service-layer logic but resolves authorization through the user/project/permission model. It does NOT mean copy-pasting business logic.
- Public/guest `/explore` calls migrate to the BFF surface using anonymous (no-session-required) variants, so that the entire browser-facing transport is consolidated. If during planning this turns out to be substantially more expensive than expected, the team may consider keeping `/explore/*` on a small subset of unauthenticated `/api/v1/*` endpoints and treating them as a documented exception.
- The setup wizard (`/setup/*`) remains on the legacy surface as a documented exception because no user/session exists during first-run installation.
- Profile-mutation endpoints (`PATCH /users/me`, `/users/me/api-tokens*`, `/users/me/password`) remain on the legacy surface as documented exceptions, consistent with the PR #71 decision.
- The dev-only `/api/v1/test` endpoint remains on the legacy surface and is treated as out of scope.
- The migration ships before any external users are onboarded (project is pre-launch). No data migration or compatibility shim is required for existing browser clients.

## Out of Scope

- Removing or restructuring the legacy `/api/v1/*` surface itself. That surface continues to serve API-key clients unchanged.
- Profile-mutation endpoints (`PATCH /users/me`, `/users/me/api-tokens*`, `/users/me/password`). These intentionally stay on the legacy surface per the PR #71 decision and the original stub.
- The setup wizard. Stays on the legacy surface as a documented exception (no session exists during first-run setup).
- The dev-only `/api/v1/test` endpoint. Test fixture only; not user-facing.
- Any change to the BFF authentication mechanism itself (session cookies, access-token format, refresh flow). Those are owned by spec/006 and only consumed here.
- Any change to the API-key permission model (`granted_permissions`). Out of scope by definition — the migration's whole point is to keep the two surfaces isolated.

## Appendix A — Endpoint Inventory (snapshot 2026-05-12, main HEAD `b8d522b5`)

> **⚠️ Snapshot — superseded in part by `research.md` D-3 / D-9 (2026-05-13).** In particular, `/api/v1/projects/feed` is NOT a live endpoint (only a negative-test fixture at `apps/web/src/lib/api/__tests__/client.permissions.test.ts:70`) and is removed from the "mirrors to add" list. The "Existing BFF mirrors" line is also incomplete — projects reads (list / detail / recordings) are already on BFF, while members listing and overview were missing at the time of the snapshot and are added in PR A2. See `research.md` D-3 for the resolved inventory.

Recorded for traceability into the planning phase. May be re-run against current main before planning starts.

Audit command:

```bash
grep -rohE '/api/v1/[a-zA-Z0-9/_${}-]+' apps/web/src/ | sed 's/[${}].*//' | sort -u
```

Endpoints called from the browser today (28 unique paths, 80 raw hits, 28 frontend files):

```
/api/v1/admin/licenses                /api/v1/auth/refresh
/api/v1/admin/licenses/{id}           /api/v1/auth/register
/api/v1/admin/recorders               /api/v1/auth/verify-email
/api/v1/admin/recorders/{id}          /api/v1/auth/verify-email/resend
/api/v1/admin/settings                /api/v1/projects
/api/v1/admin/users                   /api/v1/projects/{id}
/api/v1/admin/users/{id}              /api/v1/projects/feed
/api/v1/auth/login                    /api/v1/setup/initialize
/api/v1/auth/logout                   /api/v1/setup/status
/api/v1/auth/password-reset/confirm   /api/v1/taxa/gbif-search
/api/v1/auth/password-reset/request   /api/v1/taxa/search
/api/v1/test                          /api/v1/users/me
                                      /api/v1/users/me/api-tokens
                                      /api/v1/users/me/api-tokens/{id}
                                      /api/v1/users/me/password
```

Frontend files touching `/api/v1/*` (28 files):

```
hooks.server.ts
lib/api/__tests__/client.permissions.test.ts
lib/api/admin.ts
lib/api/auth.ts                       (PARTIAL — PR #71 migrated /me only)
lib/api/client.test.ts
lib/api/client.ts                     (apiClient itself)
lib/api/licenses.ts
lib/api/projects.ts                   ← P1 — breaks /en/projects
lib/api/query-client.ts
lib/api/recorders.ts
lib/api/setup.ts
lib/api/taxa.ts
lib/api/tokens.ts
lib/api/users.ts                      (PARTIAL — PR #71)
lib/api/web-auth.ts
lib/components/annotation/AnnotationExportDialog.svelte
lib/components/annotation/ExportDialog.svelte
lib/components/common/MiniSpectrogram.svelte
lib/components/data/ExportDialog.svelte
lib/stores/auth.svelte.ts             (PARTIAL — PR #71)
lib/types/detection.ts
lib/types/index.ts
lib/utils/audioPlayback.svelte.ts
routes/(app)/projects/[id]/annotations/[annotationProjectId]/+page.svelte
routes/(public)/explore/projects/[id]/+page.svelte
routes/+layout.svelte
routes/setup/+page.server.ts
```

Existing BFF mirrors (no work needed beyond rewiring the front-end):
`auth/*`, `projects/{id}/*`, `admin/superusers/*`, `account/dsr/*`, `users/me` (PR #71).

Mirrors that need to be added (high priority):
`projects` list + `projects/feed`, `admin/licenses`, `admin/recorders`, `admin/settings`, `admin/users`, `taxa/*`, `setup/*` (if the wizard exception is dropped during planning), some `auth/*` flows (`register`, `verify-email*`, `password-reset/*`) if still on legacy.

## Related

- PR #70 — spec/007 permission test coverage. The work that surfaced this regression during manual Gate 3 smoke.
- PR #71 — partial fix for `/users/me`. Establishes the per-resource adapter pattern this spec scales out.
- spec/006 — original BFF migration. Declared "login flow 実機完走" without enumerating all `/api/v1/*` browser callers; this spec closes that gap.
- spec/007 — permission test coverage that produced the Gate 3 evidence.
