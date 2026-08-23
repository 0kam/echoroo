# Internal Preview Bootstrap Guide

## 0. This Document's Role

This guide bootstraps an internal preview or internal user trial of Echoroo. It is for operators and product owners who need a working trial environment, initial admin, seed data, and invite path.

The spec/006 [quickstart](../../specs/006-permissions-redesign/quickstart.md) is implementer-focused and includes lower-level development checks. This document stays operator-focused and links out to detailed runbooks such as [release_readiness.md](../runbook/release_readiness.md), [email_verification.md](../runbook/email_verification.md), and [trusted_devices.md](../runbook/trusted_devices.md) instead of duplicating them.

## 1. Prerequisites

- Docker and Docker Compose are installed.
- The repository is cloned locally.
- `.env` is copied from `.env.example`.
- LocalStack KMS values are filled in `.env` for dev:

```bash
AWS_KMS_ENDPOINT=http://localstack:4566
AWS_KMS_REGION=us-east-1
AWS_KMS_CMK_2FA_ALIAS=alias/echoroo-2fa-dev
AWS_KMS_CMK_PII_HASH_ALIAS=alias/echoroo-pii-hash-dev
AWS_KMS_CMK_AUDIT_CHAIN_ALIAS=alias/echoroo-audit-chain-dev
AWS_KMS_CMK_INVITATION_HMAC_ALIAS=alias/echoroo-invitation-hmac-dev
```

## 2. Start Services

Start the dev stack:

```bash
./echoroo.sh start
```

Health checks:

```bash
docker logs echoroo-backend --tail 50
curl http://localhost:8002/health
```

Default ports are frontend `5173` and backend `8002`. The frontend port is driven by `ECHOROO_FRONTEND_PORT` in `.env`; the standard host setup re-publishes it on `3000` (see [DOCKER.md](../../DOCKER.md)). Open the frontend at whichever port the host stack uses — `http://localhost:3000` for the standard SSH-port-forwarded setup, `http://localhost:5173` if the container port is published unchanged. Override the backend port with `ECHOROO_API_PORT`.

## 3. Apply Migrations

The Docker entrypoint does not currently run migrations automatically. Apply them manually before creating users or seed data:

```bash
./echoroo.sh migrate
docker exec echoroo-backend uv run alembic current
```

## 4. Create Initial Superuser

Open `/setup` in the frontend and submit the initial administrator form. One admin is enough for an internal preview; production FR-111 requires at least three active superusers.

The setup screen creates the bootstrap superuser through `POST /api/v1/setup/initialize` and then displays the one-time TOTP secret, TOTP provisioning URI, QR code, 24-hour bootstrap token, and `webauthn_registration_url`.

Save the one-time output immediately. The plaintext TOTP secret and bootstrap token are not recoverable after leaving the success screen.

For the production requirement, register WebAuthn credentials within 24 hours. For preview only, the admin can log in with TOTP without completing WebAuthn registration.

## 5. Seed Initial Data (Optional)

Run the seeders only when the trial needs taxonomy or sensitivity data:

```bash
docker exec echoroo-backend uv run python -m echoroo.scripts.initial_iucn_sync
docker exec echoroo-backend uv run python -m echoroo.scripts.seed_moe_rdb <csv-path> --confirm
```

Seed the `taxa` table **first** (Admin -> Settings -> "Seed BirdNET taxa", see
below). Both seeders key their rows on `taxa.id` and resolve incoming rows by
scientific name, so against an empty `taxa` table every row is reported as
`unresolved` and nothing is written.

The MoE RDB CSV header is:

```csv
scientific_name,category,sensitivity_h3_res,notes
Nipponia nippon,CR,5,Endemic to Sado
```

`sensitivity_h3_res` must be one of {2, 5, 7, 9, 15}. Names with no local
taxon are warned about, counted in the `unresolved=` summary, and skipped;
they do not abort the import. If two rows resolve to the same taxon, the
strictest (lowest) `sensitivity_h3_res` wins regardless of row order.

