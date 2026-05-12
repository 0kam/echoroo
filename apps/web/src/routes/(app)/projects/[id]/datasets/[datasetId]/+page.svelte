<script lang="ts">
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { fetchDataset, updateDataset, deleteDataset } from '$lib/api/datasets';
  import { projectsApi } from '$lib/api/projects';
  import { localizeHref, getLocale } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import type { DatasetUpdate } from '$lib/types/data';
  import { getDatasetStatusClass } from '$lib/utils/statusFormatters';
  import DatasetForm from '$lib/components/data/DatasetForm.svelte';
  import DatasetStatistics from '$lib/components/data/DatasetStatistics.svelte';
  import ImportProgress from '$lib/components/data/ImportProgress.svelte';
  import FileUpload from '$lib/components/data/FileUpload.svelte';
  import ExportDialog from '$lib/components/data/ExportDialog.svelte';
  import RecordingList from '$lib/components/data/RecordingList.svelte';
  import DeleteConfirmDialog from '$lib/components/ui/DeleteConfirmDialog.svelte';
  import MLAnalysisStatus from '$lib/components/data/MLAnalysisStatus.svelte';
  import EmbeddingStatus from '$lib/components/data/EmbeddingStatus.svelte';
  import DatetimeConfigCard from '$lib/components/data/DatetimeConfigCard.svelte';

  const queryClient = useQueryClient();

  const projectId = $derived($page.params.id as string);
  const datasetId = $derived($page.params.datasetId as string);

  const datasetQuery = $derived(
    createQuery({
      queryKey: ['dataset', projectId, datasetId],
      queryFn: () => fetchDataset(projectId, datasetId),
    })
  );

  // Phase 1 (spec/007): fetch project to resolve `current_user_role`
  // as the single source of truth for permission gating on this page.
  // TODO Phase 2B.3: replace the role comparisons below with `can()`
  //   - `manage_dataset_admin` (admin/owner) for Edit/Delete dataset
  //   - `manage_dataset` (member/admin/owner) for content actions
  //     (clip generation, annotation, etc.)
  const projectQuery = $derived(
    createQuery({
      queryKey: ['project', projectId],
      queryFn: () => projectsApi.get(projectId),
    })
  );

  const currentUserRole = $derived($projectQuery.data?.current_user_role ?? null);

  // TODO Phase 2B.3: replace with can('manage_dataset_admin', ctx)
  const canManageDatasetAdmin = $derived(
    currentUserRole === 'owner' || currentUserRole === 'admin'
  );

  // TODO Phase 2B.3: replace with can('manage_dataset', ctx)
  const canManageDatasetContent = $derived(
    currentUserRole === 'owner' ||
      currentUserRole === 'admin' ||
      currentUserRole === 'member'
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
      goto(localizeHref(`/projects/${projectId}/datasets`));
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
    return new Date(dateStr).toLocaleString(getLocale());
  }

  const deleteWarnings = $derived(
    $datasetQuery.data
      ? [
          m.dataset_detail_delete_warnings_recordings({ count: $datasetQuery.data.recording_count || 0 }),
          m.dataset_detail_delete_warnings_annotations(),
        ]
      : []
  );


</script>

<svelte:head>
  <title>{$datasetQuery.data ? m.dataset_detail_page_title({ name: $datasetQuery.data.name }) : m.dataset_detail_loading()}</title>
</svelte:head>

