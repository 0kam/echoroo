# spec/008 — Permissions Vocabulary Refinement

Companion spec to `spec/007-permission-test-coverage`. Amends only the
permission vocabulary in `spec/006-permissions-redesign` by introducing
`MANAGE_DATASET_ADMIN` (admin/owner only) so that dataset-resource
operations and dataset-content operations are no longer conflated under a
single `MANAGE_DATASET`. Behavior-preserving: no role gains or loses any
endpoint access, and no UI changes.

- [spec.md](./spec.md) — full amendment, glossary, behavior-preservation
  proof, acceptance criteria
- Amends → `../006-permissions-redesign/spec.md` (vocabulary only)
- Implementation plan → `../007-permission-test-coverage/plan.md` (Phase 2A.0)
