<script lang="ts">
  /**
   * SearchConfigBar - Compact configuration bar for batch species search.
   *
   * Provides selectors for model, similarity threshold, max results per species,
   * and dataset filter. Includes a search button with validation feedback.
   */

  import { onMount } from 'svelte';
  import * as m from '$lib/paraglide/messages.js';
  import { fetchDatasets } from '$lib/api/datasets';
  import type { Dataset } from '$lib/types/data';
  import type { SearchConfig } from '$lib/types/search';

  interface Props {
    projectId: string;
    config: SearchConfig;
    speciesCount: number;
    hasAllSources: boolean;
    isSearching: boolean;
    onConfigChange: (config: SearchConfig) => void;
    onSearch: () => void;
  }

  let {
    projectId,
    config,
    speciesCount,
    hasAllSources,
    isSearching,
    onConfigChange,
    onSearch,
  }: Props = $props();

  let datasets = $state<Dataset[]>([]);

  onMount(async () => {
    try {
      const response = await fetchDatasets(projectId, { page_size: 100 });
      datasets = response.items;
    } catch {
      // Silently fail — dataset filter will just show "All Datasets"
    }
  });

  function emitChange() {
    onConfigChange({ ...config });
  }

  const canSearch = $derived(speciesCount > 0 && hasAllSources && !isSearching);
</script>

<div class="rounded-lg border border-card bg-surface-card p-4 shadow-sm">
  <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
    <!-- Model selector -->
    <div>
      <label for="scb-model" class="mb-1 block text-sm font-medium text-stone-700">
        {m.search_model()}
      </label>
      <select
        id="scb-model"
        class="w-full rounded-md border border-card bg-surface-card px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
        bind:value={config.model_name}
        onchange={emitChange}
      >
        <option value="perch">Perch v2.0</option>
        <option value="birdnet">BirdNET</option>
      </select>
    </div>

    <!-- Dataset filter -->
    <div>
      <label for="scb-dataset" class="mb-1 block text-sm font-medium text-stone-700">
        {m.search_dataset()}
      </label>
      <select
        id="scb-dataset"
        class="w-full rounded-md border border-card bg-surface-card px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
        bind:value={config.dataset_id}
        onchange={emitChange}
      >
        <option value="">{m.search_all_datasets()}</option>
        {#each datasets as ds (ds.id)}
          <option value={ds.id}>{ds.name}</option>
        {/each}
      </select>
    </div>
  </div>

  <!-- Search button + validation -->
  <div class="mt-4 flex items-center justify-between">
    {#if speciesCount > 0 && !hasAllSources}
      <p class="text-sm text-warning">{m.search_validation_hint()}</p>
    {:else}
      <div></div>
    {/if}

    <button
      class="flex items-center gap-2 rounded-md bg-primary-600 px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50"
      onclick={onSearch}
      disabled={!canSearch}
      type="button"
    >
      {#if isSearching}
        <!-- Spinner icon -->
        <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
        {m.search_searching()}
      {:else}
        <!-- Search icon -->
        <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        {speciesCount > 1 ? m.search_search_all() : m.search_search_single()}
      {/if}
    </button>
  </div>
</div>
