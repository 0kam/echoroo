/**
 * Frontend permission utility (Spec 007 Phase 2B.1 / Plan Rev.5.1 AD-2).
 *
 * Pure synchronous `can()` evaluator that mirrors the backend
 * `compute_effective_permissions()` contract for project-scoped
 * permissions. Inputs are a `ProjectPermission` and a fully
 * discriminated `ProjectContext`.
 *
 * The permission matrix is sourced from the build-time JSON fixture
 * `__fixtures__/role_permissions.json`, which is regenerated from the
 * backend `ROLE_PERMISSIONS` / `FRONTEND_PROJECT_PERMISSIONS` and
 * validated by the CI drift gate (Phase 2B.0). The ProjectPermission
 * string union below MUST stay in sync with
 * `roleMatrix.frontend_project_permissions` — the CI gate fails the
 * build on drift.
 *
 * NO DOM, NO network, NO async. Safe to call inside Svelte `$derived`.
 */

import type { Project, ProjectVisibility, User } from '$lib/types';
import roleMatrixJson from './__fixtures__/role_permissions.json';

// ---------------------------------------------------------------------------
// Type definitions (Plan Rev.5.1 § AD-2)
// ---------------------------------------------------------------------------

/**
 * Project membership role. `null` means "no project-level role
 * assigned" — but `null` alone is ambiguous (guest vs. authenticated
 * non-member vs. loading), so callers MUST use `ProjectContext` with
 * an explicit `authState` discriminator, not `ComputedRole` in
 * isolation.
 */
export type ComputedRole = 'owner' | 'admin' | 'member' | 'viewer' | null;

/**
 * Discriminator for the user's relationship to the current project.
 * Rev.4 fix (Codex Rev.3 P0-1): `authenticated_member` MUST be in
 * this union so the discriminated `ProjectContext` member branch is
 * satisfiable.
 */
export type AuthState =
  | 'unauthenticated'
  | 'authenticated_non_member'
  | 'authenticated_member'
  | 'pending_invitation'
  | 'loading';

/**
 * Frontend project permission union.
 *
 * MUST stay in sync with `roleMatrix.frontend_project_permissions`
 * emitted by `apps/api/scripts/export_role_permissions.py`. The CI
 * drift gate (Phase 2B.0) fails the build on drift. Codegen of this
 * union from the JSON is a future improvement; for now it is
 * hand-written.
 *
 * EXCLUSIONS (intentionally NOT in this union):
 *   - search_cross_project — global, not project-scoped
 *   - manage_api_key, manage_2fa — user-scoped (account settings)
 *   - manage_site — superuser-only (separate gate)
 */
export type ProjectPermission =
  | 'view_project_metadata'
  | 'view_dataset_list'
  | 'view_media'
  | 'view_detection'
  | 'view_precise_location'
  | 'view_audit_log'
  | 'search_within_project'
  | 'download'
  | 'export'
  | 'vote'
  | 'comment'
  | 'create_tag'
  | 'annotate'
  | 'upload'
  | 'manage_dataset'
  | 'manage_dataset_admin'
  | 'run_inference'
  | 'train_model'
  | 'manage_members'
  | 'manage_trusted'
  | 'edit_project'
  | 'manage_license'
  | 'delete_project'
  | 'transfer_ownership'
  | 'override_taxon_sensitivity';

/**
 * Restricted-mode capability toggle subset relevant to `can()`.
 *
 * Mirrors the toggles in `roleMatrix.visibility_overlays.restricted_toggles`.
 * The full `RestrictedConfig` type (in `$lib/types`) carries additional
 * fields (e.g. `mask_species_in_detection`, h3 resolution) that affect
 * response shaping but not permission gating, so they are intentionally
 * omitted here.
 */
export interface RestrictedToggles {
  allow_media_playback: boolean;
  allow_detection_view: boolean;
  allow_download: boolean;
  allow_export: boolean;
  allow_voting_and_comments: boolean;
  allow_precise_location_to_viewer: boolean;
}

/**
 * Discriminated project context. Rev.3 fix (Codex Rev.2 Rev2-1):
 * a non-null role is ONLY valid with `authState: 'authenticated_member'`.
 * Constructing `{ role: 'admin', authState: 'authenticated_non_member' }`
 * fails TypeScript type-check.
 */
