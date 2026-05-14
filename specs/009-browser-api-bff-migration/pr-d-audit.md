# PR D Pre-Audit: Annotation/Data Exports + Audio Playback

**Date**: 2026-05-14
**Branch**: `codex/spec-009-pr-d-exports-audio-bff`
**Scope**: spec/009 T068-T073, D-10 checklist before PR D frontend rewiring.

## Verdict

Backend prerequisite required before continuing with PR D frontend rewiring.

The existing BFF surface exposes `GET /web-api/v1/projects/{project_id}/recordings`
for the recordings list only. It does not expose project-scoped BFF routes for
recording audio, playback, spectrograms, annotation export, or dataset export.
Rewiring the frontend components directly to `/web-api/v1/...` would therefore
fail before reaching the legacy audio/export behavior.

## T068: Cookie-auth audio playback

Result: **failed pre-audit**.

Evidence:

- Live backend OpenAPI on `http://localhost:8002/openapi.json` lists only
  `/web-api/v1/projects/{project_id}/recordings` under project-scoped BFF
  recording/media/export paths.
- A probe to
  `/web-api/v1/projects/00000000-0000-0000-0000-000000000000/recordings/00000000-0000-0000-0000-000000000000/audio`
  returned `401 application/json` with `{"error_code":"auth_required","message":"Session cookie + access token required"}`.
  This confirms the request reached the BFF auth layer, but the target route is
  not available for browser playback validation.
- Static route registration confirms `apps/api/echoroo/api/web_v1/projects/__init__.py`
  includes `_core`, `_license`, `_members`, `_overview`, `_ownership`,
  `_restricted_config`, and trusted routes, but no `_media` router.
- `apps/api/echoroo/api/web_v1/projects/_core.py` implements only
  `GET /{project_id}/recordings` for recordings.

Browser audible playback was not attempted because the required BFF route is
missing.

## T069: Range header propagation

Result: **blocked by missing BFF audio route**.

Legacy v1 behavior is known:

- `GET /api/v1/projects/{project_id}/recordings/{recording_id}/audio` supports
  `Range`.
- Range responses return `206 Partial Content` with `Accept-Ranges`,
  `Content-Length`, and `Content-Range`.
- `/playback` delegates to `/audio`, preserving Range behavior.

The BFF route must mirror this behavior, then a browser seek test can confirm
mid-playback `Range` requests and `206` responses.

## T070: Presigned S3 redirect behavior

Result: **legacy does not redirect to presigned S3 URLs**.

Legacy v1 audio streams server-side through FastAPI. The route documentation in
`apps/api/echoroo/api/v1/recordings.py` states that it does not generate a
presigned S3 URL for the response, and the implementation resolves audio with
`AudioService.ensure_file_local()` before streaming local bytes or cached OGG.

The BFF equivalent should therefore return the same audio data through the BFF
mount, not redirect to S3.

## T071: Export response shape

Result: **blocked by missing BFF export routes**.

Legacy export behavior:

- Annotation export:
  `GET /api/v1/projects/{project_id}/annotation-projects/{annotation_project_id}/export`
  returns JSON/AOEF data directly, or a full CSV `Response`. It is not a
  streaming route.
- Dataset export:
  `GET /api/v1/projects/{project_id}/datasets/{dataset_id}/export` returns a
  `StreamingResponse` with `application/zip`, but the current service builds the
  ZIP in memory before yielding chunks.

No equivalent project-scoped BFF export routes are registered today. Token
refresh during a BFF export cannot be validated until those routes exist.

## T072: Vite proxy MIME and Range behavior

Result: **proxy is pass-through; backend route missing is the blocker**.

`apps/web/vite.config.ts` proxies both `/api` and `/web-api` to the backend with
`changeOrigin: true`. It does not rewrite or synthesize `Range`, `Content-Type`,
or `Content-Range` headers. Once the backend BFF media route exists, MIME and
Range behavior should be preserved by the dev proxy and validated in the browser.

## T073: Backend prerequisite

Result: **gap surfaced**.

Add a backend prerequisite split before continuing PR D frontend rewiring:

- Add project-scoped BFF media/export handlers, preferably in
  `apps/api/echoroo/api/web_v1/projects/_media.py`.
- Mirror legacy server-streaming audio behavior for:
  - `GET /web-api/v1/projects/{project_id}/recordings/{recording_id}/audio`
  - `GET /web-api/v1/projects/{project_id}/recordings/{recording_id}/playback`
  - `GET /web-api/v1/projects/{project_id}/recordings/{recording_id}/spectrogram`
- Mirror export behavior for:
  - `GET /web-api/v1/projects/{project_id}/annotation-projects/{annotation_project_id}/export`
  - `GET /web-api/v1/projects/{project_id}/datasets/{dataset_id}/export`
- Add integration coverage for cookie auth, API-key cross-rejection, permission
  denial, `Range: bytes=0-99` -> `206`, `Content-Range`, and no redirect for
  audio.

## Verification Notes

Commands attempted:

```bash
docker ps --format '{{.Names}} {{.Status}} {{.Ports}}'
curl -s http://localhost:8002/openapi.json | jq -r '.paths | keys[] | select(startswith("/web-api/v1/projects")) | select(test("recordings|export|datasets|annotation-projects"))'
curl -s http://localhost:8002/openapi.json | jq -r '.paths | keys[] | select(startswith("/api/v1/projects")) | select(test("recordings/.*/(audio|playback|spectrogram)|datasets/.*/export|annotation-projects/.*/export"))'
curl -s -o /tmp/echoroo_bff_audio_probe.txt -w '%{http_code} %{content_type}\n' http://localhost:8002/web-api/v1/projects/00000000-0000-0000-0000-000000000000/recordings/00000000-0000-0000-0000-000000000000/audio
```

`uv run` based route inspection was not available because the local
`apps/api/.venv` symlink/environment is broken and `uv` failed while attempting
to remove `.venv/lib` with a permission error.

## D0 Follow-up Implemented

The backend prerequisite split was implemented in this branch after the audit:

- Added `apps/api/echoroo/api/web_v1/projects/_media.py`.
- Wired `_media` into `apps/api/echoroo/api/web_v1/projects/__init__.py`.
- Added the five new BFF media/export paths to
  `apps/api/tests/contract/_bff_path_parity_allowlist.py`.
- Added integration coverage in:
  - `apps/api/tests/integration/api/web_v1/test_projects_recordings_media.py`
  - `apps/api/tests/integration/api/web_v1/test_projects_exports.py`

Post-D0 verification:

```bash
docker exec -w /app echoroo-backend uv run ruff check echoroo/api/web_v1/projects/_media.py tests/integration/api/web_v1/test_projects_recordings_media.py tests/integration/api/web_v1/test_projects_exports.py
docker exec -w /app echoroo-backend sh -lc 'TEST_DATABASE_URL=postgresql+asyncpg://postgres:cf3871bf@db:5432/echoroo uv run pytest tests/integration/api/web_v1/test_projects_recordings_media.py tests/integration/api/web_v1/test_projects_exports.py -q --no-cov'
docker exec -w /app echoroo-backend sh -lc 'TEST_DATABASE_URL=postgresql+asyncpg://postgres:cf3871bf@db:5432/echoroo uv run pytest tests/contract/test_recordings.py tests/contract/test_annotation_projects.py tests/contract/test_datasets.py -q --no-cov'
```

Results:

- Ruff passed.
- D0 BFF tests passed: `14 passed`.
- Relevant legacy contract tests completed successfully (`[100%]`) with no
  failures.
- Running backend OpenAPI now includes:
  - `/web-api/v1/projects/{project_id}/recordings/{recording_id}/audio`
  - `/web-api/v1/projects/{project_id}/recordings/{recording_id}/playback`
  - `/web-api/v1/projects/{project_id}/recordings/{recording_id}/spectrogram`
  - `/web-api/v1/projects/{project_id}/annotation-projects/{annotation_project_id}/export`
  - `/web-api/v1/projects/{project_id}/datasets/{dataset_id}/export`

## PR D Completion Notes

Frontend rewiring and follow-up BFF read adapters were completed in this branch.
The final browser smoke opened annotation, dataset, recording, and detection
project screens, then exercised annotation export, dataset export, BFF audio
Range streaming, and native media token playback.

Final browser network sample:

```json
{
  "direct": {
    "annotationExport": 200,
    "datasetExport": 200,
    "audioRange": 206,
    "audioContentRange": "bytes 0-127/5227",
    "nativePlaybackToken": 206,
    "nativeContentRange": "bytes 0-127/5227"
  },
  "legacyHits": [],
  "bad": []
}
```

Additional implementation notes:

- Export dialogs now download through `apiClient.requestRaw()` + blob URLs
  instead of unauthenticated anchor navigation.
- `AuthRouterMiddleware` accepts `?token=` only for BFF recording media GETs
  (`audio`, `playback`, `spectrogram`) while still requiring the session cookie.
  This preserves native `<audio>` / `<img>` Range behavior for first-party pages.
- Dataset, recording, detection-run, detection, and annotation prerequisite reads
  needed by the PR D screens now have project-scoped BFF adapters.

Final verification:

```bash
docker exec -w /app echoroo-backend uv run --extra dev ruff check ...
docker exec -w /app echoroo-backend sh -lc 'TEST_DATABASE_URL=postgresql+asyncpg://postgres:cf3871bf@db:5432/echoroo uv run pytest tests/integration/api/web_v1/test_projects_annotations.py tests/integration/api/web_v1/test_projects_recordings_media.py tests/integration/api/web_v1/test_projects_exports.py -q --no-cov'
cd apps/web && npm run check
cd apps/web && npm run test -- --run
```

Results:

- Backend Ruff passed.
- Backend targeted integration passed: `19 passed`.
- Frontend `npm run check` passed with 0 errors and 18 pre-existing warnings.
- Frontend Vitest passed: `10 passed`, `1284 passed`.
