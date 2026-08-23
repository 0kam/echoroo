<script lang="ts">
  /**
   * Bundled vernacular-name load panel (subsection of the taxon maintenance card).
   *
   * Dispatches the `load_bundled_vernacular_names` task, which upserts the
   * versioned Japanese names shipped inside the API package (IOC World Bird
   * List via the AviList crosswalk) onto the local taxa. No network access is
   * involved and the task is idempotent. The BirdNET seed already performs
   * this load, so this action exists for re-running after the bundle is
   * regenerated from a newer upstream release.
   *
   * Mirrors `BirdnetSeedPanel`: owns its confirmation modal and reports via
   * the `onLoad` callback; the parent surfaces results through the shared
   * banners and controls the `isLoading` in-flight flag.
   */

  import * as m from '$lib/paraglide/messages';

  let {
    isLoading,
    onLoad,
  }: {
    isLoading: boolean;
    onLoad: () => void;
  } = $props();

  let showLoadBundledConfirm = $state(false);

  function handleConfirm() {
    showLoadBundledConfirm = false;
    onLoad();
  }
</script>

<!-- Load bundled vernacular names -->
<div>
  <div class="flex items-center justify-between gap-4">
    <div class="flex-1">
      <h3 class="text-sm font-medium text-stone-700">
        {m.admin_settings_taxon_bundled_vernacular_label()}
      </h3>
      <p class="mt-1 text-sm text-stone-500">
        {m.admin_settings_taxon_bundled_vernacular_hint()}
      </p>
    </div>
    <button
      type="button"
      onclick={() => (showLoadBundledConfirm = true)}
      disabled={isLoading}
      class="inline-flex flex-shrink-0 items-center rounded-md border border-transparent bg-primary-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
    >
      {#if isLoading}
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
        {m.admin_settings_taxon_bundled_vernacular_button()}
      {/if}
    </button>
  </div>
</div>

<!-- Load bundled vernacular confirmation modal -->
{#if showLoadBundledConfirm}
  <div
    class="fixed inset-0 z-50 overflow-y-auto"
    aria-labelledby="load-bundled-vernacular-modal-title"
    role="dialog"
    aria-modal="true"
  >
    <div class="flex min-h-screen items-end justify-center px-4 pb-20 pt-4 text-center sm:block sm:p-0">
      <!-- Background overlay -->
      <div
        class="fixed inset-0 bg-stone-500 bg-opacity-75 transition-opacity"
        aria-hidden="true"
        onclick={() => (showLoadBundledConfirm = false)}
      ></div>

      <!-- Center modal -->
      <span class="hidden sm:inline-block sm:h-screen sm:align-middle" aria-hidden="true">&#8203;</span>

      <!-- Modal panel -->
      <div class="inline-block transform overflow-hidden rounded-lg bg-surface-card text-left align-bottom shadow-xl transition-all sm:my-8 sm:w-full sm:max-w-lg sm:align-middle">
        <div class="bg-surface-card px-4 pb-4 pt-5 sm:p-6 sm:pb-4">
          <h3 class="text-lg font-medium leading-6 text-stone-900" id="load-bundled-vernacular-modal-title">
            {m.admin_settings_taxon_bundled_vernacular_label()}
          </h3>
          <div class="mt-2">
            <p class="text-sm text-stone-500">
              {m.admin_settings_taxon_bundled_vernacular_confirm()}
            </p>
          </div>
        </div>
        <div class="bg-stone-50 px-4 py-3 sm:flex sm:flex-row-reverse sm:px-6">
          <button
            type="button"
            onclick={handleConfirm}
            class="inline-flex w-full justify-center rounded-md bg-primary-600 px-4 py-2 text-base font-medium text-white shadow-sm hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 sm:ml-3 sm:w-auto sm:text-sm dark:bg-primary-500 dark:hover:bg-primary-400"
          >
            {m.admin_settings_taxon_bundled_vernacular_button()}
          </button>
          <button
            type="button"
            onclick={() => (showLoadBundledConfirm = false)}
            class="mt-3 inline-flex w-full justify-center rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-base font-medium text-stone-700 shadow-sm hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 sm:ml-3 sm:mt-0 sm:w-auto sm:text-sm"
          >
            {m.admin_settings_taxon_cancel()}
          </button>
        </div>
      </div>
    </div>
  </div>
{/if}
