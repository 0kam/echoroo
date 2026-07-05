<script lang="ts">
  /**
   * Sites & Data unified page.
   * Provides a tabbed interface for Sites, Datasets, and Recordings.
   */

  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { fetchSites, createSite, deleteSite, fetchSite } from '$lib/api/sites';
  import { localizeHref } from '$lib/paraglide/runtime';
  import { fetchDatasets, createDataset, deleteDataset, fetchDataset } from '$lib/api/datasets';
  import type { Dataset, DatasetCreate, DatasetStatus, DatasetVisibility, DatasetUpdate, Site, SiteCreate } from '$lib/types/data';
  import SiteList from '$lib/components/data/SiteList.svelte';
  import SiteForm from '$lib/components/data/SiteForm.svelte';
  import DatasetList from '$lib/components/data/DatasetList.svelte';
  import DatasetForm from '$lib/components/data/DatasetForm.svelte';
  import RecordingList from '$lib/components/data/RecordingList.svelte';
  import ConfirmDialog from '$lib/components/ui/ConfirmDialog.svelte';
  import * as m from '$lib/paraglide/messages';

  const queryClient = useQueryClient();

  const projectId = $derived($page.params.id as string);

  type Tab = 'sites' | 'datasets' | 'recordings';
  let activeTab = $state<Tab>('datasets');

  // --- Sites state ---
  let showSiteCreateForm = $state(false);
  let siteToDelete = $state<Site | null>(null);
  let showSiteDeleteDialog = $state(false);
  let siteDeleteWarningItems = $state<string[]>([]);

  // --- Datasets state ---
  let showDatasetCreateForm = $state(false);
  let datasetToDelete = $state<Dataset | null>(null);
  let showDatasetDeleteDialog = $state(false);
  let datasetDeleteWarningItems = $state<string[]>([]);
  let datasetDeleteError = $state<string | null>(null);
  let datasetCurrentPage = $state(1);
  let datasetSearch = $state('');
  let datasetStatusFilter = $state<DatasetStatus | ''>('');
  let datasetVisibilityFilter = $state<DatasetVisibility | ''>('');

  // --- Sites queries ---
  const sitesQuery = $derived(
    createQuery({
      queryKey: ['sites', projectId],
      queryFn: () => fetchSites(projectId),
      enabled: !!projectId,
    })
  );

  const siteCreateMutation = createMutation({
    mutationFn: (data: SiteCreate) => createSite(projectId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sites', projectId] });
      showSiteCreateForm = false;
    },
  });

  const siteDeleteMutation = createMutation({
    mutationFn: (siteId: string) => deleteSite(projectId, siteId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sites', projectId] });
      siteToDelete = null;
    },
  });

  // --- Dataset queries ---
  const datasetsQuery = $derived(
    createQuery({
      queryKey: ['datasets', projectId, datasetCurrentPage, datasetSearch, datasetStatusFilter, datasetVisibilityFilter],
      queryFn: () =>
        fetchDatasets(projectId, {
          page: datasetCurrentPage,
          page_size: 20,
          search: datasetSearch || undefined,
          status: datasetStatusFilter || undefined,
          visibility: datasetVisibilityFilter || undefined,
        }),
    })
  );

  const datasetCreateMutation = createMutation({
    mutationFn: (data: DatasetCreate) => createDataset(projectId, data),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['datasets', projectId] });
      showDatasetCreateForm = false;
      goto(localizeHref(`/projects/${projectId}/datasets/${created.id}`));
    },
  });

  const datasetDeleteMutation = createMutation({
    mutationFn: (datasetId: string) => deleteDataset(projectId, datasetId),
    // Surfaces its own inline error via `datasetDeleteError`; opt out of
    // the global generic error toast to avoid double feedback.
    meta: { suppressErrorToast: true },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['datasets', projectId] });
      datasetToDelete = null;
      showDatasetDeleteDialog = false;
      datasetDeleteError = null;
    },
    onError: (error: Error) => {
      datasetDeleteError = error.message || m.sites_data_dataset_error_delete();
    },
  });

  // --- Site handlers ---
  function handleSiteSelect(site: Site) {
    goto(localizeHref(`/projects/${projectId}/sites/${site.id}`));
  }

  async function handleSiteDeleteClick(site: Site) {
    siteToDelete = site;
    try {
      const siteDetail = await fetchSite(projectId, site.id);
      const warnings: string[] = [];
      if (siteDetail.dataset_count > 0) {
        warnings.push(m.common_datasets_count({ count: siteDetail.dataset_count }));
      }
      if (siteDetail.recording_count > 0) {
        warnings.push(m.common_recordings_count({ count: siteDetail.recording_count }));
      }
      if (warnings.length === 0) {
        warnings.push(m.sites_data_site_delete_warning_all());
      }
      siteDeleteWarningItems = warnings;
    } catch {
      siteDeleteWarningItems = [m.sites_data_site_delete_warning_fallback()];
    }
    showSiteDeleteDialog = true;
  }

  async function confirmSiteDelete() {
    if (siteToDelete) {
      await $siteDeleteMutation.mutateAsync(siteToDelete.id);
      showSiteDeleteDialog = false;
      siteToDelete = null;
    }
  }

  function cancelSiteDelete() {
    showSiteDeleteDialog = false;
    siteToDelete = null;
    siteDeleteWarningItems = [];
  }

  async function handleSiteCreateSubmit(data: SiteCreate) {
    await $siteCreateMutation.mutateAsync(data);
  }

  // --- Dataset handlers ---
  function handleDatasetSelect(dataset: Dataset) {
    goto(localizeHref(`/projects/${projectId}/datasets/${dataset.id}`));
  }

  async function handleDatasetDeleteClick(dataset: Dataset) {
    datasetToDelete = dataset;
    datasetDeleteError = null;
    try {
      const datasetDetail = await fetchDataset(projectId, dataset.id);
      const warnings: string[] = [];
      const recordingCount = datasetDetail.processed_files || 0;
      if (recordingCount > 0) {
        warnings.push(m.sites_data_dataset_delete_warning_recordings({ count: recordingCount }));
        warnings.push(m.sites_data_dataset_delete_warning_clips());
      }
      if (warnings.length === 0) {
        warnings.push(m.sites_data_dataset_delete_warning_all());
      }
      datasetDeleteWarningItems = warnings;
    } catch {
      datasetDeleteWarningItems = [m.sites_data_dataset_delete_warning_fallback()];
    }
    showDatasetDeleteDialog = true;
  }

  async function confirmDatasetDelete() {
    if (datasetToDelete) {
      datasetDeleteError = null;
      try {
        await $datasetDeleteMutation.mutateAsync(datasetToDelete.id);
        // onSuccess handles closing the dialog and clearing state
      } catch {
        // Error is displayed via datasetDeleteError set in onError handler
        // Keep the dialog open so the user can see the error
      }
    }
  }

  function cancelDatasetDelete() {
    showDatasetDeleteDialog = false;
    datasetToDelete = null;
    datasetDeleteWarningItems = [];
    datasetDeleteError = null;
  }

  async function handleDatasetCreateSubmit(data: DatasetCreate | DatasetUpdate) {
    await $datasetCreateMutation.mutateAsync(data as DatasetCreate);
  }

  function handleDatasetFilterChange() {
    datasetCurrentPage = 1;
  }

  // --- Recordings handlers ---
  function handleRecordingSelect(recordingId: string) {
    goto(localizeHref(`/projects/${projectId}/recordings/${recordingId}`));
  }

  // Tab labels map (derived so labels react to locale changes)
  const tabs = $derived<{ id: Tab; label: string }[]>([
    { id: 'sites', label: m.sites_data_tab_sites() },
    { id: 'datasets', label: m.sites_data_tab_datasets() },
    { id: 'recordings', label: m.sites_data_tab_recordings() },
  ]);
