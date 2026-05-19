# Seeded Browser E2E Roadmap

**Status**: US1/US2/US3 plus Trusted Overlay lifecycle, Export/Search API-primary, Dataset ZIP export with audio, Search storage gate guards, Export-recordings success CSV, Reference-audio success stream, Media plus Clip API-primary, and Clip browser BFF media-token wiring complete
**Last updated**: 2026-05-18
**Purpose**: Persistent handoff notes for continuing seeded browser E2E permission and feature coverage across Codex context compaction.

## Current Baseline

The local E2E environment has a seeded permission fixture flow and seven green Playwright suites.

Changed files currently in progress:

- `apps/api/echoroo/scripts/seed_e2e_permissions.py`
- `apps/web/tests/e2e/permissions/seeded-permissions.helpers.ts`
- `apps/web/tests/e2e/permissions/seeded-permissions-matrix.spec.ts`
- `apps/web/tests/e2e/permissions/seeded-feature-permissions.spec.ts`
- `apps/web/tests/e2e/permissions/seeded-data-surfaces.spec.ts`
- `apps/web/tests/e2e/permissions/seeded-vote-comment.spec.ts`
- `apps/web/tests/e2e/permissions/seeded-trusted-overlay.spec.ts`
- `apps/web/tests/e2e/permissions/seeded-export-search.spec.ts`
- `apps/web/tests/e2e/permissions/seeded-media.spec.ts`
- `apps/api/README.md`

Seeded fixture coverage now includes:

- Users: `owner`, `admin`, `member`, `viewer`, `nonmember`, `trusted`, `trusted_lifecycle`
- Two projects: one `public`, one `restricted`
- Project memberships for `admin`, `member`, `viewer`; `trusted` and `nonmember` are not members
- One site, dataset, recording, clip, detection, and annotation per project
- A deterministic 12.5s / 48kHz / 2ch / 16-bit WAV fixture uploaded idempotently to the seeded recording paths in local storage
- One completed, storage-free search session per project
- One completed exportable search session per project with deterministic one-match results, a seeded embedding for `/export-recordings` CSV payload coverage, and one S3-backed reference WAV object for `/reference-audio/0` stream coverage
- Accepted trusted invitation and active `ProjectTrustedUser` overlay for the trusted user on both projects
- Disposable restricted-project trusted lifecycle overlays: one active row reset by the seeder and one expired row for status-filter coverage
- One raw API key per seeded user for `/api/v1` programmatic checks
- JSON `env` payload with emails, TOTP secrets, project IDs, site IDs, dataset IDs, recording IDs, clip IDs, detection IDs, annotation IDs, search session IDs, trusted overlay IDs, trusted lifecycle IDs, and API keys

Important design notes:

- `/api/v1` is the API key surface. Do not use web JWT bearer tokens there; use the seeded `E2E_*_API_KEY` values.
- `/web-api/v1` remains the browser/session BFF surface and uses UI login plus session cookies. `getBearerTokenAfterLogin()` is only used where a BFF route explicitly accepts Authorization.
- Public project authenticated users may receive broader public overlay permissions than their member role alone would imply. The feature spec expectations were adjusted from observed backend behavior.
- Restricted project nonmember vote/comment currently succeeds because the seeded restricted config has `allow_voting_and_comments=true`.
- Trusted overlay capabilities are validated primarily through API behavior because frontend `can()` does not model trusted overlays.
- Trusted lifecycle mutation is API-primary and mutates only disposable restricted-project lifecycle overlays. Re-run the seeder before rerunning the trusted lifecycle suite because it intentionally revokes the disposable active overlay.
- Export/Search coverage is API-primary. It asserts permission status and CSV content type for allowed export responses, dataset ZIP shape for `include_audio=false`, dataset ZIP audio inclusion across the role/visibility matrix for allowed `include_audio=true` cases, storage-free `export-recordings` / `reference-audio` gate boundaries, a deterministic successful `export-recordings` CSV payload for owner access, and successful full plus Range reference-audio streaming for owner access. It intentionally avoids broader streaming CSV row coverage beyond the seeded exportable session.
- Media coverage verifies real bytes/content types for recording audio, playback, spectrogram, and download endpoints; clip audio, spectrogram, and download endpoints; guest recording media behavior; owner/trusted recording browser media smoke; and owner/trusted clip browser BFF media-token wiring.
- Dataset export with `include_audio=true` now uses the same S3-backed local resolution path as media endpoints and is covered across allowed role/visibility cases by ZIP entry plus WAV `RIFF` payload assertions. Current search storage guard checks assert allowed callers get fixture-missing 404 details and denied callers get 403 before storage lookup; the separate exportable search sessions cover one successful `export-recordings` CSV payload path and one successful S3-backed `reference-audio/0` full/Range stream path.

Verified commands after the current baseline:

```bash
docker exec -e DEBUG=false echoroo-backend uv run python -m echoroo.scripts.seed_e2e_permissions --confirm > /tmp/echoroo-e2e-seed.json

RUFF_CACHE_DIR=/tmp/echoroo-ruff-cache ruff check apps/api/echoroo/scripts/seed_e2e_permissions.py
RUFF_CACHE_DIR=/tmp/echoroo-ruff-cache ruff format --check apps/api/echoroo/scripts/seed_e2e_permissions.py
python3 -m py_compile apps/api/echoroo/scripts/seed_e2e_permissions.py

cd apps/web
npx prettier --check tests/e2e/permissions/seeded-permissions.helpers.ts tests/e2e/permissions/seeded-permissions-matrix.spec.ts tests/e2e/permissions/seeded-feature-permissions.spec.ts
npx eslint tests/e2e/permissions/seeded-permissions.helpers.ts tests/e2e/permissions/seeded-permissions-matrix.spec.ts tests/e2e/permissions/seeded-feature-permissions.spec.ts
```

Green browser runs:

