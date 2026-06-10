/**
 * Shared status formatting utilities.
 *
 * Centralises label and CSS-class derivation for every domain status type
 * used across the frontend so that each mapping lives in exactly one place.
 *
 * Label functions that correspond to i18n keys accept an optional `t`
 * (translate) callback so callers can supply their paraglide-generated
 * message functions.  When no translator is provided the English fallback
 * string is returned, which keeps the helpers usable outside Svelte components
 * (e.g. in unit tests or plain TypeScript modules).
 */

import type {
  DetectionStatus,
  ConsensusStatus,
  DetectionRunStatus,
} from '$lib/types/detection';
import type { DatasetStatus, UploadSessionStatus } from '$lib/types/data';
import type { CustomModelStatus } from '$lib/types/custom-model';
import type {
  AnnotationSetStatus,
  AnnotationSegmentStatus,
  EvaluationRunStatus,
} from '$lib/types/annotation-set';
import type {
  ProjectStatus,
  ProjectTrustedStatus,
  BulkInvitationResultItem,
} from '$lib/types';

/** Status union for a member/trusted invitation lifecycle. */
type InvitationLifecycleStatus =
  | 'pending'
  | 'accepted'
  | 'declined'
  | 'revoked'
  | 'expired';

/** Status union for a single row of a bulk invitation result. */
type BulkInvitationStatus = BulkInvitationResultItem['status'];

// ============================================
// Review / Detection status
// Covers: DetectionStatus ('unreviewed' | 'confirmed' | 'rejected')
//         SearchResultStatus (same union, defined in search.ts)
// ============================================

/**
 * CSS class string for a review-status badge (border-included variant).
 * Used by ReviewActions components for the inline status pill.
 */
export function getReviewStatusBadgeClass(status: DetectionStatus): string {
  switch (status) {
    case 'confirmed':
      return 'bg-green-100 text-green-800 border-green-200';
    case 'rejected':
      return 'bg-red-100 text-red-800 border-red-200';
    default:
      return 'bg-stone-100 text-stone-600 border-stone-200';
  }
}

/**
 * CSS class string for the card border that surrounds a ReviewCard.
 * Adds a coloured ring when a decision has been made.
 */
export function getReviewCardBorderClass(
  status: DetectionStatus,
  isSelected = false,
): string {
  if (status === 'confirmed') return 'border-green-400 ring-1 ring-green-300';
  if (status === 'rejected') return 'border-red-400 ring-1 ring-red-300';
  return isSelected
    ? 'border-primary-400 ring-1 ring-primary-300'
    : 'border-stone-200';
}

/**
 * Human-readable label for a review status.
 *
 * Pass the three paraglide message functions when calling from a Svelte
 * component so that locale changes are reflected reactively.
 */
export function getReviewStatusLabel(
  status: DetectionStatus,
  t?: {
    confirmed: () => string;
    rejected: () => string;
    unreviewed: () => string;
  },
): string {
  switch (status) {
    case 'confirmed':
      return t?.confirmed() ?? 'Confirmed';
    case 'rejected':
      return t?.rejected() ?? 'Rejected';
    default:
      return t?.unreviewed() ?? 'Unreviewed';
  }
}

// ============================================
// Vote consensus status
// Covers: ConsensusStatus ('needs_votes' | 'agreed' | 'disputed' | 'rejected')
// ============================================

/**
 * CSS class string for a consensus-status badge.
 * Used on detection cards to show the team's voting outcome.
 */
export function getConsensusStatusBadgeClass(consensus: ConsensusStatus): string {
  switch (consensus) {
    case 'agreed':
      return 'bg-green-100 text-green-800 border-green-200';
    case 'disputed':
      return 'bg-orange-100 text-orange-800 border-orange-200';
    case 'rejected':
      return 'bg-red-100 text-red-800 border-red-200';
    default:
      return 'bg-stone-100 text-stone-600 border-stone-200';
  }
}

/**
 * Human-readable label for a consensus status.
 */
export function getConsensusStatusLabel(
  consensus: ConsensusStatus,
  t?: {
    needs_votes: () => string;
    agreed: () => string;
    disputed: () => string;
    rejected: () => string;
  },
): string {
  switch (consensus) {
    case 'agreed':
      return t?.agreed() ?? 'Agreed';
    case 'disputed':
      return t?.disputed() ?? 'Disputed';
    case 'rejected':
      return t?.rejected() ?? 'Rejected';
    default:
      return t?.needs_votes() ?? 'Needs Votes';
  }
}

