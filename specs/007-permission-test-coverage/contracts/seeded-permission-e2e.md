# Contract: Seeded Permission E2E Suites

## Seed Command

```bash
docker exec -e DEBUG=false echoroo-backend \
  uv run python -m echoroo.scripts.seed_e2e_permissions --confirm \
  > /tmp/echoroo-e2e-seed.json
```

The command writes JSON with:

- `env`: shell-exportable environment variables for Playwright suites.
- `projects`: structured public/restricted project payloads.
- `api_keys`: API key metadata and the env variable name containing the raw local key.

## Required Environment Contract

All seeded suites require:

- `E2E_PASSWORD`
- `E2E_OWNER_EMAIL`, `E2E_OWNER_TOTP_SECRET`, `E2E_OWNER_API_KEY`
- `E2E_ADMIN_EMAIL`, `E2E_ADMIN_TOTP_SECRET`, `E2E_ADMIN_API_KEY`
- `E2E_MEMBER_EMAIL`, `E2E_MEMBER_TOTP_SECRET`, `E2E_MEMBER_API_KEY`
- `E2E_VIEWER_EMAIL`, `E2E_VIEWER_TOTP_SECRET`, `E2E_VIEWER_API_KEY`
- `E2E_NONMEMBER_EMAIL`, `E2E_NONMEMBER_TOTP_SECRET`, `E2E_NONMEMBER_API_KEY`
- `E2E_TRUSTED_EMAIL`, `E2E_TRUSTED_TOTP_SECRET`, `E2E_TRUSTED_API_KEY`
- `E2E_TRUSTED_LIFECYCLE_EMAIL`, `E2E_TRUSTED_LIFECYCLE_TOTP_SECRET`, `E2E_TRUSTED_LIFECYCLE_API_KEY`
- `E2E_PUBLIC_PROJECT_ID`, `E2E_PUBLIC_PROJECT_NAME`
- `E2E_RESTRICTED_PROJECT_ID`, `E2E_RESTRICTED_PROJECT_NAME`

Data-surface suites additionally require:

- `E2E_PUBLIC_SITE_ID`
- `E2E_PUBLIC_DATASET_ID`, `E2E_PUBLIC_DATASET_NAME`
- `E2E_PUBLIC_RECORDING_ID`
- `E2E_PUBLIC_DETECTION_ID`
- `E2E_RESTRICTED_SITE_ID`
- `E2E_RESTRICTED_DATASET_ID`, `E2E_RESTRICTED_DATASET_NAME`
- `E2E_RESTRICTED_RECORDING_ID`
- `E2E_RESTRICTED_DETECTION_ID`

If detection detail deep links are asserted, the suite also needs a stable
visibility-prefixed detection tag ID or must derive the tag ID from a list
response before navigating.

Vote/comment suites additionally require:

- `E2E_PUBLIC_ANNOTATION_ID`
- `E2E_RESTRICTED_ANNOTATION_ID`

Export/search suites additionally require:

- `E2E_PUBLIC_DATASET_ID`
- `E2E_PUBLIC_SEARCH_SESSION_ID`
- `E2E_PUBLIC_EXPORTABLE_SEARCH_SESSION_ID`
- `E2E_RESTRICTED_DATASET_ID`
- `E2E_RESTRICTED_SEARCH_SESSION_ID`
- `E2E_RESTRICTED_EXPORTABLE_SEARCH_SESSION_ID`

Media suites additionally require the data-surface recording IDs:

- `E2E_PUBLIC_RECORDING_ID`
- `E2E_PUBLIC_CLIP_ID`
- `E2E_RESTRICTED_RECORDING_ID`
- `E2E_RESTRICTED_CLIP_ID`

Trusted overlay lifecycle suites additionally require:

- `E2E_TRUSTED_LIFECYCLE_USER_ID`
- `E2E_RESTRICTED_TRUSTED_LIFECYCLE_OVERLAY_ID`
- `E2E_RESTRICTED_TRUSTED_EXPIRED_OVERLAY_ID`

## API Contract

Programmatic checks use:

```http
Authorization: Bearer <E2E_ROLE_API_KEY>
```

against `ECHOROO_API_URL` or `PUBLIC_API_URL`, normalized without trailing slash.

Vote endpoints:

```http
GET    /api/v1/projects/{projectId}/annotations/{annotationId}/votes
POST   /api/v1/projects/{projectId}/annotations/{annotationId}/votes
DELETE /api/v1/projects/{projectId}/annotations/{annotationId}/votes
```

POST vote payload:

```json
{
  "vote": "agree",
  "signal_quality": "solo"
}
```

Comment endpoints:

```http
GET  /api/v1/projects/{projectId}/annotations/{annotationId}/comments
POST /api/v1/projects/{projectId}/annotations/{annotationId}/comments
```

POST comment payload:

```json
{
  "body": "unique per role, visibility, and run"
}
```

