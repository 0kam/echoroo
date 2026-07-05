<script lang="ts">
  /**
   * Custom Models page.
   *
   * Hub for managing trained custom SVM classifiers. Provides:
   * - Model list with status badges
   * - Detail view with metrics, hyperparameters, training stats
   * - Apply dialog (run model on another dataset)
   * - Delete dialog
   * - Navigation to source Search session
   *
   * Uses a 2-mode layout:
   * - 'list'   : Default view showing all models
   * - 'detail' : Full-width view for a single model with metrics and polling
   *
   * Model creation has been moved to the Search page.
   */

  import { page } from '$app/stores';
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import {
    fetchCustomModels,
    trainCustomModel,
    deleteCustomModel,
    getCustomModelStatus,
    applyCustomModel,
  } from '$lib/api/custom-models';
  import { fetchDatasets } from '$lib/api/datasets';
  import { toasts } from '$lib/stores/toast';
  import ModelListView from '$lib/components/models/ModelListView.svelte';
  import ModelDetailView from '$lib/components/models/ModelDetailView.svelte';
  import ApplyToDatasetDialog from '$lib/components/models/ApplyToDatasetDialog.svelte';
  import { useModelPolling } from '$lib/components/models/useModelPolling.svelte';

  const projectId = $derived($page.params.id as string);
  const queryClient = useQueryClient();

  // ============================================
  // View state
  // ============================================

  let viewMode = $state<'list' | 'detail'>('list');
  let selectedModelId = $state<string | null>(null);

  // Process deep-link (?model=<id>) only once on mount
  let initialDeepLinkProcessed = $state(false);
  $effect(() => {
    if (initialDeepLinkProcessed) return;
    initialDeepLinkProcessed = true;
    const modelParam = $page.url.searchParams.get('model');
    if (modelParam) {
      selectedModelId = modelParam;
      viewMode = 'detail';
    }
  });

  // ============================================
  // Delete confirmation state
  // ============================================

  let deletingModelId = $state<string | null>(null);

  // ============================================
  // Apply to Dataset dialog state
  // ============================================

  let showApplyDialog = $state(false);
  let applyDatasetId = $state('');
  let applyThreshold = $state(0.5);
  let applyError = $state<string | null>(null);

  // ============================================
  // Queries
  // ============================================

  const modelsQuery = $derived(
    createQuery({
      queryKey: ['custom-models', projectId],
      queryFn: () => fetchCustomModels(projectId),
      enabled: !!projectId,
      refetchInterval: false,
    })
  );

  const datasetsQuery = $derived(
    createQuery({
      queryKey: ['datasets', projectId, 'for-apply'],
      queryFn: () => fetchDatasets(projectId, { page_size: 200 }),
      enabled: showApplyDialog,
    })
  );

  const detailQuery = $derived(
    createQuery({
      queryKey: ['custom-model', projectId, selectedModelId],
      queryFn: () =>
        selectedModelId ? getCustomModelStatus(projectId, selectedModelId) : Promise.reject('No model selected'),
      enabled: !!selectedModelId && viewMode === 'detail',
      refetchOnWindowFocus: false,
    })
  );

  // ============================================
  // Training polling
  // ============================================

  const polling = useModelPolling({
    projectId: () => projectId,
    model: () => $detailQuery.data ?? null,
    onComplete: (modelId) => {
      // Invalidate list + detail so both refresh
      queryClient.invalidateQueries({ queryKey: ['custom-models', projectId] });
      queryClient.invalidateQueries({
        queryKey: ['custom-model', projectId, modelId],
      });
    },
  });

  // Use polled data if available (fresher than TanStack cache during training)
  const displayedModel = $derived(polling.polledModel ?? $detailQuery.data ?? null);

  // ============================================
  // Mutations
  // ============================================

  const trainMutationState = createMutation({
    mutationFn: (modelId: string) => trainCustomModel(projectId, modelId),
    onSuccess: (updated) => {
      queryClient.setQueryData(['custom-model', projectId, updated.id], updated);
      queryClient.invalidateQueries({ queryKey: ['custom-models', projectId] });
    },
  });

  const deleteMutationState = createMutation({
    mutationFn: (modelId: string) => deleteCustomModel(projectId, modelId),
    onSuccess: (_data, deletedId) => {
      deletingModelId = null;
      handleBackToList();
      queryClient.removeQueries({ queryKey: ['custom-model', projectId, deletedId] });
      queryClient.removeQueries({ queryKey: ['sampling-rounds', projectId, deletedId] });
      queryClient.invalidateQueries({ queryKey: ['custom-models', projectId] });
    },
    onError: () => {
      deletingModelId = null;
    },
  });

  const applyMutationState = createMutation({
    mutationFn: ({ modelId, datasetId, threshold }: { modelId: string; datasetId: string; threshold: number }) =>
      applyCustomModel(projectId, modelId, datasetId, threshold),
    onSuccess: (_data, variables) => {
      closeApplyDialog();
      // Immediate feedback: the job was queued. The RecentApplications panel
      // will poll and fire the completion/failure toast on status transition.
      toasts.success(m.models_apply_queued());
      // Force the RecentApplications panel to pick up the new run right away
      // rather than waiting for its next polling tick.
      queryClient.invalidateQueries({
        queryKey: ['custom-model-detection-runs', projectId, variables.modelId],
      });
    },
    onError: (err: Error) => {
      applyError = err.message;
    },
  });

  // ============================================
  // Handlers
  // ============================================

  function handleTrain(modelId: string) {
    $trainMutationState.mutate(modelId);
  }

  function handleDeleteRequest(modelId: string) {
    deletingModelId = modelId;
  }

  function handleDeleteConfirm() {
    const modelId = deletingModelId;
    if (!modelId) return;
    $deleteMutationState.mutate(modelId);
  }

  function handleDeleteCancel() {
    deletingModelId = null;
  }

  function openApplyDialog() {
    applyDatasetId = '';
    applyThreshold = 0.5;
    applyError = null;
    showApplyDialog = true;
  }

  function closeApplyDialog() {
    showApplyDialog = false;
  }

  function handleApply() {
    applyError = null;
    if (!applyDatasetId) {
      applyError = 'Select a dataset';
      return;
    }
    if (!selectedModelId) return;
    $applyMutationState.mutate({ modelId: selectedModelId, datasetId: applyDatasetId, threshold: applyThreshold });
  }

  function handleSelectModel(modelId: string) {
    selectedModelId = modelId;
    viewMode = 'detail';
    const url = new URL(window.location.href);
    url.searchParams.set('model', modelId);
    history.replaceState({}, '', url.toString());
  }

  function handleBackToList() {
    polling.reset();
    selectedModelId = null;
    viewMode = 'list';
    const url = new URL(window.location.href);
    url.searchParams.delete('model');
    history.replaceState({}, '', url.toString());
  }
