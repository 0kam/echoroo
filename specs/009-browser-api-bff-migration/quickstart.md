# Quickstart — Per-Resource BFF Migration Gate 3 Smoke

**Date**: 2026-05-12
**Spec**: [spec.md](spec.md)
**Plan**: [plan.md](plan.md)

Every per-resource PR in this migration ships with a Gate 3 browser smoke. This file is the **recipe** each PR follows so the gate is consistent across PRs A–J. Per-PR evidence (URL visited, screen confirmed, console error count) is recorded in the PR description, not in this directory.

---

## Prerequisites (once per session)

1. Start the dev stack:
   ```bash
   ./scripts/docker.sh dev
   ```
2. Wait for `echoroo-frontend` and `echoroo-backend` to become healthy. Sanity-check:
   ```bash
   docker logs echoroo-backend --tail 30
   docker logs echoroo-frontend --tail 30
   ```
3. Open the frontend in a real browser at the forwarded local port (default `http://localhost:3000`).
4. Have the test account (`test@echoroo.app`) credentials at hand (see `memory/test-accounts.md`). Use an admin account (`okamoto.ryotaro@nies.go.jp`) for admin-screen PRs (E–H).

---

## Gate 1 — Static checks (before opening a browser)

Run from repo root. These are mandatory for every per-resource PR before Gate 3 is attempted:

```bash
# Backend
(cd apps/api && uv run ruff check . && uv run mypy .)

# Frontend
(cd apps/web && npm run check)
```

Expected: all three commands exit 0. Any failure → fix before continuing.

---

## Gate 2 — Automated tests

Run the targeted slices that cover the migrated resource. Examples:

```bash
# Backend integration tests for the new BFF adapter (PRs that add one)
(cd apps/api && uv run pytest tests/integration/api/web_v1/ -q)

# OpenAPI diff contract test — gates both surfaces
(cd apps/api && uv run pytest tests/contract/test_openapi_diff.py -q)

# Frontend unit tests
(cd apps/web && npm run test -- --run lib/api)
```

Expected: all green. Any red → fix before continuing.

---

## Gate 3 — Browser smoke (mandatory, MCP-driven)

Per `CLAUDE.md` Gate 3, every PR in this sequence MUST be exercised in a real browser using Playwright MCP tools. The pattern is the same for every PR; only the page-under-test changes.

### Generic recipe

```text
1. browser_navigate         → target URL for the migrated screen
2. browser_snapshot         → confirm the page rendered (not stuck on "Loading...")
3. browser_console_messages → MUST show 0 red errors and 0 new 401s
4. browser_network_requests → spot-check the screen's calls; confirm zero hits on
                              /api/v1/* outside the documented exception list
5. Exercise the feature (click / type / submit) using browser_click / browser_type
                              → confirm the action completes without surfacing a 401
6. Record evidence in the PR description: URL, snapshot summary, console error
                              count, network sample
```

### Per-PR test targets

> **Important — Gate 3 network filter is scoped per PR.** Until PR J ships, "zero `/api/v1/*` calls" applies only to the *resource family this PR migrates*. Other resources may still hit legacy paths until their own PR lands. Frame each Gate 3 evidence note accordingly.

| PR | URL to smoke | Test user | What to exercise | Allowed network state |
|----|--------------|-----------|------------------|------------------------|
| **A — projects read subset** | `/en/projects` then a `/en/projects/{id}` detail page | `test@echoroo.app` | Page renders with the user's projects; open one project; confirm list + detail + recordings list load via BFF. Sidebar members list and overview tile may still call legacy paths in this PR — that is expected (they migrate in A2). | `GET /web-api/v1/projects` and `GET /web-api/v1/projects/{id}` and the recordings read MUST be on BFF. `GET /api/v1/projects/{id}/members` and `GET /api/v1/projects/{id}/overview` are **tolerated** in this PR (they remain on legacy until A2). Mutations also still tolerated (migrate in A2). |
| **A2 — projects mutations + missing reads** | `/en/projects/new` (create); a project's settings page (update); delete from detail; member add / edit / remove dialogs; reload detail and confirm members + overview load via BFF | `test@echoroo.app` (must own a project) | Create a new project; rename it; add a member; change that member's role; remove them; delete the project. Reload a project detail and confirm members list + overview tile both load from BFF. All actions succeed with no 401. Confirm audit log entries are tagged `actor_kind=session` (check via the API or DB). | After this PR, `apps/web/src/lib/api/projects.ts` has **zero** `/api/v1/projects*` calls. PR A's read migrations also remain on BFF. |
| **B — auth follow-up** | `/en/register`, `/en/verify-email`, `/en/forgot-password` flows | new throwaway email | Register a fresh account end-to-end (uses real outbox locally); resend verify email; request password reset. No 401s. | `apps/web/src/lib/api/auth.ts`: zero `/api/v1/auth/*` calls (except documented exceptions, of which there are none for auth). |
| **C — taxa** | A project's taxa search page (and any tag autocomplete in the annotation flow) | `test@echoroo.app` | Type a partial Latin name and a partial Japanese name; both autocompletes return results without 401. | `apps/web/src/lib/api/taxa.ts`: zero `/api/v1/taxa/*` calls. |
| **D — exports + audio playback** | Annotation review screen; data export dialog; mini-spectrogram | `test@echoroo.app` | Start an annotation export; start a data export; press play on a mini-spectrogram. All succeed without 401. **Verify audio Range seeking works** (drag spectrogram cursor mid-playback). | Inline fetches in `AnnotationExportDialog.svelte`, `ExportDialog.svelte` (annotation + data), `audioPlayback.svelte.ts`, `MiniSpectrogram.svelte`: zero `/api/v1/*` calls. |
| **E — admin/licenses** | `/en/admin/licenses` | `okamoto.ryotaro@nies.go.jp` | List, create, edit, delete a license. | `lib/api/licenses.ts` + `lib/api/admin.ts` license calls: zero `/api/v1/admin/licenses*` hits. |
| **F — admin/recorders** | `/en/admin/recorders` | admin | List, create, edit, delete a recorder. | `lib/api/recorders.ts`: zero `/api/v1/admin/recorders*` hits. |
| **G — admin/settings** | `/en/admin/settings` | admin | Read settings; toggle one and persist. | `lib/api/admin.ts` settings calls: zero `/api/v1/admin/settings*` hits. |
| **H — admin/users** | `/en/admin/users` | admin | List, edit role, deactivate. | `lib/api/admin.ts` user calls: zero `/api/v1/admin/users*` hits. |
| **I — guest/`/explore` polish** | `/explore/projects` and `/explore/projects/{id}` in an incognito session | _(none — guest)_ | Public list and detail render without auth. Confirm `<audio>` / `<img>` src URLs do not include `/api/v1/*`. | Public surfaces: zero `/api/v1/*` calls. `/projects/feed` is NOT a live endpoint — do not look for it. |
| **J — CI guard + cleanup + BFF parity test** | _(no new screen)_ | — | Smoke a complete authenticated walkthrough (`/en/projects` → project detail → datasets → annotations → admin once) and confirm zero `/api/v1/*` calls outside the exception list. This is the SC-001 evidence. | Repo-wide: only the 5 documented exception groups may appear on the browser network log. |

