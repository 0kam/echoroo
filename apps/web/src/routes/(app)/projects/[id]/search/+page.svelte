<script lang="ts">
  /**
   * Enhanced similarity search page.
   *
   * Uses a 3-mode single-column layout:
   * - 'list'       : Default view with session list and embedding stats
   * - 'detail'     : Full-width session detail view
   * - 'new-search' : Full-width new search form with results
   *
   * Search is async: POST /search/batch returns a job_id (202 Accepted),
   * and we poll GET /search/jobs/{job_id} every 2 seconds until completion.
   */

  import { onDestroy } from 'svelte';
  import { page } from '$app/stores';
  import { createQuery } from '@tanstack/svelte-query';
  import { localizeHref, getLocale } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import { searchBatch, getSearchJobStatus, fetchEmbeddingStats } from '$lib/api/search';
  import ReferenceSoundsPanel from '$lib/components/search/ReferenceSoundsPanel.svelte';
  import SearchConfigBar from '$lib/components/search/SearchConfigBar.svelte';
  import ResultsPanel from '$lib/components/search/ResultsPanel.svelte';
  import SearchSessionList from '$lib/components/search/SearchSessionList.svelte';
  import SearchSessionExportButton from '$lib/components/search/SearchSessionExportButton.svelte';
  import SearchSessionDetail from '$lib/components/search/SearchSessionDetail.svelte';
  import type {
    TargetSpecies,
    SearchConfig,
    SpeciesMatchResult,
    EmbeddingStats,
  } from '$lib/types/search';

  const projectId = $derived($page.params.id as string);

  // ============================================
  // View mode state
  // ============================================

  let viewMode = $state<'list' | 'detail' | 'new-search'>('list');
  let selectedSessionId = $state<string | null>(null);

  // ============================================
  // Search state
  // ============================================

  let species = $state<TargetSpecies[]>([]);
  let config = $state<SearchConfig>({
    model_name: 'perch',
    // Use a low backend threshold to fetch all results; client-side filtering applied in ResultsPanel
    min_similarity: 0.1,
    limit_per_species: 200,
    dataset_id: undefined,
  });
  let results = $state<Record<string, SpeciesMatchResult> | null>(null);
  let totalMatches = $state(0);
  let searchDurationMs = $state(0);
  let isSearching = $state(false);
  let searchError = $state<string | undefined>(undefined);

  // Async job polling state
  let searchJobId = $state<string | null>(null);
  let searchProgress = $state<{ species_completed: number; species_total: number } | null>(null);
  let pollingInterval = $state<ReturnType<typeof setInterval> | null>(null);

  // Session persistence state
  let searchSessionId = $state<string | null>(null);
  let sessionRefreshTrigger = $state(0);

  // Session reference audio display state (used when re-running from detail view)
  /** Session ID to pass as source_session_id when re-running a search */
  let rerunSourceSessionId = $state<string | null>(null);
  /** Whether the current search is a re-run using S3 sources from a prior session */
  let isRerunMode = $state(false);

  // ============================================
  // Derived
  // ============================================

  const hasAllSources = $derived(
    species.length > 0 && species.every((sp) => sp.sources.length > 0)
  );

  /** Human-readable searching status message for the progress indicator. */
  const searchStatusMessage = $derived(() => {
    if (!isSearching) return '';
    if (searchProgress) {
      return m.search_analyzing({
        completed: String(searchProgress.species_completed),
        total: String(searchProgress.species_total),
      });
    }
    return m.search_starting();
  });

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
  // Polling cleanup
  // ============================================

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

    // Cancel any in-flight poll from a previous search
    stopPolling();

    isSearching = true;
    searchError = undefined;
    results = null;
    searchJobId = null;
    searchProgress = null;

    try {
      const response = await searchBatch(projectId, species, config, rerunSourceSessionId ?? undefined);
      rerunSourceSessionId = null;
      isRerunMode = false;
      searchJobId = response.job_id;
      searchSessionId = response.session_id ?? null;

      // Begin polling the job status endpoint every 2 seconds
      pollingInterval = setInterval(async () => {
        try {
          const status = await getSearchJobStatus(projectId, response.job_id, getLocale());

          // Capture session_id from polling response if not yet available
          if (status.session_id) {
            searchSessionId = status.session_id;
          }

          if (status.status === 'processing') {
            searchProgress = status.progress;
          } else if (status.status === 'completed') {
            stopPolling();
            if (status.results) {
              results = status.results.results;
              totalMatches = status.results.total_matches;
              searchDurationMs = status.results.search_duration_ms;
            }
            isSearching = false;
            // Trigger a refresh of the session history list
            sessionRefreshTrigger++;
            // Automatically transition to detail mode for the completed session
            if (searchSessionId) {
              selectedSessionId = searchSessionId;
              viewMode = 'detail';
            }
          } else if (status.status === 'failed') {
            stopPolling();
            searchError = status.error ?? m.search_failed();
            isSearching = false;
          }
          // 'pending' state: keep polling without any state change
        } catch (pollErr) {
          // Do not stop polling on transient network errors
          console.warn('Search job polling error:', pollErr);
        }
      }, 2000);
    } catch (err) {
      searchError = err instanceof Error ? err.message : m.search_error_search_failed();
      isSearching = false;
    }
  }

  // ============================================
  // Mode transition handlers
  // ============================================

  /**
   * Transition: list -> new-search
   * Resets all search state and shows the search form.
   */
  function handleNewSearch() {
    stopPolling();
    species = [];
    results = null;
    totalMatches = 0;
    searchDurationMs = 0;
    isSearching = false;
    searchError = undefined;
    searchJobId = null;
    searchProgress = null;
    searchSessionId = null;
    isRerunMode = false;
    rerunSourceSessionId = null;
    viewMode = 'new-search';
  }

  /**
   * Transition: list -> detail
   * Opens a session selected from the session list.
   */
  function handleSelectSession(sessionId: string) {
    selectedSessionId = sessionId;
    viewMode = 'detail';
  }

  /**
   * Transition: detail -> list (also from new-search -> list)
   */
  function handleBackToList() {
    selectedSessionId = null;
    viewMode = 'list';
  }

  /**
   * Transition: detail -> new-search
   * Pre-populates search state with species from the session being re-run.
   */
  function handleRerunFromDetail(rerunSpecies: TargetSpecies[]) {
    const sessionIdForRerun = selectedSessionId;
    species = rerunSpecies;
    isRerunMode = true;
    rerunSourceSessionId = sessionIdForRerun;
    results = null;
    totalMatches = 0;
    searchDurationMs = 0;
    searchJobId = null;
    searchSessionId = null;
    selectedSessionId = null;
    viewMode = 'new-search';
  }