Expected current statuses:

| Surface | Public roles | Restricted owner/admin/member | Restricted viewer | Restricted nonmember | Restricted trusted |
|---------|--------------|-------------------------------|-------------------|----------------------|--------------------|
| `GET votes` | 200 | 200 | 200 when detection read is allowed | 200 when restricted public overlay allows detection read | 200 |
| `POST votes` | 200 | 200 | 403 | 200 due to `allow_voting_and_comments=true` | 200 |
| `DELETE votes` | 200 after same-user vote exists | 200 after same-user vote exists | 403 | 200 after same-user vote exists | 200 after same-user vote exists |
| `GET comments` | 200 | 200 | 200 when detection read is allowed | 200 when restricted public overlay allows detection read | 200 |
| `POST comments` | 201 | 201 | 403 | 201 due to `allow_voting_and_comments=true` | 201 |

Search endpoints:

```http
GET /api/v1/projects/{projectId}/search/sessions
GET /api/v1/projects/{projectId}/search/sessions/{searchSessionId}
```

Search export endpoints:

```http
GET /api/v1/projects/{projectId}/detections/export/csv
GET /api/v1/projects/{projectId}/search/sessions/{searchSessionId}/export/csv
GET /api/v1/projects/{projectId}/search/sessions/{searchSessionId}/export-recordings
GET /api/v1/projects/{projectId}/search/sessions/{searchSessionId}/reference-audio/0
GET /api/v1/projects/{projectId}/datasets/{datasetId}/export?include_audio=false
GET /api/v1/projects/{projectId}/datasets/{datasetId}/export?include_audio=true
```

Expected current statuses:

| Surface | Public roles | Restricted owner/admin/member | Restricted viewer | Restricted nonmember | Restricted trusted |
|---------|--------------|-------------------------------|-------------------|----------------------|--------------------|
| `GET search sessions` | 200 | 200 | 200 | 403 | 200 |
| `GET search session detail` | 200 | 200 | 200 | 403 | 200 |
| `GET detections CSV export` | 200 | 200 | 403 | 403 | 200 |
| `GET search session CSV export` | 200 | 200 | 403 | 403 | 200 |
| `GET search session recordings export` | 404 | 404 | 403 | 403 | 404 |
| `GET search session reference audio` | 404 | 404 | 404 | 403 | 404 |
| `GET dataset ZIP export` | 200 | 200 | 403 | 403 | 200 |

The completed Export/Search slice asserts status and CSV `content-type` only.
The exportable search-session check additionally consumes one deterministic
`export-recordings` CSV body for owner access and asserts the exact header,
seeded recording filename, species labels, and `1.0000` aggregate values. It
also streams one deterministic S3-backed reference WAV for owner access and
asserts full `200` plus Range `206` audio responses. The dataset ZIP export
checks use `include_audio=false` for the role/status matrix and
`include_audio=true` role/visibility payload assertions for allowed cases,
verifying the expected audio entry and inflated WAV `RIFF` bytes. The
`export-recordings` and `reference-audio/0` checks are storage-free permission
guards: allowed callers reach deterministic fixture-missing 404 responses
(`"Session has no results to export"` and
`"Reference audio source index 0 not found"`), while denied callers receive 403
before storage-backed processing. Broader multi-role dataset audio ZIP payload
assertions beyond the seeded single-recording fixture remain future scope.

Media endpoints:

```http
GET /api/v1/projects/{projectId}/recordings/{recordingId}/audio
GET /api/v1/projects/{projectId}/recordings/{recordingId}/playback
GET /api/v1/projects/{projectId}/recordings/{recordingId}/spectrogram
GET /api/v1/projects/{projectId}/recordings/{recordingId}/download
GET /api/v1/projects/{projectId}/recordings/{recordingId}/clips/{clipId}/audio
GET /api/v1/projects/{projectId}/recordings/{recordingId}/clips/{clipId}/spectrogram
GET /api/v1/projects/{projectId}/recordings/{recordingId}/clips/{clipId}/download
```

Clip browser BFF endpoints:

```http
GET /web-api/v1/projects/{projectId}/recordings/{recordingId}/clips
GET /web-api/v1/projects/{projectId}/recordings/{recordingId}/clips/{clipId}
GET /web-api/v1/projects/{projectId}/recordings/{recordingId}/spectrogram?start={clipStart}&end={clipEnd}&media_token={token}
GET /web-api/v1/projects/{projectId}/recordings/{recordingId}/playback?start={clipStart}&end={clipEnd}&media_token={token}
```

Expected current statuses:

| Surface | Public authenticated roles | Restricted authenticated roles | Public guest | Restricted guest |
|---------|----------------------------|--------------------------------|--------------|------------------|
| `GET audio` | 200 or 206 | 200 or 206 | 200 or 206 | 200 or 206 |
| `GET playback` | 200 or 206 | 200 or 206 | 200 or 206 | 200 or 206 |
| `GET spectrogram` | 200 | 200 | 200 | 200 |
| `GET download` | 200 | 200 | not asserted | not asserted |

