<script lang="ts">
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { fetchImportStatus, startImport, rescanDataset } from '$lib/api/datasets';
  import type { DatasetStatus } from '$lib/types/data';

  export let projectId: string;
  export let datasetId: string;
  export let currentStatus: DatasetStatus;

  const queryClient = useQueryClient();

  // Poll for status when processing
  $: isProcessing = currentStatus === 'scanning' || currentStatus === 'processing';

  const statusQuery = createQuery({
    queryKey: ['import-status', projectId, datasetId],
    queryFn: () => fetchImportStatus(projectId, datasetId),
    refetchInterval: isProcessing ? 2000 : false, // Poll every 2s while processing
    enabled: isProcessing,
  });

  const startImportMutation = createMutation({
    mutationFn: () => startImport(projectId, datasetId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dataset', projectId, datasetId] });
      queryClient.invalidateQueries({ queryKey: ['import-status', projectId, datasetId] });
    },
  });

  const rescanMutation = createMutation({
    mutationFn: () => rescanDataset(projectId, datasetId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dataset', projectId, datasetId] });
      queryClient.invalidateQueries({ queryKey: ['import-status', projectId, datasetId] });
    },
  });

  function handleStartImport() {
    $startImportMutation.mutate();
  }

  function handleRescan() {
    $rescanMutation.mutate();
  }

  function getStatusMessage(status: DatasetStatus): string {
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

  $: statusData = $statusQuery.data;
  $: progressPercent = statusData?.progress_percent ?? 0;
  $: totalFiles = statusData?.total_files ?? 0;
  $: processedFiles = statusData?.processed_files ?? 0;
  $: errorMessage = statusData?.error ?? null;
</script>

<div class="import-progress">
  <div class="status-header">
    <h3>Import Status</h3>
    <div class="status-badge {currentStatus}">
      {getStatusMessage(currentStatus)}
    </div>
  </div>

  {#if isProcessing}
    <div class="progress-section">
      <div class="progress-info">
        <span>{processedFiles} / {totalFiles} files processed</span>
        <span>{progressPercent.toFixed(1)}%</span>
      </div>
      <div class="progress-bar">
        <div class="progress-fill" style="width: {progressPercent}%"></div>
      </div>
    </div>
  {/if}

  {#if currentStatus === 'failed' && errorMessage}
    <div class="error-section">
      <div class="error-header">
        <span class="error-icon">⚠️</span>
        <span class="error-title">Import Error</span>
      </div>
      <div class="error-message">{errorMessage}</div>
    </div>
  {/if}

  {#if currentStatus === 'completed'}
    <div class="success-section">
      <div class="success-icon">✓</div>
      <div class="success-message">
        Successfully imported {totalFiles} audio file{totalFiles !== 1 ? 's' : ''}
      </div>
    </div>
  {/if}

  <div class="actions">
    {#if currentStatus === 'pending'}
      <button
        class="btn-primary"
        on:click={handleStartImport}
        disabled={$startImportMutation.isPending}
      >
        {$startImportMutation.isPending ? 'Starting...' : 'Start Import'}
      </button>
    {:else if currentStatus === 'completed' || currentStatus === 'failed'}
      <button class="btn-secondary" on:click={handleRescan} disabled={$rescanMutation.isPending}>
        {$rescanMutation.isPending ? 'Rescanning...' : 'Rescan Directory'}
      </button>
    {/if}
  </div>
</div>

<style>
  .import-progress {
    padding: 1.5rem;
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 0.5rem;
  }

  .status-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1.5rem;
  }

  .status-header h3 {
    margin: 0;
    font-size: 1rem;
    font-weight: 600;
    color: #111827;
  }

  .status-badge {
    padding: 0.375rem 0.75rem;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    font-weight: 500;
  }

  .status-badge.pending {
    background: #fef3c7;
    color: #92400e;
  }

  .status-badge.scanning,
  .status-badge.processing {
    background: #dbeafe;
    color: #1e40af;
  }

  .status-badge.completed {
    background: #d1fae5;
    color: #065f46;
  }

  .status-badge.failed {
    background: #fee2e2;
    color: #991b1b;
  }

  .progress-section {
    margin-bottom: 1.5rem;
  }

  .progress-info {
    display: flex;
    justify-content: space-between;
    margin-bottom: 0.5rem;
    font-size: 0.875rem;
    color: #6b7280;
  }

  .progress-bar {
    height: 0.5rem;
    background: #e5e7eb;
    border-radius: 0.25rem;
    overflow: hidden;
  }

  .progress-fill {
    height: 100%;
    background: #3b82f6;
    transition: width 0.3s ease;
  }

  .error-section {
    padding: 1rem;
    background: #fef2f2;
    border: 1px solid #fecaca;
    border-radius: 0.375rem;
    margin-bottom: 1.5rem;
  }

  .error-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.5rem;
  }

  .error-icon {
    font-size: 1.25rem;
  }

  .error-title {
    font-weight: 600;
    color: #991b1b;
  }

  .error-message {
    color: #dc2626;
    font-size: 0.875rem;
    font-family: monospace;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .success-section {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 1rem;
    background: #f0fdf4;
    border: 1px solid #bbf7d0;
    border-radius: 0.375rem;
    margin-bottom: 1.5rem;
  }

  .success-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 2rem;
    height: 2rem;
    background: #16a34a;
    color: white;
    border-radius: 50%;
    font-weight: bold;
    font-size: 1.25rem;
  }

  .success-message {
    color: #065f46;
    font-weight: 500;
  }

  .actions {
    display: flex;
    gap: 0.75rem;
  }

  .btn-primary,
  .btn-secondary {
    padding: 0.625rem 1.25rem;
    font-size: 0.875rem;
    font-weight: 500;
    border-radius: 0.375rem;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .btn-primary {
    background: #3b82f6;
    color: white;
    border: none;
  }

  .btn-primary:hover:not(:disabled) {
    background: #2563eb;
  }

  .btn-primary:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .btn-secondary {
    background: white;
    color: #374151;
    border: 1px solid #d1d5db;
  }

  .btn-secondary:hover:not(:disabled) {
    background: #f9fafb;
  }

  .btn-secondary:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
