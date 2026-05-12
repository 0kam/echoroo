/**
 * Matrix-complete vitest for `can()` (Spec 007 Phase 2B.2 / Plan Rev.5.1
 * § Phase 2B.2 + § Phase 4.1).
 *
 * Generates a Cartesian product of:
 *   - 8 (authState, role) combos
 *   - 2 visibilities (public, restricted)
 *   - |FRONTEND_PROJECT_PERMISSIONS| permissions emitted from the JSON
 *     fixture (currently 25)
 *   - 3 restricted-toggle profiles (all_off, all_on, media_only)
 *
 * The expected value for each cell is computed FROM the JSON fixture
 * (not by calling `can()`), so the test is a true cross-check against
 * the backend-exported matrix rather than a re-implementation tautology.
 *
 * The Cartesian generator yields ~1200 cases; `test.each` reports each
 * cell individually so a regression pinpoints exactly which
 * (authState, role, visibility, permission, toggle profile) tuple
 * broke. Edge cases listed in Plan § Phase 4.1 have dedicated
 * `it.each` spot tests below the matrix so failures there are
 * unambiguous even if the matrix generator changes shape.
 *
 * NOTE: The matrix tests are derived from the JSON fixture, which is
 * the same artefact that drives `can()`'s internal sets. If the
 * fixture drifts from the backend `ROLE_PERMISSIONS`, the CI drift
 * gate (Phase 2B.0) will fail — that gate guards the source of truth,
 * not this test.
 */

import { describe, expect, it, test } from 'vitest';

import roleMatrixJson from './__fixtures__/role_permissions.json';
import {
  can,
  type ProjectContext,
  type ProjectPermission,
  type RestrictedToggles,
} from './permissions';

// ---------------------------------------------------------------------------
// JSON fixture typing (mirror the internal types in permissions.ts).
// ---------------------------------------------------------------------------

type RoleKey = 'owner' | 'admin' | 'member' | 'viewer';

interface RoleMatrix {
  role_permissions: Record<RoleKey, readonly string[]>;
  frontend_project_permissions: readonly string[];
  visibility_overlays: {
    public: {
      guest: readonly string[];
      authenticated_non_member: readonly string[];
    };
    restricted_toggles: Record<keyof RestrictedToggles, readonly string[]>;
  };
}

const matrix = roleMatrixJson as unknown as RoleMatrix;

const FRONTEND_PERMISSIONS = matrix.frontend_project_permissions as readonly ProjectPermission[];

const ROLE_PERMISSION_SETS: Record<RoleKey, ReadonlySet<string>> = {
  owner: new Set(matrix.role_permissions.owner),
  admin: new Set(matrix.role_permissions.admin),
  member: new Set(matrix.role_permissions.member),
  viewer: new Set(matrix.role_permissions.viewer),
};

const PUBLIC_GUEST_SET = new Set(matrix.visibility_overlays.public.guest);
const PUBLIC_NONMEMBER_SET = new Set(
  matrix.visibility_overlays.public.authenticated_non_member,
);
const RESTRICTED_TOGGLES = matrix.visibility_overlays.restricted_toggles;

// ---------------------------------------------------------------------------
// Matrix axes.
// ---------------------------------------------------------------------------

type AuthRoleCombo =
  | { authState: 'authenticated_member'; role: 'owner' | 'admin' | 'member' | 'viewer' }
  | { authState: 'unauthenticated'; role: null }
  | { authState: 'authenticated_non_member'; role: null }
  | { authState: 'pending_invitation'; role: null }
  | { authState: 'loading'; role: null };

const COMBOS: readonly AuthRoleCombo[] = [
  { authState: 'authenticated_member', role: 'owner' },
  { authState: 'authenticated_member', role: 'admin' },
  { authState: 'authenticated_member', role: 'member' },
  { authState: 'authenticated_member', role: 'viewer' },
  { authState: 'unauthenticated', role: null },
  { authState: 'authenticated_non_member', role: null },
  { authState: 'pending_invitation', role: null },
  { authState: 'loading', role: null },
];

const VISIBILITIES: readonly ('public' | 'restricted')[] = ['public', 'restricted'];

