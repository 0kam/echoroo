<script lang="ts">
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { localizeHref, getLocale } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import {
    fetchDetectionRuns,
    createDetectionRun,
    retryDetectionRun,
    cancelDetectionRun,
  } from '$lib/api/detection-runs';
  import type { DetectionRun } from '$lib/types/detection';

  interface Props {
    projectId: string;
    datasetId: string;
  }

  let { projectId, datasetId }: Props = $props();

  const queryClient = useQueryClient();

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
  // This avoids the derived_references_self error caused by referencing runsQuery inside its own options.
  $effect(() => {
    const run = latestRun;
    refetchInterval = run && (run.status === 'pending' || run.status === 'running') ? 10000 : false;
  });

  let mutationError = $state<string | null>(null);

  const createMut = createMutation({
    mutationFn: () => createDetectionRun(projectId, datasetId),
    onSuccess: () => {
      mutationError = null;
      queryClient.invalidateQueries({ queryKey: queryKey });
    },
    onError: (err: Error) => {
      mutationError = err.message || 'Failed to start BirdNET analysis';
    },
  });

  const retryMut = createMutation({
    mutationFn: (runId: string) => retryDetectionRun(projectId, runId),
    onSuccess: () => {
      mutationError = null;
      queryClient.invalidateQueries({ queryKey: queryKey });
    },
    onError: (err: Error) => {
      mutationError = err.message || 'Failed to retry BirdNET analysis';
    },
  });

  const cancelMut = createMutation({
    mutationFn: (runId: string) => cancelDetectionRun(projectId, runId),
    onSuccess: () => {
      mutationError = null;
      queryClient.invalidateQueries({ queryKey: queryKey });
    },
    onError: (err: Error) => {
      mutationError = err.message || 'Failed to cancel BirdNET analysis';
    },
  });

  const isActing = $derived(
    $createMut.isPending || $retryMut.isPending || $cancelMut.isPending
  );
</script>

<div class="rounded-lg border border-gray-200 bg-white p-6">
  <div class="mb-4 flex items-center gap-2">
    <!-- Bird icon (SVG) -->
    <svg
      class="h-5 w-5 text-indigo-500"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.75"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      <!-- Stylized bird silhouette using path -->
      <path d="M2 12c1-4 4-6 7-6 2 0 4 1 5 3 1-1 2.5-1.5 4-1" />
      <path d="M9 12c0 2 1.5 4 3 5s4 1 5-1" />
      <path d="M12 17v3" />
    </svg>
    <h3 class="text-base font-semibold text-gray-900">BirdNET Analysis</h3>
  </div>

  {#if $runsQuery.isLoading}
    <div class="flex items-center gap-2 text-sm text-gray-500">
      <svg class="h-4 w-4 animate-spin text-blue-600" fill="none" viewBox="0 0 24 24">
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
    <!-- No runs yet — invite the user to run BirdNET -->
    <div class="flex items-center justify-between gap-4">
      <p class="text-sm text-gray-500">
        Run BirdNET to automatically detect bird species in the recordings.
      </p>
      <button
        onclick={() => { mutationError = null; $createMut.mutate(); }}
        disabled={isActing}
        class="flex-shrink-0 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {$createMut.isPending ? 'Starting...' : 'Run BirdNET'}
      </button>
    </div>
  {:else if latestRun.status === 'pending' || latestRun.status === 'running'}
    <!-- Processing state -->
    <div class="flex items-center justify-between gap-4">
      <div class="flex items-center gap-3">
        <svg class="h-5 w-5 animate-spin text-blue-600" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
        <div>
          <p class="text-sm font-medium text-blue-700">Analyzing with BirdNET...</p>
          {#if latestRun.status === 'pending'}
            <p class="text-xs text-blue-500">Queued, waiting to start</p>
          {:else}
            <p class="text-xs text-blue-500">Processing recordings</p>
          {/if}
        </div>
      </div>
      <button
        onclick={() => { if (latestRun) $cancelMut.mutate(latestRun.id); }}
        disabled={isActing}
        class="flex-shrink-0 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-600 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
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
            BirdNET complete — {m.common_detections_count({ count: latestRun.annotation_count })} found
          </p>
          {#if latestRun.completed_at}
            <p class="text-xs text-gray-400">
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
          class="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-600 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
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
          <p class="text-sm font-medium text-red-700">BirdNET analysis failed</p>
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
</div>
