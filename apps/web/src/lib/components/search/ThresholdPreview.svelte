<script lang="ts">
  /**
   * ThresholdPreview - Spectrogram grid for results within a similarity range.
   *
   * Renders a two-handle range slider allowing the user to define a min/max
   * similarity band, then fetches randomly sampled spectrogram thumbnails
   * from the sampling API for the selected range.
   *
   * - Uses GET /search-sessions/{id}/sample to retrieve random samples
   * - Debounces slider changes to avoid excessive API calls
   * - "Resample" button fetches a different random set
   */

  import { createQuery } from '@tanstack/svelte-query';
  import * as m from '$lib/paraglide/messages.js';
  import type { SimilarityResult } from '$lib/types/search';
  import { getSessionSample } from '$lib/api/search';
  import MiniSpectrogram from '$lib/components/common/MiniSpectrogram.svelte';

  // ============================================================================
  // Props
  // ============================================================================

  let {
    projectId,
    sessionId,
    minSimilarity = $bindable(),
    maxSimilarity = $bindable(),
    limit = 20,
  }: {
    projectId: string;
    /** Session ID for the sampling API. When null/undefined, shows a placeholder. */
    sessionId: string | null | undefined;
    minSimilarity: number;
    maxSimilarity: number;
    /** Maximum number of samples to fetch (default 20) */
    limit?: number;
  } = $props();

  // ============================================================================
  // Debouncing state for API calls
  // ============================================================================

  /** Debounced values used as the actual query key — updated after 400ms idle */
  let debouncedMin = $state(minSimilarity);
  let debouncedMax = $state(maxSimilarity);
  let debounceTimer = $state<ReturnType<typeof setTimeout> | null>(null);

  /** Resample counter — incrementing this forces a re-fetch with the same range */
  let resampleCounter = $state(0);

  $effect(() => {
    // Track changes to min/max and debounce the query
    void minSimilarity;
    void maxSimilarity;
    if (debounceTimer !== null) {
      clearTimeout(debounceTimer);
    }
    debounceTimer = setTimeout(() => {
      debouncedMin = minSimilarity;
      debouncedMax = maxSimilarity;
    }, 400);
  });

  // ============================================================================
  // Sampling query
  // ============================================================================

  const sampleQuery = $derived(
    createQuery({
      queryKey: ['session-sample', projectId, sessionId, debouncedMin, debouncedMax, limit, resampleCounter],
      queryFn: () =>
        getSessionSample(projectId, sessionId!, debouncedMin, debouncedMax, limit),
      enabled: !!sessionId,
    })
  );

  const results = $derived<SimilarityResult[]>(
    $sampleQuery.data?.results ?? []
  );

  const totalInRange = $derived($sampleQuery.data?.total_in_range ?? 0);

  // ============================================================================
  // Audio playback state
  // ============================================================================

  let playingId = $state<string | null>(null);

  function handleCardClick(result: SimilarityResult) {
    if (playingId === result.embedding_id) {
      playingId = null;
    } else {
      playingId = result.embedding_id;
    }
  }

  // ============================================================================
  // Two-handle range slider
  // ============================================================================

  let sliderEl = $state<HTMLDivElement | null>(null);
  let draggingHandle = $state<'min' | 'max' | null>(null);

  const SNAP = 0.05; // Snap to 5% increments

  function snap(v: number): number {
    return Math.round(v / SNAP) * SNAP;
  }

  function getValueFromMouseX(clientX: number): number {
    const rect = sliderEl?.getBoundingClientRect();
    if (!rect) return 0;
    const rel = (clientX - rect.left) / rect.width;
    return snap(Math.max(0, Math.min(1, rel)));
  }

  function handleSliderMouseDown(e: MouseEvent, handle: 'min' | 'max') {
    draggingHandle = handle;
    e.preventDefault();
  }

  function handleWindowMouseMove(e: MouseEvent) {
    if (!draggingHandle) return;
    const val = getValueFromMouseX(e.clientX);
    if (draggingHandle === 'min') {
      minSimilarity = Math.min(val, maxSimilarity - SNAP);
    } else {
      maxSimilarity = Math.max(val, minSimilarity + SNAP);
    }
  }

  function handleWindowMouseUp() {
    draggingHandle = null;
  }

  // ============================================================================
  // Formatting helpers
  // ============================================================================

  function formatPct(v: number): string {
    return `${Math.round(v * 100)}%`;
  }

  function formatTime(seconds: number): string {
    const mins = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  }
