<script lang="ts">
  /**
   * Custom Models page.
   *
   * Allows users to create, train, and manage custom SVM classifiers
   * trained on labeled similarity search session data.
   *
   * Uses a 2-mode layout:
   * - 'list'   : Default view showing all models with create button
   * - 'detail' : Full-width view for a single model with metrics and polling
   */

  import { flushSync, onDestroy } from 'svelte';
  import { page } from '$app/stores';
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import {
    fetchCustomModels,
    createCustomModel,
    trainCustomModel,
    deleteCustomModel,
    getCustomModelStatus,
    applyCustomModel,
    generateAuditSet,
    getAuditSet,
    evaluateAuditSet,
  } from '$lib/api/custom-models';
  import { fetchTags } from '$lib/api/tags';
  import { fetchDatasets } from '$lib/api/datasets';
  import { toasts } from '$lib/stores/toast';
  import type { CustomModel, CustomModelListItem, CustomModelCreate, AuditMetrics } from '$lib/types/custom-model';
  import type { Tag } from '$lib/types/annotation';
  import { getCustomModelStatusClass, getCustomModelStatusLabel } from '$lib/utils/statusFormatters';
  import ReviewTab from '$lib/components/models/ReviewTab.svelte';

  const projectId = $derived($page.params.id as string);
  const queryClient = useQueryClient();

  // ============================================
  // View state
  // ============================================

  /** Top-level tab: 'models' shows the model list/detail, 'review' shows the review interface */
  let activeTab = $state<'models' | 'review'>('models');

  let viewMode = $state<'list' | 'detail'>('list');
  let selectedModelId = $state<string | null>(null);

  // ============================================
  // Create model dialog state
  // ============================================

  let showCreateDialog = $state(false);
  let createName = $state('');
  let createDescription = $state('');
  let createTargetTagId = $state('');
  let createEmbeddingModel = $state('perch');
  let createError = $state<string | null>(null);

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
  // Audit set state
  // ============================================

  /** Active metrics tab in the detail view: 'internal' or 'audit' */
  let metricsTab = $state<'internal' | 'audit'>('internal');

  // ============================================
  // Training polling state
  // ============================================

  let pollingInterval = $state<ReturnType<typeof setInterval> | null>(null);
  let polledModel = $state<CustomModel | null>(null);

  function stopPolling() {
    if (pollingInterval !== null) {
      clearInterval(pollingInterval);
      pollingInterval = null;
    }
  }

  onDestroy(() => {
    stopPolling();
  });

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

  const tagsQuery = $derived(
    createQuery({
      queryKey: ['tags', projectId],
      queryFn: () => fetchTags(projectId, { page_size: 200 }),
      enabled: showCreateDialog,
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

  const auditSetQuery = $derived(
    createQuery({
      queryKey: ['audit-set', projectId, selectedModelId],
      queryFn: () =>
        selectedModelId ? getAuditSet(projectId, selectedModelId) : Promise.reject('No model selected'),
      enabled: !!selectedModelId && viewMode === 'detail',
      refetchOnWindowFocus: false,
    })
  );

  // Start polling when a model is training
  $effect(() => {
    const model = $detailQuery.data;
    if (model?.status === 'training') {
      if (pollingInterval === null) {
        pollingInterval = setInterval(async () => {
          try {
            const updated = await getCustomModelStatus(projectId, model.id);
            polledModel = updated;
            if (updated.status !== 'training') {
              stopPolling();
              // Invalidate list + detail so both refresh
              queryClient.invalidateQueries({ queryKey: ['custom-models', projectId] });
              queryClient.invalidateQueries({
                queryKey: ['custom-model', projectId, model.id],
              });
            }
          } catch (err) {
            console.warn('Model status polling error:', err);
          }
        }, 3000);
      }
    } else {
      stopPolling();
      polledModel = null;
    }
  });

  // Use polled data if available (fresher than TanStack cache during training)
  const displayedModel = $derived(polledModel ?? $detailQuery.data ?? null);

  // ============================================
  // Mutations
  // ============================================

  const createMutationState = createMutation({
    mutationFn: (data: CustomModelCreate) => createCustomModel(projectId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['custom-models', projectId] });
      closeCreateDialog();
    },
    onError: (err: Error) => {
      createError = err.message;
    },
  });

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
      queryClient.removeQueries({ queryKey: ['audit-set', projectId, deletedId] });
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
    onSuccess: () => {
      closeApplyDialog();
      toasts.success(m.models_apply_success());
    },
    onError: (err: Error) => {
      applyError = err.message;
    },
  });

  const generateAuditSetMutation = createMutation({
    mutationFn: (modelId: string) => generateAuditSet(projectId, modelId),
    onSuccess: () => {
      // Refresh the audit set list after generation is dispatched
      queryClient.invalidateQueries({ queryKey: ['audit-set', projectId, selectedModelId] });
      toasts.success('Audit set generation dispatched. Items will appear shortly.');
    },
    onError: (err: Error) => {
      toasts.error(`Failed to generate audit set: ${err.message}`);
    },
  });

  const evaluateAuditSetMutation = createMutation({
    mutationFn: (modelId: string) => evaluateAuditSet(projectId, modelId),
    onSuccess: (_metrics: AuditMetrics) => {
      // Refresh the model detail to show updated audit_metrics
      queryClient.invalidateQueries({ queryKey: ['custom-model', projectId, selectedModelId] });
      toasts.success('Audit evaluation complete. Metrics updated.');
    },
    onError: (err: Error) => {
      toasts.error(`Evaluation failed: ${err.message}`);
    },
  });

  // ============================================
  // Handlers
  // ============================================

  function openCreateDialog() {
    createName = '';
    createDescription = '';
    createTargetTagId = '';
    createEmbeddingModel = 'perch';
    createError = null;
    showCreateDialog = true;
  }

  /** Called from ReviewTab when user clicks "Train Custom Model" */
  function handleReviewTrainRequest(_sessionId: string) {
    openCreateDialog();
  }

  function closeCreateDialog() {
    showCreateDialog = false;
  }

  function handleCreate() {
    createError = null;
    if (!createName.trim()) {
      createError = 'Model name is required';
      return;
    }
    if (!createTargetTagId) {
      createError = 'Target species tag is required';
      return;
    }

    const payload: CustomModelCreate = {
      name: createName.trim(),
      description: createDescription.trim() || undefined,
      target_tag_id: createTargetTagId,
      embedding_model_name: createEmbeddingModel,
    };

    $createMutationState.mutate(payload);
  }

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
  }

  function handleBackToList() {
    stopPolling();
    polledModel = null;
    selectedModelId = null;
    viewMode = 'list';
    metricsTab = 'internal';
  }

  // ============================================
  // Helpers
  // ============================================

  function statusLabel(status: string): string {
    return getCustomModelStatusLabel(status, {
      draft: m.models_status_draft,
      training: m.models_status_training,
      trained: m.models_status_trained,
      deployed: m.models_status_deployed,
      failed: m.models_status_failed,
    });
  }

  function statusClasses(status: string): string {
    return getCustomModelStatusClass(status);
  }

  function formatDuration(seconds: number): string {
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    return `${mins}m ${secs}s`;
  }

  function formatPercent(value: number): string {
    return `${(value * 100).toFixed(1)}%`;
  }

  function formatDate(iso: string): string {
    return new Date(iso).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  }

  function getTagName(tagId: string | null, tags: Tag[]): string {
    if (!tagId) return m.models_no_target_species();
    const tag = tags.find((t) => t.id === tagId);
    if (!tag) return tagId;
    return tag.scientific_name ?? tag.name;
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
    {#if activeTab === 'models' && viewMode === 'detail' && displayedModel}
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

  <!-- Tab bar -->
  {#if !(activeTab === 'models' && viewMode === 'detail')}
    <div class="mb-6 flex border-b border-stone-200 dark:border-stone-700">
      <button
        type="button"
        class="relative px-4 py-2.5 text-sm font-medium transition-colors focus:outline-none
          {activeTab === 'models'
            ? 'text-primary-600 dark:text-primary-400'
            : 'text-stone-500 hover:text-stone-800 dark:hover:text-stone-200'}"
        onclick={() => { activeTab = 'models'; }}
        aria-selected={activeTab === 'models'}
        role="tab"
      >
        {m.models_tab_models()}
        {#if activeTab === 'models'}
          <span class="absolute bottom-0 left-0 right-0 h-0.5 rounded-t bg-primary-500"></span>
        {/if}
      </button>
      <button
        type="button"
        class="relative px-4 py-2.5 text-sm font-medium transition-colors focus:outline-none
          {activeTab === 'review'
            ? 'text-primary-600 dark:text-primary-400'
            : 'text-stone-500 hover:text-stone-800 dark:hover:text-stone-200'}"
        onclick={() => { activeTab = 'review'; }}
        aria-selected={activeTab === 'review'}
        role="tab"
      >
        {m.models_tab_review()}
        {#if activeTab === 'review'}
          <span class="absolute bottom-0 left-0 right-0 h-0.5 rounded-t bg-primary-500"></span>
        {/if}
      </button>
    </div>
  {/if}

  <!-- ====================================================
       Tab: Review
  ==================================================== -->
  {#if activeTab === 'review'}
    <ReviewTab
      {projectId}
      modelId={selectedModelId ?? undefined}
      onTrainRequest={handleReviewTrainRequest}
    />

  <!-- ====================================================
       Tab: Models
  ==================================================== -->
  {:else}

  <!-- ====================================================
       Mode: list
  ==================================================== -->
  {#if viewMode === 'list'}
    <div class="space-y-6">

      <!-- Page header -->
      <div class="flex items-start justify-between">
        <div>
          <h1 class="text-2xl font-bold text-stone-900">{m.models_title()}</h1>
          <p class="mt-1 text-sm text-stone-500">{m.models_description()}</p>
        </div>
        <button
          type="button"
          class="inline-flex items-center gap-2 rounded-lg bg-primary-600 dark:bg-primary-300 px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-primary-700 dark:hover:bg-primary-200 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2"
          onclick={() => openCreateDialog()}
        >
          <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
          </svg>
          {m.models_create()}
        </button>
      </div>

      <!-- Model list -->
      {#if $modelsQuery.isLoading}
        <div class="flex items-center gap-2 text-sm text-stone-400">
          <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
          </svg>
          {m.nav_loading()}
        </div>

      {:else if $modelsQuery.isError}
        <div class="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-400">
          Failed to load models. Please refresh the page.
        </div>

      {:else if $modelsQuery.data && $modelsQuery.data.models.length === 0}
        <!-- Empty state -->
        <div class="rounded-xl border-2 border-dashed border-stone-200 bg-surface-card p-12 text-center dark:border-stone-700">
          <svg class="mx-auto h-12 w-12 text-stone-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
          </svg>
          <h2 class="mt-4 text-base font-semibold text-stone-700">{m.models_no_models()}</h2>
          <p class="mt-1 text-sm text-stone-500">{m.models_description()}</p>
          <button
            type="button"
            class="mt-6 inline-flex items-center gap-2 rounded-lg bg-primary-600 dark:bg-primary-300 px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-primary-700 dark:hover:bg-primary-200"
            onclick={() => openCreateDialog()}
          >
            <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
            </svg>
            {m.models_create()}
          </button>
        </div>

      {:else if $modelsQuery.data}
        <div class="space-y-3">
          {#each $modelsQuery.data.models as model (model.id)}
            <div
              class="cursor-pointer rounded-xl border border-card bg-surface-card p-5 shadow-sm transition-shadow hover:shadow-md"
              onclick={() => handleSelectModel(model.id)}
              onkeydown={(e) => e.key === 'Enter' && handleSelectModel(model.id)}
              role="button"
              tabindex="0"
            >
              <div class="flex items-start justify-between gap-4">
                <!-- Left: name + description + tags -->
                <div class="min-w-0 flex-1">
                  <div class="flex flex-wrap items-center gap-2">
                    <h2 class="text-base font-semibold text-stone-900">
                      {model.name}
                    </h2>
                    <!-- Status badge -->
                    <span class="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium {statusClasses(model.status)}">
                      {#if model.status === 'training'}
                        <svg class="h-3 w-3 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                        </svg>
                      {/if}
                      {statusLabel(model.status)}
                    </span>
                    <!-- Embedding model -->
                    <span class="rounded-full bg-stone-100 px-2 py-0.5 text-xs text-stone-500 dark:bg-stone-800">
                      {model.embedding_model_name}
                    </span>
                  </div>

                  {#if model.description}
                    <p class="mt-1 text-sm text-stone-500 line-clamp-2">{model.description}</p>
                  {/if}

                  <p class="mt-1.5 text-xs text-stone-400">
                    {m.models_created_at()} {formatDate(model.created_at)}
                    {#if model.completed_at}
                      &middot; {m.models_trained_at()} {formatDate(model.completed_at)}
                    {/if}
                  </p>
                </div>

                <!-- Right: action buttons -->
                <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
                <div class="flex shrink-0 items-center gap-2" onclick={(e) => e.stopPropagation()} role="group">
                  {#if model.status === 'draft' || model.status === 'failed'}
                    <button
                      type="button"
                      class="inline-flex items-center gap-1.5 rounded-lg border border-primary-300 bg-primary-50 px-3 py-1.5 text-xs font-medium text-primary-700 transition-colors hover:bg-primary-100 dark:border-primary-700 dark:bg-primary-900/20 dark:text-primary-400 dark:hover:bg-primary-900/40 disabled:opacity-50"
                      onclick={() => handleTrain(model.id)}
                      disabled={$trainMutationState.isPending}
                    >
                      <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                      {m.models_train()}
                    </button>
                  {/if}
                  <button
                    type="button"
                    class="rounded-lg p-1.5 text-stone-400 transition-colors hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/30"
                    onclick={() => handleDeleteRequest(model.id)}
                    aria-label={m.models_delete()}
                  >
                    <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                </div>
              </div>
            </div>
          {/each}
        </div>
      {/if}
    </div>

  <!-- ====================================================
       Mode: detail
  ==================================================== -->
  {:else if viewMode === 'detail'}
    <div class="space-y-6">
      <!-- Back link -->
      <button
        type="button"
        class="inline-flex items-center gap-1.5 text-sm text-stone-500 transition-colors hover:text-stone-900 dark:hover:text-stone-100"
        onclick={handleBackToList}
      >
        <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <path d="M19 12H5M12 19l-7-7 7-7" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
        {m.models_back_to_list()}
      </button>

      {#if $detailQuery.isLoading && !displayedModel}
        <div class="flex items-center gap-2 text-sm text-stone-400">
          <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
          </svg>
          {m.nav_loading()}
        </div>

      {:else if displayedModel}
        {@const model = displayedModel}

        <!-- Model header -->
        <div class="rounded-xl border border-card bg-surface-card p-6 shadow-sm">
          <div class="flex items-start justify-between gap-4">
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2">
                <h1 class="text-2xl font-bold text-stone-900">{model.name}</h1>
                <span class="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium {statusClasses(model.status)}">
                  {#if model.status === 'training'}
                    <svg class="h-3 w-3 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                    </svg>
                  {/if}
                  {statusLabel(model.status)}
                </span>
              </div>

              {#if model.description}
                <p class="mt-2 text-sm text-stone-500">{model.description}</p>
              {/if}

              <dl class="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-stone-400">
                <div class="flex items-center gap-1">
                  <dt class="font-medium">{m.models_embedding_model()}:</dt>
                  <dd>{model.embedding_model_name}</dd>
                </div>
                <div class="flex items-center gap-1">
                  <dt class="font-medium">{m.models_created_at()}:</dt>
                  <dd>{formatDate(model.created_at)}</dd>
                </div>
                {#if model.completed_at}
                  <div class="flex items-center gap-1">
                    <dt class="font-medium">{m.models_trained_at()}:</dt>
                    <dd>{formatDate(model.completed_at)}</dd>
                  </div>
                {/if}
              </dl>
            </div>

            <!-- Actions -->
            <div class="flex shrink-0 flex-wrap gap-2">
              {#if model.status === 'trained' || model.status === 'deployed'}
                <button
                  type="button"
                  class="inline-flex items-center gap-2 rounded-lg border border-success/40 bg-success-light px-4 py-2 text-sm font-medium text-success transition-colors hover:bg-success/20"
                  onclick={openApplyDialog}
                >
                  <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  {m.models_apply()}
                </button>
              {/if}
              {#if model.status === 'draft' || model.status === 'failed'}
                <button
                  type="button"
                  class="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:opacity-50"
                  onclick={() => handleTrain(model.id)}
                  disabled={$trainMutationState.isPending}
                >
                  {#if $trainMutationState.isPending && $trainMutationState.variables === model.id}
                    <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                    </svg>
                    {m.models_training()}
                  {:else}
                    {m.models_train()}
                  {/if}
                </button>
              {/if}
              <button
                type="button"
                class="inline-flex items-center gap-2 rounded-lg border border-danger/40 px-4 py-2 text-sm font-medium text-danger transition-colors hover:bg-danger-light"
                onclick={() => handleDeleteRequest(model.id)}
              >
                {m.models_delete()}
              </button>
            </div>
          </div>
        </div>

        <!-- Training in progress notice -->
        {#if model.status === 'training'}
          <div class="flex items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-700 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-400">
            <svg class="h-4 w-4 shrink-0 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
            <span>{m.models_status_training()} Polling for updates every 3 seconds...</span>
          </div>
        {/if}

        <!-- Error message -->
        {#if model.error_message}
          <div class="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-400">
            <span class="font-medium">{m.models_error_prefix()}</span> {model.error_message}
          </div>
        {/if}

        <!-- Metrics (only shown when trained) -->
        {#if model.metrics || model.audit_metrics}
          <!-- Metrics tab bar -->
          <div class="flex gap-1 rounded-xl border border-card bg-surface-card p-1 shadow-sm">
            <button
              type="button"
              class="flex-1 rounded-lg px-4 py-2 text-sm font-medium transition-colors focus:outline-none
                {metricsTab === 'internal'
                  ? 'bg-primary-50 text-primary-700 dark:bg-primary-900/30 dark:text-primary-300'
                  : 'text-stone-500 hover:text-stone-800 dark:hover:text-stone-200'}"
              onclick={() => { metricsTab = 'internal'; }}
            >
              Internal Validation
            </button>
            <button
              type="button"
              class="flex-1 rounded-lg px-4 py-2 text-sm font-medium transition-colors focus:outline-none
                {metricsTab === 'audit'
                  ? 'bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300'
                  : 'text-stone-500 hover:text-stone-800 dark:hover:text-stone-200'}"
              onclick={() => { metricsTab = 'audit'; }}
            >
              Blind Audit
              {#if model.audit_metrics}
                <span class="ml-1.5 rounded-full bg-amber-100 px-1.5 py-0.5 text-xs text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
                  evaluated
                </span>
              {/if}
            </button>
          </div>

          <!-- Internal Validation panel -->
          {#if metricsTab === 'internal'}
            {#if model.metrics}
              {@const metrics = model.metrics}
              <div class="rounded-xl border border-card bg-surface-card p-6 shadow-sm">
                <div class="mb-5 flex flex-wrap items-center gap-2">
                  <h2 class="text-sm font-semibold uppercase tracking-wider text-stone-500">
                    Internal Validation
                  </h2>
                  {#if metrics.cv_method}
                    <span class="rounded-full bg-stone-100 px-2 py-0.5 text-xs text-stone-500 dark:bg-stone-800">
                      {metrics.cv_method}
                    </span>
                  {/if}
                </div>

                {#if metrics.cv_warning}
                  <div class="mb-4 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-700 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-400">
                    <svg class="mt-0.5 h-3.5 w-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                    </svg>
                    {metrics.cv_warning}
                  </div>
                {/if}

                <!-- Primary metric bars -->
                <div class="space-y-4">
                  {#each [
                    { label: m.models_metrics_f1(), value: metrics.f1 },
                    { label: m.models_metrics_auc_roc(), value: metrics.roc_auc },
                    { label: m.models_metrics_pr_auc(), value: metrics.pr_auc },
                    { label: m.models_metrics_accuracy(), value: metrics.accuracy },
                    { label: m.models_metrics_precision(), value: metrics.precision },
                    { label: m.models_metrics_recall(), value: metrics.recall },
                  ] as metric}
                    <div>
                      <div class="mb-1 flex items-center justify-between text-sm">
                        <span class="font-medium text-stone-700">{metric.label}</span>
                        <span class="font-mono text-stone-900">{formatPercent(metric.value as number)}</span>
                      </div>
                      <div class="h-2 w-full overflow-hidden rounded-full bg-stone-100 dark:bg-stone-800">
                        <div
                          class="h-full rounded-full bg-primary-500 transition-all"
                          style="width: {((metric.value as number) * 100).toFixed(1)}%"
                        ></div>
                      </div>
                    </div>
                  {/each}
                </div>
              </div>

              <!-- Confusion matrix + hyperparameters -->
              <div class="grid gap-4 sm:grid-cols-2">
                <!-- Confusion matrix -->
                <div class="rounded-xl border border-card bg-surface-card p-6 shadow-sm">
                  <h2 class="mb-4 text-sm font-semibold uppercase tracking-wider text-stone-500">
                    {m.models_detail_confusion_matrix()}
                  </h2>
                  {#if metrics.confusion_matrix}
                    {@const [[tn, fp], [fn, tp]] = metrics.confusion_matrix}
                    <div class="grid grid-cols-2 gap-2 text-center text-sm">
                      <div class="rounded-lg bg-green-50 p-3 dark:bg-green-950/30">
                        <p class="text-xs font-medium text-green-600 dark:text-green-400">{m.models_detail_true_positive()}</p>
                        <p class="mt-1 text-xl font-bold text-green-700 dark:text-green-300">{tp}</p>
                      </div>
                      <div class="rounded-lg bg-red-50 p-3 dark:bg-red-950/30">
                        <p class="text-xs font-medium text-red-600 dark:text-red-400">{m.models_detail_false_positive()}</p>
                        <p class="mt-1 text-xl font-bold text-red-700 dark:text-red-300">{fp}</p>
                      </div>
                      <div class="rounded-lg bg-red-50 p-3 dark:bg-red-950/30">
                        <p class="text-xs font-medium text-red-600 dark:text-red-400">{m.models_detail_false_negative()}</p>
                        <p class="mt-1 text-xl font-bold text-red-700 dark:text-red-300">{fn}</p>
                      </div>
                      <div class="rounded-lg bg-green-50 p-3 dark:bg-green-950/30">
                        <p class="text-xs font-medium text-green-600 dark:text-green-400">{m.models_detail_true_negative()}</p>
                        <p class="mt-1 text-xl font-bold text-green-700 dark:text-green-300">{tn}</p>
                      </div>
                    </div>
                  {/if}
                </div>

                <!-- Hyperparameters -->
                <div class="rounded-xl border border-card bg-surface-card p-6 shadow-sm">
                  <h2 class="mb-4 text-sm font-semibold uppercase tracking-wider text-stone-500">
                    {m.models_detail_hyperparameters()}
                  </h2>
                  <dl class="space-y-2 text-sm">
                    {#if model.hyperparameters?.best_c !== undefined}
                      <div class="flex items-center justify-between">
                        <dt class="text-stone-500">{m.models_detail_best_c()}</dt>
                        <dd class="font-mono font-semibold text-stone-900">{model.hyperparameters.best_c}</dd>
                      </div>
                    {/if}
                  </dl>
                  {#if model.hyperparameters}
                    {#each Object.entries(model.hyperparameters).filter(([k]) => k !== 'best_c') as [key, value]}
                      <dl class="mt-2 space-y-2 text-sm">
                        <div class="flex items-center justify-between">
                          <dt class="text-stone-500">{key}</dt>
                          <dd class="font-mono font-semibold text-stone-900">{String(value)}</dd>
                        </div>
                      </dl>
                    {/each}
                  {/if}
                </div>
              </div>
            {/if}
          {/if}

          <!-- Blind Audit panel -->
          {#if metricsTab === 'audit'}
            <div class="rounded-xl border border-amber-200 bg-surface-card p-6 shadow-sm dark:border-amber-800/40">
              <div class="mb-5 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 class="text-sm font-semibold uppercase tracking-wider text-amber-700 dark:text-amber-400">
                    Blind Audit — Independent Evaluation
                  </h2>
                  <p class="mt-1 text-xs text-stone-500">
                    Score-stratified sample of unseen clips reviewed by a human annotator.
                  </p>
                </div>

                <!-- Audit set progress + actions -->
                {#if $auditSetQuery.data}
                  {@const auditItems = $auditSetQuery.data.items}
                  {@const reviewedCount = auditItems.filter(i => i.review_status === 'confirmed' || i.review_status === 'rejected').length}
                  <div class="flex items-center gap-3">
                    <span class="text-xs text-stone-500">
                      {reviewedCount}/{auditItems.length} reviewed
                    </span>
                    {#if auditItems.length === 0 && model.status === 'trained'}
                      <button
                        type="button"
                        class="inline-flex items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-700 transition-colors hover:bg-amber-100 dark:border-amber-700 dark:bg-amber-900/20 dark:text-amber-400 dark:hover:bg-amber-900/40 disabled:opacity-50"
                        onclick={() => selectedModelId && $generateAuditSetMutation.mutate(selectedModelId)}
                        disabled={$generateAuditSetMutation.isPending}
                      >
                        {#if $generateAuditSetMutation.isPending}
                          <svg class="h-3.5 w-3.5 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                          </svg>
                          Generating...
                        {:else}
                          Generate Audit Set
                        {/if}
                      </button>
                    {:else if reviewedCount >= 2}
                      <button
                        type="button"
                        class="inline-flex items-center gap-2 rounded-lg bg-amber-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-amber-700 disabled:opacity-50"
                        onclick={() => selectedModelId && $evaluateAuditSetMutation.mutate(selectedModelId)}
                        disabled={$evaluateAuditSetMutation.isPending}
                      >
                        {#if $evaluateAuditSetMutation.isPending}
                          <svg class="h-3.5 w-3.5 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                          </svg>
                          Evaluating...
                        {:else}
                          Evaluate
                        {/if}
                      </button>
                    {/if}
                  </div>
                {:else if model.status === 'trained'}
                  <!-- Audit set not yet generated -->
                  <button
                    type="button"
                    class="inline-flex items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-700 transition-colors hover:bg-amber-100 dark:border-amber-700 dark:bg-amber-900/20 dark:text-amber-400 dark:hover:bg-amber-900/40 disabled:opacity-50"
                    onclick={() => selectedModelId && $generateAuditSetMutation.mutate(selectedModelId)}
                    disabled={$generateAuditSetMutation.isPending}
                  >
                    {#if $generateAuditSetMutation.isPending}
                      <svg class="h-3.5 w-3.5 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                      </svg>
                      Generating...
                    {:else}
                      Generate Audit Set
                    {/if}
                  </button>
                {/if}
              </div>

              {#if model.audit_metrics}
                {@const am = model.audit_metrics as { accuracy: number; precision: number; recall: number; f1: number; roc_auc: number | null; pr_auc: number | null; confusion_matrix: [[number, number], [number, number]]; n_audited: number; n_total: number }}
                <!-- Audit progress summary -->
                <div class="mb-5 flex items-center gap-4 rounded-lg bg-amber-50 p-3 text-xs dark:bg-amber-950/20">
                  <div>
                    <span class="text-stone-500">Audited</span>
                    <span class="ml-1 font-semibold text-stone-800 dark:text-stone-200">{am.n_audited}</span>
                    <span class="text-stone-400"> / {am.n_total}</span>
                  </div>
                  <div class="h-3 w-px bg-stone-200 dark:bg-stone-700"></div>
                  <div class="text-stone-500">
                    {am.n_total > 0 ? ((am.n_audited / am.n_total) * 100).toFixed(0) : 0}% coverage
                  </div>
                </div>

                <!-- Audit metric bars -->
                <div class="space-y-4">
                  {#each [
                    { label: m.models_metrics_f1(), value: am.f1 },
                    { label: m.models_metrics_auc_roc(), value: am.roc_auc },
                    { label: m.models_metrics_pr_auc(), value: am.pr_auc },
                    { label: m.models_metrics_accuracy(), value: am.accuracy },
                    { label: m.models_metrics_precision(), value: am.precision },
                    { label: m.models_metrics_recall(), value: am.recall },
                  ] as metric}
                    {#if metric.value !== null}
                      <div>
                        <div class="mb-1 flex items-center justify-between text-sm">
                          <span class="font-medium text-stone-700">{metric.label}</span>
                          <span class="font-mono text-stone-900">{formatPercent(metric.value)}</span>
                        </div>
                        <div class="h-2 w-full overflow-hidden rounded-full bg-stone-100 dark:bg-stone-800">
                          <div
                            class="h-full rounded-full bg-amber-500 transition-all"
                            style="width: {(metric.value * 100).toFixed(1)}%"
                          ></div>
                        </div>
                      </div>
                    {/if}
                  {/each}
                </div>

                <!-- Audit confusion matrix -->
                {#if am.confusion_matrix}
                  {@const [[tn, fp], [fn, tp]] = am.confusion_matrix}
                  <div class="mt-6">
                    <h3 class="mb-3 text-xs font-semibold uppercase tracking-wider text-stone-400">
                      {m.models_detail_confusion_matrix()}
                    </h3>
                    <div class="grid grid-cols-2 gap-2 text-center text-sm">
                      <div class="rounded-lg bg-green-50 p-3 dark:bg-green-950/30">
                        <p class="text-xs font-medium text-green-600 dark:text-green-400">{m.models_detail_true_positive()}</p>
                        <p class="mt-1 text-xl font-bold text-green-700 dark:text-green-300">{tp}</p>
                      </div>
                      <div class="rounded-lg bg-red-50 p-3 dark:bg-red-950/30">
                        <p class="text-xs font-medium text-red-600 dark:text-red-400">{m.models_detail_false_positive()}</p>
                        <p class="mt-1 text-xl font-bold text-red-700 dark:text-red-300">{fp}</p>
                      </div>
                      <div class="rounded-lg bg-red-50 p-3 dark:bg-red-950/30">
                        <p class="text-xs font-medium text-red-600 dark:text-red-400">{m.models_detail_false_negative()}</p>
                        <p class="mt-1 text-xl font-bold text-red-700 dark:text-red-300">{fn}</p>
                      </div>
                      <div class="rounded-lg bg-green-50 p-3 dark:bg-green-950/30">
                        <p class="text-xs font-medium text-green-600 dark:text-green-400">{m.models_detail_true_negative()}</p>
                        <p class="mt-1 text-xl font-bold text-green-700 dark:text-green-300">{tn}</p>
                      </div>
                    </div>
                  </div>
                {/if}
              {:else}
                <!-- No audit metrics yet -->
                <div class="rounded-lg border border-dashed border-amber-200 p-6 text-center text-sm text-stone-400 dark:border-amber-800/40">
                  {#if $auditSetQuery.data && $auditSetQuery.data.items.length > 0}
                    {@const reviewedCount = $auditSetQuery.data.items.filter(i => i.review_status === 'confirmed' || i.review_status === 'rejected').length}
                    {#if reviewedCount < 2}
                      Review at least 2 audit items to enable evaluation.
                    {:else}
                      Click "Evaluate" to compute metrics from {reviewedCount} reviewed items.
                    {/if}
                  {:else if model.status === 'trained'}
                    Generate an audit set to independently validate this model on unseen clips.
                  {:else}
                    Blind audit is available for TRAINED models only.
                  {/if}
                </div>
              {/if}
            </div>
          {/if}
        {/if}

        <!-- Training stats -->
        {#if model.training_stats}
          {@const stats = model.training_stats}
          <div class="rounded-xl border border-card bg-surface-card p-6 shadow-sm">
            <h2 class="mb-4 text-sm font-semibold uppercase tracking-wider text-stone-500">
              {m.models_detail_training_stats()}
            </h2>
            <div class="flex flex-wrap gap-6">
              <div>
                <p class="text-xs font-medium uppercase tracking-wider text-stone-400">{m.models_detail_positive()}</p>
                <p class="mt-1 text-2xl font-bold text-stone-900">{stats.positive_count.toLocaleString()}</p>
              </div>
              <div>
                <p class="text-xs font-medium uppercase tracking-wider text-stone-400">{m.models_detail_negative()}</p>
                <p class="mt-1 text-2xl font-bold text-stone-900">{stats.negative_count.toLocaleString()}</p>
              </div>
              <div>
                <p class="text-xs font-medium uppercase tracking-wider text-stone-400">{m.models_detail_unlabeled()}</p>
                <p class="mt-1 text-2xl font-bold text-stone-900">{stats.unlabeled_count.toLocaleString()}</p>
              </div>
              <div>
                <p class="text-xs font-medium uppercase tracking-wider text-stone-400">{m.models_detail_duration()}</p>
                <p class="mt-1 text-2xl font-bold text-stone-900">{formatDuration(stats.training_duration_s)}</p>
              </div>
            </div>
          </div>
        {/if}
      {/if}
    </div>
  {/if}

  {/if}<!-- end activeTab === 'review' / else -->

</div>

<!-- ====================================================
     Create Model Dialog
==================================================== -->
{#if showCreateDialog}
  <!-- Backdrop -->
  <div
    class="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm"
    onclick={closeCreateDialog}
    onkeydown={(e) => e.key === 'Escape' && closeCreateDialog()}
    role="button"
    tabindex="-1"
    aria-label="Close dialog"
  ></div>

  <!-- Dialog panel -->
  <div
    class="fixed inset-x-0 bottom-0 z-50 mx-auto max-w-2xl rounded-t-2xl border border-card bg-surface-card p-6 shadow-2xl sm:inset-x-auto sm:left-1/2 sm:top-1/2 sm:w-full sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-2xl sm:p-8"
    role="dialog"
    aria-modal="true"
    aria-labelledby="create-dialog-title"
  >
    <div class="mb-6">
      <h2 id="create-dialog-title" class="text-lg font-semibold text-stone-900">
        {m.models_create_dialog_title()}
      </h2>
      <p class="mt-1 text-sm text-stone-500">
        {m.models_create_dialog_subtitle()}
      </p>
    </div>

    <form
      class="space-y-5"
      onsubmit={(e) => { e.preventDefault(); handleCreate(); }}
    >
      <!-- Model name -->
      <div>
        <label for="model-name" class="block text-sm font-medium text-stone-700">
          {m.models_name()} <span class="text-danger">*</span>
        </label>
        <input
          id="model-name"
          type="text"
          bind:value={createName}
          class="mt-1.5 block w-full rounded-lg border border-stone-300 bg-surface-card px-3 py-2 text-sm text-stone-900 placeholder:text-stone-400 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-stone-600"
          placeholder="e.g. Robin detector v1"
          required
        />
      </div>

      <!-- Description -->
      <div>
        <label for="model-description" class="block text-sm font-medium text-stone-700">
          {m.models_description_label()}
        </label>
        <textarea
          id="model-description"
          bind:value={createDescription}
          rows="2"
          class="mt-1.5 block w-full rounded-lg border border-stone-300 bg-surface-card px-3 py-2 text-sm text-stone-900 placeholder:text-stone-400 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-stone-600"
          placeholder="Optional description..."
        ></textarea>
      </div>

      <!-- Target species tag -->
      <div>
        <label for="model-tag" class="block text-sm font-medium text-stone-700">
          {m.models_target_species()} <span class="text-danger">*</span>
        </label>
        <select
          id="model-tag"
          bind:value={createTargetTagId}
          class="mt-1.5 block w-full rounded-lg border border-stone-300 bg-surface-card px-3 py-2 text-sm text-stone-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-stone-600"
        >
          <option value="">{m.models_no_target_species()}</option>
          {#if $tagsQuery.data}
            {#each $tagsQuery.data.items as tag (tag.id)}
              <option value={tag.id}>
                {tag.scientific_name ?? tag.name}
                {#if tag.common_name} — {tag.common_name}{/if}
              </option>
            {/each}
          {/if}
        </select>
      </div>

      <!-- Embedding model -->
      <div>
        <label for="model-embedding" class="block text-sm font-medium text-stone-700">
          {m.models_embedding_model()}
        </label>
        <select
          id="model-embedding"
          bind:value={createEmbeddingModel}
          class="mt-1.5 block w-full rounded-lg border border-stone-300 bg-surface-card px-3 py-2 text-sm text-stone-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-stone-600"
        >
          <option value="perch">perch</option>
          <option value="birdnet">birdnet</option>
        </select>
      </div>

      <!-- Error message -->
      {#if createError}
        <p class="text-sm text-red-600 dark:text-red-400">{createError}</p>
      {/if}

      <!-- Footer buttons -->
      <div class="flex justify-end gap-3 pt-2">
        <button
          type="button"
          class="rounded-lg border border-stone-300 px-4 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50 dark:border-stone-600 dark:hover:bg-stone-800"
          onclick={closeCreateDialog}
          disabled={$createMutationState.isPending}
        >
          {m.models_cancel()}
        </button>
        <button
          type="submit"
          class="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:opacity-50"
          disabled={$createMutationState.isPending}
        >
          {#if $createMutationState.isPending}
            <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
            {m.models_creating()}
          {:else}
            {m.models_create()}
          {/if}
        </button>
      </div>
    </form>
  </div>
{/if}

<!-- ====================================================
     Apply to Dataset Dialog
==================================================== -->
{#if showApplyDialog}
  <!-- Backdrop -->
  <div
    class="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm"
    onclick={closeApplyDialog}
    onkeydown={(e) => e.key === 'Escape' && closeApplyDialog()}
    role="button"
    tabindex="-1"
    aria-label="Close dialog"
  ></div>

  <!-- Dialog panel -->
  <div
    class="fixed inset-x-0 bottom-0 z-50 mx-auto max-w-lg rounded-t-2xl border border-card bg-surface-card p-6 shadow-2xl sm:inset-x-auto sm:left-1/2 sm:top-1/2 sm:w-full sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-2xl sm:p-8"
    role="dialog"
    aria-modal="true"
    aria-labelledby="apply-dialog-title"
  >
    <div class="mb-6">
      <h2 id="apply-dialog-title" class="text-lg font-semibold text-stone-900">
        {m.models_apply()}
      </h2>
      <p class="mt-1 text-sm text-stone-500">
        {m.models_apply_description()}
      </p>
    </div>

    <form
      class="space-y-5"
      onsubmit={(e) => { e.preventDefault(); handleApply(); }}
    >
      <!-- Dataset selector -->
      <div>
        <label for="apply-dataset" class="block text-sm font-medium text-stone-700">
          Dataset <span class="text-danger">*</span>
        </label>
        <select
          id="apply-dataset"
          bind:value={applyDatasetId}
          class="mt-1.5 block w-full rounded-lg border border-stone-300 bg-surface-card px-3 py-2 text-sm text-stone-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-stone-600"
        >
          <option value="">— Select a dataset —</option>
          {#if $datasetsQuery.isLoading}
            <option disabled>Loading...</option>
          {:else if $datasetsQuery.data}
            {#each $datasetsQuery.data.items as dataset (dataset.id)}
              <option value={dataset.id}>{dataset.name}</option>
            {/each}
          {/if}
        </select>
      </div>

      <!-- Threshold slider -->
      <div>
        <label for="apply-threshold" class="block text-sm font-medium text-stone-700">
          {m.models_apply_threshold()}
          <span class="ml-2 font-mono text-primary-600 dark:text-primary-400">{applyThreshold.toFixed(2)}</span>
        </label>
        <input
          id="apply-threshold"
          type="range"
          min="0"
          max="1"
          step="0.01"
          bind:value={applyThreshold}
          class="mt-2 h-2 w-full cursor-pointer appearance-none rounded-full bg-stone-200 accent-primary-500 dark:bg-stone-700"
        />
        <div class="mt-1 flex justify-between text-xs text-stone-400">
          <span>0</span>
          <span>0.5</span>
          <span>1</span>
        </div>
      </div>

      <!-- Error message -->
      {#if applyError}
        <p class="text-sm text-red-600 dark:text-red-400">{applyError}</p>
      {/if}

      <!-- Footer buttons -->
      <div class="flex justify-end gap-3 pt-2">
        <button
          type="button"
          class="rounded-lg border border-stone-300 px-4 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50 dark:border-stone-600 dark:hover:bg-stone-800"
          onclick={closeApplyDialog}
          disabled={$applyMutationState.isPending}
        >
          {m.models_cancel()}
        </button>
        <button
          type="submit"
          class="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:opacity-50"
          disabled={$applyMutationState.isPending}
        >
          {#if $applyMutationState.isPending}
            <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
            {m.models_applying()}
          {:else}
            {m.models_apply()}
          {/if}
        </button>
      </div>
    </form>
  </div>
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
