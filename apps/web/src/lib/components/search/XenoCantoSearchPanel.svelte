<script lang="ts">
  /**
   * XenoCantoSearchPanel - Search panel for finding Xeno-canto recordings.
   *
   * Shown in AddSourcePanel when the user selects the "From URL" tab.
   * Allows searching Xeno-canto by species name with optional filters,
   * and adding recordings directly as SoundSource references.
   *
   * Features:
   * - Play/pause toggle with visual row highlight for currently playing recording
   * - Audio cleanup on component destroy (bulletproof via both onDestroy and $effect)
   * - Checkbox multi-select with cross-pagination persistence
   * - Floating action bar showing selected count with "Add Selected" / "Clear" actions
   */

  import { onDestroy } from 'svelte';
  import * as m from '$lib/paraglide/messages.js';
  import { searchXenoCanto } from '$lib/api/search';
  import { generateId } from '$lib/utils/id';
  import type { SoundSource, XenoCantoRecording, XenoCantoSearchResponse } from '$lib/types/search';

  interface Props {
    /** Scientific name pre-filled from the parent SpeciesCard */
    scientificName: string;
    /** Project ID for the API call */
    projectId: string;
    /** Called when user adds one or more recordings as sources */
    onAdd: (sources: SoundSource[]) => void;
  }

  let { scientificName, projectId, onAdd }: Props = $props();

  // Search form state
  let query = $state(scientificName);
  let country = $state('');
  let area = $state('');
  let qualityMin = $state('');
  let recordingType = $state('');
  let currentPage = $state(1);

  // Results state
  let results = $state<XenoCantoSearchResponse | null>(null);
  let isLoading = $state(false);
  let error = $state<string | null>(null);

  // Audio playback state
  let playingXcId = $state<string | null>(null);
  let audioElement: HTMLAudioElement | null = null;
  let audioError = $state<string | null>(null);

  // Multi-select state: persists across pages (keyed by xc_id)
  let selectedIds = $state<Set<string>>(new Set());

  const AREA_OPTIONS = ['', 'africa', 'america', 'asia', 'australia', 'europe'];
  const QUALITY_OPTIONS = ['', 'A', 'B', 'C', 'D', 'E'];
  const TYPE_OPTIONS = ['', 'song', 'call', 'alarm call', 'flight call', 'nocturnal flight call', 'subsong'];

  // Derived: how many selected items are not on the current page
  let selectedCount = $derived(selectedIds.size);
  let currentPageIds = $derived<Set<string>>(
    new Set(results?.recordings.map((r) => r.xc_id) ?? [])
  );
  let offPageSelectedCount = $derived(
    [...selectedIds].filter((id) => !currentPageIds.has(id)).length
  );

  // --- Audio cleanup helpers ---

  function stopAudio() {
    if (audioElement) {
      audioElement.pause();
      audioElement.src = '';
      audioElement.onended = null;
      audioElement.onerror = null;
      audioElement = null;
    }
    playingXcId = null;
  }

  // Cleanup on component destroy — catches Cancel button click which unmounts this component
  onDestroy(() => {
    stopAudio();
  });

  // Additional $effect cleanup as a belt-and-suspenders guarantee
  $effect(() => {
    return () => {
      stopAudio();
    };
  });

  // --- Audio playback ---

  function toggleAudioPlayback(recording: XenoCantoRecording) {
    if (playingXcId === recording.xc_id) {
      // Toggle off: stop current playback
      stopAudio();
      audioError = null;
      return;
    }

    // Stop any existing playback first
    stopAudio();

    audioError = null;
    const audio = new Audio(recording.file_url);

    audio.onended = () => {
      playingXcId = null;
    };

    audio.onerror = () => {
      audioError = recording.xc_id;
      playingXcId = null;
    };

    audioElement = audio;
    playingXcId = recording.xc_id;

    audio.play().catch(() => {
      audioError = recording.xc_id;
      playingXcId = null;
      audioElement = null;
    });
  }

  // --- Search ---

  async function doSearch(page: number = 1) {
    if (!query.trim()) return;
    isLoading = true;
    error = null;
    currentPage = page;

    try {
      results = await searchXenoCanto(projectId, {
        query: query.trim(),
        country: country || undefined,
        area: area || undefined,
        quality_min: qualityMin || undefined,
        recording_type: recordingType || undefined,
        page,
        per_page: 20,
      });
    } catch (err) {
      error = err instanceof Error ? err.message : 'Search failed.';
      results = null;
    } finally {
      isLoading = false;
    }
  }

  function handleSearch() {
    void doSearch(1);
  }

  function handlePrev() {
    if (currentPage > 1) void doSearch(currentPage - 1);
  }

  function handleNext() {
    if (results && currentPage < results.total_pages) void doSearch(currentPage + 1);
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') handleSearch();
  }

  // --- Multi-select ---

  function toggleSelect(xcId: string) {
    const next = new Set(selectedIds);
    if (next.has(xcId)) {
      next.delete(xcId);
    } else {
      next.add(xcId);
    }
    selectedIds = next;
  }

  function clearSelection() {
    selectedIds = new Set();
  }

  function handleAddSelected() {
    if (!results) return;

    // Gather all selected recordings that are currently visible.
    // We can only add recordings we have data for (current page).
    // Selected IDs from other pages will be retained in the set but cannot be dispatched
    // without their metadata — iterate over all recordings we have seen.
    // Since we only store IDs across pages (not full recording objects), we add
    // what's currently visible and leave off-page IDs selected until user navigates.
    const toAdd = results.recordings.filter((r) => selectedIds.has(r.xc_id));

    // Build all sources first, then dispatch them in a single call so the parent
    // can append all of them at once (avoids the bug where each call would
    // close the panel or overwrite state before the next one runs).
    const sources: SoundSource[] = toAdd.map((recording) => ({
      id: generateId(),
      origin: 'url',
      label: `XC${recording.xc_id}`,
      source_url: recording.file_url,
      xc_id: recording.xc_id,
      quality: recording.quality as 'A' | 'B' | 'C' | 'D' | 'E',
      recording_type: recording.recording_type,
      recordist: recording.recordist,
      location: recording.location,
    }));

    if (sources.length > 0) {
      onAdd(sources);
    }

    // Remove only the ones we just added from the selection set
    const addedXcIds = new Set(toAdd.map((r) => r.xc_id));
    const next = new Set([...selectedIds].filter((id) => !addedXcIds.has(id)));
    selectedIds = next;
  }
