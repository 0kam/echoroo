<script lang="ts">
  /**
   * List of evaluation runs for an annotation set.
   *
   * Each row shows:
   *   - run status (pending / running / completed / failed) badge
   *   - number of requested models
   *   - started / completed timestamps + duration
   *   - actions: expand to show dashboard, delete
   *
   * Polls the list every 3s while any pending/running entries exist so the
   * status flips automatically when the worker finishes.
   */
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import * as m from '$lib/paraglide/messages';
  import {
    listEvaluationRuns,
    deleteEvaluationRun,
  } from '$lib/api/annotation-sets';
  import type {
    EvaluationRunListResponse,
    EvaluationRunResponse,
    EvaluationRunStatus,
  } from '$lib/types/annotation-set';
  import EvaluationResultDashboard from './EvaluationResultDashboard.svelte';
  import { toasts } from '$lib/stores/toast';

  interface Props {
    setId: string;
    projectId: string;
  }

  const { setId, projectId }: Props = $props();

  const queryClient = useQueryClient();

  const runsQuery = $derived(
    createQuery({
      queryKey: ['evaluation-runs', setId],
      queryFn: () => listEvaluationRuns(projectId, setId, { limit: 50 }),
      enabled: !!setId,
      refetchOnWindowFocus: false,
      refetchInterval: (query): number | false => {
        const data = query.state.data as EvaluationRunListResponse | undefined;
        if (!data) return false;
        const hasInflight = data.items.some(
          (r) => r.status === 'pending' || r.status === 'running',
        );
        return hasInflight ? 3000 : false;
      },
    }),
  );

  const runs = $derived<EvaluationRunResponse[]>($runsQuery.data?.items ?? []);
  // `isLoading` only covers the very first fetch. While the query is
  // pending / refetching we may have a stale `undefined` data object — in
  // that case we should not prematurely render the empty state.
  const isInitialFetch = $derived(
    $runsQuery.isPending || (!$runsQuery.data && $runsQuery.isFetching),
  );

  // ------------------------------------------------------------
  // Expand / collapse
  // ------------------------------------------------------------

  let expandedId = $state<string | null>(null);

  function toggleExpand(id: string) {
    expandedId = expandedId === id ? null : id;
  }

  // ------------------------------------------------------------
  // Delete
  // ------------------------------------------------------------

  let deletingId = $state<string | null>(null);

  const deleteMutation = createMutation({
    mutationFn: (id: string) => deleteEvaluationRun(projectId, id),
    onSuccess: (_, id) => {
      if (expandedId === id) expandedId = null;
      deletingId = null;
      queryClient.invalidateQueries({ queryKey: ['evaluation-runs', setId] });
      queryClient.removeQueries({ queryKey: ['evaluation-run', id] });
      toasts.success(m.evaluation_run_delete_success());
    },
    onError: () => {
      deletingId = null;
      toasts.error(m.evaluation_run_delete_error());
    },
  });

  function confirmDelete(id: string) {
    if (!confirm(m.evaluation_run_delete_confirm())) return;
    deletingId = id;
    $deleteMutation.mutate(id);
  }

  // ------------------------------------------------------------
  // Formatting
  // ------------------------------------------------------------

  function statusLabel(s: EvaluationRunStatus): string {
    switch (s) {
      case 'pending':
        return m.evaluation_run_status_pending();
      case 'running':
        return m.evaluation_run_status_running();
      case 'completed':
        return m.evaluation_run_status_completed();
      case 'failed':
        return m.evaluation_run_status_failed();
    }
  }

  function statusClass(s: EvaluationRunStatus): string {
    switch (s) {
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

  function formatDate(iso: string | null): string {
    if (!iso) return '—';
    return new Date(iso).toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  function formatDuration(startedAt: string | null, completedAt: string | null): string {
    if (!startedAt || !completedAt) return '—';
    const delta = new Date(completedAt).getTime() - new Date(startedAt).getTime();
    if (delta < 0) return '—';
    const seconds = Math.round(delta / 1000);
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    const remSec = seconds % 60;
    if (minutes < 60) return `${minutes}m ${remSec}s`;
    const hours = Math.floor(minutes / 60);
    const remMin = minutes % 60;
    return `${hours}h ${remMin}m`;
  }
</script>

<div>
  {#if isInitialFetch}
    <p class="text-sm text-stone-400">{m.evaluation_run_list_loading()}</p>
  {:else if $runsQuery.isError && !$runsQuery.data}
    <div class="rounded-lg border border-danger/30 bg-danger-light p-3 text-sm text-danger">
      {m.evaluation_run_list_error()}
    </div>
  {:else if runs.length === 0}
    <p class="rounded-lg bg-stone-50 p-4 text-sm text-stone-500 dark:bg-stone-800/40">
      {m.evaluation_run_list_empty()}
    </p>
  {:else}
    <ul class="space-y-3">
      {#each runs as run (run.id)}
        {@const expanded = expandedId === run.id}
        <li class="rounded-lg border border-stone-200 dark:border-stone-700">
          <div class="flex flex-wrap items-center gap-3 p-3">
            <span
              class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium {statusClass(run.status)}"
            >
              {statusLabel(run.status)}
            </span>
            <span class="text-sm text-stone-700 dark:text-stone-200">
              {m.evaluation_run_models_count({
                count: String(run.requested_model_refs.length),
              })}
            </span>
            <div class="flex-1"></div>
            <div class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-stone-500">
              <span>
                {m.evaluation_run_created_at()}: {formatDate(run.started_at ?? run.created_at)}
              </span>
              {#if run.completed_at}
                <span>
                  {m.evaluation_run_duration()}: {formatDuration(
                    run.started_at,
                    run.completed_at,
                  )}
                </span>
              {/if}
            </div>
            <div class="flex flex-shrink-0 items-center gap-1">
              {#if run.status === 'completed' || run.status === 'failed'}
                <button
                  type="button"
                  class="rounded-lg border border-primary-300 bg-primary-50 px-2.5 py-1 text-xs font-medium text-primary-700 transition-colors hover:bg-primary-100 dark:border-primary-700 dark:bg-primary-900/20 dark:text-primary-300 dark:hover:bg-primary-900/40"
                  onclick={() => toggleExpand(run.id)}
                >
                  {expanded ? m.evaluation_run_hide() : m.evaluation_run_view()}
                </button>
              {/if}
              <button
                type="button"
                class="rounded-lg border border-danger/40 bg-danger-light px-2.5 py-1 text-xs font-medium text-danger transition-colors hover:bg-danger/20 disabled:opacity-50"
                onclick={() => confirmDelete(run.id)}
                disabled={deletingId === run.id}
              >
                {m.evaluation_run_delete()}
              </button>
            </div>
          </div>

          {#if run.status === 'failed' && run.error_message}
            <div
              class="border-t border-danger/30 bg-danger-light px-3 py-2 text-xs text-danger"
            >
              <strong>{m.evaluation_run_error_prefix()}:</strong>
              {run.error_message}
            </div>
          {/if}

          {#if expanded}
            <div class="border-t border-stone-200 bg-stone-50/60 p-4 dark:border-stone-700 dark:bg-stone-800/20">
              <EvaluationResultDashboard
                evaluationRunId={run.id}
                {projectId}
              />
            </div>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</div>
