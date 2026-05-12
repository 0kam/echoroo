# Phase 0 Baseline (2026-05-12)

Captured on branch `007-permission-test-coverage` @ main HEAD `a7386bd3`.

## Backend test baselines

### test_permissions.py (Canonical Matrix)
- Total: 380 tests
- Passed: 258
- Xfailed: **108** ← Phase 2A target = 0
- Errors: 14 (pre-existing HTTP integration fixture issues — not in scope for 007)

### test_endpoint_coverage.py (status: skipped)
- Location: `tests/security/authorization/test_endpoint_coverage.py` (note: plan referenced `tests/contract/`, actual location is `tests/security/authorization/`)
- Current status: `@pytest.mark.skip(reason="Phase 2: ACTIONS is intentionally empty. Phase 3 (T100+) registers every endpoint. This test becomes mandatory at T100f enforcement.")`
- 1 passed (collection sanity), 1 skipped (the real coverage test)

### ACTIONS catalog
- Location: `apps/api/echoroo/core/actions.py`
- Registered: ~62 (per memory)
- Target after Phase 2A: ~114 (62 existing + ~52 new + admin/taxon/etc.)

## Phase 0 deliverables status
- [x] Branch `007-permission-test-coverage` created from main `a7386bd3`
- [x] Baseline xfail count recorded (108)
- [x] Baseline endpoint_coverage skip status confirmed
- [x] xfail tracking file scaffolded (`xfail_tracking.md`)
- [ ] Open GitHub tracking issue for xeno_canto mid-revoke xfail (deferred — will open at PR creation time per CLAUDE.md autonomous-action-with-side-effects guidance)
