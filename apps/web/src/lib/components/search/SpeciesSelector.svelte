<script lang="ts">
  /**
   * SpeciesSelector - Inline typeahead panel for adding a target species.
   *
   * Searches three sources in parallel with debounced input:
   * 1. Project tags (category=species)
   * 2. Local taxon database (including vernacular/Japanese names)
   * 3. GBIF backbone taxonomy (real-time, for species not in local DB)
   *
   * Allows selecting an existing tag, a taxon result, a GBIF result,
   * or adding a custom species by name.
   */

  import { onMount } from 'svelte';
  import * as m from '$lib/paraglide/messages.js';
  import { fetchTags } from '$lib/api/tags';
  import { searchGBIF, searchTaxa } from '$lib/api/taxa';
  import type { Tag } from '$lib/types/annotation';
  import type { GBIFSpeciesResult, TaxonSearchResult } from '$lib/types/taxon';

  interface Props {
    projectId: string;
    /** Tag IDs that have already been added (shown grayed out with checkmark) */
    addedSpeciesIds: Set<string>;
    onAdd: (species: { tag_id: string | null; scientific_name: string; common_name?: string }) => void;
    onClose: () => void;
  }

  let { projectId, addedSpeciesIds, onAdd, onClose }: Props = $props();

  let inputEl: HTMLInputElement | undefined = $state();
  let query = $state('');
  let suggestions = $state<Tag[]>([]);
  let taxonResults = $state<TaxonSearchResult[]>([]);
  let gbifResults = $state<GBIFSpeciesResult[]>([]);
  let isLoading = $state(false);
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;

  // Auto-focus the input when the component mounts
  onMount(() => {
    inputEl?.focus();
  });

  // Deduplicated taxon results: exclude taxa that already appear in project tags
  let filteredTaxonResults = $derived(() => {
    const tagScientificNames = new Set(
      suggestions.map((t) => (t.scientific_name ?? t.name).toLowerCase())
    );
    return taxonResults.filter(
      (tr) => !tagScientificNames.has(tr.scientific_name.toLowerCase())
    );
  });

  // Deduplicated GBIF results: exclude species already found in project tags or local taxon DB
  let filteredGbifResults = $derived(() => {
    const existingNames = new Set([
      ...suggestions.map((t) => (t.scientific_name ?? t.name).toLowerCase()),
      ...taxonResults.map((tr) => tr.scientific_name.toLowerCase()),
    ]);
    return gbifResults.filter(
      (gr) => !existingNames.has(gr.canonical_name.toLowerCase())
    );
  });

  // Whether the query exactly matches a suggestion's scientific name or name
  let exactMatch = $derived(
    suggestions.some(
      (t) =>
        (t.scientific_name ?? t.name).toLowerCase() === query.toLowerCase() ||
        t.name.toLowerCase() === query.toLowerCase()
    ) ||
    taxonResults.some(
      (tr) =>
        tr.scientific_name.toLowerCase() === query.toLowerCase() ||
        (tr.common_name?.toLowerCase() === query.toLowerCase())
    ) ||
    gbifResults.some(
      (gr) =>
        gr.canonical_name.toLowerCase() === query.toLowerCase() ||
        (gr.vernacular_name?.toLowerCase() === query.toLowerCase())
    )
  );

  async function search(value: string) {
    const trimmed = value.trim();
    if (trimmed.length < 1) {
      suggestions = [];
      taxonResults = [];
      gbifResults = [];
      isLoading = false;
      return;
    }

    isLoading = true;

    // Search project tags and local taxon database in parallel immediately.
    // Also search GBIF when query is at least 2 characters.
    // Do NOT pass locale so the search covers all vernacular names
    // (e.g. a user on the English page can still search Japanese names).
    const searches: [
      Promise<Awaited<ReturnType<typeof fetchTags>>>,
      Promise<TaxonSearchResult[]>,
      Promise<GBIFSpeciesResult[]>,
    ] = [
      fetchTags(projectId, {
        search: trimmed,
        category: 'species',
        page_size: 20,
      }),
      searchTaxa(trimmed, undefined, 15),
      trimmed.length >= 2 ? searchGBIF(trimmed, 10) : Promise.resolve([]),
    ];

    const [tagResult, taxonResult, gbifResult] = await Promise.allSettled(searches);

    suggestions = tagResult.status === 'fulfilled' ? tagResult.value.items : [];
    taxonResults = taxonResult.status === 'fulfilled' ? taxonResult.value : [];
    gbifResults = gbifResult.status === 'fulfilled' ? gbifResult.value : [];

    isLoading = false;
  }

  function handleInput() {
    if (debounceTimer !== null) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => void search(query), 300);
  }

  function addSpecies(tag: Tag) {
    if (addedSpeciesIds.has(tag.id)) return;
    onAdd({
      tag_id: tag.id,
      scientific_name: tag.scientific_name ?? tag.name,
      common_name: tag.common_name ?? undefined,
    });
    query = '';
    suggestions = [];
    taxonResults = [];
    gbifResults = [];
  }

  function addTaxonSpecies(taxon: TaxonSearchResult) {
    onAdd({
      tag_id: null,
      scientific_name: taxon.scientific_name,
      common_name: taxon.common_name ?? undefined,
    });
    query = '';
    suggestions = [];
    taxonResults = [];
    gbifResults = [];
  }

  function addGbifSpecies(result: GBIFSpeciesResult) {
    onAdd({
      tag_id: null,
      scientific_name: result.canonical_name,
      common_name: result.vernacular_name ?? undefined,
    });
    query = '';
    suggestions = [];
    taxonResults = [];
    gbifResults = [];
  }

  function addCustom() {
    const trimmed = query.trim();
    if (trimmed.length < 2) return;
    onAdd({
      tag_id: null,
      scientific_name: trimmed,
    });
    query = '';
    suggestions = [];
    taxonResults = [];
    gbifResults = [];
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') {
      e.preventDefault();
      // Add top non-added suggestion, or first taxon result, or first GBIF result, or custom
      const first = suggestions.find((t) => !addedSpeciesIds.has(t.id));
      if (first) {
        addSpecies(first);
      } else if (filteredTaxonResults().length > 0) {
        const firstTaxon = filteredTaxonResults()[0];
        if (firstTaxon) addTaxonSpecies(firstTaxon);
      } else if (filteredGbifResults().length > 0) {
        const firstGbif = filteredGbifResults()[0];
        if (firstGbif) addGbifSpecies(firstGbif);
      } else if (query.trim().length >= 2 && !exactMatch) {
        addCustom();
      }
    }
    if (e.key === 'Escape') {
      onClose();
    }
  }