<div class="mx-auto max-w-5xl space-y-6 px-6 py-8">
  {#if $datasetQuery.isLoading}
    <div class="flex items-center justify-center py-12 text-sm text-stone-500">
      <svg class="mr-2 h-5 w-5 animate-spin text-primary-600" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      {m.dataset_detail_loading()}
    </div>
  {:else if $datasetQuery.isError}
    <div class="rounded-md border border-danger/20 bg-danger-light px-4 py-3 text-sm text-danger">
      Error: {$datasetQuery.error?.message}
    </div>
  {:else if $datasetQuery.data}
    {@const dataset = $datasetQuery.data}

    <!-- Header -->
    <div>
      <nav class="mb-2 flex items-center gap-2 text-sm text-stone-500">
        <a href={localizeHref(`/projects/${projectId}`)} class="hover:text-stone-900">{m.dataset_detail_breadcrumb_project()}</a>
        <span>/</span>
        <a href={localizeHref(`/projects/${projectId}/datasets`)} class="hover:text-stone-900">{m.dataset_detail_breadcrumb_datasets()}</a>
        <span>/</span>
        <span class="font-medium text-stone-900">{dataset.name}</span>
      </nav>

      <div class="flex items-start justify-between gap-4">
        <div>
          <h1 class="text-2xl font-bold text-stone-900">{dataset.name}</h1>
          {#if dataset.description}
            <p class="mt-1 text-sm text-stone-500">{dataset.description}</p>
          {/if}
        </div>
        <div class="flex flex-shrink-0 gap-2">
          <!-- TODO Phase 2B.3: replace with can('manage_dataset', ctx) -->
          {#if dataset.status === 'completed' && canManageDatasetContent}
            <button
              onclick={() => (showExportDialog = true)}
              class="flex items-center gap-2 rounded-md bg-success px-3 py-2 text-sm font-medium text-white transition-colors hover:opacity-90"
            >
              <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" stroke-width="2" />
                <polyline points="7 10 12 15 17 10" stroke-width="2" />
                <line x1="12" y1="15" x2="12" y2="3" stroke-width="2" />
              </svg>
              {m.dataset_detail_export_button()}
            </button>
          {/if}
          <!-- TODO Phase 2B.3: replace with can('manage_dataset_admin', ctx) -->
          {#if canManageDatasetAdmin}
            <button
              onclick={() => (showEditModal = true)}
              class="rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50"
            >
              {m.dataset_detail_edit_button()}
            </button>
            <button
              onclick={() => (showDeleteConfirm = true)}
              class="rounded-md border border-danger/20 bg-surface-card px-3 py-2 text-sm font-medium text-danger transition-colors hover:bg-danger-light"
            >
              {m.dataset_detail_delete_button()}
            </button>
          {/if}
        </div>
      </div>
    </div>

    <!-- Dataset info card -->
    <div class="rounded-lg border border-card bg-surface-card p-6">
      <h2 class="mb-4 text-sm font-semibold uppercase tracking-wider text-stone-500">{m.dataset_detail_info_heading()}</h2>
      <div class="grid grid-cols-2 gap-4 sm:grid-cols-3">
        <div class="flex flex-col gap-1">
          <span class="text-xs font-medium uppercase tracking-wider text-stone-400">{m.dataset_detail_site_label()}</span>
          <span class="text-sm text-stone-900">
            {#if dataset.site}
              <a href={localizeHref(`/projects/${projectId}/sites/${dataset.site.id}`)} class="text-primary-600 hover:underline">
                {dataset.site.name}
              </a>
            {:else}
              <span class="text-stone-400">{m.dataset_detail_site_na()}</span>
            {/if}
          </span>
        </div>

        <div class="flex flex-col gap-1">
          <span class="text-xs font-medium uppercase tracking-wider text-stone-400">{m.dataset_detail_status_label()}</span>
          <span class="inline-flex w-fit items-center rounded px-2 py-0.5 text-xs font-medium capitalize {getDatasetStatusClass(dataset.status)}">
            {dataset.status}
          </span>
        </div>

        <div class="flex flex-col gap-1">
          <span class="text-xs font-medium uppercase tracking-wider text-stone-400">{m.dataset_detail_visibility_label()}</span>
          <span class="text-sm text-stone-900 capitalize">{dataset.visibility}</span>
        </div>

        {#if dataset.recorder}
          <div class="flex flex-col gap-1">
            <span class="text-xs font-medium uppercase tracking-wider text-stone-400">{m.dataset_detail_recorder_label()}</span>
            <span class="text-sm text-stone-900">{dataset.recorder.manufacturer} {dataset.recorder.recorder_name}</span>
          </div>
        {/if}

        {#if dataset.license}
          <div class="flex flex-col gap-1">
            <span class="text-xs font-medium uppercase tracking-wider text-stone-400">{m.dataset_detail_license_label()}</span>
            <span class="text-sm text-stone-900">{dataset.license.name} ({dataset.license.short_name})</span>
          </div>
        {/if}

        {#if dataset.doi}
          <div class="flex flex-col gap-1">
            <span class="text-xs font-medium uppercase tracking-wider text-stone-400">{m.dataset_detail_doi_label()}</span>
            <a href="https://doi.org/{dataset.doi}" target="_blank" rel="noopener noreferrer" class="text-sm text-primary-600 hover:underline">
              {dataset.doi}
            </a>
          </div>
        {/if}

        {#if dataset.gain !== null}
          <div class="flex flex-col gap-1">
            <span class="text-xs font-medium uppercase tracking-wider text-stone-400">{m.dataset_detail_gain_label()}</span>
            <span class="text-sm text-stone-900">{dataset.gain} dB</span>
          </div>
        {/if}

        <div class="flex flex-col gap-1">
          <span class="text-xs font-medium uppercase tracking-wider text-stone-400">{m.dataset_detail_created_label()}</span>
          <span class="text-sm text-stone-900">{formatDateTime(dataset.created_at)}</span>
        </div>

        {#if dataset.created_by}
          <div class="flex flex-col gap-1">
            <span class="text-xs font-medium uppercase tracking-wider text-stone-400">{m.dataset_detail_created_by_label()}</span>
            <span class="text-sm text-stone-900">{dataset.created_by.display_name || dataset.created_by.username}</span>
          </div>
        {/if}
      </div>

      {#if dataset.note}
        <div class="mt-4 border-t border-stone-100 pt-4">
          <span class="mb-1 block text-xs font-medium uppercase tracking-wider text-stone-400">{m.dataset_detail_note_label()}</span>
          <p class="whitespace-pre-wrap text-sm text-stone-700">{dataset.note}</p>
        </div>
      {/if}
    </div>

    <!-- Import Progress (not shown when pending - FileUpload handles the full flow) -->
    {#if dataset.status !== 'pending'}
      <ImportProgress {projectId} {datasetId} currentStatus={dataset.status} />
    {/if}

    <!-- File Upload (available when dataset is pending or completed) -->
    <!-- TODO Phase 2B.3: replace with can('manage_dataset', ctx) -->
    {#if (dataset.status === 'pending' || dataset.status === 'completed') && canManageDatasetContent}
      <FileUpload
        {projectId}
        {datasetId}
        onComplete={() => {
          queryClient.invalidateQueries({ queryKey: ['dataset', projectId, datasetId] });
        }}
      />
    {/if}

    <!-- Datetime parsing configuration (show when recordings exist) -->
    <!-- TODO Phase 2B.3: replace with can('manage_dataset', ctx) -->
    {#if dataset.recording_count > 0 && canManageDatasetContent}
      <DatetimeConfigCard {projectId} {datasetId} />
    {/if}

    <!-- ML Detection Status (only if dataset import is complete) -->
    {#if dataset.status === 'completed'}
      <MLAnalysisStatus {projectId} {datasetId} />
    {/if}

    <!-- Embedding Generation Status (only if dataset import is complete) -->
    {#if dataset.status === 'completed'}
      <EmbeddingStatus {projectId} {datasetId} />
    {/if}

    <!-- Statistics (only if completed) -->
    {#if dataset.status === 'completed'}
      <DatasetStatistics {projectId} {datasetId} />
    {/if}

    <!-- Recordings list (show when recordings exist) -->
    {#if dataset.recording_count > 0}
      <div class="rounded-lg border border-card bg-surface-card p-6">
        <div class="mb-4">
          <h3 class="text-base font-semibold text-stone-900">{m.dataset_detail_recordings_heading()}</h3>
          <p class="mt-0.5 text-sm text-stone-500">{m.dataset_detail_recordings_count({ count: dataset.recording_count })}</p>
        </div>
        <RecordingList
          {projectId}
          {datasetId}
          onSelect={(recordingId) => goto(localizeHref(`/projects/${projectId}/recordings/${recordingId}`))}
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
      class="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-lg bg-surface-card"
      onclick={(e) => e.stopPropagation()}
      role="document"
    >
      <div class="flex items-center justify-between border-b border-stone-200 px-6 py-4">
        <h3 id="edit-dataset-title" class="m-0 text-lg font-semibold text-stone-900">{m.dataset_detail_edit_modal_title()}</h3>
        <button
          onclick={() => (showEditModal = false)}
          class="rounded p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-600"
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
        <div class="mx-6 mb-4 rounded-md border border-danger/20 bg-danger-light px-3 py-2 text-sm text-danger">
          {$updateMutation.error?.message || 'Failed to update dataset'}
        </div>
      {/if}
    </div>
  </div>
{/if}

<!-- Delete Confirmation Dialog -->
<DeleteConfirmDialog
  isOpen={showDeleteConfirm}
  title={m.dataset_detail_delete_title()}
  message={m.dataset_detail_delete_message({ name: $datasetQuery.data?.name ?? '' })}
  warnings={deleteWarnings}
  confirmText={m.dataset_detail_delete_confirm()}
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