```bash
cd apps/web
set -a
source <(jq -r '.env | to_entries[] | "\(.key)=\(.value|@sh)"' /tmp/echoroo-e2e-seed.json)
set +a

E2E_FEATURE_PERMISSIONS_ENABLED=1 ECHOROO_API_URL=http://localhost:8002 PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test tests/e2e/permissions/seeded-feature-permissions.spec.ts --reporter=list --workers=1
# 7 passed

E2E_PERMISSIONS_MATRIX_ENABLED=1 ECHOROO_API_URL=http://localhost:8002 PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test tests/e2e/permissions/seeded-permissions-matrix.spec.ts --reporter=list --workers=1
# 10 passed
```

Verified after Data Surfaces and Vote/Comment expansion:

```bash
docker exec -e DEBUG=false echoroo-backend uv run python -m echoroo.scripts.seed_e2e_permissions --confirm > /tmp/echoroo-e2e-seed.json

cd apps/web
set -a
source <(jq -r '.env | to_entries[] | "\(.key)=\(.value|@sh)"' /tmp/echoroo-e2e-seed.json)
set +a

E2E_DATA_SURFACES_ENABLED=1 ECHOROO_API_URL=http://localhost:8002 PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test tests/e2e/permissions/seeded-data-surfaces.spec.ts --reporter=list --workers=1
# 13 passed, 12 skipped

E2E_VOTE_COMMENT_ENABLED=1 ECHOROO_API_URL=http://localhost:8002 PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test tests/e2e/permissions/seeded-vote-comment.spec.ts --reporter=list --workers=1
# 12 passed

E2E_FEATURE_PERMISSIONS_ENABLED=1 ECHOROO_API_URL=http://localhost:8002 PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test tests/e2e/permissions/seeded-feature-permissions.spec.ts --reporter=list --workers=1
# 7 passed

E2E_PERMISSIONS_MATRIX_ENABLED=1 ECHOROO_API_URL=http://localhost:8002 PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test tests/e2e/permissions/seeded-permissions-matrix.spec.ts --reporter=list --workers=1
# 10 passed
```

Final cross-cutting validation:

```bash
git diff --check

RUFF_CACHE_DIR=/tmp/echoroo-ruff-cache ruff check apps/api/echoroo/scripts/seed_e2e_permissions.py
RUFF_CACHE_DIR=/tmp/echoroo-ruff-cache ruff format --check apps/api/echoroo/scripts/seed_e2e_permissions.py
PYTHONPYCACHEPREFIX=/tmp/echoroo-pycache python3 -m py_compile apps/api/echoroo/scripts/seed_e2e_permissions.py

cd apps/api
UV_PROJECT_ENVIRONMENT=/tmp/echoroo-api-mypy-venv uv run mypy echoroo/scripts/seed_e2e_permissions.py

cd apps/web
npx prettier --check tests/e2e/permissions/seeded-permissions.helpers.ts tests/e2e/permissions/seeded-permissions-matrix.spec.ts tests/e2e/permissions/seeded-feature-permissions.spec.ts tests/e2e/permissions/seeded-data-surfaces.spec.ts tests/e2e/permissions/seeded-vote-comment.spec.ts
npx eslint tests/e2e/permissions/seeded-permissions.helpers.ts tests/e2e/permissions/seeded-permissions-matrix.spec.ts tests/e2e/permissions/seeded-feature-permissions.spec.ts tests/e2e/permissions/seeded-data-surfaces.spec.ts tests/e2e/permissions/seeded-vote-comment.spec.ts
npm run check
# 0 errors, 18 existing warnings in 7 files

E2E_FEATURE_PERMISSIONS_ENABLED=1 E2E_PERMISSIONS_MATRIX_ENABLED=1 E2E_DATA_SURFACES_ENABLED=1 E2E_VOTE_COMMENT_ENABLED=1 \
ECHOROO_API_URL=http://localhost:8002 PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test \
    tests/e2e/permissions/seeded-feature-permissions.spec.ts \
    tests/e2e/permissions/seeded-permissions-matrix.spec.ts \
    tests/e2e/permissions/seeded-data-surfaces.spec.ts \
    tests/e2e/permissions/seeded-vote-comment.spec.ts \
    --reporter=list --workers=1
# 42 passed, 12 skipped
```

Verified after Trusted Overlay read-only expansion:

```bash
docker exec -e DEBUG=false echoroo-backend uv run python -m echoroo.scripts.seed_e2e_permissions --confirm > /tmp/echoroo-e2e-seed.json

cd apps/web
set -a
source <(jq -r '.env | to_entries[] | "\(.key)=\(.value|@sh)"' /tmp/echoroo-e2e-seed.json)
set +a

E2E_TRUSTED_OVERLAY_ENABLED=1 ECHOROO_API_URL=http://localhost:8002 PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test tests/e2e/permissions/seeded-trusted-overlay.spec.ts --reporter=list --workers=1
# 7 passed

npx prettier --check tests/e2e/permissions/seeded-permissions.helpers.ts tests/e2e/permissions/seeded-permissions-matrix.spec.ts tests/e2e/permissions/seeded-feature-permissions.spec.ts tests/e2e/permissions/seeded-data-surfaces.spec.ts tests/e2e/permissions/seeded-vote-comment.spec.ts tests/e2e/permissions/seeded-trusted-overlay.spec.ts
npx eslint tests/e2e/permissions/seeded-permissions.helpers.ts tests/e2e/permissions/seeded-permissions-matrix.spec.ts tests/e2e/permissions/seeded-feature-permissions.spec.ts tests/e2e/permissions/seeded-data-surfaces.spec.ts tests/e2e/permissions/seeded-vote-comment.spec.ts tests/e2e/permissions/seeded-trusted-overlay.spec.ts
npm run check
# 0 errors, 18 existing warnings in 7 files

E2E_FEATURE_PERMISSIONS_ENABLED=1 E2E_PERMISSIONS_MATRIX_ENABLED=1 E2E_DATA_SURFACES_ENABLED=1 E2E_VOTE_COMMENT_ENABLED=1 E2E_TRUSTED_OVERLAY_ENABLED=1 \
ECHOROO_API_URL=http://localhost:8002 PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test \
    tests/e2e/permissions/seeded-feature-permissions.spec.ts \
    tests/e2e/permissions/seeded-permissions-matrix.spec.ts \
    tests/e2e/permissions/seeded-data-surfaces.spec.ts \
    tests/e2e/permissions/seeded-vote-comment.spec.ts \
    tests/e2e/permissions/seeded-trusted-overlay.spec.ts \
    --reporter=list --workers=1
# 49 passed, 12 skipped
```