</script>

<div class="rounded-lg border border-stone-200 bg-stone-50 p-4 space-y-3 dark:border-stone-700 dark:bg-stone-800/50">
  <p class="text-sm font-medium text-stone-900">
    {m.search_species_selector_title()}
  </p>

  <!-- Search input -->
  <div class="relative">
    <!-- Search icon -->
    <svg class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-stone-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
      <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
    </svg>
    <input
      bind:this={inputEl}
      bind:value={query}
      type="text"
      class="w-full rounded-md border border-stone-300 bg-surface-card py-1.5 pl-9 pr-3 text-sm
             text-stone-900 placeholder-stone-400 focus:border-primary-500 focus:outline-none focus:ring-1
             focus:ring-primary-500 dark:border-stone-600"
      placeholder={m.search_species_selector_placeholder()}
      oninput={handleInput}
      onkeydown={handleKeydown}
      autocomplete="off"
    />
    {#if isLoading}
      <div class="absolute right-3 top-1/2 -translate-y-1/2">
        <div class="h-3.5 w-3.5 animate-spin rounded-full border-2 border-stone-300 border-t-primary-500"></div>
      </div>
    {/if}
  </div>

  <!-- Suggestions dropdown -->
  {#if suggestions.length > 0 || filteredTaxonResults().length > 0 || filteredGbifResults().length > 0}
    <div class="max-h-64 overflow-y-auto divide-y divide-stone-200 rounded-lg border border-stone-200 dark:divide-stone-700 dark:border-stone-700">
      <!-- Project species section -->
      {#if suggestions.length > 0}
        <div class="px-3 py-1.5 bg-stone-100 dark:bg-stone-700/30">
          <span class="text-xs font-medium uppercase tracking-wide text-stone-500">
            {m.search_species_section_project()}
          </span>
        </div>
        {#each suggestions as tag (tag.id)}
          {@const alreadyAdded = addedSpeciesIds.has(tag.id)}
          <div
            class="flex items-center justify-between px-3 py-2
                   {alreadyAdded ? 'opacity-50' : 'hover:bg-stone-100 dark:hover:bg-stone-700/50'}"
          >
            <div class="min-w-0 flex-1">
              <span class="text-sm italic text-stone-900">
                {tag.scientific_name ?? tag.name}
              </span>
              {#if tag.common_name}
                <span class="ml-2 text-sm text-stone-500">{tag.common_name}</span>
              {/if}
            </div>
            {#if alreadyAdded}
              <!-- Check icon -->
              <svg class="h-4 w-4 shrink-0 text-stone-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                <path d="M20 6 9 17l-5-5" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            {:else}
              <button
                type="button"
                class="ml-2 shrink-0 text-primary-600 transition-colors hover:text-primary-700 dark:text-primary-400"
                onclick={() => addSpecies(tag)}
                aria-label="Add {tag.scientific_name ?? tag.name}"
              >
                <!-- Plus icon -->
                <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                  <path d="M12 5v14M5 12h14" stroke-linecap="round" />
                </svg>
              </button>
            {/if}
          </div>
        {/each}
      {/if}

      <!-- Global taxon database section -->
      {#if filteredTaxonResults().length > 0}
        <div class="px-3 py-1.5 bg-stone-100 dark:bg-stone-700/30">
          <span class="text-xs font-medium uppercase tracking-wide text-stone-500">
            {m.search_species_section_taxon_db()}
          </span>
        </div>
        {#each filteredTaxonResults() as taxon (taxon.id)}
          <div
            class="flex items-center justify-between px-3 py-2 hover:bg-stone-100 dark:hover:bg-stone-700/50"
          >
            <div class="min-w-0 flex-1">
              <span class="text-sm italic text-stone-900">
                {taxon.scientific_name}
              </span>
              {#if taxon.common_name}
                <span class="ml-2 text-sm text-stone-500">{taxon.common_name}</span>
              {/if}
            </div>
            <button
              type="button"
              class="ml-2 shrink-0 text-primary-600 transition-colors hover:text-primary-700 dark:text-primary-400"
              onclick={() => addTaxonSpecies(taxon)}
              aria-label="Add {taxon.scientific_name}"
            >
              <!-- Plus icon -->
              <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                <path d="M12 5v14M5 12h14" stroke-linecap="round" />
              </svg>
            </button>
          </div>
        {/each}
      {/if}

      <!-- GBIF real-time search section -->
      {#if filteredGbifResults().length > 0}
        <div class="px-3 py-1.5 bg-stone-100 dark:bg-stone-700/30">
          <span class="text-xs font-medium uppercase tracking-wide text-stone-500">
            {m.search_species_section_gbif()}
          </span>
        </div>
        {#each filteredGbifResults() as result (result.gbif_key)}
          <div
            class="flex items-center justify-between px-3 py-2 hover:bg-stone-100 dark:hover:bg-stone-700/50"
          >
            <div class="min-w-0 flex-1">
              <span class="text-sm italic text-stone-900">
                {result.canonical_name}
              </span>
              {#if result.vernacular_name}
                <span class="ml-2 text-sm text-stone-500">{result.vernacular_name}</span>
              {/if}
            </div>
            <button
              type="button"
              class="ml-2 shrink-0 text-primary-600 transition-colors hover:text-primary-700 dark:text-primary-400"
              onclick={() => addGbifSpecies(result)}
              aria-label="Add {result.canonical_name}"
            >
              <!-- Plus icon -->
              <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                <path d="M12 5v14M5 12h14" stroke-linecap="round" />
              </svg>
            </button>
          </div>
        {/each}
      {/if}
    </div>
  {/if}

  <!-- Custom entry (if no exact match and query is long enough) -->
  {#if query.trim().length >= 2 && !exactMatch}
    <div class="text-sm text-stone-500">
      <p>{m.search_species_selector_custom_hint()}</p>
      <div class="mt-1 flex items-center gap-2">
        <span class="italic">"{query.trim()}"</span>
        <button
          type="button"
          class="rounded border border-stone-300 px-2 py-0.5 text-xs text-stone-700 transition-colors
                 hover:border-primary-400 hover:text-primary-700 dark:border-stone-600"
          onclick={addCustom}
        >
          {m.search_species_selector_add_custom()}
        </button>
      </div>
    </div>
  {/if}

  <!-- Close link -->
  <div class="text-right">
    <button
      type="button"
      class="text-sm text-stone-500 transition-colors hover:text-stone-700 dark:hover:text-stone-200"
      onclick={onClose}
    >
      {m.search_species_selector_close()}
    </button>
  </div>
</div>
