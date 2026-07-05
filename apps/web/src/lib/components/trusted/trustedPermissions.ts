/**
 * Shared helpers for the Trusted-user permission surface (Phase 10 / T520).
 *
 * Centralises the allowlisted permission ordering, the localized permission
 * labels and the `Record<TrustedGrantedPermission, boolean>` scaffolding that
 * is otherwise duplicated between the invite form and the edit-permissions
 * modal.
 *
 * The `Record` <-> list conversions are pure (no Svelte / DOM dependencies)
 * so they can be unit tested in isolation. `permissionLabel` reads the
 * paraglide messages directly; locale changes stay reactive because the
 * message functions resolve the active locale on each call.
 */
import * as m from '$lib/paraglide/messages';
import type { TrustedGrantedPermission } from '$lib/types';

/**
 * Allowlisted permissions (mirrors `TRUSTED_ALLOWED_PERMISSIONS` / FR-012).
 * Order is stable so the form layout doesn't shuffle between renders.
 */
export const ALL_TRUSTED_PERMISSIONS: ReadonlyArray<TrustedGrantedPermission> = [
  'view_media',
  'view_detection',
  'view_precise_location',
  'download',
  'export',
  'search_within_project',
  'vote',
  'comment',
];

/** A selection state keyed by every allowlisted permission. */
export type TrustedPermissionRecord = Record<TrustedGrantedPermission, boolean>;

/** Localized flash message state shared by the invite form and row actions. */
export type TrustedFlash =
  | { kind: 'idle' }
  | { kind: 'success'; message: string }
  | { kind: 'error'; message: string };

/** Localized label for a single Trusted permission. */
export function permissionLabel(p: TrustedGrantedPermission): string {
  switch (p) {
    case 'view_media':
      return m.trusted_permission_view_media();
    case 'view_detection':
      return m.trusted_permission_view_detection();
    case 'view_precise_location':
      return m.trusted_permission_view_precise_location();
    case 'download':
      return m.trusted_permission_download();
    case 'export':
      return m.trusted_permission_export();
    case 'search_within_project':
      return m.trusted_permission_search_within_project();
    case 'vote':
      return m.trusted_permission_vote();
    case 'comment':
      return m.trusted_permission_comment();
  }
}

/**
 * Build a selection record from an explicit set of granted permissions.
 * Any permission not present in `granted` is set to `false`.
 */
export function permissionRecordFrom(
  granted: Iterable<TrustedGrantedPermission>,
): TrustedPermissionRecord {
  const set = new Set(granted);
  return ALL_TRUSTED_PERMISSIONS.reduce((acc, perm) => {
    acc[perm] = set.has(perm);
    return acc;
  }, {} as TrustedPermissionRecord);
}

/** An all-`false` selection record (nothing granted). */
export function emptyPermissionRecord(): TrustedPermissionRecord {
  return permissionRecordFrom([]);
}

/** The default invite selection (safe read-only view: media + detection). */
export function defaultInvitePermissionRecord(): TrustedPermissionRecord {
  return permissionRecordFrom(['view_media', 'view_detection']);
}

/**
 * Flatten a selection record back into the allowlist-ordered list of
 * granted permissions (drops the `false` entries).
 */
export function selectedPermissions(
  record: TrustedPermissionRecord,
): TrustedGrantedPermission[] {
  return ALL_TRUSTED_PERMISSIONS.filter((p) => record[p]);
}
