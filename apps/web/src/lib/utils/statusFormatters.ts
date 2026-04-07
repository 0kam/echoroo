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

import type { DetectionStatus } from '$lib/types/detection';
import type { DatasetStatus } from '$lib/types/data';
import type { AnnotationTaskStatus, ReviewStatus } from '$lib/types/annotation';
import type { CustomModelStatus } from '$lib/types/custom-model';

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
// Annotation clip review status
// Covers: ReviewStatus ('unreviewed' | 'approved' | 'rejected') from annotation.ts
// ============================================

/**
 * Human-readable label for an annotation clip review status.
 *
 * Pass the paraglide message functions when calling from a Svelte component.
 */
export function getAnnotationReviewStatusLabel(
  status: ReviewStatus | string,
  t?: {
    approved: () => string;
    rejected: () => string;
    unreviewed: () => string;
  },
): string {
  switch (status) {
    case 'approved':
      return t?.approved() ?? 'Approved';
    case 'rejected':
      return t?.rejected() ?? 'Rejected';
    default:
      return t?.unreviewed() ?? 'Unreviewed';
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
// Annotation task status
// Covers: AnnotationTaskStatus ('pending' | 'in_progress' | 'completed' | 'review_pending')
// ============================================

/**
 * CSS class string for an annotation-task status badge.
 * Returns a BEM-style compound class (e.g. "badge badge-pending") that
 * maps to existing CSS in the annotation page stylesheet.
 */
export function getAnnotationTaskStatusClass(status: AnnotationTaskStatus): string {
  switch (status) {
    case 'pending':
      return 'badge badge-pending';
    case 'in_progress':
      return 'badge badge-in-progress';
    case 'completed':
      return 'badge badge-completed';
    case 'review_pending':
      return 'badge badge-review-pending';
    default:
      return 'badge';
  }
}

/**
 * Human-readable label for an annotation task status.
 *
 * Pass the paraglide message functions when calling from a Svelte component.
 */
export function getAnnotationTaskStatusLabel(
  status: AnnotationTaskStatus,
  t?: {
    pending: () => string;
    in_progress: () => string;
    completed: () => string;
    review_pending: () => string;
  },
): string {
  switch (status) {
    case 'pending':
      return t?.pending() ?? 'Pending';
    case 'in_progress':
      return t?.in_progress() ?? 'In Progress';
    case 'completed':
      return t?.completed() ?? 'Completed';
    case 'review_pending':
      return t?.review_pending() ?? 'Review Pending';
    default:
      return status;
  }
}