Verified after Trusted Overlay lifecycle expansion:

```bash
docker exec -e DEBUG=false echoroo-backend uv run python -m echoroo.scripts.seed_e2e_permissions --confirm > /tmp/echoroo-e2e-seed.json

RUFF_CACHE_DIR=/tmp/echoroo-ruff-cache ruff check apps/api/echoroo/scripts/seed_e2e_permissions.py
RUFF_CACHE_DIR=/tmp/echoroo-ruff-cache ruff format --check apps/api/echoroo/scripts/seed_e2e_permissions.py
PYTHONPYCACHEPREFIX=/tmp/echoroo-pycache python3 -m py_compile apps/api/echoroo/scripts/seed_e2e_permissions.py

cd apps/api
UV_PROJECT_ENVIRONMENT=/tmp/echoroo-api-mypy-venv uv run mypy echoroo/scripts/seed_e2e_permissions.py

cd apps/web
set -a
source <(jq -r '.env | to_entries[] | "\(.key)=\(.value|@sh)"' /tmp/echoroo-e2e-seed.json)
set +a

E2E_TRUSTED_OVERLAY_ENABLED=1 ECHOROO_API_URL=http://localhost:8002 PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test tests/e2e/permissions/seeded-trusted-overlay.spec.ts --reporter=list --workers=1
# 13 passed

npx prettier --check tests/e2e/permissions/seeded-permissions.helpers.ts tests/e2e/permissions/seeded-permissions-matrix.spec.ts tests/e2e/permissions/seeded-feature-permissions.spec.ts tests/e2e/permissions/seeded-data-surfaces.spec.ts tests/e2e/permissions/seeded-vote-comment.spec.ts tests/e2e/permissions/seeded-trusted-overlay.spec.ts tests/e2e/permissions/seeded-export-search.spec.ts
npx eslint tests/e2e/permissions/seeded-permissions.helpers.ts tests/e2e/permissions/seeded-permissions-matrix.spec.ts tests/e2e/permissions/seeded-feature-permissions.spec.ts tests/e2e/permissions/seeded-data-surfaces.spec.ts tests/e2e/permissions/seeded-vote-comment.spec.ts tests/e2e/permissions/seeded-trusted-overlay.spec.ts tests/e2e/permissions/seeded-export-search.spec.ts
npm run check
# 0 errors, 18 existing warnings in 7 files

E2E_FEATURE_PERMISSIONS_ENABLED=1 E2E_PERMISSIONS_MATRIX_ENABLED=1 E2E_DATA_SURFACES_ENABLED=1 E2E_VOTE_COMMENT_ENABLED=1 E2E_TRUSTED_OVERLAY_ENABLED=1 E2E_EXPORT_SEARCH_ENABLED=1 \
ECHOROO_API_URL=http://localhost:8002 PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test \
    tests/e2e/permissions/seeded-feature-permissions.spec.ts \
    tests/e2e/permissions/seeded-permissions-matrix.spec.ts \
    tests/e2e/permissions/seeded-data-surfaces.spec.ts \
    tests/e2e/permissions/seeded-vote-comment.spec.ts \
    tests/e2e/permissions/seeded-trusted-overlay.spec.ts \
    tests/e2e/permissions/seeded-export-search.spec.ts \
    --reporter=list --workers=1
# 61 passed, 12 skipped
```

Claude review completed for the trusted lifecycle seed/spec changes. It found no
blocking issues. A non-blocking active-row lookup polish was applied so active
trusted overlays are reused by `(project_id, user_id, status=active)` before
insert.

Verified after Export/Search API-primary expansion:

```bash
docker exec -e DEBUG=false echoroo-backend uv run python -m echoroo.scripts.seed_e2e_permissions --confirm > /tmp/echoroo-e2e-seed.json

RUFF_CACHE_DIR=/tmp/echoroo-ruff-cache ruff check apps/api/echoroo/scripts/seed_e2e_permissions.py
RUFF_CACHE_DIR=/tmp/echoroo-ruff-cache ruff format --check apps/api/echoroo/scripts/seed_e2e_permissions.py
PYTHONPYCACHEPREFIX=/tmp/echoroo-pycache python3 -m py_compile apps/api/echoroo/scripts/seed_e2e_permissions.py

cd apps/api
UV_PROJECT_ENVIRONMENT=/tmp/echoroo-api-mypy-venv uv run mypy echoroo/scripts/seed_e2e_permissions.py

cd apps/web
set -a
source <(jq -r '.env | to_entries[] | "\(.key)=\(.value|@sh)"' /tmp/echoroo-e2e-seed.json)
set +a

E2E_EXPORT_SEARCH_ENABLED=1 ECHOROO_API_URL=http://localhost:8002 PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test tests/e2e/permissions/seeded-export-search.spec.ts --reporter=list --workers=1
# 6 passed

npx prettier --check tests/e2e/permissions/seeded-permissions.helpers.ts tests/e2e/permissions/seeded-permissions-matrix.spec.ts tests/e2e/permissions/seeded-feature-permissions.spec.ts tests/e2e/permissions/seeded-data-surfaces.spec.ts tests/e2e/permissions/seeded-vote-comment.spec.ts tests/e2e/permissions/seeded-trusted-overlay.spec.ts tests/e2e/permissions/seeded-export-search.spec.ts
npx eslint tests/e2e/permissions/seeded-permissions.helpers.ts tests/e2e/permissions/seeded-permissions-matrix.spec.ts tests/e2e/permissions/seeded-feature-permissions.spec.ts tests/e2e/permissions/seeded-data-surfaces.spec.ts tests/e2e/permissions/seeded-vote-comment.spec.ts tests/e2e/permissions/seeded-trusted-overlay.spec.ts tests/e2e/permissions/seeded-export-search.spec.ts
npm run check
# 0 errors, 18 existing warnings in 7 files

E2E_FEATURE_PERMISSIONS_ENABLED=1 E2E_PERMISSIONS_MATRIX_ENABLED=1 E2E_DATA_SURFACES_ENABLED=1 E2E_VOTE_COMMENT_ENABLED=1 E2E_TRUSTED_OVERLAY_ENABLED=1 E2E_EXPORT_SEARCH_ENABLED=1 \
ECHOROO_API_URL=http://localhost:8002 PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test \
    tests/e2e/permissions/seeded-feature-permissions.spec.ts \
    tests/e2e/permissions/seeded-permissions-matrix.spec.ts \
    tests/e2e/permissions/seeded-data-surfaces.spec.ts \
    tests/e2e/permissions/seeded-vote-comment.spec.ts \
    tests/e2e/permissions/seeded-trusted-overlay.spec.ts \
    tests/e2e/permissions/seeded-export-search.spec.ts \
    --reporter=list --workers=1
# 55 passed, 12 skipped
```