The seeder exits non-zero when it cannot do its job, so a bootstrap script
will not march on with an empty masking table: `2` no `--confirm`, `3` file
not found, `4` rows were processed but none imported (almost always: `taxa`
is not seeded yet), `5` the CSV header does not match the contract above
(e.g. a pre-0034 export with a `taxon_id` column).

### Taxonomy and Japanese vernacular names (和名)

**Admin → Settings → "Seed BirdNET taxa"** populates the `taxa` table from the
BirdNET V2.4 species list. Since WS-A v2 slice 2a it *also* loads the Japanese
names in the same transaction, so a fresh install has 和名 with no extra step
and no network access.

Those names come from a **versioned bundle shipped inside the package**
(`apps/api/echoroo/data/vernacular/`), built from the IOC World Bird List
v15.2 Multilingual list. BirdNET labels follow eBird/Clements taxonomy, so a
packaged AviList v2025b crosswalk bridges renamed genera (e.g. BirdNET's
`Accipiter gularis` → IOC `Tachyspiza gularis` → ツミ). Attribution and
licensing: [THIRD_PARTY_LICENSES.md](../../THIRD_PARTY_LICENSES.md).

`POST /web-api/v1/admin/taxon/load-bundled-vernacular` (superuser-only,
returns 202 + a Celery task id) re-runs *only* the name load. Use it after the
bundle is regenerated from a newer upstream release — the load is idempotent
and rewrites only rows whose name actually changed. Regenerate the bundle
with:

```bash
cd apps/api && uv run --with openpyxl python scripts/build_vernacular_bundle.py \
  --ioc <Multiling IOC xlsx> --avilist <AviList extended xlsx> \
  --birdnet-labels <BirdNET V2.4 English labels txt> \
  --out-dir echoroo/data/vernacular
```

Labels the crosswalk could not resolve (non-birds such as `Engine` / `Dog`,
plus genuine taxonomic splits) land in `birdnet_unresolved.txt`; add curated
pairs to `overrides.csv` and rebuild to fix them.

The bundled names are ranked below an operator-loaded national checklist
(`source="authority"`) and below in-app manual overrides (`source="user"`),
and above the GBIF / iNaturalist names fetched by
`POST /web-api/v1/admin/taxon/sync-vernacular`.

#### Catalogue of Life XR identity (WS-A v2 slice 3)

GBIF's legacy backbone taxonomy is frozen, so a taxon's *re-matchable external
identity* is resolved against the **Catalogue of Life XR** checklist instead.
This is identity only — for birds the bundled AviList/IOC crosswalk above
remains the authority for names, and nothing here rewrites a display name or
the local `taxa.id` UUID (which stays immutable).

**Admin → the superuser-only endpoint
`POST /web-api/v1/admin/taxon/resolve-col-xr`** (body
`{"batch_size": 500, "force": false}`, returns 202 + a Celery task id) queues
`resolve_col_xr_batch`. For each biological taxon it stores, on the `taxa`
row: the COL usage key (`col_xr_id`), the accepted usage key / rank
(`col_xr_accepted_id`, `col_xr_accepted_rank`) and accepted name
(`accepted_scientific_name`, always authorship-free — the authorship lives in
`accepted_authorship`), the usage status (`col_xr_status`, e.g. `SYNONYM` for
*Accipiter gularis* → *Tachyspiza gularis*), both authorships, the
classification filtered to the seven principal ranks
(`col_xr_classification`), the match type and confidence, and the COL release
the match was pinned to (`col_xr_release` / `col_xr_clb_dataset_key`, read once
per run, e.g. `COL26.6 XR`). The release read is mandatory: if the matching
index does not report both an alias and a dataset key the run aborts before
writing anything.

**Sizing.** `batch_size` is capped at **2000**. The upstream costs ~0.35 s per
taxon and the task has a 900 s hard / 840 s soft Celery limit, so ~2000 rows
(~12 min) is the largest dispatch that reliably completes; a full ~6,500-taxon
catalogue is four dispatches. Progress is committed every 100 taxa, so a
dispatch that is killed (time limit, OOM, redeploy) still banks its work and
the next one resumes where it stopped.

Acceptance is decided by the match type, never by the usage status (a
`HIGHERRANK` hit returns an *accepted* genus or kingdom and must not become an
identity):

