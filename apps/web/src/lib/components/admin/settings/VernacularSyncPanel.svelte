<script lang="ts">
  /**
   * Vernacular-name sync panel (subsection of the taxon maintenance card).
   *
   * Owns its own confirmation modal and two-way binds the sync form inputs
   * (batch size, locales, skip-existing). Dispatches the sync task via the
   * `onSync` callback once the admin confirms. The parent surfaces results
   * through the shared success/error banners and controls the `isSyncing`
   * in-flight flag.
   */

  import * as m from '$lib/paraglide/messages';

  let {
    isSyncing,
    onSync,
    vernacularBatchSize = $bindable(),
    vernacularLocales = $bindable(),
    vernacularSkipExisting = $bindable(),
  }: {
    isSyncing: boolean;
    onSync: () => void;
    vernacularBatchSize: number;
    vernacularLocales: string;
    vernacularSkipExisting: boolean;
  } = $props();

  let showSyncVernacularConfirm = $state(false);

  function handleConfirm() {
    showSyncVernacularConfirm = false;
    onSync();
  }

  /**
   * Handle vernacular batch size change (clamped to the 1-500 contract).
   */
  function handleVernacularBatchSizeChange(event: Event) {
    const target = event.target as HTMLInputElement;
    const parsed = parseInt(target.value, 10);
    if (Number.isNaN(parsed)) {
      vernacularBatchSize = 100;
      return;
    }
    vernacularBatchSize = Math.min(500, Math.max(1, parsed));
  }

  /**
   * Handle vernacular locales free-text change.
   */
  function handleVernacularLocalesChange(event: Event) {
    const target = event.target as HTMLInputElement;
    vernacularLocales = target.value;
  }

  /**
   * Toggle "skip existing" for the vernacular sync.
   */
  function handleVernacularSkipExistingToggle() {
    vernacularSkipExisting = !vernacularSkipExisting;
  }
</script>

