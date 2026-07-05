/**
 * Shared presentational formatters for the custom-models views.
 *
 * Extracted from the models page so the list/detail sub-components can share
 * the exact status-label, status-class, and value-formatting behaviour.
 */

import * as m from '$lib/paraglide/messages';
import { getCustomModelStatusClass, getCustomModelStatusLabel } from '$lib/utils/statusFormatters';

export function statusLabel(status: string): string {
  return getCustomModelStatusLabel(status, {
    draft: m.models_status_draft,
    training: m.models_status_training,
    trained: m.models_status_trained,
    deployed: m.models_status_deployed,
    failed: m.models_status_failed,
  });
}

export function statusClasses(status: string): string {
  return getCustomModelStatusClass(status);
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return `${mins}m ${secs}s`;
}

export function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}
