<script lang="ts">
  /**
   * Enhanced similarity search page.
   *
   * Composes the species-based batch search workflow:
   * 1. ReferenceSoundsPanel — select target species and add reference sounds
   * 2. SearchConfigBar — configure model, threshold, limits, dataset filter
   * 3. ResultsPanel — display per-species search results
   * 4. Inline embedding stats — project-level embedding statistics
   */

  import { page } from '$app/stores';
  import { createQuery } from '@tanstack/svelte-query';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import { searchBatch, fetchEmbeddingStats } from '$lib/api/search';
  import ReferenceSoundsPanel from '$lib/components/search/ReferenceSoundsPanel.svelte';
  import SearchConfigBar from '$lib/components/search/SearchConfigBar.svelte';
  import ResultsPanel from '$lib/components/search/ResultsPanel.svelte';
  import type {
    TargetSpecies,
    SearchConfig,
    SpeciesMatchResult,
    BatchSearchResponse,
    EmbeddingStats,
  } from '$lib/types/search';

  const projectId = $derived($page.params.id as string);

  // ============================================
  // State
  // ============================================

  let species = $state<TargetSpecies[]>([]);
  let config = $state<SearchConfig>({
    model_name: 'perch',
    min_similarity: 0.5,
    limit_per_species: 20,
    dataset_id: undefined,
  });
  let results = $state<Record<string, SpeciesMatchResult> | null>(null);
  let totalMatches = $state(0);
  let searchDurationMs = $state(0);
  let isSearching = $state(false);
  let searchError = $state<string | undefined>(undefined);

  // ============================================
  // Derived
  // ============================================

  const hasAllSources = $derived(
    species.length > 0 && species.every((sp) => sp.sources.length > 0)
  );

  // ============================================
  // Embedding stats query (project-level)
  // ============================================

  const statsQuery = $derived(
    createQuery({
      queryKey: ['embedding-stats', projectId],
      queryFn: () => fetchEmbeddingStats(projectId),
      enabled: !!projectId,
    })
  );

  // ============================================
  // Handlers
  // ============================================

  function handleSpeciesChange(updated: TargetSpecies[]) {
    species = updated;
  }

  function handleConfigChange(updated: SearchConfig) {
    config = updated;
  }

  async function handleSearch() {
    if (!hasAllSources || species.length === 0) return;

    isSearching = true;
    searchError = undefined;
    results = null;

    try {
      const response: BatchSearchResponse = await searchBatch(projectId, species, config);
      results = response.results;
      totalMatches = response.total_matches;
      searchDurationMs = response.search_duration_ms;
    } catch (err) {
      searchError = err instanceof Error ? err.message : m.search_error_search_failed();
    } finally {
      isSearching = false;
    }
  }
</script>

<svelte:head>
  <title>{m.search_page_title()}</title>
</svelte:head>

<div class="mx-auto max-w-5xl space-y-6 px-4 py-6">
  <!-- Page header -->
  <div>
    <nav class="mb-2 flex items-center gap-2 text-sm text-stone-500 dark:text-stone-400">
      <a href={localizeHref(`/projects/${projectId}`)} class="hover:text-stone-900 dark:hover:text-stone-200">
        {m.search_breadcrumb_project()}
      </a>
      <span>/</span>
      <span class="font-medium text-stone-900 dark:text-stone-100">{m.search_title()}</span>
    </nav>
    <h1 class="text-2xl font-bold text-stone-900 dark:text-stone-100">{m.search_title()}</h1>
    <p class="mt-1 text-sm text-stone-500 dark:text-stone-400">{m.search_description()}</p>
  </div>

  <!-- [A] Reference Sounds Panel -->
  <ReferenceSoundsPanel
    {projectId}
    {species}
    modelName={config.model_name}
    onSpeciesChange={handleSpeciesChange}
  />

  <!-- [B] Search Configuration Bar -->
  <SearchConfigBar
    {projectId}
    {config}
    speciesCount={species.length}
    {hasAllSources}
    {isSearching}
    onConfigChange={handleConfigChange}
    onSearch={handleSearch}
  />

  <!-- Error display -->
  {#if searchError}
    <div class="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-400">
      {searchError}
    </div>
  {/if}

  <!-- [C] Results Panel (only show when searching or have results) -->
  {#if isSearching || results}
    <ResultsPanel
      {projectId}
      {results}
      {totalMatches}
      {searchDurationMs}
      {isSearching}
      searchingSpecies={species}
    />
  {/if}

  <!-- [D] Embedding Stats (project-level) -->
  <div class="rounded-lg border border-card bg-surface-card p-6 shadow-sm">
    <h2 class="mb-4 text-sm font-semibold uppercase tracking-wider text-stone-500 dark:text-stone-400">
      {m.search_embedding_stats()}
    </h2>

    {#if $statsQuery.isLoading}
      <div class="flex items-center gap-2 text-sm text-stone-400">
        <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
        Loading...
      </div>
    {:else if $statsQuery.isError}
      <p class="text-sm text-red-500">Failed to load embedding statistics.</p>
    {:else if $statsQuery.data}
      {@const stats = $statsQuery.data as EmbeddingStats}
      {#if stats.total_count === 0}
        <!-- No embeddings -->
        <div class="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-400">
          {m.search_no_embeddings()}
        </div>
      {:else}
        <div class="flex flex-wrap gap-6">
          <!-- Total count -->
          <div>
            <p class="text-xs font-medium uppercase tracking-wider text-stone-400 dark:text-stone-500">
              {m.search_total_embeddings()}
            </p>
            <p class="mt-1 text-2xl font-bold text-stone-900 dark:text-stone-100">
              {stats.total_count.toLocaleString()}
            </p>
          </div>

          <!-- By model -->
          {#if Object.keys(stats.by_model).length > 0}
            <div>
              <p class="text-xs font-medium uppercase tracking-wider text-stone-400 dark:text-stone-500">
                {m.search_stats_by_model()}
              </p>
              <div class="mt-1 flex flex-wrap gap-2">
                {#each Object.entries(stats.by_model) as [model, count] (model)}
                  <span class="inline-flex items-center gap-1 rounded-full bg-primary-100 px-2.5 py-0.5 text-xs font-medium text-primary-800 dark:bg-primary-900/30 dark:text-primary-300">
                    {model}: {count.toLocaleString()}
                  </span>
                {/each}
              </div>
            </div>
          {/if}
        </div>
      {/if}
    {/if}
  </div>
</div>
