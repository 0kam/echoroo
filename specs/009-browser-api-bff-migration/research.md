# Phase 0 Research — Browser API → BFF Migration

**Date**: 2026-05-12
**Spec**: [spec.md](spec.md)
**Plan**: [plan.md](plan.md)

This document records the design decisions taken to remove every `NEEDS CLARIFICATION` from the plan's Technical Context, and to fix the per-resource sequencing on solid ground. All findings come from a 2026-05-12 codebase audit (main HEAD `b8d522b5`, branch `009-browser-api-bff-migration`) plus the 2026-05-12 Codex consultation captured in the original spec/009 stub.

---

## D-1. Auth dependency: BFF accepts both cookie session and Bearer JWT through the SAME `CurrentUser`

**Decision**: Use the existing `CurrentUser = Annotated[User, Depends(get_current_user)]` dependency (`apps/api/echoroo/middleware/auth.py:324`) for every new BFF adapter. No new dependency is required.

**Rationale**:
- `get_current_user` (lines 96+) resolves the current user via a documented priority chain: (1) `request.state.principal` populated by `AuthRouterMiddleware`, (2) Bearer JWT, (3) Bearer API-token (legacy `ecr_*`).
- The principal fast-path (lines 160–175) accepts both first-party cookie sessions and Bearer callers; the middleware does the schema discrimination so handlers stay uniform.
- Legacy `/api/v1/*` still routes through the same dependency, but `AuthRouterMiddleware` (`auth_router.py:504`) rejects BFF JWTs with the exact string `"API key invalid or revoked"` mentioned in the spec — confirming the two surfaces remain mutually rejecting by design (preserves the actor-type isolation spec/006 established).

**Alternatives considered**:
- Wrapping a `BffCurrentUser` dedicated dependency. Rejected — would duplicate resolution logic and risk drift; the existing dependency already discriminates correctly.
- Loosening legacy `/api/v1/*` to accept BFF JWTs. Rejected upstream (Codex 2026-05-12) — would dissolve the actor-type / audit / rate-limit isolation.

---

## D-2. Adapter pattern (template = PR #71's `web_v1/users/me`)

**Decision**: New BFF handlers are thin route declarations that delegate to existing service-layer functions. No business logic is duplicated.

**Rationale**:
- PR #71's `web_v1/users.py:54` is the minimal-shape reference: declare route → take `CurrentUser` dependency → return Pydantic schema model_validated against the result. Use this whenever the result is a simple projection of the authenticated user or a single record.
- For list / detail endpoints reuse a shared helper from `apps/api/echoroo/services/`, exactly as `web_v1/projects/_core.py:255` does with `build_project_summaries(db, projects)`.
- Authorization MUST be evaluated via the user/project/permission model (`gate_action` from spec/007), never against API-key `granted_permissions`.

**Alternatives considered**:
- Re-implementing route handlers entirely. Rejected — defeats the migration's clean-architecture goal and risks permission-semantics drift.
- Calling the legacy v1 handler internally from the BFF handler. Rejected — would couple the two routers; the service layer is the correct seam.

### D-2a. Adapter acceptance criteria for actor / audit / rate-limit isolation

`CurrentUser` is the same dependency on both surfaces, but the spec/006 isolation it must preserve runs at a different layer (middleware + audit + rate-limit). Each new BFF adapter PR MUST verify the following, with explicit assertions in its integration tests:

