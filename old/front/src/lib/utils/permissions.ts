/**
 * Permission utility functions for Echoroo
 * Based on the permission matrix defined in UI_STRUCTURE_PLAN.md
 */

import type {
  User,
  Project,
  ProjectMember,
  Dataset,
  AnnotationProject,
  ClipAnnotation,
  SoundEventAnnotation,
} from "@/lib/types";

// Generic annotation type for permission checks
type Annotation = ClipAnnotation | SoundEventAnnotation;

// ============================================
// User Role Checks
// ============================================

/**
 * Check if user is a superuser
 */
export function isSuperuser(user: User | null | undefined): boolean {
  return user?.is_superuser === true;
}

/**
 * Check if user is a manager of a specific project
 */
export function isProjectManager(
  user: User | null | undefined,
  project: Project | null | undefined
): boolean {
  if (!user || !project) return false;
  return project.memberships.some(
    (m) => m.user_id === user.id && m.role === "manager"
  );
}

/**
 * Check if user is a member (manager or regular member) of a specific project
 */
export function isProjectMember(
  user: User | null | undefined,
  project: Project | null | undefined
): boolean {
  if (!user || !project) return false;
  return project.memberships.some((m) => m.user_id === user.id);
}

/**
 * Get user's membership in a project
 */
export function getProjectMembership(
  user: User | null | undefined,
  project: Project | null | undefined
): ProjectMember | null {
  if (!user || !project) return null;
  return (
    project.memberships.find((m) => m.user_id === user.id) ?? null
  );
}

// ============================================
// Project Permissions
// ============================================

/**
 * Can user create a new project?
 * Only superusers can create projects
 */
export function canCreateProject(user: User | null | undefined): boolean {
  return isSuperuser(user);
}

/**
 * Can user view a project?
 * All users (including anonymous) can view all projects
 */
export function canViewProject(
  _user: User | null | undefined,
  _project: Project | null | undefined
): boolean {
  return true;
}

/**
 * Can user edit project details?
 * Superusers and project managers can edit
 */
export function canEditProject(
  user: User | null | undefined,
  project: Project | null | undefined
): boolean {
  return isSuperuser(user) || isProjectManager(user, project);
}

/**
 * Can user delete a project?
 * Only superusers can delete projects
 */
export function canDeleteProject(user: User | null | undefined): boolean {
  return isSuperuser(user);
}

// ============================================
// Project Membership Permissions
// ============================================

/**
 * Can user add members to a project?
 * Superusers and project managers can add members
 */
export function canAddProjectMember(
  user: User | null | undefined,
  project: Project | null | undefined
): boolean {
  return isSuperuser(user) || isProjectManager(user, project);
}

/**
 * Can user remove members from a project?
 * Superusers and project managers can remove members
 */
export function canRemoveProjectMember(
  user: User | null | undefined,
  project: Project | null | undefined
): boolean {
  return isSuperuser(user) || isProjectManager(user, project);
}

/**
 * Can user change member roles in a project?
 * Superusers and project managers can change roles
 */
export function canChangeProjectMemberRole(
  user: User | null | undefined,
  project: Project | null | undefined
): boolean {
  return isSuperuser(user) || isProjectManager(user, project);
}

// ============================================
// Site Permissions
// ============================================

/**
 * Can user view sites?
 * All users (including anonymous) can view all sites
 */
export function canViewSite(
  _user: User | null | undefined,
  _site?: any
): boolean {
  return true;
}

/**
 * Can user create a site?
 * Superusers and project managers can create sites
 */
export function canCreateSite(
  user: User | null | undefined,
  project: Project | null | undefined
): boolean {
  return isSuperuser(user) || isProjectManager(user, project);
}

/**
 * Can user edit a site?
 * Superusers and project managers can edit sites
 */
export function canEditSite(
  user: User | null | undefined,
  project: Project | null | undefined
): boolean {
  return isSuperuser(user) || isProjectManager(user, project);
}

/**
 * Can user delete a site?
 * Only superusers can delete sites
 */
export function canDeleteSite(user: User | null | undefined): boolean {
  return isSuperuser(user);
}

// ============================================
// Dataset Permissions
// ============================================

/**
 * Can user view a dataset?
 * - Public datasets: all users
 * - Restricted datasets: project members only
 */
export function canViewDataset(
  user: User | null | undefined,
  dataset: Dataset | null | undefined,
  project?: Project | null | undefined
): boolean {
  if (!dataset) return false;

  // Public datasets are visible to everyone
  if (dataset.visibility === "public") return true;

  // Restricted datasets require project membership
  if (dataset.visibility === "restricted") {
    if (isSuperuser(user)) return true;
    if (project && isProjectMember(user, project)) return true;
    return false;
  }

  return false;
}

/**
 * Can user create a dataset?
 * Superusers and project managers can create datasets
 */
export function canCreateDataset(
  user: User | null | undefined,
  project: Project | null | undefined
): boolean {
  return isSuperuser(user) || isProjectManager(user, project);
}

/**
 * Can user edit a dataset?
 * Superusers and project managers can edit datasets
 */
export function canEditDataset(
  user: User | null | undefined,
  dataset: Dataset | null | undefined,
  project?: Project | null | undefined
): boolean {
  if (!dataset) return false;
  if (isSuperuser(user)) return true;
  if (project && isProjectManager(user, project)) return true;
  return false;
}

/**
 * Can user delete a dataset?
 * Superusers and project managers can delete datasets
 */
