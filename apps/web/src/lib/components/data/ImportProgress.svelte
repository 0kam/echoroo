<script lang="ts">
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { fetchImportStatus, startImport, rescanDataset } from '$lib/api/datasets';
  import type { DatasetStatus } from '$lib/types/data';
  import { getDatasetStatusClass, getDatasetStatusMessage } from '$lib/utils/statusFormatters';
  import * as m from '$lib/paraglide/messages';

  interface Props {
    projectId: string;
    datasetId: string;
    currentStatus: DatasetStatus;
    /**
     * Persisted count of successfully imported recordings (from the
     * dataset object). The import-status poll query below is disabled
     * once `currentStatus` flips to 'completed', so `statusData` is
     * frequently `undefined` at that point. Sourcing the completed
     * banner count from this persisted value avoids showing 0 (see
     * preview-feedback #10).
     */
    importedCount?: number;
  }

  let { projectId, datasetId, currentStatus, importedCount = 0 }: Props = $props();

  const queryClient = useQueryClient();

  const isProcessing = $derived(currentStatus === 'scanning' || currentStatus === 'processing');

  const statusQuery = $derived(
    createQuery({
      queryKey: ['import-status', projectId, datasetId],
      queryFn: () => fetchImportStatus(projectId, datasetId),
      refetchInterval: isProcessing ? 2000 : false,
      enabled: isProcessing,
      // spec/007 Phase 1.5 / AD-3
      meta: { projectId },
    })
  );

  let mutationError = $state<string | null>(null);

  const startImportMutation = createMutation({
    mutationFn: () => startImport(projectId, datasetId),
    meta: { projectId },
    onSuccess: () => {
      mutationError = null;
      queryClient.invalidateQueries({ queryKey: ['dataset', projectId, datasetId] });
      queryClient.invalidateQueries({ queryKey: ['import-status', projectId, datasetId] });
    },
    onError: (err: Error) => {
      mutationError = err.message || 'Failed to start import';
    },
  });

  const rescanMutation = createMutation({
    mutationFn: () => rescanDataset(projectId, datasetId),
    meta: { projectId },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dataset', projectId, datasetId] });
      queryClient.invalidateQueries({ queryKey: ['import-status', projectId, datasetId] });
    },
  });

  const statusData = $derived($statusQuery.data);
  const progressPercent = $derived(statusData?.progress_percent ?? 0);
  const totalFiles = $derived(statusData?.total_files ?? 0);
  const processedFiles = $derived(statusData?.processed_files ?? 0);
  const errorMessage = $derived(statusData?.error ?? null);

</script>

<div class="rounded-lg border border-card bg-surface-card p-6">
  <div class="mb-4 flex items-center justify-between">
    <h3 class="m-0 text-base font-semibold text-stone-900">Import Status</h3>
    <span class="rounded-md px-3 py-1 text-sm font-medium {getDatasetStatusClass(currentStatus)}">
      {getDatasetStatusMessage(currentStatus)}
    </span>
  </div>

  {#if isProcessing}
    <div class="mb-4">
      <div class="mb-1.5 flex justify-between text-sm text-stone-500">
        <span>{processedFiles} / {totalFiles} files processed</span>
        <span>{progressPercent.toFixed(1)}%</span>
      </div>
      <div class="h-2 overflow-hidden rounded-full bg-stone-200">
        <div
          class="h-full bg-primary-600 transition-all duration-300"
          style="width: {progressPercent}%"
        ></div>
      </div>
    </div>
  {/if}

  {#if currentStatus === 'failed' && errorMessage}
    <div class="mb-4 rounded-md border border-danger/20 bg-danger-light p-4">
      <div class="mb-2 flex items-center gap-2">
        <svg class="h-4 w-4 text-danger" viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
        <span class="text-sm font-semibold text-danger">Import Error</span>
      </div>
      <div class="whitespace-pre-wrap break-words font-mono text-sm text-danger">{errorMessage}</div>
    </div>
  {/if}

  {#if currentStatus === 'completed'}
    <div class="mb-4 flex items-center gap-3 rounded-md border border-success/30 bg-success-light p-4">
      <div class="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-success text-lg font-bold text-white">
        ✓
      </div>
      <span class="font-medium text-success">
        {m.import_progress_success({ count: importedCount })}
      </span>
    </div>
  {/if}

  {#if mutationError}
    <div class="mb-4 rounded-md border border-danger/30 bg-danger-light p-4">
      <div class="mb-2 flex items-center gap-2">
        <svg class="h-4 w-4 text-danger" viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
        <span class="text-sm font-semibold text-danger">Import Error</span>
      </div>
      <div class="text-sm text-danger">{mutationError}</div>
    </div>
  {/if}

  <div class="flex gap-3">
    {#if currentStatus === 'pending'}
      <button
        onclick={() => { mutationError = null; $startImportMutation.mutate(); }}
        disabled={$startImportMutation.isPending}
        class="rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
      >
        {$startImportMutation.isPending ? 'Starting...' : 'Start Import'}
      </button>
    {:else if currentStatus === 'completed' || currentStatus === 'failed'}
      <button
        onclick={() => $rescanMutation.mutate()}
        disabled={$rescanMutation.isPending}
        class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {$rescanMutation.isPending ? 'Rescanning...' : 'Rescan Directory'}
      </button>
    {/if}
  </div>
</div>