</script>

<svelte:head>
  <title>{m.search_page_title()}</title>
</svelte:head>

<div class="mx-auto max-w-5xl px-4 py-6">

  <!-- Breadcrumb (always visible) -->
  <nav class="mb-6 flex items-center gap-2 text-sm text-stone-500 dark:text-stone-400">
    <a href={localizeHref(`/projects/${projectId}`)} class="hover:text-stone-900 dark:hover:text-stone-200">
      {m.search_breadcrumb_project()}
    </a>
    <span>/</span>
    <span class="font-medium text-stone-900 dark:text-stone-100">{m.search_title()}</span>
  </nav>

  <!-- Mode: list -->
  {#if viewMode === 'list'}
    <div class="space-y-6">
      <!-- Page header -->
      <div>
        <h1 class="text-2xl font-bold text-stone-900 dark:text-stone-100">{m.search_title()}</h1>
        <p class="mt-1 text-sm text-stone-500 dark:text-stone-400">{m.search_description()}</p>
      </div>

      <!-- Session list (full-width) -->
      <SearchSessionList
        {projectId}
        onSelectSession={handleSelectSession}
        onNewSearch={handleNewSearch}
        activeSessionId={selectedSessionId ?? undefined}
        refreshTrigger={sessionRefreshTrigger}
      />

      <!-- Embedding stats section -->
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

  <!-- Mode: detail -->
  {:else if viewMode === 'detail' && selectedSessionId}
    <SearchSessionDetail
      {projectId}
      sessionId={selectedSessionId}
      onBack={handleBackToList}
      onRerun={handleRerunFromDetail}
    />

  <!-- Mode: new-search -->
  {:else if viewMode === 'new-search'}
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
        {m.search_back_to_sessions()}
      </button>

      <!-- Page heading -->
      <h1 class="text-2xl font-bold text-stone-900 dark:text-stone-100">{m.search_new_search()}</h1>

      <!-- Reference Sounds Panel (editable) -->
      <ReferenceSoundsPanel
        {projectId}
        {species}
        modelName={config.model_name}
        onSpeciesChange={handleSpeciesChange}
      />

      <!-- Search Configuration Bar -->
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

      <!-- Search progress indicator (shown while async job is running) -->
      {#if isSearching && !results}
        <div class="flex items-center gap-3 rounded-lg border border-card bg-surface-card p-4 text-sm text-stone-600 dark:text-stone-400">
          <svg class="h-4 w-4 shrink-0 animate-spin text-primary-500" fill="none" viewBox="0 0 24 24" aria-hidden="true">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
          </svg>
          <span>{searchStatusMessage()}</span>
        </div>
      {/if}

      <!-- Export button (show when session exists and has results) -->
      {#if searchSessionId && results}
        <div class="flex justify-end">
          <SearchSessionExportButton {projectId} sessionId={searchSessionId} />
        </div>
      {/if}

      <!-- Results Panel (only show when searching or have results) -->
      {#if isSearching || results}
        <ResultsPanel
          {projectId}
          {results}
          {totalMatches}
          {searchDurationMs}
          {isSearching}
          searchingSpecies={species}
          searchSessionId={searchSessionId ?? undefined}
        />
      {/if}
    </div>
  {/if}

</div>