| match type | confidence | outcome |
| --- | --- | --- |
| `EXACT` | any | stored |
| `VARIANT` / `FUZZY` | ≥ 90 | stored, flagged for review via `col_xr_match_type` |
| `VARIANT` / `FUZZY` | < 90 | rejected |
| `HIGHERRANK` / `NONE` | — | rejected |

Rejected rows keep `col_xr_id` NULL but are still stamped with
`col_xr_match_type`, `col_xr_resolved_at` **and the release pin**: a rejection
is a *resolved* "no identity at this release", not a pending row. That stamp is
what makes the endpoint resumable — repeated calls walk the remaining taxa
rather than redoing the first `batch_size` rows.

Review the outcome with:

```bash
docker exec echoroo-db psql -U postgres -d echoroo \
  -c "SELECT col_xr_match_type, col_xr_status, count(*) FROM taxa GROUP BY 1,2 ORDER BY 3 DESC"
```

**After a COL release bump** (the alias in `col_xr_release` no longer matches
what `GET https://api.gbif.org/v2/species/match/metadata?checklistKey=xcol`
reports), re-run the endpoint with `{"force": true}`. A forced pass selects the
taxa whose stored release pin differs from the release the run is on, so —
exactly like the normal pass — **repeated dispatches advance through the
catalogue** instead of re-resolving the same first rows, and any identity that
no longer matches is cleared. Check what is left with:

```bash
docker exec echoroo-db psql -U postgres -d echoroo \
  -c "SELECT col_xr_release, count(*) FROM taxa WHERE NOT is_non_biological GROUP BY 1"
```

when every biological row reports the current alias, the re-resolution is
complete. No credentials are needed — COL XR is served by the public GBIF v2
matching API.

#### Identity provenance: what changed, and where a concept went (WS-A v2 slice 5)

A re-resolution **overwrites** the identity columns above, so slice 5 records
what it replaced. Two read-only, superuser-only endpoints expose it:

* **`GET /web-api/v1/admin/taxon/{taxon_id}/identity-history`** — the
  append-only journal for one taxon, newest first. One row per changed
  identity field: `col_xr_id`, `col_xr_accepted_id`, `col_xr_status`,
  `accepted_scientific_name`, `authorship`, `accepted_authorship`,
  `gbif_taxon_key` and the `col_xr_release` pin. Each row carries the old and
  new value, the `source` (`col_xr` / `gbif` / `admin` / `migration`), the
  `resolver` that wrote it, the release it was pinned to, and the actor — the
  Celery task id for a batch dispatch, the user id when a human materialised a
  GBIF pick. Filters: `field`, `source`, `since`, plus `limit` (1-500) /
  `offset`.
* **`GET /web-api/v1/admin/taxon/concept-relations`** — the directed "where did
  this concept go" edges. A `synonym_of` edge is seeded automatically whenever
  a taxon resolves with `col_xr_status='SYNONYM'`. Its target is keyed by the
  **COL usage key** (`to_col_xr_id`), not by a local id, because the accepted
  usage is usually not itself a local taxon — today every one of the ~302
  synonym targets is external, so `to_taxon_id` is null (`Accipiter badius` →
  `CVWCS Tachyspiza badia`). Filters: `relation`, `from_taxon_id`, `release`,
  `unresolved_target`, plus the same pagination.

Two things are deliberately true of this journal:

* **An identical re-resolution records nothing.** Re-running the endpoint with
  `{"force": true}` against an unchanged COL release rewrites the same values,
  and a database CHECK (`old_value IS DISTINCT FROM new_value`) plus the writer
  drop no-op rewrites, so the journal does not grow. A growing journal means
  the catalogue really moved.
* **Vernacular (display-name) changes are NOT identity changes** and never
  appear here. 和名 / English names come from the bundled IOC file, the loaded
  national checklist and the GBIF/iNaturalist sync — all re-derivable by
  re-running their loaders, so they need no journal.

Neither endpoint writes a `platform_audit_log` entry (both are read-only). Spot
check the journal and the edges with:

