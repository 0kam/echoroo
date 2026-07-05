<script lang="ts">
  /**
   * BirdNET taxon seed panel (subsection of the taxon maintenance card).
   *
   * Owns its own confirmation modal; dispatches the seed task via the
   * `onSeed` callback once the admin confirms. The parent surfaces results
   * through the shared success/error banners and controls the `isSeeding`
   * in-flight flag.
   */

  import * as m from '$lib/paraglide/messages';

  let {
    isSeeding,
    onSeed,
  }: {
    isSeeding: boolean;
    onSeed: () => void;
  } = $props();

  let showSeedBirdnetConfirm = $state(false);

  function handleConfirm() {
    showSeedBirdnetConfirm = false;
    onSeed();
  }
</script>

<!-- Seed BirdNET taxa -->
<div>
  <div class="flex items-center justify-between gap-4">
    <div class="flex-1">
      <h3 class="text-sm font-medium text-stone-700">
        {m.admin_settings_taxon_seed_birdnet_label()}
      </h3>
      <p class="mt-1 text-sm text-stone-500">
        {m.admin_settings_taxon_seed_birdnet_hint()}
      </p>
    </div>
    <button
      type="button"
      onclick={() => (showSeedBirdnetConfirm = true)}
      disabled={isSeeding}
      class="inline-flex flex-shrink-0 items-center rounded-md border border-transparent bg-primary-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
    >
      {#if isSeeding}
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
        {m.admin_settings_taxon_seed_birdnet_button()}
      {/if}
    </button>
  </div>
</div>

<!-- Seed BirdNET confirmation modal -->
{#if showSeedBirdnetConfirm}
  <div
    class="fixed inset-0 z-50 overflow-y-auto"
    aria-labelledby="seed-birdnet-modal-title"
    role="dialog"
    aria-modal="true"
  >
    <div class="flex min-h-screen items-end justify-center px-4 pb-20 pt-4 text-center sm:block sm:p-0">
      <!-- Background overlay -->
      <div
        class="fixed inset-0 bg-stone-500 bg-opacity-75 transition-opacity"
        aria-hidden="true"
        onclick={() => (showSeedBirdnetConfirm = false)}
      ></div>

      <!-- Center modal -->
      <span class="hidden sm:inline-block sm:h-screen sm:align-middle" aria-hidden="true">&#8203;</span>

      <!-- Modal panel -->
      <div class="inline-block transform overflow-hidden rounded-lg bg-surface-card text-left align-bottom shadow-xl transition-all sm:my-8 sm:w-full sm:max-w-lg sm:align-middle">
        <div class="bg-surface-card px-4 pb-4 pt-5 sm:p-6 sm:pb-4">
          <h3 class="text-lg font-medium leading-6 text-stone-900" id="seed-birdnet-modal-title">
            {m.admin_settings_taxon_seed_birdnet_label()}
          </h3>
          <div class="mt-2">
            <p class="text-sm text-stone-500">
              {m.admin_settings_taxon_seed_birdnet_confirm()}
            </p>
          </div>
        </div>
        <div class="bg-stone-50 px-4 py-3 sm:flex sm:flex-row-reverse sm:px-6">
          <button
            type="button"
            onclick={handleConfirm}
            class="inline-flex w-full justify-center rounded-md bg-primary-600 px-4 py-2 text-base font-medium text-white shadow-sm hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 sm:ml-3 sm:w-auto sm:text-sm dark:bg-primary-500 dark:hover:bg-primary-400"
          >
            {m.admin_settings_taxon_seed_birdnet_button()}
          </button>
          <button
            type="button"
            onclick={() => (showSeedBirdnetConfirm = false)}
            class="mt-3 inline-flex w-full justify-center rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-base font-medium text-stone-700 shadow-sm hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 sm:ml-3 sm:mt-0 sm:w-auto sm:text-sm"
          >
            {m.admin_settings_taxon_cancel()}
          </button>
        </div>
      </div>
    </div>
  </div>
{/if}
