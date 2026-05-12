# Spec 008 — Permissions Vocabulary Refinement

| Field | Value |
|-------|-------|
| **Spec ID** | `008-permissions-vocabulary-refinement` |
| **Status** | Draft (companion to `spec/007-permission-test-coverage` plan Rev.5.1) |
| **Date** | 2026-05-12 |
| **Author** | @okam |
| **Supersedes** | — (nothing) |
| **Amends** | `spec/006-permissions-redesign` (vocabulary section only — `Permission` enum and `ROLE_PERMISSIONS` matrix) |
| **Related** | `spec/007-permission-test-coverage/plan.md` (implementation plan, Rev.5.1) |
| **Feature branch** | `008-permissions-vocabulary-refinement` |

---

## 1. Summary

This spec amends the permission vocabulary in `spec/006-permissions-redesign`
**without changing any observable behavior**. It introduces a new permission,
`MANAGE_DATASET_ADMIN`, to disambiguate two operations that the existing
`MANAGE_DATASET` permission conflates:

- **Dataset RESOURCE management** — create / delete / import / datetime-config
  mutate / annotation_project CRUD / confirmed_region CRUD / detection_run
  update or delete / evaluation delete. These are currently gated by
  `is_project_admin()` in backend code (admin and owner only).
- **Dataset CONTENT management** — clip CRUD, clip generate, annotation
  CRUD, detection_run read/start. These are currently gated by
  `check_project_access()` (member and above).

After this amendment:

- `MANAGE_DATASET` remains a member-held permission, scoped to **content
  inside a dataset**.
- `MANAGE_DATASET_ADMIN` (NEW) is added to the `Permission` enum and granted
  **only to admin and owner**, scoped to the **dataset resource lifecycle**.

The set of role × endpoint pairs that resolve to "allowed" is byte-identical
before and after this amendment. There are no UI changes, no new endpoints,
no behavior changes for any role (guest, viewer, member, admin, owner,
superuser, trusted user).

---

## 2. Motivation

`spec/006-permissions-redesign` Rev.3.2 (the spec currently in main) defines a
`ROLE_PERMISSIONS` matrix in which `MANAGE_DATASET` is granted to **member**,
admin, and owner. The intent at the time was that `MANAGE_DATASET` would gate
the full "dataset management" surface.

In practice the backend implementation (landed across spec/006 Phase 1–16 and
the spec/007 Phase 0 audit) is stricter. The backend uses
`is_project_admin()` — a check that admits only admin and owner — for the
destructive subset of dataset operations:

- `POST /datasets` (create), `PATCH /datasets/{id}`, `DELETE /datasets/{id}`
- `POST /datasets/{id}/import`
- `POST /datasets/{id}/datetime/apply` (datetime config mutation)
- `POST/PATCH/DELETE /annotation_projects/...` (annotation_project CRUD)
- `POST/DELETE /confirmed_regions/...` (confirmed_region CRUD)
- `PATCH/DELETE /detection_runs/{id}` (detection_run mutate)
- `DELETE /evaluations/{id}`

Members can still operate **inside** an existing dataset — they can generate
clips, edit clips, create and edit annotations, start detection runs — but
they cannot delete the dataset itself or invoke its admin-only lifecycle
operations.

`spec/007-permission-test-coverage` exposed this gap in two ways:

1. **Codex review of spec/007 Rev.1 (P0-1)** identified the
   `MANAGE_DATASET` overload as the primary new P0 blocking the test
   coverage uplift: tests that asserted "member can call dataset DELETE
   because the matrix says they have `MANAGE_DATASET`" would diverge from
   reality.
2. **The AD-1A behavior-neutrality rule** (spec/007 plan § AD-1A) requires
   that every newly registered `ACTION` resolve to the same role set that the
   existing endpoint enforces. For the destructive dataset operations, no
   existing permission in the matrix admits exactly `{admin, owner}` — the
   closest, `MANAGE_DATASET`, admits members too.

Both pressures point at the same answer: introduce one new permission that
expresses "manage the dataset resource itself" so that the test coverage work
can proceed without changing behavior.

### Guiding principle

> **"Do not change permission behavior under the banner of test
> coverage."**
> (spec/007 plan AD-1B rationale; "テスト強化の名目で権限仕様を変更しない".)

This amendment is a vocabulary refinement, not a permission redesign.
Member-visible UI is unchanged. Member-callable endpoints are unchanged. The
only observable side effect is that `ROLE_PERMISSIONS[admin]` and
`ROLE_PERMISSIONS[owner]` each contain one additional permission constant
(`MANAGE_DATASET_ADMIN`); no role gains or loses any endpoint access.