```bash
docker exec echoroo-db psql -U postgres -d echoroo \
  -c "SELECT field, count(*) FROM taxon_identity_history GROUP BY 1 ORDER BY 2 DESC"
docker exec echoroo-db psql -U postgres -d echoroo \
  -c "SELECT relation, (to_taxon_id IS NULL) AS target_external, count(*) \
      FROM taxon_concept_relations GROUP BY 1,2"
```

#### National checklist as the top-ranked authority (日本鳥類目録改訂第8版)

The Ornithological Society of Japan's checklist is the authority for
Japanese names but is **not bundled** (its terms allow derived use without
stating a redistribution license). An operator loads it themselves:

1. Download the official species list XLSX from
   <https://ornithology.jp/checklist.html> (`jpbirdlist8ed_ver1.xlsx`).
2. Convert it on the host (species rows only, Part A + B):
   ```bash
   cd apps/api && uv run --with openpyxl python scripts/convert_osj_checklist.py \
     jpbirdlist8ed_ver1.xlsx --out osj8_ja.csv
   ```
3. Load it inside the container under `source="authority"` (idempotent,
   same race-safe loader as the bundle, crosswalk applied):
   ```bash
   docker cp osj8_ja.csv echoroo-backend:/tmp/osj8_ja.csv
   docker exec echoroo-backend uv run python -m echoroo.scripts.load_authority_checklist \
     /tmp/osj8_ja.csv --confirm
   ```

Expect roughly 600 of the ~680 checklist species to match the BirdNET taxa;
the remainder are Japanese endemics and rarities BirdNET does not model
(メグロ, ノグチゲラ, ヤンバルクイナ, …) and will be named automatically once
those taxa exist. Where the checklist and the IOC bundle disagree (a handful
of species, e.g. *Anthus rubescens* タヒバリ vs アメリカタヒバリ) the
checklist wins.

Role-based test users plus a sample project and dataset come from the seeded-permission E2E fixture. Run `./echoroo.sh seed e2e` to bootstrap the same Viewer / Annotator / Manager users the trial scenarios reference. Its stdout JSON includes credentials and tokens; handle it as sensitive.

## 6. Invite Trial Users

The operator flow is: admin logs in, creates a project, then invites members.

The invitation token API is:

- `POST /web-api/v1/projects/{id}/trusted-users` with session cookies and CSRF.
- `POST /api/v1/projects/{id}/trusted-users` with an API key.

The UI invite screen is not implemented yet. For now, use curl to mint a token and hand out the resulting invitation link through the trial plan or operator channel.

Get the session and CSRF cookie values first:

1. Sign in as the project owner in a normal browser tab.
2. Open DevTools, go to **Application > Cookies > the frontend origin**, and copy the values of `echoroo_session` and `echoroo_csrf`.
3. Paste them into the request. The CSRF cookie value also goes into the `X-CSRF-Token` header (double-submit pattern).

```bash
curl -X POST http://localhost:8002/web-api/v1/projects/{id}/trusted-users \
  -H "Cookie: echoroo_session=<session>; echoroo_csrf=<csrf>" \
  -H "X-CSRF-Token: <csrf>" \
  -H "Content-Type: application/json" \
  -d '{"email":"trial.user@example.com","granted_permissions":["view_media","view_detection","download"],"duration_seconds":7776000}'
```

Implementation reference: [invitation_service.py](../../apps/api/echoroo/services/invitation_service.py).

The trial user follows the link, registers, and joins the project.

## 7. Recommended Trial Scenarios

- Login, project list, detection detail, vote, export.
- File upload by adding a recording.
- Public settings check from spec/006.
- Role-based display differences for Viewer, Annotator, and Manager.

Keep detailed scripts in the trial plan. This document only points to the paths and flows needed to bootstrap the preview.

## 8. Known Limits (Out Of Scope / Known Bugs)

