<script lang="ts">
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { fetchSite, updateSite, deleteSite } from '$lib/api/sites';
  import type { SiteUpdate } from '$lib/types/data';
  import SiteForm from '$lib/components/data/SiteForm.svelte';
  import DeleteConfirmDialog from '$lib/components/ui/DeleteConfirmDialog.svelte';

  // Extract and validate route params
  $: projectId = $page.params.id;
  $: siteId = $page.params.siteId;

  // Early return if required params are undefined
  $: if (!projectId || !siteId) {
    throw new Error('Project ID and Site ID are required');
  }

  const queryClient = useQueryClient();

  let isEditing = false;
  let showDeleteConfirm = false;

  // Query for site details
  $: siteQuery = createQuery({
    queryKey: ['site', projectId, siteId],
    queryFn: () => fetchSite(projectId!, siteId!),
    enabled: !!projectId && !!siteId,
  });

  // Update mutation
  const updateMutation = createMutation({
    mutationFn: (data: SiteUpdate) => {
      if (!projectId || !siteId) throw new Error('Project ID and Site ID are required');
      return updateSite(projectId, siteId, data);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['site', projectId, siteId] });
      queryClient.invalidateQueries({ queryKey: ['sites', projectId] });
      isEditing = false;
    },
  });

  // Delete mutation
  const deleteMutation = createMutation({
    mutationFn: () => {
      if (!projectId || !siteId) throw new Error('Project ID and Site ID are required');
      return deleteSite(projectId, siteId);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sites', projectId] });
      if (projectId) goto(`/projects/${projectId}/sites`);
    },
  });

  async function handleUpdateSubmit(data: { name: string; h3_index: string }) {
    await $updateMutation.mutateAsync(data);
  }

  function handleDeleteConfirm() {
    $deleteMutation.mutate();
    showDeleteConfirm = false;
  }

  function formatDuration(seconds: number): string {
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    if (hours > 0) return `${hours}h ${mins}m`;
    return `${mins}m`;
  }

  $: deleteWarnings = $siteQuery.data
    ? [
        `${$siteQuery.data.dataset_count} dataset(s)`,
        `${$siteQuery.data.recording_count} recording(s)`,
        `${formatDuration($siteQuery.data.total_duration)} of audio data`,
      ]
    : [];
</script>

<svelte:head>
  <title>{$siteQuery.data?.name ?? 'Site'} | Project</title>
</svelte:head>

<div class="site-detail-page">
  <nav class="breadcrumb">
    <a href="/projects/{projectId}/sites">Sites</a>
    <span>/</span>
    <span>{$siteQuery.data?.name ?? 'Loading...'}</span>
  </nav>

  {#if $siteQuery.isLoading}
    <div class="loading">Loading site details...</div>
  {:else if $siteQuery.isError}
    <div class="error">Error: {$siteQuery.error?.message}</div>
  {:else if $siteQuery.data}
    {#if isEditing}
      <div class="edit-container">
        <h2>Edit Site</h2>
        <SiteForm
          site={$siteQuery.data}
          onSubmit={handleUpdateSubmit}
          onCancel={() => (isEditing = false)}
        />
      </div>
    {:else}
      <header class="page-header">
        <div>
          <h1>{$siteQuery.data.name}</h1>
          <code class="h3-index">{$siteQuery.data.h3_index}</code>
        </div>
        <div class="actions">
          <button class="btn-secondary" on:click={() => (isEditing = true)}>
            Edit
          </button>
          <button
            class="btn-danger"
            on:click={() => (showDeleteConfirm = true)}
          >
            Delete
          </button>
        </div>
      </header>

      <div class="stats-grid">
        <div class="stat-card">
          <span class="stat-value">{$siteQuery.data.dataset_count}</span>
          <span class="stat-label">Datasets</span>
        </div>
        <div class="stat-card">
          <span class="stat-value">{$siteQuery.data.recording_count}</span>
          <span class="stat-label">Recordings</span>
        </div>
        <div class="stat-card">
          <span class="stat-value">{formatDuration($siteQuery.data.total_duration)}</span>
          <span class="stat-label">Total Duration</span>
        </div>
      </div>

      <section class="section">
        <h2>Datasets at this Site</h2>
        <p class="coming-soon">Dataset list coming soon...</p>
        <a href="/projects/{projectId}/datasets?site_id={siteId}" class="btn-link">
          View all datasets →
        </a>
      </section>
    {/if}
  {/if}

  <DeleteConfirmDialog
    isOpen={showDeleteConfirm}
    title="Delete Site"
    message={`Are you sure you want to delete "${$siteQuery.data?.name ?? 'this site'}"? This action cannot be undone.`}
    warnings={deleteWarnings}
    confirmText="Delete Site"
    isDeleting={$deleteMutation.isPending}
    onConfirm={handleDeleteConfirm}
    onCancel={() => (showDeleteConfirm = false)}
  />
</div>

<style>
  .site-detail-page {
    max-width: 1200px;
    margin: 0 auto;
    padding: 2rem;
  }

  .breadcrumb {
    display: flex;
    gap: 0.5rem;
    font-size: 0.875rem;
    margin-bottom: 1.5rem;
  }

  .breadcrumb a {
    color: #3b82f6;
    text-decoration: none;
  }

  .breadcrumb a:hover {
    text-decoration: underline;
  }

  .breadcrumb span {
    color: #9ca3af;
  }

  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 2rem;
  }

  .page-header h1 {
    margin: 0 0 0.5rem 0;
    font-size: 1.5rem;
    font-weight: 600;
  }

  .h3-index {
    font-size: 0.875rem;
    background: #f3f4f6;
    padding: 0.25rem 0.5rem;
    border-radius: 0.25rem;
    color: #6b7280;
  }

  .actions {
    display: flex;
    gap: 0.75rem;
  }

  .edit-container {
    background: white;
    padding: 1.5rem;
    border-radius: 0.5rem;
    border: 1px solid #e5e7eb;
  }

  .edit-container h2 {
    margin: 0 0 1.5rem 0;
    font-size: 1.125rem;
  }

  .stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 1rem;
    margin-bottom: 2rem;
  }

  .stat-card {
    background: white;
    padding: 1.5rem;
    border-radius: 0.5rem;
    border: 1px solid #e5e7eb;
    text-align: center;
  }

  .stat-value {
    display: block;
    font-size: 2rem;
    font-weight: 600;
    color: #111827;
  }

  .stat-label {
    font-size: 0.875rem;
    color: #6b7280;
  }

  .section {
    background: white;
    padding: 1.5rem;
    border-radius: 0.5rem;
    border: 1px solid #e5e7eb;
  }

  .section h2 {
    margin: 0 0 1rem 0;
    font-size: 1.125rem;
    font-weight: 600;
  }

  .coming-soon {
    color: #9ca3af;
    font-style: italic;
  }

  .btn-link {
    display: inline-block;
    margin-top: 1rem;
    color: #3b82f6;
    text-decoration: none;
  }

  .btn-link:hover {
    text-decoration: underline;
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

  .btn-secondary,
  .btn-danger {
    padding: 0.5rem 1rem;
    font-size: 0.875rem;
    border-radius: 0.375rem;
    cursor: pointer;
  }

  .btn-secondary {
    background: white;
    color: #374151;
    border: 1px solid #d1d5db;
  }

  .btn-danger {
    background: #dc2626;
    color: white;
    border: none;
  }

  .btn-danger:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
