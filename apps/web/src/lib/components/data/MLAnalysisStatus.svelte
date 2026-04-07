<script lang="ts">
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { localizeHref, getLocale } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import {
    fetchDetectionRuns,
    createDetectionRun,
    retryDetectionRun,
    cancelDetectionRun,
    fetchAvailableModels,
  } from '$lib/api/detection-runs';
  import type { DetectionRun } from '$lib/types/detection';

  interface Props {
    projectId: string;
    datasetId: string;
  }

  let { projectId, datasetId }: Props = $props();

  const queryClient = useQueryClient();

  // Currently selected model name
  let selectedModel = $state('birdnet');

  /** Display label for a model name */
  function modelDisplayName(name: string): string {
    if (name === 'birdnet') return m.ml_analysis_model_birdnet();
    if (name === 'perch') return m.ml_analysis_model_perch();
    return name;
  }

  /** Short description for the selected model */
  const modelDescription = $derived(
    selectedModel === 'birdnet'
      ? m.ml_analysis_model_birdnet_desc()
      : selectedModel === 'perch'
        ? m.ml_analysis_model_perch_desc()
        : ''
  );

  // Fetch available models from the server
  const modelsQuery = createQuery({
    queryKey: ['available-models'],
    queryFn: fetchAvailableModels,
    staleTime: 5 * 60 * 1000,
  });

  const queryKey = $derived(['detection-runs', projectId, datasetId]);

  // Separate state for refetch interval to avoid derived_references_self circular reference.
  // The query is created once; $effect updates refetchInterval reactively after data arrives.
  let refetchInterval = $state<number | false>(false);

  const runsQuery = $derived(
    createQuery({
      queryKey: queryKey,
      queryFn: () => fetchDetectionRuns(projectId, datasetId),
      refetchInterval: refetchInterval,
    })
  );

  // Pick the most recent detection run for this dataset
  const latestRun: DetectionRun | null = $derived(
    ($runsQuery.data && $runsQuery.data.items.length > 0 ? $runsQuery.data.items[0] : null) ?? null
  );

  // Update polling interval reactively based on run status.
  $effect(() => {
    const run = latestRun;
    refetchInterval = run && (run.status === 'pending' || run.status === 'running') ? 10000 : false;
  });

  let mutationError = $state<string | null>(null);

  const createMut = createMutation({
    mutationFn: () => createDetectionRun(projectId, datasetId, selectedModel),
    onSuccess: () => {
      mutationError = null;
      queryClient.invalidateQueries({ queryKey: queryKey });
    },
    onError: (err: Error) => {
      mutationError = err.message || 'Failed to start ML analysis';
    },
  });

  const retryMut = createMutation({
    // Re-run creates a fresh DetectionRun rather than reusing the existing run_id,
    // so each click produces a new record with its own history.
    mutationFn: (_runId: string) => createDetectionRun(projectId, datasetId, selectedModel),
    onSuccess: () => {
      mutationError = null;
      queryClient.invalidateQueries({ queryKey: queryKey });
    },
    onError: (err: Error) => {
      mutationError = err.message || 'Failed to retry ML analysis';
    },
  });

  const cancelMut = createMutation({
    mutationFn: (runId: string) => cancelDetectionRun(projectId, runId),
    onSuccess: () => {
      mutationError = null;
      queryClient.invalidateQueries({ queryKey: queryKey });
    },
    onError: (err: Error) => {
      mutationError = err.message || 'Failed to cancel ML analysis';
    },
  });

  const isActing = $derived(
    $createMut.isPending || $retryMut.isPending || $cancelMut.isPending
  );

  /** Display name for the run's model (from run data or fallback to current selection) */
  function runModelLabel(run: DetectionRun): string {
    return modelDisplayName(run.model_name);
  }
</script>

