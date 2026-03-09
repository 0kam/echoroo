<script lang="ts">
  /**
   * Detection export dialog for configuring and triggering exports.
   * Supports CSV export with status filtering and ML Dataset export as ZIP.
   * Allows selecting which detection run to export from.
   */

  import type { DetectionRun, DetectionStatus } from '$lib/types/detection';
  import { fetchDetectionRuns } from '$lib/api/detection-runs';
  import { exportDetectionsCSV, exportMLDataset } from '$lib/api/detection-export';
  import * as m from '$lib/paraglide/messages';

  // Props
  let {
    projectId,
    isOpen = false,
    initialFormat = 'csv' as 'csv' | 'ml-dataset',
    detectionRunId = undefined,
    onClose,
  }: {
    projectId: string;
    isOpen: boolean;
    initialFormat?: 'csv' | 'ml-dataset';
    detectionRunId?: string | undefined;
    onClose: () => void;
  } = $props();

  let format = $state<'csv' | 'ml-dataset'>('csv');
  let statusFilter = $state<DetectionStatus | ''>('');
  let isExporting = $state(false);
  let errorMessage = $state('');
  let selectedRunId = $state<string | undefined>(undefined);
  let completedRuns = $state<DetectionRun[]>([]);
  let isLoadingRuns = $state(false);

  /** Format a detection run for display in the dropdown. */
  function formatRunLabel(run: DetectionRun): string {
    const dateStr = run.completed_at
      ? new Date(run.completed_at).toLocaleString()
      : new Date(run.created_at).toLocaleString();
    const version = run.model_version.replace(/^v/, '');
    return `${run.model_name} v${version} - ${dateStr} (${run.annotation_count} detections)`;
  }

  /** Load completed detection runs when dialog opens. */
  async function loadRuns(): Promise<void> {
    isLoadingRuns = true;
    try {
      const result = await fetchDetectionRuns(projectId);
      completedRuns = result.items.filter((r) => r.status === 'completed');
    } catch {
      completedRuns = [];
    } finally {
      isLoadingRuns = false;
    }
  }

  // Reset state when dialog opens, and sync format with initialFormat prop
  $effect(() => {
    if (isOpen) {
      format = initialFormat;
      statusFilter = '';
      errorMessage = '';
      selectedRunId = detectionRunId;
      loadRuns();
    }
  });

  async function handleExport() {
    isExporting = true;
    errorMessage = '';
    try {
      if (format === 'csv') {
        await exportDetectionsCSV(projectId, {
          status: statusFilter || undefined,
          detection_run_id: selectedRunId,
        });
      } else {
        await exportMLDataset(projectId, {
          detection_run_id: selectedRunId,
        });
      }
      onClose();
    } catch (err) {
      errorMessage = err instanceof Error ? err.message : 'Export failed';
    } finally {
      isExporting = false;
    }
  }

  function handleBackdropClick(event: MouseEvent) {
    if (event.target === event.currentTarget) {
      onClose();
    }
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      onClose();
    }
  }
</script>

