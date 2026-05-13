# Contracts — spec/009 Browser API → BFF Migration

**Date**: 2026-05-12 (initial) · 2026-05-13 (corrected)
**Spec**: [../spec.md](../spec.md)
**Plan**: [../plan.md](../plan.md)
**Phase 0 decisions**: [../research.md#d-5](../research.md)

## Why this directory is mostly a pointer

This feature does not introduce a new contract format or a new validation framework. Echoroo already gates both HTTP surfaces (`/api/v1/*` and `/web-api/v1/*`) through a single OpenAPI diff contract test, BUT that test has a known limitation that this migration must compensate for.

- **Test**: `apps/api/tests/contract/test_openapi_diff.py`
- **Mount prefixes covered**: `_API_MOUNT_PREFIXES = ("/web-api/v1", "/api/v1")` (line 78)
- **Source-of-truth contract YAMLs**: `specs/006-permissions-redesign/contracts/` — current contents: `README.md`, `account.yaml`, `admin.yaml`, `audit.yaml`, `auth.yaml`, `detections.yaml`, `projects.yaml`, `trusted.yaml` (verified 2026-05-13)

> ⚠️ **Correction from the 2026-05-12 draft of this README**: the earlier text claimed the YAMLs lived under `apps/api/contracts/<resource>.yaml`. That directory does not exist. The actual location is `specs/006-permissions-redesign/contracts/`. Any new BFF paths added by this migration update those existing YAMLs (in particular `projects.yaml` for PR A2 and `admin.yaml` for PRs E–H).

## Known limitation of the existing diff test

`test_openapi_diff.py` walks both mount prefixes, normalises each path by stripping its mount prefix, and shallow-merges the resulting entries using `dict.setdefault` (around line 220). The practical consequences are:

- The test catches "endpoint missing from the contract" and "endpoint missing from BOTH live surfaces".
- The test does NOT catch "endpoint declared on `/api/v1` but missing on `/web-api/v1`" (or vice versa). The first surface that gets normalised wins; the second is dropped silently.

This is why each per-resource PR adds its own integration test that hits the BFF path directly, and PR J adds a contract-level guard test (see below) that enumerates every BFF path declared by this migration and asserts it is in the live OpenAPI surface.

## YAML paths vs live OpenAPI paths

The existing contract YAMLs at `specs/006-permissions-redesign/contracts/` use **prefix-less path keys**. The `/api/v1` and `/web-api/v1` mount prefixes are declared in each YAML's top-level `servers:` block, and `test_openapi_diff.py` normalises both live mount prefixes back to the prefix-less form before comparing.

**Path parameter naming**: the existing YAMLs use the short form `{id}` for the project identifier (e.g. `/projects/{id}`, `/projects/{id}/members`), NOT `{project_id}`. When adding new paths under `projects.yaml`, follow the existing `{id}` convention so the file stays internally consistent. The same applies to `{license_id}` / `{recorder_id}` / `{user_id}` in `admin.yaml` — match whatever shape the existing entries use. Tasks in `tasks.md` write `{project_id}` for clarity in human-facing prose, but the actual YAML key MUST use the existing short form.

When this README's "New paths added" column below describes a path as `/web-api/v1/projects/...`, that is the **live OpenAPI** form (i.e. what the browser hits). In the YAML you add the path under the prefix-less key (e.g. under `paths: /projects`), and the `servers:` block declares it is reachable on both surfaces. The security block on a path operation discriminates the legacy Bearer surface from the BFF cookie+CSRF surface.

## Per-PR contract changes (planned)

Refined and converted into checkboxed tasks by `/speckit-tasks`. Live-form paths in the table below — translate to prefix-less keys when editing the YAMLs.

| PR | YAML(s) updated | New paths added (live form) | Notes |
|----|-----------------|------------------------------|-------|
| **A — projects read subset (frontend only)** | _(none if already declared)_ | _(none expected)_ | Verify `projects.yaml` declares `/projects` (GET), `/projects/{project_id}` (GET), `/projects/{project_id}/recordings` (GET) on both surfaces. If any is missing on the BFF security block, add it in PR A. |
| **A2 — projects mutations + missing reads** | `projects.yaml` | `/web-api/v1/projects/{project_id}/members` (GET), `/web-api/v1/projects/{project_id}/overview` (GET), `/web-api/v1/projects` (POST), `/web-api/v1/projects/{project_id}` (PATCH, DELETE), `/web-api/v1/projects/{project_id}/members` (POST), `/web-api/v1/projects/{project_id}/members/{user_id}` (PATCH, DELETE) — for entries not yet on the BFF security block | First "new BFF adapter" PR. Mirrors `/api/v1/projects` shapes. CSRF security block (`sessionCookie + csrfToken`) required for mutations. |
| **B — auth follow-up (frontend only)** | `auth.yaml` (likely) | _(usually none — BFF auth paths already declared)_ | Spot-check that register / verify-email / password-reset BFF paths exist on both surfaces in the YAML; add if missing. |
| **C — taxa** | new file: `taxa.yaml` (recommended) — alternatively a sub-block under `admin.yaml` if the team prefers fewer files | `/web-api/v1/taxa/search`, `/web-api/v1/taxa/gbif-search` (and the parallel `/api/v1` mounts) | First new-resource YAML in this migration. Response shapes mirror `/api/v1/taxa/*`. |
| **D — annotation/data export + audio playback** | `projects.yaml` (likely) | Component-scoped paths under `/web-api/v1/projects/{project_id}/...` if Phase 0 D-10 audit surfaces gaps | Most paths likely already declared. Conditional on D-10 outcomes. |
| **E — admin/licenses** | `admin.yaml` | `/web-api/v1/admin/licenses`, `/web-api/v1/admin/licenses/{license_id}` | Mirror legacy admin paths. |
| **F — admin/recorders** | `admin.yaml` | `/web-api/v1/admin/recorders`, `/web-api/v1/admin/recorders/{recorder_id}` | Mirror legacy admin paths. |
| **G — admin/settings** | `admin.yaml` | `/web-api/v1/admin/settings` | Mirror legacy admin paths. |
| **H — admin/users** | `admin.yaml` | `/web-api/v1/admin/users`, `/web-api/v1/admin/users/{user_id}` | Mirror legacy admin paths. |
| **I — guest/`/explore` polish** | _(none expected)_ | _(none — already declared)_ | Public surfaces already on BFF. PR I confirms no residual legacy references on the frontend (no contract changes). |
| **J — CI guard + cleanup + BFF-parity test** | _(none)_ | _(none)_ | Adds `tests/contract/test_bff_path_parity.py` enumerating every BFF path declared by this migration and asserting each appears in the live OpenAPI surface (closes the shallow-merge limitation of `test_openapi_diff.py`). Also adds a CI lint guard against new `/api/v1/*` literals in `apps/web/src/`. |

## How a new adapter PR adds its BFF path

The procedure each new-adapter PR follows is captured below for traceability:

1. Locate the resource's existing YAML under `specs/006-permissions-redesign/contracts/` (e.g. `projects.yaml`, `admin.yaml`). If the resource has no existing YAML (e.g. `taxa`), add a new file alongside the existing ones with the same shape (top-level `servers:` block enumerating both mount prefixes; `paths:` keys in prefix-less form).
2. Under `paths:`, the path key is **prefix-less** (e.g. `/projects/{project_id}/members`, not `/web-api/v1/projects/{project_id}/members`). Add the new operation under that key.
3. Declare the operation's `security:` block as `[{ apiKeyAuth: [] }, { sessionCookie: [], csrfToken: [] }]`. Note that this OR-list is a **contract-level declaration of which auth shape is valid on which surface** — not a runtime claim that any caller may pick either. At runtime, mutual rejection is enforced by the router-level prefix discrimination: `/api/v1/*` accepts only `apiKeyAuth` (legacy Bearer API key) and rejects BFF cookies; `/web-api/v1/*` accepts only `sessionCookie + csrfToken` and rejects API-key Bearers with the documented `"API key invalid or revoked"` 401. The YAML's combined OR-list is what `test_openapi_diff.py` shallow-merges across both surfaces to satisfy contract presence; the actual auth surface is single-valued per mount. For read-only paths reachable by guests on the BFF surface, also include `[{}]` (empty requirement) so anonymous reads are contractually permitted.
4. Reference the same request/response component schemas the legacy paths reference — Pydantic schemas are shared.
5. Run `uv run pytest apps/api/tests/contract/test_openapi_diff.py` — it MUST pass before merge. Note that this test alone cannot detect "BFF mount missing while legacy mount present" — see Known Limitation above. PR J's `test_bff_path_parity.py` closes that gap.
6. Add the new BFF path (live form, `/web-api/v1/...`) to the allowlist consumed by PR J's `test_bff_path_parity.py` (until PR J ships, this is a TODO note in the PR description).

## What this directory intentionally does NOT contain

- New OpenAPI files. The repo's existing `specs/006-permissions-redesign/contracts/` is the source of truth.
- Path-by-path schema snippets. Those live in `specs/006-permissions-redesign/contracts/<resource>.yaml` and are reused as-is.
- Per-endpoint sample requests/responses. The integration tests under `apps/api/tests/integration/api/web_v1/` carry the executable examples.
