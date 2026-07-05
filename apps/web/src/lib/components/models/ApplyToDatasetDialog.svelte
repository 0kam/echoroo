<script lang="ts">
  /**
   * Apply-to-Dataset dialog.
   *
   * Presentational modal for running a trained custom model against another
   * dataset. Two-way binds the dataset selection + threshold and delegates the
   * queued-job dispatch to the parent via `onSubmit`. The parent owns the
   * datasets query and the apply mutation (including error surfacing) and
   * controls the `pending` in-flight flag.
   */

  import * as m from '$lib/paraglide/messages';

  let {
    datasetsLoading,
    datasets,
    applyDatasetId = $bindable(),
    applyThreshold = $bindable(),
    applyError,
    pending,
    onClose,
    onSubmit,
  }: {
    datasetsLoading: boolean;
    datasets: readonly { id: string; name: string }[] | undefined;
    applyDatasetId: string;
    applyThreshold: number;
    applyError: string | null;
    pending: boolean;
    onClose: () => void;
    onSubmit: () => void;
  } = $props();
</script>

<!-- Backdrop -->
<div
  class="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm"
  onclick={onClose}
  onkeydown={(e) => e.key === 'Escape' && onClose()}
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
    onsubmit={(e) => { e.preventDefault(); onSubmit(); }}
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
        {#if datasetsLoading}
          <option disabled>Loading...</option>
        {:else if datasets}
          {#each datasets as dataset (dataset.id)}
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
      <p class="text-sm text-danger">{applyError}</p>
    {/if}

    <!-- Footer buttons -->
    <div class="flex justify-end gap-3 pt-2">
      <button
        type="button"
        class="rounded-lg border border-stone-300 px-4 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50 dark:border-stone-600 dark:hover:bg-stone-800"
        onclick={onClose}
        disabled={pending}
      >
        {m.models_cancel()}
      </button>
      <button
        type="submit"
        class="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:opacity-50 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
        disabled={pending}
      >
        {#if pending}
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