Verified after Search storage gate guard expansion:

```bash
docker exec -e DEBUG=false echoroo-backend uv run python -m echoroo.scripts.seed_e2e_permissions --confirm > /tmp/echoroo-e2e-seed.json

cd apps/api
RUFF_CACHE_DIR=/tmp/echoroo-ruff-cache ruff check echoroo/api/v1/search/sessions.py echoroo/scripts/seed_e2e_permissions.py echoroo/api/v1/clips.py
RUFF_CACHE_DIR=/tmp/echoroo-ruff-cache ruff format --check echoroo/api/v1/search/sessions.py echoroo/scripts/seed_e2e_permissions.py echoroo/api/v1/clips.py
PYTHONPYCACHEPREFIX=/tmp/echoroo-pycache python3 -m py_compile echoroo/api/v1/search/sessions.py echoroo/scripts/seed_e2e_permissions.py echoroo/api/v1/clips.py
UV_PROJECT_ENVIRONMENT=/tmp/echoroo-api-mypy-venv uv run mypy echoroo/api/v1/search/sessions.py echoroo/scripts/seed_e2e_permissions.py echoroo/api/v1/clips.py

cd apps/web
npx prettier --check tests/e2e/permissions/seeded-export-search.spec.ts
npx eslint tests/e2e/permissions/seeded-export-search.spec.ts
npm run check
# 0 errors, 18 existing warnings in 7 files

set -a
source <(jq -r '.env | to_entries[] | "\(.key)=\(.value|@sh)"' /tmp/echoroo-e2e-seed.json)
set +a

E2E_EXPORT_SEARCH_ENABLED=1 ECHOROO_API_URL=http://localhost:8002 PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test tests/e2e/permissions/seeded-export-search.spec.ts --reporter=list --workers=1
# 6 passed

E2E_PERMISSIONS_MATRIX_ENABLED=1 E2E_FEATURE_PERMISSIONS_ENABLED=1 E2E_DATA_SURFACES_ENABLED=1 E2E_VOTE_COMMENT_ENABLED=1 E2E_TRUSTED_OVERLAY_ENABLED=1 E2E_EXPORT_SEARCH_ENABLED=1 E2E_MEDIA_ENABLED=1 \
ECHOROO_API_URL=http://localhost:8002 PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test tests/e2e/permissions/seeded-*.spec.ts --reporter=list --workers=1
# 77 passed, 12 skipped
```

Verified after Export-recordings success CSV expansion:

```bash
docker exec -e DEBUG=false echoroo-backend uv run python -m echoroo.scripts.seed_e2e_permissions --confirm > /tmp/echoroo-e2e-seed.json

cd apps/api
RUFF_CACHE_DIR=/tmp/echoroo-ruff-cache ruff check echoroo/scripts/seed_e2e_permissions.py echoroo/api/v1/search/sessions.py echoroo/api/v1/clips.py
RUFF_CACHE_DIR=/tmp/echoroo-ruff-cache ruff format --check echoroo/scripts/seed_e2e_permissions.py echoroo/api/v1/search/sessions.py echoroo/api/v1/clips.py
PYTHONPYCACHEPREFIX=/tmp/echoroo-pycache python3 -m py_compile echoroo/scripts/seed_e2e_permissions.py echoroo/api/v1/search/sessions.py echoroo/api/v1/clips.py
UV_PROJECT_ENVIRONMENT=/tmp/echoroo-api-mypy-venv uv run mypy echoroo/scripts/seed_e2e_permissions.py echoroo/api/v1/search/sessions.py echoroo/api/v1/clips.py

cd apps/web
npx prettier --check tests/e2e/permissions/seeded-export-search.spec.ts
npx eslint tests/e2e/permissions/seeded-export-search.spec.ts
npm run check
# 0 errors, 18 existing warnings in 7 files

set -a
source <(jq -r '.env | to_entries[] | "\(.key)=\(.value|@sh)"' /tmp/echoroo-e2e-seed.json)
set +a

E2E_EXPORT_SEARCH_ENABLED=1 ECHOROO_API_URL=http://localhost:8002 PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test tests/e2e/permissions/seeded-export-search.spec.ts --reporter=list --workers=1
# 7 passed

E2E_PERMISSIONS_MATRIX_ENABLED=1 E2E_FEATURE_PERMISSIONS_ENABLED=1 E2E_DATA_SURFACES_ENABLED=1 E2E_VOTE_COMMENT_ENABLED=1 E2E_TRUSTED_OVERLAY_ENABLED=1 E2E_EXPORT_SEARCH_ENABLED=1 E2E_MEDIA_ENABLED=1 \
ECHOROO_API_URL=http://localhost:8002 PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test tests/e2e/permissions/seeded-*.spec.ts --reporter=list --workers=1
# 78 passed, 12 skipped
```

