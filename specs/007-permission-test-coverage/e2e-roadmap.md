# Seeded Browser E2E Roadmap

**Status**: US1/US2/US3 plus Trusted Overlay lifecycle, Export/Search API-primary, Dataset ZIP export, Search storage gate guards, Export-recordings success CSV, and Media plus Clip API-primary complete
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
- One completed exportable search session per project with deterministic one-match results and a seeded embedding for `/export-recordings` CSV payload coverage
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
- Export/Search coverage is API-primary. It asserts permission status and CSV content type for allowed export responses, dataset ZIP shape for `include_audio=false`, storage-free `export-recordings` / `reference-audio` gate boundaries, and a deterministic successful `export-recordings` CSV payload for owner access. It intentionally avoids broader streaming CSV row coverage beyond the seeded exportable session.
- Media coverage verifies real bytes/content types for recording audio, playback, spectrogram, and download endpoints; clip audio, spectrogram, and download endpoints; guest recording media behavior; and owner/trusted browser media smoke.
- Successful reference-audio streaming and dataset export with `include_audio=true` are out of scope until their storage and payload contracts are reviewed. Current search storage guard checks assert allowed callers get fixture-missing 404 details and denied callers get 403 before storage lookup; the separate exportable search sessions cover one successful `export-recordings` CSV payload path.

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

Earlier Claude review for the initial export/search seed/spec slice found no
blocking issues. Non-blocking notes are recorded below.

Verified after Media expansion:

```bash
docker exec -e DEBUG=false echoroo-backend uv run python -m echoroo.scripts.seed_e2e_permissions --confirm > /tmp/echoroo-e2e-seed.json

cd apps/web
set -a
source <(jq -r '.env | to_entries[] | "\(.key)=\(.value|@sh)"' /tmp/echoroo-e2e-seed.json)
set +a

E2E_MEDIA_ENABLED=1 ECHOROO_API_URL=http://localhost:8002 PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test tests/e2e/permissions/seeded-media.spec.ts --reporter=list --workers=1
# 16 passed

E2E_FEATURE_PERMISSIONS_ENABLED=1 E2E_PERMISSIONS_MATRIX_ENABLED=1 E2E_DATA_SURFACES_ENABLED=1 E2E_VOTE_COMMENT_ENABLED=1 E2E_TRUSTED_OVERLAY_ENABLED=1 E2E_EXPORT_SEARCH_ENABLED=1 E2E_MEDIA_ENABLED=1 \
ECHOROO_API_URL=http://localhost:8002 PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test tests/e2e/permissions/seeded-*.spec.ts --reporter=list --workers=1
# 77 passed, 12 skipped
```

Static verification after Media expansion:

```bash
cd apps/api
RUFF_CACHE_DIR=/tmp/echoroo-ruff-cache ruff check echoroo/scripts/seed_e2e_permissions.py echoroo/api/v1/clips.py
RUFF_CACHE_DIR=/tmp/echoroo-ruff-cache ruff format --check echoroo/scripts/seed_e2e_permissions.py echoroo/api/v1/clips.py
PYTHONPYCACHEPREFIX=/tmp/echoroo-pycache python3 -m py_compile echoroo/scripts/seed_e2e_permissions.py echoroo/api/v1/clips.py
UV_PROJECT_ENVIRONMENT=/tmp/echoroo-api-mypy-venv uv run mypy echoroo/scripts/seed_e2e_permissions.py echoroo/api/v1/clips.py

cd apps/web
npx prettier --check tests/e2e/permissions/seeded-data-surfaces.spec.ts tests/e2e/permissions/seeded-export-search.spec.ts tests/e2e/permissions/seeded-feature-permissions.spec.ts tests/e2e/permissions/seeded-media.spec.ts tests/e2e/permissions/seeded-permissions-matrix.spec.ts tests/e2e/permissions/seeded-permissions.helpers.ts tests/e2e/permissions/seeded-trusted-overlay.spec.ts tests/e2e/permissions/seeded-vote-comment.spec.ts
npx eslint tests/e2e/permissions/seeded-data-surfaces.spec.ts tests/e2e/permissions/seeded-export-search.spec.ts tests/e2e/permissions/seeded-feature-permissions.spec.ts tests/e2e/permissions/seeded-media.spec.ts tests/e2e/permissions/seeded-permissions-matrix.spec.ts tests/e2e/permissions/seeded-permissions.helpers.ts tests/e2e/permissions/seeded-trusted-overlay.spec.ts tests/e2e/permissions/seeded-vote-comment.spec.ts
npm run check
# 0 errors, 18 existing warnings in 7 unrelated files
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

Status: API-primary read/status slice, dataset export ZIP smoke,
storage-free `export-recordings` / `reference-audio` permission guard checks,
and one deterministic successful `export-recordings` CSV payload check are
complete. Dataset export with audio, reference-audio streaming, broader
storage-backed file assertions, and broader CSV row/content assertions remain
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
- Role/visibility/API key expectations for export/search permissions
- Later: successful dataset export with audio, successful reference-audio
  streaming, and broader CSV content assertions after contract/storage review

Seed needs:

- Stable completed `SearchSession` rows are seeded for public and restricted
  projects and emitted as `E2E_PUBLIC_SEARCH_SESSION_ID` and
  `E2E_RESTRICTED_SEARCH_SESSION_ID`.
- Future dataset export with audio/export-recordings coverage still needs
  storage-backed payload validation and contract review.
- Dataset export without audio is covered as a successful ZIP shape check; keep
  audio-file inclusion in a separate storage-backed slice.
- Search session `export-recordings` and `reference-audio` routes now have
  explicit backend `gate_action()` guards before storage-backed session
  processing. The current seeded sessions intentionally have no results and no
  reference audio, so E2E asserts permission gates through 403 vs fixture-missing
  404 boundaries rather than successful payloads.
- Separate exportable search sessions are seeded for public and restricted
  projects and emitted as `E2E_PUBLIC_EXPORTABLE_SEARCH_SESSION_ID` and
  `E2E_RESTRICTED_EXPORTABLE_SEARCH_SESSION_ID`. Each has one deterministic
  `Embedding` row and one result match, letting `/export-recordings` produce a
  stable CSV without depending on S3/audio storage.
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
and representative browser media wiring. Clip browser wiring remains future
scope.

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
- Claude review completed; the status matrix was tightened and no media blocker remains.

## Known Review Notes

Claude review flagged several broader risks. Immediate fix already applied: seeded API key raw secrets are no longer deterministic. Remaining notes to keep in mind:

- Seeder currently rotates TOTP/security stamps/API keys on rerun. This is acceptable for local E2E if the latest JSON env is always used, but it invalidates old sessions.
- Project lookup by name is sufficient for current local fixture usage but not ideal for shared environments.
- Public/restricted vote/comment expectations should stay aligned with the canonical permission matrix and current restricted toggles.
- API key scopes are intentionally broad to let the central permission gate intersect with user/project permissions. If gate semantics change, revisit this.
- README examples write sensitive JSON to `/tmp`; treat it as local-only test material and delete it when done.
- Data Surfaces intentionally avoids audio/spectrogram/download byte assertions; the completed Media suite owns those checks.
- Trusted Overlay lifecycle intentionally avoids invitation accept/re-grant activation because the signed invite token is delivered through email/outbox and is not returned by the API. The current suite covers fresh invite issuance only.
- Trusted Overlay lifecycle leaves the disposable active overlay revoked after the suite. Run the seeder before rerunning this suite or the full seeded set.
- Export/Search CSV checks validate status and content type for standard exports; the exportable search session also validates one deterministic `export-recordings` CSV body. Dataset ZIP export validates archive shape with `include_audio=false`.
- Search `export-recordings` is covered both as a storage-free gate guard and as one deterministic successful CSV payload using the exportable seeded sessions. `reference-audio` is still covered only as a storage-free gate guard: allowed callers reach expected fixture-missing 404 details and denied callers receive 403. Successful reference-audio payload assertions remain out of scope until the permission and storage contracts are reviewed.
- Dataset export with audio remains out of scope until the permission and storage contracts are reviewed. Dataset export without audio is covered by ZIP shape and manifest-entry checks.
- Media covers recording audio/playback/spectrogram/download and clip audio/spectrogram/download. Clip browser UI/BFF media-token wiring remains future scope because the current completed browser smoke is recording-detail focused.
- The media seeder falls back to writing below `AUDIO_ROOT` if LocalStack/S3 is unavailable, so successful local runs should still watch for S3 fixture drift in CI-like stacks.
- Guest public explore BFF list currently returns restricted project metadata, so Data Surfaces asserts private metadata non-leak instead of restricted ID absence.
- Public explore detail UI can remain in a loading state in the local SSR/dev setup; the suite verifies guest detail through the BFF detail and recording-list contracts plus UI non-leak checks.