export type ProjectContext =
  | {
      authState: 'authenticated_member';
      role: 'owner' | 'admin' | 'member' | 'viewer';
      visibility: 'public' | 'restricted';
      restrictedConfig?: RestrictedToggles;
    }
  | {
      authState:
        | 'unauthenticated'
        | 'authenticated_non_member'
        | 'pending_invitation'
        | 'loading';
      role: null;
      visibility: 'public' | 'restricted';
      restrictedConfig?: RestrictedToggles;
    };

// ---------------------------------------------------------------------------
// Internal: typed view over the JSON fixture
// ---------------------------------------------------------------------------

type RoleKey = 'owner' | 'admin' | 'member' | 'viewer';

interface RoleMatrix {
  role_permissions: Record<RoleKey, readonly string[]>;
  visibility_overlays: {
    public: {
      guest: readonly string[];
      authenticated_non_member: readonly string[];
    };
    restricted_toggles: Record<keyof RestrictedToggles, readonly string[]>;
  };
}

const roleMatrix = roleMatrixJson as unknown as RoleMatrix;

/**
 * Pre-build per-role permission Sets for O(1) membership checks.
 */
const ROLE_PERMISSION_SETS: Record<RoleKey, ReadonlySet<string>> = {
  owner: new Set(roleMatrix.role_permissions.owner),
  admin: new Set(roleMatrix.role_permissions.admin),
  member: new Set(roleMatrix.role_permissions.member),
  viewer: new Set(roleMatrix.role_permissions.viewer),
};

const PUBLIC_GUEST_OVERLAY: ReadonlySet<string> = new Set(
  roleMatrix.visibility_overlays.public.guest
);
const PUBLIC_NONMEMBER_OVERLAY: ReadonlySet<string> = new Set(
  roleMatrix.visibility_overlays.public.authenticated_non_member
);
const RESTRICTED_TOGGLE_PERMS: Record<keyof RestrictedToggles, readonly string[]> =
  roleMatrix.visibility_overlays.restricted_toggles;

// ---------------------------------------------------------------------------
// can()
// ---------------------------------------------------------------------------

/**
 * Evaluate whether a permission is granted in the given project
 * context. Pure, synchronous, and side-effect-free.
 *
 * Decision tree:
 *   1. authState === 'loading' || 'pending_invitation' → false
 *      (safe default — invitation must be accepted before any access).
 *   2. authState === 'authenticated_member' → base = role_permissions[role]
 *      + restricted toggle overlay (when visibility === 'restricted'
 *      and the toggle grants something the role lacks, e.g. Viewer
 *      with `allow_voting_and_comments` or `allow_precise_location_to_viewer`).
 *      Public visibility adds no extras for members (members already
 *      have ≥ all overlay perms).
 *   3. Non-member branch:
 *      - Public:
 *          unauthenticated → public.guest overlay
 *          authenticated_non_member → public.authenticated_non_member overlay
 *      - Restricted: NO base permissions. Only restricted toggle perms
 *        are granted (if `restrictedConfig` is present and the matching
 *        toggle is true). Note: 'authenticated_non_member' on a
 *        restricted project still pivots through this branch (FR-014).
 */
export function can(permission: ProjectPermission, ctx: ProjectContext): boolean {
  // 1. Safe default for transient / pre-acceptance states.
  if (ctx.authState === 'loading' || ctx.authState === 'pending_invitation') {
    return false;
  }

  // 2. Member branch: role-based base + restricted toggle overlay.
  if (ctx.authState === 'authenticated_member') {
    const base = ROLE_PERMISSION_SETS[ctx.role];
    if (base.has(permission)) {
      return true;
    }

    // Members may pick up extra perms on Restricted via toggles
    // (e.g. Viewer with allow_voting_and_comments → vote/comment;
    // Viewer with allow_precise_location_to_viewer → view_precise_location).
    if (ctx.visibility === 'restricted' && ctx.restrictedConfig) {
      return isPermittedByRestrictedToggle(permission, ctx.restrictedConfig);
    }

    return false;
  }

  // 3. Non-member branch (unauthenticated | authenticated_non_member).
  if (ctx.visibility === 'public') {
    const overlay =
      ctx.authState === 'unauthenticated'
        ? PUBLIC_GUEST_OVERLAY
        : PUBLIC_NONMEMBER_OVERLAY;
    return overlay.has(permission);
  }

  // Restricted + non-member: only toggle-granted perms.
  if (ctx.restrictedConfig) {
    return isPermittedByRestrictedToggle(permission, ctx.restrictedConfig);
  }

  return false;
}

/**
 * Look up whether the given permission is granted by any enabled
 * restricted toggle. Returns true iff at least one toggle is `true`
 * AND maps to the requested permission.
 */