- The `/setup` HTTP endpoint and frontend wizard are functional. With an empty database, open `http://localhost:3001/setup` and create the initial superuser from the browser. The CLI `init_superuser` remains available for automated and non-interactive setup paths.
- Email verification flow is in progress; the trial should not depend on email-verification-required paths.
- 2FA reset admin operation: DB schema exists, admin UI is not implemented.
- API token management UI: not implemented; use CLI or seed data only.
- Trusted device revoke list UI: not implemented.
- Project invitation UI: contracts are defined, but the SvelteKit form is not implemented; use curl as in section 6.
- Detection detail / pending invitation CTA: some E2E coverage is currently skipped.

## 9. Session Stability Check (CSRF Cookie TTL Hotfix)

Before PR #86 the CSRF cookie expired after 15 minutes (`web_access_token_ttl_seconds`) even though the session and refresh cookies lived for 30 days, so any unsafe request after the 15-minute mark returned `403 csrf_failed` and the user appeared to be auto-logged-out. To confirm the fix:

1. Sign in, then leave the tab open for at least 16 minutes (one minute past the old TTL is enough to expose the regression).
2. Trigger one unsafe request (`POST` / `PATCH` / `DELETE`) such as a vote or a comment.
3. Open browser DevTools **Application > Cookies** and check that `echoroo_csrf` shows the same `Max-Age` / `Expires` as `echoroo_refresh` (the long-lived session cookie). Both should be on the order of 30 days, not 15 minutes.
4. A `403 csrf_failed` response or an auto-logout at this point is a regression matching pre-PR-#86 behavior.

## 10. Test Mode (2FA bypass for browser testing)

For Playwright tests and internal preview workflows only, the backend can accept a shared TOTP secret after the user's enrolled TOTP secret fails. Enable it only through development environment configuration:

```bash
TEST_MODE=true
TEST_TOTP_SECRET_BASE32=JBSWY3DPEHPK3PXP
```

Generate a matching browser-test code with either command:

```bash
oathtool --totp -b JBSWY3DPEHPK3PXP
python -c "import pyotp; print(pyotp.TOTP('JBSWY3DPEHPK3PXP').now())"
```

When `TEST_MODE=true` and `TEST_TOTP_SECRET_BASE32` is set in `.env`, the 2FA challenge accepts a code generated from the shared secret for ANY user. The user's enrolled secret is always checked first, and enrolled-secret success does not emit the bypass audit event.

When enabled, startup logs `TEST_MODE is enabled, 2FA shared-secret bypass is ACTIVE. DO NOT use in production. ENVIRONMENT=%s`. A successful shared-secret match emits the audit action `two_factor.test_mode_bypass` with reason `shared_secret_match` and the current environment.

Never enable `TEST_MODE` in production and NEVER ship it to a prod-facing deployment. Startup settings validation refuses `TEST_MODE=true` in production and refuses `TEST_MODE=true` without `TEST_TOTP_SECRET_BASE32`. `compose.dev.yaml` passes these variables through for development; `compose.preview.yaml` intentionally does not.

## 11. Troubleshooting

If the frontend fails, check logs:

```bash
docker logs echoroo-frontend --tail 100
```

If migration fails, the database may not be empty. Check tables:

```bash
docker exec echoroo-db psql -U postgres -c '\dt'
```

If a trial user is stuck logging in, a rate limit may be involved. Check `login_attempts` and clear only the relevant rows:

```bash
docker exec echoroo-db psql -U postgres -c 'SELECT * FROM login_attempts ORDER BY attempted_at DESC LIMIT 20;'
docker exec echoroo-db psql -U postgres -c "DELETE FROM login_attempts WHERE email = 'trial.user@example.com';"
```

Do not use `redis-cli FLUSHALL`; it destroys sessions and Celery state.

For CSRF 403 regressions, confirm the branch includes PR #86:

```bash
git log --oneline --decorate --all --grep '#86'
```

## 12. Related Links

- [specs/006-permissions-redesign/quickstart.md](../../specs/006-permissions-redesign/quickstart.md)
- [docs/runbook/release_readiness.md](../runbook/release_readiness.md)
- [docs/runbook/email_verification.md](../runbook/email_verification.md)
- [docs/runbook/trusted_devices.md](../runbook/trusted_devices.md)
- [DOCKER.md](../../DOCKER.md)
- [CONFIGURATION.md](../../CONFIGURATION.md)