// ============================================
// Dataset status
// Covers: DatasetStatus ('pending' | 'scanning' | 'processing' | 'completed' | 'failed')
// ============================================

/**
 * CSS class string for a dataset-status badge.
 */
export function getDatasetStatusClass(status: DatasetStatus): string {
  switch (status) {
    case 'pending':
      return 'bg-yellow-100 text-yellow-800';
    case 'scanning':
    case 'processing':
      return 'bg-primary-100 text-primary-800';
    case 'completed':
      return 'bg-green-100 text-green-800';
    case 'failed':
      return 'bg-red-100 text-red-800';
    default:
      return 'bg-stone-100 text-stone-800';
  }
}

/**
 * Short human-readable label for a dataset status (English fallback).
 * Components that support i18n should supply their own translated strings.
 */
export function getDatasetStatusLabel(status: DatasetStatus): string {
  switch (status) {
    case 'pending':
      return 'Pending';
    case 'scanning':
      return 'Scanning';
    case 'processing':
      return 'Processing';
    case 'completed':
      return 'Ready';
    case 'failed':
      return 'Failed';
    default:
      return status;
  }
}

/**
 * Descriptive message shown inside the ImportProgress component.
 */
export function getDatasetStatusMessage(status: DatasetStatus): string {
  switch (status) {
    case 'pending':
      return 'Ready to start import';
    case 'scanning':
      return 'Scanning directory for audio files...';
    case 'processing':
      return 'Processing audio files...';
    case 'completed':
      return 'Import completed successfully';
    case 'failed':
      return 'Import failed';
    default:
      return status;
  }
}

// ============================================
// Search-session status
// Covers: string literals 'completed' | 'running' | 'pending' | 'failed'
// (No dedicated type in search.ts at the time of writing.)
// ============================================

/**
 * Tailwind background class for the small status indicator dot shown in
 * the SearchSessionList sidebar.
 */
export function getSearchSessionStatusDotClass(status: string): string {
  switch (status) {
    case 'completed':
      return 'bg-emerald-500';
    case 'running':
    case 'pending':
      return 'bg-amber-500';
    case 'failed':
      return 'bg-red-500';
    default:
      return 'bg-stone-300';
  }
}

/**
 * Human-readable label for a search-session status.
 *
 * The SearchSessionList sidebar uses inline English strings because the
 * paraglide keys were not compiled there, while SearchSessionDetail uses
 * compiled keys.  The optional `t` translator allows both use cases.
 */
export function getSearchSessionStatusLabel(
  status: string,
  t?: {
    completed: () => string;
    running: () => string;
    pending: () => string;
    failed: () => string;
  },
): string {
  switch (status) {
    case 'completed':
      return t?.completed() ?? 'Completed';
    case 'running':
      return t?.running() ?? 'Running';
    case 'pending':
      return t?.pending() ?? 'Pending';
    case 'failed':
      return t?.failed() ?? 'Failed';
    default:
      return status;
  }
}

/**
 * Returns true for statuses that should render with an animated pulse.
 */
export function isSearchSessionStatusAnimated(status: string): boolean {
  return status === 'running' || status === 'pending';
}

/**
 * Text colour class for the search-session status shown in the detail panel.
 */
export function getSearchSessionStatusTextClass(status: string): string {
  switch (status) {
    case 'completed':
      return 'text-emerald-600 dark:text-emerald-400';
    case 'running':
      return 'text-blue-600 dark:text-blue-400';
    case 'failed':
      return 'text-red-600 dark:text-red-400';
    case 'pending':
      return 'text-amber-600 dark:text-amber-400';
    default:
      return 'text-stone-500';
  }
}

/**
 * Background class for the dot indicator shown in the search-session detail panel.
 * Note: 'running' includes an animate-pulse modifier unlike the sidebar dot.
 */
export function getSearchSessionStatusDetailDotClass(status: string): string {
  switch (status) {
    case 'completed':
      return 'bg-emerald-500';
    case 'running':
      return 'bg-blue-500 animate-pulse';
    case 'failed':
      return 'bg-red-500';
    case 'pending':
      return 'bg-amber-500';
    default:
      return 'bg-stone-400';
  }
}