const ALL_OFF: RestrictedToggles = {
  allow_media_playback: false,
  allow_detection_view: false,
  allow_download: false,
  allow_export: false,
  allow_voting_and_comments: false,
  allow_precise_location_to_viewer: false,
};

const ALL_ON: RestrictedToggles = {
  allow_media_playback: true,
  allow_detection_view: true,
  allow_download: true,
  allow_export: true,
  allow_voting_and_comments: true,
  allow_precise_location_to_viewer: true,
};

const MEDIA_ONLY: RestrictedToggles = {
  ...ALL_OFF,
  allow_media_playback: true,
};

const TOGGLE_PROFILES: ReadonlyArray<{ name: string; toggles: RestrictedToggles }> = [
  { name: 'all_off', toggles: ALL_OFF },
  { name: 'all_on', toggles: ALL_ON },
  { name: 'media_only', toggles: MEDIA_ONLY },
];

// ---------------------------------------------------------------------------
// Independent expected-value calculator. Derives the answer directly
// from the JSON fixture using the SAME rules documented in
// permissions.ts:can(), but expressed declaratively so a wrong
// implementation in can() will diverge from this oracle.
// ---------------------------------------------------------------------------

function toggleGrantsPermission(
  permission: ProjectPermission,
  toggles: RestrictedToggles,
): boolean {
  const keys = Object.keys(RESTRICTED_TOGGLES) as (keyof RestrictedToggles)[];
  for (const key of keys) {
    if (toggles[key] && RESTRICTED_TOGGLES[key].includes(permission)) {
      return true;
    }
  }
  return false;
}

function expectedValue(
  combo: AuthRoleCombo,
  visibility: 'public' | 'restricted',
  permission: ProjectPermission,
  toggles: RestrictedToggles,
): boolean {
  // 1. loading / pending_invitation → never grants anything.
  if (combo.authState === 'loading' || combo.authState === 'pending_invitation') {
    return false;
  }

  // 2. Member branch: base role perms + restricted-toggle overlay.
  if (combo.authState === 'authenticated_member') {
    const base = ROLE_PERMISSION_SETS[combo.role];
    if (base.has(permission)) {
      return true;
    }
    if (visibility === 'restricted') {
      return toggleGrantsPermission(permission, toggles);
    }
    return false;
  }

  // 3. Non-member branch on public: pick the right overlay.
  if (visibility === 'public') {
    const overlay =
      combo.authState === 'unauthenticated'
        ? PUBLIC_GUEST_SET
        : PUBLIC_NONMEMBER_SET;
    return overlay.has(permission);
  }

  // 4. Non-member branch on restricted: only toggle-granted perms.
  return toggleGrantsPermission(permission, toggles);
}

// ---------------------------------------------------------------------------
// Build the parametrised case list.
// ---------------------------------------------------------------------------

interface MatrixCase {
  authState: AuthRoleCombo['authState'];
  role: AuthRoleCombo['role'];
  visibility: 'public' | 'restricted';
  permission: ProjectPermission;
  profileName: string;
  toggles: RestrictedToggles;
  expected: boolean;
}

