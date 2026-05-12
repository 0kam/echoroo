<script lang="ts">
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { fetchDatasets, createDataset, deleteDataset, fetchDataset } from '$lib/api/datasets';
  import { projectsApi } from '$lib/api/projects';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import type { Dataset, DatasetCreate, DatasetUpdate, DatasetStatus, DatasetVisibility } from '$lib/types/data';
  import DatasetList from '$lib/components/data/DatasetList.svelte';
  import DatasetForm from '$lib/components/data/DatasetForm.svelte';
  import ConfirmDialog from '$lib/components/ui/ConfirmDialog.svelte';
  import { can } from '$lib/utils/permissions';
  import { usePermissionContext } from '$lib/stores/permissionContext';

  const queryClient = useQueryClient();

  const projectId = $derived($page.params.id as string);

  // spec/007 XFL-3 fix: gate "+ New Dataset" + delete on manage_dataset_admin
  // (§ 4A vocabulary glossary rule 2 — dataset RESOURCE management is
  // admin/owner-only). Backend already enforces this via DATASET_CREATE_ACTION
  // / DATASET_DELETE_ACTION (Phase 2A.6 wiring); this gate suppresses the
  // button so members/viewers don't see a control whose backend will 403.
  const projectQuery = $derived(
    createQuery({
      queryKey: ['project', projectId],
      queryFn: () => projectsApi.get(projectId),
      meta: { projectId },
    })
  );
  const projectCtx = $derived(
    usePermissionContext({
      projectQuery,
      routeParams: { invitationToken: null },
    })
  );
  const canCreateDataset = $derived(can('manage_dataset_admin', $projectCtx));

  let showCreateForm = $state(false);
  let datasetToDelete = $state<Dataset | null>(null);
  let showDeleteDialog = $state(false);
  let deleteWarningItems = $state<string[]>([]);
  let deleteError = $state<string | null>(null);

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
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['datasets', projectId] });
      showCreateForm = false;
      goto(localizeHref(`/projects/${projectId}/datasets/${created.id}`));
    },
  });

  // Mutation for deleting a dataset
  const deleteMutation = createMutation({
    mutationFn: (datasetId: string) => deleteDataset(projectId, datasetId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['datasets', projectId] });
      datasetToDelete = null;
      showDeleteDialog = false;
      deleteError = null;
    },
    onError: (error: Error) => {
      deleteError = error.message || 'Failed to delete dataset';
    },
  });

  function handleDatasetSelect(dataset: Dataset) {
    goto(localizeHref(`/projects/${projectId}/datasets/${dataset.id}`));
  }

  async function handleDeleteClick(dataset: Dataset) {
    datasetToDelete = dataset;
    deleteError = null;

    try {
      const datasetDetail = await fetchDataset(projectId, dataset.id);
      const warnings: string[] = [];

      const recordingCount = datasetDetail.processed_files || 0;
      if (recordingCount > 0) {
        warnings.push(m.dataset_detail_delete_warnings_recordings({ count: recordingCount }));
        warnings.push(m.dataset_detail_delete_warnings_annotations());
      }

      if (warnings.length === 0) {
        warnings.push(m.dataset_detail_delete_warnings_all());
      }

      deleteWarningItems = warnings;
    } catch {
      deleteWarningItems = [m.dataset_detail_delete_warnings_fallback()];
    }

    showDeleteDialog = true;
  }

  async function confirmDelete() {
    if (datasetToDelete) {
      deleteError = null;
      try {
        await $deleteMutation.mutateAsync(datasetToDelete.id);
        // onSuccess handles closing the dialog and clearing state
      } catch {
        // Error is displayed via deleteError set in onError handler
        // Keep the dialog open so the user can see the error
      }
    }
  }

  function cancelDelete() {
    showDeleteDialog = false;
    datasetToDelete = null;
    deleteWarningItems = [];
    deleteError = null;
  }

  async function handleCreateSubmit(data: DatasetCreate | DatasetUpdate) {
    await $datasetCreateMutation.mutateAsync(data as DatasetCreate);
  }

  function handleFilterChange() {
    currentPage = 1;
  }