---

## 3. Vocabulary Glossary

This glossary is the **single source of truth** for what each dataset-related
permission means across spec, backend, frontend, tests, and Playwright
assertions. It mirrors `spec/007-permission-test-coverage/plan.md § 4A`; the
plan remains the canonical location and this section reproduces it for
discoverability.

### 3.1 Member-held permission (preserved)

| Permission | Holders | Semantic scope | Representative endpoints |
|------------|---------|----------------|--------------------------|
| `MANAGE_DATASET` | member / admin / owner | Manage CONTENT within an existing dataset: clips (create / update / delete / generate), detection_run read & start. | `POST /clips`, `PATCH /clips/{id}`, `DELETE /clips/{id}`, `POST /clips/generate`, `POST /detection_runs` (start) |

### 3.2 Admin-held permission (NEW)

| Permission | Holders | Semantic scope | Representative endpoints |
|------------|---------|----------------|--------------------------|
| `MANAGE_DATASET_ADMIN` (NEW) | admin / owner only | Lifecycle of the dataset RESOURCE itself: create / update / delete dataset; import; datetime-config apply; annotation_project CRUD; confirmed_region CRUD; detection_run update / delete; evaluation delete. | `POST /datasets`, `PATCH /datasets/{id}`, `DELETE /datasets/{id}`, `POST /datasets/{id}/import`, `POST /datasets/{id}/datetime/apply`, `POST/PATCH/DELETE /annotation_projects/...`, `POST/DELETE /confirmed_regions/...`, `PATCH/DELETE /detection_runs/{id}`, `DELETE /evaluations/{id}` |

### 3.3 Disambiguation rules (consumers MUST follow)

1. **"Can the user manage THIS dataset's contents (clips, annotations)?"**
   → check `MANAGE_DATASET`. Member: yes. Viewer: no.
2. **"Can the user create / delete THIS dataset, change its datetime
   configuration, or manage its annotation_projects?"** → check
   `MANAGE_DATASET_ADMIN`. Member: **no**. Admin / owner: yes.