Claude review completed for the export-recordings success CSV seed/spec changes.
It found no blocking issues. The actionable E2E reliability notes were addressed
by replacing naive CSV splitting with a small quoted-cell parser and asserting
the seeded timestamp exactly. The export/search suite was re-run after that
follow-up:

```bash
cd apps/web
npx prettier --check tests/e2e/permissions/seeded-export-search.spec.ts
npx eslint tests/e2e/permissions/seeded-export-search.spec.ts

E2E_EXPORT_SEARCH_ENABLED=1 ECHOROO_API_URL=http://localhost:8002 PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test tests/e2e/permissions/seeded-export-search.spec.ts --reporter=list --workers=1
# 7 passed
```

Verified after Reference-audio success stream and Dataset audio ZIP expansion:

```bash
docker exec -e DEBUG=false echoroo-backend uv run python -m echoroo.scripts.seed_e2e_permissions --confirm > /tmp/echoroo-e2e-seed.json

cd apps/api
RUFF_CACHE_DIR=/tmp/echoroo-ruff-cache ruff check echoroo/api/v1/datasets.py echoroo/services/export.py echoroo/scripts/seed_e2e_permissions.py
RUFF_CACHE_DIR=/tmp/echoroo-ruff-cache ruff format --check echoroo/api/v1/datasets.py echoroo/services/export.py echoroo/scripts/seed_e2e_permissions.py
PYTHONPYCACHEPREFIX=/tmp/echoroo-pycache python3 -m py_compile echoroo/api/v1/datasets.py echoroo/services/export.py echoroo/scripts/seed_e2e_permissions.py
UV_PROJECT_ENVIRONMENT=/tmp/echoroo-api-mypy-venv uv run mypy echoroo/api/v1/datasets.py echoroo/services/export.py echoroo/scripts/seed_e2e_permissions.py

cd apps/web
npx prettier --check tests/e2e/permissions/seeded-export-search.spec.ts
npx eslint tests/e2e/permissions/seeded-export-search.spec.ts
npm run check
# 0 errors, 18 existing warnings in 7 files

set -a
source <(jq -r '.env | to_entries[] | "\(.key)=\(.value|@sh)"' /tmp/echoroo-e2e-seed.json)
set +a

E2E_EXPORT_SEARCH_ENABLED=1 ECHOROO_API_URL=http://localhost:8002 PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test tests/e2e/permissions/seeded-export-search.spec.ts --grep "owner can stream reference audio" --reporter=list --workers=1
# 1 passed

E2E_EXPORT_SEARCH_ENABLED=1 ECHOROO_API_URL=http://localhost:8002 PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test tests/e2e/permissions/seeded-export-search.spec.ts --reporter=list --workers=1
# 8 passed

E2E_PERMISSIONS_MATRIX_ENABLED=1 E2E_FEATURE_PERMISSIONS_ENABLED=1 E2E_DATA_SURFACES_ENABLED=1 E2E_VOTE_COMMENT_ENABLED=1 E2E_TRUSTED_OVERLAY_ENABLED=1 E2E_EXPORT_SEARCH_ENABLED=1 E2E_MEDIA_ENABLED=1 \
ECHOROO_API_URL=http://localhost:8002 PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test tests/e2e/permissions/seeded-*.spec.ts --reporter=list --workers=1
# 79 passed, 12 skipped

docker exec -e DEBUG=false echoroo-backend uv run python -m echoroo.scripts.seed_e2e_permissions --confirm > /tmp/echoroo-e2e-seed.json
```

Verified after Claude hygiene follow-up:

```bash
docker exec -e DEBUG=false echoroo-backend uv run python -m echoroo.scripts.seed_e2e_permissions --confirm > /tmp/echoroo-e2e-seed.json

jq '{user_keys: (.users.owner | keys), api_key_keys: (.api_keys.owner | keys), credential_keys: (.credentials | keys), env_has_owner_api_key: (.env.E2E_OWNER_API_KEY | type), env_has_owner_totp: (.env.E2E_OWNER_TOTP_SECRET | type)}' /tmp/echoroo-e2e-seed.json
# top-level users/api_keys/credentials expose env-name metadata only; env retains the raw secrets
jq -r '.env | to_entries[] | "export \(.key)=\(.value|@sh)"' /tmp/echoroo-e2e-seed.json > /tmp/echoroo-e2e.env

cd apps/api
RUFF_CACHE_DIR=/tmp/echoroo-ruff-cache ruff check echoroo/scripts/seed_e2e_permissions.py
RUFF_CACHE_DIR=/tmp/echoroo-ruff-cache ruff format --check echoroo/scripts/seed_e2e_permissions.py
PYTHONPYCACHEPREFIX=/tmp/echoroo-pycache python3 -m py_compile echoroo/scripts/seed_e2e_permissions.py
UV_PROJECT_ENVIRONMENT=/tmp/echoroo-api-mypy-venv uv run mypy echoroo/scripts/seed_e2e_permissions.py

cd apps/web
set -a
source /tmp/echoroo-e2e.env
set +a

E2E_EXPORT_SEARCH_ENABLED=1 \
  npx playwright test tests/e2e/permissions/seeded-export-search.spec.ts --reporter=line
# 8 passed

E2E_PERMISSIONS_MATRIX_ENABLED=1 E2E_FEATURE_PERMISSIONS_ENABLED=1 E2E_DATA_SURFACES_ENABLED=1 E2E_VOTE_COMMENT_ENABLED=1 E2E_TRUSTED_OVERLAY_ENABLED=1 E2E_EXPORT_SEARCH_ENABLED=1 E2E_MEDIA_ENABLED=1 \
ECHOROO_API_URL=http://localhost:8002 PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test tests/e2e/permissions/seeded-*.spec.ts --reporter=line --workers=1
# 79 passed, 12 skipped

docker exec -e DEBUG=false echoroo-backend uv run python -m echoroo.scripts.seed_e2e_permissions --confirm > /tmp/echoroo-e2e-seed.json
```