// ============================================
// Custom model status
// Covers: CustomModelStatus ('draft' | 'training' | 'trained' | 'deployed' | 'failed' | 'archived')
// ============================================

/**
 * CSS class string for a custom-model status badge.
 */
export function getCustomModelStatusClass(status: CustomModelStatus | string): string {
  switch (status) {
    case 'draft':
      return 'bg-stone-100 text-stone-600 dark:bg-stone-800 dark:text-stone-400';
    case 'training':
      return 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400';
    case 'trained':
      return 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400';
    case 'deployed':
      return 'bg-primary-100 text-primary-700 dark:bg-primary-900/30 dark:text-primary-400';
    case 'failed':
      return 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400';
    default:
      return 'bg-stone-100 text-stone-600';
  }
}

/**
 * Human-readable label for a custom model status.
 *
 * Pass the paraglide message functions when calling from a Svelte component.
 */
export function getCustomModelStatusLabel(
  status: CustomModelStatus | string,
  t?: {
    draft: () => string;
    training: () => string;
    trained: () => string;
    deployed: () => string;
    failed: () => string;
  },
): string {
  switch (status) {
    case 'draft':
      return t?.draft() ?? 'Draft';
    case 'training':
      return t?.training() ?? 'Training';
    case 'trained':
      return t?.trained() ?? 'Trained';
    case 'deployed':
      return t?.deployed() ?? 'Deployed';
    case 'failed':
      return t?.failed() ?? 'Failed';
    default:
      return status;
  }
}

// ============================================
// Detection run status (apply / detection jobs)
// Covers: DetectionRunStatus ('pending' | 'running' | 'completed' | 'failed')
// ============================================

/**
 * CSS class string for a detection-run status badge.
 */
export function getDetectionRunStatusClass(status: DetectionRunStatus): string {
  switch (status) {
    case 'pending':
      return 'bg-stone-100 text-stone-600 dark:bg-stone-800 dark:text-stone-300';
    case 'running':
      return 'bg-info/10 text-info';
    case 'completed':
      return 'bg-success-light text-success';
    case 'failed':
      return 'bg-danger-light text-danger';
  }
}

/**
 * Human-readable label for a detection-run status.
 *
 * Pass the paraglide message functions when calling from a Svelte component.
 */
export function getDetectionRunStatusLabel(
  status: DetectionRunStatus,
  t?: {
    pending: () => string;
    running: () => string;
    completed: () => string;
    failed: () => string;
  },
): string {
  switch (status) {
    case 'pending':
      return t?.pending() ?? 'Pending';
    case 'running':
      return t?.running() ?? 'Running';
    case 'completed':
      return t?.completed() ?? 'Completed';
    case 'failed':
      return t?.failed() ?? 'Failed';
  }
}

// ============================================
// Evaluation run status (cross-model evaluation jobs)
// Covers: EvaluationRunStatus ('pending' | 'running' | 'completed' | 'failed')
// ============================================

/**
 * CSS class string for an evaluation-run status badge.
 */
export function getEvaluationRunStatusClass(status: EvaluationRunStatus): string {
  switch (status) {
    case 'pending':
      return 'bg-stone-100 text-stone-700 dark:bg-stone-800 dark:text-stone-300';
    case 'running':
      return 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300';
    case 'completed':
      return 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300';
    case 'failed':
      return 'bg-danger-light text-danger';
  }
}

/**
 * Human-readable label for an evaluation-run status.
 *
 * Pass the paraglide message functions when calling from a Svelte component.
 */
export function getEvaluationRunStatusLabel(
  status: EvaluationRunStatus,
  t?: {
    pending: () => string;
    running: () => string;
    completed: () => string;
    failed: () => string;
  },
): string {
  switch (status) {
    case 'pending':
      return t?.pending() ?? 'Pending';
    case 'running':
      return t?.running() ?? 'Running';
    case 'completed':
      return t?.completed() ?? 'Completed';
    case 'failed':
      return t?.failed() ?? 'Failed';
  }
}

// ============================================
// Annotation set status
// Covers: AnnotationSetStatus ('sampling' | 'ready' | 'in_progress' | 'completed')
// ============================================

/**
 * CSS class string for an annotation-set status badge.
 */
