# Coverage-debt shrink roadmap (PHASE17_PENDING)

`scripts/check_coverage_threshold.py` enforces per-module statement-coverage
thresholds (permission-critical modules: 95%, all other `echoroo/` modules:
85%) against `coverage.json` produced by the backend pytest run. Modules that
cannot yet reach their threshold are listed in the `PHASE17_PENDING`
frozenset in that script, where they are treated as `WARN(ph17)` instead of a
hard `FAIL`.

That list is debt, not a feature, so as of W5-7 (2026-07-06) it is a
**one-way ratchet**: `PHASE17_PENDING_BASELINE_COUNT` caps it at its current
size (114 entries — six previously-stale entries referencing deleted/renamed
files were pruned in the same change), and `_check_phase17_pending_invariants()`
hard-fails CI if the set grows past the cap or references a file that no
longer exists. See the comment block above `PHASE17_PENDING` in
`scripts/check_coverage_threshold.py` for the mechanism and per-batch removal
history (PR-B through PR-H, 2026-05-09 .. 2026-05-31).

## Current size

- **114 entries** (as of 2026-07-06, W5-7).

## Easiest next burn-down candidates

Judged by module size (LOC), whether the module is a thin re-export façade
(near-zero logic to actually cover), whether the reported gap-to-threshold is
already small per existing NOTE comments in the script, and whether the
module needs only unit-level mocking (no live DB / Celery / GPU fixture).

| Rank | Module | LOC | Why it's easy | Notes |
|---|---|---|---|---|
| 1 | `echoroo/workers/classifier_tasks.py` | 58 | Pure re-export shim (façade) over `echoroo/workers/classifier/*`; a single import + task-invocation smoke test should push it to ~100%. | Same pattern already proven for `echoroo/api/v1/search/sessions/*` façade split (W3-1). |
| 2 | `echoroo/api/v1/search/sessions/__init__.py` | 80 | Also a compat façade; `router` is an intentionally-empty `APIRouter`, rest is re-exports. One test module covering the re-export surface clears it. | Comment in file explicitly documents the façade intent. |
| 3 | `echoroo/repositories/superuser_credentials.py` | 58 | Comment in `check_coverage_threshold.py` already reports 83.3% unit-only — only ~1.7pp short of the 85% "other" threshold (not permission-tier). Store is an **in-memory stub** (no DB), so no integration fixture is needed. | Currently re-added to PENDING because it "requires live-DB integration tests" per an older note, but the implementation itself (`InMemorySuperuserCredentialStore`) is pure Python — worth re-checking with a plain unit test first. |
| 4 | `echoroo/api/v1/settings.py` | 42 | Single GET endpoint, one repository call, no branching beyond the default fallback inside the repository. 2-3 FastAPI TestClient cases (default value, configured value, unauthenticated 401) should clear 85% easily. | Small enough that a full rewrite-as-test could hit 100%. |
| 5 | `echoroo/services/captcha.py` | 63 | One async function, ~5 branches (missing secret + prod/dev, network success, network exception + prod/non-prod). All branches are reachable with `httpx` mocked/monkeypatched — no external network or DB needed. | Already has a docstring example; branches map 1:1 to test cases. |
| 6 | `echoroo/workers/two_factor_tasks.py` | 62 | Single Celery task wrapping one service call; only needs `AsyncSessionLocal` and `run_dispatch_due_requests` mocked to exercise the summary-logging branch (`inspected` truthy/falsy). | Mirrors the already-cleared `trusted_expiry_dispatcher`-style workers pattern. |
| 7 | `echoroo/services/h3_utils.py` | 110 | Likely pure geometry/index helper functions (H3 cell math) — good candidate for property-style unit tests once confirmed branch-free. | Verify no import-time GPU/model dependency before committing to full unit coverage. |
| 8 | `echoroo/services/vernacular.py` | 109 | Locale-resolution helper; if it's mostly IN-query + dict construction (per MEMORY.md notes on vernacular resolution), it's DB-adjacent but the branch logic (locale fallback rules) can likely be isolated and unit-tested with a fake repository. | Cross-check with `services/vernacular.py` callers before scoping the test — some branches may need a DB fixture. |
| 9 | `echoroo/scripts/initial_iucn_sync.py` | 107 | CLI script; the T998 runbook-smoke-test gate already exercises `--help`, so most of the CLI parsing path is proven — extending to cover the sync logic branches (with the IUCN client mocked) is incremental, not net-new test infra. | Runbook smoke gate (T998) already covers the entry point; this is "finish the job." |

## Not worth chasing yet

Repository/service modules that need a live Postgres fixture (`repositories/annotation.py`,
`repositories/clip.py`, `repositories/taxon.py`, etc.), ML modules that need
GPU/model fixtures (`ml/birdnet/*`, `ml/perch/*`, `ml/classifiers.py`), and
Celery worker tasks that need a running broker (`workers/search_tasks.py`,
`workers/upload_tasks.py`, etc.) are all listed in `PHASE17_PENDING` for
structural reasons (missing fixture infrastructure), not because the code is
hard to write tests for. These should wait for a dedicated integration-test
investment rather than one-off unit tests.

## Maintaining this document

When a `PHASE17_PENDING` entry is removed because a module reached
threshold, update `PHASE17_PENDING_BASELINE_COUNT` down to match (the ratchet
check in `scripts/check_coverage_threshold.py` will not stop you from
lowering the cap — only from raising it) and drop the corresponding row from
the table above if present.
