# Implementation Plan: Pre-Launch Permission Test Coverage

**Spec ID**: 007-permission-test-coverage
**Created**: 2026-05-11
**Revised**: 2026-05-11 (Rev.5.1)
**Status**: Rev.6 seeded browser E2E US1/US2/US3 plus Trusted Overlay lifecycle, Export/Search API-primary, Dataset ZIP export with audio, Search storage gate guards, Export-recordings success CSV, Reference-audio success stream, Media plus Clip API-primary, and Clip browser BFF media-token wiring complete
**Branch base**: main @ a7386bd3

---

## Revision History

| Rev | Date | Change Summary |
|-----|------|----------------|
| 1 | 2026-05-11 | Initial draft |
| 2 | 2026-05-11 | Codex Rev.1 feedback: AD-1 split into vocab vs behavior (P0-1); ALLOWLIST_PATHS structured metadata (P0-2); ProjectContext gains `authState` (重要 1); demotion mitigation upgraded to mandatory (重要 2); coherence test expanded from 5 → 9 classes (重要 3); vitest matrix-completeness instead of case-count target; Playwright boundary scenarios added; streaming endpoint category; CI gate for new-endpoint enforcement; timeline 18.5h → 24h (single) / 14h (parallel) |
| 3 | 2026-05-11 | Codex Rev.2 feedback: **Permission Vocabulary Glossary** (§ 4A) added to fix `MANAGE_DATASET` vs `MANAGE_DATASET_ADMIN` ambiguity (P0-Rev2-1); `ProjectContext` discriminated union tightened to forbid `role: non-null + authState: authenticated_non_member` (Rev2-1); AD-3 adds **projectId resolution convention** for 403 invalidation (Rev2-2); 2B.0 adds **CI regenerate + diff fail** for JSON fixture (Rev2-3); AD-4 class 3 renamed to **TestSuperuserOnlyActionsConsistent**, AD-6 unified to "admin = Action register, NOT allowlist" (Rev2-4); new **AD-8 Permission Category Classification** narrows `TestAllPermissionsCoveredByActions` scope to `ENDPOINT_BACKED_PERMISSIONS` (Rev2-5); AD-5 gains `last_reviewed_at`, `project_scope_allowed: bool = False` (Q12); AD-4 class 9 marked **interim**, future migration to per-Action `resource/operation/scope/category` metadata (Q13); permissionContext store helper formalized (Q16); streaming xfail upgraded to `strict=True` + tracking ID (Q17); **Prerequisite §0** added: AD-1B Option A approval + spec amendment (Q11); timeline 24h → 32-40h single / 20-24h parallel (3.5-5 days / 2.5-3 days) |
| 5.1 | 2026-05-11 | Codex Rev.5 final review: **conditional GO** with 3 mechanical conditions. All addressed inline: (1) `handle403` extended to guard against refetch-loop when project detail query itself returns 403 — adds `removeQueries` + redirect to `/no-access` path + per-projectId toast dedupe (5s); (2) `TAXON_SENSITIVITY_OVERRIDE_*_ACTION` registrations added to Phase 2A.5 with fallback plan if endpoints are not yet wired; (3) Phase 4.1 `26 permissions` replaced with `\|FRONTEND_PROJECT_PERMISSIONS\|`. Plan is now **GO for implementation**. |
| 5 | 2026-05-11 | Codex Rev.4 feedback: **重要-新1** `FRONTEND_PROJECT_PERMISSIONS` explicit allow-set added to AD-8 (was subtractive `ENDPOINT_BACKED - SEARCH_CROSS_PROJECT` which dropped COMPUTED_ONLY members like VIEW_PRECISE_LOCATION). AD-2 ProjectPermission union codegen pinned to FRONTEND_PROJECT_PERMISSIONS. **重要-新2** OVERRIDE_TAXON_SENSITIVITY moved from COMPUTED_ONLY → ENDPOINT_BACKED + included in FRONTEND_PROJECT_PERMISSIONS, resolving § 4A vs AD-8 conflict. **重要-新3** AllowlistEntry sample updated to include `last_reviewed_at`; field made required with no default. **重要-新4** test file renamed to `meta-completeness.test.ts` (vitest pattern); scope expanded to include `src/routes/**/*.svelte`; new `projectQueryOptions.ts` typed helper added (Q23). 403 handler home consolidated on `queryClient.ts`; `refetchType: 'active'` added so invalidation also refetches (重要-2 part 2). Test Strategy stale "336 cells" → "len(Permission) × 6 × 2" expression; vitest "26 entries" → emitted from FRONTEND_PROJECT_PERMISSIONS. |
| 4 | 2026-05-11 | Codex Rev.3 feedback: **P0-1** `AuthState` type missing `authenticated_member` member (TypeScript-uncompilable union); fixed by adding it. **P0-2** §7 Data Flow used `MANAGE_DATASET` for dataset DELETE — fixed to `MANAGE_DATASET_ADMIN` per § 4A rule 3. **重要-1** AD-5 review-date fail condition was reversed (`> today` → `< today`). **重要-2** AD-3 403 handler implementation made concrete with `QueryCache.onError` + `MutationCache.onError` hooks reading `query.meta` / `mutation.options.meta`; URL fallback regex tightened to strict UUID v4 (Q20). **重要-3** xeno_canto search disambiguated: only `external_proxy` allowlist (Action registration removed for `XENO_CANTO_SEARCH_ACTION` since the endpoint is non-project-scoped). **重要-4** `ProjectPermission` union boundary documented: excludes `SEARCH_CROSS_PROJECT`, `MANAGE_API_KEY`, `MANAGE_2FA`, `MANAGE_SITE` with rationale (Q18). **重要-5** Phase 3 / Test Strategy / File Map updated: renamed test class references, expanded file list with `endpoint_allowlist.py`, `permissionContext.ts`, `queryClient.ts`, `client.permissions.test.ts`, `test_meta_completeness.ts`, `test_allowlist_metadata.py`, CI workflow file. **Q17** xfail `raises=NotImplementedError` removed (over-constrains); tracking issues collected into `xfail_tracking.md` per Phase 0. **Q22** spec amendment scoped to new `spec/008-permissions-vocabulary-refinement` rather than spec/006 Rev.4. |
| 6 | 2026-05-15 | Added the seeded browser E2E extension plan for Data Surfaces, Vote/Comment, and future risky slices. Implementation completed through US1/US2/US3, Trusted Overlay read-only/lifecycle coverage, Export/Search API-primary plus Dataset ZIP with audio plus Search storage gate guard plus Export-recordings success CSV plus Reference-audio success stream coverage, Media recording plus Clip API-primary coverage, Clip browser BFF media-token wiring, and Claude hygiene follow-up; verified summaries and residual risks now live in `e2e-roadmap.md` and `tasks.md`. |

---

## 1. Summary

This plan closes the two remaining permission coverage gaps before public launch:

**Issue 2 — Endpoint x Role Matrix Coverage**: The ACTIONS catalog in
`apps/api/echoroo/core/actions.py` registers 62 of ~114 actionable project-scope
API routes. The coverage test (`apps/api/tests/contract/test_endpoint_coverage.py`)
is currently disabled with `@pytest.mark.skip`. ~52 project-scope endpoints remain
unregistered; the existing `test_permissions.py` marks them as `xfail` silently
instead of failing CI.

**Issue 3 — Frontend Permission Rendering Tests**: The frontend has zero vitest or
Playwright permission tests. Role-derived UI state is scattered across at least 3
pages using the `members.find()` anti-pattern.

ROI-ordered launch agenda (from pre-analysis Codex recommendation):
1. (2a) Enable test_endpoint_coverage.py as a hard-fail CI gate
2. (2c) ACTIONS catalog x Canonical Matrix coherence contract test
3. Thin Playwright E2E smoke matrix for key screens x roles
4. (2b) Full route-matrix registration

This plan executes all four items in 5 phases over 2 days.

## 2. Background and Context

specs/006-permissions-redesign (completed, main HEAD a7386bd3) delivered:
- ROLE_PERMISSIONS Canonical Matrix (28 permissions x 4 roles, permissions.py:263-322)
- ACTIONS catalog + register_action helper (actions.py, 667 lines, 62 registered)
- is_allowed gate + gate_action HTTP adapter (permissions.py:681-1300)
- 641 security tests in tests/security/
- test_permissions.py (842 lines): exhaustive is_allowed 28x6x2 — but xfail-skipping
  cells where no Action is registered

Current gaps confirmed by codebase audit (2026-05-11):

Backend — ACTIONS registration gap:
| Module | Endpoint count | Guard status |
|--------|---------------|--------------|
| api/v1/datasets.py | 12 | is_project_admin() legacy |
| api/v1/clips.py | 8 | check_project_access() legacy |
| api/v1/annotation_projects.py | 5 | check_project_access() legacy |
| api/v1/annotation_tasks.py | 4 | check_project_access() legacy |
| api/v1/annotations.py | 4 | check_project_access() legacy |
| api/v1/confirmed_regions.py | 3 | check_project_access() legacy |
| api/v1/detection_runs.py | 5 | check_project_access() legacy |
| api/v1/xeno_canto.py | 2 | check_project_access() legacy |
| api/v1/search/ | 5 | SearchGate only, no Action |
| api/v1/evaluation.py | 4 | check_project_access() legacy |
| Total unregistered | ~52 | — |

Non-project-scope routes (~15: auth, users/me, recorders, taxa, h3, setup) are
candidates for ALLOWLIST_PATHS, not ACTIONS.

Frontend — permission logic scatter:
| File | Pattern | Issue |
|------|---------|-------|
| routes/(app)/projects/[id]/settings/+page.svelte:63-76 | members.find(m => m.user.id === currentUser.id) | Stale on demotion |
| routes/(app)/projects/[id]/members/+page.svelte:50-58 | Same members.find() pattern | Stale on demotion |
| routes/(app)/projects/[id]/trusted/+page.svelte:76-79 | Uses project.current_user_role | Correct pattern |
| routes/(app)/projects/[id]/+page.svelte:47-57 | Uses project.current_user_role | Correct pattern |
| routes/(app)/projects/[id]/datasets/[datasetId]/+page.svelte | No role check at all | Delete button visible to all |

Frontend test files: 0 vitest tests, 0 Playwright permission tests.

## 2A. Prerequisites Before Implementation Start (Rev.3 — gated approvals)

These items MUST be confirmed before Phase 0 commences. They are NOT
implementation work and do NOT count toward the timeline estimate.

### Prereq-1: AD-1B Option A approval (product/user) — ✅ APPROVED 2026-05-12

**Status**: Approved by user @okam on 2026-05-12 (conversation record).

User/product owner acknowledges:
- `MANAGE_DATASET_ADMIN` permission is introduced as a vocabulary refinement.
- Current behavior is preserved: admin/owner retain destructive dataset CRUD,
  member retains current clip/annotation mutate access.
- No member-visible UI changes are intended.

Option B (spec-as-truth, expand member access) and Option C (escalate) are
NOT selected. Plan proceeds with Option A.

### Prereq-2: Spec amendment recording (per Codex Rev.2 Q11)

`MANAGE_DATASET_ADMIN` introduction touches the `Permission` enum and
`ROLE_PERMISSIONS` — these are spec/006 artifacts.

**Decision (Rev.4 per Codex Rev.3 Q22)**: Create
`spec/008-permissions-vocabulary-refinement/spec.md` as a follow-on
spec. Rationale: spec/006 is closed (Phase 16 main-merged) and a Rev.4
amendment process would be heavier than a small follow-on spec. spec/008
explicitly states "This spec amends the vocabulary in spec/006 without
changing observable behavior" and links back.

spec/008 deliverables (out of scope for this plan; tracked as a
companion PR):
- Add `MANAGE_DATASET_ADMIN` to the `Permission` enum table.
- Update the `ROLE_PERMISSIONS` matrix in spec/006 by reference.
- Document the § 4A vocabulary glossary as authoritative.
- Add a short note in `specs/006-permissions-redesign/spec.md` pointing to
  spec/008.

This plan's PR description MUST link to the spec/008 PR. Implementation
does NOT block on spec/008 merge, but they MUST be merged in the same
release window.

### Prereq-3: Phase 17 A-5 verification

