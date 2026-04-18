<script lang="ts">
  /**
   * RecentApplications panel.
   *
   * Displays the N most recent DetectionRuns created by applying a custom
   * model to a dataset. Polls every 3 seconds while any run is still
   * queued/running, stops automatically once all have terminated.
   *
   * Also fires toasts on running -> completed / failed transitions so the
   * user is notified of apply job outcomes without having to stay on the
   * page staring at the list.
   *
   * Props:
   * - projectId: Owning project UUID.
   * - modelId: Custom model UUID. The panel fetches runs scoped to this model.
   * - limit: Max runs to display (default 5).
   */

  import { createQuery } from '@tanstack/svelte-query';
  import { listCustomModelDetectionRuns } from '$lib/api/custom-models';
  import { toasts } from '$lib/stores/toast';
  import * as m from '$lib/paraglide/messages';
  import type {
    CustomModelDetectionRun,
    DetectionRunStatus,
  } from '$lib/types/custom-model';

  interface Props {
    projectId: string;
    modelId: string;
    limit?: number;
  }

  const { projectId, modelId, limit = 5 }: Props = $props();

  // ============================================
  // Query with adaptive polling
  // ============================================

  const runsQuery = $derived(
    createQuery({
      queryKey: ['custom-model-detection-runs', projectId, modelId, limit],
      queryFn: () => listCustomModelDetectionRuns(projectId, modelId, limit),
      enabled: !!projectId && !!modelId,
      // Keep polling while at least one run is still in a non-terminal state.
      // TanStack Query passes the current query instance to this callback.
      refetchInterval: (query) => {
        const data = query.state.data as
          | { runs: CustomModelDetectionRun[] }
          | undefined;
        if (!data) return 3000;
        const hasInFlight = data.runs.some(
          (r) => r.status === 'pending' || r.status === 'running'
        );
        return hasInFlight ? 3000 : false;
      },
      refetchOnWindowFocus: false,
    })
  );

  // ============================================
  // Toast on status transitions
  // ============================================

  // Track the previous status of each run id so we can notify on transitions.
  // We rely on `$effect` re-running whenever $runsQuery.data changes.
  let prevStatuses = new Map<string, DetectionRunStatus>();

  $effect(() => {
    const runs = $runsQuery.data?.runs;
    if (!runs) return;

    for (const run of runs) {
      const prev = prevStatuses.get(run.id);
      // Only fire when we've previously seen the run in a non-terminal state
      // and it has now completed/failed. Skip the first snapshot to avoid
      // toasting for historical runs that were already complete on mount.
      if (prev && prev !== run.status) {
        if (
          (prev === 'pending' || prev === 'running') &&
          run.status === 'completed'
        ) {
          toasts.success(
            m.models_apply_success_toast({ count: run.annotation_count })
          );
        } else if (
          (prev === 'pending' || prev === 'running') &&
          run.status === 'failed'
        ) {
          toasts.error(
            m.models_apply_failed_toast({
              error: run.error_message ?? m.models_apply_failed(),
            })
          );
        }
      }
      prevStatuses.set(run.id, run.status);
    }
  });

  // ============================================
  // Error-message expand state
  // ============================================

  let expandedErrors = $state<Record<string, boolean>>({});

  function toggleError(runId: string) {
    expandedErrors[runId] = !expandedErrors[runId];
  }

  // ============================================
  // Formatting helpers
  // ============================================

  /** Format an ISO timestamp as a short relative string. */
  function formatRelative(iso: string): string {
    const then = new Date(iso).getTime();
    const now = Date.now();
    const diffSec = Math.max(0, Math.floor((now - then) / 1000));
    if (diffSec < 5) return m.models_apply_relative_just_now();
    if (diffSec < 60) return m.models_apply_relative_seconds_ago({ n: diffSec });
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return m.models_apply_relative_minutes_ago({ n: diffMin });
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return m.models_apply_relative_hours_ago({ n: diffHr });
    const diffDay = Math.floor(diffHr / 24);
    return m.models_apply_relative_days_ago({ n: diffDay });
  }

  function statusLabel(status: DetectionRunStatus): string {
    switch (status) {
      case 'pending':
        return m.models_apply_pending();
      case 'running':
        return m.models_apply_running();
      case 'completed':
        return m.models_apply_completed();
      case 'failed':
        return m.models_apply_failed();
    }
  }

  function statusClasses(status: DetectionRunStatus): string {
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
</script>

<div class="rounded-xl border border-card bg-surface-card p-5 shadow-sm">
  <h2 class="mb-4 text-base font-semibold text-stone-800 dark:text-stone-200">
    {m.models_recent_applications()}
  </h2>

  {#if $runsQuery.isLoading}
    <div class="flex items-center gap-2 text-sm text-stone-400">
      <svg
        class="h-4 w-4 animate-spin"
        fill="none"
        viewBox="0 0 24 24"
        aria-hidden="true"
      >
        <circle
          class="opacity-25"
          cx="12"
          cy="12"
          r="10"
          stroke="currentColor"
          stroke-width="4"
        ></circle>
        <path
          class="opacity-75"
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
        ></path>
      </svg>
      {m.nav_loading()}
    </div>
  {:else if $runsQuery.isError}
    <p class="text-sm text-danger">{m.models_recent_applications_error()}</p>
  {:else if $runsQuery.data && $runsQuery.data.runs.length === 0}
    <p class="text-sm text-stone-500">{m.models_recent_applications_empty()}</p>
  {:else if $runsQuery.data}
    <ul class="divide-y divide-stone-100 dark:divide-stone-800">
      {#each $runsQuery.data.runs as run (run.id)}
        <li class="py-3 first:pt-0 last:pb-0">
          <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
            <!-- Status badge -->
            <span
              class="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium {statusClasses(
                run.status
              )}"
            >
              {#if run.status === 'running' || run.status === 'pending'}
                <svg
                  class="h-3 w-3 animate-spin"
                  fill="none"
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                >
                  <circle
                    class="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    stroke-width="4"
                  ></circle>
                  <path
                    class="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                  ></path>
                </svg>
              {/if}
              {statusLabel(run.status)}
            </span>

            <!-- Dataset name -->
            <span
              class="min-w-0 flex-1 truncate text-sm font-medium text-stone-800 dark:text-stone-200"
              title={run.dataset_name ?? ''}
            >
              {run.dataset_name ?? run.dataset_id ?? '—'}
            </span>

            <!-- Annotation count (completed only) -->
            {#if run.status === 'completed'}
              <span class="text-xs font-mono text-stone-500">
                {m.models_apply_annotations_count({
                  count: run.annotation_count,
                })}
              </span>
            {/if}

            <!-- Relative time -->
            <span class="text-xs text-stone-400" title={run.created_at}>
              {formatRelative(run.created_at)}
            </span>
          </div>

          <!-- Failure message (collapsible) -->
          {#if run.status === 'failed' && run.error_message}
            <div class="mt-2">
              <button
                type="button"
                class="text-xs text-danger underline-offset-2 hover:underline"
                onclick={() => toggleError(run.id)}
              >
                {expandedErrors[run.id]
                  ? m.models_apply_hide_error()
                  : m.models_apply_show_error()}
              </button>
              {#if expandedErrors[run.id]}
                <pre
                  class="mt-1 max-h-40 overflow-auto whitespace-pre-wrap rounded-lg border border-danger/30 bg-danger-light p-2 text-xs text-danger">{run.error_message}</pre>
              {/if}
            </div>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</div>