Claude review completed for the reference-audio success stream slice. It found
no blocking issues. A non-blocking operational note remains: unlike recording
media fixtures, reference-audio fixtures intentionally require S3/LocalStack
because the production route reads `SearchSession.reference_audio_keys` directly
through S3 and does not use `AUDIO_ROOT`.

Claude review completed for the dataset audio ZIP slice. It found no blocking
issues. Non-blocking residual risks remain around pre-existing synchronous ZIP
write work and in-memory ZIP construction for large datasets.

Earlier Claude review for the initial export/search seed/spec slice found no
blocking issues. Non-blocking notes are recorded below.

Verified after Media plus Clip browser expansion:

```bash
docker exec -e DEBUG=false echoroo-backend uv run python -m echoroo.scripts.seed_e2e_permissions --confirm > /tmp/echoroo-e2e-seed.json

cd apps/web
set -a
source <(jq -r '.env | to_entries[] | "\(.key)=\(.value|@sh)"' /tmp/echoroo-e2e-seed.json)
set +a

E2E_MEDIA_ENABLED=1 ECHOROO_API_URL=http://localhost:8002 PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test tests/e2e/permissions/seeded-media.spec.ts --grep "restricted recording detail wires media UI" --reporter=line --workers=1
# 2 passed

E2E_MEDIA_ENABLED=1 ECHOROO_API_URL=http://localhost:8002 PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test tests/e2e/permissions/seeded-media.spec.ts --reporter=list --workers=1
# 16 passed

E2E_FEATURE_PERMISSIONS_ENABLED=1 E2E_PERMISSIONS_MATRIX_ENABLED=1 E2E_DATA_SURFACES_ENABLED=1 E2E_VOTE_COMMENT_ENABLED=1 E2E_TRUSTED_OVERLAY_ENABLED=1 E2E_EXPORT_SEARCH_ENABLED=1 E2E_MEDIA_ENABLED=1 \
ECHOROO_API_URL=http://localhost:8002 PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test tests/e2e/permissions/seeded-*.spec.ts --reporter=list --workers=1
# 79 passed, 12 skipped

docker exec -e DEBUG=false echoroo-backend uv run python -m echoroo.scripts.seed_e2e_permissions --confirm > /tmp/echoroo-e2e-seed.json
```

Static verification after Media plus Clip browser expansion:

```bash
cd apps/api
RUFF_CACHE_DIR=/tmp/echoroo-ruff-cache ruff check echoroo/scripts/seed_e2e_permissions.py echoroo/api/v1/clips.py echoroo/api/web_v1/projects/_media.py
RUFF_CACHE_DIR=/tmp/echoroo-ruff-cache ruff format --check echoroo/scripts/seed_e2e_permissions.py echoroo/api/v1/clips.py echoroo/api/web_v1/projects/_media.py
PYTHONPYCACHEPREFIX=/tmp/echoroo-pycache python3 -m py_compile echoroo/scripts/seed_e2e_permissions.py echoroo/api/v1/clips.py echoroo/api/web_v1/projects/_media.py
UV_PROJECT_ENVIRONMENT=/tmp/echoroo-api-mypy-venv uv run mypy echoroo/scripts/seed_e2e_permissions.py echoroo/api/v1/clips.py echoroo/api/web_v1/projects/_media.py

cd apps/web
npx prettier --check src/lib/api/clips.ts tests/e2e/permissions/seeded-data-surfaces.spec.ts tests/e2e/permissions/seeded-export-search.spec.ts tests/e2e/permissions/seeded-feature-permissions.spec.ts tests/e2e/permissions/seeded-media.spec.ts tests/e2e/permissions/seeded-permissions-matrix.spec.ts tests/e2e/permissions/seeded-permissions.helpers.ts tests/e2e/permissions/seeded-trusted-overlay.spec.ts tests/e2e/permissions/seeded-vote-comment.spec.ts
npx eslint src/lib/api/clips.ts tests/e2e/permissions/seeded-data-surfaces.spec.ts tests/e2e/permissions/seeded-export-search.spec.ts tests/e2e/permissions/seeded-feature-permissions.spec.ts tests/e2e/permissions/seeded-media.spec.ts tests/e2e/permissions/seeded-permissions-matrix.spec.ts tests/e2e/permissions/seeded-permissions.helpers.ts tests/e2e/permissions/seeded-trusted-overlay.spec.ts tests/e2e/permissions/seeded-vote-comment.spec.ts
npm run check
# 0 errors, 18 warnings in 7 files
```

Claude review completed for the media seed/spec changes. Its actionable media
status-matrix concerns were addressed by explicit role/visibility/endpoint
expectation tables, a comment documenting restricted nonmember clip media
expectations, and guest clip media 401 checks; no media blocker remains. The
existing broad seeded API key scope remains a fixture-level residual risk.

## Operating Rules

Continue in small feature slices. Each slice must satisfy:

- Seed data is idempotent enough for local reruns.
- Required seed values are emitted in the JSON `env` payload.
- Static checks pass.
- The new Playwright suite passes in a real browser.
- Existing `seeded-permissions-matrix.spec.ts` and `seeded-feature-permissions.spec.ts` remain green.
- Any failure is classified as either test expectation drift, missing seed data, or product bug.

Use Claude CLI review selectively for riskier slices:

- Trusted overlay state changes
- Search/export data model changes
- Media/storage/audio fixture changes
- Security-sensitive API key or permission behavior

## Roadmap To Complete Items 1-5

### 1. Data Surfaces

Goal: Expand read/detail coverage for core project data pages.

Candidate spec:

- `apps/web/tests/e2e/permissions/seeded-data-surfaces.spec.ts`

Coverage:

- Dataset list and detail
- Recording list and detail
- Detection list and detail where stable
- Public explore list/detail
- Owner email and private metadata non-leak checks for public guest flows

Seed needs:

- Existing dataset/recording/detection seed is probably enough for list/detail.
- Add env IDs for `recording_id` and `detection_id` if deep links need them.
- Avoid asserting successful audio/spectrogram playback here; that belongs to item 5.

