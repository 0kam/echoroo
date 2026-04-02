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

  import { onDestroy } from 'svelte';
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
  } from '$lib/api/custom-models';
  import { listSearchSessions } from '$lib/api/search';
  import { fetchTags } from '$lib/api/tags';
  import type { CustomModel, CustomModelListItem, CustomModelCreate } from '$lib/types/custom-model';
  import type { Tag } from '$lib/types/annotation';

  const projectId = $derived($page.params.id as string);
  const queryClient = useQueryClient();

  // ============================================
  // View state
  // ============================================

  let viewMode = $state<'list' | 'detail'>('list');
  let selectedModelId = $state<string | null>(null);

  // ============================================
  // Create model dialog state
  // ============================================

  let showCreateDialog = $state(false);
  let createName = $state('');
  let createDescription = $state('');
  let createTargetTagId = $state('');
  let createSessionIds = $state<string[]>([]);
  let createEmbeddingModel = $state('perch');
  let createError = $state<string | null>(null);

  // ============================================
  // Delete confirmation state
  // ============================================

  let deletingModelId = $state<string | null>(null);

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

  const sessionsQuery = $derived(
    createQuery({
      queryKey: ['search-sessions', projectId, 'for-models'],
      queryFn: () => listSearchSessions(projectId, 100, 0),
      enabled: showCreateDialog,
    })
  );

  const tagsQuery = $derived(
    createQuery({
      queryKey: ['tags', projectId],
      queryFn: () => fetchTags(projectId, { page_size: 200 }),
      enabled: showCreateDialog,
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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['custom-models', projectId] });
      if (selectedModelId === deletingModelId) {
        handleBackToList();
      }
      deletingModelId = null;
    },
    onError: () => {
      deletingModelId = null;
    },
  });

  // ============================================
  // Handlers
  // ============================================

  function openCreateDialog() {
    createName = '';
    createDescription = '';
    createTargetTagId = '';
    createSessionIds = [];
    createEmbeddingModel = 'perch';
    createError = null;
    showCreateDialog = true;
  }

  function closeCreateDialog() {
    showCreateDialog = false;
  }

  function toggleSession(sessionId: string) {
    if (createSessionIds.includes(sessionId)) {
      createSessionIds = createSessionIds.filter((id) => id !== sessionId);
    } else {
      createSessionIds = [...createSessionIds, sessionId];
    }
  }

  function handleCreate() {
    createError = null;
    if (!createName.trim()) {
      createError = 'Model name is required';
      return;
    }
    if (createSessionIds.length === 0) {
      createError = 'Select at least one search session';
      return;
    }

    const payload: CustomModelCreate = {
      name: createName.trim(),
      description: createDescription.trim() || undefined,
      target_tag_id: createTargetTagId || undefined,
      training_session_ids: createSessionIds,
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
    if (deletingModelId) {
      $deleteMutationState.mutate(deletingModelId);
    }
  }

  function handleDeleteCancel() {
    deletingModelId = null;
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
  }

  // ============================================
  // Helpers
  // ============================================

  function statusLabel(status: string): string {
    switch (status) {
      case 'draft':
        return m.models_status_draft();
      case 'training':
        return m.models_status_training();
      case 'trained':
        return m.models_status_trained();
      case 'deployed':
        return m.models_status_deployed();
      case 'failed':
        return m.models_status_failed();
      default:
        return status;
    }
  }

  function statusClasses(status: string): string {
    switch (status) {
      case 'draft':
        return 'bg-stone-100 text-stone-600 dark:bg-stone-800 dark:text-stone-400';
      case 'training':
        return 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400';
      case 'trained':
        return 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400';
      case 'deployed':
        return 'bg-primary-100 text-primary-700 dark:bg-primary-900/30 dark:text-primary-400';
      case 'failed':
        return 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400';
      default:
        return 'bg-stone-100 text-stone-600';
    }
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
  <nav class="mb-6 flex items-center gap-2 text-sm text-stone-500 dark:text-stone-400">
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
      <span class="font-medium text-stone-900 dark:text-stone-100">{displayedModel.name}</span>
    {:else}
      <span class="font-medium text-stone-900 dark:text-stone-100">{m.models_title()}</span>
    {/if}
  </nav>

  <!-- ====================================================
       Mode: list
  ==================================================== -->
  {#if viewMode === 'list'}
    <div class="space-y-6">

      <!-- Page header -->
      <div class="flex items-start justify-between">
        <div>
          <h1 class="text-2xl font-bold text-stone-900 dark:text-stone-100">{m.models_title()}</h1>
          <p class="mt-1 text-sm text-stone-500 dark:text-stone-400">{m.models_description()}</p>
        </div>
        <button
          type="button"
          class="inline-flex items-center gap-2 rounded-lg bg-primary-500 px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-primary-600 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2"
          onclick={openCreateDialog}
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
          <svg class="mx-auto h-12 w-12 text-stone-300 dark:text-stone-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
          </svg>
          <h2 class="mt-4 text-base font-semibold text-stone-700 dark:text-stone-300">{m.models_no_models()}</h2>
          <p class="mt-1 text-sm text-stone-500 dark:text-stone-400">{m.models_description()}</p>
          <button
            type="button"
            class="mt-6 inline-flex items-center gap-2 rounded-lg bg-primary-500 px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-primary-600"
            onclick={openCreateDialog}
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
                    <h2 class="text-base font-semibold text-stone-900 dark:text-stone-100">
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
                    <span class="rounded-full bg-stone-100 px-2 py-0.5 text-xs text-stone-500 dark:bg-stone-800 dark:text-stone-400">
                      {model.embedding_model_name}
                    </span>
                  </div>

                  {#if model.description}
                    <p class="mt-1 text-sm text-stone-500 dark:text-stone-400 line-clamp-2">{model.description}</p>
                  {/if}

                  <p class="mt-1.5 text-xs text-stone-400 dark:text-stone-500">
                    {m.models_created_at()} {formatDate(model.created_at)}
                    {#if model.completed_at}
                      &middot; {m.models_trained_at()} {formatDate(model.completed_at)}
                    {/if}
                  </p>
                </div>

                <!-- Right: action buttons -->
                <div class="flex shrink-0 items-center gap-2" onclick={(e) => e.stopPropagation()}>
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
        class="inline-flex items-center gap-1.5 text-sm text-stone-500 transition-colors hover:text-stone-900 dark:text-stone-400 dark:hover:text-stone-100"
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
                <h1 class="text-2xl font-bold text-stone-900 dark:text-stone-100">{model.name}</h1>
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
                <p class="mt-2 text-sm text-stone-500 dark:text-stone-400">{model.description}</p>
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
            <div class="flex shrink-0 gap-2">
              {#if model.status === 'draft' || model.status === 'failed'}
                <button
                  type="button"
                  class="inline-flex items-center gap-2 rounded-lg bg-primary-500 px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-primary-600 disabled:opacity-50"
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
                class="inline-flex items-center gap-2 rounded-lg border border-red-300 px-4 py-2 text-sm font-medium text-red-600 transition-colors hover:bg-red-50 dark:border-red-700 dark:text-red-400 dark:hover:bg-red-950/30"
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
        {#if model.metrics}
          {@const metrics = model.metrics}
          <div class="rounded-xl border border-card bg-surface-card p-6 shadow-sm">
            <h2 class="mb-5 text-sm font-semibold uppercase tracking-wider text-stone-500 dark:text-stone-400">
              Metrics
            </h2>

            <!-- Primary metric bars -->
            <div class="space-y-4">
              {#each [
                { label: m.models_metrics_f1(), value: metrics.f1 },
                { label: m.models_metrics_auc_roc(), value: metrics.auc_roc },
                { label: m.models_metrics_pr_auc(), value: metrics.pr_auc },
                { label: m.models_metrics_accuracy(), value: metrics.accuracy },
                { label: m.models_metrics_precision(), value: metrics.precision },
                { label: m.models_metrics_recall(), value: metrics.recall },
              ] as metric}
                <div>
                  <div class="mb-1 flex items-center justify-between text-sm">
                    <span class="font-medium text-stone-700 dark:text-stone-300">{metric.label}</span>
                    <span class="font-mono text-stone-900 dark:text-stone-100">{formatPercent(metric.value)}</span>
                  </div>
                  <div class="h-2 w-full overflow-hidden rounded-full bg-stone-100 dark:bg-stone-800">
                    <div
                      class="h-full rounded-full bg-primary-500 transition-all"
                      style="width: {(metric.value * 100).toFixed(1)}%"
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
              <h2 class="mb-4 text-sm font-semibold uppercase tracking-wider text-stone-500 dark:text-stone-400">
                {m.models_detail_confusion_matrix()}
              </h2>
              <div class="grid grid-cols-2 gap-2 text-center text-sm">
                <div class="rounded-lg bg-green-50 p-3 dark:bg-green-950/30">
                  <p class="text-xs font-medium text-green-600 dark:text-green-400">{m.models_detail_true_positive()}</p>
                  <p class="mt-1 text-xl font-bold text-green-700 dark:text-green-300">{metrics.confusion_matrix.tp}</p>
                </div>
                <div class="rounded-lg bg-red-50 p-3 dark:bg-red-950/30">
                  <p class="text-xs font-medium text-red-600 dark:text-red-400">{m.models_detail_false_positive()}</p>
                  <p class="mt-1 text-xl font-bold text-red-700 dark:text-red-300">{metrics.confusion_matrix.fp}</p>
                </div>
                <div class="rounded-lg bg-red-50 p-3 dark:bg-red-950/30">
                  <p class="text-xs font-medium text-red-600 dark:text-red-400">{m.models_detail_false_negative()}</p>
                  <p class="mt-1 text-xl font-bold text-red-700 dark:text-red-300">{metrics.confusion_matrix.fn}</p>
                </div>
                <div class="rounded-lg bg-green-50 p-3 dark:bg-green-950/30">
                  <p class="text-xs font-medium text-green-600 dark:text-green-400">{m.models_detail_true_negative()}</p>
                  <p class="mt-1 text-xl font-bold text-green-700 dark:text-green-300">{metrics.confusion_matrix.tn}</p>
                </div>
              </div>
            </div>

            <!-- Hyperparameters -->
            <div class="rounded-xl border border-card bg-surface-card p-6 shadow-sm">
              <h2 class="mb-4 text-sm font-semibold uppercase tracking-wider text-stone-500 dark:text-stone-400">
                {m.models_detail_hyperparameters()}
              </h2>
              <dl class="space-y-2 text-sm">
                <div class="flex items-center justify-between">
                  <dt class="text-stone-500 dark:text-stone-400">{m.models_detail_best_c()}</dt>
                  <dd class="font-mono font-semibold text-stone-900 dark:text-stone-100">{metrics.best_c}</dd>
                </div>
              </dl>
              {#if model.hyperparameters}
                {#each Object.entries(model.hyperparameters).filter(([k]) => k !== 'best_c') as [key, value]}
                  <dl class="mt-2 space-y-2 text-sm">
                    <div class="flex items-center justify-between">
                      <dt class="text-stone-500 dark:text-stone-400">{key}</dt>
                      <dd class="font-mono font-semibold text-stone-900 dark:text-stone-100">{String(value)}</dd>
                    </div>
                  </dl>
                {/each}
              {/if}
            </div>
          </div>
        {/if}

        <!-- Training stats -->
        {#if model.training_stats}
          {@const stats = model.training_stats}
          <div class="rounded-xl border border-card bg-surface-card p-6 shadow-sm">
            <h2 class="mb-4 text-sm font-semibold uppercase tracking-wider text-stone-500 dark:text-stone-400">
              {m.models_detail_training_stats()}
            </h2>
            <div class="flex flex-wrap gap-6">
              <div>
                <p class="text-xs font-medium uppercase tracking-wider text-stone-400">{m.models_detail_positive()}</p>
                <p class="mt-1 text-2xl font-bold text-stone-900 dark:text-stone-100">{stats.positive_count.toLocaleString()}</p>
              </div>
              <div>
                <p class="text-xs font-medium uppercase tracking-wider text-stone-400">{m.models_detail_negative()}</p>
                <p class="mt-1 text-2xl font-bold text-stone-900 dark:text-stone-100">{stats.negative_count.toLocaleString()}</p>
              </div>
              <div>
                <p class="text-xs font-medium uppercase tracking-wider text-stone-400">{m.models_detail_unlabeled()}</p>
                <p class="mt-1 text-2xl font-bold text-stone-900 dark:text-stone-100">{stats.unlabeled_count.toLocaleString()}</p>
              </div>
              <div>
                <p class="text-xs font-medium uppercase tracking-wider text-stone-400">{m.models_detail_duration()}</p>
                <p class="mt-1 text-2xl font-bold text-stone-900 dark:text-stone-100">{formatDuration(stats.training_duration_seconds)}</p>
              </div>
            </div>
          </div>
        {/if}
      {/if}
    </div>
  {/if}

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
      <h2 id="create-dialog-title" class="text-lg font-semibold text-stone-900 dark:text-stone-100">
        {m.models_create_dialog_title()}
      </h2>
      <p class="mt-1 text-sm text-stone-500 dark:text-stone-400">
        {m.models_create_dialog_subtitle()}
      </p>
    </div>

    <form
      class="space-y-5"
      onsubmit={(e) => { e.preventDefault(); handleCreate(); }}
    >
      <!-- Model name -->
      <div>
        <label for="model-name" class="block text-sm font-medium text-stone-700 dark:text-stone-300">
          {m.models_name()} <span class="text-red-500">*</span>
        </label>
        <input
          id="model-name"
          type="text"
          bind:value={createName}
          class="mt-1.5 block w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 placeholder:text-stone-400 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-stone-600 dark:bg-stone-800 dark:text-stone-100"
          placeholder="e.g. Robin detector v1"
          required
        />
      </div>

      <!-- Description -->
      <div>
        <label for="model-description" class="block text-sm font-medium text-stone-700 dark:text-stone-300">
          {m.models_description_label()}
        </label>
        <textarea
          id="model-description"
          bind:value={createDescription}
          rows="2"
          class="mt-1.5 block w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 placeholder:text-stone-400 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-stone-600 dark:bg-stone-800 dark:text-stone-100"
          placeholder="Optional description..."
        ></textarea>
      </div>

      <!-- Target species tag -->
      <div>
        <label for="model-tag" class="block text-sm font-medium text-stone-700 dark:text-stone-300">
          {m.models_target_species()}
        </label>
        <select
          id="model-tag"
          bind:value={createTargetTagId}
          class="mt-1.5 block w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-stone-600 dark:bg-stone-800 dark:text-stone-100"
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
        <label for="model-embedding" class="block text-sm font-medium text-stone-700 dark:text-stone-300">
          {m.models_embedding_model()}
        </label>
        <select
          id="model-embedding"
          bind:value={createEmbeddingModel}
          class="mt-1.5 block w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-stone-600 dark:bg-stone-800 dark:text-stone-100"
        >
          <option value="perch">perch</option>
          <option value="birdnet">birdnet</option>
        </select>
      </div>

      <!-- Search sessions selector -->
      <div>
        <p class="text-sm font-medium text-stone-700 dark:text-stone-300">
          {m.models_training_sessions()} <span class="text-red-500">*</span>
        </p>
        <p class="mt-0.5 text-xs text-stone-400 dark:text-stone-500">{m.models_min_samples()}</p>

        <div class="mt-2 max-h-48 space-y-1.5 overflow-y-auto rounded-lg border border-stone-200 p-2 dark:border-stone-700">
          {#if $sessionsQuery.isLoading}
            <p class="p-2 text-sm text-stone-400">{m.nav_loading()}</p>
          {:else if $sessionsQuery.data && $sessionsQuery.data.sessions.length === 0}
            <p class="p-2 text-sm text-stone-400">{m.models_select_sessions()}</p>
          {:else if $sessionsQuery.data}
            {#each $sessionsQuery.data.sessions as session (session.id)}
              {@const isChecked = createSessionIds.includes(session.id)}
              <label
                class="flex cursor-pointer items-start gap-3 rounded-md p-2 transition-colors {isChecked ? 'bg-primary-50 dark:bg-primary-950/20' : 'hover:bg-stone-50 dark:hover:bg-stone-800'}"
              >
                <input
                  type="checkbox"
                  checked={isChecked}
                  onchange={() => toggleSession(session.id)}
                  class="mt-0.5 h-4 w-4 rounded border-stone-300 text-primary-500 focus:ring-primary-500"
                />
                <div class="min-w-0 flex-1">
                  <p class="text-sm font-medium text-stone-800 dark:text-stone-200">
                    {session.name ?? session.id.slice(0, 8)}
                  </p>
                  <p class="text-xs text-stone-400">
                    {session.confirmed_count} confirmed &middot; {session.rejected_count} rejected &middot; {session.result_count} total
                  </p>
                </div>
              </label>
            {/each}
          {/if}
        </div>
      </div>

      <!-- Error message -->
      {#if createError}
        <p class="text-sm text-red-600 dark:text-red-400">{createError}</p>
      {/if}

      <!-- Footer buttons -->
      <div class="flex justify-end gap-3 pt-2">
        <button
          type="button"
          class="rounded-lg border border-stone-300 px-4 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50 dark:border-stone-600 dark:text-stone-300 dark:hover:bg-stone-800"
          onclick={closeCreateDialog}
          disabled={$createMutationState.isPending}
        >
          {m.models_cancel()}
        </button>
        <button
          type="submit"
          class="inline-flex items-center gap-2 rounded-lg bg-primary-500 px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-primary-600 disabled:opacity-50"
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
    <h2 id="delete-dialog-title" class="text-base font-semibold text-stone-900 dark:text-stone-100">
      {m.models_delete()}
    </h2>
    <p class="mt-2 text-sm text-stone-500 dark:text-stone-400">{m.models_delete_confirm()}</p>
    <div class="mt-5 flex justify-end gap-3">
      <button
        type="button"
        class="rounded-lg border border-stone-300 px-4 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50 dark:border-stone-600 dark:text-stone-300 dark:hover:bg-stone-800"
        onclick={handleDeleteCancel}
      >
        {m.models_cancel()}
      </button>
      <button
        type="button"
        class="inline-flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-red-700 disabled:opacity-50"
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