</script>

<svelte:window onmousemove={handleWindowMouseMove} onmouseup={handleWindowMouseUp} />

<div class="flex flex-col gap-3">
  <!-- Range Slider -->
  <div class="flex flex-col gap-1.5">
    <div class="flex items-center justify-between text-xs text-stone-500">
      <span>
        {m.search_threshold_range()}
        <span class="font-semibold text-stone-700">{formatPct(minSimilarity)}</span>
        –
        <span class="font-semibold text-stone-700">{formatPct(maxSimilarity)}</span>
      </span>
      {#if $sampleQuery.data}
        <span class="text-stone-400">
          {m.search_threshold_results_count({ count: totalInRange.toLocaleString() })}
        </span>
      {/if}
    </div>

    <!-- Two-handle slider track -->
    <div
      bind:this={sliderEl}
      class="relative h-5 cursor-pointer select-none"
      role="group"
      aria-label={m.search_aria_range_selector()}
    >
      <!-- Track background -->
      <div class="absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-stone-200"></div>

      <!-- Active track segment between handles -->
      <div
        class="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-primary-400"
        style="left: {minSimilarity * 100}%; right: {(1 - maxSimilarity) * 100}%;"
      ></div>

      <!-- Min handle -->
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div
        class="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 cursor-ew-resize rounded-full border-2 border-primary-500 bg-white shadow-sm transition-shadow hover:shadow-md"
        style="left: {minSimilarity * 100}%;"
        role="slider"
        aria-label={m.search_aria_min_similarity()}
        aria-valuenow={Math.round(minSimilarity * 100)}
        aria-valuemin={0}
        aria-valuemax={Math.round(maxSimilarity * 100)}
        tabindex="0"
        onmousedown={(e) => handleSliderMouseDown(e, 'min')}
        onkeydown={(e) => {
          if (e.key === 'ArrowLeft') minSimilarity = Math.max(0, snap(minSimilarity - SNAP));
          if (e.key === 'ArrowRight') minSimilarity = Math.min(maxSimilarity - SNAP, snap(minSimilarity + SNAP));
        }}
      ></div>

      <!-- Max handle -->
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div
        class="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 cursor-ew-resize rounded-full border-2 border-primary-500 bg-white shadow-sm transition-shadow hover:shadow-md"
        style="left: {maxSimilarity * 100}%;"
        role="slider"
        aria-label={m.search_aria_max_similarity()}
        aria-valuenow={Math.round(maxSimilarity * 100)}
        aria-valuemin={Math.round(minSimilarity * 100)}
        aria-valuemax={100}
        tabindex="0"
        onmousedown={(e) => handleSliderMouseDown(e, 'max')}
        onkeydown={(e) => {
          if (e.key === 'ArrowLeft') maxSimilarity = Math.max(minSimilarity + SNAP, snap(maxSimilarity - SNAP));
          if (e.key === 'ArrowRight') maxSimilarity = Math.min(1, snap(maxSimilarity + SNAP));
        }}
      ></div>
    </div>

    <!-- Tick marks at 20% intervals -->
    <div class="flex justify-between px-0.5 text-[10px] text-stone-400">
      {#each [0, 20, 40, 60, 80, 100] as pct}
        <span>{pct}%</span>
      {/each}
    </div>
  </div>

  <!-- Loading state -->
  {#if $sampleQuery.isLoading}
    <div class="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
      {#each { length: 6 } as _}
        <div class="animate-pulse overflow-hidden rounded-lg border border-stone-200 bg-surface-card">
          <div class="h-[80px] bg-stone-200"></div>
          <div class="p-1.5">
            <div class="h-3 w-3/4 rounded bg-stone-100"></div>
          </div>
        </div>
      {/each}
    </div>

  <!-- Error state -->
  {:else if $sampleQuery.isError}
    <div class="flex flex-col items-center justify-center rounded-lg border border-stone-200 bg-stone-50 py-8 text-center">
      <p class="text-sm text-stone-400">{m.search_no_results_in_range()}</p>
    </div>

  <!-- No session yet -->
  {:else if !sessionId}
    <div class="flex flex-col items-center justify-center rounded-lg border border-stone-200 bg-stone-50 py-10 text-center">
      <p class="text-sm text-stone-400">{m.search_no_results_in_range()}</p>
      <p class="mt-1 text-xs text-stone-300">{m.search_no_results_in_range_hint()}</p>
    </div>

  <!-- Empty range -->
  {:else if results.length === 0}
    <div class="flex flex-col items-center justify-center rounded-lg border border-stone-200 bg-stone-50 py-10 text-center">
      <p class="text-sm text-stone-400">{m.search_no_results_in_range()}</p>
      <p class="mt-1 text-xs text-stone-300">{m.search_no_results_in_range_hint()}</p>
    </div>

  {:else}
    <!-- Resample button + count -->
    <div class="flex items-center justify-between">
      <p class="text-xs text-stone-400">
        {results.length} / {totalInRange.toLocaleString()} samples shown
      </p>
      <button
        type="button"
        class="flex items-center gap-1.5 rounded-md border border-stone-200 bg-surface-card px-3 py-1.5 text-xs font-medium text-stone-600 transition-colors hover:border-primary-300 hover:text-primary-700 disabled:opacity-50"
        disabled={$sampleQuery.isFetching}
        onclick={() => { resampleCounter++; }}
      >
        {#if $sampleQuery.isFetching}
          <svg class="h-3.5 w-3.5 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
          </svg>
        {:else}
          <!-- Refresh icon -->
          <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
        {/if}
        Resample
      </button>
    </div>

    <!-- Results grid -->
    <div class="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
      {#each results as result (result.embedding_id)}
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <div
          class="group flex cursor-pointer flex-col gap-1 rounded-lg border p-1 transition-all
            {playingId === result.embedding_id
              ? 'border-primary-400 bg-primary-50 shadow-md'
              : 'border-stone-200 bg-white hover:border-primary-300 hover:shadow-sm'}"
          role="button"
          tabindex="0"
          aria-label={m.search_aria_play_result({ filename: result.recording_filename, time: formatTime(result.start_time), similarity: formatPct(result.similarity) })}
          onclick={() => handleCardClick(result)}
          onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleCardClick(result); } }}
        >
          <!-- Spectrogram thumbnail -->
          <MiniSpectrogram
            {projectId}
            recordingId={result.recording_id}
            startTime={result.start_time}
            endTime={result.end_time}
          />

          <!-- Metadata row -->
          <div class="flex items-center justify-between px-0.5">
            <!-- Similarity badge -->
            <span
              class="rounded-full px-1.5 py-0.5 text-[10px] font-semibold
                {result.similarity >= 0.8
                  ? 'bg-primary-100 text-primary-700'
                  : result.similarity >= 0.6
                    ? 'bg-amber-100 text-amber-700'
                    : 'bg-stone-100 text-stone-600'}"
            >
              {formatPct(result.similarity)}
            </span>

            <!-- Play indicator -->
            {#if playingId === result.embedding_id}
              <span class="text-primary-500">
                <!-- Pause icon -->
                <svg class="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 16 16" aria-hidden="true">
                  <path d="M5.5 3.5A1.5 1.5 0 017 5v6a1.5 1.5 0 01-3 0V5a1.5 1.5 0 011.5-1.5zm5 0A1.5 1.5 0 0112 5v6a1.5 1.5 0 01-3 0V5a1.5 1.5 0 011.5-1.5z"/>
                </svg>
              </span>
            {:else}
              <span class="text-stone-300 group-hover:text-primary-400">
                <!-- Play icon -->
                <svg class="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 16 16" aria-hidden="true">
                  <path d="M6.79 5.093A.5.5 0 006 5.5v5a.5.5 0 00.79.407l3.5-2.5a.5.5 0 000-.814l-3.5-2.5z"/>
                </svg>
              </span>
            {/if}
          </div>

          <!-- Recording name (truncated) -->
          <p class="truncate px-0.5 text-[10px] text-stone-400" title={result.recording_filename}>
            {result.recording_filename}
          </p>
        </div>
      {/each}
    </div>
  {/if}
</div>
