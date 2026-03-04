<script lang="ts">
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { fetchDataset, updateDataset, deleteDataset } from '$lib/api/datasets';
  import type { DatasetUpdate } from '$lib/types/data';
  import DatasetForm from '$lib/components/data/DatasetForm.svelte';
  import DatasetStatistics from '$lib/components/data/DatasetStatistics.svelte';
  import ImportProgress from '$lib/components/data/ImportProgress.svelte';
  import FileUpload from '$lib/components/data/FileUpload.svelte';
  import ExportDialog from '$lib/components/data/ExportDialog.svelte';
  import RecordingList from '$lib/components/data/RecordingList.svelte';
  import DeleteConfirmDialog from '$lib/components/ui/DeleteConfirmDialog.svelte';
  import BirdnetStatus from '$lib/components/data/BirdnetStatus.svelte';

  const queryClient = useQueryClient();

  const projectId = $derived($page.params.id as string);
  const datasetId = $derived($page.params.datasetId as string);

  const datasetQuery = $derived(
    createQuery({
      queryKey: ['dataset', projectId, datasetId],
      queryFn: () => fetchDataset(projectId, datasetId),
    })
  );

  let showEditModal = $state(false);
  let showDeleteConfirm = $state(false);
  let showExportDialog = $state(false);

  const updateMutation = createMutation({
    mutationFn: (data: DatasetUpdate) => updateDataset(projectId, datasetId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dataset', projectId, datasetId] });
      queryClient.invalidateQueries({ queryKey: ['datasets', projectId] });
      showEditModal = false;
    },
  });

  const deleteMutation = createMutation({
    mutationFn: () => deleteDataset(projectId, datasetId),
    onSuccess: () => {
      goto(`/projects/${projectId}/datasets`);
    },
  });

  async function handleUpdateSubmit(data: DatasetUpdate) {
    await $updateMutation.mutateAsync(data);
  }

  function confirmDelete() {
    $deleteMutation.mutate();
    showDeleteConfirm = false;
  }

  function formatDateTime(dateStr: string): string {
    return new Date(dateStr).toLocaleString();
  }

  const deleteWarnings = $derived(
    $datasetQuery.data
      ? [
          `${$datasetQuery.data.recording_count || 0} recording(s)`,
          'All associated clips and annotations',
        ]
      : []
  );

  function getStatusClasses(status: string): string {
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

<svelte:head>
  <title>{$datasetQuery.data?.name || 'Dataset'} | Project</title>
</svelte:head>

<div class="mx-auto max-w-5xl space-y-6 px-6 py-8">
  {#if $datasetQuery.isLoading}
    <div class="flex items-center justify-center py-12 text-sm text-gray-500">
      <svg class="mr-2 h-5 w-5 animate-spin text-blue-600" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      Loading dataset...
    </div>
  {:else if $datasetQuery.isError}
    <div class="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
      Error: {$datasetQuery.error?.message}
    </div>
  {:else if $datasetQuery.data}
    {@const dataset = $datasetQuery.data}

    <!-- Header -->
    <div>
      <nav class="mb-2 flex items-center gap-2 text-sm text-gray-500">
        <a href="/projects/{projectId}" class="hover:text-gray-900">Project</a>
        <span>/</span>
        <a href="/projects/{projectId}/datasets" class="hover:text-gray-900">Datasets</a>
        <span>/</span>
        <span class="font-medium text-gray-900">{dataset.name}</span>
      </nav>

      <div class="flex items-start justify-between gap-4">
        <div>
          <h1 class="text-2xl font-bold text-gray-900">{dataset.name}</h1>
          {#if dataset.description}
            <p class="mt-1 text-sm text-gray-500">{dataset.description}</p>
          {/if}
        </div>
        <div class="flex flex-shrink-0 gap-2">
          {#if dataset.status === 'completed'}
            <button
              onclick={() => (showExportDialog = true)}
              class="flex items-center gap-2 rounded-md bg-emerald-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-700"
            >
              <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" stroke-width="2" />
                <polyline points="7 10 12 15 17 10" stroke-width="2" />
                <line x1="12" y1="15" x2="12" y2="3" stroke-width="2" />
              </svg>
              Export
            </button>
          {/if}
          <button
            onclick={() => (showEditModal = true)}
            class="rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50"
          >
            Edit
          </button>
          <button
            onclick={() => (showDeleteConfirm = true)}
            class="rounded-md border border-red-200 bg-white px-3 py-2 text-sm font-medium text-red-600 transition-colors hover:bg-red-50"
          >
            Delete
          </button>
        </div>
      </div>
    </div>

    <!-- Dataset info card -->
    <div class="rounded-lg border border-gray-200 bg-white p-6">
      <h2 class="mb-4 text-sm font-semibold uppercase tracking-wider text-gray-500">Dataset Information</h2>
      <div class="grid grid-cols-2 gap-4 sm:grid-cols-3">
        <div class="flex flex-col gap-1">
          <span class="text-xs font-medium uppercase tracking-wider text-gray-400">Site</span>
          <span class="text-sm text-gray-900">
            {#if dataset.site}
              <a href="/projects/{projectId}/sites/{dataset.site.id}" class="text-blue-600 hover:underline">
                {dataset.site.name}
              </a>
            {:else}
              <span class="text-gray-400">N/A</span>
            {/if}
          </span>
        </div>

        <div class="flex flex-col gap-1">
          <span class="text-xs font-medium uppercase tracking-wider text-gray-400">Status</span>
          <span class="inline-flex w-fit items-center rounded px-2 py-0.5 text-xs font-medium capitalize {getStatusClasses(dataset.status)}">
            {dataset.status}
          </span>
        </div>

        <div class="flex flex-col gap-1">
          <span class="text-xs font-medium uppercase tracking-wider text-gray-400">Visibility</span>
          <span class="text-sm text-gray-900 capitalize">{dataset.visibility}</span>
        </div>

        {#if dataset.recorder}
          <div class="flex flex-col gap-1">
            <span class="text-xs font-medium uppercase tracking-wider text-gray-400">Recorder</span>
            <span class="text-sm text-gray-900">{dataset.recorder.manufacturer} {dataset.recorder.recorder_name}</span>
          </div>
        {/if}

        {#if dataset.license}
          <div class="flex flex-col gap-1">
            <span class="text-xs font-medium uppercase tracking-wider text-gray-400">License</span>
            <span class="text-sm text-gray-900">{dataset.license.name} ({dataset.license.short_name})</span>
          </div>
        {/if}

        {#if dataset.doi}
          <div class="flex flex-col gap-1">
            <span class="text-xs font-medium uppercase tracking-wider text-gray-400">DOI</span>
            <a href="https://doi.org/{dataset.doi}" target="_blank" rel="noopener noreferrer" class="text-sm text-blue-600 hover:underline">
              {dataset.doi}
            </a>
          </div>
        {/if}

        {#if dataset.gain !== null}
          <div class="flex flex-col gap-1">
            <span class="text-xs font-medium uppercase tracking-wider text-gray-400">Gain</span>
            <span class="text-sm text-gray-900">{dataset.gain} dB</span>
          </div>
        {/if}

        <div class="flex flex-col gap-1">
          <span class="text-xs font-medium uppercase tracking-wider text-gray-400">Created</span>
          <span class="text-sm text-gray-900">{formatDateTime(dataset.created_at)}</span>
        </div>

        {#if dataset.created_by}
          <div class="flex flex-col gap-1">
            <span class="text-xs font-medium uppercase tracking-wider text-gray-400">Created By</span>
            <span class="text-sm text-gray-900">{dataset.created_by.display_name || dataset.created_by.username}</span>
          </div>
        {/if}
      </div>

      {#if dataset.note}
        <div class="mt-4 border-t border-gray-100 pt-4">
          <span class="mb-1 block text-xs font-medium uppercase tracking-wider text-gray-400">Note</span>
          <p class="whitespace-pre-wrap text-sm text-gray-700">{dataset.note}</p>
        </div>
      {/if}
    </div>

    <!-- Import Progress (not shown when pending - FileUpload handles the full flow) -->
    {#if dataset.status !== 'pending'}
      <ImportProgress {projectId} {datasetId} currentStatus={dataset.status} />
    {/if}

    <!-- File Upload (available when dataset is pending or completed) -->
    {#if dataset.status === 'pending' || dataset.status === 'completed'}
      <FileUpload
        {projectId}
        {datasetId}
        onComplete={() => {
          queryClient.invalidateQueries({ queryKey: ['dataset', projectId, datasetId] });
        }}
      />
    {/if}

    <!-- BirdNET ML Detection Status (only if dataset import is complete) -->
    {#if dataset.status === 'completed'}
      <BirdnetStatus {projectId} {datasetId} />
    {/if}

    <!-- Statistics (only if completed) -->
    {#if dataset.status === 'completed'}
      <DatasetStatistics {projectId} {datasetId} />
    {/if}

    <!-- Recordings list (show when recordings exist) -->
    {#if dataset.recording_count > 0}
      <div class="rounded-lg border border-gray-200 bg-white p-6">
        <div class="mb-4">
          <h3 class="text-base font-semibold text-gray-900">Recordings</h3>
          <p class="mt-0.5 text-sm text-gray-500">{dataset.recording_count} recording(s) in this dataset</p>
        </div>
        <RecordingList
          {projectId}
          {datasetId}
          onSelect={(recordingId) => goto(`/projects/${projectId}/recordings/${recordingId}`)}
        />
      </div>
    {/if}
  {/if}
</div>

<!-- Edit Modal -->
{#if showEditModal && $datasetQuery.data}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    onclick={() => (showEditModal = false)}
    role="dialog"
    aria-modal="true"
    aria-labelledby="edit-dataset-title"
    tabindex="-1"
  >
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
    <div
      class="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-lg bg-white"
      onclick={(e) => e.stopPropagation()}
      role="document"
    >
      <div class="flex items-center justify-between border-b border-gray-200 px-6 py-4">
        <h3 id="edit-dataset-title" class="m-0 text-lg font-semibold text-gray-900">Edit Dataset</h3>
        <button
          onclick={() => (showEditModal = false)}
          class="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
          aria-label="Close"
        >
          <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <line x1="18" y1="6" x2="6" y2="18" stroke-width="2" />
            <line x1="6" y1="6" x2="18" y2="18" stroke-width="2" />
          </svg>
        </button>
      </div>
      <div class="p-6">
        <DatasetForm
          {projectId}
          dataset={$datasetQuery.data}
          onSubmit={handleUpdateSubmit}
          onCancel={() => (showEditModal = false)}
        />
      </div>
      {#if $updateMutation.isError}
        <div class="mx-6 mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">
          {$updateMutation.error?.message || 'Failed to update dataset'}
        </div>
      {/if}
    </div>
  </div>
{/if}

<!-- Delete Confirmation Dialog -->
<DeleteConfirmDialog
  isOpen={showDeleteConfirm}
  title="Delete Dataset"
  message={`Are you sure you want to delete "${$datasetQuery.data?.name ?? 'this dataset'}"? This action cannot be undone.`}
  warnings={deleteWarnings}
  confirmText="Delete Dataset"
  isDeleting={$deleteMutation.isPending}
  onConfirm={confirmDelete}
  onCancel={() => (showDeleteConfirm = false)}
/>

<!-- Export Dialog -->
{#if $datasetQuery.data}
  <ExportDialog
    {projectId}
    {datasetId}
    datasetName={$datasetQuery.data.name}
    isOpen={showExportDialog}
    onClose={() => (showExportDialog = false)}
  />
{/if}
