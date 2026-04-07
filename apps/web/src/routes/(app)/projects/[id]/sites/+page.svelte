<script lang="ts">
  import { page } from '$app/stores';
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { fetchSites, createSite, deleteSite, fetchSite } from '$lib/api/sites';
  import type { Site, SiteCreate } from '$lib/types/data';
  import SiteList from '$lib/components/data/SiteList.svelte';
  import SiteForm from '$lib/components/data/SiteForm.svelte';
  import ConfirmDialog from '$lib/components/ui/ConfirmDialog.svelte';
  import { goto } from '$app/navigation';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';

  const projectId = $derived($page.params.id as string);

  const queryClient = useQueryClient();

  let showCreateForm = $state(false);
  let siteToDelete = $state<Site | null>(null);
  let showDeleteDialog = $state(false);
  let deleteWarningItems = $state<string[]>([]);

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
      showCreateForm = false;
    },
  });

  const deleteMutation = createMutation({
    mutationFn: (siteId: string) => deleteSite(projectId, siteId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sites', projectId] });
      siteToDelete = null;
    },
  });

  function handleSiteSelect(site: Site) {
    goto(localizeHref(`/projects/${projectId}/sites/${site.id}`));
  }

  async function handleDeleteClick(site: Site) {
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
        warnings.push('All associated data');
      }

      deleteWarningItems = warnings;
    } catch {
      deleteWarningItems = ['All associated datasets and recordings'];
    }

    showDeleteDialog = true;
  }

  async function confirmDelete() {
    if (siteToDelete) {
      await $deleteMutation.mutateAsync(siteToDelete.id);
      showDeleteDialog = false;
      siteToDelete = null;
    }
  }

  function cancelDelete() {
    showDeleteDialog = false;
    siteToDelete = null;
    deleteWarningItems = [];
  }

  async function handleCreateSubmit(data: SiteCreate) {
    await $siteCreateMutation.mutateAsync(data);
  }
</script>

<svelte:head>
  <title>Sites | Project</title>
</svelte:head>

<div class="mx-auto max-w-4xl px-6 py-8">
  <header class="mb-6 flex items-start justify-between">
    <div>
      <nav class="mb-2 flex items-center gap-2 text-sm text-stone-500">
        <a href={localizeHref(`/projects/${projectId}`)} class="hover:text-stone-900">Project</a>
        <span>/</span>
        <span class="font-medium text-stone-900">Sites</span>
      </nav>
      <h1 class="text-2xl font-bold text-stone-900">Sites</h1>
      <p class="mt-1 text-sm text-stone-500">Manage geographic locations for your recordings</p>
    </div>
    {#if !showCreateForm}
      <button
        onclick={() => (showCreateForm = true)}
        class="flex items-center gap-2 rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700"
      >
        <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <line x1="12" y1="5" x2="12" y2="19" stroke-width="2" />
          <line x1="5" y1="12" x2="19" y2="12" stroke-width="2" />
        </svg>
        New Site
      </button>
    {/if}
  </header>

  {#if showCreateForm}
    <div class="mb-6 rounded-lg border border-card bg-surface-card p-6">
      <div class="mb-4 flex items-center justify-between">
        <h2 class="text-lg font-semibold text-stone-900">Create New Site</h2>
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
      <SiteForm onSubmit={handleCreateSubmit} onCancel={() => (showCreateForm = false)} />
      {#if $siteCreateMutation.isError}
        <div class="mt-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">
          {$siteCreateMutation.error?.message || 'Failed to create site'}
        </div>
      {/if}
    </div>
  {:else if $sitesQuery.isLoading}
    <div class="flex items-center justify-center py-12 text-sm text-stone-500">
      <svg class="mr-2 h-5 w-5 animate-spin text-primary-600" fill="none" viewBox="0 0 24 24">
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
      onDelete={handleDeleteClick}
    />

    {#if $sitesQuery.data.total > 0}
      <p class="mt-3 text-center text-sm text-stone-400">
        Showing {$sitesQuery.data.items.length} of {$sitesQuery.data.total} sites
      </p>
    {/if}
  {/if}
</div>

<!-- Delete Confirmation Dialog -->
<ConfirmDialog
  isOpen={showDeleteDialog}
  title="Delete Site"
  message={siteToDelete ? `Are you sure you want to delete "${siteToDelete.name}"? This action cannot be undone.` : ''}
  confirmText="Delete Site"
  cancelText="Cancel"
  isDanger={true}
  onConfirm={confirmDelete}
  onCancel={cancelDelete}
  warningItems={deleteWarningItems}
/>
