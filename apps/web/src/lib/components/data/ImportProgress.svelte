<script lang="ts">
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { fetchImportStatus, startImport, rescanDataset } from '$lib/api/datasets';
  import type { DatasetStatus } from '$lib/types/data';

  interface Props {
    projectId: string;
    datasetId: string;
    currentStatus: DatasetStatus;
  }

  let { projectId, datasetId, currentStatus }: Props = $props();

  const queryClient = useQueryClient();

  const isProcessing = $derived(currentStatus === 'scanning' || currentStatus === 'processing');

  const statusQuery = $derived(
    createQuery({
      queryKey: ['import-status', projectId, datasetId],
      queryFn: () => fetchImportStatus(projectId, datasetId),
      refetchInterval: isProcessing ? 2000 : false,
      enabled: isProcessing,
    })
  );

  let mutationError = $state<string | null>(null);

  const startImportMutation = createMutation({
    mutationFn: () => startImport(projectId, datasetId),
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

  function getStatusMessage(status: DatasetStatus): string {
    switch (status) {
      case 'pending': return 'Ready to start import';
      case 'scanning': return 'Scanning directory for audio files...';
      case 'processing': return 'Processing audio files...';
      case 'completed': return 'Import completed successfully';
      case 'failed': return 'Import failed';
      default: return status;
    }
  }

  function getStatusClasses(status: DatasetStatus): string {
    switch (status) {
      case 'pending': return 'bg-yellow-100 text-yellow-800';
      case 'scanning':
      case 'processing': return 'bg-blue-100 text-blue-800';
      case 'completed': return 'bg-green-100 text-green-800';
      case 'failed': return 'bg-red-100 text-red-800';
      default: return 'bg-gray-100 text-gray-800';
    }
  }
</script>

<div class="rounded-lg border border-gray-200 bg-white p-6">
  <div class="mb-4 flex items-center justify-between">
    <h3 class="m-0 text-base font-semibold text-gray-900">Import Status</h3>
    <span class="rounded-md px-3 py-1 text-sm font-medium {getStatusClasses(currentStatus)}">
      {getStatusMessage(currentStatus)}
    </span>
  </div>

  {#if isProcessing}
    <div class="mb-4">
      <div class="mb-1.5 flex justify-between text-sm text-gray-500">
        <span>{processedFiles} / {totalFiles} files processed</span>
        <span>{progressPercent.toFixed(1)}%</span>
      </div>
      <div class="h-2 overflow-hidden rounded-full bg-gray-200">
        <div
          class="h-full bg-blue-600 transition-all duration-300"
          style="width: {progressPercent}%"
        ></div>
      </div>
    </div>
  {/if}

  {#if currentStatus === 'failed' && errorMessage}
    <div class="mb-4 rounded-md border border-red-200 bg-red-50 p-4">
      <div class="mb-2 flex items-center gap-2">
        <svg class="h-4 w-4 text-red-500" viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
        <span class="text-sm font-semibold text-red-700">Import Error</span>
      </div>
      <div class="whitespace-pre-wrap break-words font-mono text-sm text-red-600">{errorMessage}</div>
    </div>
  {/if}

  {#if currentStatus === 'completed'}
    <div class="mb-4 flex items-center gap-3 rounded-md border border-green-200 bg-green-50 p-4">
      <div class="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-green-600 text-lg font-bold text-white">
        ✓
      </div>
      <span class="font-medium text-green-800">
        Successfully imported {totalFiles} audio file{totalFiles !== 1 ? 's' : ''}
      </span>
    </div>
  {/if}

  {#if mutationError}
    <div class="mb-4 rounded-md border border-red-200 bg-red-50 p-4">
      <div class="mb-2 flex items-center gap-2">
        <svg class="h-4 w-4 text-red-500" viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
        <span class="text-sm font-semibold text-red-700">Import Error</span>
      </div>
      <div class="text-sm text-red-600">{mutationError}</div>
    </div>
  {/if}

  <div class="flex gap-3">
    {#if currentStatus === 'pending'}
      <button
        onclick={() => { mutationError = null; $startImportMutation.mutate(); }}
        disabled={$startImportMutation.isPending}
        class="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {$startImportMutation.isPending ? 'Starting...' : 'Start Import'}
      </button>
    {:else if currentStatus === 'completed' || currentStatus === 'failed'}
      <button
        onclick={() => $rescanMutation.mutate()}
        disabled={$rescanMutation.isPending}
        class="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {$rescanMutation.isPending ? 'Rescanning...' : 'Rescan Directory'}
      </button>
    {/if}
  </div>
</div>