1. **Audit actor_kind = `session`** — the audit-log row emitted by the migrated action records `actor_kind` as the user/session actor type, not as `api_key`. Mirror the assertion pattern used in `apps/api/tests/integration/api/web_v1/test_auth.py` style fixtures.
2. **Rate-limit bucket = web surface** — the action increments the BFF rate-limit bucket, not the API-key bucket. If the resource is unauthenticated (e.g. guest reads on `web_v1/projects`), confirm it lands in the anonymous-web bucket.
3. **API-key callers do not cross into BFF** — a request to `/web-api/v1/<resource>` carrying an `Authorization: Bearer echoroo_<...>` (legacy API-key shape) MUST be rejected at the BFF middleware layer (the existing `AuthRouter` already routes by prefix; the test pins this behavior). Likewise a session-cookie-only request to `/api/v1/<resource>` MUST be rejected by the legacy `AuthRouter` with the documented `"API key invalid or revoked"` 401.
4. **403, not 401, on permission denial** — `gate_action` must propagate its 403 unchanged. The BFF adapter MUST NOT reframe a 403 as a 401 (which would trigger the frontend's auto-logout interceptor).
5. **CSRF on every BFF mutation** — POST / PATCH / DELETE handlers require the `X-CSRF-Token` header; the integration test asserts a 403 on a mutation submitted without it.

These five points are the migration's actor-type / audit / rate-limit isolation contract. They are NOT optional and are not implicit in the use of `CurrentUser` alone.

---

## D-3. Which BFF mirrors already exist (audit snapshot 2026-05-12; reconfirmed 2026-05-13)

**Decision**: Treat the migration as **mostly frontend-rewiring for the high-priority resources**. New BFF adapters are only required for a small set.

**Findings** (from `apps/api/echoroo/api/web_v1/`):

| Surface | BFF mirror exists? | Notes |
|---------|-------------------|-------|
| `auth/login, /logout, /register, /refresh, /verify-email[/resend], /password-reset/{request,confirm}, /2fa/*` | ✅ yes | All auth flows mirrored. Frontend rewiring only. |
| `users/me` (GET) | ✅ yes | PR #71. |
| `users/me` (PATCH), `users/me/api-tokens`, `users/me/password` | — | **Documented exception** — stays on legacy. |
| `projects/` — **GET** list, detail, recordings | ✅ yes | `web_v1/projects/_core.py:132/307/424`. Frontend rewiring only. PR A's scope. |
| `projects/` — **GET** members listing, overview | ❌ no | `web_v1/projects/_members.py` exposes only invitation accept (`POST /{project_id}/invitations/{token}/accept`) and recipient decline (`DELETE /{project_id}/invitations/{token}`), NOT a member-listing GET. `GET /{project_id}/overview` is absent on BFF entirely. **PR A2** adds both. |
| `projects/` — **POST/PATCH/DELETE** create, update, delete, member CRUD | ❌ no | Only present on legacy `apps/api/echoroo/api/v1/projects.py`. **PR A2** adds these to BFF. |
| `projects/feed` | — **does not exist** | 2026-05-13 grep: no live endpoint on either surface. The only reference in the codebase is `apps/web/src/lib/api/__tests__/client.permissions.test.ts:70`, where `/api/v1/projects/feed` is an intentional negative-test fixture for the "non-UUID segment rejected" code path. **Phase 0 close** — see D-9. |
| `taxa/search`, `taxa/gbif-search` | ❌ no | **Needs new BFF mirror.** |
| `admin/licenses[/{id}]` | ❌ no (existing `web_v1/admin.py` covers superusers/approvals/2FA/IP allowlist only) | **Needs new BFF mirror.** |
| `admin/recorders[/{id}]` | ❌ no | **Needs new BFF mirror.** |
| `admin/settings` | ❌ no | **Needs new BFF mirror.** |
| `admin/users[/{id}]` | ❌ no | **Needs new BFF mirror.** |
| `setup/status`, `setup/initialize` | — | **Documented exception** — no session during first-run install. |
| `/api/v1/test` | — | **Documented exception** — dev only. |
| `account/dsr/*`, `audit/*` | ✅ yes | Already BFF-only — out of this migration. |

**Implication for sequencing**: PR A (projects **reads**) and PR B (auth follow-up) are **frontend-only**. PR A2 (projects **mutations**) is the first "new BFF adapter" PR, immediately following A, and establishes the CSRF / audit `actor_kind=session` / 403-not-401 / rate-limit-bucket pattern that PRs C–H will copy.

---

## D-4. Frontend rewire mechanism: `apiClient.get('/web-api/v1/...')` + `callWebApi()` helper

**Decision**: Reuse the existing `apiClient` (`apps/web/src/lib/api/client.ts`). For mutating verbs on the BFF surface, use the existing `callWebApi()` helper in `lib/api/projects.ts` (or extract it to `lib/api/client.ts` if reused outside projects).

**Rationale**:
- `apiClient` already handles both surfaces uniformly: attaches Bearer header when `accessToken` is present; supports `credentials: 'include'` for cookie session; has built-in retry-on-401-without-Bearer for Guest-readable paths.
- The PR #71 shape is the migration template: `apiClient.get<User>('/web-api/v1/users/me')` for reads; mutations on the BFF use a CSRF-aware path. `lib/api/projects.ts` defines `callWebApi()` (~lines 67–102) that extracts the `echoroo_csrf` cookie and injects `X-CSRF-Token`.
- The TanStack query-client (`lib/api/query-client.ts`) already URL-pattern-matches both surfaces (the `PROJECT_ID_URL_RE` regex matches both `/api/v1/projects/{id}` and `/web-api/v1/projects/{id}`), so no query-key changes are required.

**Alternatives considered**:
- A new `bffClient` parallel to `apiClient`. Rejected — `apiClient` already does the right thing; duplication would create two truths.
- Generating a new typed BFF client from the OpenAPI contract. Rejected for this migration's scope — the existing apiClient + manual function signatures match the project's idiom; type generation is a separate concern that could be picked up later.

---

## D-5. Contract testing strategy: existing OpenAPI diff test + a new BFF-parity guard test

**Decision**: Keep the existing `apps/api/tests/contract/test_openapi_diff.py` as the per-resource contract gate, BUT add a small spec/009-specific guard test (delivered in PR J) that closes its known limitation.

**Rationale**:
- The existing test declares `_API_MOUNT_PREFIXES = ("/web-api/v1", "/api/v1")` and walks both surfaces. **However**, it normalises both mount prefixes to a single prefix-stripped path and shallow-merges entries with `setdefault` (`test_openapi_diff.py:220`). Effect: a method present on **one** surface and missing on the other passes the test silently. The test catches "missing from both surfaces" and "missing from contract", but does NOT catch "declared on legacy, missing on BFF".
- Therefore, for resources that need BFF parity (projects mutations in PR A2, taxa in PR C, admin/* in PRs E–H), each PR's integration test asserts the BFF path directly responds (e.g. `200` for `GET /web-api/v1/<resource>`, `403` without CSRF, etc.).
- PR J then adds a single contract-level guard test that enumerates every `/web-api/v1/<resource>` path declared by spec/009 (drawn from a small allowlist in the test) and asserts each path is in the live OpenAPI surface. This locks the migration's BFF additions in place.
- The contract YAMLs themselves live at `specs/006-permissions-redesign/contracts/` (NOT `apps/api/contracts/` — earlier docs in this directory were incorrect). 2026-05-13 verification: `specs/006-permissions-redesign/contracts/` contains `README.md`, `account.yaml`, `admin.yaml`, `audit.yaml`, `auth.yaml`, `detections.yaml`, `projects.yaml`, `trusted.yaml`. New paths for taxa and admin sub-resources should be added to the appropriate existing YAML (admin.yaml is the likely home for licenses / recorders / settings / users); if no suitable home exists for taxa, a new `taxa.yaml` is added under the same directory.

**Alternatives considered**:
- A separate BFF contract suite. Rejected — single-source-of-truth contract YAMLs remain simpler.
- Modifying `test_openapi_diff.py` to enforce parity directly. Considered but deferred — the test is shared with spec/006 and changing its semantics is out of scope. A narrow guard test is safer.

---

## D-6. Per-resource PR sequence (rationale)

**Decision**: Ship in the order PR A → B → C → D → E–H (parallelizable, up to 2 worktrees) → I → J. See plan.md "Migration sequence" table.

**Rationale**:
- US1 (P1) is the only confirmed-broken entry point. PR A (projects, frontend-only) must land first to restore `/en/projects`.
- PR B (auth follow-up, frontend-only) is a foundation: residual `/api/v1/auth/*` calls (register / verify-email / password-reset) must move off legacy before they break in the wild for first-time signups. Small diff, ships next.
- PR C (taxa) is the first new BFF adapter — small surface, validates the adapter pattern before applying it to the four admin resources.
- PR D (annotation export / data export / audio playback components) batches three component-level rewires that all rely on already-BFF-served paths under `web_v1/projects/{id}/*`.
- PR E–H (admin/{licenses,recorders,settings,users}) all follow the PR C template. Each is small, independent, and parallelizable with worktree isolation (memory: max 2 parallel SSAs to avoid the 2 prior git accidents).
- PR I is reframed as "guest/`/explore` polish": public routes already hit `/web-api/v1/projects[/{id}]` per the 2026-05-13 grep, so this PR is a confirmation + residual-legacy-reference cleanup (especially `<audio>` / `<img>` URLs on public detail pages), not a new-adapter PR.
- PR J (CI guard + leftover audit) locks the migration: a new CI step grep-fails on `/api/v1/*` string literals in `apps/web/src/` outside an explicit allowlist file.

**Alternatives considered**:
- Single big-bang PR. Rejected — review burden + Gate 3 browser-smoke burden grow combinatorially; one bad gate blocks the entire migration.
- Backend-first then frontend-second batches. Rejected — leaves the browser broken longer; the user-visible regression is the urgent driver.

---

## D-7. Migration window safety (no auto-logout regressions)

**Decision**: A migrated BFF endpoint MUST return 403 (not 401) for permission denials, so the frontend's "401 → auto-logout" interceptor in `apiClient` does not trigger on a legitimate permission error.

**Rationale**:
- spec FR-009 + edge case "403 vs 401 disambiguation".
- The `gate_action` permission middleware established by spec/007 already returns 403 on RBAC denial.
- Every new BFF adapter MUST call `gate_action` and propagate its HTTP status unchanged (never reframe 403 as 401).

**Alternatives considered**:
- Updating the frontend to ignore 401 from select paths. Rejected — fragile and against the spec's "preserve actor-type isolation" goal.

---

## D-8. Exception list (final form)

**Decision**: Five documented exceptions, codified in plan.md and enforced by PR J's CI guard:

1. `PATCH /api/v1/users/me` (profile mutation)
2. `/api/v1/users/me/api-tokens[/{id}]` (API-token management UI)
3. `PUT /api/v1/users/me/password` (password change)
4. `/api/v1/setup/{status,initialize}` (first-run install — no session exists)
5. `/api/v1/test` (dev-only fixture; not user-facing)

**Rationale**: Satisfies spec FR-011 + SC-004 (≤ 5 endpoint groups). All five have explicit one-sentence reasons in the spec's "Out of Scope" section.

---

## D-9. `projects/feed` — RESOLVED (does not exist)

**Resolution (2026-05-13)**: `/api/v1/projects/feed` and `/web-api/v1/projects/feed` are not live endpoints. `rg /projects/feed` against the repo returns hits **only** in `apps/web/src/lib/api/__tests__/client.permissions.test.ts:70`, where it is used as an intentional negative-test fixture asserting that the URL-to-`projectId` extractor rejects non-UUID path segments. The earlier spec inventory's listing of `/api/v1/projects/feed` was a grep false-positive on this test fixture, not a live caller.

**Consequence for the PR sequence**:
- PR I is reframed from "add `projects/feed` BFF mirror" to "guest/`/explore` polish" — confirm public routes already hit `/web-api/v1/projects[/  {id}]` (true per the 2026-05-13 grep) and remove any residual legacy references, including a check that `<audio>` / `<img>` URLs on the public detail page do not embed `/api/v1/*` paths.
- The negative-test fixture in `client.permissions.test.ts:70` MUST be kept (it gates the URL-extractor's safety against non-UUID segments). Audit task in PR J does not flag it.

## D-10. Pre-PR audit checklist for PR D (audio / export / streaming)

**Decision**: Before opening PR D, run a small audit to confirm `<audio>` cookie auth, Range header propagation, signed URL paths, and streaming behavior on the existing BFF project-scoped paths. Failing any item triggers an additional backend adapter ticket that ships in PR D's PR or as a separate prerequisite PR.

**Items**:
1. **`<audio src="…">` cookie auth** — confirm the browser sends the BFF session cookie when fetching audio via `<audio src>` from `/web-api/v1/projects/{id}/recordings/{rid}/...` (HTML media elements do not attach Authorization headers; cookie auth is the only viable mechanism). If cookie auth is rejected at the BFF middleware for media routes, PR D needs a backend follow-up.
2. **Range header** — confirm BFF media routes propagate the browser's `Range:` header to the storage backend; partial-content (206) responses must work for spectrogram seeking.
3. **Signed URL paths** — if the legacy v1 surface uses time-bounded signed URLs (e.g. presigned S3 URLs returned through a redirect), confirm the BFF equivalent exists or design one. Cookie auth alone is insufficient for cross-origin signed S3 URLs.
4. **Streaming export** — `ExportDialog`-style endpoints may use chunked transfer or background-job poll patterns. Confirm the BFF equivalent supports the same response shape; a streaming response that breaks mid-flight on token refresh would surface as a partial export.
5. **CORS / proxy** — confirm Vite proxy mappings for `/web-api/v1/projects/{id}/recordings/...` carry through audio MIME types correctly in dev.

The audit's results are recorded in PR D's description; missing items are turned into a backend prerequisite PR (variant of PR D split off, similar to A→A2).

---

## Summary

All NEEDS CLARIFICATION items from the plan's Technical Context resolved:

- Auth dependency → shared `CurrentUser` with explicit actor / audit / rate-limit acceptance criteria per adapter (D-1, D-2a)
- Adapter pattern → PR #71 template + service-layer reuse (D-2)
- Where work is needed → projects mutations (PR A2) + 4 admin resources + taxa (D-3)
- Frontend rewire mechanism → existing `apiClient` + `callWebApi` (D-4)
- Contract testing → existing OpenAPI diff test + new BFF-parity guard test in PR J; YAMLs live at `specs/006-permissions-redesign/contracts/` (D-5)
- Sequence → A → A2 → B → C → D → E–H parallel → I → J (D-6)
- 401 vs 403 → 403 for permission denial (D-7)
- Exception list → 5 endpoint groups; per-PR guard required (D-8)
- `projects/feed` → does not exist, PR I reframed (D-9)
- PR D pre-audit → 5-item checklist (D-10)

No outstanding clarifications. Plan Constitution Check stays PASS. Ready for Phase 1 follow-ups and `/speckit-tasks`.