export function getAnnotationSetStatusClass(status: AnnotationSetStatus): string {
  switch (status) {
    case 'sampling':
      return 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300';
    case 'ready':
      return 'bg-primary-100 text-primary-800 dark:bg-primary-900/30 dark:text-primary-300';
    case 'in_progress':
      return 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300';
    case 'completed':
      return 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300';
  }
}

/**
 * Human-readable label for an annotation-set status.
 *
 * Pass the paraglide message functions when calling from a Svelte component.
 */
export function getAnnotationSetStatusLabel(
  status: AnnotationSetStatus,
  t?: {
    sampling: () => string;
    ready: () => string;
    in_progress: () => string;
    completed: () => string;
  },
): string {
  switch (status) {
    case 'sampling':
      return t?.sampling() ?? 'Sampling';
    case 'ready':
      return t?.ready() ?? 'Ready';
    case 'in_progress':
      return t?.in_progress() ?? 'In progress';
    case 'completed':
      return t?.completed() ?? 'Completed';
  }
}

// ============================================
// Annotation segment status
// Covers: AnnotationSegmentStatus ('unannotated' | 'annotated' | 'skipped')
// ============================================

/**
 * CSS class string for an annotation-segment status badge.
 */
export function getAnnotationSegmentStatusClass(status: AnnotationSegmentStatus): string {
  switch (status) {
    case 'annotated':
      return 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300';
    case 'skipped':
      return 'bg-stone-200 text-stone-700 dark:bg-stone-700 dark:text-stone-300';
    default:
      return 'bg-stone-100 text-stone-600 dark:bg-stone-800 dark:text-stone-400';
  }
}

/**
 * Human-readable label for an annotation-segment status.
 *
 * Pass the paraglide message functions when calling from a Svelte component.
 */
export function getAnnotationSegmentStatusLabel(
  status: AnnotationSegmentStatus,
  t?: {
    unannotated: () => string;
    annotated: () => string;
    skipped: () => string;
  },
): string {
  switch (status) {
    case 'unannotated':
      return t?.unannotated() ?? 'Unannotated';
    case 'annotated':
      return t?.annotated() ?? 'Annotated';
    case 'skipped':
      return t?.skipped() ?? 'Skipped';
  }
}

// ============================================
// Upload session status
// Covers: UploadSessionStatus
//   ('issued' | 'uploaded' | 'validating' | 'validated'
//    | 'importing' | 'imported' | 'failed')
// ============================================

/**
 * CSS class string for an upload-session status badge.
 */
export function getUploadSessionStatusClass(status: UploadSessionStatus): string {
  switch (status) {
    case 'issued':
    case 'uploaded':
      return 'bg-warning-light text-warning';
    case 'validating':
    case 'importing':
      return 'bg-primary-100 text-primary-800 dark:bg-primary-900/30 dark:text-primary-400';
    case 'validated':
    case 'imported':
      return 'bg-success-light text-success';
    case 'failed':
      return 'bg-danger-light text-danger';
    default:
      return 'bg-stone-100 text-stone-800 dark:bg-stone-700 dark:text-stone-300';
  }
}

/**
 * Human-readable label for an upload-session status.
 *
 * Pass the paraglide message functions when calling from a Svelte component.
 */
export function getUploadSessionStatusLabel(
  status: UploadSessionStatus,
  t?: {
    issued: () => string;
    uploaded: () => string;
    validating: () => string;
    validated: () => string;
    importing: () => string;
    imported: () => string;
    failed: () => string;
  },
): string {
  switch (status) {
    case 'issued':
      return t?.issued() ?? 'Issued';
    case 'uploaded':
      return t?.uploaded() ?? 'Uploaded';
    case 'validating':
      return t?.validating() ?? 'Validating';
    case 'validated':
      return t?.validated() ?? 'Validated';
    case 'importing':
      return t?.importing() ?? 'Importing';
    case 'imported':
      return t?.imported() ?? 'Imported';
    case 'failed':
      return t?.failed() ?? 'Failed';
    default:
      return status;
  }
}

// ============================================
// Project status (public project lifecycle)
// Covers: ProjectStatus ('active' | 'dormant' | 'archived')
// ============================================

/**
 * Human-readable label for a project lifecycle status.
 *
 * Pass the paraglide message functions when calling from a Svelte component.
 */
