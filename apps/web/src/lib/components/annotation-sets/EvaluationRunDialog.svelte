<script lang="ts">
  /**
   * Modal dialog for launching a new cross-model evaluation run.
   *
   * Lets the user pick BirdNET, Perch, and any number of trained custom
   * models. On submit, POSTs to `/annotation-sets/{id}/evaluate` and
   * closes itself; the parent is responsible for refetching the run list.
   */
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import * as m from '$lib/paraglide/messages';
  import { fetchCustomModels } from '$lib/api/custom-models';
  import { evaluateAnnotationSet } from '$lib/api/annotation-sets';
  import type { CustomModelListItem } from '$lib/types/custom-model';
  import type {
    EvaluationModelRef,
    EvaluationRunResponse,
  } from '$lib/types/annotation-set';
  import { toasts } from '$lib/stores/toast';

  interface Props {
    setId: string;
    projectId: string;
    /** Parent status; shows a warning when not yet completed. */
    setStatus: 'sampling' | 'ready' | 'in_progress' | 'completed';
    onClose: () => void;
    onSuccess?: (run: EvaluationRunResponse) => void;
  }

  const { setId, projectId, setStatus, onClose, onSuccess }: Props = $props();

  const queryClient = useQueryClient();

  let includeBirdnet = $state(true);
  let includePerch = $state(true);
  let selectedCustomIds = $state<Set<string>>(new Set());
  let submitError = $state<string | null>(null);

  // ------------------------------------------------------------
  // Custom models (trained only)
  // ------------------------------------------------------------

  const customModelsQuery = $derived(
    createQuery({
      queryKey: ['custom-models-for-evaluation', projectId],
      queryFn: () => fetchCustomModels(projectId, { limit: 200 }),
      refetchOnWindowFocus: false,
    }),
  );

  const trainedModels = $derived<CustomModelListItem[]>(
    ($customModelsQuery.data?.models ?? []).filter(
      (model) => model.status === 'trained' || model.status === 'deployed',
    ),
  );

  function toggleCustomId(id: string) {
    const next = new Set(selectedCustomIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    selectedCustomIds = next;
  }

  // ------------------------------------------------------------
  // Mutation
  // ------------------------------------------------------------

  const mutation = createMutation({
    mutationFn: (refs: EvaluationModelRef[]) =>
      evaluateAnnotationSet(setId, { model_refs: refs }),
    onSuccess: (run) => {
      queryClient.invalidateQueries({
        queryKey: ['evaluation-runs', setId],
      });
      toasts.success(m.evaluation_run_status_pending());
      onSuccess?.(run);
      onClose();
    },
    onError: () => {
      submitError = m.evaluation_dialog_submit_error();
    },
  });

  const selectionCount = $derived(
    (includeBirdnet ? 1 : 0) + (includePerch ? 1 : 0) + selectedCustomIds.size,
  );

  function submit() {
    submitError = null;
    if (selectionCount === 0) {
      submitError = m.evaluation_dialog_select_at_least_one();
      return;
    }
    const refs: EvaluationModelRef[] = [];
    if (includeBirdnet) refs.push({ kind: 'birdnet' });
    if (includePerch) refs.push({ kind: 'perch' });
    for (const id of selectedCustomIds) {
      refs.push({ kind: 'custom', model_id: id });
    }
    $mutation.mutate(refs);
  }

  function onBackdropClick(event: MouseEvent) {
    if (event.target === event.currentTarget) onClose();
  }

  function onKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') onClose();
  }

  const showWarning = $derived(setStatus !== 'completed');
</script>

<svelte:window on:keydown={onKeydown} />

<!-- svelte-ignore a11y_click_events_have_key_events -->
<div
  class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
  role="dialog"
  aria-modal="true"
  aria-labelledby="evaluation-dialog-title"
  tabindex="-1"
  onclick={onBackdropClick}
