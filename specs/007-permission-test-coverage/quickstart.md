# Quickstart: Seeded Permission E2E Coverage

## 1. Seed Local Fixtures

```bash
docker exec -e DEBUG=false echoroo-backend \
  uv run python -m echoroo.scripts.seed_e2e_permissions --confirm \
  > /tmp/echoroo-e2e-seed.json
```

## 2. Export Seed Environment

```bash
cd /home/okamoto/Projects/echoroo/apps/web
set -a
source <(jq -r '.env | to_entries[] | "\(.key)=\(.value|@sh)"' /tmp/echoroo-e2e-seed.json)
set +a
```

## 3. Run Existing Green Baseline

```bash
E2E_FEATURE_PERMISSIONS_ENABLED=1 \
ECHOROO_API_URL=http://localhost:8002 \
PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test tests/e2e/permissions/seeded-feature-permissions.spec.ts \
  --reporter=list --workers=1

E2E_PERMISSIONS_MATRIX_ENABLED=1 \
ECHOROO_API_URL=http://localhost:8002 \
PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test tests/e2e/permissions/seeded-permissions-matrix.spec.ts \
  --reporter=list --workers=1
```

## 4. Run New Slice Suites

Data surfaces:

```bash
E2E_DATA_SURFACES_ENABLED=1 \
ECHOROO_API_URL=http://localhost:8002 \
PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test tests/e2e/permissions/seeded-data-surfaces.spec.ts \
  --reporter=list --workers=1
```

Vote/comment:

```bash
E2E_VOTE_COMMENT_ENABLED=1 \
ECHOROO_API_URL=http://localhost:8002 \
PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test tests/e2e/permissions/seeded-vote-comment.spec.ts \
  --reporter=list --workers=1
```

Trusted overlay:

```bash
E2E_TRUSTED_OVERLAY_ENABLED=1 \
ECHOROO_API_URL=http://localhost:8002 \
PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test tests/e2e/permissions/seeded-trusted-overlay.spec.ts \
  --reporter=list --workers=1
```

The trusted overlay suite includes lifecycle mutation coverage for disposable
restricted-project overlays. Re-run the seed command before rerunning this suite
or the full seeded set because the lifecycle tests intentionally revoke the
disposable active overlay.

Export/search:

```bash
E2E_EXPORT_SEARCH_ENABLED=1 \
ECHOROO_API_URL=http://localhost:8002 \
PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test tests/e2e/permissions/seeded-export-search.spec.ts \
  --reporter=list --workers=1
```

The export/search suite covers search session list/detail, detection and search
CSV export status/content type, dataset ZIP export with `include_audio=false`,
and role/visibility matrix dataset ZIP export with `include_audio=true`.
It also covers storage-free `export-recordings` and `reference-audio/0`
permission guard boundaries through expected 403 vs fixture-missing 404
responses, plus one deterministic successful `export-recordings` CSV body for
seeded exportable search sessions and one deterministic successful
`reference-audio/0` full/Range WAV stream for owner access. The audio-backed
dataset ZIP assertions run across the role/visibility matrix for allowed cases
and verify the expected archive entry plus inflated WAV `RIFF` bytes. Broader
CSV row body assertions remain separate storage-contract follow-ups.

Media:

```bash
E2E_MEDIA_ENABLED=1 \
ECHOROO_API_URL=http://localhost:8002 \
PUBLIC_API_URL=http://localhost:8002 \
  npx playwright test tests/e2e/permissions/seeded-media.spec.ts \
  --reporter=list --workers=1
```

The media suite requires the latest seed run because the seeder uploads a real
deterministic WAV fixture to each seeded recording path and emits stable clip
IDs for clip media checks. It covers API-primary clip media bytes and
recording-detail clip browser BFF media-token wiring.

## 5. Static Checks

```bash
RUFF_CACHE_DIR=/tmp/echoroo-ruff-cache \
  ruff check apps/api/echoroo/scripts/seed_e2e_permissions.py \
    apps/api/echoroo/api/v1/clips.py \
    apps/api/echoroo/api/v1/search/sessions.py \
    apps/api/echoroo/api/web_v1/projects/_media.py

RUFF_CACHE_DIR=/tmp/echoroo-ruff-cache \
  ruff format --check apps/api/echoroo/scripts/seed_e2e_permissions.py \
    apps/api/echoroo/api/v1/clips.py \
    apps/api/echoroo/api/v1/search/sessions.py \
    apps/api/echoroo/api/web_v1/projects/_media.py

python3 -m py_compile apps/api/echoroo/scripts/seed_e2e_permissions.py \
  apps/api/echoroo/api/v1/clips.py \
  apps/api/echoroo/api/v1/search/sessions.py \
  apps/api/echoroo/api/web_v1/projects/_media.py

cd /home/okamoto/Projects/echoroo/apps/api
uv run mypy echoroo/scripts/seed_e2e_permissions.py \
  echoroo/api/v1/clips.py \
  echoroo/api/v1/search/sessions.py \
  echoroo/api/web_v1/projects/_media.py

cd /home/okamoto/Projects/echoroo/apps/web
npx prettier --check src/lib/api/clips.ts \
  tests/e2e/permissions/seeded-permissions.helpers.ts \
  tests/e2e/permissions/seeded-permissions-matrix.spec.ts \
  tests/e2e/permissions/seeded-feature-permissions.spec.ts \
  tests/e2e/permissions/seeded-data-surfaces.spec.ts \
  tests/e2e/permissions/seeded-vote-comment.spec.ts \
  tests/e2e/permissions/seeded-trusted-overlay.spec.ts \
  tests/e2e/permissions/seeded-export-search.spec.ts \
  tests/e2e/permissions/seeded-media.spec.ts

npx eslint src/lib/api/clips.ts \
  tests/e2e/permissions/seeded-permissions.helpers.ts \
  tests/e2e/permissions/seeded-permissions-matrix.spec.ts \
  tests/e2e/permissions/seeded-feature-permissions.spec.ts \
  tests/e2e/permissions/seeded-data-surfaces.spec.ts \
  tests/e2e/permissions/seeded-vote-comment.spec.ts \
  tests/e2e/permissions/seeded-trusted-overlay.spec.ts \
  tests/e2e/permissions/seeded-export-search.spec.ts \
  tests/e2e/permissions/seeded-media.spec.ts

npm run check
```