</script>

<svelte:head>
  <title>{m.models_page_title()}</title>
</svelte:head>

<div class="mx-auto max-w-5xl px-4 py-6">

  <!-- Breadcrumb (always visible) -->
  <nav class="mb-4 flex items-center gap-2 text-sm text-stone-500">
    <a href={localizeHref(`/projects/${projectId}`)} class="hover:text-stone-900 dark:hover:text-stone-200">
      {m.search_breadcrumb_project()}
    </a>
    <span>/</span>
    {#if viewMode === 'detail' && displayedModel}
      <button
        type="button"
        class="hover:text-stone-900 dark:hover:text-stone-200"
        onclick={handleBackToList}
      >
        {m.models_title()}
      </button>
      <span>/</span>
      <span class="font-medium text-stone-900">{displayedModel.name}</span>
    {:else}
      <span class="font-medium text-stone-900">{m.models_title()}</span>
    {/if}
  </nav>

  <!-- ====================================================
       Mode: list
  ==================================================== -->
  {#if viewMode === 'list'}
    <ModelListView
      {projectId}
      isLoading={$modelsQuery.isLoading}
      isError={$modelsQuery.isError}
      models={$modelsQuery.data?.models}
      trainPending={$trainMutationState.isPending}
      onSelectModel={handleSelectModel}
      onTrain={handleTrain}
      onDeleteRequest={handleDeleteRequest}
    />

  <!-- ====================================================
       Mode: detail
  ==================================================== -->
  {:else if viewMode === 'detail'}
    <ModelDetailView
      {projectId}
      model={displayedModel}
      detailLoading={$detailQuery.isLoading}
      trainPending={$trainMutationState.isPending}
      trainVariables={$trainMutationState.variables}
      onBackToList={handleBackToList}
      onApply={openApplyDialog}
      onTrain={handleTrain}
      onDeleteRequest={handleDeleteRequest}
      onReviewTrainRequest={(id) =>
        queryClient.invalidateQueries({ queryKey: ['custom-model', projectId, id] })}
    />
  {/if}

</div>

<!-- ====================================================
     Apply to Dataset Dialog
==================================================== -->
{#if showApplyDialog}
  <ApplyToDatasetDialog
    datasetsLoading={$datasetsQuery.isLoading}
    datasets={$datasetsQuery.data?.items}
    bind:applyDatasetId
    bind:applyThreshold
    {applyError}
    pending={$applyMutationState.isPending}
    onClose={closeApplyDialog}
    onSubmit={handleApply}
  />
{/if}

<!-- ====================================================
     Delete Confirmation Dialog
==================================================== -->
{#if deletingModelId !== null}
  <div
    class="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm"
    onclick={handleDeleteCancel}
    onkeydown={(e) => e.key === 'Escape' && handleDeleteCancel()}
    role="button"
    tabindex="-1"
    aria-label="Close dialog"
  ></div>

  <div
    class="fixed left-1/2 top-1/2 z-50 w-full max-w-sm -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-card bg-surface-card p-6 shadow-2xl"
    role="alertdialog"
    aria-modal="true"
    aria-labelledby="delete-dialog-title"
  >
    <h2 id="delete-dialog-title" class="text-base font-semibold text-stone-900">
      {m.models_delete()}
    </h2>
    <p class="mt-2 text-sm text-stone-500">{m.models_delete_confirm()}</p>
    <div class="mt-5 flex justify-end gap-3">
      <button
        type="button"
        class="rounded-lg border border-stone-300 px-4 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50 dark:border-stone-600 dark:hover:bg-stone-800"
        onclick={handleDeleteCancel}
      >
        {m.models_cancel()}
      </button>
      <button
        type="button"
        class="inline-flex items-center gap-2 rounded-lg bg-danger px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-danger/90 disabled:opacity-50"
        onclick={handleDeleteConfirm}
        disabled={$deleteMutationState.isPending}
      >
        {#if $deleteMutationState.isPending}
          <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
          </svg>
        {/if}
        {m.models_delete()}
      </button>
    </div>
  </div>
{/if}