</script>

<div class="space-y-3">
  <!-- Search form -->
  <div class="space-y-2">
    <!-- Main query row -->
    <div class="flex gap-2">
      <input
        type="text"
        bind:value={query}
        onkeydown={handleKeydown}
        class="min-w-0 flex-1 rounded-md border border-stone-300 bg-white px-3 py-1.5 text-sm
               placeholder-stone-400 focus:border-primary-500 focus:outline-none focus:ring-1
               focus:ring-primary-500 dark:border-stone-600 dark:bg-stone-800 dark:text-stone-100"
        placeholder={scientificName}
      />
      <button
        type="button"
        onclick={handleSearch}
        disabled={isLoading || !query.trim()}
        class="shrink-0 rounded-md bg-primary-600 px-3 py-1.5 text-sm font-medium text-white
               hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isLoading ? m.search_xc_loading() : m.search_xc_search()}
      </button>
    </div>

    <!-- Filter row -->
    <div class="flex flex-wrap gap-2">
      <!-- Country -->
      <input
        type="text"
        bind:value={country}
        onkeydown={handleKeydown}
        class="w-28 rounded-md border border-stone-300 bg-white px-2 py-1 text-xs
               placeholder-stone-400 focus:border-primary-500 focus:outline-none focus:ring-1
               focus:ring-primary-500 dark:border-stone-600 dark:bg-stone-800 dark:text-stone-100"
        placeholder={m.search_xc_country()}
      />

      <!-- Area -->
      <select
        bind:value={area}
        class="rounded-md border border-stone-300 bg-white px-2 py-1 text-xs text-stone-700
               focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500
               dark:border-stone-600 dark:bg-stone-800 dark:text-stone-300"
      >
        {#each AREA_OPTIONS as opt}
          <option value={opt}>{opt || m.search_xc_area()}</option>
        {/each}
      </select>

      <!-- Min quality -->
      <select
        bind:value={qualityMin}
        class="rounded-md border border-stone-300 bg-white px-2 py-1 text-xs text-stone-700
               focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500
               dark:border-stone-600 dark:bg-stone-800 dark:text-stone-300"
      >
        {#each QUALITY_OPTIONS as opt}
          <option value={opt}>{opt || m.search_xc_quality_min()}</option>
        {/each}
      </select>

      <!-- Recording type -->
      <select
        bind:value={recordingType}
        class="rounded-md border border-stone-300 bg-white px-2 py-1 text-xs text-stone-700
               focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500
               dark:border-stone-600 dark:bg-stone-800 dark:text-stone-300"
      >
        {#each TYPE_OPTIONS as opt}
          <option value={opt}>{opt || m.search_xc_recording_type()}</option>
        {/each}
      </select>
    </div>
  </div>

  <!-- Error message -->
  {#if error}
    <p class="rounded bg-red-50 px-3 py-2 text-sm text-red-600 dark:bg-red-900/20 dark:text-red-400">
      {error}
    </p>
  {/if}

  <!-- Loading skeleton -->
  {#if isLoading}
    <div class="space-y-2">
      {#each [1, 2, 3] as _}
        <div class="h-14 animate-pulse rounded-lg bg-stone-100 dark:bg-stone-800"></div>
      {/each}
    </div>

  <!-- Results -->
  {:else if results}
    <!-- Result count + pagination info -->
    <div class="flex items-center justify-between text-xs text-stone-500 dark:text-stone-400">
      <span>
        {m.search_xc_total_results({ count: results.total_recordings.toString() })}
      </span>
      {#if results.total_pages > 1}
        <span>
          {m.search_xc_page_info({ page: results.page.toString(), total: results.total_pages.toString() })}
        </span>
      {/if}
    </div>

    {#if results.recordings.length === 0}
      <!-- Empty state -->
      <div class="py-6 text-center text-sm text-stone-400 dark:text-stone-500">
        {m.search_xc_no_results()}
      </div>
    {:else}
      <!-- Recording rows -->
      <div class="space-y-1.5">
        {#each results.recordings as recording (recording.xc_id)}
          {@const isPlaying = playingXcId === recording.xc_id}
          {@const hasError = audioError === recording.xc_id}
          {@const isSelected = selectedIds.has(recording.xc_id)}

          <div
            class="flex items-center gap-2 rounded-lg border px-2.5 py-2 transition-colors
                   {isPlaying
                     ? 'border-primary-200 bg-primary-50/60 dark:border-primary-800 dark:bg-primary-900/20'
                     : isSelected
                       ? 'border-stone-200 bg-stone-100/80 dark:border-stone-600 dark:bg-stone-700/40'
                       : 'border-stone-100 bg-stone-50 dark:border-stone-700 dark:bg-stone-800/50'}"
          >
            <!-- Checkbox -->
            <label class="shrink-0 cursor-pointer">
              <input
                type="checkbox"
                checked={isSelected}
                onchange={() => toggleSelect(recording.xc_id)}
                class="h-4 w-4 cursor-pointer rounded border-stone-300 text-primary-600
                       accent-primary-600 focus:ring-primary-500 dark:border-stone-600"
                aria-label="Select XC{recording.xc_id}"
              />
            </label>

            <!-- Sonogram thumbnail -->
            {#if recording.sonogram_url}
              <img
                src={recording.sonogram_url}
                alt="Sonogram for XC{recording.xc_id}"
                class="h-10 w-16 shrink-0 rounded object-cover"
                loading="lazy"
              />
            {:else}
              <!-- Placeholder when no sonogram -->
              <div class="h-10 w-16 shrink-0 rounded bg-stone-200 dark:bg-stone-700"></div>
            {/if}

            <!-- Main info -->
            <div class="min-w-0 flex-1 space-y-0.5">
              <div class="flex flex-wrap items-center gap-1.5">
                <!-- XC ID -->
                <a
                  href="https://xeno-canto.org/{recording.xc_id}"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="font-mono text-xs font-semibold text-primary-600 hover:underline dark:text-primary-400"
                  title={m.search_xc_listen()}
                >
                  XC{recording.xc_id}
                </a>

                <!-- Recording type badge -->
                {#if recording.recording_type}
                  <span class="rounded bg-stone-200 px-1.5 py-0.5 text-xs text-stone-600
                               dark:bg-stone-700 dark:text-stone-300">
                    {recording.recording_type}
                  </span>
                {/if}

                <!-- Quality badge -->
                {#if recording.quality}
                  <span class="rounded px-1.5 py-0.5 text-xs font-medium
                               {recording.quality === 'A'
                                 ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                                 : recording.quality === 'B'
                                   ? 'bg-lime-100 text-lime-700 dark:bg-lime-900/30 dark:text-lime-400'
                                   : recording.quality === 'C'
                                     ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400'
                                     : 'bg-stone-100 text-stone-600 dark:bg-stone-700 dark:text-stone-300'}">
                    {recording.quality}
                  </span>
                {/if}

                <!-- Duration -->
                {#if recording.length}
                  <span class="text-xs text-stone-400">{recording.length}</span>
                {/if}
              </div>

              <!-- Recordist + location -->
              <p class="truncate text-xs text-stone-500 dark:text-stone-400">
                {recording.recordist}
                {#if recording.location || recording.country}
                  &middot;
                  {[recording.location, recording.country].filter(Boolean).join(', ')}
                {/if}
              </p>
            </div>

            <!-- Play / Pause button -->
            <button
              type="button"
              onclick={() => toggleAudioPlayback(recording)}
              class="shrink-0 rounded-md border px-1.5 py-1 text-xs transition-colors
                     {hasError
                       ? 'border-red-300 text-red-500 dark:border-red-700 dark:text-red-400'
                       : isPlaying
                         ? 'border-primary-300 bg-primary-50 text-primary-700 dark:border-primary-700 dark:bg-primary-900/30 dark:text-primary-400'
                         : 'border-stone-300 text-stone-500 hover:border-primary-400 hover:text-primary-600 dark:border-stone-600 dark:text-stone-400 dark:hover:border-primary-500 dark:hover:text-primary-400'}"
              aria-label={isPlaying ? 'Pause' : 'Play'}
              title={hasError ? 'Playback failed' : isPlaying ? 'Pause' : 'Play preview'}
            >
              {#if hasError}
                <!-- Error icon -->
                <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                  <circle cx="12" cy="12" r="10" />
                  <path d="M12 8v4m0 4h.01" stroke-linecap="round" />
                </svg>
              {:else if isPlaying}
                <!-- Pause icon -->
                <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                  <rect x="6" y="4" width="4" height="16" rx="1" />
                  <rect x="14" y="4" width="4" height="16" rx="1" />
                </svg>
              {:else}
                <!-- Play icon -->
                <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                  <path d="M8 5.14v13.72a1 1 0 0 0 1.5.86l11-6.86a1 1 0 0 0 0-1.72l-11-6.86A1 1 0 0 0 8 5.14z" />
                </svg>
              {/if}
            </button>
          </div>
        {/each}
      </div>

      <!-- Pagination controls -->
      {#if results.total_pages > 1}
        <div class="flex items-center justify-center gap-3 pt-1">
          <button
            type="button"
            onclick={handlePrev}
            disabled={currentPage <= 1}
            class="rounded-md border border-stone-300 px-3 py-1 text-xs text-stone-700
                   hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-40
                   dark:border-stone-600 dark:text-stone-300 dark:hover:bg-stone-700/50"
          >
            {m.search_xc_prev()}
          </button>
          <span class="text-xs text-stone-500">
            {m.search_xc_page_info({ page: results.page.toString(), total: results.total_pages.toString() })}
          </span>
          <button
            type="button"
            onclick={handleNext}
            disabled={currentPage >= results.total_pages}
            class="rounded-md border border-stone-300 px-3 py-1 text-xs text-stone-700
                   hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-40
                   dark:border-stone-600 dark:text-stone-300 dark:hover:bg-stone-700/50"
          >
            {m.search_xc_next()}
          </button>
        </div>
      {/if}
    {/if}
  {/if}

  <!-- Floating action bar: shown when at least one recording is selected -->
  {#if selectedCount > 0}
    <div class="sticky bottom-0 flex items-center justify-between gap-3 rounded-lg border
                border-primary-200 bg-primary-50 px-3 py-2 shadow-md
                dark:border-primary-800 dark:bg-primary-950/60">
      <div class="flex items-center gap-2 text-sm font-medium text-primary-800 dark:text-primary-200">
        <span>{m.search_xc_selected({ count: selectedCount.toString() })}</span>
        {#if offPageSelectedCount > 0}
          <span class="rounded-full bg-primary-200 px-1.5 py-0.5 text-xs text-primary-700
                       dark:bg-primary-800 dark:text-primary-300">
            +{offPageSelectedCount} other pages
          </span>
        {/if}
      </div>
      <div class="flex items-center gap-2">
        <button
          type="button"
          onclick={clearSelection}
          class="rounded-md px-2.5 py-1 text-xs text-primary-700 hover:bg-primary-100
                 dark:text-primary-300 dark:hover:bg-primary-900/40"
        >
          {m.search_xc_clear_selection()}
        </button>
        <button
          type="button"
          onclick={handleAddSelected}
          class="rounded-md bg-primary-600 px-3 py-1 text-xs font-medium text-white
                 hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {m.search_xc_add_selected()}
        </button>
      </div>
    </div>
  {/if}
</div>