### Documented exceptions (network filter)

When inspecting `browser_network_requests` for Gate 3, the following `/api/v1/*` hits are expected and must be tolerated:

- `PATCH /api/v1/users/me`
- `GET|POST|PATCH|DELETE /api/v1/users/me/api-tokens[/{id}]`
- `PUT /api/v1/users/me/password`
- `GET|POST /api/v1/setup/{status,initialize}`
- `GET /api/v1/test`

For PRs A–I, additional `/api/v1/*` hits to **resources outside this PR's scope** are tolerated as well (they migrate in their own PR). For PR J, only the 5 exception groups above may appear repo-wide. Any other `/api/v1/*` hit on the browser is a regression — fail Gate 3 and fix.

### Per-PR static legacy-call guard (mandatory)

Before opening any PR in this sequence, run the following from repo root and confirm it returns zero results outside this PR's scope:

```bash
# Replace <resource> with the migration target (e.g. projects, taxa, admin/licenses).
rg -n "/api/v1/<resource>" apps/web/src/ \
  --glob '!**/__tests__/**' \
  --glob '!**/lib/types/**'
```

Exclusions in the command above:

- `**/__tests__/**` — `lib/api/__tests__/client.permissions.test.ts:70` contains an intentional `/api/v1/projects/feed` negative-test fixture for the URL-extractor. Keep it.
- `**/lib/types/**` — type-only references (no runtime call) are not migration targets; PR J audits these separately.

Hits outside these excluded paths must be migrated by the current PR (or be one of the 5 documented exceptions). PR J then runs the repo-wide variant (no `<resource>` filter) as the final lock.

---

## Gate 4 — Completion report template

Each PR's description MUST include the Gate-4 block (from `CLAUDE.md`):

```text
## 完了報告
- Changed files: [list]
- Gate 1 (static): ✅/❌ [npm run check + ruff + mypy details]
- Gate 2 (automated tests): ✅/❌ [pytest + vitest details]
- Gate 3 (browser smoke): ✅/❌ [URL + snapshot summary + network sample]
- Gate 4 (console errors): ✅ 0 / ❌ [error contents]
```

---

## Pre-PR-D audit checklist (audio / Range / streaming)

Before opening PR D, walk through the D-10 checklist in [research.md](research.md). Recap:

1. `<audio src="…">` cookie auth on `/web-api/v1/projects/{id}/recordings/...`
2. `Range:` header propagation (206 partial-content for spectrogram seeking)
3. Signed-URL paths (if the legacy v1 surface returns redirects to presigned S3 URLs, confirm BFF equivalent)
4. Streaming export response shape (token-refresh mid-flight does not corrupt the response)
5. Vite proxy MIME types in dev for `/web-api/v1/projects/{id}/recordings/*`

Each item is a checkbox in the PR D description. If any item surfaces a gap, split the gap-fix into a backend prerequisite PR (variant of PR D), the same way PR A→A2 is split for projects mutations.

## Local debug helpers

If a Gate 3 reveals a 401, the fastest diagnostic chain is:

1. **Check the call path**: `browser_network_requests` and confirm whether the call is on `/web-api/v1/...` or still `/api/v1/...`. If the latter, the frontend rewire is incomplete.
2. **Check the auth path**: `docker logs echoroo-backend --tail 100` — look for `"API key invalid or revoked"`. That string confirms a BFF Bearer token hit the legacy `/api/v1/*` surface.
3. **Check the permission path**: if the call is correctly on `/web-api/v1/...` but returns 401 instead of 403, the new BFF adapter is reframing a permission denial — fix it to propagate 403.
4. **Check the CSRF path**: a 403 on a BFF mutation without an `X-CSRF-Token` header means the frontend wrapper missed the `callWebApi()` helper. Confirm the request includes `X-CSRF-Token`.

---

## What this file is NOT

- A test plan. The per-PR test plan lives in each PR's description.
- A runbook for production. This is a local-dev quickstart only.
- A spec for the migration itself. That lives in [spec.md](spec.md).