<div class="rounded-lg border border-card bg-surface-card p-6">
  <div class="mb-4 flex items-center gap-2">
    <!-- Brain/ML icon (SVG) -->
    <svg
      class="h-5 w-5 text-primary-500"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.75"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      <path d="M9.5 2a2.5 2.5 0 0 1 5 0v.5" />
      <path d="M2 9.5a2.5 2.5 0 0 1 0 5H2.5" />
      <path d="M21.5 9.5a2.5 2.5 0 0 1 0 5H21" />
      <path d="M9.5 21.5a2.5 2.5 0 0 1 5 0" />
      <rect x="7" y="7" width="10" height="10" rx="2" />
    </svg>
    <h3 class="text-base font-semibold text-stone-900">{m.ml_analysis_title()}</h3>
  </div>

  {#if $runsQuery.isLoading}
    <div class="flex items-center gap-2 text-sm text-stone-500">
      <svg class="h-4 w-4 animate-spin text-primary-600" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      Loading...
    </div>
  {:else if $runsQuery.isError}
    <div class="text-sm text-red-600">
      Failed to load detection status: {$runsQuery.error?.message}
    </div>
  {:else if !latestRun}
    <!-- No runs yet — show model selector and invite the user to run analysis -->
    <div class="space-y-4">
      <!-- Model selector -->
      <div>
        <label for="model-select" class="mb-1 block text-sm font-medium text-stone-700">
          {m.ml_analysis_select_model()}
        </label>
        <select
          id="model-select"
          bind:value={selectedModel}
          class="block w-full rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-sm text-stone-900 shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
        >
          {#if $modelsQuery.data}
            {#each $modelsQuery.data as model (model)}
              <option value={model}>{modelDisplayName(model)}</option>
            {/each}
          {:else}
            <!-- Fallback options while loading -->
            <option value="birdnet">{m.ml_analysis_model_birdnet()}</option>
            <option value="perch">{m.ml_analysis_model_perch()}</option>
          {/if}
        </select>
        {#if modelDescription}
          <p class="mt-1.5 text-xs text-stone-500">{modelDescription}</p>
        {/if}
      </div>

      <div class="flex items-center justify-between gap-4">
        <p class="text-sm text-stone-500">
          Run ML analysis to automatically detect species in the recordings.
        </p>
        <button
          onclick={() => { mutationError = null; $createMut.mutate(); }}
          disabled={isActing}
          class="flex-shrink-0 rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {$createMut.isPending ? 'Starting...' : m.ml_analysis_run()}
        </button>
      </div>
    </div>
  {:else if latestRun.status === 'pending' || latestRun.status === 'running'}
    <!-- Processing state -->
    <div class="flex items-center justify-between gap-4">
      <div class="flex items-center gap-3">
        <svg class="h-5 w-5 animate-spin text-primary-600" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
        <div>
          <p class="text-sm font-medium text-primary-700">
            {m.ml_analysis_running({ model: runModelLabel(latestRun) })}
          </p>
          {#if latestRun.status === 'pending'}
            <p class="text-xs text-primary-500">Queued, waiting to start</p>
          {:else}
            <p class="text-xs text-primary-500">Processing recordings</p>
          {/if}
        </div>
      </div>
      <button
        onclick={() => { if (latestRun) $cancelMut.mutate(latestRun.id); }}
        disabled={isActing}
        class="flex-shrink-0 rounded-md border border-stone-300 bg-surface-card px-3 py-1.5 text-sm font-medium text-stone-600 transition-colors hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {$cancelMut.isPending ? 'Cancelling...' : 'Cancel'}
      </button>
    </div>
  {:else if latestRun.status === 'completed'}
    <!-- Completed state -->
    <div class="flex items-center justify-between gap-4">
      <div class="flex items-center gap-3">
        <div class="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-green-600">
          <svg class="h-4 w-4 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="20 6 9 17 4 12"></polyline>
          </svg>
        </div>
        <div>
          <p class="text-sm font-medium text-green-800">
            {m.ml_analysis_completed({ model: runModelLabel(latestRun) })} — {m.common_detections_count({ count: latestRun.annotation_count })} found
          </p>
          {#if latestRun.completed_at}
            <p class="text-xs text-stone-400">
              Finished {new Date(latestRun.completed_at).toLocaleString(getLocale())}
            </p>
          {/if}
        </div>
      </div>
      <div class="flex flex-shrink-0 gap-2">
        <a
          href={localizeHref(`/projects/${projectId}/detections?dataset_id=${datasetId}`)}
          class="rounded-md bg-green-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-green-700"
        >
          View Detections
        </a>
        <button
          onclick={() => { if (latestRun) $retryMut.mutate(latestRun.id); }}
          disabled={isActing}
          class="rounded-md border border-stone-300 bg-surface-card px-3 py-1.5 text-sm font-medium text-stone-600 transition-colors hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {$retryMut.isPending ? 'Retrying...' : 'Re-run'}
        </button>
      </div>
    </div>
  {:else if latestRun.status === 'failed'}
    <!-- Failed state -->
    <div class="flex items-start justify-between gap-4">
      <div class="flex items-start gap-3">
        <div class="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-red-100">
          <svg class="h-4 w-4 text-red-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
        </div>
        <div>
          <p class="text-sm font-medium text-red-700">
            {m.ml_analysis_failed({ model: runModelLabel(latestRun) })}
          </p>
          {#if latestRun.error_message}
            <p class="mt-0.5 text-xs text-red-500">{latestRun.error_message}</p>
          {/if}
        </div>
      </div>
      <button
        onclick={() => { if (latestRun) $retryMut.mutate(latestRun.id); }}
        disabled={isActing}
        class="flex-shrink-0 rounded-md bg-red-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {$retryMut.isPending ? 'Retrying...' : 'Retry'}
      </button>
    </div>
  {/if}

  {#if mutationError}
    <div class="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">
      {mutationError}
    </div>
  {/if}

  <!-- Recent runs history -->
  {#if $runsQuery.data && $runsQuery.data.items.length > 1}
    <div class="mt-4 border-t border-stone-100 pt-4">
      <p class="mb-2 text-xs font-medium uppercase tracking-wider text-stone-400">Recent Runs</p>
      <ul class="space-y-1.5">
        {#each $runsQuery.data.items as run (run.id)}
          <li class="flex items-center justify-between gap-2 text-xs text-stone-500">
            <span class="font-medium text-stone-700">{modelDisplayName(run.model_name)}</span>
            <span class={
              run.status === 'completed' ? 'text-green-600' :
              run.status === 'failed' ? 'text-red-500' :
              run.status === 'running' ? 'text-primary-500' :
              'text-stone-400'
            }>
              {run.status === 'completed' ? 'Completed' :
               run.status === 'failed' ? 'Failed' :
               run.status === 'running' ? 'Running...' :
               run.status === 'pending' ? 'Pending' : run.status}
            </span>
            {#if run.completed_at}
              <span class="ml-auto text-stone-400">{new Date(run.completed_at).toLocaleDateString(getLocale())}</span>
            {/if}
          </li>
        {/each}
      </ul>
    </div>
  {/if}
</div>
