# Quickstart §3 Runbook Validation Log

**Phase**: 16 Batch 6h-3 (T998)
**Date**: 2026-04-29
**Branch**: `006-permissions-redesign`
**Validator**: backend-developer SSA

This document records the local execution evidence for the four bootstrap
scripts referenced by `specs/006-permissions-redesign/quickstart.md` §3.
The companion automated regression gate lives at
`apps/api/tests/runbook/test_quickstart_phase3_smoke.py` and is wired into
the CI pipeline as the `runbook-smoke-tests` job (`.github/workflows/ci.yml`).

CI runs the smoke subset only. Operators opt into the full live-infra
suite locally via `pytest -m requires_runbook` against the Docker Compose
dev stack (PostgreSQL + Redis + LocalStack).

---

## 1. Script Inventory

| Script | Module path | argparse | --help | --confirm gate | Notes |
|--------|-------------|----------|--------|----------------|-------|
| `wipe_database` | `echoroo.scripts.wipe_database` | No (interactive only) | n/a | Safety phrase + 2 superuser UUIDs + `wipe_guard` 3-point precondition | Module exposes `main` and `SAFETY_PHRASE = "YES I UNDERSTAND THIS DESTROYS ALL DATA"`. |
| `init_superuser` | `echoroo.scripts.init_superuser` | Yes | OK | Required (`--confirm`) | Phase 15 T952. Supports `--non-interactive` for CI/automation. |
| `initial_iucn_sync` | `echoroo.scripts.initial_iucn_sync` | Yes | OK | Required (`--confirm`) | Phase 11 T621, FR-036. Requires `IUCN_API_TOKEN`. |
| `seed_moe_rdb` | `echoroo.scripts.seed_moe_rdb` | Yes | OK | Required (`--confirm`) | Phase 11 T622, FR-032. Takes CSV positional arg. |

All four scripts are present at `apps/api/echoroo/scripts/`; no stub creation
or Phase 17 follow-up ticket is required.

---

## 2. `--help` Verification

Captured live from `echoroo-backend` container on `2026-04-29` against
HEAD `2386e1ca`.

### 2.1 `init_superuser`

```
$ docker exec echoroo-backend uv run python -m echoroo.scripts.init_superuser --help
usage: echoroo.scripts.init_superuser [-h] [--confirm] [--email EMAIL]
                                      [--display-name DISPLAY_NAME]
                                      [--password PASSWORD]
                                      [--non-interactive]

Bootstrap the initial superuser (Phase 15 T952). Run ONCE after the release-
time wipe so the M-of-N approval engine has a quorum-eligible operator.
Subsequent superusers are added via the admin endpoint with full M-of-N
gating.

options:
  -h, --help            show this help message and exit
  --confirm             Required acknowledgement that this script will INSERT
                        a new user + superuser row into the database. Without
                        --confirm the script exits non-zero without touching
                        the database.
  --email EMAIL         Operator e-mail (RFC 5322). When omitted the script
                        prompts interactively.
  --display-name DISPLAY_NAME
                        Optional display name. Defaults to the local part of
                        --email.
  --password PASSWORD   Temporary password (>= 16 chars). When omitted the
                        script prompts via ``getpass`` so the secret never
                        lands in shell history.
  --non-interactive     Disable interactive prompts. All fields must be
                        supplied via flags. Intended for CI / smoke tests.

exit code: 0
```

### 2.2 `initial_iucn_sync`

```
$ docker exec echoroo-backend uv run python -m echoroo.scripts.initial_iucn_sync --help
usage: echoroo.scripts.initial_iucn_sync [-h] [--confirm]

Pull the current IUCN Red List snapshot and UPSERT it into
taxon_sensitivities. Intended to be run ONCE during initial platform bootstrap
(quickstart §3). Subsequent syncs are handled by the weekly Celery beat
schedule.

options:
  -h, --help  show this help message and exit
  --confirm   Required acknowledgement that this script will mutate the global
              taxon_sensitivities table. Without --confirm the script exits
              non-zero without contacting the IUCN API.

exit code: 0
```

### 2.3 `seed_moe_rdb`