export function canDeleteDataset(
  user: User | null | undefined,
  dataset: Dataset | null | undefined,
  project?: Project | null | undefined
): boolean {
  if (!dataset) return false;
  if (isSuperuser(user)) return true;
  if (project && isProjectManager(user, project)) return true;
  return false;
}

/**
 * Can user manage datetime parsing for a dataset?
 * Superusers and project managers can manage datetime parsing
 */
export function canManageDatetimeParsing(
  user: User | null | undefined,
  dataset: Dataset | null | undefined,
  project?: Project | null | undefined
): boolean {
  return canEditDataset(user, dataset, project);
}

// ============================================
// Annotation Project Permissions
// ============================================

/**
 * Can user view an annotation project?
 * Same rules as dataset: public or project member for restricted
 */
export function canViewAnnotationProject(
  user: User | null | undefined,
  annotationProject: AnnotationProject | null | undefined,
  project?: Project | null | undefined
): boolean {
  if (!annotationProject) return false;

  // Public APs are visible to everyone
  if (annotationProject.visibility === "public") return true;

  // Restricted APs require project membership
  if (annotationProject.visibility === "restricted") {
    if (isSuperuser(user)) return true;
    if (project && isProjectMember(user, project)) return true;
    return false;
  }

  return false;
}

/**
 * Can user create an annotation project?
 * Superusers and project managers can create annotation projects
 */
export function canCreateAnnotationProject(
  user: User | null | undefined,
  project: Project | null | undefined
): boolean {
  return isSuperuser(user) || isProjectManager(user, project);
}

/**
 * Can user edit an annotation project?
 * Superusers and project managers can edit annotation projects
 */
export function canEditAnnotationProject(
  user: User | null | undefined,
  annotationProject: AnnotationProject | null | undefined,
  project?: Project | null | undefined
): boolean {
  if (!annotationProject) return false;
  if (isSuperuser(user)) return true;
  if (project && isProjectManager(user, project)) return true;
  return false;
}

/**
 * Can user delete an annotation project?
 * Superusers and project managers can delete annotation projects
 */
export function canDeleteAnnotationProject(
  user: User | null | undefined,
  annotationProject: AnnotationProject | null | undefined,
  project?: Project | null | undefined
): boolean {
  if (!annotationProject) return false;
  if (isSuperuser(user)) return true;
  if (project && isProjectManager(user, project)) return true;
  return false;
}

// ============================================
// Annotation Permissions
// ============================================

/**
 * Can user add annotations?
 * Project members can add annotations
 */
export function canAddAnnotation(
  user: User | null | undefined,
  project: Project | null | undefined
): boolean {
  if (isSuperuser(user)) return true;
  return isProjectMember(user, project);
}

/**
 * Can user edit an annotation?
 * - Own annotations: creator and managers
 * - Other's annotations: only managers
 */
export function canEditAnnotation(
  user: User | null | undefined,
  annotation: Annotation | null | undefined,
  project?: Project | null | undefined
): boolean {
  if (!user || !annotation) return false;

  // Superusers can edit any annotation
  if (isSuperuser(user)) return true;

  // Project managers can edit any annotation
  if (project && isProjectManager(user, project)) return true;

  // Users can edit their own annotations
  if (annotation.created_by?.id === user.id) return true;

  return false;
}

/**
 * Can user delete an annotation?
 * Same rules as edit
 */
export function canDeleteAnnotation(
  user: User | null | undefined,
  annotation: Annotation | null | undefined,
  project?: Project | null | undefined
): boolean {
  return canEditAnnotation(user, annotation, project);
}

/**
 * Can user add comments to an annotation?
 * All users (including anonymous) can comment
 */
export function canAddAnnotationComment(
  _user: User | null | undefined
): boolean {
  return true;
}

// ============================================
// Metadata (Recorder/License) Permissions
// ============================================

/**
 * Can user view recorders/licenses?
 * All users can view
 */
export function canViewMetadata(
  _user: User | null | undefined
): boolean {
  return true;
}

/**
 * Can user create recorders/licenses?
 * Superusers and project managers can create
 */
export function canCreateMetadata(user: User | null | undefined): boolean {
  if (isSuperuser(user)) return true;
  // Any project manager can create metadata
  // We'll need to check if user is a manager of any project
  return false; // TODO: implement project manager check
}

/**
 * Can user edit recorders/licenses?
 * Superusers and project managers can edit
 */
export function canEditMetadata(user: User | null | undefined): boolean {
  return canCreateMetadata(user);
}

/**
 * Can user delete recorders/licenses?
 * Superusers and project managers can delete (when unused)
 */
export function canDeleteMetadata(user: User | null | undefined): boolean {
  return canCreateMetadata(user);
}

// ============================================
// User Management Permissions
// ============================================

/**
 * Can user view user list?
 * Only superusers can view user list
 */
export function canViewUserList(user: User | null | undefined): boolean {
  return isSuperuser(user);
}

/**
 * Can user create users?
 * Only superusers can create users
 */
export function canCreateUser(user: User | null | undefined): boolean {
  return isSuperuser(user);
}

/**
 * Can user edit a specific user?
 * Only superusers can edit users
 */
export function canEditUser(
  currentUser: User | null | undefined,
  _targetUser?: User | null | undefined
): boolean {
  return isSuperuser(currentUser);
}

/**
 * Can user delete a specific user?
 * Only superusers can delete users
 */
export function canDeleteUser(user: User | null | undefined): boolean {
  return isSuperuser(user);
}