</script>

<svelte:head>
  <title>{m.sites_data_page_title()}</title>
</svelte:head>

<div class="mx-auto max-w-6xl px-6 py-8">
  <!-- Page header -->
  <header class="mb-6">
    <nav class="mb-2 flex items-center gap-2 text-sm text-stone-500">
      <a href={localizeHref(`/projects/${projectId}`)} class="hover:text-stone-900">{m.dataset_list_breadcrumb_project()}</a>
      <span>/</span>
      <span class="font-medium text-stone-900">{m.sites_data_breadcrumb()}</span>
    </nav>
    <h1 class="text-2xl font-bold text-stone-900">{m.sites_data_heading()}</h1>
    <p class="mt-1 text-sm text-stone-500">{m.sites_data_description()}</p>
  </header>

  <!-- Tab bar -->
  <div class="mb-6 border-b border-stone-200">
    <nav class="-mb-px flex gap-6" aria-label="Tabs">
      {#each tabs as tab}
        <button
          onclick={() => (activeTab = tab.id)}
          class="border-b-2 pb-3 text-sm font-medium transition-colors {activeTab === tab.id
            ? 'border-primary-600 text-primary-600'
            : 'border-transparent text-stone-500 hover:border-stone-300 hover:text-stone-700'}"
          aria-current={activeTab === tab.id ? 'page' : undefined}
        >
          {tab.label}
        </button>
      {/each}
    </nav>
  </div>

  <!-- Sites tab -->
  {#if activeTab === 'sites'}
    <div>
      <div class="mb-6 flex items-center justify-between">
        <p class="text-sm text-stone-500">{m.sites_data_site_description()}</p>
        {#if !showSiteCreateForm}
          <button
            onclick={() => (showSiteCreateForm = true)}
            class="flex items-center gap-2 rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
          >
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <line x1="12" y1="5" x2="12" y2="19" stroke-width="2" />
              <line x1="5" y1="12" x2="19" y2="12" stroke-width="2" />
            </svg>
            {m.sites_data_site_new_button()}
          </button>
        {/if}
      </div>

      {#if showSiteCreateForm}
        <div class="mb-6 rounded-lg border border-card bg-surface-card p-6">
          <div class="mb-4 flex items-center justify-between">
            <h2 class="text-lg font-semibold text-stone-900">{m.sites_data_site_create_heading()}</h2>
            <button
              onclick={() => (showSiteCreateForm = false)}
              class="rounded p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-600"
              aria-label={m.common_close()}
            >
              <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <line x1="18" y1="6" x2="6" y2="18" stroke-width="2" />
                <line x1="6" y1="6" x2="18" y2="18" stroke-width="2" />
              </svg>
            </button>
          </div>
          <SiteForm onSubmit={handleSiteCreateSubmit} onCancel={() => (showSiteCreateForm = false)} />
          {#if $siteCreateMutation.isError}
            <div class="mt-4 rounded-md border border-danger/20 bg-danger-light px-3 py-2 text-sm text-danger">
              {$siteCreateMutation.error?.message || m.sites_data_site_error_create()}
            </div>
          {/if}
        </div>
      {:else if $sitesQuery.isLoading}
        <div class="flex items-center justify-center py-12 text-sm text-stone-500">
          <svg class="mr-2 h-5 w-5 animate-spin text-primary-600" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
          </svg>
          {m.common_loading_sites()}
        </div>
      {:else if $sitesQuery.isError}
        <div class="rounded-md border border-danger/20 bg-danger-light px-4 py-3 text-sm text-danger">
          {m.site_list_error_load({ message: $sitesQuery.error?.message ?? '' })}
        </div>
      {:else if $sitesQuery.data}
        <SiteList
          sites={$sitesQuery.data.items}
          onSelect={handleSiteSelect}
          onDelete={handleSiteDeleteClick}
        />
        {#if $sitesQuery.data.total > 0}
          <p class="mt-3 text-center text-sm text-stone-400">
            {m.sites_data_site_showing({ showing: $sitesQuery.data.items.length, total: $sitesQuery.data.total })}
          </p>
        {/if}
      {/if}
    </div>
  {/if}

  <!-- Datasets tab -->
  {#if activeTab === 'datasets'}
    <div>
      <div class="mb-6 flex items-center justify-between">
        <p class="text-sm text-stone-500">{m.sites_data_dataset_description()}</p>
        {#if !showDatasetCreateForm}
          <button
            onclick={() => (showDatasetCreateForm = true)}
            class="flex items-center gap-2 rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
          >
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <line x1="12" y1="5" x2="12" y2="19" stroke-width="2" />
              <line x1="5" y1="12" x2="19" y2="12" stroke-width="2" />
            </svg>
            {m.dataset_list_new_button()}
          </button>
        {/if}
      </div>

      {#if showDatasetCreateForm}
        <div class="mb-6 rounded-lg border border-card bg-surface-card p-6">
          <div class="mb-4 flex items-center justify-between">
            <h2 class="text-lg font-semibold text-stone-900">{m.dataset_list_create_heading()}</h2>
            <button
              onclick={() => (showDatasetCreateForm = false)}
              class="rounded p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-600"
              aria-label={m.common_close()}
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
            onSubmit={handleDatasetCreateSubmit}
            onCancel={() => (showDatasetCreateForm = false)}
          />
          {#if $datasetCreateMutation.isError}
            <div class="mt-4 rounded-md border border-danger/20 bg-danger-light px-3 py-2 text-sm text-danger">
              {$datasetCreateMutation.error?.message || m.dataset_list_error_create()}
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
          {m.sites_data_dataset_error_load({ message: $datasetsQuery.error?.message ?? '' })}
        </div>
      {:else if $datasetsQuery.data}
        <DatasetList
          datasets={$datasetsQuery.data.items}
          bind:search={datasetSearch}
          bind:statusFilter={datasetStatusFilter}
          bind:visibilityFilter={datasetVisibilityFilter}
          onFilterChange={handleDatasetFilterChange}
          onSelect={handleDatasetSelect}
          onDelete={handleDatasetDeleteClick}
        />

        {#if $datasetsQuery.data.pages > 1}
          <div class="mt-4 flex items-center justify-center gap-4">
            <button
              onclick={() => (datasetCurrentPage = Math.max(1, datasetCurrentPage - 1))}
              disabled={datasetCurrentPage === 1}
              class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {m.common_previous()}
            </button>
            <span class="text-sm text-stone-500">
              {m.sites_data_dataset_page_info({ page: datasetCurrentPage, total: $datasetsQuery.data.pages })}
            </span>
            <button
              onclick={() => (datasetCurrentPage = Math.min($datasetsQuery.data!.pages, datasetCurrentPage + 1))}
              disabled={datasetCurrentPage === $datasetsQuery.data.pages}
              class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {m.common_next()}
            </button>
          </div>
        {/if}

        {#if $datasetsQuery.data.total > 0}
          <p class="mt-3 text-center text-sm text-stone-400">
            {m.sites_data_dataset_showing({ showing: $datasetsQuery.data.items.length, total: $datasetsQuery.data.total })}
          </p>
        {/if}
      {/if}
    </div>
  {/if}

  <!-- Recordings tab -->
  {#if activeTab === 'recordings'}
    <div>
      <div class="mb-6">
        <p class="text-sm text-stone-500">{m.sites_data_recordings_description()}</p>
      </div>
      {#if projectId}
        <RecordingList {projectId} onSelect={handleRecordingSelect} />
      {/if}
    </div>
  {/if}
</div>

<!-- Site delete confirmation -->
<ConfirmDialog
  isOpen={showSiteDeleteDialog}
  title={m.site_list_delete_title()}
  message={siteToDelete ? m.site_list_delete_message({ name: siteToDelete.name }) : ''}
  confirmText={m.site_list_delete_confirm()}
  cancelText={m.site_list_delete_cancel()}
  isDanger={true}
  onConfirm={confirmSiteDelete}
  onCancel={cancelSiteDelete}
  warningItems={siteDeleteWarningItems}
/>

<!-- Dataset delete confirmation -->
<ConfirmDialog
  isOpen={showDatasetDeleteDialog}
  title={m.dataset_list_delete_title()}
  message={datasetToDelete ? m.dataset_list_delete_message({ name: datasetToDelete.name }) : ''}
  confirmText={m.dataset_list_delete_confirm()}
  cancelText={m.dataset_list_delete_cancel()}
  isDanger={true}
  onConfirm={confirmDatasetDelete}
  onCancel={cancelDatasetDelete}
  warningItems={datasetDeleteWarningItems}
  errorMessage={datasetDeleteError}
/>
