# API surface: `/web-api/v1` (browser BFF) vs `/api/v1` (programmatic)

Echoroo exposes two parallel HTTP surfaces over the same domain. They are
authenticated and shaped differently, and the split is deliberate.

| Aspect | `/web-api/v1` (Browser BFF) | `/api/v1` (Programmatic API) |
| --- | --- | --- |
| Intended caller | Echoroo SvelteKit frontend / browsers | Scripts, researchers, integrations |
| Auth | First-party session cookie + CSRF token (media GETs also accept a scoped `media_token`) | `Authorization: Bearer <API key or JWT>` |
| CSRF | Enforced on all mutating requests | Not applicable (no ambient credential) |
| Shape | Tuned for UI needs (aggregation, media tokens, un-gated image proxy) | Resource-oriented, stable contract |
| Business logic | Thin adapters that `gate_action(...)` then delegate to the legacy handler | Legacy handler bodies (the same helpers the BFF delegates to) |

Historically the frontend called `/api/v1` directly. Over the W2-3 / W2-4
migration the browser-facing routes were **unmounted** from `/api/v1` and moved
to the `/web-api/v1` BFF. Only the route registration moved: the legacy handler
bodies survive as importable helpers that the BFF adapter imports and delegates
to, so there is no duplicated business logic.

For the full programmatic catalogue and auth details see
[`docs/api/v1-programmatic-api.md`](../api/v1-programmatic-api.md).

## `keep_other` — permanent `/api/v1` KEEP list

A curated set of routes stays mounted on `/api/v1` even though the browser also
reaches equivalent functionality through the BFF. These are **not** slated for
future unmount — each is a programmatic-first or contract-stable surface.

| Route | Rationale |
| --- | --- |
| `GET /api/v1/projects/{project_id}/detections/{detection_id}` | Single-detection read for scripted review clients; stable programmatic contract. |
| `POST /api/v1/projects/{project_id}/detections/{detection_id}/confirm` | Scripted review workflow (confirm a detection) without a browser session. |
| `POST /api/v1/projects/{project_id}/detections/{detection_id}/reject` | Scripted review workflow (reject a detection) without a browser session. |
| `DELETE /api/v1/projects/{project_id}/detections/{detection_id}` | Scripted review workflow (delete a detection) without a browser session. |
| `GET /api/v1/projects/{project_id}/detection-runs/{run_id}` | Poll a detection-run's status/result from an automation client. |
| `PATCH /api/v1/projects/{project_id}/detection-runs/{run_id}` | Update a detection-run (e.g. rename) programmatically. |
| `POST /api/v1/projects/{project_id}/search/similar` | Embedding similarity search by detection — programmatic pipeline entry point (the UI flow uses `/search/batch`). |
| `POST /api/v1/projects/{project_id}/search/similar-by-audio` | Embedding similarity search by uploaded audio — programmatic pipeline entry point. |
| `POST /api/v1/annotation-sets/{set_id}/sample` | Sample an annotation set for external labelling / QA tooling. |
| `GET /api/v1/projects/{project_id}/datasets/{dataset_id}/export` | Dataset export for scripted download / archival pipelines. |

## Un-gated permanent keep: Xeno-canto sonogram proxy

`GET /web-api/v1/projects/{project_id}/xeno-canto/sonogram` is a permanent keep
that is **intentionally unauthenticated**. The server-emitted
`XenoCantoRecording.sonogram_url` is rendered by a native `<img src=...>`
element, which cannot attach an `Authorization: Bearer` header (and CSRF exempts
GET). Sonograms are open data from xeno-canto.org, so no credential is required;
the SSRF allowlist (`_validate_sonogram_url` — https-only, host-pinned to
`xeno-canto.org`, private-IP rejection, DNS-rebinding-proof IP pinning, bounded
redirect re-validation) is the primary control. The `{project_id}` segment is
routing-only and is not validated. This is the sole un-gated route on either
surface besides the auth bootstrap endpoints. It was moved from `/api/v1` to the
BFF surface in W2-4 PR-D; the legacy `/api/v1` sonogram route is unmounted.

## Xeno-canto search + audio (W2-4 PR-C)

The Xeno-canto **search** and **audio** proxies are browser-first and were
unmounted from `/api/v1` in W2-4 PR-C in favour of their BFF twins:

- `GET /web-api/v1/projects/{project_id}/xeno-canto/search` — gated by
  `SEARCH_SESSION_LIST_ACTION` (mirroring the legacy `check_project_access`
  baseline).
- `GET /web-api/v1/projects/{project_id}/xeno-canto/audio/{xc_id}` — gated by
  `XENO_CANTO_AUDIO_ACTION` (connection-time gate on the streaming response).

The legacy handler bodies (`search_xeno_canto`, `proxy_audio`) survive as
importable helpers delegated to by the BFF adapter. With PR-C the legacy
`xeno_canto.router` defines zero routes, so its `include_router` was removed.
