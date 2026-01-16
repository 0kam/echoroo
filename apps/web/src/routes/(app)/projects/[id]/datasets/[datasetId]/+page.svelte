<script lang="ts">
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { fetchDataset, updateDataset, deleteDataset } from '$lib/api/datasets';
  import type { DatasetUpdate } from '$lib/types/data';
  import DatasetForm from '$lib/components/data/DatasetForm.svelte';
  import DatasetStatistics from '$lib/components/data/DatasetStatistics.svelte';
  import ImportProgress from '$lib/components/data/ImportProgress.svelte';
  import ExportDialog from '$lib/components/data/ExportDialog.svelte';
  import DeleteConfirmDialog from '$lib/components/ui/DeleteConfirmDialog.svelte';

  const queryClient = useQueryClient();

  $: projectId = $page.params.id as string;
  $: datasetId = $page.params.datasetId as string;

  $: datasetQuery = createQuery({
    queryKey: ['dataset', projectId, datasetId],
    queryFn: () => fetchDataset(projectId, datasetId),
  });

  let showEditModal = false;

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

  let showDeleteConfirm = false;
  let showExportDialog = false;

  async function handleUpdateSubmit(data: DatasetUpdate) {
    await $updateMutation.mutateAsync(data);
  }

  function confirmDelete() {
    $deleteMutation.mutate();
    showDeleteConfirm = false;
  }

  function formatDate(dateStr: string): string {
    return new Date(dateStr).toLocaleDateString();
  }

  function formatDateTime(dateStr: string): string {
    return new Date(dateStr).toLocaleString();
  }

  $: deleteWarnings = $datasetQuery.data
    ? [
        `${$datasetQuery.data.recording_count || 0} recording(s)`,
        'All associated clips and annotations',
      ]
    : [];
</script>

<svelte:head>
  <title>{$datasetQuery.data?.name || 'Dataset'} | Project</title>
</svelte:head>

