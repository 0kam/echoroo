/**
 * Permission management store
 * Handles role-based permissions for projects
 */

import { writable } from 'svelte/store';

export type ProjectRole = 'admin' | 'member' | 'viewer';

export interface ProjectPermissions {
  canView: boolean;
  canEdit: boolean;
  canManageMembers: boolean;
  canDelete: boolean;
  isOwner: boolean;
  role: ProjectRole | null;
}

/**
 * Store for current project permissions
 */
export const currentProjectPermissions = writable<ProjectPermissions>({
  canView: false,
  canEdit: false,
  canManageMembers: false,
  canDelete: false,
  isOwner: false,
  role: null,
});

/**
 * Calculate permissions based on role and ownership
 */
export function getPermissionsForRole(
  role: ProjectRole | null,
  isOwner: boolean
): ProjectPermissions {
  // Owner has all permissions
  if (isOwner) {
    return {
      canView: true,
      canEdit: true,
      canManageMembers: true,
      canDelete: true,
      isOwner: true,
      role: 'admin', // Owner is effectively admin
    };
  }

  // Non-member has no permissions
  if (!role) {
    return {
      canView: false,
      canEdit: false,
      canManageMembers: false,
      canDelete: false,
      isOwner: false,
      role: null,
    };
  }

  // Role-based permissions
  switch (role) {
    case 'admin':
      return {
        canView: true,
        canEdit: true,
        canManageMembers: true,
        canDelete: false, // Only owner can delete
        isOwner: false,
        role: 'admin',
      };
    case 'member':
      return {
        canView: true,
        canEdit: true,
        canManageMembers: false,
        canDelete: false,
        isOwner: false,
        role: 'member',
      };
    case 'viewer':
      return {
        canView: true,
        canEdit: false,
        canManageMembers: false,
        canDelete: false,
        isOwner: false,
        role: 'viewer',
      };
    default:
      return {
        canView: false,
        canEdit: false,
        canManageMembers: false,
        canDelete: false,
        isOwner: false,
        role: null,
      };
  }
}

/**
 * Get role description
 */
export function getRoleDescription(role: ProjectRole): string {
  switch (role) {
    case 'admin':
      return 'Can manage members and edit project settings';
    case 'member':
      return 'Can view and edit project data';
    case 'viewer':
      return 'Can only view project data';
  }
}

/**
 * Get role display name
 */
export function getRoleDisplayName(role: ProjectRole): string {
  return role.charAt(0).toUpperCase() + role.slice(1);
}