</script>

<svelte:head>
  <title>{m.dataset_list_page_title()}</title>
</svelte:head>

<div class="mx-auto max-w-6xl px-6 py-8">
  <header class="mb-6 flex items-start justify-between">
    <div>
      <nav class="mb-2 flex items-center gap-2 text-sm text-stone-500">
        <a href={localizeHref(`/projects/${projectId}`)} class="hover:text-stone-900">{m.dataset_list_breadcrumb_project()}</a>
        <span>/</span>
        <span class="font-medium text-stone-900">{m.dataset_list_breadcrumb_datasets()}</span>
      </nav>
      <h1 class="text-2xl font-bold text-stone-900">{m.dataset_list_heading()}</h1>
      <p class="mt-1 text-sm text-stone-500">{m.dataset_list_description()}</p>
    </div>
    {#if !showCreateForm && canCreateDataset}
      <button
        onclick={() => (showCreateForm = true)}
        class="flex items-center gap-2 rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
      >
        <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <line x1="12" y1="5" x2="12" y2="19" stroke-width="2" />
          <line x1="5" y1="12" x2="19" y2="12" stroke-width="2" />
        </svg>
        {m.dataset_list_new_button()}
      </button>
    {/if}
  </header>

  {#if showCreateForm}
    <div class="mb-6 rounded-lg border border-card bg-surface-card p-6">
      <div class="mb-4 flex items-center justify-between">
        <h2 class="text-lg font-semibold text-stone-900">{m.dataset_list_create_heading()}</h2>
        <button
          onclick={() => (showCreateForm = false)}
          class="rounded p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-600"
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
        <div class="mt-4 rounded-md border border-danger/20 bg-danger-light px-3 py-2 text-sm text-danger">
          {$datasetCreateMutation.error?.message || 'Failed to create dataset'}
        </div>
      {/if}
    </div>
  {/if}

  {#if $datasetsQuery.isLoading}
    <div class="flex items-center justify-center py-12 text-sm text-stone-500">
      <svg class="mr-2 h-5 w-5 animate-spin text-primary-600" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      {m.dataset_list_loading()}
    </div>
  {:else if $datasetsQuery.isError}
    <div class="rounded-md border border-danger/20 bg-danger-light px-4 py-3 text-sm text-danger">
      {m.dataset_list_error_load({ message: $datasetsQuery.error?.message ?? '' })}
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
          class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {m.dataset_list_previous()}
        </button>
        <span class="text-sm text-stone-500">
          {m.dataset_list_page_info({ page: currentPage, total: $datasetsQuery.data.pages })}
        </span>
        <button
          onclick={() => (currentPage = Math.min($datasetsQuery.data!.pages, currentPage + 1))}
          disabled={currentPage === $datasetsQuery.data.pages}
          class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {m.dataset_list_next()}
        </button>
      </div>
    {/if}

    {#if $datasetsQuery.data.total > 0}
      <p class="mt-3 text-center text-sm text-stone-400">
        {m.dataset_list_showing({ showing: $datasetsQuery.data.items.length, total: $datasetsQuery.data.total })}
      </p>
    {/if}
  {/if}
</div>

<!-- Delete Confirmation Dialog -->
<ConfirmDialog
  isOpen={showDeleteDialog}
  title={m.dataset_list_delete_title()}
  message={datasetToDelete ? m.dataset_list_delete_message({ name: datasetToDelete.name }) : ''}
  confirmText={m.dataset_list_delete_confirm()}
  cancelText={m.dataset_list_delete_cancel()}
  isDanger={true}
  onConfirm={confirmDelete}
  onCancel={cancelDelete}
  warningItems={deleteWarningItems}
  errorMessage={deleteError}
/>