<div class="dataset-detail-page">
  {#if $datasetQuery.isLoading}
    <div class="loading">Loading dataset...</div>
  {:else if $datasetQuery.isError}
    <div class="error">Error: {$datasetQuery.error?.message}</div>
  {:else if $datasetQuery.data}
    {@const dataset = $datasetQuery.data}

    <!-- Header -->
    <header class="page-header">
      <div class="header-content">
        <div class="breadcrumb">
          <a href="/projects/{projectId}/datasets">Datasets</a>
          <span class="separator">/</span>
          <span>{dataset.name}</span>
        </div>
        <h1>{dataset.name}</h1>
        {#if dataset.description}
          <p class="description">{dataset.description}</p>
        {/if}
      </div>
      <div class="header-actions">
        {#if dataset.status === 'completed'}
          <button class="btn-export" on:click={() => (showExportDialog = true)}>
            <svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" stroke-width="2" />
              <polyline points="7 10 12 15 17 10" stroke-width="2" />
              <line x1="12" y1="15" x2="12" y2="3" stroke-width="2" />
            </svg>
            Export
          </button>
        {/if}
        <button class="btn-secondary" on:click={() => (showEditModal = true)}>
          Edit
        </button>
        <button class="btn-danger" on:click={() => (showDeleteConfirm = true)}>
          Delete
        </button>
      </div>
    </header>

    <!-- Dataset info -->
    <div class="info-card">
      <h2>Dataset Information</h2>
      <div class="info-grid">
        <div class="info-item">
          <span class="info-label">Site</span>
          <span class="info-value">
            {#if dataset.site}
              <a href="/projects/{projectId}/sites/{dataset.site.id}">
                {dataset.site.name}
              </a>
            {:else}
              <span class="text-muted">N/A</span>
            {/if}
          </span>
        </div>

        <div class="info-item">
          <span class="info-label">Status</span>
          <span class="info-value">
            <span class="status-badge {dataset.status}">
              {dataset.status}
            </span>
          </span>
        </div>

        <div class="info-item">
          <span class="info-label">Visibility</span>
          <span class="info-value">{dataset.visibility}</span>
        </div>

        <div class="info-item">
          <span class="info-label">Audio Directory</span>
          <span class="info-value">
            <code>{dataset.audio_dir}</code>
          </span>
        </div>

        {#if dataset.recorder}
          <div class="info-item">
            <span class="info-label">Recorder</span>
            <span class="info-value">
              {dataset.recorder.manufacturer} {dataset.recorder.recorder_name}
            </span>
          </div>
        {/if}

        {#if dataset.license}
          <div class="info-item">
            <span class="info-label">License</span>
            <span class="info-value">
              {dataset.license.name} ({dataset.license.short_name})
            </span>
          </div>
        {/if}

        {#if dataset.doi}
          <div class="info-item">
            <span class="info-label">DOI</span>
            <span class="info-value">
              <a href="https://doi.org/{dataset.doi}" target="_blank" rel="noopener noreferrer">
                {dataset.doi}
              </a>
            </span>
          </div>
        {/if}

        {#if dataset.gain !== null}
          <div class="info-item">
            <span class="info-label">Gain</span>
            <span class="info-value">{dataset.gain} dB</span>
          </div>
        {/if}

        <div class="info-item">
          <span class="info-label">Created</span>
          <span class="info-value">{formatDateTime(dataset.created_at)}</span>
        </div>

        {#if dataset.created_by}
          <div class="info-item">
            <span class="info-label">Created By</span>
            <span class="info-value">
              {dataset.created_by.display_name || dataset.created_by.username}
            </span>
          </div>
        {/if}
      </div>

      {#if dataset.note}
        <div class="note-section">
          <span class="info-label">Note</span>
          <p class="note-text">{dataset.note}</p>
        </div>
      {/if}
    </div>

    <!-- Import Progress -->
    <ImportProgress {projectId} {datasetId} currentStatus={dataset.status} />

    <!-- Statistics (only if completed) -->
    {#if dataset.status === 'completed'}
      <DatasetStatistics {projectId} {datasetId} />

      <!-- Link to recordings -->
      <div class="recordings-link-card">
        <div class="link-content">
          <h3>Recordings</h3>
          <p>View and manage {dataset.recording_count} recording(s) in this dataset</p>
        </div>
        <a href="/projects/{projectId}/recordings?dataset={datasetId}" class="btn-primary">
          View Recordings
        </a>
      </div>
    {/if}
  {/if}

  <!-- Edit Modal -->
  {#if showEditModal && $datasetQuery.data}
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="modal-overlay" on:click={() => (showEditModal = false)}>
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div class="modal large" on:click|stopPropagation>
        <div class="modal-header">
          <h3>Edit Dataset</h3>
          <button class="close-btn" on:click={() => (showEditModal = false)}>×</button>
        </div>
        <div class="modal-body">
          <DatasetForm
            {projectId}
            dataset={$datasetQuery.data}
            onSubmit={handleUpdateSubmit}
            onCancel={() => (showEditModal = false)}
          />
        </div>
        {#if $updateMutation.isError}
          <div class="modal-error">
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
</div>

<style>
  .dataset-detail-page {
    max-width: 1200px;
    margin: 0 auto;
    padding: 2rem;
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
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

  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 2rem;
  }

  .header-content {
    flex: 1;
  }

  .breadcrumb {
    margin-bottom: 0.5rem;
    font-size: 0.875rem;
  }

  .breadcrumb a {
    color: #3b82f6;
    text-decoration: none;
  }

  .breadcrumb a:hover {
    text-decoration: underline;
  }

  .separator {
    margin: 0 0.5rem;
    color: #9ca3af;
  }

  h1 {
    margin: 0 0 0.5rem 0;
    font-size: 1.875rem;
    font-weight: 600;
    color: #111827;
  }

  .description {
    margin: 0;
    color: #6b7280;
    font-size: 1rem;
  }

  .header-actions {
    display: flex;
    gap: 0.75rem;
  }

  .info-card,
  .recordings-link-card {
    padding: 1.5rem;
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 0.5rem;
  }

  .info-card h2 {
    margin: 0 0 1.5rem 0;
    font-size: 1rem;
    font-weight: 600;
    color: #111827;
  }

  .info-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
    gap: 1.25rem;
  }

  .info-item {
    display: flex;
    flex-direction: column;
    gap: 0.375rem;
  }

  .info-label {
    font-size: 0.75rem;
    font-weight: 500;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .info-value {
    font-size: 0.875rem;
    color: #111827;
  }

  .info-value a {
    color: #3b82f6;
    text-decoration: none;
  }

  .info-value a:hover {
    text-decoration: underline;
  }

  .info-value code {
    background: #f3f4f6;
    padding: 0.25rem 0.5rem;
    border-radius: 0.25rem;
    font-family: monospace;
    font-size: 0.75rem;
  }

  .text-muted {
    color: #9ca3af;
  }

  .status-badge {
    display: inline-block;
    padding: 0.25rem 0.625rem;
    border-radius: 0.25rem;
    font-size: 0.75rem;
    font-weight: 500;
    text-transform: capitalize;
  }

  .status-badge.pending {
    background: #fef3c7;
    color: #92400e;
  }

  .status-badge.scanning,
  .status-badge.processing {
    background: #dbeafe;
    color: #1e40af;
  }

  .status-badge.completed {
    background: #d1fae5;
    color: #065f46;
  }

  .status-badge.failed {
    background: #fee2e2;
    color: #991b1b;
  }

  .note-section {
    margin-top: 1.5rem;
    padding-top: 1.5rem;
    border-top: 1px solid #e5e7eb;
  }

  .note-text {
    margin: 0.5rem 0 0 0;
    color: #374151;
    white-space: pre-wrap;
  }

  .recordings-link-card {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .link-content h3 {
    margin: 0 0 0.25rem 0;
    font-size: 1rem;
    font-weight: 600;
  }

  .link-content p {
    margin: 0;
    font-size: 0.875rem;
    color: #6b7280;
  }

  .btn-primary,
  .btn-secondary,
  .btn-danger,
  .btn-export {
    padding: 0.625rem 1.25rem;
    font-size: 0.875rem;
    font-weight: 500;
    border-radius: 0.375rem;
    cursor: pointer;
    transition: all 0.15s ease;
    text-decoration: none;
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
  }

  .btn-export {
    background: #10b981;
    color: white;
    border: none;
  }

  .btn-export:hover {
    background: #059669;
  }

  .btn-icon {
    width: 16px;
    height: 16px;
  }

  .btn-primary {
    background: #3b82f6;
    color: white;
    border: none;
  }

  .btn-primary:hover {
    background: #2563eb;
  }

  .btn-secondary {
    background: white;
    color: #374151;
    border: 1px solid #d1d5db;
  }

  .btn-secondary:hover {
    background: #f9fafb;
  }

  .btn-danger {
    background: white;
    color: #dc2626;
    border: 1px solid #fecaca;
  }

  .btn-danger:hover {
    background: #fef2f2;
    border-color: #f87171;
  }

  .btn-danger:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  /* Modal styles */
  .modal-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 50;
    padding: 1rem;
  }

  .modal {
    background: white;
    padding: 1.5rem;
    border-radius: 0.5rem;
    max-width: 500px;
    width: 100%;
    max-height: 90vh;
    overflow-y: auto;
  }

  .modal.large {
    max-width: 800px;
  }

  .modal h3 {
    margin: 0 0 1rem 0;
    font-size: 1.125rem;
    font-weight: 600;
  }

  .modal p {
    margin: 0 0 1.5rem 0;
    color: #4b5563;
  }

  .modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1.5rem;
  }

  .close-btn {
    background: none;
    border: none;
    font-size: 2rem;
    line-height: 1;
    color: #9ca3af;
    cursor: pointer;
    padding: 0;
    width: 2rem;
    height: 2rem;
  }

  .close-btn:hover {
    color: #4b5563;
  }

  .modal-body {
    margin-bottom: 1rem;
  }

  .modal-error {
    padding: 0.75rem;
    background: #fef2f2;
    border: 1px solid #fecaca;
    border-radius: 0.375rem;
    color: #dc2626;
    font-size: 0.875rem;
    margin-top: 1rem;
  }

  .modal-actions {
    display: flex;
    justify-content: flex-end;
    gap: 0.75rem;
  }
</style>