The streaming endpoint mid-revoke handling (AD-6 / Q17) references Phase 17
A-5 work already merged to main (PR #21, HEAD `a051b175` per memory). Before
Phase 4.2:
- Read `tests/security/streaming/` to identify what streaming permission
  re-check IS implemented.
- Mark only the truly unimplemented mid-revoke scenarios as `xfail
  strict=True` with reason `"phase17-A5-mid-revoke-followup-issue-NNN"`.
- The xfail reasons MUST link to a tracking issue (open as part of Phase 0).

---

## 3. Goals / Non-Goals / Success Criteria

### Goals (Launch-blocking)
1. test_endpoint_coverage.py: skip removed, hard-fail enabled, ALLOWLIST_PATHS expanded,
   all ~52 unregistered routes either registered or allowlisted
2. ACTIONS x Canonical Matrix coherence: every registered Action's required_permission
   exists in ROLE_PERMISSIONS and is reachable from at least one role
3. Frontend can() single-layer: role derivation consolidated, members.find() replaced,
   0 dual-state patterns
4. Vitest parametric matrix: can() x 4 roles x 2 visibilities = >=200 cases
5. Playwright smoke matrix: 5 screens x 4 roles = 20 test scenarios, 0 console errors

### Non-Goals (Post-launch)
- Full OpenAPI auto-generated route matrix (all ~205 routes)
- Automatic OpenAPI diff for new routes
- Mutation testing integration for frontend permission layer
- Mobile browser testing

### Success Criteria (Quantitative)
| Criterion | Target |
|-----------|--------|
| test_endpoint_coverage.py CI result | 0 failures, hard-fail |
| ACTIONS registered (project-scope) | >=114 (62 existing + ~52 new) |
| xfail count in test_permissions.py | 0 |
| ACTIONS x Matrix coherence test | 100% pass (9 test classes — see AD-4) |
| ALLOWLIST_PATHS entries | All carry structured metadata (category + reason + owner + spec_ref) — see AD-5 |
| Frontend can() matrix completeness | 100% of (role × permission × visibility × authState) combinations covered by generated tests — see AD-2 / E.1 |
| Playwright permission scenarios | 25 scenarios (20 role×screen + 5 boundary), 0 failures |
| Frontend console errors during smoke | 0 |
| Demotion-race mitigation | On every 403 mutation, `['project', projectId]` invalidated AND refetched within current test plan |
| New-endpoint CI gate | PR adding APIRoute fails CI unless (ACTIONS registration) OR (ALLOWLIST_PATHS structured entry) is added — see AD-7 |
| Streaming endpoint coverage | xeno_canto stream + recordings stream both have ACTIONS entries with connection-time auth + documented mid-stream-revoke status (xfail OK for launch) — see AD-6 |
| CI gates added | 3 new (endpoint-coverage hard-fail + new-endpoint enforcement + allowlist metadata lint) |

## 4. Architecture Decisions

### § 4A. Permission Vocabulary Glossary (Rev.3 — Codex Rev.2 P0-Rev2-1 fix)

This glossary is the **single source of truth** for what each permission
means across spec, backend, frontend, tests, and Playwright assertions.
Any ambiguity here causes downstream confusion (Codex Rev.2 flagged
`MANAGE_DATASET` vs `MANAGE_DATASET_ADMIN` as the primary new P0).

**Member-held permissions** (existing — preserved by AD-1B Option A):

| Permission | Holders | Semantic scope | UI surfaces affected |
|------------|---------|----------------|----------------------|
| `MANAGE_DATASET` | viewer? / **member** / admin / owner | Manage CONTENT within a dataset: clips (create/update/delete/generate), annotations, confirmed_regions (read), detection_runs (read/start) | Clip toolbar, annotation editor, "Run inference" button |
| `ANNOTATE` | viewer (toggle) / member / admin / owner | Create/edit/delete annotations on detections; complete annotation tasks | Annotation editor save, detection-card vote-tag, task complete |
| `UPLOAD` | member / admin / owner | Upload new recordings | Upload page, dataset detail "Add recording" |
| `VIEW_DETECTION` | viewer / member / admin / owner (+ Public toggles) | View detection cards, search results, evaluation lists | Detection list, search results page |
| `VIEW_MEDIA` | viewer / member / admin / owner (+ Public toggles) | Play recording audio, view spectrograms | Audio player, spectrogram viewer |

**Admin-held permissions** (new — introduced for Rev.3):

| Permission | Holders | Semantic scope | UI surfaces affected |
|------------|---------|----------------|----------------------|
| `MANAGE_DATASET_ADMIN` (NEW) | **admin / owner only** | Lifecycle of the dataset RESOURCE itself: create/update/delete dataset, import, datetime config apply, annotation_project CRUD, confirmed_region CRUD, detection_run update/delete, evaluation delete | Dataset card "Edit/Delete", dataset list "+ New Dataset", annotation_project tab "Create" |
| `MANAGE_MEMBERS` | admin / owner | Invite/remove/role-change project members | `/members` page CRUD buttons |
| `MANAGE_TRUSTED` | admin / owner | Manage Trusted User allowlist | `/trusted` page CRUD |
| `EDIT_PROJECT` | admin / owner | Project name, description, visibility toggles | `/settings` form |
| `MANAGE_LICENSE` | admin / owner | Project license, attribution settings | `/settings` license section |
| `EXPORT` | admin / owner | Bulk export of detections, annotations, datasets | Export buttons across pages |

**Owner-only permissions** (existing):

| Permission | Holders | Semantic scope |
|------------|---------|----------------|
| `DELETE_PROJECT` | owner | Project deletion |
| `TRANSFER_OWNERSHIP` | owner | Ownership transfer |
| `OVERRIDE_TAXON_SENSITIVITY` | owner | Taxon sensitivity overrides |

**Critical disambiguation rules (consumers MUST follow)**:

1. **"Can the user manage THIS dataset's contents (clips/annotations)?"** →
   `can('manage_dataset', ctx)` → **member: yes**, viewer: no.
2. **"Can the user create/delete THIS dataset, OR edit its datetime config,
   OR manage annotation_projects?"** → `can('manage_dataset_admin', ctx)` →
   **member: no**, admin/owner: yes.
3. UI elements that look like dataset CRUD (e.g. "Delete dataset card",
   "Edit dataset name") MUST gate on `manage_dataset_admin`, never on
   `manage_dataset`.
4. UI elements that operate WITHIN a dataset (e.g. "Generate clips", "Add
   annotation") MUST gate on the relevant content permission
   (`manage_dataset`, `annotate`, etc.), not on `manage_dataset_admin`.

**Playwright expectation alignment** (Rev.3):

The Playwright datasets row reads (now consistent):

| Screen | Owner | Admin | Member | Viewer |
|--------|-------|-------|--------|--------|
| `/datasets` list | "+ New Dataset" visible | "+ New Dataset" visible | NO "+ New Dataset" | NO "+ New Dataset" |
| `/datasets/{id}` detail | "Edit dataset", "Delete dataset" visible; "Generate clips", "Add annotation" visible | Same as owner | NO "Edit/Delete dataset"; YES "Generate clips", "Add annotation" | View-only; no mutate buttons |

This table replaces the ambiguous Rev.2 row "View only (NO create per AD-1B)"
which mixed dataset-resource and dataset-content semantics.

### AD-1A: ACTIONS Catalog Gap Closure — Vocabulary Only (Behavior-Neutral)

Decision: Phase 2A registers all unregistered project-scope endpoints in
`core/actions.py` **using a permission that matches the CURRENTLY ENFORCED behavior**,
not necessarily the spec's `ROLE_PERMISSIONS` matrix. The goal of Phase 2A is to
**close the coverage gate without changing who can do what**.

Rule: For each unregistered endpoint, the chosen `required_permission` MUST satisfy
both conditions:
1. Currently-allowed roles (e.g. admin+owner under `is_project_admin()`) MUST
   have that permission in `ROLE_PERMISSIONS`.
2. Currently-denied roles (e.g. member under `is_project_admin()`) MUST NOT
   gain the permission as a side effect.

If no existing Permission satisfies both, the endpoint is **deferred** to AD-1B and
a `MANAGE_DATASET_ADMIN` (or similar) permission is introduced as a follow-up.

Initial permission assignment table (behavior-neutral mapping confirmed against
current guards):

| Route category | Current enforcement | Required permission | Rationale |
|---------------|---------------------|---------------------|-----------|
| dataset CRUD read | `check_project_access()` (member+) | VIEW_DATASET_LIST | Member already reads |
| dataset CRUD mutate | `is_project_admin()` (admin+owner) | **MANAGE_DATASET_ADMIN** (NEW, see AD-1B) | Member must NOT gain mutate as side effect |
| dataset import | `is_project_admin()` (admin+owner) | **MANAGE_DATASET_ADMIN** | Same as above |
| dataset export | `is_project_admin()` (admin+owner) | EXPORT (admin+owner only in matrix) | Verify EXPORT not in MEMBER row |
| dataset datetime config read | `check_project_access()` | VIEW_DATASET_LIST | Read-only |
| dataset datetime mutate | `is_project_admin()` | **MANAGE_DATASET_ADMIN** | Same as above |
| clip read | `check_project_access()` | VIEW_MEDIA | Member already reads |
| clip create/update/delete | `check_project_access()` (member+) | MANAGE_DATASET | Member already mutates clips |
| clip generate | `check_project_access()` (member+) | MANAGE_DATASET | Member already runs |
| annotation_project CRUD | `is_project_admin()` | **MANAGE_DATASET_ADMIN** | Currently admin-only |
| annotation_task read | `check_project_access()` | VIEW_DETECTION | Member already reads |
| annotation_task complete | `check_project_access()` (member+) | ANNOTATE | Member already annotates |
| annotation read/write | `check_project_access()` (member+) | ANNOTATE | Same |
| confirmed_region CRUD | `is_project_admin()` | **MANAGE_DATASET_ADMIN** | Currently admin-only |
| detection_run list/get | `check_project_access()` | VIEW_DETECTION | Read |
| detection_run create | `check_project_access()` (member+) | RUN_INFERENCE | Member already runs (verify) |
| detection_run update/delete | `is_project_admin()` | **MANAGE_DATASET_ADMIN** | Currently admin-only |
| xeno_canto proxy | `check_project_access()` | VIEW_MEDIA | Read |
| search sessions | SearchGate only | SEARCH_WITHIN_PROJECT | Already enforced |
| evaluation list/get | `check_project_access()` | VIEW_DETECTION | Read |
| evaluation create | `is_project_admin()` | RUN_INFERENCE or **MANAGE_DATASET_ADMIN** | Verify spec |
| evaluation delete | `is_project_admin()` | **MANAGE_DATASET_ADMIN** | Admin-only |

**Verification step required before Phase 2A.6**: For every row marked with
"Current enforcement", read the actual function body and confirm the role-check
matches the assumed gate. Discrepancies are escalated to AD-1B.

### AD-1B: Spec/Behavior Divergence — Product Decision Gate

The current `ROLE_PERMISSIONS` matrix (`permissions.py:263-322`) grants
`MANAGE_DATASET` to **member**. The current backend code uses
`is_project_admin()` (admin+owner only) for dataset mutate, import, datetime
mutate, annotation_project CRUD, confirmed_region CRUD, detection_run mutate,
evaluation mutate.

This is a **specification/implementation divergence**, not a test gap.

Resolution options:
- **Option A (default for Phase 2A — recommended)**: Preserve current behavior.
  Introduce `MANAGE_DATASET_ADMIN` permission. Update `ROLE_PERMISSIONS` so
  admin and owner have it, member does not. Member retains `MANAGE_DATASET` for
  the operations they currently can do (e.g. clip mutate, annotation mutate).
  This is a backwards-compatible vocabulary refinement.
- **Option B (defer to post-launch)**: Spec-as-source-of-truth. Member gains
  destructive dataset CRUD. Requires product/UX review of UI implications
  (e.g. member-visible delete buttons on dataset cards). Out of scope for launch.
- **Option C (escalate)**: Convene product decision pre-launch. Not in scope of
  this plan.

**This plan implements Option A.** A separate spec change (`spec.md` Rev.4 or
new spec 008-permissions-vocabulary-refinement) tracks the
`MANAGE_DATASET_ADMIN` introduction.

Phase 2A is **gated on Option A being approved**. If user/product picks Option
B or C, Phase 2A is replanned.

**Why this matters**: Codex Rev.1 flagged the original AD-1 as a P0 because
"テスト強化の名目で権限仕様を変更する" mixes scope. AD-1A enforces strict
behavioral neutrality; AD-1B records the spec divergence as a separate decision.

### AD-2: Frontend can() Utility Design

Decision: Synchronous function in new file `apps/web/src/lib/utils/permissions.ts`.
Uses `project.current_user_role` from the already-loaded Project query, AND
the auth/membership state from the auth store. Pure synchronous, no DOM, no
network.

**Codex Rev.1 fix (重要 1)**: `role: null` is ambiguous (guest vs authenticated
non-member vs unloaded vs pending invitation). Rev.2 introduces an explicit
`authState` discriminator. `role: null` ALONE never reaches `can()` — callers
MUST pass a fully-discriminated `ProjectContext`.

Type definitions:
  // Project membership role — null means "no project-level role assigned".
  export type ComputedRole = 'owner' | 'admin' | 'member' | 'viewer' | null;

  // Discriminator for the user's relationship to the current project.
  // Rev.4 fix (Codex Rev.3 P0-1): `authenticated_member` must be included
  // here, otherwise the ProjectContext union branch
  // `{ authState: 'authenticated_member', ... }` is unsatisfiable in
  // TypeScript.
  export type AuthState =
    | 'unauthenticated'           // Browser has no session (true guest)
    | 'authenticated_non_member'  // Logged in, but not a project member
    | 'authenticated_member'      // Logged in AND is a project member with a role
    | 'pending_invitation'        // Invited but not yet accepted
    | 'loading';                  // Auth or project query in-flight

  // Frontend ProjectPermission union: permissions evaluated in a
  // project-scoped UI context via can().
  //
  // Rev.5 fix (Codex Rev.4 重要-新1 + Q24): The CI drift gate (Phase 2B.0)
  // emits this union from the backend `FRONTEND_PROJECT_PERMISSIONS`
  // explicit allow-set (defined in AD-8). Adding a new permission to
  // ENDPOINT_BACKED_PERMISSIONS does NOT auto-expose it to the frontend;
  // it must also be added to FRONTEND_PROJECT_PERMISSIONS. This catches
  // cases like SEARCH_CROSS_PROJECT that are endpoint-backed but should
  // not appear in a per-project UI context.
  //
  // EXPLICIT EXCLUSIONS (NOT in FRONTEND_PROJECT_PERMISSIONS):
  //   - SEARCH_CROSS_PROJECT (evaluated globally, not in a single project)
  //   - MANAGE_API_KEY, MANAGE_2FA (USER_SCOPE_PERMISSIONS — handled by
  //     account/settings pages, not can(ctx))
  //   - MANAGE_SITE (SUPERUSER_ONLY_PERMISSIONS — admin UI uses a separate
  //     superuser-gate hook)
  //
  // INCLUDED (computed-only that the UI still gates on):
  //   - view_precise_location: response-filter-enforced; UI shows
  //     coarse vs precise location indicator based on this.
  //
  // Rev.4 fix (Codex Rev.3 重要-4) + Rev.5 fix (Codex Rev.4 重要-新1):
  // boundary explicitly documented and enforced by a backend allow-set.
  export type ProjectPermission =
    | 'view_project_metadata' | 'view_dataset_list' | 'view_media'
    | 'view_detection' | 'view_precise_location' | 'view_audit_log'
    | 'search_within_project' | 'download' | 'export'
    | 'vote' | 'comment' | 'create_tag' | 'annotate' | 'upload'
    | 'manage_dataset' | 'manage_dataset_admin'  // AD-1B vocabulary
    | 'run_inference' | 'train_model'
    | 'manage_members' | 'manage_trusted' | 'edit_project' | 'manage_license'
    | 'delete_project' | 'transfer_ownership' | 'override_taxon_sensitivity';
  // Note: 'manage_site' removed in Rev.4 — superuser-only, not in project can() context.

  // Discriminated context. Rev.3 fix (Codex Rev.2 重要-Rev2-1): role: non-null
  // is ONLY valid with authState: 'authenticated_member'. The Rev.2 union
  // incorrectly allowed `role: 'admin' + authState: 'authenticated_non_member'`,
  // which is semantically impossible.
  export type ProjectContext =
    | {
        // The user IS a project member with an explicit role.
        authState: 'authenticated_member';
        role: 'owner' | 'admin' | 'member' | 'viewer';
        visibility: 'public' | 'restricted';
        restrictedConfig?: RestrictedToggles;
      }
    | {
        // The user is NOT a project member. authState explains why.
        authState: 'unauthenticated' | 'authenticated_non_member' | 'pending_invitation' | 'loading';
        role: null;
        visibility: 'public' | 'restricted';
        restrictedConfig?: RestrictedToggles;
      };

  // TypeScript exhaustiveness: any caller constructing ProjectContext with
  // (role: 'admin', authState: 'authenticated_non_member') fails type-check.

  interface RestrictedToggles {
    allow_media_playback: boolean;
    allow_detection_view: boolean;
    allow_download: boolean;
    allow_export: boolean;
    allow_voting_and_comments: boolean;
    allow_precise_location_to_viewer: boolean;
  }

  export function can(permission: ProjectPermission, ctx: ProjectContext): boolean

Rationale:
- `project.current_user_role` is already in TanStack Query cache.
- `authState` is derived from `auth.store.ts` (existing).
- No async DB lookup needed.
- Mirrors backend `compute_effective_permissions()` contract.

Boundary semantics (CRITICAL — see vitest matrix in 4.1).

Per § 4A vocabulary glossary:
- `manage_dataset` = manage CONTENT (clips/annotations) within a dataset
- `manage_dataset_admin` = manage the dataset RESOURCE (CRUD, import, datetime)

| authState | role | visibility | view_media | vote | manage_dataset | manage_dataset_admin |
|-----------|------|------------|------------|------|----------------|----------------------|
| `loading` | null | * | false (safe default) | false | false | false |
| `unauthenticated` | null | public | true | true (matches backend public-vote) | false | false |
| `unauthenticated` | null | restricted | only if `allow_media_playback` | false | false | false |
| `authenticated_non_member` | null | public | true | true | false | false |
| `authenticated_non_member` | null | restricted | only if `allow_*` toggle | false | false | false |
| `pending_invitation` | null | * | false (invitation must be accepted first) | false | false | false |
| `authenticated_member` | viewer | restricted | true | only if `allow_voting_and_comments` | false | false |
| `authenticated_member` | member | * | true | true | **true** (member has MANAGE_DATASET per spec) | **false** (per AD-1B, member lacks MANAGE_DATASET_ADMIN) |
| `authenticated_member` | admin | * | true | true | true | true |
| `authenticated_member` | owner | * | true | true | true | true |

Note: `authenticated_member` role MUST come from `project.current_user_role`, not
from `members.find()` (see AD-3). The `members.find()` pattern is eliminated.

Helper builders (in `apps/web/src/lib/utils/permissions.ts` + new
`apps/web/src/lib/stores/permissionContext.ts`):

```typescript
// Pure function — given concrete inputs, returns a ProjectContext.
export function buildProjectContext(args: {
  authStore: { isAuthenticated: boolean; user: User | null };
  project: Project | undefined;
  projectQueryState: { isLoading: boolean; isError: boolean };
  pendingInvitationToken: string | null;
}): ProjectContext { ... }

// Svelte 5 store wrapper — derives the context for the current page.
// Rev.3 fix (Codex Rev.2 Q16): centralize derivation so pages don't
// re-implement the authState calculation.
export function usePermissionContext(args: {
  projectQuery: CreateQueryResult<Project, Error>;
  routeParams: { invitationToken?: string };
}): Readable<ProjectContext> { ... }
```

Callers in Svelte components:
```svelte
<script lang="ts">
  const ctx = usePermissionContext({ projectQuery, routeParams: $page.params });
</script>

{#if can('manage_dataset_admin', $ctx)}
  <button>Delete Dataset</button>
{/if}
```

This eliminates per-page recomputation of authState (Codex Rev.2 Q16
concern: "if each page composes auth.store + projectQuery + URL token
individually, scatter returns").

### AD-3: State Single-Source Strategy + Demotion-Race Mitigation

Decision: `project.current_user_role` (from `ProjectResponse`,
`types/index.ts:458`) is the ONLY source for role-derived UI decisions.

Anti-pattern locations to eliminate:
1. `settings/+page.svelte:63-76`: `members.find(m => m.user.id === currentUser.id)?.role === 'admin'`
   Replace with `can('edit_project', context)` (via Phase 2B's helper).
2. `members/+page.svelte:50-58`: `project.owner.id === currentUser.id || members.find(...)?.role === 'admin'`
   Replace with `can('manage_members', context)`.
3. `datasets/[datasetId]/+page.svelte`: no role check at all
   Add `can('manage_dataset_admin', context)` (per AD-1B) or `can('manage_dataset', context)` for non-destructive actions.

TanStack Query cache invalidation triggers (existing):
- Successful PATCH `/projects/{id}/members/{userId}` (role change)
- Successful DELETE `/projects/{id}/members/{userId}` (removal)
- Successful POST `/projects/{id}/transfer-ownership`

**Codex Rev.1 fix (重要 2 — demotion race is NOT acceptable as "no security impact")**:

The original Rev.1 plan classified the demotion-race UI inconsistency as
"LOW / no security impact". Codex Rev.1 review correctly identified that
frontend display alone is not sufficient because:
- Demoted user may have already opened a tab with stale `current_user_role`.
- Other tabs/windows may show stale UI for up to `staleTime` (currently
  unbounded, since project detail has no `staleTime` set).
- The user may attempt a destructive action that the UI permits but the
  backend rejects with 403 — bad UX and a support burden.

Rev.2 upgrades the mitigation to **mandatory** with the following enforcement:

| Layer | Mitigation | Implementation point | Phase |
|-------|-----------|----------------------|-------|
| Backend (authoritative) | All permission decisions enforced server-side via `gate_action` / `is_allowed` | Already implemented | n/a |
| Browser cache TTL | `staleTime: 30_000` for `['project', projectId]` queries; `refetchOnWindowFocus: true` | `apps/web/src/lib/api/projects.ts` | Phase 1.5 |
| 403-driven invalidation (Rev.3) | Global TanStack Query error handler: on any HTTP 403 (mutation OR query), resolve `projectId` via the convention below, invalidate `['project', projectId]`, refetch, show toast | `apps/web/src/lib/api/client.ts` | Phase 1.5 |
| Multi-tab sync | (post-launch) `BroadcastChannel` for permission claim invalidation | Out of scope for launch | post-launch waiver |

**Rev.3 + Rev.4 fix (Codex Rev.2 Rev2-2 + Codex Rev.3 重要-2): `projectId` resolution convention**

The global 403 handler needs to know WHICH project to invalidate. Rev.2 left
this unspecified. Rev.3 specified meta tagging but Codex Rev.3 noted the
implementation point was ambiguous (HTTP error objects do not normally
carry meta). Rev.4 specifies it as TanStack Query cache hooks.

Implementation:
- Wire `QueryCache.onError` and `MutationCache.onError` on the
  `QueryClient` constructor in `apps/web/src/lib/api/queryClient.ts`:

```typescript
const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error, query) => {
      if (error instanceof HTTPError && error.status === 403) {
        handle403(error, query.meta, { kind: 'query', queryKey: query.queryKey });
      }
    },
  }),
  mutationCache: new MutationCache({
    onError: (error, _variables, _context, mutation) => {
      if (error instanceof HTTPError && error.status === 403) {
        handle403(error, mutation.options.meta, { kind: 'mutation' });
      }
    },
  }),
});

const lastToastByProjectId = new Map<string, number>();      // dedupe state

function handle403(
  error: HTTPError,
  meta: QueryMeta | undefined,
  source: { kind: 'query' | 'mutation'; queryKey?: readonly unknown[] },
) {
  const projectId =
    (meta?.projectId as string | undefined)
    ?? extractProjectIdFromUrl(error.request.url)
    ?? null;
  if (!projectId) {
    console.warn('[permissions] 403 received without projectId context');
    toast.warn('Your permissions may have changed. Please refresh the page.');
    return;
  }

  // Rev.5.1 fix (Codex Rev.5 重要-1): avoid refetch-loop when the
  // project detail query itself returns 403 (e.g. access revoked).
  // Refetching the same query immediately would just produce another
  // 403 and another toast.
  const isProjectDetailQuery =
    source.kind === 'query'
    && Array.isArray(source.queryKey)
    && source.queryKey[0] === 'project'
    && source.queryKey[1] === projectId
    && source.queryKey.length === 2;

  if (isProjectDetailQuery) {
    // Don't refetch; remove from cache so a fallback UI can render.
    queryClient.removeQueries({ queryKey: ['project', projectId], exact: true });
    // Optionally redirect to a "no longer have access" landing page.
    goto(`/projects/${projectId}/no-access`);
  } else {
    // Mutation 403 or unrelated query 403: invalidate + active refetch.
    queryClient.invalidateQueries({
      queryKey: ['project', projectId],
      refetchType: 'active',
    });
  }

  // Toast dedupe: at most one toast per projectId per 5 seconds.
  const now = Date.now();
  const last = lastToastByProjectId.get(projectId) ?? 0;
  if (now - last > 5_000) {
    toast.warn('Your permissions have changed. Refreshing project access...');
    lastToastByProjectId.set(projectId, now);
  }
}
```

Project-scoped query/mutation definitions MUST set `meta: { projectId }`:

```typescript
createQuery({
  queryKey: ['project', projectId, 'datasets'],
  queryFn: () => api.listDatasets(projectId),
  meta: { projectId },                                 // ← required
});

createMutation({
  mutationFn: (input) => api.deleteDataset(projectId, input.datasetId),
  meta: { projectId },                                 // ← required
});
```

URL-extraction fallback regex (Codex Rev.3 Q20 — strict UUID v4):

```typescript
const PROJECT_ID_URL_RE =
  /(?:^|\/)projects\/([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})(?:\/|$|\?)/i;
```

This prevents matching `/projects/feed` or other hex-like segments. The
fallback is intentionally last-resort; the `meta` path is the canonical
mechanism.

Enforcement:
- A new lint test (`tests/unit/lib/api/test_meta_completeness.ts`) walks
  all `apps/web/src/lib/api/*.ts` files via AST and ensures every
  project-scoped query/mutation factory sets `meta: { projectId }`.
- A new vitest unit test `client.permissions.test.ts` verifies the 403
  handler invokes invalidation with the correct projectId for all three
  paths (meta, URL extraction, no-op).
- Mutation 403 AND query 403 both trigger invalidation.

**Test coverage for demotion race**:
- Phase 4.2 Playwright boundary scenario: "admin demoted to viewer mid-session" —
  user clicks a member-only button after demotion. Expected: 403 received,
  UI refreshes, button disappears, toast shown.

**Cross-tab / pending invitation states** are tracked via `authState` discriminator
in AD-2 (not implemented as live sync for launch; Rev.2 treats them as static
context derived from auth store + URL).

### AD-4: ACTIONS x Canonical Matrix Coherence Contract Test (Expanded)

Decision: New file `apps/api/tests/contract/test_actions_coherence.py`.

**Codex Rev.1 fix (重要 3)**: The original 5-class design only verified
"required_permission exists in ROLE_PERMISSIONS for ≥1 role" — i.e. structural
presence. This passes even if a `DATASET_DELETE_ACTION` is mistakenly set to
`required_permission=VIEW_DATASET_LIST` (since the permission exists). Rev.2
expands to 9 test classes that also verify **semantic alignment**: HTTP
method, path pattern, mutate vs read intent, scope mutual exclusion.

9 test classes (each is a hard-fail CI gate). Rev.3 fixes:
- Class 2 scope narrowed to `ENDPOINT_BACKED_PERMISSIONS` (Codex Rev.2 Rev2-5)
- Class 3 renamed and made consistent with AD-6 admin-as-Action approach (Rev2-4)

1. **TestEveryActionPermissionInMatrix** (original #1)
   For every registered Action `A`, `A.required_permission` MUST appear in
   `ROLE_PERMISSIONS[r]` for at least one role `r` (or in
   `USER_SCOPE_PERMISSIONS` / `SUPERUSER_ONLY_PERMISSIONS`). Catches typos
   and removed permissions.

2. **TestAllEndpointBackedPermissionsCoveredByActions** (Rev.3 — narrowed scope)
   For every `Permission` in `ENDPOINT_BACKED_PERMISSIONS` (see AD-8), at
   least one Action MUST have it as `required_permission`. Forces
   coverage WITHOUT inducing dummy Actions for `COMPUTED_ONLY_PERMISSIONS`
   like `VIEW_PRECISE_LOCATION` (which is enforced via response filter,
   not endpoint gate).

3. **TestSuperuserOnlyActionsConsistent** (Rev.3 — renamed from Rev.2
   "TestSuperuserOnlyActionsOnAllowlist")
   For every Action with `is_superuser_only=True`:
   - `required_permission` MUST be in `SUPERUSER_ONLY_PERMISSIONS` (e.g.
     `MANAGE_SITE`), AND
   - The bound route MUST have a `CurrentSuperuser` (or equivalent)
     dependency (AST scan).
   The Rev.2 name "OnAllowlist" was misleading: AD-6 mandates admin
   endpoints are registered as Actions, NOT placed in ALLOWLIST. This
   class verifies the Action-registration path is internally consistent.

4. **TestRolePermissionsSubsetOfEnum** (original #4)
   Every permission key in `ROLE_PERMISSIONS` MUST be a member of the
   `Permission` enum. Catches stale role-matrix entries.

5. **TestNoDuplicateActionNames** (original #5)
   Action `name` field is unique across the catalog.

6. **TestMutatingActionsHaveMutatingHttpMethod** (NEW — semantic gate)
   For every Action `A` where `A.is_mutating=True`, the bound route's HTTP
   method MUST be one of POST/PUT/PATCH/DELETE. Catches `GET` routes
   mistakenly flagged mutating, or mutating routes left as `is_mutating=False`.

7. **TestReadActionsHaveReadHttpMethod** (NEW — semantic gate)
   Action `A` with `is_mutating=False` AND `required_permission` in
   `READ_ONLY_PERMISSIONS` MUST be bound to `GET` (or `HEAD`). Exception
   list: search session creation (POST that semantically reads), explicitly
   documented.

8. **TestSuperuserAndPlatformScopeMutuallyExclusive** (NEW — Codex Rev.1 重要 3)
   For every Action, `is_superuser_only=True` AND `is_platform_scope=True`
   are mutually exclusive with `required_permission` being a project-scoped
   permission. Specifically:
   - If `is_superuser_only=True`: `required_permission` MUST be in
     `SUPERUSER_ONLY_PERMISSIONS` (e.g. `MANAGE_SITE`).
   - If `is_platform_scope=True`: `required_permission` MUST be in
     `USER_SCOPE_PERMISSIONS` (e.g. `MANAGE_API_KEY`).
   - These two flags MUST NOT both be `True` on the same Action.

9. **TestPathPatternMatchesPermissionCategory** (NEW — semantic gate, **INTERIM** per Codex Rev.2 Q13)
   For routes matching well-known path patterns, the Action's
   `required_permission` MUST be in a permission category set:
   - `/members/*` (mutate) → `MANAGE_MEMBERS`
   - `/trusted/*` (mutate) → `MANAGE_TRUSTED`
   - `/visibility` (mutate), `/restricted-toggles/*` (mutate) → `EDIT_PROJECT`
   - `/transfer-ownership` → `TRANSFER_OWNERSHIP`
   - `/datasets/{dataset_id}` (DELETE) → `MANAGE_DATASET_ADMIN` (per AD-1B)
   - `/license` (mutate) → `MANAGE_LICENSE`
   - `/audit-log` (read) → `VIEW_AUDIT_LOG`

   Implementation: regex table mapping path pattern → allowed permissions.
   Catches "delete dataset gated by VIEW_DATASET_LIST" class of bugs.

   **Interim status (Codex Rev.2 Q13)**: Regex on paths is brittle to URL
   refactors. Class 9 is acceptable for launch as a defense-in-depth gate.
   Post-launch migration target: per-Action structured metadata
   (`resource: 'dataset'`, `operation: 'delete'`, `scope: 'project'`,
   `category: 'destructive'`) so class 9 becomes a metadata-vs-permission
   consistency check rather than a path regex. Tracked in
   `PHASE17_BACKLOG.md` or follow-on spec.

Test class 2 (TestAllPermissionsCoveredByActions) and class 6/7/9 (semantic
gates) together drive Phase 2A. Class 8 enforces the
superuser/platform-scope hygiene Codex Rev.1 flagged.

Estimated test file size: ~350 LOC (up from ~200 LOC in Rev.1).

### AD-8: Permission Category Classification (Rev.3 — Codex Rev.2 Rev2-5 fix)

The Rev.2 coherence test class 2 required EVERY `Permission` to have at
least one registered Action. Codex Rev.2 correctly flagged that this would
induce dummy Actions for permissions that are NOT directly tied to a single
endpoint (e.g. `VIEW_PRECISE_LOCATION` is enforced via response field
filtering, not an endpoint gate).

Rev.3 introduces 4 mutually-exclusive permission category sets, defined
in `apps/api/echoroo/core/permissions.py`:

```python
# Permissions backed by exactly one (or more) HTTP endpoint, gated by an
# Action's required_permission. Class 2 of test_actions_coherence.py
# requires every member to have >=1 registered Action.
ENDPOINT_BACKED_PERMISSIONS: frozenset[Permission] = frozenset({
    Permission.VIEW_PROJECT_METADATA,
    Permission.VIEW_DATASET_LIST,
    Permission.VIEW_MEDIA,
    Permission.VIEW_DETECTION,
    Permission.VIEW_AUDIT_LOG,
    Permission.SEARCH_WITHIN_PROJECT,
    Permission.SEARCH_CROSS_PROJECT,
    Permission.DOWNLOAD,
    Permission.EXPORT,
    Permission.VOTE,
    Permission.COMMENT,
    Permission.CREATE_TAG,
    Permission.ANNOTATE,
    Permission.UPLOAD,
    Permission.MANAGE_DATASET,
    Permission.MANAGE_DATASET_ADMIN,  # NEW per AD-1B
    Permission.RUN_INFERENCE,
    Permission.TRAIN_MODEL,
    Permission.MANAGE_MEMBERS,
    Permission.MANAGE_TRUSTED,
    Permission.EDIT_PROJECT,
    Permission.MANAGE_LICENSE,
    Permission.DELETE_PROJECT,
    Permission.TRANSFER_OWNERSHIP,
    Permission.OVERRIDE_TAXON_SENSITIVITY,  # Rev.5: moved from COMPUTED_ONLY
})

# Permissions enforced via response transformations (filters / overlays)
# rather than endpoint gates. Class 2 does NOT require an Action for these.
COMPUTED_ONLY_PERMISSIONS: frozenset[Permission] = frozenset({
    Permission.VIEW_PRECISE_LOCATION,  # response filter; controls H3 resolution
})

# User-scoped permissions (no project context). Class 2 does NOT require
# a project-scope Action for these.
#
# Rev.5.2 note (Codex consultation 2026-05-12, applied during Phase 2A.0):
# Pre-AD-8 implementations of permissions.py included SEARCH_CROSS_PROJECT
# in USER_SCOPE_PERMISSIONS. This was an over-grant: SEARCH_CROSS_PROJECT
# depends on the visibility of the *searched* projects, not on the actor's
# own user-scope settings (which is the semantic for MANAGE_API_KEY /
# MANAGE_2FA). AD-8 intentionally moves SEARCH_CROSS_PROJECT into
# ENDPOINT_BACKED_PERMISSIONS, allowing matrix path enforcement:
#   - Authenticated on Public → granted via compute_effective_permissions
#   - Authenticated on Restricted → denied (matrix doesn't grant it)
# A targeted regression test asserting the new semantics is added in
# Phase 3 test_actions_coherence.py (or unit tests) per Codex
# recommendation.
USER_SCOPE_PERMISSIONS: frozenset[Permission] = frozenset({
    Permission.MANAGE_API_KEY,
    Permission.MANAGE_2FA,
})

# Superuser-only permissions. Per AD-6 these ARE backed by endpoints
# (admin endpoints with is_superuser_only=True), but live in a separate
# bucket for class 3/8 enforcement.
SUPERUSER_ONLY_PERMISSIONS: frozenset[Permission] = frozenset({
    Permission.MANAGE_SITE,
})

# Rev.5 fix (Codex Rev.4 重要-新2): OVERRIDE_TAXON_SENSITIVITY moved to
# ENDPOINT_BACKED_PERMISSIONS above. Reasoning: although it is conceptually
# owner-only and gated by superuser approval workflows downstream, the
# permission itself is checked at a project-scoped endpoint (submit
# override request) and held by owner role. The "superuser approval"
# step is a separate workflow not gated by this permission. § 4A glossary
# (owner-only) is consistent with this placement.

# Rev.5 fix (Codex Rev.4 Q24): Explicit frontend permission allow-set
# instead of subtraction. Adding a new permission to
# ENDPOINT_BACKED_PERMISSIONS does NOT automatically expose it to the
# frontend; it must also be added here. This is the source of truth for
# the TypeScript `ProjectPermission` union (emitted by 2B.0 export script).
FRONTEND_PROJECT_PERMISSIONS: frozenset[Permission] = frozenset({
    # Read permissions
    Permission.VIEW_PROJECT_METADATA,
    Permission.VIEW_DATASET_LIST,
    Permission.VIEW_MEDIA,
    Permission.VIEW_DETECTION,
    Permission.VIEW_AUDIT_LOG,
    Permission.SEARCH_WITHIN_PROJECT,
    # Computed-only that the UI still needs to know about
    Permission.VIEW_PRECISE_LOCATION,
    # Content/action permissions
    Permission.DOWNLOAD,
    Permission.EXPORT,
    Permission.VOTE,
    Permission.COMMENT,
    Permission.CREATE_TAG,
    Permission.ANNOTATE,
    Permission.UPLOAD,
    Permission.MANAGE_DATASET,
    Permission.MANAGE_DATASET_ADMIN,
    Permission.RUN_INFERENCE,
    Permission.TRAIN_MODEL,
    # Project management
    Permission.MANAGE_MEMBERS,
    Permission.MANAGE_TRUSTED,
    Permission.EDIT_PROJECT,
    Permission.MANAGE_LICENSE,
    Permission.DELETE_PROJECT,
    Permission.TRANSFER_OWNERSHIP,
    Permission.OVERRIDE_TAXON_SENSITIVITY,
})
# Explicitly excluded (intentional):
# - SEARCH_CROSS_PROJECT: evaluated globally, not in a single project context
# - MANAGE_API_KEY, MANAGE_2FA: USER_SCOPE_PERMISSIONS, handled by /account pages
# - MANAGE_SITE: SUPERUSER_ONLY, separate admin UI gate
assert FRONTEND_PROJECT_PERMISSIONS.issubset(
    ENDPOINT_BACKED_PERMISSIONS | COMPUTED_ONLY_PERMISSIONS
)
assert Permission.SEARCH_CROSS_PROJECT not in FRONTEND_PROJECT_PERMISSIONS

# Sanity check (runs as test class 1.5):
assert (ENDPOINT_BACKED_PERMISSIONS
        | COMPUTED_ONLY_PERMISSIONS
        | USER_SCOPE_PERMISSIONS
        | SUPERUSER_ONLY_PERMISSIONS) == set(Permission)
assert ENDPOINT_BACKED_PERMISSIONS.isdisjoint(COMPUTED_ONLY_PERMISSIONS)
# ... pairwise disjoint
```

This classification is the source of truth for:
- `test_actions_coherence.py` class 2 (scoped to `ENDPOINT_BACKED_PERMISSIONS`)
- `test_actions_coherence.py` class 3 / 8 (scoped to `SUPERUSER_ONLY_PERMISSIONS`)
- Frontend can() matrix tests: import `FRONTEND_PROJECT_PERMISSIONS` set
- Frontend `ProjectPermission` TypeScript union: emitted from `FRONTEND_PROJECT_PERMISSIONS`
- Backend `compute_effective_permissions()` documentation

### AD-5: ALLOWLIST_PATHS — Structured Metadata Records (Codex Rev.1 P0-2)

Decision: Replace `ALLOWLIST_PATHS: frozenset[str]` with a structured records
list. CI lints that every entry carries metadata.

**Codex Rev.1 fix (P0-2)**: A growing `frozenset[str]` becomes a graveyard for
endpoints that "should have been registered but were rushed". Rev.2 makes the
allowlist auditable.

New module: `apps/api/echoroo/core/endpoint_allowlist.py`

```python
from enum import Enum
from typing import NamedTuple
from datetime import date

class AllowlistCategory(str, Enum):
    AUTH_CALLBACK = "auth_callback"          # OAuth, magic link callbacks
    PUBLIC_STATIC = "public_static"          # /robots.txt, /favicon.ico
    INFRA_HEALTH = "infra_health"            # /health, /ready, /metrics
    DOCS_OPENAPI = "docs_openapi"            # /docs, /openapi.json
    SUPERUSER_ONLY = "superuser_only"        # /admin/* (validated separately)
    TOKEN_AUTH_ONLY = "token_auth_only"      # /invitations/{token} (token IS the auth)
    EXTERNAL_PROXY = "external_proxy"        # /xeno-canto/search (no project context)
    USER_SCOPED_ONLY = "user_scoped_only"    # /users/me/* (no project context)
    SETUP_BOOTSTRAP = "setup_bootstrap"      # /setup (only callable when no users exist)

class AllowlistEntry(NamedTuple):
    path_pattern: str            # e.g. "/api/v1/auth/login" or "/api/v1/admin/*"
    methods: frozenset[str]      # e.g. {"POST"} or {"*"}
    category: AllowlistCategory
    reason: str                  # Human-readable, REQUIRED, min 20 chars
    owner: str                   # GitHub handle, REQUIRED
    spec_ref: str | None         # e.g. "spec/006-permissions-redesign#FR-079"
    expiry: date | None          # If non-None, CI fails on expiry; warns 30 days before
    last_reviewed_at: date       # REQUIRED — no default. Rev.5: every entry must specify.
    review_interval_days: int = 180  # Rev.3 — quarterly review by default
    project_scope_allowed: bool = False  # Rev.3 — must be True explicitly to allow {project_id} in path_pattern

ALLOWLIST: list[AllowlistEntry] = [
    AllowlistEntry(
        path_pattern="/api/v1/auth/login",
        methods=frozenset({"POST"}),
        category=AllowlistCategory.AUTH_CALLBACK,
        reason="Pre-authentication endpoint; no project context exists",
        owner="@okam",
        spec_ref="spec/006-permissions-redesign#auth",
        expiry=None,
        last_reviewed_at=date(2026, 5, 11),  # Rev.5 — required for every entry
        review_interval_days=180,
        project_scope_allowed=False,
    ),
    # ... full list follows. EVERY entry MUST include last_reviewed_at;
    # the field is required by the lint and there is no default value.
]
```

`test_endpoint_coverage.py` imports `ALLOWLIST` and matches route paths
against entries.

**Allowlist lint** (`apps/api/tests/contract/test_allowlist_metadata.py`) (Rev.3):
- Every entry has non-empty `reason` (>= 20 chars).
- Every entry has non-empty `owner`.
- `superuser_only` category entries: corresponding routes MUST have
  `CurrentSuperuser` dependency (statically checked via AST scan).
- `token_auth_only` category entries: corresponding routes MUST have
  `_resolve_invitation_token`-style dependency.
- Entries with `expiry` < today fail CI.
- Entries with `last_reviewed_at + review_interval_days` < today (i.e. the
  entry is past its review-by date) fail CI. The inverse comparison would
  fail every valid entry — Rev.3 had this reversed; Rev.4 corrected per
  Codex Rev.3 重要-1.
- Entries where `path_pattern` contains `{project_id}` MUST have
  `project_scope_allowed: True` AND require an explicit owner-approved
  justification in `reason` (Rev.3, Codex Rev.2 Q12). Default `False`
  means project-scoped paths CANNOT silently land in the allowlist.
- AD-6 admin endpoints MUST NOT appear in the allowlist (they are
  registered as Actions per the unified approach).

This prevents the "silent allowlist drift" Codex flagged as P0-2 and
addresses Codex Rev.2 Q12.

### AD-6: Streaming / SSE / Admin / Audit / Bulk Endpoint Categorization

**Codex Rev.1 fix (改善提案)**: streaming endpoints (xeno_canto.stream,
recordings stream) and admin/audit/export/bulk operations were not explicitly
categorized in Rev.1.

Decision: These categories receive explicit treatment.

**Streaming endpoints** (`StreamingResponse` return type):
- `xeno_canto.stream` → `XENO_CANTO_STREAM_ACTION` with `required_permission=VIEW_MEDIA`
- Existing `recordings.media` → `RECORDING_MEDIA_ACTION` (already registered)

Connection-time authorization: `gate_action` runs once at connection establishment.

**Mid-stream permission revoke** (e.g. user demoted while streaming):

Per Codex Rev.2 Q17, the xfail approach is conditionally acceptable.
Rev.3 strengthens the handling:

1. **Pre-Phase 4.2 audit** (Prereq-3): read `tests/security/streaming/` to
   identify what Phase 17 A-5 already implemented (PR #21 / HEAD `a051b175`
   per memory).
2. For scenarios A-5 ALREADY covers: write them as **passing tests**, not
   xfail.
3. For genuinely unimplemented scenarios: mark `@pytest.mark.xfail(
   strict=True, reason="mid-stream-revoke: tracked in #<ISSUE_NUMBER>")`.
   Do NOT use `raises=NotImplementedError` — it locks the failure mode
   and breaks if the implementation later raises a different error
   (e.g. assertion failure). Leave `raises` unset so any failure
   satisfies xfail.
4. Phase 0 includes opening a tracking issue per xfail scenario; capture
   the issue numbers in a new file
   `specs/007-permission-test-coverage/xfail_tracking.md` for the PR
   reviewer's convenience.
5. The Phase 4 DoD verifies all xfail entries are `strict=True` AND have
   an issue-number tracking ID in the reason text.

This implements the Codex Rev.2 Q17 requirement: "xfail strict=True かつ
tracking ID 付き ... 黙認 xfail は不可".

**Admin endpoints** (`/api/v1/admin/*`):
- All admin endpoints already require `CurrentSuperuser` dependency.
- **Decision (Rev.3 — unified per Codex Rev.2 Rev2-4)**: Admin endpoints
  ARE registered as Actions with `is_superuser_only=True` and
  `required_permission=MANAGE_SITE`. They are NOT in `ALLOWLIST`. This
  unifies AD-4 class 3 (`TestSuperuserOnlyActionsConsistent`) and AD-5
  (`AllowlistCategory.SUPERUSER_ONLY` is reserved for hypothetical future
  use and currently empty).
- `AllowlistCategory.SUPERUSER_ONLY` enum value remains defined but
  unused in initial `ALLOWLIST`; reserved as escape hatch only.
- The Rev.2 ambiguity between "admin = Action" (AD-6) and
  "SuperuserOnlyActionsOnAllowlist" (AD-4 class 3) is resolved by
  renaming class 3 and clarifying both AD-4 and AD-6 point to the same
  registration path.

**Audit endpoints** (`/api/v1/projects/{id}/audit-log`):
- Already registered as `AUDIT_LOG_ACTION` per memory.
- Phase 3 coherence test class 9 verifies path pattern `/audit-log` →
  `VIEW_AUDIT_LOG` permission.

**Export / import / bulk endpoints**:
- Export → `EXPORT` permission (admin+owner in matrix).
- Import → `MANAGE_DATASET_ADMIN` (per AD-1B).
- Bulk operations (e.g. bulk-delete recordings) inherit the destructive
  operation's permission. Documented per-endpoint in Phase 2A registration table.

### AD-7: CI Gate — New Endpoint Must Register or Allowlist

**Codex Rev.1 fix (改善提案)**: To prevent silent regression, adding a new
APIRoute MUST require either an ACTIONS entry or an ALLOWLIST_PATHS entry.

Decision: Implement as part of Phase 2A.7 (skip removal). The existing
`test_endpoint_coverage.py` already enforces this (every route MUST be in
ACTIONS or ALLOWLIST). Once hard-fail is on, this gate is automatic.

Additional pre-commit hint: `lint_permission_guard.py` already detects routes
without `@check_action`/`@gate_action`. Rev.2 extends it to:
- Emit a hint when a new route is added without ACTIONS registration.
- Emit a hint when a route is added to ALLOWLIST without metadata fields filled.

No new tooling needed beyond Phase 2A; this AD just makes the enforcement
explicit in documentation.

## 5. Phase Breakdown

### Phase 0: Branch + Baseline (0.5h)

Tasks:
- [ ] Create branch 007-permission-test-coverage from main
- [ ] Run existing test suite to establish baseline
- [ ] Count xfail entries: pytest apps/api/tests/contract/test_permissions.py -v 2>&1 | grep -c XFAIL

Completion gate: Baseline xfail count recorded, branch created.

### Phase 1: State Single-Source Consolidation (3h)

Must be completed before Phase 2B.

1.1 Audit existing state sources (0.5h)
Files:
- apps/web/src/routes/(app)/projects/[id]/settings/+page.svelte (lines 63-76)
- apps/web/src/routes/(app)/projects/[id]/members/+page.svelte (lines 50-58)
- apps/web/src/routes/(app)/projects/[id]/datasets/[datasetId]/+page.svelte (no role check)

1.2 Fix settings/+page.svelte (0.5h)
Current (lines 63-76):
  const isOwner = $derived(currentUser && project && project.owner.id === currentUser.id);
  const hasAdminAccess = $derived((() => {
    if (!currentUser || !project) return false;
    if (isOwner) return true;
    const member = members.find((m) => m.user.id === currentUser.id);
    return member?.role === 'admin';
  })());

Replace with:
  const isOwner = $derived(project?.current_user_role === 'owner');
  const hasAdminAccess = $derived(
    project?.current_user_role === 'owner' || project?.current_user_role === 'admin'
  );

Remove members state and listMembers API call from loadProject().

1.3 Fix members/+page.svelte (0.5h)
Current (lines 50-58):
  const isAdmin = $derived((() => {
    if (!currentUser || !project) return false;
    if (project.owner.id === currentUser.id) return true;
    const member = members.find((m) => m.user.id === currentUser.id);
    return member?.role === 'admin';
  })());

Replace with:
  const isAdmin = $derived(
    project?.current_user_role === 'owner' || project?.current_user_role === 'admin'
  );

Note: members array is still needed for the list UI, not for role derivation.

1.4 Fix datasets/[datasetId]/+page.svelte (0.5h)

Per § 4A vocabulary glossary, this page has TWO distinct UI regions:
- **Dataset resource region** (Edit/Delete dataset, Edit datetime config) →
  gate on `can('manage_dataset_admin', ctx)` → **admin/owner only**.
- **Dataset content region** (Generate clips, Add annotation, Run inference) →
  gate on `can('manage_dataset', ctx)` (or specific finer-grained permission
  like `can('annotate', ctx)`) → **member/admin/owner**.

Implementation (uses the can() utility from Phase 2B — Phase 1.4 only sets up
the data query; the can() call comes in Phase 2B.3):
  const projectQuery = $derived(createQuery({
    queryKey: ['project', projectId],
    queryFn: () => projectsApi.get(projectId),
    staleTime: 30_000,                  // AD-3
    refetchOnWindowFocus: true,         // AD-3
  }));
  // Phase 2B.3 inserts:
  //   const ctx = $derived(contextFromProject($projectQuery.data, authState));
  //   const canEditDatasetResource = $derived(can('manage_dataset_admin', ctx));
  //   const canAddDatasetContent = $derived(can('manage_dataset', ctx));

Note: The Rev.2 `canManageDataset` boolean that included member was the
Codex Rev.2 P0-Rev2-1 issue. Rev.3 splits it into two booleans aligned with
§ 4A glossary.

1.5 Demotion-race mitigation (2h — Rev.5 expanded per AD-3 final form)

Audit + implement:
- TanStack Query mutation handlers in `apps/web/src/lib/api/projects.ts`:
  - `updateMemberRole` → invalidates `['project', projectId]`
  - `removeMember` → invalidates `['project', projectId]`
  - `transferOwnership` → invalidates `['project', projectId]`
- Project detail query config:
  - `staleTime: 30_000`
  - `refetchOnWindowFocus: true`
  - `meta: { projectId }` (REQUIRED — see AD-3 Rev.4)
- **Global 403 handler in `apps/web/src/lib/api/queryClient.ts`** (Rev.5:
  consolidated location; Rev.3/4 said both `client.ts` and `queryClient.ts`
  — Rev.5 picks `queryClient.ts` as the single home):
  - Wire `QueryCache.onError` + `MutationCache.onError` per AD-3 code sketch.
  - On 403: resolve projectId (meta → URL fallback → no-op).
  - **Invalidate AND refetch** (Rev.5 explicit per Codex Rev.4 重要-2 part 2):
    `queryClient.invalidateQueries({ queryKey: ['project', projectId], refetchType: 'active' })`.
    Default `invalidateQueries` only marks stale; the `refetchType: 'active'`
    option forces the active project query to refetch immediately so the
    UI updates without a focus event.
  - Show toast "Your permissions have changed. Refreshing project access..."

Completion gate (Phase 1):
- Gate 1: `npm run check` passes
- No `members.find()` for role derivation (grep clean)
- Settings page loads without `listMembers` network call
- Project query has `staleTime: 30_000` and `refetchOnWindowFocus: true`
- 403 error handler invalidates + refetches + toasts

### Phase 2A: ACTIONS Registration + Endpoint Coverage Hard-Fail (8h, was 6h)

Fully parallel with Phase 2B (different files).

**Rev.2 prerequisite**: AD-1B Option A approved (member retains current
non-destructive permissions; `MANAGE_DATASET_ADMIN` introduced for the
admin-only operations). If Option A is rejected, Phase 2A is replanned.

2A.0 Introduce MANAGE_DATASET_ADMIN permission (0.5h — NEW per AD-1B)
- `apps/api/echoroo/core/permissions.py`: add `MANAGE_DATASET_ADMIN` to
  `Permission` enum (between `MANAGE_DATASET` and `RUN_INFERENCE`).
- Update `_ADMIN_PERMS` and `_OWNER_PERMS` to include the new permission.
- Update `_MEMBER_PERMS` to NOT include it (preserves current behavior).
- Re-run `tests/unit/core/test_permissions_matrix.py` baseline.
- Re-run `tests/contract/test_permissions.py` baseline.

2A.1 Build structured ALLOWLIST (1.5h, expanded per AD-5)

Create new module `apps/api/echoroo/core/endpoint_allowlist.py` with
`AllowlistCategory` enum, `AllowlistEntry` NamedTuple, and `ALLOWLIST` list.

Initial population (each entry MUST have category + reason + owner; spec_ref
where applicable):
- `auth_callback`: `/api/v1/auth/login`, `/api/v1/auth/register`,
  `/api/v1/auth/refresh`, `/api/v1/auth/logout`, `/api/v1/auth/oauth/*`,
  `/web-api/v1/auth/*`, `/web-api/v1/account/dsr/*`
- `user_scoped_only`: `/api/v1/users/me`, `/api/v1/users/me/password`,
  `/api/v1/users/me/api-tokens/*`, `/api/v1/users/me/2fa/*`
- `external_proxy`: `/api/v1/xeno-canto/search` (non-project-scoped global proxy)
- `infra_health`: `/health`, `/ready`, `/metrics`
- `docs_openapi`: `/docs`, `/openapi.json`, `/redoc`
- `setup_bootstrap`: `/api/v1/setup` (only callable when no users exist)
- `token_auth_only`: `/web-api/v1/projects/{id}/invitations/{token}` (token IS auth)
- For `/api/v1/admin/*`: use AD-6 option (a) — register Actions with
  `is_superuser_only=True`, NOT allowlist.

Update `test_endpoint_coverage.py` to import `ALLOWLIST` instead of the
hard-coded `ALLOWLIST_PATHS` frozenset.

Create `apps/api/tests/contract/test_allowlist_metadata.py` (~80 LOC) per AD-5.

2A.2 Register Actions for datasets in actions.py (1h)
**Permission assignments updated per AD-1B (Option A) — behavior preserving:**
  DATASET_LIST_ACTION: required_permission=VIEW_DATASET_LIST
  DATASET_GET_ACTION: required_permission=VIEW_DATASET_LIST
  DATASET_CREATE_ACTION: required_permission=MANAGE_DATASET_ADMIN, is_mutating=True
  DATASET_UPDATE_ACTION: required_permission=MANAGE_DATASET_ADMIN, is_mutating=True
  DATASET_DELETE_ACTION: required_permission=MANAGE_DATASET_ADMIN, is_mutating=True
  DATASET_IMPORT_ACTION: required_permission=MANAGE_DATASET_ADMIN, is_mutating=True
  DATASET_EXPORT_ACTION: required_permission=EXPORT
  DATASET_STATISTICS_ACTION: required_permission=VIEW_DATASET_LIST
  DATASET_DATETIME_CONFIG_ACTION: required_permission=VIEW_DATASET_LIST
  DATASET_DATETIME_AUTODETECT_ACTION: required_permission=MANAGE_DATASET_ADMIN, is_mutating=False  # POST that reads; see Q6
  DATASET_DATETIME_TEST_ACTION: required_permission=VIEW_DATASET_LIST
  DATASET_DATETIME_APPLY_ACTION: required_permission=MANAGE_DATASET_ADMIN, is_mutating=True

2A.3 Register Actions for clips (0.5h)
  CLIP_LIST_ACTION: required_permission=VIEW_MEDIA
  CLIP_GET_ACTION: required_permission=VIEW_MEDIA
  CLIP_CREATE_ACTION: required_permission=MANAGE_DATASET, is_mutating=True
  CLIP_UPDATE_ACTION: required_permission=MANAGE_DATASET, is_mutating=True
  CLIP_DELETE_ACTION: required_permission=MANAGE_DATASET, is_mutating=True
  CLIP_GENERATE_ACTION: required_permission=MANAGE_DATASET, is_mutating=True
  CLIP_AUDIO_ACTION: required_permission=VIEW_MEDIA
  CLIP_DOWNLOAD_ACTION: required_permission=DOWNLOAD

2A.4 Register Actions for annotation_projects, annotation_tasks, annotations (1h)
**Per AD-1B: annotation_project CRUD is currently admin-only**
  ANNOTATION_PROJECT_LIST_ACTION: required_permission=VIEW_DETECTION
  ANNOTATION_PROJECT_GET_ACTION: required_permission=VIEW_DETECTION
  ANNOTATION_PROJECT_CREATE_ACTION: required_permission=MANAGE_DATASET_ADMIN, is_mutating=True
  ANNOTATION_PROJECT_UPDATE_ACTION: required_permission=MANAGE_DATASET_ADMIN, is_mutating=True
  ANNOTATION_PROJECT_DELETE_ACTION: required_permission=MANAGE_DATASET_ADMIN, is_mutating=True
  ANNOTATION_PROJECT_EXPORT_ACTION: required_permission=EXPORT
  ANNOTATION_TASK_LIST_ACTION: required_permission=VIEW_DETECTION
  ANNOTATION_TASK_GET_ACTION: required_permission=VIEW_DETECTION
  ANNOTATION_TASK_COMPLETE_ACTION: required_permission=ANNOTATE, is_mutating=True
  ANNOTATION_TASK_SKIP_ACTION: required_permission=ANNOTATE, is_mutating=True
  ANNOTATION_GET_ACTION: required_permission=VIEW_DETECTION
  ANNOTATION_CREATE_ACTION: required_permission=ANNOTATE, is_mutating=True
  ANNOTATION_UPDATE_ACTION: required_permission=ANNOTATE, is_mutating=True
  ANNOTATION_DELETE_ACTION: required_permission=ANNOTATE, is_mutating=True

2A.5 Register Actions for remaining modules (1h)
**Per AD-1B + AD-6:**
  CONFIRMED_REGION_LIST_ACTION: required_permission=VIEW_DETECTION
  CONFIRMED_REGION_CREATE_ACTION: required_permission=MANAGE_DATASET_ADMIN, is_mutating=True
  CONFIRMED_REGION_DELETE_ACTION: required_permission=MANAGE_DATASET_ADMIN, is_mutating=True
  DETECTION_RUN_LIST_ACTION: required_permission=VIEW_DETECTION
  DETECTION_RUN_GET_ACTION: required_permission=VIEW_DETECTION
  DETECTION_RUN_CREATE_ACTION: required_permission=RUN_INFERENCE, is_mutating=True
  DETECTION_RUN_UPDATE_ACTION: required_permission=MANAGE_DATASET_ADMIN, is_mutating=True
  DETECTION_RUN_DELETE_ACTION: required_permission=MANAGE_DATASET_ADMIN, is_mutating=True
  # XENO_CANTO_SEARCH_ACTION: REMOVED in Rev.4 (Codex Rev.3 重要-3).
  # The /api/v1/xeno-canto/search endpoint is non-project-scoped (global
  # external proxy) and is in ALLOWLIST as external_proxy category.
  # If a project-scoped variant is added later (e.g. logged search history
  # tied to a project), register an Action at that time.
  XENO_CANTO_STREAM_ACTION: required_permission=VIEW_MEDIA  # streaming — see AD-6; project-scoped media playback
  SEARCH_SESSION_CREATE_ACTION: required_permission=SEARCH_WITHIN_PROJECT, is_mutating=True  # POST that reads conceptually; see Risk 5
  SEARCH_SESSION_GET_ACTION: required_permission=SEARCH_WITHIN_PROJECT
  SEARCH_SESSION_LIST_ACTION: required_permission=SEARCH_WITHIN_PROJECT
  SEARCH_SESSION_ANNOTATE_ACTION: required_permission=ANNOTATE, is_mutating=True
  SEARCH_SIMILARITY_ACTION: required_permission=SEARCH_WITHIN_PROJECT
  EVALUATION_CREATE_ACTION: required_permission=RUN_INFERENCE, is_mutating=True
  EVALUATION_LIST_ACTION: required_permission=VIEW_DETECTION
  EVALUATION_GET_ACTION: required_permission=VIEW_DETECTION
  EVALUATION_DELETE_ACTION: required_permission=MANAGE_DATASET_ADMIN, is_mutating=True

  # Taxon sensitivity overrides — Rev.5.1 per Codex Rev.5 重要-2:
  # OVERRIDE_TAXON_SENSITIVITY was moved to ENDPOINT_BACKED_PERMISSIONS in
  # AD-8, so class 2 of test_actions_coherence.py requires >=1 Action.
  # Phase 2A.5 introduces / confirms the following Actions:
  TAXON_SENSITIVITY_OVERRIDE_LIST_ACTION: required_permission=VIEW_DETECTION  # read existing overrides
  TAXON_SENSITIVITY_OVERRIDE_SUBMIT_ACTION: required_permission=OVERRIDE_TAXON_SENSITIVITY, is_mutating=True
  TAXON_SENSITIVITY_OVERRIDE_REVOKE_ACTION: required_permission=OVERRIDE_TAXON_SENSITIVITY, is_mutating=True
  # Implementation prerequisite: read apps/api/echoroo/api/v1/taxa/* to
  # confirm endpoint shape before registering. If endpoints are still in
  # spec/006 Phase 11 wiring and not yet exposed, the action registration
  # is deferred to spec/008 follow-up and OVERRIDE_TAXON_SENSITIVITY is
  # temporarily moved BACK to COMPUTED_ONLY_PERMISSIONS for launch.

  # Admin endpoints — per AD-6 option (a)
  ADMIN_USERS_LIST_ACTION: required_permission=MANAGE_SITE, is_superuser_only=True
  ADMIN_USERS_GET_ACTION: required_permission=MANAGE_SITE, is_superuser_only=True
  ADMIN_USERS_UPDATE_ACTION: required_permission=MANAGE_SITE, is_superuser_only=True, is_mutating=True
  # ... (full admin endpoint enumeration in implementation PR)

2A.6 Wire gate_action in each affected router (1.5h)
For each of the 10 modules, replace legacy guard with gate_action pattern:

  Before:
    async def list_datasets(project_id: UUID, current_user: CurrentUser, ...) -> DatasetListResponse:
        datasets, total = await service.list_by_project(current_user.id, project_id, ...)

  After:
    async def list_datasets(
        project_id: UUID, current_user: CurrentUser, request: Request, db: DbSession, ...
    ) -> DatasetListResponse:
        project = await gate_action(
            action=DATASET_LIST_ACTION,
            project_id=project_id,
            current_user=current_user,
            request=request,
            db=db,
        )
        datasets, total = await service.list_by_project(project_id=project.id, ...)

Note: gate_action returns the loaded Project row, eliminating duplicate SELECT.

2A.7 Enable hard-fail in test_endpoint_coverage.py (0.5h)
Remove @pytest.mark.skip decorator. Verify 0 failures.

Completion gate (Phase 2A):
- Gate 1: uv run mypy . passes
- Gate 1: uv run ruff check . passes
- Gate 2: pytest apps/api/tests/contract/test_endpoint_coverage.py — 0 failures
- Gate 2: pytest apps/api/tests/contract/test_permissions.py — 0 xfail entries

### Phase 2B: Frontend can() Utility + Scatter Replacement (5h, was 4h)

Fully parallel with Phase 2A.

**Rev.2 contract freeze**: Before parallel 2A/2B start, the
`ProjectPermission` string-union enum (AD-2) MUST be agreed between backend
and frontend. The backend list lives in `permissions.py::Permission` enum;
frontend imports a mirrored TypeScript union. Coherence is enforced by 2B.2
parametric tests.

2B.1 Create `apps/web/src/lib/utils/permissions.ts` (2.5h)
New file. Defines:
- `ComputedRole`, `AuthState`, `ProjectPermission`, `ProjectContext` types (per AD-2).
- `can(permission, ctx): boolean` — pure synchronous.
- `contextFromProject(project, authState): ProjectContext` helper.

Implementation mirrors `compute_effective_permissions()` in
`permissions.py:476-566`. Role-to-permission tables encoded as `const`
maps (NOT inline conditionals), so a future code-gen can replace them.

Role-to-permission mapping (mirrors `ROLE_PERMISSIONS` in
`permissions.py:263-322` + new `MANAGE_DATASET_ADMIN` from AD-1B):
- `unauthenticated` + null + public: `_GUEST_PUBLIC_PERMS`
- `unauthenticated` + null + restricted: `_GUEST_RESTRICTED_BASE_PERMS` + toggle overlay
- `authenticated_non_member` + null + public: `_GUEST_PUBLIC_PERMS` + authenticated extras (VOTE, COMMENT, etc.)
- `pending_invitation` + null + *: `_EMPTY_PERMS` (must accept first)
- `loading` + null + *: `_EMPTY_PERMS` (safe default)
- `authenticated_member` + viewer: `_VIEWER_PERMS` (permissions.py:263-271)
- `authenticated_member` + member: `_MEMBER_PERMS` (permissions.py:273-292) — NO MANAGE_DATASET_ADMIN
- `authenticated_member` + admin: `_ADMIN_PERMS` (permissions.py:294-303) + MANAGE_DATASET_ADMIN
- `authenticated_member` + owner: `_OWNER_PERMS` (permissions.py:305-313) + MANAGE_DATASET_ADMIN

2B.2 Create `apps/web/src/lib/utils/permissions.test.ts` — matrix-complete generation (1.5h, per E.1)

**Codex Rev.1 fix (改善 1)**: success criterion is matrix completeness, not
case count. Tests are generated parametrically:

```typescript
const ROLES: (ComputedRole | 'unauthenticated' | 'authenticated_non_member' | 'pending_invitation' | 'loading')[] = [...];
const PERMISSIONS: ProjectPermission[] = [...]; // emitted from FRONTEND_PROJECT_PERMISSIONS (Rev.5)
const VISIBILITIES: ('public' | 'restricted')[] = ['public', 'restricted'];
const TOGGLE_STATES = [{ all_true: true }, { all_false: false }, ...realistic_combos];

// Generate test cases: every (auth/role) × permission × visibility × toggle
describe.each(generateAllCases())('can(%s, %s)', (permission, ctx, expected) => {
  test(`returns ${expected}`, () => {
    expect(can(permission, ctx)).toBe(expected);
  });
});
```

Expected truth table is **derived from the backend matrix** (loaded from a
JSON file generated by a backend script in 2B.0). This guarantees frontend
matches backend without manual transcription.

2B.0 Backend matrix export script + CI drift gate (1h, expanded — Rev.3)

New script: `scripts/export_role_permissions_to_json.py`
- Reads `permissions.py::ROLE_PERMISSIONS` + visibility/toggle overlays
  + `ENDPOINT_BACKED_PERMISSIONS` / `COMPUTED_ONLY_PERMISSIONS` /
  `USER_SCOPE_PERMISSIONS` / `SUPERUSER_ONLY_PERMISSIONS` (AD-8) +
  the full list of `Permission` enum values.
- Emits `apps/web/src/lib/utils/__fixtures__/role_permissions.json`.
- The JSON also serves as the canonical source for the
  `ProjectPermission` TypeScript union via a generation step in CI.

**Rev.3 fix (Codex Rev.2 Rev2-3): CI drift gate**

The JSON fixture alone does NOT prevent drift if it is hand-edited or
left stale. CI MUST enforce regenerate + diff:

New CI job `permissions-fixture-drift`:
```yaml
- name: Regenerate frontend permissions fixture
  run: uv run python scripts/export_role_permissions_to_json.py --check
```

The `--check` flag:
1. Generates the fixture to a temp file.
2. Diffs against the committed
   `apps/web/src/lib/utils/__fixtures__/role_permissions.json`.
3. If different, prints the diff and exits with code 1.

Locally, developers run `uv run python scripts/export_role_permissions_to_json.py`
(without `--check`) to regenerate.

Additionally, a vitest test verifies the imported JSON has all enum keys
present (a missing key would crash matrix generation but might be missed
without explicit assertion).

This closes the Codex Rev.2 Rev2-3 gap: fixture cannot silently drift.

2B.3 Replace scattered role checks (1h)
Update `settings/+page.svelte`, `members/+page.svelte`,
`datasets/[datasetId]/+page.svelte` with `can()` calls and the
`contextFromProject()` helper.

Completion gate (Phase 2B):
- Gate 1: `npm run check` passes
- Gate 2: `npm run test` — matrix-complete tests pass (estimated 500+
  generated cases; the metric is "all combinations covered", not the count)
- No `members.find()` for role derivation (grep clean)
- `role_permissions.json` fixture imported by tests matches backend

### Phase 3: ACTIONS x Canonical Matrix Coherence Contract Test (3h, was 2h)

Prerequisite: Phase 2A complete.

3.1 Create `apps/api/tests/contract/test_actions_coherence.py` (~400 LOC)

9 test classes (see AD-4 for details):
1. TestEveryActionPermissionInMatrix
2. **TestAllEndpointBackedPermissionsCoveredByActions** ← Phase 2A completeness driver (Rev.3 — narrowed via AD-8)
3. **TestSuperuserOnlyActionsConsistent** ← Rev.3 renamed (was "OnAllowlist")
4. TestRolePermissionsSubsetOfEnum
5. TestNoDuplicateActionNames
6. TestMutatingActionsHaveMutatingHttpMethod  ← NEW semantic gate
7. TestReadActionsHaveReadHttpMethod  ← NEW semantic gate
8. TestSuperuserAndPlatformScopeMutuallyExclusive  ← Codex Rev.1 重要 3
9. TestPathPatternMatchesPermissionCategory  ← NEW semantic gate (interim per Codex Rev.2 Q13)

3.2 Create `apps/api/tests/contract/test_allowlist_metadata.py` (~80 LOC, per AD-5)
- Validates `ALLOWLIST` entries: reason ≥20 chars, owner non-empty.
- AST scan: `superuser_only` category routes have `CurrentSuperuser`.
- AST scan: `token_auth_only` category routes have invitation-token dep.
- Expiry check.

Completion gate (Phase 3):
- Gate 2: `pytest apps/api/tests/contract/test_actions_coherence.py` — 0 failures
- Gate 2: `pytest apps/api/tests/contract/test_allowlist_metadata.py` — 0 failures

### Phase 4: Vitest Matrix + Playwright Smoke (4h, was 3h)

Prerequisite: Phase 2B complete. Vitest (4.1) and Playwright (4.2) can run in parallel.

4.1 Complete vitest parametric matrix (1h)
Already implemented in 2B.2 as matrix-complete generation. 4.1 verifies:
- Generated case count >= (5 authState × 5 roles × |FRONTEND_PROJECT_PERMISSIONS| × 2
  visibility × 3 toggle states) — pruned to legal combinations (~500+ cases).
- Spot-check edge cases (asserted explicitly, not derived):
  - `can('vote', { authState: 'unauthenticated', role: null, visibility: 'public' })` → `true`
  - `can('vote', { authState: 'pending_invitation', role: null, visibility: 'public' })` → `false`
  - `can('delete_project', { authState: 'authenticated_member', role: 'owner', visibility: 'restricted' })` → `true`
  - `can('delete_project', { authState: 'authenticated_member', role: 'admin', visibility: 'restricted' })` → `false`
  - `can('manage_dataset_admin', { authState: 'authenticated_member', role: 'member', visibility: '*' })` → `false` (AD-1B)
  - Toggle interaction: `can('view_media', { ..., visibility: 'restricted', restrictedConfig: { allow_media_playback: true, ... } })` → `true`

4.2 Playwright smoke matrix (3h, was 2h)
New file `apps/web/tests/permissions/smoke-matrix.test.ts`

**Codex Rev.1 fix (改善 2)**: 25 scenarios = 20 role×screen + 5 boundary.

Role × screen scenarios (20):
1. `/projects/{id}` (project-detail)
2. `/projects/{id}/members`
3. `/projects/{id}/trusted`
4. `/projects/{id}/settings`
5. `/projects/{id}/datasets`

Permission expectations per role (Rev.3 — matches § 4A vocabulary glossary):

| Screen | Owner | Admin | Member | Viewer |
|--------|-------|-------|--------|--------|
| project-detail | Delete button visible | Edit button visible | No admin buttons | View only |
| members | Full CRUD | Full CRUD | Redirect to /projects/{id} | Redirect |
| trusted | Full CRUD | Read-only | Redirect | Redirect |
| settings | Edit enabled | Edit enabled | Redirect | Redirect |
| datasets list | "+ New Dataset" visible | "+ New Dataset" visible | NO "+ New Dataset" button | NO "+ New Dataset" button |
| dataset detail | "Edit dataset" + "Delete dataset" + "Generate clips" + "Add annotation" all visible | Same as owner | NO "Edit/Delete dataset"; YES "Generate clips" + "Add annotation" (per § 4A) | View-only; no mutate buttons |

The Rev.3 split of the datasets row resolves Codex Rev.2 P0-Rev2-1
(the Rev.2 row "View only (NO create per AD-1B)" conflated dataset-resource
permissions with dataset-content permissions).

Boundary scenarios (5 — NEW per Codex Rev.1):
- **B-1 Direct URL navigation**: viewer types `/projects/{id}/settings` directly → redirected to project detail with toast.
- **B-2 API 403 mid-session**: admin clicks "Update settings" → server returns 403 (simulated via mock) → UI displays toast "Your permissions have changed", project query invalidates, settings form disables.
- **B-3 Demotion reload**: admin user logs in, gets demoted to viewer (via separate API call), user refreshes page → settings link no longer visible.
- **B-4 Pending invitation**: user with `authState: 'pending_invitation'` (token in URL but not yet accepted) lands on `/projects/{id}` → CTA shows "Accept invitation" instead of project content.
- **B-5 Unknown role fallback**: project response has unexpected `current_user_role: 'guest_legacy'` (simulated via mock) → UI falls back to most restrictive view, no JS error.

Test accounts: `test@echoroo.app` (owner), create 3 additional via globalSetup.

Completion gate (Phase 4):
- Gate 2: `npm run test` — vitest matrix tests pass (matrix-complete metric)
- Gate 3: Playwright smoke — 25/25 scenarios pass, 0 console errors
  - 20 role×screen scenarios
  - 5 boundary scenarios (B-1 through B-5)

## 6. File Change Map

### Files to Create (Rev.4 — full list)

| File | Phase | Purpose | Estimated LOC |
|------|-------|---------|--------------|
| `apps/api/echoroo/core/endpoint_allowlist.py` | 2A.1 | Structured ALLOWLIST module (AD-5) | ~250 |
| `scripts/export_role_permissions_to_json.py` | 2B.0 | Backend matrix → JSON fixture exporter + `--check` mode (AD-8 + Rev.3) | ~200 |
| `apps/web/src/lib/utils/__fixtures__/role_permissions.json` | 2B.0 | Generated fixture; commit and CI-diff-gated | ~varies |
| `apps/web/src/lib/utils/permissions.ts` | 2B.1 | `can()` utility + `buildProjectContext()` (AD-2) | ~200 |
| `apps/web/src/lib/stores/permissionContext.ts` | 2B.1 | `usePermissionContext()` Svelte store helper (AD-2 / Q16) | ~80 |
| `apps/web/src/lib/api/queryClient.ts` (or extend existing) | 1.5 | `QueryCache.onError` / `MutationCache.onError` 403 handler (AD-3 Rev.4) | ~120 |
| `apps/web/src/lib/utils/permissions.test.ts` | 2B.2, 4.1 | vitest matrix-complete tests | ~500 |
| `apps/web/src/lib/api/client.permissions.test.ts` | 1.5 | 403 handler + projectId resolution unit tests | ~150 |
| `apps/web/src/lib/api/__tests__/meta-completeness.test.ts` | 1.5 | AST + runtime lint: every project-scoped query/mutation has `meta: { projectId }`. Rev.5: renamed to `*.test.ts` pattern so vitest picks it up. Scans `src/lib/api/**/*.ts` AND `src/routes/**/*.svelte`. Combined with `projectQueryOptions(projectId, ...)` / `projectMutationOptions(projectId, ...)` typed helpers (Codex Rev.4 Q23) — pages SHOULD use the helpers; direct `createQuery` with project-scoped keys is permitted only with explicit `meta.projectId` and the lint catches misses. | ~120 |
| `apps/web/src/lib/api/projectQueryOptions.ts` | 1.5 | Typed helper enforcing `meta: { projectId }` at type level for project-scoped queries/mutations | ~60 |
| `apps/api/tests/contract/test_actions_coherence.py` | 3.1 | 9-class ACTIONS coherence | ~400 |
| `apps/api/tests/contract/test_allowlist_metadata.py` | 3.2 | AllowlistEntry metadata lint (AD-5) | ~120 |
| `apps/web/tests/permissions/smoke-matrix.test.ts` | 4.2 | Playwright 20 role×screen + 5 boundary scenarios | ~350 |
| `.github/workflows/permissions-fixture-drift.yml` (or job in existing CI) | 2B.0 | CI job running export script in `--check` mode (Rev.3) | ~30 |

### Files to Modify
| File | Phase | Change summary |
|------|-------|---------------|
| apps/api/echoroo/core/actions.py | 2A | +~52 Action registrations |
| apps/api/tests/contract/test_endpoint_coverage.py | 2A | Skip removal + ALLOWLIST_PATHS |
| apps/api/echoroo/api/v1/datasets.py | 2A | gate_action replacement (12 endpoints) |
| apps/api/echoroo/api/v1/clips.py | 2A | gate_action replacement (8 endpoints) |
| apps/api/echoroo/api/v1/annotation_projects.py | 2A | gate_action replacement |
| apps/api/echoroo/api/v1/annotation_tasks.py | 2A | gate_action replacement |
| apps/api/echoroo/api/v1/annotations.py | 2A | gate_action replacement |
| apps/api/echoroo/api/v1/confirmed_regions.py | 2A | gate_action replacement |
| apps/api/echoroo/api/v1/detection_runs.py | 2A | gate_action replacement |
| apps/api/echoroo/api/v1/xeno_canto.py | 2A | gate_action replacement |
| apps/api/echoroo/api/v1/search/ submodules | 2A | Action registration + optional gate |
| apps/api/echoroo/api/v1/evaluation.py | 2A | gate_action replacement |
| apps/web/src/routes/(app)/projects/[id]/settings/+page.svelte | 1 | Remove members.find() |
| apps/web/src/routes/(app)/projects/[id]/members/+page.svelte | 1 | Remove members.find() |
| apps/web/src/routes/(app)/projects/[id]/datasets/[datasetId]/+page.svelte | 1, 2B | Add role guard |

## 7. Data Flow

(Rev.4 fix — Codex Rev.3 P0-2: dataset DELETE/UPDATE flows MUST gate on
`MANAGE_DATASET_ADMIN`, not `MANAGE_DATASET`, per § 4A glossary rule 3.)

### Backend: Request Authorization with New Actions

  HTTP Request (DELETE /api/v1/projects/{id}/datasets/{dataset_id})
      |
      v
  AuthRouterMiddleware (resolves user from JWT/session/API key)
      |
      v
  TwoFactorEnforcementMiddleware (2FA check)
      |
      v
  dataset.delete() handler
      |
      +-- gate_action(action=DATASET_DELETE_ACTION, project_id, current_user, request, db)
      |       |
      |       +-- load_project_or_404(db, project_id)              [1 SELECT]
      |       +-- _resolve_project_member_role(db, project_id, user_id)  [1 SELECT]
      |       +-- _ScopedPrincipal(current_user, role)
      |       +-- is_allowed(DATASET_DELETE_ACTION, user=principal, project)
      |               |
      |               +-- resolve_role(user, project)             [pure]
      |               +-- normalize_role(raw_role, project)       [pure]
      |               +-- compute_effective_permissions(...)      [pure]
      |               +-- MANAGE_DATASET_ADMIN in effective -> allowed (admin/owner only)
      |               +-- member role -> NOT allowed (per AD-1B Option A)
      |
      +-- service.delete_dataset(project_id=project.id, ...)

Contrast: a clip mutate request (POST /api/v1/projects/{id}/datasets/{dataset_id}/clips)
gates on `CLIP_CREATE_ACTION` with `required_permission=MANAGE_DATASET`, which
the member role HAS — illustrating the § 4A distinction.

### Frontend: Permission-Aware Rendering

  SvelteKit page load
      |
      v
  TanStack Query: createQuery({
        queryKey: ['project', projectId],
        queryFn: () => projectsApi.get(projectId),
        staleTime: 30_000,
        refetchOnWindowFocus: true,
        meta: { projectId },                              // AD-3 Rev.4
      })
      |           <- returns Project { current_user_role: 'admin', ... }
      |
      v
  $derived: ctx = usePermissionContext({ projectQuery, routeParams })
      |           <- builds the discriminated ProjectContext
      |
      v
  $derived: canDeleteDataset = can('manage_dataset_admin', ctx)  // dataset RESOURCE
              canAddClip       = can('manage_dataset', ctx)        // dataset CONTENT
      |           <- pure functions, no network request
      |
      v
  Svelte template:
      {#if canDeleteDataset} <button>Delete Dataset</button> {/if}
      {#if canAddClip}       <button>+ Add Clip</button>     {/if}

## 8. Risks and Mitigation

### Risk 1: MANAGE_DATASET vs is_project_admin() behavioral divergence (RESOLVED in Rev.2)

**Codex Rev.1 P0-1 fix**: This risk is structurally resolved in Rev.2 by
AD-1B Option A. Phase 2A is now strictly behavior-preserving:
- `MANAGE_DATASET_ADMIN` is introduced (admin+owner only).
- Member retains current `MANAGE_DATASET` for non-destructive operations
  (clip mutate, annotation mutate).
- No member-visible UI changes.

Residual risk: AD-1B Option A approval gate. If product/user picks Option B
(spec-as-truth) or Option C (escalate), Phase 2A is replanned. This plan
assumes Option A.

### Risk 2: is_superuser_only misconfiguration (MEDIUM)

Problem: New Action with is_superuser_only=True but required_permission not on
SUPERUSER_PROJECT_SCOPE_ALLOWLIST -> required_permission is unused.

Detection: Phase 3 coherence test TestSuperuserOnlyActionsOnAllowlist hard-fails.

Mitigation: Do not merge Phase 2A without Phase 3 passing.

### Risk 3: Frontend state invalidation race on demotion (RECLASSIFIED — was LOW, now MEDIUM with mandatory mitigation)

**Codex Rev.1 重要 2 fix**: Reclassified per AD-3. Backend always enforces
correctly; the risk is UX-quality, not security. Rev.2 makes the mitigation
mandatory rather than optional.

Mandatory mitigation (Phase 1.5):
1. `staleTime: 30_000` + `refetchOnWindowFocus: true` for `['project', projectId]`.
2. Global 403 error handler invalidates `['project', projectId]` + refetches +
   shows toast "Your permissions have changed".
3. Phase 4.2 boundary scenarios B-2 and B-3 verify the mitigation end-to-end.

Out-of-scope for launch (post-launch): `BroadcastChannel` for cross-tab sync.

### Risk 4: Playwright test flakiness (LOW)

Problem: Smoke matrix requires 4 test accounts with specific roles.

Mitigation:
1. Use test@echoroo.app for owner (memory/test-accounts.md)
2. Create dedicated test project in playwright.config.ts globalSetup
3. Create other 3 test accounts programmatically in globalSetup
4. Verify accounts exist before each test via beforeAll

### Risk 5: search/ SearchGate and gate_action double guard (MEDIUM)

Problem: Adding gate_action to search endpoints may duplicate permission check
already in SearchGate. 2 extra DB SELECTs per search request.

Mitigation: Review search/ submodules before Phase 2A. If SearchGate calls
is_allowed with project scope, outer gate_action is redundant but harmless.
Add comment explaining the rationale.

### Risk 6: Frontend can() drift from backend ROLE_PERMISSIONS (HIGH)

Problem: can() is a manual re-implementation. Backend matrix changes may not
be reflected in frontend.

Detection: vitest parametric matrix (Phase 4.1) catches divergence.

Mitigation:
1. Comment in permissions.ts: "MUST stay in sync with ROLE_PERMISSIONS in
   apps/api/echoroo/core/permissions.py"
2. Cross-reference each test case with backend _VIEWER_PERMS/_MEMBER_PERMS constants
3. Future: Generate permissions.ts from backend enum (out of scope for launch)

## 9. Rollback Plan

Each phase maps to an independent PR:
- PR-007-ph0: Branch setup (always safe)
- PR-007-ph1: State consolidation (revert if pages break)
- PR-007-ph2a: ACTIONS registration + endpoint coverage gate (revert if CI regresses)
- PR-007-ph2b: Frontend can() (revert if rendering breaks)
- PR-007-ph3: Coherence test (test-only, always safe)
- PR-007-ph4: vitest + Playwright (test-only, always safe)

Skip re-enablement rollback: If test_endpoint_coverage.py hard-fail surfaces
unexpected failures after Phase 2A, add specific routes back to ALLOWLIST_PATHS
rather than re-adding @pytest.mark.skip.

## 10. Test Strategy

### Backend Testing

Layer 1 - Unit (pure function): test_permissions.py (842 lines) covers
is_allowed exhaustively. After Phase 2A: all matrix cells
(`len(Permission)` × 6 principals × 2 visibility — exact count varies as
permissions are added in Rev.4-5; the test is parametric over `Permission`
enum membership, not a hard-coded count) pass without xfail.

Layer 2 - Contract (endpoint coverage): test_endpoint_coverage.py verifies every
actionable route has an ACTIONS entry. Hard-fail CI gate.

Layer 3 - Contract (coherence): test_actions_coherence.py verifies structural
correctness of the catalog. 9 test classes (per AD-4 Rev.3), ~150
parametric cases including semantic gates (HTTP method, path pattern,
superuser/platform-scope exclusion).

Layer 4 - Integration (HTTP): Existing test_permissions.py HTTP-level tests
(ViewerPermissions, MemberPermissions, AdminPermissions, OwnerPermissions) exercise
new routes via updated Actions. Add 1-2 integration cases per new Action category.

Layer 5 - Security regression: Existing 641 security tests in tests/security/
must continue to pass throughout.

### Frontend Testing

Layer 1 - Unit (can() function): permissions.test.ts with >=300 parametric cases.
Covers every Permission x 6 ComputedRole x 2 visibility. Pure synchronous, no DOM.

Layer 2 - Smoke E2E (Playwright): smoke-matrix.test.ts with 20 role x screen
scenarios. Verifies rendered UI matches expected permission state. Gate 3 requirement.

Mutation testing (post-launch): Run mutmut on permissions.ts in future session.

## 11. Timeline (Rev.3)

**Codex Rev.2 fix (タイムライン Q15)**: Rev.2 24h/14h estimate was still
optimistic. Rev.3 adds (a) § 4A vocabulary glossary work + Playwright row
split, (b) AD-3 projectId resolution convention + meta tagging across all
project-scoped APIs, (c) JSON drift CI gate, (d) AD-8 permission category
classification + AD-5 metadata enhancements, (e) permissionContext store
helper, (f) Phase 17 A-5 audit prereq, (g) spec amendment work (Prereq-2).

Revised estimate: **~32-40h single / ~20-24h parallel** (3.5-5 days / 2.5-3 days).
Codex Rev.2 noted Phase 2A.6 (10 routers gate_action) at 3h and Playwright 25
scenarios at 3h were both too aggressive.

**Schedule (single dev, conservative)**:

| Day | Hours | Work |
|-----|-------|------|
| Pre-Day 0 | 1h | Prereq-1 (Option A approval), Prereq-2 (spec amendment PR draft), Prereq-3 (Phase 17 A-5 audit) |
| Day 1 | 8h | Phase 0 (0.5h) + Phase 1 state consolidation (3h) + Phase 1.5 demotion mitigation with projectId convention (2h) + start Phase 2A.0 MANAGE_DATASET_ADMIN + AD-8 categorization (1.5h) + buffer (1h) |
| Day 2 | 8h | Phase 2A.1 structured ALLOWLIST (2h) + 2A.2-2A.5 Action registration including admin (3.5h) + 2A.6 gate_action wiring start (2.5h) |
| Day 3 | 8h | Phase 2A.6 gate_action wiring complete + mypy/ruff (4h) + 2A.7 hard-fail enable + debug (2h) + Phase 2B.0 backend matrix export + CI drift gate (2h) |
| Day 4 | 8h | Phase 2B.1 can() utility + permissionContext store (3h) + 2B.2 matrix-complete vitest (3h) + 2B.3 scatter replacement (2h) |
| Day 5 | 6-8h | Phase 3.1 coherence test 9 classes (3h) + 3.2 allowlist metadata test (1h) + Phase 4.2 Playwright 25 scenarios (3-4h) + final gates (1h) |

**Parallel execution (backend + frontend developers in two-tracks)**:
- Track A (backend): Phase 2A.0-2A.7 + 3.1 + 3.2
- Track B (frontend): Phase 1 + 1.5 + 2B.0-2B.3 + 4.2
- Shared dependency: Phase 2B.0 (matrix export) requires AD-8 categorization
  done in backend first; sync point at end of Day 1 (single) / Day 2 morning (parallel).

Parallel total: **~20-24h** (2.5-3 days), assuming both tracks can sustain
~8h/day without context switching.

Single dev total: **~32-40h** (3.5-5 days).

Codex Rev.2 noted specifically:
- Phase 2A.6 budgeted at 3h is unrealistic for 10 routers (Rev.2 estimate).
  Rev.3 raises to 6.5h split across Day 2/3.
- Playwright 25 scenarios + globalSetup + 4 test accounts: Rev.3 budgets
  3-4h on Day 5 (was 3h in Rev.2).

## 12. Definition of Done (Rev.2)

Phase 1 Complete:
- [ ] `members.find()` for role derivation removed from all pages
- [ ] `npm run check` passes
- [ ] Settings page loads without `GET /members` network call
- [ ] No new console errors
- [ ] Project query has `staleTime: 30_000` + `refetchOnWindowFocus: true` (AD-3)
- [ ] Global 403 error handler invalidates `['project', projectId]` + refetches + toasts (AD-3)

Phase 2A Complete:
- [ ] `MANAGE_DATASET_ADMIN` permission added to `Permission` enum + `_ADMIN_PERMS` / `_OWNER_PERMS` (AD-1B Option A)
- [ ] `actions.py` has >=114 registered Actions (including admin endpoints per AD-6)
- [ ] `endpoint_allowlist.py` module created with `ALLOWLIST` of structured entries (AD-5)
- [ ] `test_endpoint_coverage.py` runs without `@pytest.mark.skip`, 0 failures
- [ ] `test_allowlist_metadata.py` passes (AD-5)
- [ ] `test_permissions.py` has 0 xfail entries
- [ ] `uv run mypy .` passes
- [ ] `uv run ruff check .` passes
- [ ] `uv run pytest` — all 641+ security tests pass
- [ ] No member role gains destructive dataset/annotation_project/confirmed_region/detection_run permissions (per AD-1B Option A; verified via security tests)

Phase 2B Complete:
- [ ] `apps/web/src/lib/utils/permissions.ts` created with `can()` + `ProjectContext` (with `authState` discriminator per AD-2)
- [ ] `apps/web/src/lib/utils/contextFromProject()` helper created
- [ ] `scripts/export_role_permissions_to_json.py` generates `role_permissions.json` fixture
- [ ] `npm run check` passes
- [ ] `npm run test` — matrix-complete vitest tests pass (every legal `authState × role × permission × visibility × toggle` combination)
- [ ] No `members.find()` for role derivation (grep clean)

Phase 3 Complete:
- [ ] `test_actions_coherence.py` created with 9 test classes (AD-4), 0 failures
- [ ] Class 6/7 (HTTP method semantic gates) pass
- [ ] Class 8 (superuser/platform-scope mutual exclusion) passes
- [ ] Class 9 (path-pattern → permission category) passes
- [ ] `test_allowlist_metadata.py` 0 failures (AD-5)

Phase 4 Complete:
- [ ] Vitest matrix tests pass with matrix-complete coverage (every legal combination)
- [ ] Edge case spot checks pass (vote/null role/public, manage_dataset_admin/member/restricted, etc.)
- [ ] Playwright role×screen smoke: 20/20 scenarios pass
- [ ] Playwright boundary scenarios: B-1 through B-5 all pass
- [ ] 0 console errors across all 25 Playwright scenarios

Final Launch Gate:
- [ ] `uv run pytest` — 0 failures (including new tests)
- [ ] `npm run test` — 0 failures
- [ ] `npm run check` — 0 errors
- [ ] `uv run mypy .` — 0 errors
- [ ] `uv run ruff check .` — 0 warnings
- [ ] Playwright Gate 3 verified at http://localhost:3000
- [ ] CI pipeline green on `007-permission-test-coverage` branch PR
- [ ] AD-1B Option A approved (recorded in PR description with product/user acknowledgement)

## 13. Codex Review Checklist (Rev.2 — Update)

### Rev.1 questions — resolved in Rev.2

| Q | Rev.1 question (summary) | Rev.2 resolution |
|---|---------------------------|------------------|
| Q1 | MANAGE_DATASET for member? | **Resolved by AD-1B Option A**: introduce `MANAGE_DATASET_ADMIN`; member retains current non-destructive access. Phase 2A is now behavior-preserving. |
| Q2 | can() null-role guest/non-member disambiguation | **Resolved by AD-2**: `ProjectContext` now carries explicit `authState` discriminator. `role: null` alone never reaches `can()`. |
| Q3 | search/ SearchGate double guard | **Open** (still). Plan accepts double guard as harmless. Documented in Risk 5. Codex Rev.2 may push for `SearchGate` to be the sole enforcement. |
| Q4 | ANNOTATE permission for annotation_task.complete | **Behavior-preserving**: matches current `check_project_access()` (member+). No change. |
| Q5 | Phase 1 → Phase 2B dependency | **Captured**: Phase 1 must merge before Phase 2B scatter replacement. Timeline shows the lag. |
| Q6 | DATASET_DATETIME_AUTODETECT `is_mutating` | **Resolved**: set to `is_mutating=False` (it's a POST that reads). Class 6 coherence test will fail if mis-flagged. |
| Q7 | Risk 1 severity for launch | **Resolved by AD-1B Option A**: no member-visible behavior change. Pre-launch status remains relevant for B/C options only. |
| Q8 | Frontend drift structural prevention | **Resolved by 2B.0**: `scripts/export_role_permissions_to_json.py` generates fixture; vitest matrix imports it. No manual transcription. |
| Q9 | evaluation.py project access via AnnotationSet FK | **Open** (still). Implementation detail — Phase 2A.6 verifies `gate_action` resolves `project_id` correctly. |
| Q10 | xeno_canto.stream `StreamingResponse` compatibility | **Documented in AD-6**: connection-time auth only; mid-stream revoke marked `xfail` with reference to spec/006 Phase 17 A-5. |

### Rev.2 new questions (for Codex Rev.2 review)

Q11. **AD-1B Option A binding scope**: Phase 2A introduces
`MANAGE_DATASET_ADMIN` and reassigns ~8 endpoint categories to it. This is a
matrix change (adding a Permission enum value, updating `_ADMIN_PERMS` /
`_OWNER_PERMS`) — does this require a spec amendment (spec/006 Rev.4 or new
spec 008)? Or is it within plan-level discretion since it's
**behavior-preserving**?

Q12. **AD-5 allowlist metadata enforcement**: Does the proposed
`AllowlistEntry` schema (path + methods + category + reason + owner +
spec_ref + expiry) cover the audit needs Codex Rev.1 raised? Is `expiry`
sufficient as a freshness signal, or should we add a `last_reviewed_at`
field too?

Q13. **AD-4 coherence test class 9 (path-pattern → permission category)**:
The regex table approach is brittle if route paths change. Is this a worth
trade-off vs the maintenance cost? Alternative: encode the expected
permission as a `route.tags` value at the FastAPI router level and assert
the tag matches the registered Action.

Q14. **AD-3 demotion-race mitigation completeness**: Rev.2 mandates 403
invalidation + 30s staleTime + window-focus refetch. Is this sufficient for
launch, or should we also implement permission claim short-TTL in JWT/session
cookies (e.g. permissions baked into JWT with 5-minute expiry)?

Q15. **Rev.2 timeline realism**: 24h single / 14h parallel covers the
expanded scope. Is this still optimistic? Specifically, Phase 2A.6 (wire
`gate_action` in 10 routers) is budgeted at 3h — based on the spec/006
Phase 2 patterns (gate_action introduction took ~2 days for 5 routers), is
this realistic?

Q16. **AD-2 authState derivation**: Where is `authState` computed in the
frontend? Proposed: combine `auth.store.ts::isAuthenticated` +
`projectQuery.isLoading` + `project.current_user_role` +
`pendingInvitationToken` from URL. Should `authState` itself be a derived
`$state.derived` in a new `permissionContext` store?

Q17. **Streaming endpoint mid-revoke (AD-6)**: Documenting as `xfail` is
pragmatic. Is the xfail acceptable as a launch-blocker waiver, or does
Codex think this should be solved before launch given that Phase 17 A-5
already partially addressed the streaming permission re-check?

### Priority-tagged review request for Codex Rev.2 — RESOLVED

(Resolved in Rev.3 by the changes summarized below.)

### Rev.2 → Rev.3 resolution table

| Codex Rev.2 finding | Rev.3 resolution |
|---------------------|------------------|
| **P0-Rev2-1**: MANAGE_DATASET vs MANAGE_DATASET_ADMIN ambiguity | New § 4A Permission Vocabulary Glossary defines both unambiguously. AD-2 boundary table split into 2 columns. Phase 1.4 splits `canManageDataset` into `canEditDatasetResource` (manage_dataset_admin) + `canAddDatasetContent` (manage_dataset). Playwright datasets row split into "datasets list" + "dataset detail" with explicit per-role expectations matching § 4A. |
| **Rev2-1**: ProjectContext discriminated union allows invalid combination | AD-2 union tightened: `role: non-null` branch is `authState: 'authenticated_member'` only. Invalid combinations now fail TypeScript type-check. |
| **Rev2-2**: 403 invalidation lacks projectId resolution | AD-3 adds 3-tier projectId resolution: (1) TanStack Query `meta.projectId`, (2) URL pattern regex, (3) no-op + warning. Mutation AND query 403 both invalidate. New unit test `client.permissions.test.ts`. |
| **Rev2-3**: JSON export does not prevent drift | Phase 2B.0 expanded to include `scripts/export_role_permissions_to_json.py --check` as a CI job that diffs against committed fixture and fails on drift. |
| **Rev2-4**: AD-4 class 3 naming conflicts with AD-6 admin-as-Action approach | Class 3 renamed to `TestSuperuserOnlyActionsConsistent`. AD-6 explicitly states admin endpoints are Action-registered (not in ALLOWLIST). `AllowlistCategory.SUPERUSER_ONLY` reserved but unused. |
| **Rev2-5**: `TestAllPermissionsCoveredByActions` too strong | New AD-8 introduces 4-way permission classification (`ENDPOINT_BACKED_PERMISSIONS`, `COMPUTED_ONLY_PERMISSIONS`, `USER_SCOPE_PERMISSIONS`, `SUPERUSER_ONLY_PERMISSIONS`). Class 2 narrowed to `ENDPOINT_BACKED_PERMISSIONS` only. |
| **Q11**: spec amendment required | Prereq-2 added: spec/006 Rev.4 or spec/008 must be drafted before implementation. |
| **Q12**: allowlist needs last_reviewed_at | AD-5 entry extended with `last_reviewed_at`, `review_interval_days` (default 180), `project_scope_allowed: bool = False`. Project-scoped paths cannot silently land in allowlist. |
| **Q13**: class 9 regex brittle | Marked **interim** with explicit migration target to per-Action `resource/operation/scope/category` metadata post-launch. |
| **Q14**: demotion mitigation completeness | Confirmed sufficient (backend gate_action queries DB membership per request); JWT TTL not required. Multi-tab waiver explicit. |
| **Q15**: timeline 24h still optimistic | Revised to 32-40h single / 20-24h parallel (3.5-5 days / 2.5-3 days). Phase 2A.6 raised from 3h → 6.5h. |
| **Q16**: authState centralization | AD-2 adds `buildProjectContext()` pure function + `usePermissionContext()` Svelte store helper. Pages no longer re-implement authState calculation. |
| **Q17**: streaming xfail | Strengthened to `strict=True` + tracking ID. Prereq-3 audits Phase 17 A-5 to convert covered scenarios to passing tests rather than xfail. |

### Rev.3 new questions (for Codex Rev.3 review)

Q18. **§ 4A vocabulary glossary completeness**: Does the glossary cover
every permission consumers will encounter? Are there cases where a single
UI element legitimately needs BOTH `manage_dataset` AND `manage_dataset_admin`
to be visible (e.g. a combined toolbar)?

Q19. **AD-8 category boundaries**: Is `VIEW_PRECISE_LOCATION` correctly
classified as `COMPUTED_ONLY_PERMISSIONS`? The response filter is the only
enforcement point, but there is also a per-request decision in
`apply_response_filter`. Does that count as "endpoint-backed"?

Q20. **projectId URL-pattern fallback robustness**: The AD-3 regex
`/projects\/([0-9a-f-]+)/i` matches both `/api/v1/projects/{id}` and
`/api/v1/web-api/projects/{id}`. Are there URL shapes (e.g.
`/projects/list?filter=...` or `/api/v1/projects/{id}/datasets/{id}`) where
the regex picks the wrong ID? Should we restrict to a stricter pattern?

Q21. **CI drift gate failure mode**: When `permissions-fixture-drift`
fails, the developer runs the export script locally and commits the result.
Is this enough, or should the CI job auto-commit the regenerated fixture
on PR branches (with a tagged commit) to reduce manual back-and-forth?

Q22. **Prereq-2 spec amendment scope**: Codex Rev.2 said "spec/006 Rev.4
or spec/008". Which is preferred? spec/006 is closed (Phase 16 main-merged);
amending might require a Rev.4 process. spec/008 is cleaner but separates
the vocabulary from its origin. Recommendation requested.

### Rev.3 → Rev.4 resolution table

| Codex Rev.3 finding | Rev.4 resolution |
|---------------------|------------------|
| **P0-1**: AuthState type missing `authenticated_member` | AD-2 `AuthState` union extended; ProjectContext branches now satisfiable. |
| **P0-2**: §7 Data Flow uses stale `MANAGE_DATASET` for dataset DELETE | §7 fully rewritten: DELETE flow gates on `DATASET_DELETE_ACTION` + `MANAGE_DATASET_ADMIN`; frontend example splits `canDeleteDataset` (manage_dataset_admin) and `canAddClip` (manage_dataset). |
| **重要-1**: AD-5 review-date fail condition reversed | Inverted: `last_reviewed_at + review_interval_days < today` fails CI. |
| **重要-2**: 403 handler `meta.projectId` implementation point ambiguous | Pinned to `QueryCache.onError` + `MutationCache.onError` reading `query.meta` and `mutation.options.meta` respectively. Code sketch included. URL fallback regex tightened to strict UUID v4 (Q20). |
| **重要-3**: xeno_canto search in both allowlist and Action | Removed `XENO_CANTO_SEARCH_ACTION`. The endpoint is non-project-scoped and lives in ALLOWLIST `external_proxy` only. |
| **重要-4**: AD-8 / frontend `ProjectPermission` scope mismatch | Frontend union explicitly excludes `SEARCH_CROSS_PROJECT`, `MANAGE_API_KEY`, `MANAGE_2FA`, `MANAGE_SITE`. CI gate emits the union from backend `ENDPOINT_BACKED_PERMISSIONS - {SEARCH_CROSS_PROJECT}`. |
| **重要-5**: Phase 3 / Test Strategy / File Map Rev.2 残骸 | Phase 3.1 test names corrected, Test Strategy "5 classes" → "9 classes", File Change Map expanded with all Rev.3/Rev.4 new files. |
| Q18 glossary completeness | Frontend boundary documented; excluded permissions listed with rationale. |
| Q19 VIEW_PRECISE_LOCATION classification | Confirmed `COMPUTED_ONLY_PERMISSIONS`. Note added: response filter has separate tests. |
| Q20 projectId URL regex | Tightened to strict UUID v4 with segment boundary; primary path is `meta.projectId`. |
| Q21 CI auto-commit | Rejected: security-sensitive fixture; CI fails + diff-displays only, developer commits. |
| Q22 spec amendment scope | Locked to `spec/008-permissions-vocabulary-refinement` per Prereq-2. |
| Q17 (Rev.2 carry-over) | xfail `raises=NotImplementedError` removed; tracking issues collected in `xfail_tracking.md`. |

### Rev.4 new questions (for Codex Rev.4 review)

Q23. **AD-3 `meta` AST lint** (`test_meta_completeness.ts`): Is AST-based
walking of `apps/web/src/lib/api/*.ts` reliable? TypeScript AST nodes for
TanStack Query factory calls may not be uniformly typed across the
codebase. Alternative: runtime check that throws in development when a
project-scoped query/mutation is registered without `meta.projectId`.

Q24. **ProjectPermission boundary enforcement at code-gen time**: The
union is emitted from the backend export script. If a backend dev adds a
new permission to `ENDPOINT_BACKED_PERMISSIONS`, the frontend union grows
automatically on next CI run. Are there cases where the new permission
should NOT appear in the frontend union? If yes, we need an explicit
backend opt-out marker.

Q25. **Spec/008 ordering**: Prereq-2 says spec/008 must be drafted
before implementation, merged in the same release window. Should the
plan PR be blocked on spec/008 merge, or proceed in parallel with a link?

### Rev.4 → Rev.5 resolution table (Codex Rev.4 review)

| Codex Rev.4 finding | Rev.5 resolution |
|---------------------|------------------|
| **重要-新1** ProjectPermission codegen vs AD-8 mismatch | AD-8 adds explicit `FRONTEND_PROJECT_PERMISSIONS` allow-set with assertions; ProjectPermission union emits from it (Q24 answer applied). |
| **重要-新2** OVERRIDE_TAXON_SENSITIVITY classification conflict | Moved to ENDPOINT_BACKED_PERMISSIONS + FRONTEND_PROJECT_PERMISSIONS. Now consistent with § 4A "owner-only" description. The "superuser approval" workflow is a separate concern not gated by this permission. |
| **重要-新3** AllowlistEntry example missing last_reviewed_at | Sample updated; field documented as REQUIRED, no default. |
| **重要-新4** test_meta_completeness.ts vitest pattern | Renamed to `meta-completeness.test.ts`; scope expanded to `src/routes/**/*.svelte`; new typed helper `projectQueryOptions.ts` added per Q23. |
| **重要-2 (Rev.3 carry)** invalidate but not refetch | Code sketch adds `refetchType: 'active'`. Phase 1.5 and AD-3 consolidated on `queryClient.ts`. |
| **重要-5 (Rev.3 carry)** Test Strategy stale numbers | "336 cells / 28 perms" replaced with `len(Permission) × 6 × 2` expression; vitest "26 entries" replaced with "emitted from FRONTEND_PROJECT_PERMISSIONS". |
| Q23 AST lint reliability | Combined with typed helper + dev runtime assertion approach. |
| Q24 frontend union auto-grow | Solved by explicit `FRONTEND_PROJECT_PERMISSIONS` allow-set. |
| Q25 spec/008 ordering | Codified: parallel work OK, release linked. |

### Priority-tagged review request for Codex Rev.5 (final cycle)

Please confirm:
- All Rev.4 重要 1-5 + 重要-新1-4 fully resolved.
- Q23-Q25 answers integrated.
- Timeline 32-40h / 20-24h remains realistic.
- No new P0/重要 issues introduced by Rev.5.

**This is intended to be the final review cycle.** If GO → implementation
starts. If new P0/重要 surface, Rev.6 is acceptable but indicates the plan
needs structural rework. Editorial nits (typos, minor clarifications) are
NOT blockers — they can be fixed during implementation.

---

## 14. Rev.6 Seeded Browser E2E Extension Plan

**Date**: 2026-05-15
**Status**: US1/US2/US3 plus Trusted Overlay lifecycle, Export/Search API-primary plus Dataset ZIP with audio plus Search storage gate guards plus Export-recordings success CSV plus Reference-audio success stream, Media plus Clip API-primary, and Clip browser BFF media-token wiring complete as of 2026-05-18
**Input**: `specs/007-permission-test-coverage/e2e-roadmap.md`

### Technical Context

**Language/Version**: Python 3.12 backend scripts; TypeScript/SvelteKit
frontend E2E tests.
**Primary Dependencies**: FastAPI, SQLAlchemy, Pydantic, Playwright, ESLint,
Prettier, ruff.
**Storage**: Local development PostgreSQL through the Docker backend stack;
Media uses deterministic WAV fixtures written to LocalStack/S3 with an
`AUDIO_ROOT` fallback.
**Testing**: Seed script, Python static checks, Playwright browser tests with
`--workers=1`, frontend `npm run check`, backend `mypy` for touched Python,
and existing seeded matrix/feature suites as regression gates.
**Target Platform**: Local Docker-backed development environment.
**Project Type**: Web application with `apps/api` and `apps/web`.
**Performance Goals**: Keep each seeded suite narrow enough to run serially
without destabilizing local feedback; no launch performance target changes.
**Constraints**: Do not use web JWT bearer tokens for `/api/v1`; Data Surfaces
must leave audio/spectrogram playback to the Media suite; do not destroy
baseline trusted overlay state.
**Scale/Scope**: Five incremental E2E slices: data surfaces, vote/comment,
trusted overlay, export/search, and media. Rev.6 delivered items 1 and 2, the
Trusted Overlay read/list/capability and lifecycle slices, the Export/Search
API-primary plus Dataset ZIP with audio plus Search storage gate guard plus
Export-recordings success CSV plus Reference-audio success stream slice, the
Media recording plus Clip API-primary plus Clip browser BFF media-token slice,
and the future-slice roadmap gate checklist.

### Constitution Check

- **Clean Architecture**: PASS. New behavior is test/fixture orchestration and
  does not bypass service or repository boundaries.
- **Test-Driven Development**: PASS. Each slice starts with a focused Playwright
  suite and seed requirements before implementation changes are accepted.
- **Type Safety**: PASS. TypeScript E2E helpers and Python seeder changes must
  pass ESLint/Prettier, `npm run check`, ruff/py_compile, and backend `mypy`
  gates.
- **ML Pipeline Architecture**: N/A. No ML task behavior changes.
- **API Versioning**: PASS. API assertions target existing `/api/v1` and
  `/web-api/v1` contracts without introducing breaking endpoint changes.

### Phase 0 Research Output

See `research.md`. Key decisions:

- Extend the existing seeded fixture strategy in small browser suites.
- Keep `/api/v1` API-key checks separate from `/web-api/v1` browser-session
  checks.
- Exclude media playback and spectrogram assertions from data-surface tests.
- Make vote/comment API-primary and serial when mutating shared annotation state.
- Reserve Claude review for trusted lifecycle, export/search, and media/storage
  risk, including clip media when production endpoint storage behavior changes.

### Phase 1 Design Output

- `spec.md`: continuation feature spec for seeded permission E2E coverage.
- `data-model.md`: seeded users, projects, content fixtures, vote/comment state,
  and suite gates.
- `contracts/seeded-permission-e2e.md`: seed env, API, UI, and verification
  contracts.
- `quickstart.md`: seed, env export, static check, and Playwright commands.
- `e2e-roadmap.md`: remains the persistent compact-resume roadmap and should be
  updated after each completed slice.

### Data Surfaces Slice

Candidate suite:

- `apps/web/tests/e2e/permissions/seeded-data-surfaces.spec.ts`

Implementation notes:

- Reuse seeded users, UI login helper, project IDs, dataset IDs, and dataset
  names from the existing green baseline.
- Add flat env entries for `E2E_PUBLIC_SITE_ID`, `E2E_PUBLIC_RECORDING_ID`,
  `E2E_PUBLIC_DETECTION_ID`, `E2E_RESTRICTED_SITE_ID`,
  `E2E_RESTRICTED_RECORDING_ID`, and `E2E_RESTRICTED_DETECTION_ID` before
  deep-link tests depend on them.
- Cover dataset list/detail, recording list/detail, detection list/detail where
  stable, and public explore list/detail.
- Detection detail routes use tag IDs, not detection UUIDs. Either seed a stable
  tag ID or derive it from a list response before navigating.
- Keep owner email and private metadata non-leak checks in public guest flows.
- Avoid media playback, spectrogram rendering, clip download, or byte-content
  assertions in this slice.

Completion gate:

- Seed succeeds and latest JSON env is exported.
- Seeder static and type checks pass.
- Changed E2E files pass Prettier, ESLint, and `npm run check`.
- New data-surfaces suite passes with `--workers=1`.
- Existing seeded feature and matrix suites remain green.

### Vote / Comment Slice

Candidate suite:

- `apps/web/tests/e2e/permissions/seeded-vote-comment.spec.ts`

Implementation notes:

- Use `/api/v1` with seeded raw API keys.
- Cover:
  - `GET /api/v1/projects/{projectId}/annotations/{annotationId}/votes`
  - `POST /api/v1/projects/{projectId}/annotations/{annotationId}/votes`
  - `DELETE /api/v1/projects/{projectId}/annotations/{annotationId}/votes`
  - `GET /api/v1/projects/{projectId}/annotations/{annotationId}/comments`
  - `POST /api/v1/projects/{projectId}/annotations/{annotationId}/comments`
- Keep unique comment bodies per role, visibility, and run.
- Use serial execution or explicit cleanup for DELETE vote coverage.
- Treat comments as append-only and assert created response/body presence instead
  of exact list counts.
- Existing restricted project behavior intentionally allows nonmember
  vote/comment due to `allow_voting_and_comments=true`.
- Trusted vote/comment assertions cover authorization status only; trusted source
  badge classification is outside this slice.

Completion gate:

- Seed succeeds and latest JSON env is exported.
- Seeder static and type checks pass.
- Changed E2E files pass Prettier, ESLint, and `npm run check`.
- New vote-comment suite passes with `--workers=1`.
- Existing seeded feature and matrix suites remain green.

### Rev.6 Implementation Status

The Rev.6 Data Surfaces, Vote / Comment, Trusted Overlay read-only/lifecycle,
Export/Search API-primary plus Dataset ZIP with audio plus Search storage gate
guards plus Export-recordings success CSV plus Reference-audio success stream,
and Media recording plus Clip API-primary plus Clip browser BFF media-token
wiring slices are implemented. The future
risky-surface roadmap is also refreshed with seed, completion, and Claude review
gates for remaining storage-backed Export/Search follow-ups.

Current handoff sources:

- `tasks.md`: authoritative task completion list for T001-T139.
- `e2e-roadmap.md`: latest verified command summaries, known review notes, and
  next-slice prerequisites.
- `quickstart.md`: seed/export/static-check/Playwright command reference for the
  completed seeded suites.

Verified final seeded browser result recorded in `e2e-roadmap.md`:

```bash
# 79 passed, 12 skipped
```

Remaining Rev.6 follow-up work should keep any future Trusted Overlay
accept/re-grant activation separate from the immutable baseline overlay because
the signed invitation token is delivered through email/outbox. Export / Search
follow-ups remain higher risk when they require broader CSV payload assertions
or broader dataset audio ZIP payloads beyond the seeded single-recording
fixture.

### Post-Design Constitution Check

PASS. The design adds explicit test artifacts and local fixture contracts without
changing production architecture, API versioning, or ML behavior. The only
security-sensitive material is local seed JSON; `quickstart.md` keeps it scoped
to `/tmp/echoroo-e2e-seed.json`, raw secrets are confined to the `env` payload,
and the seeder already refuses protected environments.

End of plan Rev.6. Data Surfaces, Vote / Comment, Trusted Overlay read-only and
lifecycle, Export/Search API-primary plus Dataset ZIP with audio plus Search
storage gate guards plus Export-recordings success CSV plus Reference-audio success stream,
Media recording plus Clip API-primary coverage, Clip browser BFF media-token
wiring, and risky-surface roadmap planning are complete; continue with broader
Export/Search payload follow-ups, broader dataset audio ZIP payloads beyond the
seeded single-recording fixture, or Trusted Overlay
accept/re-grant activation only after the required seed/review gates are in
place.