Clip media expected current statuses:

| Surface | Public authenticated roles | Restricted owner/admin/member/trusted | Restricted viewer/nonmember |
|---------|----------------------------|---------------------------------------|-----------------------------|
| `GET clip audio` | 200 | 200 | 200 |
| `GET clip spectrogram` | 200 | 200 | 200 |
| `GET clip download` | 200 | 200 | 403 |

The completed Media slice asserts status, content type, and non-empty bytes.
Recording download is intentionally modeled as `VIEW_MEDIA`-gated because the
current backend routes it through `RECORDING_MEDIA_ACTION`; it is not used to
assert `Permission.DOWNLOAD`. Clip audio/spectrogram are `VIEW_MEDIA`-gated;
clip download is `DOWNLOAD`-gated. Guest clip media requests are expected to
return 401 because the clip routes currently require an authenticated
`CurrentUser`. The clip browser smoke asserts owner/trusted session access
through `/web-api/v1` list/detail routes plus scoped media tokens on preview,
detail spectrogram, and playback URLs.

Trusted overlay lifecycle endpoints:

```http
GET    /web-api/v1/projects/{projectId}/trusted-users?status=active|expired|revoked
POST   /web-api/v1/projects/{projectId}/trusted-users
PATCH  /web-api/v1/projects/{projectId}/trusted-users/{trustedUserId}
DELETE /web-api/v1/projects/{projectId}/trusted-users/{trustedUserId}
```

Trusted lifecycle mutation checks use UI login session cookies plus Bearer and
`X-CSRF-Token` from the `echoroo_csrf` cookie. The completed slice covers:

- owner PATCH `granted_permissions` and `extension_seconds` on the disposable
  restricted lifecycle overlay.
- admin PATCH/DELETE denial with 403.
- owner DELETE revoke with 204 and revoked-filter listing.
- trusted lifecycle API key denial after revoke.
- owner fresh invitation issuance with 202.
- expired seeded overlay listing through `?status=expired`.

The immutable baseline overlay IDs (`E2E_PUBLIC_TRUSTED_OVERLAY_ID` and
`E2E_RESTRICTED_TRUSTED_OVERLAY_ID`) must not be PATCHed or DELETEd by lifecycle
tests. Invitation accept/re-grant activation is future scope because the signed
token is delivered through email/outbox and is not returned by the invite API.

## UI Contract

Browser UI checks use:

- `/en/login` for UI login and TOTP.
- `/en/projects/{projectId}/datasets`
- `/en/projects/{projectId}/datasets/{datasetId}`
- `/en/projects/{projectId}/recordings`
- `/en/projects/{projectId}/recordings/{recordingId}`
- `/en/projects/{projectId}/detections`
- `/en/projects/{projectId}/detections/{tagId}` only when a stable tag ID is
  seeded or derived
- Public explore routes under `/en/explore/projects`.

UI assertions must prefer stable headings, accessible names, and existing
`data-testid` attributes. Data Surfaces must avoid media playback and
spectrogram rendering; the Media suite owns those checks, including
`clip-preview-image`, `clip-detail-spectrogram`, `clip-detail-audio`, and
`clip-detail-play`. Detection service
success should not be a hard gate for Data Surfaces unless the implementation
first verifies the current deferred dependencies are stable in the local stack.

## Verification Contract

Each completed slice must run:

```bash
RUFF_CACHE_DIR=/tmp/echoroo-ruff-cache ruff check apps/api/echoroo/scripts/seed_e2e_permissions.py apps/api/echoroo/api/v1/clips.py apps/api/echoroo/api/v1/search/sessions.py
RUFF_CACHE_DIR=/tmp/echoroo-ruff-cache ruff format --check apps/api/echoroo/scripts/seed_e2e_permissions.py apps/api/echoroo/api/v1/clips.py apps/api/echoroo/api/v1/search/sessions.py
python3 -m py_compile apps/api/echoroo/scripts/seed_e2e_permissions.py apps/api/echoroo/api/v1/clips.py apps/api/echoroo/api/v1/search/sessions.py
cd apps/api
uv run mypy echoroo/scripts/seed_e2e_permissions.py echoroo/api/v1/clips.py echoroo/api/v1/search/sessions.py

cd apps/web
npx prettier --check <changed-e2e-files>
npx eslint <changed-e2e-files>
npm run check
npx playwright test <new-suite> --reporter=list --workers=1
npx playwright test tests/e2e/permissions/seeded-feature-permissions.spec.ts --reporter=list --workers=1
npx playwright test tests/e2e/permissions/seeded-permissions-matrix.spec.ts --reporter=list --workers=1
```