<!-- Sync vernacular names -->
<div class="border-t border-stone-200 pt-6">
  <h3 class="text-sm font-medium text-stone-700">
    {m.admin_settings_taxon_sync_vernacular_label()}
  </h3>
  <p class="mt-1 text-sm text-stone-500">
    {m.admin_settings_taxon_sync_vernacular_hint()}
  </p>

  <div class="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
    <!-- Batch size -->
    <div>
      <label
        for="vernacular-batch-size"
        class="block text-sm font-medium text-stone-700"
      >
        {m.admin_settings_taxon_sync_vernacular_batch_size_label()}
      </label>
      <input
        type="number"
        id="vernacular-batch-size"
        value={vernacularBatchSize}
        oninput={handleVernacularBatchSizeChange}
        min="1"
        max="500"
        class="mt-1 block w-full rounded-md border border-stone-300 px-3 py-2 shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 sm:text-sm"
      />
      <p class="mt-1 text-xs text-stone-500">
        {m.admin_settings_taxon_sync_vernacular_batch_size_hint()}
      </p>
    </div>

    <!-- Locales -->
    <div>
      <label for="vernacular-locales" class="block text-sm font-medium text-stone-700">
        {m.admin_settings_taxon_sync_vernacular_locales_label()}
      </label>
      <input
        type="text"
        id="vernacular-locales"
        value={vernacularLocales}
        oninput={handleVernacularLocalesChange}
        placeholder="ja, en"
        class="mt-1 block w-full rounded-md border border-stone-300 px-3 py-2 shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 sm:text-sm"
      />
      <p class="mt-1 text-xs text-stone-500">
        {m.admin_settings_taxon_sync_vernacular_locales_hint()}
      </p>
    </div>
  </div>

  <!-- Skip existing -->
  <div class="mt-4 flex items-center justify-between">
    <div class="flex-1">
      <label
        for="vernacular-skip-existing"
        class="block text-sm font-medium text-stone-700"
      >
        {m.admin_settings_taxon_sync_vernacular_skip_existing_label()}
      </label>
      <p class="text-sm text-stone-500">
        {m.admin_settings_taxon_sync_vernacular_skip_existing_hint()}
      </p>
    </div>
    <button
      type="button"
      id="vernacular-skip-existing"
      onclick={handleVernacularSkipExistingToggle}
      class="relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 {vernacularSkipExisting
        ? 'bg-primary-600'
        : 'bg-stone-200'}"
      role="switch"
      aria-checked={vernacularSkipExisting}
    >
      <span class="sr-only">
        {m.admin_settings_taxon_sync_vernacular_skip_existing_label()}
      </span>
      <span
        aria-hidden="true"
        class="pointer-events-none inline-block h-5 w-5 transform rounded-full bg-surface-card shadow ring-0 transition duration-200 ease-in-out {vernacularSkipExisting
          ? 'translate-x-5'
          : 'translate-x-0'}"
      ></span>
    </button>
  </div>

  <div class="mt-4 flex justify-end">
    <button
      type="button"
      onclick={() => (showSyncVernacularConfirm = true)}
      disabled={isSyncing}
      class="inline-flex items-center rounded-md border border-transparent bg-primary-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
    >
      {#if isSyncing}
        <svg
          class="mr-2 h-4 w-4 animate-spin"
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
        >
          <circle
            class="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            stroke-width="4"
          ></circle>
          <path
            class="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
          ></path>
        </svg>
        {m.admin_settings_taxon_dispatching()}
      {:else}
        {m.admin_settings_taxon_sync_vernacular_button()}
      {/if}
    </button>
  </div>
</div>

<!-- Sync vernacular confirmation modal -->
{#if showSyncVernacularConfirm}
  <div
    class="fixed inset-0 z-50 overflow-y-auto"
    aria-labelledby="sync-vernacular-modal-title"
    role="dialog"
    aria-modal="true"
  >
    <div class="flex min-h-screen items-end justify-center px-4 pb-20 pt-4 text-center sm:block sm:p-0">
      <!-- Background overlay -->
      <div
        class="fixed inset-0 bg-stone-500 bg-opacity-75 transition-opacity"
        aria-hidden="true"
        onclick={() => (showSyncVernacularConfirm = false)}
      ></div>

      <!-- Center modal -->
      <span class="hidden sm:inline-block sm:h-screen sm:align-middle" aria-hidden="true">&#8203;</span>

      <!-- Modal panel -->
      <div class="inline-block transform overflow-hidden rounded-lg bg-surface-card text-left align-bottom shadow-xl transition-all sm:my-8 sm:w-full sm:max-w-lg sm:align-middle">
        <div class="bg-surface-card px-4 pb-4 pt-5 sm:p-6 sm:pb-4">
          <h3 class="text-lg font-medium leading-6 text-stone-900" id="sync-vernacular-modal-title">
            {m.admin_settings_taxon_sync_vernacular_label()}
          </h3>
          <div class="mt-2">
            <p class="text-sm text-stone-500">
              {m.admin_settings_taxon_sync_vernacular_confirm()}
            </p>
          </div>
        </div>
        <div class="bg-stone-50 px-4 py-3 sm:flex sm:flex-row-reverse sm:px-6">
          <button
            type="button"
            onclick={handleConfirm}
            class="inline-flex w-full justify-center rounded-md bg-primary-600 px-4 py-2 text-base font-medium text-white shadow-sm hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 sm:ml-3 sm:w-auto sm:text-sm dark:bg-primary-500 dark:hover:bg-primary-400"
          >
            {m.admin_settings_taxon_sync_vernacular_button()}
          </button>
          <button
            type="button"
            onclick={() => (showSyncVernacularConfirm = false)}
            class="mt-3 inline-flex w-full justify-center rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-base font-medium text-stone-700 shadow-sm hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 sm:ml-3 sm:mt-0 sm:w-auto sm:text-sm"
          >
            {m.admin_settings_taxon_cancel()}
          </button>
        </div>
      </div>
    </div>
  </div>
{/if}
