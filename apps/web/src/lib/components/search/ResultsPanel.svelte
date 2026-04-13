<script lang="ts">
  /**
   * ResultsPanel - Displays batch similarity search results in exploration-only mode.
   *
   * Features:
   * - Species tabs (one tab per searched species + "All" tab)
   * - Filter bar: similarity range (min/max) and limit_per_species (user-controlled)
   * - Similarity histogram (pre-computed distribution bins from API, always full range)
   * - Spiral plot (time-of-day distribution)
   * - Sample card grid: random results from the sample API, filtered by user range
   * - Audio playback (Space to play, Arrow keys to navigate)
   *
   * No voting or review actions — this panel is for exploration only.
   */

  import { onDestroy } from 'svelte';
  import { createQuery } from '@tanstack/svelte-query';
  import * as m from '$lib/paraglide/messages.js';
  import type { DistributionBin, SimilarityResult, SpeciesMatchResult, TargetSpecies, TimeDistributionCell } from '$lib/types/search';
  import { getSessionDistribution, getSessionSample, getSessionTimeDistribution } from '$lib/api/search';
  import { createReviewNavigation } from '$lib/utils/reviewNavigation.svelte';
  import SearchPreviewCard from './SearchPreviewCard.svelte';
  import SearchTimeHeatmap from './SearchTimeHeatmap.svelte';
  import SimilarityHistogram from './SimilarityHistogram.svelte';

  interface Props {
    projectId: string;
    results: Record<string, SpeciesMatchResult> | null;
    searchDurationMs: number;
    isSearching: boolean;
    searchingSpecies: TargetSpecies[];
    /** Session ID for distribution and sampling APIs */
    sessionId?: string | null;
    /** Called when the selected species tab changes */
    onSpeciesKeyChange?: (speciesKey: string | null) => void;
    /** Called when the user clicks "Train Model on these results" */
    onTrainModelRequest?: (speciesKey: string, speciesMeta: SpeciesMatchResult) => void;
  }

  let {
    projectId,
    results,
    searchDurationMs,
    isSearching,
    searchingSpecies,
    sessionId = null,
    onSpeciesKeyChange,
    onTrainModelRequest,
  }: Props = $props();

  // ============================================================================
  // Species tabs state
  // ============================================================================

  /**
   * Currently selected species key.
   * Species keys are the top-level keys of the `results` object.
   * Defaults to the first species when results change.
   */
  let selectedSpeciesKey = $state<string | null>(null);

  const speciesEntries = $derived(
    results !== null ? Object.entries(results) : []
  );

  /** Reset tab selection to first species whenever results change (new search completed). */
  let prevResultsRef = $state<Record<string, SpeciesMatchResult> | null>(null);
  $effect(() => {
    if (results !== prevResultsRef) {
      prevResultsRef = results;
      // Default to first species key (never "all")
      const keys = results ? Object.keys(results) : [];
      selectedSpeciesKey = keys.length > 0 ? (keys[0] ?? null) : null;
    }
  });

  /** Notify parent when selected species changes */
  $effect(() => {
    onSpeciesKeyChange?.(selectedSpeciesKey);
  });

  // ============================================================================
  // Filter bar state (user-controllable)
  // ============================================================================

  /** Input values (bound to form fields, not yet applied) */
  let inputMin = $state('0.5');
  let inputMax = $state('1.0');
  let inputLimit = $state('20');

  /** Applied values (used for the sample API query) */
  let appliedMin = $state(0.5);
  let appliedMax = $state(1.0);
  let appliedLimit = $state(20);

  /** Resample counter — incrementing forces a re-fetch with the same range */
  let resampleCounter = $state(0);

  function handleApply() {
    const minVal = parseFloat(inputMin);
    const maxVal = parseFloat(inputMax);
    const limitVal = parseInt(inputLimit, 10);

    if (!isNaN(minVal) && !isNaN(maxVal) && minVal >= 0 && maxVal <= 1 && minVal < maxVal) {
      appliedMin = minVal;
      appliedMax = maxVal;
    }
    if (!isNaN(limitVal) && limitVal > 0 && limitVal <= 500) {
      appliedLimit = limitVal;
    }
  }

  // ============================================================================
  // Matches for the currently selected species (or all species)
  // ============================================================================

  const selectedMatches = $derived<SimilarityResult[]>(
    results === null || selectedSpeciesKey === null
      ? []
      : (results[selectedSpeciesKey]?.matches ?? [])
  );

  /** All matches across all species — used for the heatmap and flat list. */
  const allMatches = $derived<SimilarityResult[]>(
    results !== null
      ? Object.values(results).flatMap((group) => group.matches)
      : []
  );

  // ============================================================================
  // Distribution query (TanStack Query) — always full range
  // ============================================================================

  const distributionQuery = $derived(
    createQuery({
      queryKey: ['session-distribution', projectId, sessionId, selectedSpeciesKey],
      queryFn: () => getSessionDistribution(projectId, sessionId!, selectedSpeciesKey ?? undefined),
      enabled: !!sessionId && !!selectedSpeciesKey,
    })
  );

  const distributionBins = $derived<DistributionBin[]>(
    $distributionQuery.data?.bins ?? []
  );

  // ============================================================================
  // Time distribution query (TanStack Query) — for heatmap
  // ============================================================================

  const timeDistributionQuery = $derived(
    createQuery({
      queryKey: ['session-time-distribution', projectId, sessionId, selectedSpeciesKey],
      queryFn: () => getSessionTimeDistribution(projectId, sessionId!, selectedSpeciesKey ?? undefined),
      enabled: !!sessionId && !!selectedSpeciesKey,
    })
  );

  const timeDistributionCells = $derived<TimeDistributionCell[]>(
    $timeDistributionQuery.data?.cells ?? []
  );

  const timeDistributionTimezone = $derived<string>(
    $timeDistributionQuery.data?.timezone ?? 'UTC'
  );

  /**
   * Fallback: generate bins client-side from the current species' matches
   * when the server-side distribution API data is unavailable.
   */
  const fallbackBins = $derived<DistributionBin[]>((() => {
    const source = selectedMatches;
    if (source.length === 0) return [];
    const NUM_BINS = 20;
    const counts = new Array<number>(NUM_BINS).fill(0);
    for (const r of source) {
      const idx = Math.min(Math.floor(r.similarity * NUM_BINS), NUM_BINS - 1);
      const safeIdx = idx >= 0 && idx < NUM_BINS ? idx : 0;
      counts[safeIdx] = (counts[safeIdx] ?? 0) + 1;
    }
    return counts.map((count, i) => ({
      lower: i / NUM_BINS,
      upper: (i + 1) / NUM_BINS,
      count,
    }));
  })());

  const binsToDisplay = $derived<DistributionBin[]>(
    distributionBins.length > 0 ? distributionBins : fallbackBins
  );

  // ============================================================================
  // Sample query (TanStack Query) — triggered only on applied values
  // ============================================================================

  const sampleQuery = $derived(
    createQuery({
      queryKey: ['session-sample', projectId, sessionId, appliedMin, appliedMax, appliedLimit, resampleCounter, selectedSpeciesKey],
      queryFn: () => getSessionSample(projectId, sessionId!, appliedMin, appliedMax, appliedLimit, selectedSpeciesKey ?? undefined),
      enabled: !!sessionId && !!selectedSpeciesKey,
    })
  );

  /**
   * Sample results from the API, already filtered by species_key server-side.
   */
  const sampleResults = $derived<SimilarityResult[]>(
    $sampleQuery.data?.results ?? []
  );

  const totalInRange = $derived($sampleQuery.data?.total_in_range ?? 0);

  // ============================================================================
  // Card grid navigation
  // ============================================================================

  let cardElements: (HTMLElement | null)[] = $state([]);

  const nav = createReviewNavigation({
    projectId,
    itemCount: () => sampleResults.length,
    onConfirm: () => { /* no-op: no review actions in search */ },
    onReject: () => { /* no-op: no review actions in search */ },
    getPlaybackInfo: (i) => {
      const match = sampleResults[i];
      if (!match) return null;
      return {
        recordingId: match.recording_id,
        startTime: match.start_time,
        endTime: match.end_time,
      };
    },
    getElement: (i) => cardElements[i] ?? null,
  });

  onDestroy(() => {
    nav.cleanup();
  });
