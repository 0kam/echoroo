<script lang="ts">
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { fetchDatasets, createDataset, deleteDataset, fetchDataset } from '$lib/api/datasets';
  import type { Dataset, DatasetCreate, DatasetUpdate, DatasetStatus, DatasetVisibility } from '$lib/types/data';
  import DatasetList from '$lib/components/data/DatasetList.svelte';
  import DatasetForm from '$lib/components/data/DatasetForm.svelte';
  import ConfirmDialog from '$lib/components/ui/ConfirmDialog.svelte';

  const queryClient = useQueryClient();

  const projectId = $derived($page.params.id as string);

  let showCreateForm = $state(false);
  let datasetToDelete = $state<Dataset | null>(null);
  let showDeleteDialog = $state(false);
  let deleteWarningItems = $state<string[]>([]);

  // Filter states
  let currentPage = $state(1);
  let search = $state('');
  let statusFilter = $state<DatasetStatus | ''>('');
  let visibilityFilter = $state<DatasetVisibility | ''>('');

  // Query for datasets
  const datasetsQuery = $derived(
    createQuery({
      queryKey: ['datasets', projectId, currentPage, search, statusFilter, visibilityFilter],
      queryFn: () =>
        fetchDatasets(projectId, {
          page: currentPage,
          page_size: 20,
          search: search || undefined,
          status: statusFilter || undefined,
          visibility: visibilityFilter || undefined,
        }),
    })
  );

  // Mutation for creating a dataset
  const datasetCreateMutation = createMutation({
    mutationFn: (data: DatasetCreate) => createDataset(projectId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['datasets', projectId] });
      showCreateForm = false;
    },
  });

  // Mutation for deleting a dataset
  const deleteMutation = createMutation({
    mutationFn: (datasetId: string) => deleteDataset(projectId, datasetId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['datasets', projectId] });
      datasetToDelete = null;
    },
  });

  function handleDatasetSelect(dataset: Dataset) {
    goto(`/projects/${projectId}/datasets/${dataset.id}`);
  }

  async function handleDeleteClick(dataset: Dataset) {
    datasetToDelete = dataset;

    try {
      const datasetDetail = await fetchDataset(projectId, dataset.id);
      const warnings: string[] = [];

      const recordingCount = datasetDetail.processed_files || 0;
      if (recordingCount > 0) {
        warnings.push(`${recordingCount} recording${recordingCount > 1 ? 's' : ''}`);
        warnings.push('All associated clips and annotations');
      }

      if (warnings.length === 0) {
        warnings.push('All associated data');
      }

      deleteWarningItems = warnings;
    } catch {
      deleteWarningItems = ['All associated recordings and clips'];
    }

    showDeleteDialog = true;
  }

  async function confirmDelete() {
    if (datasetToDelete) {
      await $deleteMutation.mutateAsync(datasetToDelete.id);
      showDeleteDialog = false;
      datasetToDelete = null;
    }
  }

  function cancelDelete() {
    showDeleteDialog = false;
    datasetToDelete = null;
    deleteWarningItems = [];
  }

  async function handleCreateSubmit(data: DatasetCreate | DatasetUpdate) {
    await $datasetCreateMutation.mutateAsync(data as DatasetCreate);
  }

  function handleFilterChange() {
    currentPage = 1;
  }
</script>

<svelte:head>
  <title>Datasets | Project</title>
</svelte:head>

<div class="mx-auto max-w-6xl px-6 py-8">
  <header class="mb-6 flex items-start justify-between">
    <div>
      <nav class="mb-2 flex items-center gap-2 text-sm text-gray-500">
        <a href="/projects/{projectId}" class="hover:text-gray-900">Project</a>
        <span>/</span>
        <span class="font-medium text-gray-900">Datasets</span>
      </nav>
      <h1 class="text-2xl font-bold text-gray-900">Datasets</h1>
      <p class="mt-1 text-sm text-gray-500">Manage collections of audio recordings</p>
    </div>
    {#if !showCreateForm}
      <button
        onclick={() => (showCreateForm = true)}
        class="flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
      >
        <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <line x1="12" y1="5" x2="12" y2="19" stroke-width="2" />
          <line x1="5" y1="12" x2="19" y2="12" stroke-width="2" />
        </svg>
        New Dataset
      </button>
    {/if}
  </header>

  {#if showCreateForm}
    <div class="mb-6 rounded-lg border border-gray-200 bg-white p-6">
      <div class="mb-4 flex items-center justify-between">
        <h2 class="text-lg font-semibold text-gray-900">Create New Dataset</h2>
        <button
          onclick={() => (showCreateForm = false)}
          class="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
          aria-label="Close"
        >
          <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <line x1="18" y1="6" x2="6" y2="18" stroke-width="2" />
            <line x1="6" y1="6" x2="18" y2="18" stroke-width="2" />
          </svg>
        </button>
      </div>
      <DatasetForm
        {projectId}
        dataset={null}
        onSubmit={handleCreateSubmit}
        onCancel={() => (showCreateForm = false)}
      />
      {#if $datasetCreateMutation.isError}
        <div class="mt-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">
          {$datasetCreateMutation.error?.message || 'Failed to create dataset'}
        </div>
      {/if}
    </div>
  {/if}

  {#if $datasetsQuery.isLoading}
    <div class="flex items-center justify-center py-12 text-sm text-gray-500">
      <svg class="mr-2 h-5 w-5 animate-spin text-blue-600" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      Loading datasets...
    </div>
  {:else if $datasetsQuery.isError}
    <div class="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
      Error loading datasets: {$datasetsQuery.error?.message}
    </div>
  {:else if $datasetsQuery.data}
    <DatasetList
      datasets={$datasetsQuery.data.items}
      bind:search
      bind:statusFilter
      bind:visibilityFilter
      onFilterChange={handleFilterChange}
      onSelect={handleDatasetSelect}
      onDelete={handleDeleteClick}
    />

    <!-- Pagination -->
    {#if $datasetsQuery.data.pages > 1}
      <div class="mt-4 flex items-center justify-center gap-4">
        <button
          onclick={() => (currentPage = Math.max(1, currentPage - 1))}
          disabled={currentPage === 1}
          class="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Previous
        </button>
        <span class="text-sm text-gray-500">
          Page {currentPage} of {$datasetsQuery.data.pages}
        </span>
        <button
          onclick={() => (currentPage = Math.min($datasetsQuery.data!.pages, currentPage + 1))}
          disabled={currentPage === $datasetsQuery.data.pages}
          class="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Next
        </button>
      </div>
    {/if}

    {#if $datasetsQuery.data.total > 0}
      <p class="mt-3 text-center text-sm text-gray-400">
        Showing {$datasetsQuery.data.items.length} of {$datasetsQuery.data.total} datasets
      </p>
    {/if}
  {/if}
</div>

<!-- Delete Confirmation Dialog -->
<ConfirmDialog
  isOpen={showDeleteDialog}
  title="Delete Dataset"
  message={datasetToDelete ? `Are you sure you want to delete "${datasetToDelete.name}"? This action cannot be undone.` : ''}
  confirmText="Delete Dataset"
  cancelText="Cancel"
  isDanger={true}
  onConfirm={confirmDelete}
  onCancel={cancelDelete}
  warningItems={deleteWarningItems}
/>