Completion gate:

- New data-surfaces suite green for stable surfaces.
- Detection detail tests are explicit skips because the current detection list contract does not return the seeded minimal annotation rows.
- Existing matrix and feature suites still green.

### 2. Vote / Comment

Goal: Make vote/comment behavior explicit beyond the broad feature spec.

Candidate spec:

- `apps/web/tests/e2e/permissions/seeded-vote-comment.spec.ts`

Coverage:

- `GET /api/v1/projects/{projectId}/annotations/{annotationId}/votes`
- `POST /api/v1/projects/{projectId}/annotations/{annotationId}/votes`
- `DELETE /api/v1/projects/{projectId}/annotations/{annotationId}/votes`
- `GET /api/v1/projects/{projectId}/annotations/{annotationId}/comments`
- `POST /api/v1/projects/{projectId}/annotations/{annotationId}/comments`
- Role and visibility expectations for owner/admin/member/viewer/nonmember/trusted
- UI smoke only if stable controls exist; API checks are the primary source.

Seed needs:

- Existing annotation seed is enough.
- Consider adding per-role/per-project annotation IDs if parallel mutation becomes flaky.

Completion gate:

- Suite green with `--workers=1`.
- Mutating tests run in a serial describe block and use same-user vote replacement before DELETE cleanup.

### 3. Trusted Overlay

Status: Read/list/capability and API-primary lifecycle mutation slices complete.

Goal: Cover trusted overlay management and lifecycle more deeply.

Candidate spec:

- `apps/web/tests/e2e/permissions/seeded-trusted-overlay.spec.ts`

Coverage:

- Owner sees invite form, active trusted user row, and enabled row action controls.
- Admin sees read-only notice/list and disabled edit/extend/revoke controls.
- Member/viewer/nonmember/trusted cannot access management UI.
- API checks prove the seeded trusted overlay grants restricted project export/search capability without membership.
- Owner PATCH permission edit and expiry extension on a disposable active overlay.
- Admin PATCH/DELETE denial for the disposable overlay.
- Owner DELETE revoke, revoked filter, and post-revoke capability denial.
- Owner fresh invite issuance after revoke.
- Expired seeded overlay status-filter coverage.
- Later: accept-token/re-grant activation through the invitation email token path.

Seed needs:

- Existing trusted overlay is enough for read/list and capability checks.
- Separate disposable trusted lifecycle target exists and is not a project member.
- Seeder resets one active lifecycle overlay and one expired lifecycle overlay for the restricted project.
- Future-suite gate checklist:
  - Suite path: `apps/web/tests/e2e/permissions/seeded-trusted-overlay.spec.ts`
  - Seed: one immutable baseline trusted overlay plus one disposable trusted invite target
  - Completion gate: read/list/capability checks green, lifecycle mutation resets its own disposable state, existing seeded suites remain green
  - Review gate: Claude review before edit/revoke/expire/re-grant lifecycle tests

Completion gate:

- Trusted overlay suite green with `E2E_TRUSTED_OVERLAY_ENABLED=1`.
- Full seeded permission Playwright set green with the trusted overlay suite included.
- No destructive lifecycle test mutates the baseline trusted overlay.
- Claude review completed with no blocking findings.

### 4. Export / Search

Status: API-primary read/status slice, dataset export ZIP smoke and audio ZIP,
storage-free `export-recordings` / `reference-audio` permission guard checks,
one deterministic successful `export-recordings` CSV payload check, and one
S3-backed successful `reference-audio` stream check are complete. Broader
storage-backed file assertions and broader CSV row/content assertions remain
planned.

Goal: Cover export and search workflows with realistic seed data.

Candidate spec:

- `apps/web/tests/e2e/permissions/seeded-export-search.spec.ts`

Coverage:

- Detection CSV export
- Search sessions list/detail
- Search session annotation CSV export
- Dataset ZIP export with `include_audio=false`: status/content type, `.zip`
  disposition, `PK` magic bytes, and `datapackage.json` / `deployments.csv` /
  `media.csv` entries
- Dataset ZIP export with `include_audio=true`: role/visibility status matrix,
  metadata entries for allowed responses, expected
  `data/e2e/{prefix}/{visibility}/fixture.wav` archive entry, and `RIFF` bytes
  after ZIP inflation
- Storage-free search-session guard checks:
  `export-recordings` returns 404 with `"Session has no results to export"` for
  allowed callers and 403 for denied callers; `reference-audio/0` returns 404
  with `"Reference audio source index 0 not found"` for allowed callers and 403
  for denied callers.
- Successful export-recordings check:
  owner exports a deterministic exportable search session for both seeded
  project visibilities and the CSV payload includes the expected header, seeded
  recording filename, `Testus permissionis`, `E2E Seed Species`, and `1.0000`
  similarity aggregate values.
- Successful reference-audio check:
  owner streams the deterministic reference WAV for both seeded project
  visibilities and the response includes audio content type, `Accept-Ranges:
  bytes`, `RIFF` bytes, and a `206` Range response for `bytes=0-3`.
- Role/visibility/API key expectations for export/search permissions
- Later: broader CSV content assertions after contract/storage review

Seed needs:

- Stable completed `SearchSession` rows are seeded for public and restricted
  projects and emitted as `E2E_PUBLIC_SEARCH_SESSION_ID` and
  `E2E_RESTRICTED_SEARCH_SESSION_ID`.
- Dataset export without audio is covered as a successful ZIP shape check.
  Dataset export with audio is covered across allowed role/visibility cases
  using the same seeded recording WAV objects and `AudioService.ensure_file_local()`
  path as media.
- Search session `export-recordings` and `reference-audio` routes now have
  explicit backend `gate_action()` guards before storage-backed session
  processing. The current seeded sessions intentionally have no results and no
  reference audio, so E2E asserts permission gates through 403 vs fixture-missing
  404 boundaries rather than successful payloads.
