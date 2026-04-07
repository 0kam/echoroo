<script lang="ts">
  /**
   * ThresholdPreview - Spectrogram grid for results within a similarity range.
   *
   * Renders a two-handle range slider allowing the user to define a min/max
   * similarity band, then shows spectrogram thumbnails (via MiniSpectrogram)
   * for results within that band. Supports pagination (max 20 per page)
   * and audio playback on click.
   */

  import type { SimilarityResult } from '$lib/types/search';
  import MiniSpectrogram from '$lib/components/common/MiniSpectrogram.svelte';

  // ============================================================================
  // Props
  // ============================================================================

  let {
    results,
    projectId,
    minSimilarity = $bindable(),
    maxSimilarity = $bindable(),
  }: {
    results: SimilarityResult[];
    projectId: string;
    minSimilarity: number;
    maxSimilarity: number;
  } = $props();

  // ============================================================================
  // Range slider state
  // ============================================================================

  const PAGE_SIZE = 20;
  let currentPage = $state(0);

  // Reset page when range changes
  $effect(() => {
    // Depend on range values so page resets when they change
    void minSimilarity;
    void maxSimilarity;
    currentPage = 0;
  });

  // ============================================================================
  // Filtered & paginated results
  // ============================================================================

  const filtered = $derived(
    results
      .filter((r) => r.similarity >= minSimilarity && r.similarity <= maxSimilarity)
      .sort((a, b) => b.similarity - a.similarity),
  );

  const totalPages = $derived(Math.max(1, Math.ceil(filtered.length / PAGE_SIZE)));

  const pageResults = $derived(
    filtered.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE),
  );

  // ============================================================================
  // Audio playback state
  // ============================================================================

  let playingId = $state<string | null>(null);
  let audioEl = $state<HTMLAudioElement | null>(null);

  function handleCardClick(result: SimilarityResult) {
    if (playingId === result.embedding_id) {
      audioEl?.pause();
      playingId = null;
    } else {
      playingId = result.embedding_id;
      // Audio playback is handled via the browser's native audio where available;
      // here we just track the selected card for visual feedback.
      // Full audio integration with apiClient can be added during ResultsPanel integration.
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
        Similarity range:
        <span class="font-semibold text-stone-700">{formatPct(minSimilarity)}</span>
        –
        <span class="font-semibold text-stone-700">{formatPct(maxSimilarity)}</span>
      </span>
      <span class="text-stone-400">{filtered.length.toLocaleString()} results</span>
    </div>

    <!-- Two-handle slider track -->
    <div
      bind:this={sliderEl}
      class="relative h-5 cursor-pointer select-none"
      role="group"
      aria-label="Similarity range selector"
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
        aria-label="Minimum similarity"
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
        aria-label="Maximum similarity"
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

  <!-- Results grid -->
  {#if filtered.length === 0}
    <div class="flex flex-col items-center justify-center rounded-lg border border-stone-200 bg-stone-50 py-10 text-center">
      <p class="text-sm text-stone-400">No results in this range</p>
      <p class="mt-1 text-xs text-stone-300">Adjust the similarity range slider above</p>
    </div>
  {:else}
    <div class="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
      {#each pageResults as result (result.embedding_id)}
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <div
          class="group flex cursor-pointer flex-col gap-1 rounded-lg border p-1 transition-all
            {playingId === result.embedding_id
              ? 'border-primary-400 bg-primary-50 shadow-md'
              : 'border-stone-200 bg-white hover:border-primary-300 hover:shadow-sm'}"
          role="button"
          tabindex="0"
          aria-label="Play {result.recording_filename} at {formatTime(result.start_time)}, similarity {formatPct(result.similarity)}"
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

    <!-- Pagination -->
    {#if totalPages > 1}
      <div class="flex items-center justify-center gap-2">
        <button
          class="rounded px-2 py-1 text-xs text-stone-500 disabled:opacity-30 enabled:hover:bg-stone-100"
          disabled={currentPage === 0}
          onclick={() => { currentPage = Math.max(0, currentPage - 1); }}
        >
          Previous
        </button>
        <span class="text-xs text-stone-500">
          {currentPage + 1} / {totalPages}
        </span>
        <button
          class="rounded px-2 py-1 text-xs text-stone-500 disabled:opacity-30 enabled:hover:bg-stone-100"
          disabled={currentPage >= totalPages - 1}
          onclick={() => { currentPage = Math.min(totalPages - 1, currentPage + 1); }}
        >
          Next
        </button>
      </div>
    {/if}
  {/if}
</div>