function isPermittedByRestrictedToggle(
  permission: ProjectPermission,
  config: RestrictedToggles
): boolean {
  // Iterate the known toggle keys. The fixture defines which perms
  // each toggle unlocks; we only consult a toggle's perm list when
  // the toggle is enabled.
  const toggleKeys = Object.keys(RESTRICTED_TOGGLE_PERMS) as (keyof RestrictedToggles)[];
  for (const key of toggleKeys) {
    if (config[key] && RESTRICTED_TOGGLE_PERMS[key].includes(permission)) {
      return true;
    }
  }
  return false;
}

// ---------------------------------------------------------------------------
// buildProjectContext()
// ---------------------------------------------------------------------------

/**
 * Auth store contract expected by `buildProjectContext()`. The
 * concrete `auth.svelte.ts` store satisfies this shape via its
 * `isAuthenticated` + `user` getters.
 */
export interface AuthStoreLike {
  isAuthenticated: boolean;
  user: User | null;
}

export interface ProjectQueryState {
  isLoading: boolean;
  isError: boolean;
}

export interface BuildProjectContextArgs {
  authStore: AuthStoreLike;
  project: Project | undefined;
  projectQueryState: ProjectQueryState;
  pendingInvitationToken: string | null;
}

/**
 * Derive a `ProjectContext` from the auth store + Project query +
 * optional pending invitation token.
 *
 * Priority:
 *   1. Project query loading → `loading`
 *   2. Unauthenticated WITH a pending invitation token → `pending_invitation`
 *   3. Unauthenticated WITHOUT token → `unauthenticated`
 *   4. Authenticated AND `project.current_user_role !== null` → `authenticated_member`
 *   5. Authenticated AND `project.current_user_role == null` (or project still undefined
 *      after load) → `authenticated_non_member`
 *
 * Visibility: derived from `project.visibility`.
 */
export function buildProjectContext(args: BuildProjectContextArgs): ProjectContext {
  const { authStore, project, projectQueryState, pendingInvitationToken } = args;

  const visibility = normalizeVisibility(project?.visibility);
  const restrictedConfig = project?.restricted_config
    ? toRestrictedToggles(project.restricted_config)
    : undefined;

  // 1. Query still loading — safe default.
  if (projectQueryState.isLoading) {
    return {
      authState: 'loading',
      role: null,
      visibility,
      ...(restrictedConfig ? { restrictedConfig } : {}),
    };
  }

  const isAuthed = authStore.isAuthenticated;

  // 2 + 3. Not authenticated: split on invitation token presence.
  if (!isAuthed) {
    if (pendingInvitationToken) {
      return {
        authState: 'pending_invitation',
        role: null,
        visibility,
        ...(restrictedConfig ? { restrictedConfig } : {}),
      };
    }
    return {
      authState: 'unauthenticated',
      role: null,
      visibility,
      ...(restrictedConfig ? { restrictedConfig } : {}),
    };
  }

  // 4. Authenticated member.
  const role = project?.current_user_role ?? null;
  if (role !== null) {
    return {
      authState: 'authenticated_member',
      role,
      visibility,
      ...(restrictedConfig ? { restrictedConfig } : {}),
    };
  }

  // 5. Authenticated non-member (or project still undefined after load).
  return {
    authState: 'authenticated_non_member',
    role: null,
    visibility,
    ...(restrictedConfig ? { restrictedConfig } : {}),
  };
}

/**
 * Map `ProjectVisibility` down to the `ProjectContext` visibility.
 */
function normalizeVisibility(
  visibility: ProjectVisibility | undefined
): 'public' | 'restricted' {
  return visibility === 'public' ? 'public' : 'restricted';
}

/**
 * Extract the toggle subset relevant to `can()` from the wider
 * `RestrictedConfig` shape (which also carries shaping-only fields
 * like `mask_species_in_detection` and `public_location_precision_h3_res`).
 */
function toRestrictedToggles(config: {
  allow_media_playback: boolean;
  allow_detection_view: boolean;
  allow_download: boolean;
  allow_export: boolean;
  allow_voting_and_comments: boolean;
  allow_precise_location_to_viewer: boolean;
}): RestrictedToggles {
  return {
    allow_media_playback: config.allow_media_playback,
    allow_detection_view: config.allow_detection_view,
    allow_download: config.allow_download,
    allow_export: config.allow_export,
    allow_voting_and_comments: config.allow_voting_and_comments,
    allow_precise_location_to_viewer: config.allow_precise_location_to_viewer,
  };
}
