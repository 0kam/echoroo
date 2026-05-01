# Lint allowlists (line-level fingerprint format)

This directory hosts the per-lint exemption files used by:

- `scripts/lint_permission_guard.py` -> `permission_guard_allowlist.txt`
- `scripts/lint_response_filter.py` -> `response_filter_allowlist.txt`
- `scripts/lint_search_gate.py` -> `search_gate_allowlist.txt`
- `scripts/lint_no_raw_coordinates.py` -> `raw_coordinates_allowlist.txt`
- `scripts/lint_kms_isolation.py` -> `kms_isolation_allowlist.txt`
- `scripts/assert_openapi_no_coords.py` -> `openapi_coords_allowlist.txt`
  (path-prefix matcher; NOT a fingerprint allowlist — see file header)

## Why fingerprints (Phase 2.11 P1-a)

The previous baseline (Phase 2.10 #7) was a flat list of repo-relative
file paths. Adding `apps/api/echoroo/api/v1/foo.py` to the allowlist
silenced **every** violation in that file — including any new violation
introduced by future edits. Phase 3 will touch most of these files, so
any regression slipped through silently.

The new format locks each allowlist entry to a SPECIFIC violation by
embedding a stable signature (function name, model name, identifier
name, etc.) into the entry. New violations in the same file produce a
DIFFERENT fingerprint and therefore fail the lint.

## Format

Each non-comment line is one fingerprint, optionally followed by
`  #` (two spaces + hash) and a free-form comment:

    <file>:<symbol-or-kind>:<violation-kind>  # justification

Examples:

    apps/api/echoroo/api/v1/users.py:get_current_user:missing-permission-guard  # legacy: Phase 3 T150
    apps/api/echoroo/services/export.py:field-lat:forbidden-coordinate-identifier  # legacy schema
    apps/api/echoroo/api/v1/search/annotations.py:select-Annotation:direct-select-outside-search-gate  # legacy

Rules:

- Lines starting with `#` are full-line comments.
- Lines that begin with whitespace are stripped.
- Inline comments use `  #` (two SPACES + hash). One-space `#` would
  collide with paths that contain `#` characters in the future.
- Entries are matched by exact-equality against the fingerprint emitted
  by each lint script (see the script's `_violation_fingerprint`
  helper for the schema).
- Each script also prints the fingerprint for every reported violation
  (`[fingerprint: ...]` suffix) so adding an entry is copy-paste.

## Phase 3 cleanup target

Each allowlist file must end up EMPTY by the end of Phase 3 US11. The
`# legacy: Phase 3 US11 T1xx` annotation on each entry is the explicit
cleanup target: when the corresponding endpoint / module is rewritten
to the new contract, remove the entry, run the lint, and confirm a
clean exit. The CI gate (T100f) is the final lock — at that point
the lint runs in strict mode against an empty allowlist.

## Process for adding a new entry

1. Run the relevant lint locally (`uv run python scripts/lint_*.py
   --fail-on-violation`).
2. Copy the `[fingerprint: ...]` value from the failure into the
   appropriate allowlist file with a `  # justification` comment.
3. Document the justification in your PR description.
4. Reviewers MUST evaluate whether the justification is acceptable
   (almost always: "legacy module, scheduled for Phase 3 cleanup").

## Process for removing an entry

When the underlying issue is fixed (the endpoint now uses the
permission guard, the response filter, etc.) just delete the
corresponding line and confirm the lint stays at 0. CI will reject any
PR that re-introduces a violation without an allowlist entry.