- Separate exportable search sessions are seeded for public and restricted
  projects and emitted as `E2E_PUBLIC_EXPORTABLE_SEARCH_SESSION_ID` and
  `E2E_RESTRICTED_EXPORTABLE_SEARCH_SESSION_ID`. Each has one deterministic
  `Embedding` row, one result match, and one S3-backed reference WAV key,
  letting `/export-recordings` produce a stable CSV and `/reference-audio/0`
  produce deterministic full and Range audio responses.
- Future-suite gate checklist:
  - Suite path: `apps/web/tests/e2e/permissions/seeded-export-search.spec.ts`
  - Seed: completed storage-free search sessions and env IDs for every seeded project visibility
  - Completion gate: permission-status checks separated from file-content checks, existing seeded suites remain green
  - Review gate: Claude review for search/export contracts and any CSV/file payload assertions

Completion gate:

- Search/export suite green with `E2E_EXPORT_SEARCH_ENABLED=1`.
- Full seeded permission Playwright set green with the export/search suite included.
- Claude review completed with no blocking findings.

### 5. Media

Status: Complete for recording media endpoint bytes, clip media endpoint bytes,
representative recording browser media wiring, and clip browser BFF media-token
wiring.

Goal: Test actual browser media surfaces.

Candidate spec:

- `apps/web/tests/e2e/permissions/seeded-media.spec.ts`

Coverage:

- Recording audio endpoint bytes/content type through `/api/v1`
- Playback endpoint bytes/content type through `/api/v1`
- Spectrogram endpoint PNG bytes/content type through `/api/v1`
- Recording download bytes/content type through `/api/v1`
- Clip audio endpoint bytes/content type through `/api/v1`
- Clip spectrogram endpoint PNG bytes/content type through `/api/v1`
- Clip download bytes/content type through `/api/v1`, including current
  `DOWNLOAD` permission behavior on restricted projects
- Guest public/restricted recording media behavior with explicit status expectations
- Guest clip media authentication requirement with explicit 401 expectations
- Owner/trusted restricted recording detail smoke for BFF media token,
  playback, and spectrogram wiring
- Owner/trusted restricted recording detail smoke for clip list/detail BFF
  routes and tokenized clip preview/detail spectrogram plus playback wiring

Seed needs:

- Seeder now generates a deterministic 12.5s / 48kHz / 2ch / 16-bit WAV
  matching the recording metadata.
- The WAV is uploaded idempotently to LocalStack/S3 at each seeded
  `Recording.path`; if S3 is unavailable, the seeder writes the same fixture
  below `AUDIO_ROOT` so `AudioService.ensure_file_local()` can resolve it.
- The seeder creates one stable clip per seeded recording and emits
  `E2E_PUBLIC_CLIP_ID` and `E2E_RESTRICTED_CLIP_ID`.
- Clip media endpoints resolve the parent recording through
  `AudioService.ensure_file_local()` before audio processing, matching the
  S3-first recording fixture strategy.

Completion gate:

- `E2E_MEDIA_ENABLED=1` suite green with 16 passing tests.
- Full seeded permission Playwright set green with Media included.
- API and guest status expectations are explicit in the suite.
- Clip browser list/detail calls use `/web-api/v1` session routes, and preview,
  detail spectrogram, and playback URLs include scoped media tokens.
- Claude review completed; the status matrix was tightened, the clip-row selector
  was scoped to the preview image row, and no media blocker remains.

## Known Review Notes

Claude review flagged several broader risks. Applied hygiene fixes: seeded API key raw secrets are no longer deterministic, top-level seed JSON no longer duplicates raw TOTP/API-key secrets, seeded API key grants are role-scoped, project lookup is narrowed by owner, and fixture-user Redis 2FA failure/lockout keys are reset best-effort. Remaining notes to keep in mind:

- Seeder currently rotates TOTP/security stamps/API keys on rerun. This is acceptable for local E2E if the latest JSON env is always used, but it invalidates old sessions.
- Public/restricted vote/comment expectations should stay aligned with the canonical permission matrix and current restricted toggles.
- README examples write sensitive JSON to `/tmp`; treat it as local-only test material and delete it when done.
- Data Surfaces intentionally avoids audio/spectrogram/download byte assertions; the completed Media suite owns those checks.
- Trusted Overlay lifecycle intentionally avoids invitation accept/re-grant activation because the signed invite token is delivered through email/outbox and is not returned by the API. The current suite covers fresh invite issuance only.
- Trusted Overlay lifecycle leaves the disposable active overlay revoked after the suite. Run the seeder before rerunning this suite or the full seeded set.
- Export/Search CSV checks validate status and content type for standard exports; the exportable search session also validates one deterministic `export-recordings` CSV body. Dataset ZIP export validates archive shape with `include_audio=false`.
- Search `export-recordings` is covered both as a storage-free gate guard and as one deterministic successful CSV payload using the exportable seeded sessions. `reference-audio` is covered both as a storage-free gate guard and as one deterministic successful full/Range WAV stream using the exportable seeded sessions.
- Reference-audio fixture seeding requires S3/LocalStack. This is intentional because the route does not use the recording media `AUDIO_ROOT` fallback.
- Dataset export with audio is covered across allowed role/visibility cases for the seeded single-recording fixture. Broader dataset ZIP payload breadth remains future scope. Dataset export without audio is covered by ZIP shape and manifest-entry checks.
- Media covers recording audio/playback/spectrogram/download, clip audio/spectrogram/download, and clip browser UI/BFF media-token wiring through the restricted recording detail smoke.
- Clip preview loading currently issues one scoped media token per listed clip.
  This is acceptable for the seeded fixture size but can be revisited if clip
  lists become large.
- The media seeder falls back to writing below `AUDIO_ROOT` if LocalStack/S3 is unavailable, so successful local runs should still watch for S3 fixture drift in CI-like stacks.
- Guest public explore BFF list currently returns restricted project metadata, so Data Surfaces asserts private metadata non-leak instead of restricted ID absence.
- Public explore detail UI can remain in a loading state in the local SSR/dev setup; the suite verifies guest detail through the BFF detail and recording-list contracts plus UI non-leak checks.
