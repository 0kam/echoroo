<script lang="ts">
  /**
   * ResultsPanel - Displays batch similarity search results using a detection-review-style layout.
   *
   * Features:
   * - Species tabs at the top (one per species)
   * - Client-side threshold and max-per-species filter bar
   * - Spectrogram card grid for the selected species
   * - Confirm/Reject actions on each card
   * - Keyboard shortcuts: Space=Play, C=Confirm, R=Reject, Arrow Up/Down=Navigate
   */

  import { onDestroy } from 'svelte';
  import * as m from '$lib/paraglide/messages.js';
  import type { SpeciesMatchResult, TargetSpecies, SearchResultStatus, SimilarityResult } from '$lib/types/search';
  import { createAudioPlayer } from '$lib/utils/audioPlayback.svelte';
  import SearchResultCard from './SearchResultCard.svelte';

  interface Props {
    projectId: string;
    results: Record<string, SpeciesMatchResult> | null;
    totalMatches: number;
    searchDurationMs: number;
    isSearching: boolean;
    searchingSpecies: TargetSpecies[];
    searchSessionId?: string;
  }

  let {
    projectId,
    results,
    totalMatches,
    searchDurationMs,
    isSearching,
    searchingSpecies,
    searchSessionId,
  }: Props = $props();

  // Client-side filter state
  let filterThreshold = $state(0.1);
  let filterMaxPerSpecies = $state(20);

  // Currently selected species tab key
  let selectedTabKey = $state<string | null>(null);

  // Keyboard-focused card index within filteredMatches
  let selectedIndex = $state(0);

  // Audio player for keyboard-triggered Space playback
  const player = createAudioPlayer(projectId);

  onDestroy(() => {
    player.cleanup();
  });

  // Client-side review status tracking: key = embedding_id
  let statusMap = $state<Map<string, SearchResultStatus>>(new Map());

  // Species entry list derived from results
  const speciesEntries = $derived(
    results !== null ? Object.entries(results) : []
  );

  // When results change (new search or session load), reset the tab selection
  // and initialize the status map from any server-side review_status values.
  $effect(() => {
    if (results !== null) {
      const keys = Object.keys(results);
      selectedTabKey = keys.length > 0 ? (keys[0] ?? null) : null;
      selectedIndex = 0;
      const newMap = new Map<string, SearchResultStatus>();
      for (const speciesData of Object.values(results)) {
        if (speciesData?.matches) {
          for (const match of speciesData.matches) {
            const reviewStatus = (match as SimilarityResult & { review_status?: string }).review_status;
            if (reviewStatus && reviewStatus !== 'unreviewed') {
              newMap.set(match.embedding_id, reviewStatus as SearchResultStatus);
            }
          }
        }
      }
      statusMap = newMap;
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

  function getStatus(result: SimilarityResult): SearchResultStatus {
    return statusMap.get(result.embedding_id) ?? 'unreviewed';
  }

  function handleConfirm(embeddingId: string) {
    statusMap = new Map(statusMap).set(embeddingId, 'confirmed');
  }

  function handleReject(embeddingId: string) {
    statusMap = new Map(statusMap).set(embeddingId, 'rejected');
  }

  // Keyboard shortcut handler
  function handleKeydown(e: KeyboardEvent) {
    // Skip when focus is inside an input, textarea, or select
    const target = e.target as HTMLElement;
    if (
      target.tagName === 'INPUT' ||
      target.tagName === 'TEXTAREA' ||
      target.tagName === 'SELECT'
    ) {
      return;
    }

    if (filteredMatches.length === 0) return;

    const selected = filteredMatches[selectedIndex];

    switch (e.key) {
      case ' ':
        // Space: toggle audio playback for the focused card
        if (selected) {
          e.preventDefault();
          player.toggle(selected.recording_id, selected.start_time, selected.end_time);
        }
        break;

      case 'c':
      case 'C':
        if (selected && getStatus(selected) !== 'confirmed') {
          e.preventDefault();
          // Trigger the card's confirm handler via the statusMap (mirrors handleConfirm)
          handleConfirmByIndex(selectedIndex);
        }
        break;

      case 'r':
      case 'R':
        if (selected && getStatus(selected) !== 'rejected') {
          e.preventDefault();
          handleRejectByIndex(selectedIndex);
        }
        break;

      case 'ArrowDown':
        e.preventDefault();
        player.stop();
        selectedIndex = Math.min(selectedIndex + 1, filteredMatches.length - 1);
        scrollSelectedIntoView();
        break;

      case 'ArrowUp':
        e.preventDefault();
        player.stop();
        selectedIndex = Math.max(selectedIndex - 1, 0);
        scrollSelectedIntoView();
        break;
    }
  }

  // Wrappers that trigger the card's actual confirm/reject API calls via its onConfirm/onReject props.
  // Since SearchResultCard manages the API calls internally, we simulate a click by dispatching
  // through the same statusMap pathway and relying on the card's own handlers for server sync.
  // For keyboard shortcuts we call the full async handlers by finding the card element and
  // programmatically clicking its confirm/reject buttons.
  function handleConfirmByIndex(index: number) {
    const cardEl = cardElements[index];
    if (!cardEl) return;
    const btn = cardEl.querySelector<HTMLButtonElement>('[data-action="confirm"]');
    btn?.click();
  }

  function handleRejectByIndex(index: number) {
    const cardEl = cardElements[index];
    if (!cardEl) return;
    const btn = cardEl.querySelector<HTMLButtonElement>('[data-action="reject"]');
    btn?.click();
  }

  // DOM references for keyboard-triggered scroll + button click
  let cardElements: (HTMLElement | null)[] = $state([]);

  function scrollSelectedIntoView() {
    // Use a microtask to let Svelte update the DOM first
    queueMicrotask(() => {
      cardElements[selectedIndex]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    });
  }

  function getTagId(tagKey: string, group: SpeciesMatchResult): string {
    // Use tag_id from group if present, otherwise fall back to the key
    return group.tag_id ?? tagKey;
  }

  function getDisplayName(group: SpeciesMatchResult): string {
    return group.common_name ?? group.scientific_name;
  }

  function getSecondaryName(group: SpeciesMatchResult): string | undefined {
    return group.common_name ? group.scientific_name : undefined;
  }
</script>

<svelte:window onkeydown={handleKeydown} />

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
        <kbd class="rounded border border-stone-200 bg-surface-card px-1.5 py-0.5 font-mono text-xs">C</kbd> {m.search_keyboard_confirm()}
        <kbd class="rounded border border-stone-200 bg-surface-card px-1.5 py-0.5 font-mono text-xs">R</kbd> {m.search_keyboard_reject()}
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
      <div class="grid grid-cols-2 gap-3 p-4 sm:grid-cols-3 lg:grid-cols-4">
        {#each { length: 8 } as _}
          <div class="animate-pulse overflow-hidden rounded-lg border border-stone-200 bg-surface-card shadow-sm">
            <div class="h-[120px] bg-stone-200"></div>
            <div class="flex flex-col gap-2 p-2.5">
              <div class="h-3 w-4/5 rounded bg-stone-100"></div>
              <div class="h-3 w-1/2 rounded bg-stone-100"></div>
              <div class="h-6 w-full rounded bg-stone-100"></div>
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
      <div class="rounded-lg border border-card bg-surface-card shadow-sm">
        <!-- Species tabs -->
        <div class="flex flex-wrap gap-1 border-b border-card p-2">
          {#each speciesEntries as [key, group] (key)}
            {@const filteredCount = getFilteredCount(group)}
            <button
              type="button"
              class="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors
                {selectedTabKey === key
                  ? 'bg-primary-600 text-white shadow-sm'
                  : 'border border-stone-200 bg-stone-50 text-stone-700 hover:bg-stone-100'}"
              onclick={() => { selectedTabKey = key; selectedIndex = 0; player.stop(); }}
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
              <!-- Result card grid -->
              <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                {#each filteredMatches as result, i (result.embedding_id)}
                  <div bind:this={cardElements[i]}>
                    <SearchResultCard
                      {projectId}
                      {result}
                      tagId={getTagId(selectedTabKey ?? '', selectedGroup)}
                      status={getStatus(result)}
                      {searchSessionId}
                      isSelected={i === selectedIndex}
                      onConfirm={() => handleConfirm(result.embedding_id)}
                      onReject={() => handleReject(result.embedding_id)}
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