</script>

<svelte:window onkeydown={nav.handleKeydown} />

<div class="flex flex-col gap-4">
  <!-- Keyboard shortcuts hint (only show after search completes) -->
  {#if results !== null && !isSearching}
    <div class="flex flex-wrap items-center justify-end gap-4 rounded-lg border border-stone-200 bg-stone-50 p-3">
      <div class="flex items-center gap-2 text-xs text-stone-400">
        <kbd class="rounded border border-stone-200 bg-surface-card px-1.5 py-0.5 font-mono text-xs">Space</kbd> {m.search_keyboard_play()}
        <kbd class="rounded border border-stone-200 bg-surface-card px-1.5 py-0.5 font-mono text-xs">&#8593;&#8595;</kbd> {m.search_keyboard_navigate()}
      </div>
    </div>
  {/if}

  {#if isSearching}
    <!-- Skeleton loading while search runs -->
    <div class="rounded-lg border border-card bg-surface-card shadow-sm">
      <div class="border-b border-card px-4 py-3">
        <div class="flex gap-2">
          {#each searchingSpecies as sp (sp.id)}
            <div class="h-8 w-24 animate-pulse rounded-md bg-stone-200"></div>
          {/each}
        </div>
      </div>
      <div class="grid grid-cols-1 gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3">
        {#each { length: 8 } as _}
          <div class="animate-pulse overflow-hidden rounded-lg border border-stone-200 bg-surface-card shadow-sm">
            <div class="h-[120px] bg-stone-200"></div>
            <div class="flex flex-col gap-2 p-2.5">
              <div class="h-3 w-4/5 rounded bg-stone-100"></div>
              <div class="h-3 w-1/2 rounded bg-stone-100"></div>
            </div>
          </div>
        {/each}
      </div>
    </div>
  {:else if results !== null}
    {#if speciesEntries.length === 0 || allMatches.length === 0}
      <!-- No results at all -->
      <div class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-stone-200 py-16 text-center">
        <svg
          class="mx-auto mb-3 h-12 w-12 opacity-40 text-stone-400"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          stroke-width="1.5"
          aria-hidden="true"
        >
          <path stroke-linecap="round" stroke-linejoin="round" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
        </svg>
        <p class="font-medium text-stone-500">{m.search_results_no_matches()}</p>
        <p class="mt-1 text-sm text-stone-400">{m.search_results_no_matches_hint()}</p>
      </div>
    {:else}

      <!-- ================================================================ -->
      <!-- Species tabs (always shown)                                      -->
      <!-- ================================================================ -->
      {#if speciesEntries.length > 0}
        <div class="rounded-lg border border-card bg-surface-card shadow-sm">
          <div class="flex overflow-x-auto border-b border-card">
            {#each speciesEntries as [key, sp] (key)}
              <button
                type="button"
                class="flex shrink-0 items-center gap-1.5 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors {selectedSpeciesKey === key
                  ? 'border-primary-500 text-primary-700'
                  : 'border-transparent text-stone-500 hover:text-stone-700'}"
                onclick={() => { selectedSpeciesKey = key; }}
              >
                <span class="max-w-[240px] truncate">
                  {#if sp.common_name && sp.common_name !== sp.scientific_name}
                    {sp.common_name}
                    <span class="ml-1 italic text-stone-400">({sp.scientific_name})</span>
                  {:else}
                    <span class="italic">{sp.scientific_name}</span>
                  {/if}
                </span>
              </button>
            {/each}
          </div>
        </div>
      {/if}

      <!-- ================================================================ -->
      <!-- Filter bar                                                        -->
      <!-- ================================================================ -->
      <div class="flex flex-wrap items-end gap-4 rounded-lg border border-stone-200 bg-stone-50 px-4 py-3">
        <!-- Similarity range -->
        <div class="flex items-end gap-2">
          <label class="flex flex-col gap-1">
            <span class="text-xs font-medium text-stone-500">{m.search_filter_similarity_range()}</span>
            <div class="flex items-center gap-1.5">
              <input
                type="number"
                min="0"
                max="1"
                step="0.05"
                bind:value={inputMin}
                class="w-16 rounded border border-stone-300 bg-surface-card px-2 py-1 text-sm text-stone-800 focus:border-primary-400 focus:outline-none"
              />
              <span class="text-stone-400">–</span>
              <input
                type="number"
                min="0"
                max="1"
                step="0.05"
                bind:value={inputMax}
                class="w-16 rounded border border-stone-300 bg-surface-card px-2 py-1 text-sm text-stone-800 focus:border-primary-400 focus:outline-none"
              />
            </div>
          </label>
        </div>

        <!-- Results per species -->
        <label class="flex flex-col gap-1">
          <span class="text-xs font-medium text-stone-500">{m.search_filter_results_per_species()}</span>
          <input
            type="number"
            min="1"
            max="500"
            step="1"
            bind:value={inputLimit}
            class="w-20 rounded border border-stone-300 bg-surface-card px-2 py-1 text-sm text-stone-800 focus:border-primary-400 focus:outline-none"
          />
        </label>

        <!-- Apply button -->
        <button
          type="button"
          class="rounded-md bg-primary-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-primary-700 active:bg-primary-800 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400 dark:active:bg-primary-400"
          onclick={handleApply}
        >
          {m.search_filter_apply()}
        </button>

        <!-- Train Model button — only shown when a session exists and a species is selected -->
        {#if sessionId && onTrainModelRequest}
          <button
            type="button"
            class="ml-auto rounded-md bg-primary-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-primary-700 active:bg-primary-800 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!selectedSpeciesKey || !results?.[selectedSpeciesKey]}
            onclick={() => {
              if (selectedSpeciesKey && results?.[selectedSpeciesKey]) {
                onTrainModelRequest?.(selectedSpeciesKey, results[selectedSpeciesKey] as SpeciesMatchResult);
              }
            }}
          >
            {m.search_results_train_model_button()}
          </button>
        {/if}
      </div>

      <!-- ================================================================ -->
      <!-- Visualizations: Histogram + Spiral side by side                  -->
      <!-- ================================================================ -->
      <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <!-- Histogram (left) — always shows full distribution -->
        <div class="rounded-lg border border-card bg-surface-card p-4 shadow-sm">
          <h4 class="mb-3 text-xs font-semibold uppercase tracking-wide text-stone-500">
            {m.search_score_distribution()}
          </h4>
          {#if $distributionQuery.isLoading && sessionId}
            <div class="flex h-[140px] items-center justify-center">
              <svg class="h-5 w-5 animate-spin text-stone-300" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
              </svg>
            </div>
          {:else}
            <SimilarityHistogram
              bins={binsToDisplay}
              thresholdMin={appliedMin}
              thresholdMax={appliedMax}
              onThresholdMinChange={(v) => {
                inputMin = v.toFixed(2);
                appliedMin = v;
              }}
              onThresholdMaxChange={(v) => {
                inputMax = v.toFixed(2);
                appliedMax = v;
              }}
            />
          {/if}
        </div>

        <!-- Activity Heatmap (right) — uses time-distribution API for all embeddings -->
        <div class="rounded-lg border border-card bg-surface-card p-4 shadow-sm">
          <h4 class="mb-3 text-xs font-semibold uppercase tracking-wide text-stone-500">
            {m.search_time_distribution()}
          </h4>
          {#if $timeDistributionQuery.isLoading && sessionId}
            <div class="flex h-[260px] items-center justify-center">
              <svg class="h-5 w-5 animate-spin text-stone-300" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
              </svg>
            </div>
          {:else}
            <SearchTimeHeatmap
              cells={timeDistributionCells}
              timezone={timeDistributionTimezone}
            />
          {/if}
        </div>
      </div>

      <!-- ================================================================ -->
      <!-- Sample card grid (results from sample API within applied range)  -->
      <!-- ================================================================ -->
      <div class="rounded-lg border border-card bg-surface-card shadow-sm">
        <div class="flex items-center justify-between border-b border-card px-4 py-3">
          <h4 class="text-xs font-semibold uppercase tracking-wide text-stone-500">
            {m.search_range_preview()}
            <span class="ml-1 font-normal normal-case text-stone-400">
              ({Math.round(appliedMin * 100)}% – {Math.round(appliedMax * 100)}%)
            </span>
          </h4>

          {#if $sampleQuery.data}
            <div class="flex items-center gap-3">
              <span class="text-xs text-stone-400">
                {m.search_sample_count({ shown: sampleResults.length.toString(), total: totalInRange.toLocaleString() })}
              </span>
              <button
                type="button"
                class="flex items-center gap-1.5 rounded-md border border-stone-200 bg-surface-card px-3 py-1 text-xs font-medium text-stone-600 transition-colors hover:border-primary-300 hover:text-primary-700 disabled:opacity-50"
                disabled={$sampleQuery.isFetching}
                onclick={() => { resampleCounter++; }}
              >
                {#if $sampleQuery.isFetching}
                  <svg class="h-3.5 w-3.5 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                  </svg>
                {:else}
                  <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" aria-hidden="true">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                  </svg>
                {/if}
                {m.search_resample()}
              </button>
            </div>
          {/if}
        </div>

        <div class="p-4">
          {#if !sessionId}
            <div class="flex flex-col items-center justify-center py-10 text-center">
              <p class="text-sm text-stone-400">{m.search_no_results_in_range()}</p>
              <p class="mt-1 text-xs text-stone-300">{m.search_no_results_in_range_hint()}</p>
            </div>
          {:else if $sampleQuery.isLoading}
            <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {#each { length: 6 } as _}
                <div class="animate-pulse overflow-hidden rounded-lg border border-stone-200 bg-surface-card shadow-sm">
                  <div class="h-[120px] bg-stone-200"></div>
                  <div class="flex flex-col gap-2 p-2.5">
                    <div class="h-3 w-4/5 rounded bg-stone-100"></div>
                    <div class="h-3 w-1/2 rounded bg-stone-100"></div>
                  </div>
                </div>
              {/each}
            </div>
          {:else if $sampleQuery.isError || sampleResults.length === 0}
            <div class="flex flex-col items-center justify-center py-10 text-center">
              <svg class="mb-2 h-10 w-10 text-stone-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2a1 1 0 01-.293.707L13 13.414V19a1 1 0 01-.553.894l-4 2A1 1 0 017 21v-7.586L3.293 6.707A1 1 0 013 6V4z" />
              </svg>
              <p class="text-sm text-stone-500">{m.search_no_results_in_range()}</p>
              <p class="mt-1 text-xs text-stone-400">{m.search_no_results_in_range_hint()}</p>
            </div>
          {:else}
            <!-- Sample card grid (3 columns) -->
            <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {#each sampleResults as result, i (result.embedding_id)}
                <div
                  bind:this={cardElements[i]}
                  class="transition-transform duration-300 ease-in-out"
                >
                  <SearchPreviewCard
                    {projectId}
                    recordingId={result.recording_id}
                    recordingName={result.recording_filename ?? result.recording_id.slice(0, 8) + '...'}
                    startTime={result.start_time}
                    endTime={result.end_time}
                    similarity={result.similarity}
                    isSelected={i === nav.selectedIndex}
                    isPlaying={nav.playingIndex === i && nav.isPlaying}
                    isLoadingAudio={nav.playingIndex === i && nav.isLoadingAudio}
                    onPlayToggle={() => nav.togglePlay(i)}
                  />
                </div>
              {/each}
            </div>
          {/if}
        </div>
      </div>

    {/if}
  {/if}
</div>