```
$ docker exec echoroo-backend uv run python -m echoroo.scripts.seed_moe_rdb --help
usage: echoroo.scripts.seed_moe_rdb [-h] [--confirm] csv_path

UPSERT a Japanese MoE Red Data Book CSV into the taxon_sensitivities table
under source='moe_rdb'.

positional arguments:
  csv_path    Path to the MoE RDB CSV file (UTF-8, header row required).

options:
  -h, --help  show this help message and exit
  --confirm   Required acknowledgement that this script will mutate
              taxon_sensitivities. Without --confirm the script exits non-zero
              without opening the CSV.

exit code: 0
```

### 2.4 `wipe_database`

By design `wipe_database` has no argparse layer — every gate is an
interactive prompt or a precondition check (`check_wipe_guard`). The
runbook smoke test instead asserts that the module imports cleanly and
exposes `main` + the documented `SAFETY_PHRASE`:

```
$ docker exec echoroo-backend uv run python -c \
    "from echoroo.scripts.wipe_database import SAFETY_PHRASE, main; \
     print('SAFETY_PHRASE:', SAFETY_PHRASE); print('main:', main)"
SAFETY_PHRASE: YES I UNDERSTAND THIS DESTROYS ALL DATA
main: <function main at 0x...>
```

---

## 3. Refusal Behaviour Verification

Confirms that each `--confirm`-gated script exits non-zero without doing
the destructive work when the flag is omitted.

```
$ docker exec echoroo-backend uv run python -m echoroo.scripts.initial_iucn_sync
ERROR echoroo.scripts.initial_iucn_sync: Refusing to run without --confirm.
  This script issues a platform-wide UPSERT against taxon_sensitivities and
  should only be run during the initial bootstrap (see quickstart §3).
exit code: 2
```

```
$ docker exec echoroo-backend uv run python -m echoroo.scripts.seed_moe_rdb /tmp/nonexistent.csv
ERROR echoroo.scripts.seed_moe_rdb: Refusing to run without --confirm. This
  script UPSERTs into taxon_sensitivities and may overwrite existing
  moe_rdb rows.
exit code: 2
```

`init_superuser` exhibits the same exit-code-2 refusal when `--confirm` is
omitted; the smoke test `test_init_superuser_requires_confirm` covers
this path with `--non-interactive` plus placeholder credentials so CI
regressions get caught.

---

## 4. Smoke Test Suite Result

```
$ docker exec echoroo-backend uv run pytest tests/runbook/ -m "not requires_runbook" --no-cov -q
tests/runbook/test_quickstart_phase3_smoke.py ........              [100%]
================ 8 passed, 1 deselected, 3 warnings in 7.52s ================
```

Selected (8): `--help` parametric (3) + refusal contracts (4) + wipe_database
import smoke (1).
Deselected (1): `test_check_wipe_guard_runs_against_live_stack` —
`requires_runbook` marker, opt-in only.

---

## 5. Static Validation

```
$ docker exec echoroo-backend uv run ruff check --no-cache tests/runbook/
All checks passed!

$ docker exec echoroo-backend uv run mypy tests/runbook/
Success: no issues found in 2 source files
```

---

## 6. Live-infra Tests (`requires_runbook`)

The marker gates one test today (`test_check_wipe_guard_runs_against_live_stack`).
It exercises `echoroo.scripts.check_wipe_guard` against the real DB + S3
stack and asserts the script either reports "clear for wipe" (rc=0) or
"already wiped" (rc=1) without crashing on import.

To run locally:

```bash
./scripts/docker.sh dev   # bring up db + redis + localstack
docker exec echoroo-backend uv run pytest tests/runbook/ -m requires_runbook --no-cov -v
```

Future live-infra tests for the destructive scripts (full wipe + bootstrap
end-to-end) belong here once a hermetic `testcontainers` stack with
LocalStack KMS aliases is wired up — currently tracked as out of scope
for Batch 6h-3 (script behaviour modifications are Phase 17).

---

## 7. CI Wiring

A new `runbook-smoke-tests` job in `.github/workflows/ci.yml` runs the
smoke subset on every push to `main` / `006-permissions-redesign` and on
every PR. The job uses `--no-cov -m "not requires_runbook"` so it stays
under a few seconds and does not need the postgres testcontainer.

The `requires_runbook` marker is registered in `apps/api/pyproject.toml`
under `[tool.pytest.ini_options].markers` so `--strict-markers` does not
reject it.

---

## 8. Outstanding Items

None for this batch. Script *behaviour* modifications (e.g. promoting
`wipe_database` to argparse, or adding a `--dry-run` mode) are out of
Batch 6h-3 scope per the task brief and tracked as Phase 17 candidates
should they be requested.
