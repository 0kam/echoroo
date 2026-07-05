<script lang="ts">
  /**
   * Custom models list view.
   *
   * Presentational list of trained/draft custom SVM classifiers with status
   * badges and per-row actions. The parent owns the query and mutations and
   * threads the resolved data + callbacks in.
   */

  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import type { CustomModelListItem } from '$lib/types/custom-model';
  import { statusLabel, statusClasses, formatDate } from './modelFormatters';

  let {
    projectId,
    isLoading,
    isError,
    models,
    trainPending,
    onSelectModel,
    onTrain,
    onDeleteRequest,
  }: {
    projectId: string;
    isLoading: boolean;
    isError: boolean;
    models: CustomModelListItem[] | undefined;
    trainPending: boolean;
    onSelectModel: (modelId: string) => void;
    onTrain: (modelId: string) => void;
    onDeleteRequest: (modelId: string) => void;
  } = $props();
</script>

<div class="space-y-6">

  <!-- Page header -->
  <div class="flex items-start justify-between">
    <div>
      <h1 class="text-2xl font-bold text-stone-900">{m.models_title()}</h1>
      <p class="mt-1 text-sm text-stone-500">{m.models_description()}</p>
    </div>
  </div>

  <!-- Model list -->
  {#if isLoading}
    <div class="flex items-center gap-2 text-sm text-stone-400">
      <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      {m.nav_loading()}
    </div>

  {:else if isError}
    <div class="rounded-lg border border-danger/30 bg-danger-light p-4 text-sm text-danger">
      Failed to load models. Please refresh the page.
    </div>

  {:else if models && models.length === 0}
    <!-- Empty state: direct users to Search page for model creation -->
    <div class="rounded-xl border-2 border-dashed border-stone-200 bg-surface-card p-12 text-center dark:border-stone-700">
      <svg class="mx-auto h-12 w-12 text-stone-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
      </svg>
      <h2 class="mt-4 text-base font-semibold text-stone-700">No trained models yet</h2>
      <p class="mt-1 text-sm text-stone-500">{m.models_empty_create_from_search()}</p>
      <a
        href={localizeHref(`/projects/${projectId}/search`)}
        class="mt-6 inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-primary-700 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
      >
        <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
          <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
        Go to Search
      </a>
    </div>

  {:else if models}
    <div class="space-y-3">
      {#each models as model (model.id)}
        <div
          class="cursor-pointer rounded-xl border border-card bg-surface-card p-5 shadow-sm transition-shadow hover:shadow-md"
          onclick={() => onSelectModel(model.id)}
          onkeydown={(e) => e.key === 'Enter' && onSelectModel(model.id)}
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
            <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_noninteractive_element_interactions -->
            <div class="flex shrink-0 items-center gap-2" onclick={(e) => e.stopPropagation()} role="group">
              {#if model.status === 'draft'}
                <!-- Draft: navigate to detail view with ReviewTab instead of direct train -->
                <button
                  type="button"
                  class="inline-flex items-center gap-1.5 rounded-lg border border-primary-300 bg-primary-50 px-3 py-1.5 text-xs font-medium text-primary-700 transition-colors hover:bg-primary-100 dark:border-primary-700 dark:bg-primary-900/20 dark:text-primary-400 dark:hover:bg-primary-900/40"
                  onclick={() => onSelectModel(model.id)}
                >
                  <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  {m.models_review_and_train()}
                </button>
              {:else if model.status === 'failed'}
                <!-- Failed: allow quick retry train -->
                <button
                  type="button"
                  class="inline-flex items-center gap-1.5 rounded-lg border border-primary-300 bg-primary-50 px-3 py-1.5 text-xs font-medium text-primary-700 transition-colors hover:bg-primary-100 dark:border-primary-700 dark:bg-primary-900/20 dark:text-primary-400 dark:hover:bg-primary-900/40 disabled:opacity-50"
                  onclick={() => onTrain(model.id)}
                  disabled={trainPending}
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
                class="rounded-lg p-1.5 text-stone-400 transition-colors hover:bg-danger-light hover:text-danger"
                onclick={() => onDeleteRequest(model.id)}
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
