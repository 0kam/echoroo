<script lang="ts">
  /**
   * ResultsPanel - Displays batch similarity search results in exploration-only mode.
   *
   * Features:
   * - Species tabs at the top (one per species)
   * - Client-side threshold and max-per-species filter bar
   * - Spectrogram preview card grid for the selected species
   * - Audio playback (Space to play, Arrow keys to navigate)
   *
   * No voting or review actions — this panel is for exploration only.
   */

  import { onDestroy } from 'svelte';
  import * as m from '$lib/paraglide/messages.js';
  import type { SimilarityResult, SpeciesMatchResult, TargetSpecies } from '$lib/types/search';
  import { createReviewNavigation } from '$lib/utils/reviewNavigation.svelte';
  import SearchPreviewCard from './SearchPreviewCard.svelte';
  import SimilarityHistogram from './SimilarityHistogram.svelte';
  import SimilaritySpiral from './SimilaritySpiral.svelte';
  import ThresholdPreview from './ThresholdPreview.svelte';

  interface Props {
    projectId: string;
    results: Record<string, SpeciesMatchResult> | null;
    totalMatches: number;
    searchDurationMs: number;
    isSearching: boolean;
    searchingSpecies: TargetSpecies[];
  }

  let {
    projectId,
    results,
    totalMatches,
    searchDurationMs,
    isSearching,
    searchingSpecies,
  }: Props = $props();

  // Client-side filter state
  let filterThreshold = $state(0.1);
  let filterMaxPerSpecies = $state(20);

  // ThresholdPreview independent range (not tied to the main filter threshold)
  let previewMin = $state(0.3);
  let previewMax = $state(0.7);

  // Flat array of all results across all species (for histogram + spiral + preview)
  const allMatches = $derived<SimilarityResult[]>(
    results !== null
      ? Object.values(results).flatMap((group) => group.matches)
      : []
  );

  // Currently selected species tab key
  let selectedTabKey = $state<string | null>(null);

  // DOM references for scroll-into-view
  let cardElements: (HTMLElement | null)[] = $state([]);

  // Shared keyboard navigation and audio playback (arrows + space only)
  const nav = createReviewNavigation({
    projectId,
    itemCount: () => filteredMatches.length,
    onConfirm: () => { /* no-op: no review actions in search */ },
    onReject: () => { /* no-op: no review actions in search */ },
    getPlaybackInfo: (i) => {
      const match = filteredMatches[i];
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

  // Species entry list derived from results
  const speciesEntries = $derived(
    results !== null ? Object.entries(results) : []
  );

  // Reset tab selection when results change
  $effect(() => {
    if (results !== null) {
      const keys = Object.keys(results);
      selectedTabKey = keys.length > 0 ? (keys[0] ?? null) : null;
      nav.select(0);
    }
  });

  // Filtered matches for the currently selected species
  const selectedGroup = $derived(
    selectedTabKey !== null && results !== null ? results[selectedTabKey] : null
  );

  const filteredMatches = $derived(
    selectedGroup !== null && selectedGroup !== undefined
      ? selectedGroup.matches
          .filter((r) => r.similarity >= filterThreshold)
          .slice(0, filterMaxPerSpecies)
      : []
  );

  // Filtered count per species tab (for badges)
  function getFilteredCount(group: SpeciesMatchResult): number {
    return group.matches
      .filter((r) => r.similarity >= filterThreshold)
      .slice(0, filterMaxPerSpecies).length;
  }

  function getDisplayName(group: SpeciesMatchResult): string {
    return group.common_name ?? group.scientific_name;
  }

  function getSecondaryName(group: SpeciesMatchResult): string | undefined {
    return group.common_name ? group.scientific_name : undefined;
  }
</script>

<svelte:window onkeydown={nav.handleKeydown} />

<div class="flex flex-col gap-4">
  <!-- Filter bar (only show after search completes) -->
  {#if results !== null && !isSearching}
    <div class="flex flex-wrap items-center gap-4 rounded-lg border border-stone-200 bg-stone-50 p-3">
      <!-- Threshold slider -->
      <div class="flex items-center gap-2">
        <label for="rf-threshold" class="text-xs font-medium whitespace-nowrap text-stone-600">
          {m.search_threshold()} {Math.round(filterThreshold * 100)}%
        </label>
        <input
          id="rf-threshold"
          type="range"
          min="0"
          max="1"
          step="0.05"
          bind:value={filterThreshold}
          class="w-28 accent-primary-500"
          aria-label={m.search_threshold()}
        />
      </div>

      <!-- Max per species -->
      <div class="flex items-center gap-2">
        <label for="rf-max" class="text-xs font-medium whitespace-nowrap text-stone-600">
          {m.search_max_per_species()}
        </label>
        <input
          id="rf-max"
          type="number"
          min="1"
          max="200"
          bind:value={filterMaxPerSpecies}
          class="w-16 rounded-md border border-stone-300 bg-surface-card px-2 py-1 text-xs focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
          aria-label={m.search_max_per_species()}
        />
      </div>

      <!-- Summary -->
      <span class="text-xs text-stone-400">
        {m.search_results_total({ count: totalMatches.toString() })}
        &bull;
        {m.search_search_duration({ ms: searchDurationMs.toString() })}
      </span>

      <!-- Keyboard shortcuts hint -->
      <div class="ml-auto flex items-center gap-2 text-xs text-stone-400">
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
            <!-- Spectrogram area placeholder -->
            <div class="h-[120px] bg-stone-200"></div>
            <!-- Card body placeholder -->
            <div class="flex flex-col gap-2 p-2.5">
              <div class="h-3 w-4/5 rounded bg-stone-100"></div>
              <div class="h-3 w-1/2 rounded bg-stone-100"></div>
            </div>
          </div>
        {/each}
      </div>
    </div>
  {:else if results !== null}
    {#if speciesEntries.length === 0 || totalMatches === 0}
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
      <!-- Top section: SimilarityHistogram + SimilaritySpiral side by side -->
      <!-- ================================================================ -->
      <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <!-- Histogram (left) — threshold synced with filterThreshold -->
        <div class="rounded-lg border border-card bg-surface-card p-4 shadow-sm">
          <h4 class="mb-3 text-xs font-semibold uppercase tracking-wide text-stone-500">
            {m.search_score_distribution()}
          </h4>
          <SimilarityHistogram
            results={allMatches}
            bind:threshold={filterThreshold}
            onThresholdChange={(v) => { filterThreshold = v; }}
          />
        </div>

        <!-- Spiral (right) — time-of-day view -->
        <div class="rounded-lg border border-card bg-surface-card p-4 shadow-sm">
          <h4 class="mb-3 text-xs font-semibold uppercase tracking-wide text-stone-500">
            {m.search_time_distribution()}
          </h4>
          <SimilaritySpiral
            results={allMatches}
            threshold={filterThreshold}
          />
        </div>
      </div>

      <!-- ================================================================ -->
      <!-- Middle section: ThresholdPreview (independent range slider)      -->
      <!-- ================================================================ -->
      <div class="rounded-lg border border-card bg-surface-card p-4 shadow-sm">
        <h4 class="mb-3 text-xs font-semibold uppercase tracking-wide text-stone-500">
          {m.search_range_preview()}
        </h4>
        <ThresholdPreview
          results={allMatches}
          {projectId}
          bind:minSimilarity={previewMin}
          bind:maxSimilarity={previewMax}
        />
      </div>

      <!-- ================================================================ -->
      <!-- Bottom section: Per-species card grid filtered by threshold      -->
      <!-- ================================================================ -->
      <div class="rounded-lg border border-card bg-surface-card shadow-sm">
        <!-- Species tabs -->
        <div class="flex flex-wrap gap-1 border-b border-card p-2">
          {#each speciesEntries as [key, group] (key)}
            {@const filteredCount = getFilteredCount(group)}
            <button
              type="button"
              class="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors
                {selectedTabKey === key
                  ? 'bg-primary-600 dark:bg-primary-300 text-white shadow-sm'
                  : 'border border-stone-200 bg-stone-50 text-stone-700 hover:bg-stone-100 dark:border-stone-700 dark:bg-stone-800 dark:hover:bg-stone-700'}"
              onclick={() => { selectedTabKey = key; nav.select(0); }}
            >
              <span class="max-w-[140px] truncate">{getDisplayName(group)}</span>
              <span
                class="rounded-full px-1.5 py-0.5 text-xs font-semibold
                  {selectedTabKey === key
                    ? 'bg-white/25 text-white'
                    : 'bg-primary-100 text-primary-800'}"
              >
                {filteredCount}
              </span>
            </button>
          {/each}
        </div>

        <!-- Selected species details + grid -->
        {#if selectedGroup !== null && selectedGroup !== undefined}
          <div class="p-4">
            <!-- Species name header -->
            <div class="mb-4">
              <h3 class="text-base font-semibold text-stone-900">{getDisplayName(selectedGroup)}</h3>
              {#if getSecondaryName(selectedGroup)}
                <p class="text-sm italic text-stone-400">{getSecondaryName(selectedGroup)}</p>
              {/if}
            </div>

            {#if filteredMatches.length === 0}
              <!-- No results above threshold -->
              <div class="flex flex-col items-center justify-center py-10 text-center">
                <svg class="mb-2 h-10 w-10 text-stone-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2a1 1 0 01-.293.707L13 13.414V19a1 1 0 01-.553.894l-4 2A1 1 0 017 21v-7.586L3.293 6.707A1 1 0 013 6V4z" />
                </svg>
                <p class="text-sm text-stone-500">{m.search_no_results_above_threshold()}</p>
              </div>
            {:else}
              <!-- Preview card grid -->
              <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {#each filteredMatches as result, i (result.embedding_id)}
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
        {/if}
      </div>
    {/if}
  {/if}
</div>
