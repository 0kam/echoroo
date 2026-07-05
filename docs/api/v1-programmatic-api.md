# Echoroo `/api/v1` — Programmatic API

This document describes `/api/v1/*` as the **programmatic surface** of the
Echoroo backend: the endpoints intended for researchers, scripts, and
third-party integrations that talk to Echoroo without a browser session.

## Audience

You are the intended reader if you want to:

- automate ingestion, export, or review workflows with a script (Python, R,
  shell + `curl`, etc.);
- integrate Echoroo data into an external pipeline or notebook;
- drive detection review or search from a headless client.

If you are building the Echoroo web UI (or any browser client that logs in
with the first-party session), use the **`/web-api/v1/*` BFF** instead — see
[Surface split](#surface-split-api-v1-vs-web-api-v1) below.

## Authentication

`/api/v1/*` authenticates with a **Bearer credential** in the standard
`Authorization` header:

```
Authorization: Bearer <credential>
```

Two credential types are accepted:

1. **API keys** (recommended for automation). Long-lived, per-user tokens
   with the prefix `ecr_`. Create and manage them under
   `/api/v1/users/me/api-tokens`:
   - `POST /api/v1/users/me/api-tokens` — create a key. The plaintext value is
     returned **only once** in the response; store it securely (it is hashed
     at rest and cannot be retrieved again).
   - `GET /api/v1/users/me/api-tokens` — list your active keys (values are not
     returned).
   - `DELETE /api/v1/users/me/api-tokens/{token_id}` — revoke a key.
   API keys may be scoped to specific source-IP CIDRs; repeated violations of
   the allowed range auto-revoke the key.
2. **Access-token JWTs** issued by the auth flow (`POST /api/v1/auth/register`,
   `POST /api/v1/auth/refresh`). These are the same short-lived tokens the
   session layer mints; scripts generally prefer API keys because they do not
   need periodic refresh.

Two-factor enrolment is enforced on `/api/v1/*` exactly as on the browser
surface: a principal whose account requires 2FA (or a forced password change)
is gated at the middleware layer before the handler runs.

The only unauthenticated `/api/v1` routes are the auth bootstrap endpoints
(`/api/v1/auth/*`) and the public Xeno-canto **sonogram** proxy.

## Surface split: `/api/v1` vs `/web-api/v1`

Echoroo exposes two parallel HTTP surfaces. They serve the same domain but are
authenticated and shaped differently:

| Aspect | `/api/v1` (Programmatic API) | `/web-api/v1` (Browser BFF) |
| --- | --- | --- |
| Intended caller | Scripts, researchers, integrations | The Echoroo SvelteKit frontend / browsers |
| Auth | `Authorization: Bearer <API key or JWT>` | First-party session cookie + CSRF token |
| CSRF | Not applicable (no ambient credential) | Enforced on all mutating requests |
| Shape | Resource-oriented, stable contract | Tuned for UI needs (aggregation, media tokens) |
| OpenAPI tag group | `Programmatic API — <Resource>` | plain resource tags (`projects`, `auth`, …) |

Historically the frontend called `/api/v1` directly. Over the W2-3 / W2-4
migration the browser-facing routes (~107 routes plus the media-download and
streaming aliases) were **unmounted** from `/api/v1` and moved to the
`/web-api/v1` BFF. The legacy handler bodies were kept as importable helpers
that the BFF delegates to, so there is no duplicated business logic — only the
route registration moved.

What remains mounted under `/api/v1` is the curated programmatic surface
documented below.

## Endpoint catalogue

The live surface is generated from the FastAPI app; the following is the
current `/api/v1` route inventory grouped by resource. `{…}` segments are path
parameters.

### Auth (`/api/v1/auth`)

| Method | Path | Description |
| --- | --- | --- |
| POST | `/api/v1/auth/register` | Register a new user |
| POST | `/api/v1/auth/refresh` | Refresh an access token |
| POST | `/api/v1/auth/logout` | Log out (revoke the current session) |
| POST | `/api/v1/auth/change-password` | Change own password (v1 mirror of the BFF endpoint) |

### Users (`/api/v1/users`)

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/v1/users/me` | Get the current user profile |
| PATCH | `/api/v1/users/me` | Update the current user profile |
| PUT | `/api/v1/users/me/password` | Change password |
| GET | `/api/v1/users/me/api-tokens` | List API tokens |
| POST | `/api/v1/users/me/api-tokens` | Create an API token (value shown once) |
| DELETE | `/api/v1/users/me/api-tokens/{token_id}` | Revoke an API token |

### Projects (`/api/v1/projects`)

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/v1/projects` | List projects |
| POST | `/api/v1/projects` | Create a project |
| GET | `/api/v1/projects/{project_id}` | Get a project |
| PATCH | `/api/v1/projects/{project_id}` | Update a project |
| DELETE | `/api/v1/projects/{project_id}` | Delete a project |
| GET | `/api/v1/projects/{project_id}/overview` | Get project overview |
| GET | `/api/v1/projects/{project_id}/members` | List project members |
| PATCH | `/api/v1/projects/{project_id}/members/{user_id}` | Update a member role |
| DELETE | `/api/v1/projects/{project_id}/members/{user_id}` | Remove a project member |
| PATCH | `/api/v1/projects/{project_id}/license` | Update the project license |
| GET | `/api/v1/projects/{project_id}/license-history` | Get project license history |
| PATCH | `/api/v1/projects/{project_id}/restricted-config` | Update Restricted-mode capability toggles |

### Datasets (`/api/v1/projects/{project_id}/datasets`)

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/v1/projects/{project_id}/datasets/{dataset_id}/export` | Export a dataset |

### Recordings (`/api/v1/projects/{project_id}/recordings`)

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/v1/projects/{project_id}/recordings/{recording_id}/audio` | Stream recording audio with HTTP Range support |

### Detections (`/api/v1/projects/{project_id}/detections`)

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/v1/projects/{project_id}/detections/{detection_id}` | Get a detection |
| DELETE | `/api/v1/projects/{project_id}/detections/{detection_id}` | Delete a detection |
| POST | `/api/v1/projects/{project_id}/detections/{detection_id}/confirm` | Confirm a detection |
| POST | `/api/v1/projects/{project_id}/detections/{detection_id}/reject` | Reject a detection |

### Detection runs (`/api/v1/projects/{project_id}/detection-runs`)

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/v1/projects/{project_id}/detection-runs/{run_id}` | Get a detection run |
| PATCH | `/api/v1/projects/{project_id}/detection-runs/{run_id}` | Update a detection run |

### Confirmed regions (`/api/v1/projects/{project_id}/confirmed-regions`)

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/v1/projects/{project_id}/confirmed-regions` | List confirmed regions |
| POST | `/api/v1/projects/{project_id}/confirmed-regions` | Create a confirmed region |
| DELETE | `/api/v1/projects/{project_id}/confirmed-regions/{region_id}` | Delete a confirmed region |

### Annotation comments (`/api/v1/projects/{project_id}/annotations`)

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/v1/projects/{project_id}/annotations/{annotation_id}/comments` | List annotation comments |
| POST | `/api/v1/projects/{project_id}/annotations/{annotation_id}/comments` | Create an annotation comment |

### Annotation sets (`/api/v1/annotation-sets`)

| Method | Path | Description |
| --- | --- | --- |
| POST | `/api/v1/annotation-sets/{set_id}/sample` | Dispatch the sampling job |

### Search (`/api/v1/projects/{project_id}/search`)

| Method | Path | Description |
| --- | --- | --- |
| POST | `/api/v1/projects/{project_id}/search/similar` | Search by embedding ID |
| POST | `/api/v1/projects/{project_id}/search/similar-by-audio` | Search by uploaded audio |

### Taxa (`/api/v1/taxa`)

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/v1/taxa` | List taxa |
| GET | `/api/v1/taxa/search` | Search taxa (local) |
| GET | `/api/v1/taxa/gbif-search` | Search species via the GBIF real-time API |
| POST | `/api/v1/taxa/from-gbif` | Create a local taxon from a GBIF pick |
| GET | `/api/v1/taxa/{taxon_id}` | Get taxon detail |

### Licenses (`/api/v1/licenses`)

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/v1/licenses` | List active licenses |

### H3 (`/api/v1/h3`)

| Method | Path | Description |
| --- | --- | --- |
| POST | `/api/v1/h3/from-coordinates` | Resolve an H3 index from coordinates |
| POST | `/api/v1/h3/validate` | Validate an H3 index |

### Xeno-canto proxy (`/api/v1/projects/{project_id}/xeno-canto`)

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/v1/projects/{project_id}/xeno-canto/search` | Search Xeno-canto recordings |
| GET | `/api/v1/projects/{project_id}/xeno-canto/audio/{xc_id}` | Proxy a Xeno-canto audio download |
| GET | `/api/v1/projects/{project_id}/xeno-canto/sonogram` | Proxy a Xeno-canto sonogram image (public) |

## Media routes on `/api/v1`

Two media routes stay on the programmatic surface because a script is a
legitimate first-class caller for them:

- `GET /api/v1/projects/{project_id}/recordings/{recording_id}/audio` streams
  the raw recording with HTTP **Range** support, so a script can pull audio (or
  a byte range) directly with a Bearer credential.
- `GET /api/v1/projects/{project_id}/xeno-canto/audio/{xc_id}` and
  `.../sonogram` proxy Xeno-canto media.

The **browser** media paths (clip audio / spectrogram / download, reference-
audio streaming, anonymous public playback) were moved to the `/web-api/v1`
**media-token** pattern during W2-4 (PR-A…E): the browser first mints a
short-lived, single-purpose media token via the BFF, then fetches the bytes
with that token instead of exposing a long-lived credential in an `<audio>` /
`<img>` URL. Scripts do not need this indirection, so the Range-capable audio
route remains directly available under `/api/v1`.

## Retained programmatic-only routes ("keep_other")

A small set of `/api/v1` routes have **no** `/web-api/v1` twin and no browser
caller. They are deliberately retained on the programmatic surface because
they are useful to scripts/integrations and there is no UI equivalent to move
them to:

| Route | Why it stays on `/api/v1` |
| --- | --- |
| `POST /api/v1/h3/from-coordinates` | Geospatial helper — resolve an H3 cell from lat/long in a script. No dedicated UI screen. |
| `POST /api/v1/h3/validate` | Geospatial helper — validate an H3 index. No dedicated UI screen. |
| `GET /api/v1/taxa` / `GET /api/v1/taxa/search` / `GET /api/v1/taxa/{taxon_id}` | Read-only taxonomy lookups convenient for scripted enrichment; the browser uses richer BFF-composed pickers. |
| `GET /api/v1/taxa/gbif-search` / `POST /api/v1/taxa/from-gbif` | GBIF real-time search + local-taxon creation, useful for scripted taxonomy bootstrap. |
| `GET /api/v1/licenses` | Read the active license master for scripted export/attribution. |
| `POST /api/v1/annotation-sets/{set_id}/sample` | Dispatch a sampling job programmatically. |
| `GET /api/v1/projects/{project_id}/xeno-canto/search` / `audio/{xc_id}` / `sonogram` | External Xeno-canto proxy usable from scripts (sonogram is public). |

## Examples

Create an API key (using an existing session/JWT once), then use it for
subsequent calls. Replace `$BASE` with your deployment origin (e.g.
`http://localhost:8002`).

```bash
# 1. Create an API key (returns the plaintext value ONCE)
curl -sS -X POST "$BASE/api/v1/users/me/api-tokens" \
  -H "Authorization: Bearer $BOOTSTRAP_JWT" \
  -H "Content-Type: application/json" \
  -d '{"name": "ingest-script"}'
# → {"id": "...", "name": "ingest-script", "token": "ecr_XXXXXXXX...", ...}
```

```bash
# 2. List projects with the API key
export ECR_KEY="ecr_XXXXXXXX..."
curl -sS "$BASE/api/v1/projects" \
  -H "Authorization: Bearer $ECR_KEY"
```

```bash
# 3. Download recording audio (Range-capable) to a file
curl -sS "$BASE/api/v1/projects/$PROJECT_ID/recordings/$RECORDING_ID/audio" \
  -H "Authorization: Bearer $ECR_KEY" \
  -o recording.wav
```

## Interactive documentation

The full, always-current contract (request/response schemas, status codes) is
served by the running backend:

- Swagger UI: `GET /docs`
- OpenAPI JSON: `GET /openapi.json`

In the Swagger UI, programmatic endpoints are grouped under
`Programmatic API — <Resource>` tags, and the browser BFF endpoints under the
plain resource tags, so the two surfaces are easy to tell apart.