const CASES: MatrixCase[] = [];
for (const combo of COMBOS) {
  for (const visibility of VISIBILITIES) {
    for (const permission of FRONTEND_PERMISSIONS) {
      for (const profile of TOGGLE_PROFILES) {
        CASES.push({
          authState: combo.authState,
          role: combo.role,
          visibility,
          permission,
          profileName: profile.name,
          toggles: profile.toggles,
          expected: expectedValue(combo, visibility, permission, profile.toggles),
        });
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Tests.
// ---------------------------------------------------------------------------

describe('can() — sanity', () => {
  it('frontend_project_permissions emitted by fixture is non-empty', () => {
    expect(FRONTEND_PERMISSIONS.length).toBeGreaterThan(0);
  });

  it('matrix case count matches axis cardinality', () => {
    const expectedCount =
      COMBOS.length *
      VISIBILITIES.length *
      FRONTEND_PERMISSIONS.length *
      TOGGLE_PROFILES.length;
    expect(CASES.length).toBe(expectedCount);
  });
});

describe('can() — full matrix', () => {
  test.each(CASES)(
    'authState=$authState role=$role vis=$visibility perm=$permission profile=$profileName -> $expected',
    ({ authState, role, visibility, permission, toggles, expected }) => {
      // Build a context that satisfies the discriminated union. The
      // matrix above already enforces the role+authState pairing rules
      // (role=null iff non-member), so the cast is safe at runtime.
      const ctx = {
        authState,
        role,
        visibility,
        restrictedConfig: toggles,
      } as ProjectContext;
      expect(can(permission, ctx)).toBe(expected);
    },
  );
});

// ---------------------------------------------------------------------------
// Edge-case spot tests (Plan Rev.5.1 § Phase 4.1).
// ---------------------------------------------------------------------------

describe('can() — edge-case spot tests (Plan § Phase 4.1)', () => {
  it('unauthenticated guest on public CANNOT vote (per guest overlay)', () => {
    const ctx: ProjectContext = {
      authState: 'unauthenticated',
      role: null,
      visibility: 'public',
    };
    // Backend public-vote semantics: guest overlay omits `vote`.
    // (Spec FR-019: guests must authenticate before voting.)
    expect(can('vote', ctx)).toBe(false);
  });

  it('authenticated_non_member on public CAN vote (per non-member overlay)', () => {
    const ctx: ProjectContext = {
      authState: 'authenticated_non_member',
      role: null,
      visibility: 'public',
    };
    expect(can('vote', ctx)).toBe(true);
  });

  it('pending_invitation on public CANNOT vote (safe default)', () => {
    const ctx: ProjectContext = {
      authState: 'pending_invitation',
      role: null,
      visibility: 'public',
    };
    expect(can('vote', ctx)).toBe(false);
  });

  it('owner on restricted CAN delete_project', () => {
    const ctx: ProjectContext = {
      authState: 'authenticated_member',
      role: 'owner',
      visibility: 'restricted',
    };
    expect(can('delete_project', ctx)).toBe(true);
  });

  it('admin on restricted CANNOT delete_project (owner-only)', () => {
    const ctx: ProjectContext = {
      authState: 'authenticated_member',
      role: 'admin',
      visibility: 'restricted',
    };
    expect(can('delete_project', ctx)).toBe(false);
  });

  it.each([
    ['public' as const],
    ['restricted' as const],
  ])(
    'member on %s CANNOT manage_dataset_admin (AD-1B Option A vocabulary)',
    (visibility) => {
      const ctx: ProjectContext = {
        authState: 'authenticated_member',
        role: 'member',
        visibility,
      };
      expect(can('manage_dataset_admin', ctx)).toBe(false);
    },
  );

  it('unauthenticated on restricted with allow_media_playback=true CAN view_media (toggle unlock)', () => {
    const ctx: ProjectContext = {
      authState: 'unauthenticated',
      role: null,
      visibility: 'restricted',
      restrictedConfig: {
        ...ALL_OFF,
        allow_media_playback: true,
      },
    };
    expect(can('view_media', ctx)).toBe(true);
  });

  it('viewer on restricted with allow_voting_and_comments=true CAN vote and comment (member-toggle uplift)', () => {
    const ctx: ProjectContext = {
      authState: 'authenticated_member',
      role: 'viewer',
      visibility: 'restricted',
      restrictedConfig: {
        ...ALL_OFF,
        allow_voting_and_comments: true,
      },
    };
    expect(can('vote', ctx)).toBe(true);
    expect(can('comment', ctx)).toBe(true);
  });

  it('viewer on restricted with allow_precise_location_to_viewer=true CAN view_precise_location', () => {
    const ctx: ProjectContext = {
      authState: 'authenticated_member',
      role: 'viewer',
      visibility: 'restricted',
      restrictedConfig: {
        ...ALL_OFF,
        allow_precise_location_to_viewer: true,
      },
    };
    expect(can('view_precise_location', ctx)).toBe(true);
  });

  it('loading state denies every frontend permission', () => {
    const ctx: ProjectContext = {
      authState: 'loading',
      role: null,
      visibility: 'public',
    };
    for (const perm of FRONTEND_PERMISSIONS) {
      expect(can(perm, ctx)).toBe(false);
    }
  });
});
