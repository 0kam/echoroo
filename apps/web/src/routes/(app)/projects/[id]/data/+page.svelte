<script lang="ts">
  /**
   * Sites & Data unified page.
   * Provides a tabbed interface for Sites, Datasets, and Recordings.
   */

  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { fetchSites, createSite, deleteSite, fetchSite } from '$lib/api/sites';
  import { fetchDatasets, createDataset, deleteDataset, fetchDataset } from '$lib/api/datasets';
  import type { Dataset, DatasetCreate, DatasetStatus, DatasetVisibility, DatasetUpdate, Site, SiteCreate } from '$lib/types/data';
  import SiteList from '$lib/components/data/SiteList.svelte';
  import SiteForm from '$lib/components/data/SiteForm.svelte';
  import DatasetList from '$lib/components/data/DatasetList.svelte';
  import DatasetForm from '$lib/components/data/DatasetForm.svelte';
  import RecordingList from '$lib/components/data/RecordingList.svelte';
  import ConfirmDialog from '$lib/components/ui/ConfirmDialog.svelte';

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
      goto(`/projects/${projectId}/datasets/${created.id}`);
    },
  });

  const datasetDeleteMutation = createMutation({
    mutationFn: (datasetId: string) => deleteDataset(projectId, datasetId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['datasets', projectId] });
      datasetToDelete = null;
      showDatasetDeleteDialog = false;
      datasetDeleteError = null;
    },
    onError: (error: Error) => {
      datasetDeleteError = error.message || 'Failed to delete dataset';
    },
  });

  // --- Site handlers ---
  function handleSiteSelect(site: Site) {
    goto(`/projects/${projectId}/sites/${site.id}`);
  }

  async function handleSiteDeleteClick(site: Site) {
    siteToDelete = site;
    try {
      const siteDetail = await fetchSite(projectId, site.id);
      const warnings: string[] = [];
      if (siteDetail.dataset_count > 0) {
        warnings.push(`${siteDetail.dataset_count} dataset${siteDetail.dataset_count > 1 ? 's' : ''}`);
      }
      if (siteDetail.recording_count > 0) {
        warnings.push(`${siteDetail.recording_count} recording${siteDetail.recording_count > 1 ? 's' : ''}`);
      }
      if (warnings.length === 0) {
        warnings.push('All associated data');
      }
      siteDeleteWarningItems = warnings;
    } catch {
      siteDeleteWarningItems = ['All associated datasets and recordings'];
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
    goto(`/projects/${projectId}/datasets/${dataset.id}`);
  }

  async function handleDatasetDeleteClick(dataset: Dataset) {
    datasetToDelete = dataset;
    datasetDeleteError = null;
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
      datasetDeleteWarningItems = warnings;
    } catch {
      datasetDeleteWarningItems = ['All associated recordings and clips'];
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
    goto(`/projects/${projectId}/recordings/${recordingId}`);
  }

  // Tab labels map
  const tabs: { id: Tab; label: string }[] = [
    { id: 'sites', label: 'Sites' },
    { id: 'datasets', label: 'Datasets' },
    { id: 'recordings', label: 'Recordings' },
  ];
</script>

<svelte:head>
  <title>Sites & Data | Project</title>
</svelte:head>

<div class="mx-auto max-w-6xl px-6 py-8">
  <!-- Page header -->
  <header class="mb-6">
    <nav class="mb-2 flex items-center gap-2 text-sm text-gray-500">
      <a href="/projects/{projectId}" class="hover:text-gray-900">Project</a>
      <span>/</span>
      <span class="font-medium text-gray-900">Sites & Data</span>
    </nav>
    <h1 class="text-2xl font-bold text-gray-900">Sites & Data</h1>
    <p class="mt-1 text-sm text-gray-500">Manage sites, datasets, and recordings for this project</p>
  </header>

  <!-- Tab bar -->
  <div class="mb-6 border-b border-gray-200">
    <nav class="-mb-px flex gap-6" aria-label="Tabs">
      {#each tabs as tab}
        <button
          onclick={() => (activeTab = tab.id)}
          class="border-b-2 pb-3 text-sm font-medium transition-colors {activeTab === tab.id
            ? 'border-blue-600 text-blue-600'
            : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'}"
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
        <p class="text-sm text-gray-500">Manage geographic locations for your recordings</p>
        {#if !showSiteCreateForm}
          <button
            onclick={() => (showSiteCreateForm = true)}
            class="flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
          >
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <line x1="12" y1="5" x2="12" y2="19" stroke-width="2" />
              <line x1="5" y1="12" x2="19" y2="12" stroke-width="2" />
            </svg>
            New Site
          </button>
        {/if}
      </div>

      {#if showSiteCreateForm}
        <div class="mb-6 rounded-lg border border-gray-200 bg-white p-6">
          <div class="mb-4 flex items-center justify-between">
            <h2 class="text-lg font-semibold text-gray-900">Create New Site</h2>
            <button
              onclick={() => (showSiteCreateForm = false)}
              class="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
              aria-label="Close"
            >
              <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <line x1="18" y1="6" x2="6" y2="18" stroke-width="2" />
                <line x1="6" y1="6" x2="18" y2="18" stroke-width="2" />
              </svg>
            </button>
          </div>
          <SiteForm onSubmit={handleSiteCreateSubmit} onCancel={() => (showSiteCreateForm = false)} />
          {#if $siteCreateMutation.isError}
            <div class="mt-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">
              {$siteCreateMutation.error?.message || 'Failed to create site'}
            </div>
          {/if}
        </div>
      {:else if $sitesQuery.isLoading}
        <div class="flex items-center justify-center py-12 text-sm text-gray-500">
          <svg class="mr-2 h-5 w-5 animate-spin text-blue-600" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
          </svg>
          Loading sites...
        </div>
      {:else if $sitesQuery.isError}
        <div class="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
          Error loading sites: {$sitesQuery.error?.message}
        </div>
      {:else if $sitesQuery.data}
        <SiteList
          sites={$sitesQuery.data.items}
          onSelect={handleSiteSelect}
          onDelete={handleSiteDeleteClick}
        />
        {#if $sitesQuery.data.total > 0}
          <p class="mt-3 text-center text-sm text-gray-400">
            Showing {$sitesQuery.data.items.length} of {$sitesQuery.data.total} sites
          </p>
        {/if}
      {/if}
    </div>
  {/if}

  <!-- Datasets tab -->
  {#if activeTab === 'datasets'}
    <div>
      <div class="mb-6 flex items-center justify-between">
        <p class="text-sm text-gray-500">Manage collections of audio recordings</p>
        {#if !showDatasetCreateForm}
          <button
            onclick={() => (showDatasetCreateForm = true)}
            class="flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
          >
            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <line x1="12" y1="5" x2="12" y2="19" stroke-width="2" />
              <line x1="5" y1="12" x2="19" y2="12" stroke-width="2" />
            </svg>
            New Dataset
          </button>
        {/if}
      </div>

      {#if showDatasetCreateForm}
        <div class="mb-6 rounded-lg border border-gray-200 bg-white p-6">
          <div class="mb-4 flex items-center justify-between">
            <h2 class="text-lg font-semibold text-gray-900">Create New Dataset</h2>
            <button
              onclick={() => (showDatasetCreateForm = false)}
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
            onSubmit={handleDatasetCreateSubmit}
            onCancel={() => (showDatasetCreateForm = false)}
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
              class="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Previous
            </button>
            <span class="text-sm text-gray-500">
              Page {datasetCurrentPage} of {$datasetsQuery.data.pages}
            </span>
            <button
              onclick={() => (datasetCurrentPage = Math.min($datasetsQuery.data!.pages, datasetCurrentPage + 1))}
              disabled={datasetCurrentPage === $datasetsQuery.data.pages}
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
  {/if}

  <!-- Recordings tab -->
  {#if activeTab === 'recordings'}
    <div>
      <div class="mb-6">
        <p class="text-sm text-gray-500">All recordings in this project</p>
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
  title="Delete Site"
  message={siteToDelete ? `Are you sure you want to delete "${siteToDelete.name}"? This action cannot be undone.` : ''}
  confirmText="Delete Site"
  cancelText="Cancel"
  isDanger={true}
  onConfirm={confirmSiteDelete}
  onCancel={cancelSiteDelete}
  warningItems={siteDeleteWarningItems}
/>

<!-- Dataset delete confirmation -->
<ConfirmDialog
  isOpen={showDatasetDeleteDialog}
  title="Delete Dataset"
  message={datasetToDelete ? `Are you sure you want to delete "${datasetToDelete.name}"? This action cannot be undone.` : ''}
  confirmText="Delete Dataset"
  cancelText="Cancel"
  isDanger={true}
  onConfirm={confirmDatasetDelete}
  onCancel={cancelDatasetDelete}
  warningItems={datasetDeleteWarningItems}
  errorMessage={datasetDeleteError}
/>