>
  <div class="w-full max-w-lg rounded-xl bg-surface-card p-6 shadow-xl">
    <h2
      id="evaluation-dialog-title"
      class="text-lg font-semibold text-stone-900 dark:text-stone-100"
    >
      {m.evaluation_dialog_title()}
    </h2>
    <p class="mt-1 text-sm text-stone-500">
      {m.evaluation_dialog_description()}
    </p>

    {#if showWarning}
      <div
        class="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-900/40 dark:bg-amber-900/20 dark:text-amber-300"
        role="note"
      >
        {m.evaluation_dialog_in_progress_warning()}
      </div>
    {/if}

    <!-- Built-in models -->
    <section class="mt-5">
      <h3 class="text-xs font-semibold uppercase tracking-wider text-stone-500">
        {m.evaluation_dialog_section_builtin()}
      </h3>
      <div class="mt-2 space-y-2">
        <label
          class="flex cursor-pointer items-center gap-3 rounded-lg border border-stone-200 bg-stone-50 px-3 py-2 text-sm hover:bg-stone-100 dark:border-stone-700 dark:bg-stone-800/40 dark:hover:bg-stone-800"
        >
          <input
            type="checkbox"
            class="h-4 w-4 rounded border-stone-300 text-primary-600 focus:ring-primary-500"
            bind:checked={includeBirdnet}
          />
          <span class="flex-1 font-medium text-stone-900 dark:text-stone-100">
            {m.evaluation_dialog_model_birdnet()}
          </span>
          <span class="text-xs text-stone-500">3s</span>
        </label>
        <label
          class="flex cursor-pointer items-center gap-3 rounded-lg border border-stone-200 bg-stone-50 px-3 py-2 text-sm hover:bg-stone-100 dark:border-stone-700 dark:bg-stone-800/40 dark:hover:bg-stone-800"
        >
          <input
            type="checkbox"
            class="h-4 w-4 rounded border-stone-300 text-primary-600 focus:ring-primary-500"
            bind:checked={includePerch}
          />
          <span class="flex-1 font-medium text-stone-900 dark:text-stone-100">
            {m.evaluation_dialog_model_perch()}
          </span>
          <span class="text-xs text-stone-500">5s</span>
        </label>
      </div>
    </section>

    <!-- Custom models -->
    <section class="mt-5">
      <h3 class="text-xs font-semibold uppercase tracking-wider text-stone-500">
        {m.evaluation_dialog_section_custom()}
      </h3>

      {#if $customModelsQuery.isLoading}
        <p class="mt-2 text-sm text-stone-400">
          {m.evaluation_dialog_custom_loading()}
        </p>
      {:else if $customModelsQuery.isError}
        <p class="mt-2 text-sm text-danger">
          {m.evaluation_dialog_custom_error()}
        </p>
      {:else if trainedModels.length === 0}
        <p class="mt-2 rounded-lg bg-stone-50 p-3 text-sm text-stone-500 dark:bg-stone-800/40">
          {m.evaluation_dialog_custom_empty()}
        </p>
      {:else}
        <div class="mt-2 max-h-56 space-y-2 overflow-y-auto pr-1">
          {#each trainedModels as model (model.id)}
            {@const checked = selectedCustomIds.has(model.id)}
            <label
              class="flex cursor-pointer items-center gap-3 rounded-lg border border-stone-200 bg-stone-50 px-3 py-2 text-sm hover:bg-stone-100 dark:border-stone-700 dark:bg-stone-800/40 dark:hover:bg-stone-800"
            >
              <input
                type="checkbox"
                class="h-4 w-4 rounded border-stone-300 text-primary-600 focus:ring-primary-500"
                {checked}
                onchange={() => toggleCustomId(model.id)}
              />
              <span class="min-w-0 flex-1">
                <span class="block truncate font-medium text-stone-900 dark:text-stone-100">
                  {model.name}
                </span>
                {#if model.description}
                  <span class="block truncate text-xs text-stone-500">
                    {model.description}
                  </span>
                {/if}
              </span>
              <span
                class="flex-shrink-0 rounded-full bg-green-100 px-2 py-0.5 text-xs text-green-700 dark:bg-green-900/30 dark:text-green-300"
              >
                {model.status}
              </span>
            </label>
          {/each}
        </div>
      {/if}
    </section>

    {#if submitError}
      <p class="mt-4 rounded-lg border border-danger/30 bg-danger-light p-2 text-xs text-danger">
        {submitError}
      </p>
    {/if}

    <div class="mt-6 flex items-center justify-end gap-2">
      <button
        type="button"
        class="rounded-lg border border-stone-300 px-3 py-1.5 text-sm hover:bg-stone-50 dark:border-stone-600 dark:hover:bg-stone-800"
        onclick={onClose}
        disabled={$mutation.isPending}
      >
        {m.evaluation_dialog_cancel()}
      </button>
      <button
        type="button"
        class="rounded-lg bg-primary-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
        onclick={submit}
        disabled={$mutation.isPending || selectionCount === 0}
      >
        {$mutation.isPending
          ? m.evaluation_dialog_submitting()
          : m.evaluation_dialog_submit()}
      </button>
    </div>
  </div>
</div>
