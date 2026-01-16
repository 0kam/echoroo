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

  $: projectId = $page.params.id as string;

  let showCreateForm = false;
  let datasetToDelete: Dataset | null = null;
  let showDeleteDialog = false;
  let deleteWarningItems: string[] = [];

  // Filter states
  let currentPage = 1;
  let search = '';
  let statusFilter: DatasetStatus | '' = '';
  let visibilityFilter: DatasetVisibility | '' = '';

  // Query for datasets
  $: datasetsQuery = createQuery({
    queryKey: ['datasets', projectId, currentPage, search, statusFilter, visibilityFilter],
    queryFn: () =>
      fetchDatasets(projectId, {
        page: currentPage,
        page_size: 20,
        search: search || undefined,
        status: statusFilter || undefined,
        visibility: visibilityFilter || undefined,
      }),
  });

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

    // Fetch dataset details to get recording and clip counts
    try {
      const datasetDetail = await fetchDataset(projectId, dataset.id);
      const warnings: string[] = [];

      const recordingCount = datasetDetail.processed_files || 0;
      if (recordingCount > 0) {
        warnings.push(`${recordingCount} recording${recordingCount > 1 ? 's' : ''}`);
      }

      // Note: clip count is not directly available, but we can mention clips will be deleted
      if (recordingCount > 0) {
        warnings.push('All associated clips');
      }

      if (warnings.length === 0) {
        warnings.push('All associated data');
      }

      deleteWarningItems = warnings;
      showDeleteDialog = true;
    } catch (error) {
      // If we can't fetch details, show generic warning
      deleteWarningItems = ['All associated recordings and clips'];
      showDeleteDialog = true;
    }
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
    currentPage = 1; // Reset to first page when filters change
  }
</script>

<svelte:head>
  <title>Datasets | Project</title>
</svelte:head>

<div class="datasets-page">
  <header class="page-header">
    <div>
      <h1>Datasets</h1>
      <p>Manage collections of audio recordings</p>
    </div>
    {#if !showCreateForm}
      <button class="btn-primary" on:click={() => (showCreateForm = true)}>
        + New Dataset
      </button>
    {/if}
  </header>

  {#if showCreateForm}
    <div class="create-form-container">
      <h2>Create New Dataset</h2>
      <DatasetForm
        {projectId}
        dataset={null}
        onSubmit={handleCreateSubmit}
        onCancel={() => (showCreateForm = false)}
      />
      {#if $datasetCreateMutation.isError}
        <div class="form-error">
          {$datasetCreateMutation.error?.message || 'Failed to create dataset'}
        </div>
      {/if}
    </div>
  {:else if $datasetsQuery.isLoading}
    <div class="loading">Loading datasets...</div>
  {:else if $datasetsQuery.isError}
    <div class="error">Error loading datasets: {$datasetsQuery.error?.message}</div>
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
      <div class="pagination">
        <button
          class="page-btn"
          on:click={() => (currentPage = Math.max(1, currentPage - 1))}
          disabled={currentPage === 1}
        >
          Previous
        </button>

        <span class="page-info">
          Page {currentPage} of {$datasetsQuery.data.pages}
        </span>

        <button
          class="page-btn"
          on:click={() => (currentPage = Math.min($datasetsQuery.data.pages, currentPage + 1))}
          disabled={currentPage === $datasetsQuery.data.pages}
        >
          Next
        </button>
      </div>
    {/if}

    {#if $datasetsQuery.data.total > 0}
      <div class="pagination-info">
        Showing {$datasetsQuery.data.items.length} of {$datasetsQuery.data.total} datasets
      </div>
    {/if}
  {/if}

  <!-- Delete Confirmation Dialog -->
  <ConfirmDialog
    isOpen={showDeleteDialog}
    title="Delete Dataset"
    message={datasetToDelete ? `Are you sure you want to delete "${datasetToDelete.name}"? This action cannot be undone.` : ''}
    confirmText="Delete Dataset"
    cancelText="Cancel"
    confirmButtonClass="btn-danger"
    onConfirm={confirmDelete}
    onCancel={cancelDelete}
    warningItems={deleteWarningItems}
  />
</div>

<style>
  .datasets-page {
    max-width: 1200px;
    margin: 0 auto;
    padding: 2rem;
  }

  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 2rem;
  }

  .page-header h1 {
    margin: 0 0 0.25rem 0;
    font-size: 1.5rem;
    font-weight: 600;
  }

  .page-header p {
    margin: 0;
    color: #6b7280;
  }

  .create-form-container {
    background: white;
    padding: 1.5rem;
    border-radius: 0.5rem;
    border: 1px solid #e5e7eb;
    margin-bottom: 2rem;
  }

  .create-form-container h2 {
    margin: 0 0 1.5rem 0;
    font-size: 1.125rem;
    font-weight: 600;
  }

  .form-error {
    margin-top: 1rem;
    padding: 0.75rem;
    background: #fef2f2;
    border: 1px solid #fecaca;
    border-radius: 0.375rem;
    color: #dc2626;
    font-size: 0.875rem;
  }

  .loading,
  .error {
    padding: 2rem;
    text-align: center;
    border-radius: 0.5rem;
  }

  .loading {
    background: #f3f4f6;
    color: #6b7280;
  }

  .error {
    background: #fef2f2;
    color: #dc2626;
  }

  .pagination {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 1rem;
    margin-top: 1.5rem;
  }

  .page-btn {
    padding: 0.5rem 1rem;
    background: white;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    cursor: pointer;
  }

  .page-btn:hover:not(:disabled) {
    background: #f9fafb;
  }

  .page-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .page-info {
    font-size: 0.875rem;
    color: #6b7280;
  }

  .pagination-info {
    margin-top: 1rem;
    text-align: center;
    font-size: 0.875rem;
    color: #6b7280;
  }

  .btn-primary {
    padding: 0.625rem 1rem;
    background: #3b82f6;
    color: white;
    border: none;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    font-weight: 500;
    cursor: pointer;
  }

  .btn-primary:hover {
    background: #2563eb;
  }
</style>