export function getProjectStatusLabel(
  status: ProjectStatus,
  t?: {
    active: () => string;
    dormant: () => string;
    archived: () => string;
  },
): string {
  switch (status) {
    case 'active':
      return t?.active() ?? 'Active';
    case 'dormant':
      return t?.dormant() ?? 'Dormant';
    default:
      return t?.archived() ?? 'Archived';
  }
}

// ============================================
// Project trusted-user status
// Covers: ProjectTrustedStatus ('active' | 'expired' | 'revoked')
// ============================================

/**
 * CSS class string for a trusted-user status badge.
 */
export function getProjectTrustedStatusClass(status: ProjectTrustedStatus): string {
  switch (status) {
    case 'active':
      return 'bg-success-light text-success';
    case 'expired':
      return 'bg-warning-light text-warning';
    case 'revoked':
      return 'bg-stone-100 text-stone-700';
  }
}

/**
 * Human-readable label for a trusted-user status.
 *
 * Pass the paraglide message functions when calling from a Svelte component.
 */
export function getProjectTrustedStatusLabel(
  status: ProjectTrustedStatus,
  t?: {
    active: () => string;
    expired: () => string;
    revoked: () => string;
  },
): string {
  switch (status) {
    case 'active':
      return t?.active() ?? 'Active';
    case 'expired':
      return t?.expired() ?? 'Expired';
    case 'revoked':
      return t?.revoked() ?? 'Revoked';
  }
}

// ============================================
// Invitation lifecycle status
// Covers: 'pending' | 'accepted' | 'declined' | 'revoked' | 'expired'
// (the API returns a free-form string, so unknown values fall through)
// ============================================

/**
 * CSS class string for an invitation lifecycle status badge.
 */
export function getInvitationStatusBadgeClass(status: string): string {
  switch (status) {
    case 'pending':
      return 'bg-info-light text-info';
    case 'accepted':
      return 'bg-success-light text-success';
    case 'expired':
      return 'bg-warning-light text-warning';
    case 'revoked':
    case 'declined':
    default:
      return 'bg-danger-light text-danger';
  }
}

/**
 * Human-readable label for an invitation lifecycle status.
 *
 * Pass the paraglide message functions when calling from a Svelte component.
 * Unknown statuses are returned verbatim.
 */
export function getInvitationStatusLabel(
  status: string,
  t?: {
    pending: () => string;
    accepted: () => string;
    declined: () => string;
    revoked: () => string;
    expired: () => string;
  },
): string {
  switch (status as InvitationLifecycleStatus) {
    case 'pending':
      return t?.pending() ?? 'Pending';
    case 'accepted':
      return t?.accepted() ?? 'Accepted';
    case 'declined':
      return t?.declined() ?? 'Declined';
    case 'revoked':
      return t?.revoked() ?? 'Revoked';
    case 'expired':
      return t?.expired() ?? 'Expired';
    default:
      return status;
  }
}

// ============================================
// Bulk invitation result status
// Covers: BulkInvitationResultItem['status']
//   ('issued' | 'duplicate_pending' | 'already_member'
//    | 'rate_limited' | 'internal_error')
// ============================================

/**
 * CSS class string for a bulk-invitation result status badge.
 */
export function getBulkInvitationStatusBadgeClass(status: BulkInvitationStatus): string {
  switch (status) {
    case 'issued':
      return 'bg-success-light text-success';
    case 'duplicate_pending':
    case 'already_member':
      return 'bg-warning-light text-warning';
    case 'rate_limited':
    case 'internal_error':
    default:
      return 'bg-danger-light text-danger';
  }
}

/**
 * Human-readable label for a bulk-invitation result status.
 *
 * Pass the paraglide message functions when calling from a Svelte component.
 */
export function getBulkInvitationStatusLabel(
  status: BulkInvitationStatus,
  t?: {
    issued: () => string;
    duplicate_pending: () => string;
    already_member: () => string;
    rate_limited: () => string;
    internal_error: () => string;
  },
): string {
  switch (status) {
    case 'issued':
      return t?.issued() ?? 'Issued';
    case 'duplicate_pending':
      return t?.duplicate_pending() ?? 'Already invited';
    case 'already_member':
      return t?.already_member() ?? 'Already a member';
    case 'rate_limited':
      return t?.rate_limited() ?? 'Rate limited';
    case 'internal_error':
    default:
      return t?.internal_error() ?? 'Error';
  }
}