3. UI elements that look like dataset CRUD ("Edit dataset", "Delete
   dataset card", "+ New Dataset") MUST gate on `MANAGE_DATASET_ADMIN`,
   never on `MANAGE_DATASET`.
4. UI elements that operate WITHIN an existing dataset ("Generate clips",
   "Add annotation", "Run inference") MUST gate on the relevant content
   permission (`MANAGE_DATASET`, `ANNOTATE`, `RUN_INFERENCE`, etc.), never
   on `MANAGE_DATASET_ADMIN`.

---

## 4. Permission Enum Changes

`apps/api/echoroo/core/permissions.py` defines `class Permission(StrEnum)`.

Add the new member between the existing `MANAGE_DATASET` and `RUN_INFERENCE`
entries (current lines 79–80) so the resource-management cluster stays
together:

```
class Permission(StrEnum):
    ...
    MANAGE_DATASET = "manage_dataset"
    MANAGE_DATASET_ADMIN = "manage_dataset_admin"   # NEW (spec/008)
    RUN_INFERENCE = "run_inference"
    ...
```

The string value `"manage_dataset_admin"` is the canonical wire form and
mirrors the existing snake_case convention. Frontend codegen
(`ProjectPermission` union, see spec/007 plan AD-2) MUST emit a corresponding
literal type member; the spec/007 implementation plan handles that.

---

## 5. `ROLE_PERMISSIONS` Matrix Updates

The matrix lives in the same module (`permissions.py`, current lines
263–322). Three frozensets change; one does not:

### 5.1 `_VIEWER_PERMS` — **unchanged**

Viewers do not gain `MANAGE_DATASET_ADMIN`. They already lack
`MANAGE_DATASET`; this amendment does not change that.

### 5.2 `_MEMBER_PERMS` — **unchanged**

Members **retain** `MANAGE_DATASET` exactly as today. They do **not** receive
`MANAGE_DATASET_ADMIN`. This is the critical line that keeps behavior
preserved: members do not gain dataset-resource mutation capability.

### 5.3 `_ADMIN_PERMS` — adds `MANAGE_DATASET_ADMIN`

```
_ADMIN_PERMS = _MEMBER_PERMS | frozenset({
    Permission.VIEW_AUDIT_LOG,
    Permission.MANAGE_DATASET,
    Permission.MANAGE_DATASET_ADMIN,   # NEW (spec/008)
    Permission.TRAIN_MODEL,
    Permission.MANAGE_MEMBERS,
    Permission.EDIT_PROJECT,
    Permission.MANAGE_LICENSE,
})
```

### 5.4 `_OWNER_PERMS` — inherits via `_ADMIN_PERMS`

`_OWNER_PERMS` is defined as `_ADMIN_PERMS | { …owner-only… }`. The owner
automatically inherits `MANAGE_DATASET_ADMIN` once admin does; no separate
edit to `_OWNER_PERMS` is required, though tests must assert membership
explicitly (see § 9).

### 5.5 Computed role matrix snapshot (post-amendment)

| Role | `MANAGE_DATASET` | `MANAGE_DATASET_ADMIN` |
|------|------------------|-------------------------|
| viewer | ❌ | ❌ |
| member | ✅ | ❌ |
| admin | ✅ | ✅ |
| owner | ✅ | ✅ |
| superuser (with project-scope allowlist) | ✅ (owner-equivalent) | ✅ (owner-equivalent) |

Trusted Users are unaffected: the `TRUSTED_ALLOWED_PERMISSIONS` allowlist in
spec/006 does not currently include either `MANAGE_DATASET` or
`MANAGE_DATASET_ADMIN`, and this amendment does not change that allowlist.

---

## 6. Behavior Preservation Guarantee

For every endpoint category, the set of roles allowed to call it is identical
before and after the amendment. Concretely:

| Endpoint category | Current enforcement | Gated on (after) | Roles allowed (before) | Roles allowed (after) | Equivalent? |
|-------------------|---------------------|------------------|-------------------------|--------------------------|-------------|
| dataset list / get | `check_project_access()` | `VIEW_DATASET_LIST` | viewer+ | viewer+ | ✅ |
| dataset create | `is_project_admin()` | `MANAGE_DATASET_ADMIN` | admin, owner | admin, owner | ✅ |
| dataset update | `is_project_admin()` | `MANAGE_DATASET_ADMIN` | admin, owner | admin, owner | ✅ |
| dataset delete | `is_project_admin()` | `MANAGE_DATASET_ADMIN` | admin, owner | admin, owner | ✅ |
| dataset import | `is_project_admin()` | `MANAGE_DATASET_ADMIN` | admin, owner | admin, owner | ✅ |
| dataset export | `is_project_admin()` | `EXPORT` | admin, owner | admin, owner | ✅ |
| dataset datetime read | `check_project_access()` | `VIEW_DATASET_LIST` | member+ | member+ | ✅ |
| dataset datetime apply | `is_project_admin()` | `MANAGE_DATASET_ADMIN` | admin, owner | admin, owner | ✅ |
| clip read | `check_project_access()` | `VIEW_MEDIA` | member+ | member+ | ✅ |
| clip create / update / delete | `check_project_access()` | `MANAGE_DATASET` | member+ | member+ | ✅ |
| clip generate | `check_project_access()` | `MANAGE_DATASET` | member+ | member+ | ✅ |
| annotation_project CRUD | `is_project_admin()` | `MANAGE_DATASET_ADMIN` | admin, owner | admin, owner | ✅ |
| annotation_task read | `check_project_access()` | `VIEW_DETECTION` | member+ | member+ | ✅ |
| annotation_task complete | `check_project_access()` | `ANNOTATE` | member+ | member+ | ✅ |
| annotation read / write | `check_project_access()` | `ANNOTATE` | member+ | member+ | ✅ |
| confirmed_region CRUD | `is_project_admin()` | `MANAGE_DATASET_ADMIN` | admin, owner | admin, owner | ✅ |
| detection_run list / get | `check_project_access()` | `VIEW_DETECTION` | member+ | member+ | ✅ |
| detection_run start | `check_project_access()` | `RUN_INFERENCE` | member+ | member+ | ✅ |
| detection_run update / delete | `is_project_admin()` | `MANAGE_DATASET_ADMIN` | admin, owner | admin, owner | ✅ |
| evaluation list / get | `check_project_access()` | `VIEW_DETECTION` | member+ | member+ | ✅ |
| evaluation delete | `is_project_admin()` | `MANAGE_DATASET_ADMIN` | admin, owner | admin, owner | ✅ |

> "member+" means member, admin, owner, and superuser (with the project-scope
> allowlist). Guest and viewer differ per-endpoint; see spec/006 for the full
> visibility / toggle interactions, which are unaffected by this amendment.

### No member-visible UI changes

Every Svelte component currently rendering a CTA is already gated on its
existing permission via the auth store, role checks, or backend `403`. The
amendment does not introduce any new CTA, does not promote any existing CTA
into a higher visibility, and does not relax any existing CTA. Member users
see the same set of buttons and the same set of dataset-detail affordances
they see today.

### No new failure modes for existing tests

The current 641 security tests in main (post-Phase 16) exercise role × verb
combinations against live endpoints. Because the role × endpoint truth table
is preserved, no existing assertion changes outcome. The amendment adds
**new** assertions (see § 9) to lock in the vocabulary; it does not modify
any existing assertion.

---

## 7. Non-Goals

The following are explicitly **out of scope** for this spec:

- **Granting member dataset CRUD (Option B).** The spec/007 plan AD-1B
  Option B path — promoting member to dataset-resource mutation — is **not**
  adopted. That would be a product/UX change, not a vocabulary refinement.
- **New UI features.** No new Svelte pages, components, or CTAs are
  introduced by this spec. spec/007 plan Phase 2 may add `can()` call sites
  in existing components, but those call sites resolve to the same boolean
  the existing role check resolves to today.
- **Changes to viewer, guest, trusted-user, or superuser semantics.** None
  of the visibility toggles, ephemeral allowlists, or admin-allowlist
  behaviors from spec/006 change.
- **Changes to existing test failure modes.** The amendment is additive at
  the test level; no existing failing test starts passing because of it,
  and no existing passing test starts failing because of it.
- **Changes to ACTIONS catalog wire format.** The `Action` dataclass in
  `core/actions.py` is unchanged; only the values of `required_permission`
  for ~12 existing or newly-registered Actions reference the new
  `MANAGE_DATASET_ADMIN` enum member.

---

## 8. Implementation Reference

The implementation lives in
`spec/007-permission-test-coverage/plan.md` Rev.5.1, specifically:

- **Phase 2A.0** — "Introduce `MANAGE_DATASET_ADMIN` permission" (0.5 h
  budget per the plan's task table). This is the only Phase 2A task that
  touches the `Permission` enum and `ROLE_PERMISSIONS` matrix.
- **Phase 2A.1 – 2A.6** — Register dataset-resource Actions (dataset CRUD,
  import, datetime apply, annotation_project CRUD, confirmed_region CRUD,
  detection_run mutate, evaluation delete) with
  `required_permission=MANAGE_DATASET_ADMIN`. Register dataset-content
  Actions (clip CRUD, clip generate, detection_run start) with
  `required_permission=MANAGE_DATASET` (unchanged binding).
- **Phase 2B / 2C** — Frontend `can()` utility and `ProjectPermission` union
  codegen pick up the new permission automatically through the JSON fixture
  emitted by `permissions.py`.

No other spec is touched. Specifically, spec/006 itself is **not** rev'd
(see § 11 for release/merge constraints).

---

## 9. Test Strategy Reference

Verification lives in `spec/007-permission-test-coverage/plan.md` Phase 0
and Phase 2A test classes. The amendment-relevant assertions are:

- **`test_actions_coherence.py`** (spec/007 plan AD-4 class 1) — automatically
  fails CI if `MANAGE_DATASET_ADMIN` is absent from `ROLE_PERMISSIONS[admin]`
  or `ROLE_PERMISSIONS[owner]`, or if it is unexpectedly present in
  `ROLE_PERMISSIONS[member]` / `ROLE_PERMISSIONS[viewer]`.
- **`TestAllPermissionsCoveredByActions`** (spec/007 plan AD-4 class 2,
  scoped to `ENDPOINT_BACKED_PERMISSIONS` per AD-8) — fails if
  `MANAGE_DATASET_ADMIN` is declared but no `Action` in the catalog has it
  as `required_permission`.
- **`TestSuperuserOnlyActionsConsistent`** (spec/007 plan AD-4 class 3) —
  asserts that superusers on the project-scope allowlist receive
  owner-equivalent permissions, which includes `MANAGE_DATASET_ADMIN`.
- **Existing 641 security tests** — continue to pass unchanged. Tests that
  encode "member returns 403 on dataset DELETE" continue to pass because
  the endpoint still returns 403 (gated on `MANAGE_DATASET_ADMIN`, which
  members lack). Tests that encode "member can generate clips" continue to
  pass because the clip-generate endpoint still resolves to
  `MANAGE_DATASET`, which members hold.

Mutation testing (spec/006 Phase 17 §D, ongoing in spec/007 Phase 2A) covers
the new permission identically to existing permissions: mutating the
`required_permission` of any new Action to a wrong enum member must produce
at least one failing test.

No new E2E (Playwright) test is required for this amendment. The
Playwright datasets-row table in spec/007 plan § 4A is the contract:

| Screen | Owner | Admin | Member | Viewer |
|--------|-------|-------|--------|--------|
| `/datasets` list | "+ New Dataset" visible | "+ New Dataset" visible | NO "+ New Dataset" | NO "+ New Dataset" |
| `/datasets/{id}` detail | Edit/Delete + Generate/Add annotation | Edit/Delete + Generate/Add annotation | NO Edit/Delete; YES Generate/Add annotation | View-only |

This contract is already enforced by the existing role-based UI gating; the
amendment merely renames the boolean used for the Owner/Admin column from
"role ∈ {admin, owner}" to "`can('manage_dataset_admin', ctx)`".

---

## 10. Risk & Rollback

### Risks

- **Stale references to `MANAGE_DATASET` in code reviews.** A reviewer
  reading old spec/006 text might object that the matrix lists
  `MANAGE_DATASET` for member but the new Action uses
  `MANAGE_DATASET_ADMIN`. Mitigation: the back-reference added to
  spec/006 (see § 12) points readers here.
- **Code/spec drift if `_MEMBER_PERMS` is accidentally edited to include
  the new permission.** Mitigation: `test_actions_coherence.py` (see § 9)
  is a hard CI gate that catches this.
- **Misuse of `MANAGE_DATASET_ADMIN` on dataset-content endpoints.**
  Mitigation: the disambiguation rules in § 3.3, plus the explicit Action
  registrations in spec/007 plan Phase 2A.1 – 2A.6, plus the AD-4
  coherence tests.

### Rollback

The amendment is additive. To roll back, revert the spec/007 implementation
PR — which removes the enum entry, the matrix update, and the Action
registrations atomically. spec/008 itself can remain merged as historical
record, or be removed in a follow-up `git revert`. There is no data
migration to undo: no enum-to-DB mapping persists `MANAGE_DATASET_ADMIN` (it
lives only in code and in the `ACTIONS` catalog).

---

## 11. Release Plan

- This spec PR (spec/008) and the spec/007 implementation PR MUST merge in
  the **same release window**. A staging deploy that includes one but not
  the other is acceptable for review purposes; production deploys must ship
  both together.
- **spec/008 standalone merge is not useful.** Adding vocabulary without
  the corresponding code change leaves the spec/006 → backend divergence in
  place. spec/008 is therefore tagged as `companion-spec` in the PR title
  and the description links the implementation PR.
- The spec/007 implementation PR description MUST link back to this spec
  (URL of the merged spec/008 PR) so the vocabulary change has a stable
  reference for future readers.
- No feature flag is required. The amendment is a pure-code change with no
  user-visible surface and no runtime configuration.

---

## 12. Back-reference to spec/006

A single back-reference line is added to
`specs/006-permissions-redesign/spec.md` near the header / status block:

> *Amended by:* `spec/008-permissions-vocabulary-refinement` (2026-05-12) —
> introduces `MANAGE_DATASET_ADMIN` vocabulary refinement, behavior-preserving.

No other content in spec/006 is modified.

---

## 13. Acceptance Criteria

This spec is considered "accepted" when all of the following hold:

1. `apps/api/echoroo/core/permissions.py` declares
   `Permission.MANAGE_DATASET_ADMIN` between `MANAGE_DATASET` and
   `RUN_INFERENCE`.
2. `ROLE_PERMISSIONS[admin]` and `ROLE_PERMISSIONS[owner]` contain
   `MANAGE_DATASET_ADMIN`; `ROLE_PERMISSIONS[member]` and
   `ROLE_PERMISSIONS[viewer]` do not.
3. Every dataset-resource endpoint listed in § 6 resolves to an `Action`
   whose `required_permission` is `MANAGE_DATASET_ADMIN`.
4. Every dataset-content endpoint listed in § 6 resolves to an `Action`
   whose `required_permission` is `MANAGE_DATASET` (or the relevant content
   permission per the table).
5. spec/007 plan Phase 2A.0 and Phase 2A.1 – 2A.6 are complete.
6. `test_actions_coherence.py` passes in CI.
7. The pre-existing 641 security tests pass in CI with no modifications to
   their expected outcomes.
8. spec/006 contains the back-reference line.

When all eight hold, spec/008 transitions from `Draft` to `Accepted`.

---

## 14. Open Questions

None. The amendment was unanimously approved by @okam on 2026-05-12 as
"Option A (behavior-preserving)" per `spec/007-permission-test-coverage/plan.md`
Rev.5.1 Prereq-2.
