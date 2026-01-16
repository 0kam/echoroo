<script lang="ts">
  import { page } from '$app/stores';
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { fetchSites, createSite, deleteSite, fetchSite } from '$lib/api/sites';
  import type { Site, SiteCreate } from '$lib/types/data';
  import SiteList from '$lib/components/data/SiteList.svelte';
  import SiteForm from '$lib/components/data/SiteForm.svelte';
  import ConfirmDialog from '$lib/components/ui/ConfirmDialog.svelte';
  import { goto } from '$app/navigation';

  // Extract and validate projectId from route params
  $: projectId = $page.params.id;

  // Early return if projectId is undefined
  $: if (!projectId) {
    throw new Error('Project ID is required');
  }

  const queryClient = useQueryClient();

  let showCreateForm = false;
  let siteToDelete: Site | null = null;
  let showDeleteDialog = false;
  let deleteWarningItems: string[] = [];

  // Query for sites
  $: sitesQuery = createQuery({
    queryKey: ['sites', projectId],
    queryFn: () => fetchSites(projectId!),
    enabled: !!projectId,
  });

  // Mutation for creating a site
  const siteCreateMutation = createMutation({
    mutationFn: (data: SiteCreate) => {
      if (!projectId) throw new Error('Project ID is required');
      return createSite(projectId, data);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sites', projectId] });
      showCreateForm = false;
    },
  });

  // Mutation for deleting a site
  const deleteMutation = createMutation({
    mutationFn: (siteId: string) => {
      if (!projectId) throw new Error('Project ID is required');
      return deleteSite(projectId, siteId);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sites', projectId] });
      siteToDelete = null;
    },
  });

  function handleSiteSelect(site: Site) {
    if (!projectId) return;
    goto(`/projects/${projectId}/sites/${site.id}`);
  }

  async function handleDeleteClick(site: Site) {
    if (!projectId) return;

    siteToDelete = site;

    // Fetch site details to get dataset and recording counts
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

      deleteWarningItems = warnings;
      showDeleteDialog = true;
    } catch (error) {
      // If we can't fetch details, show generic warning
      deleteWarningItems = ['All associated datasets and recordings'];
      showDeleteDialog = true;
    }
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

<div class="sites-page">
  <header class="page-header">
    <div>
      <h1>Sites</h1>
      <p>Manage geographic locations for your recordings</p>
    </div>
    {#if !showCreateForm}
      <button class="btn-primary" on:click={() => (showCreateForm = true)}>
        + New Site
      </button>
    {/if}
  </header>

  {#if showCreateForm}
    <div class="create-form-container">
      <h2>Create New Site</h2>
      <SiteForm
        onSubmit={handleCreateSubmit}
        onCancel={() => (showCreateForm = false)}
      />
    </div>
  {:else if $sitesQuery.isLoading}
    <div class="loading">Loading sites...</div>
  {:else if $sitesQuery.isError}
    <div class="error">Error loading sites: {$sitesQuery.error?.message}</div>
  {:else if $sitesQuery.data}
    <SiteList
      sites={$sitesQuery.data.items}
      onSelect={handleSiteSelect}
      onDelete={handleDeleteClick}
    />

    {#if $sitesQuery.data.total > 0}
      <div class="pagination-info">
        Showing {$sitesQuery.data.items.length} of {$sitesQuery.data.total} sites
      </div>
    {/if}
  {/if}

  <!-- Delete Confirmation Dialog -->
  <ConfirmDialog
    isOpen={showDeleteDialog}
    title="Delete Site"
    message={siteToDelete ? `Are you sure you want to delete "${siteToDelete.name}"? This action cannot be undone.` : ''}
    confirmText="Delete Site"
    cancelText="Cancel"
    confirmButtonClass="btn-danger"
    onConfirm={confirmDelete}
    onCancel={cancelDelete}
    warningItems={deleteWarningItems}
  />
</div>

<style>
  .sites-page {
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