{#if isOpen}
  <!-- Backdrop -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
    onclick={handleBackdropClick}
    onkeydown={handleKeydown}
    role="presentation"
  >
    <!-- Dialog panel -->
    <div
      class="w-full max-w-md rounded-lg border border-card bg-surface-card shadow-xl"
      role="dialog"
      aria-modal="true"
      aria-labelledby="export-dialog-title"
    >
      <!-- Header -->
      <div class="flex items-center justify-between border-b border-stone-200 px-6 py-4">
        <h2 id="export-dialog-title" class="text-base font-semibold text-stone-900">
          {m.detection_export_title()}
        </h2>
        <button
          type="button"
          onclick={onClose}
          class="rounded-md p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-600"
          aria-label="Close dialog"
        >
          <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <!-- Body -->
      <div class="px-6 py-5 space-y-5">
        <!-- Run selection -->
        <div>
          <label for="run-select" class="mb-1.5 block text-sm font-medium text-stone-700">
            {m.detection_export_run_label()}
          </label>
          {#if isLoadingRuns}
            <div class="flex items-center gap-2 rounded-md border border-stone-200 bg-stone-50 px-3 py-2 text-sm text-stone-400">
              <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              <span>Loading...</span>
            </div>
          {:else}
            <select
              id="run-select"
              bind:value={selectedRunId}
              class="w-full rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-sm text-stone-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
            >
              <option value={undefined}>{m.detection_export_run_all()}</option>
              {#each completedRuns as run (run.id)}
                <option value={run.id}>{formatRunLabel(run)}</option>
              {/each}
            </select>
          {/if}
        </div>

        <!-- Format selection -->
        <div>
          <p class="mb-3 text-sm font-medium text-stone-700">{m.detection_export_format_label()}</p>
          <div class="grid grid-cols-2 gap-3">
            <button
              type="button"
              onclick={() => { format = 'csv'; }}
              class="flex flex-col items-start rounded-lg border p-3 text-left transition-colors {format === 'csv'
                ? 'border-primary-500 bg-primary-50'
                : 'border-stone-200 bg-surface-card hover:border-stone-300 hover:bg-stone-50'}"
            >
              <div class="mb-1.5 flex h-8 w-8 items-center justify-center rounded-md {format === 'csv' ? 'bg-primary-100' : 'bg-stone-100'}">
                <svg class="h-4 w-4 {format === 'csv' ? 'text-primary-600' : 'text-stone-500'}" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
              </div>
              <span class="text-sm font-medium {format === 'csv' ? 'text-primary-700' : 'text-stone-700'}">
                {m.detection_export_csv_name()}
              </span>
              <span class="mt-0.5 text-xs {format === 'csv' ? 'text-primary-500' : 'text-stone-400'}">
                {m.detection_export_csv_desc()}
              </span>
            </button>

            <button
              type="button"
              onclick={() => { format = 'ml-dataset'; }}
              class="flex flex-col items-start rounded-lg border p-3 text-left transition-colors {format === 'ml-dataset'
                ? 'border-primary-500 bg-primary-50'
                : 'border-stone-200 bg-surface-card hover:border-stone-300 hover:bg-stone-50'}"
            >
              <div class="mb-1.5 flex h-8 w-8 items-center justify-center rounded-md {format === 'ml-dataset' ? 'bg-primary-100' : 'bg-stone-100'}">
                <svg class="h-4 w-4 {format === 'ml-dataset' ? 'text-primary-600' : 'text-stone-500'}" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
              </div>
              <span class="text-sm font-medium {format === 'ml-dataset' ? 'text-primary-700' : 'text-stone-700'}">
                {m.detection_export_ml_name()}
              </span>
              <span class="mt-0.5 text-xs {format === 'ml-dataset' ? 'text-primary-500' : 'text-stone-400'}">
                {m.detection_export_ml_desc()}
              </span>
            </button>
          </div>
        </div>

        <!-- Status filter (CSV only) -->
        {#if format === 'csv'}
          <div>
            <label for="status-filter" class="mb-1.5 block text-sm font-medium text-stone-700">
              {m.detection_export_status_filter_label()}
            </label>
            <select
              id="status-filter"
              bind:value={statusFilter}
              class="w-full rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-sm text-stone-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
            >
              <option value="">{m.detection_filter_all_statuses()}</option>
              <option value="unreviewed">{m.detection_filter_unreviewed()}</option>
              <option value="confirmed">{m.detection_filter_confirmed()}</option>
              <option value="rejected">{m.detection_filter_rejected()}</option>
            </select>
          </div>
        {/if}

        <!-- Format details -->
        <div class="rounded-md border border-stone-100 bg-stone-50 px-4 py-3">
          <p class="mb-1.5 text-xs font-medium uppercase tracking-wide text-stone-400">{m.detection_export_includes_label()}</p>
          {#if format === 'csv'}
            <ul class="flex flex-wrap gap-1.5">
              {#each ['recording_filename', 'start_time / end_time', 'species, confidence', 'source, model_name', 'verified, verified_by'] as field}
                <li class="rounded-full bg-surface-card border border-stone-200 px-2 py-0.5 text-xs text-stone-600">
                  {field}
                </li>
              {/each}
            </ul>
          {:else}
            <ul class="flex flex-wrap gap-1.5">
              {#each ['Audio clips (.wav)', 'annotations.csv', 'metadata.json', 'README.txt'] as item}
                <li class="rounded-full bg-surface-card border border-stone-200 px-2 py-0.5 text-xs text-stone-600">
                  {item}
                </li>
              {/each}
            </ul>
          {/if}
        </div>

        <!-- Error message -->
        {#if errorMessage}
          <div class="rounded-md border border-red-200 bg-red-50 px-4 py-3">
            <p class="text-sm text-red-700">{errorMessage}</p>
          </div>
        {/if}
      </div>

      <!-- Footer -->
      <div class="flex items-center justify-end gap-3 border-t border-stone-200 px-6 py-4">
        <button
          type="button"
          onclick={onClose}
          disabled={isExporting}
          class="rounded-md border border-stone-200 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {m.detection_export_cancel()}
        </button>
        <button
          type="button"
          onclick={handleExport}
          disabled={isExporting}
          class="flex items-center gap-2 rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {#if isExporting}
            <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            {m.detection_export_exporting()}
          {:else}
            <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
            </svg>
            {format === 'csv' ? m.detection_export_csv_button() : m.detection_export_zip_button()}
          {/if}
        </button>
      </div>
    </div>
  </div>
{/if}
