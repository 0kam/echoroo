<script lang="ts">
  /**
   * SearchPreviewCard - Read-only card for displaying a single similarity search result.
   *
   * Shows the spectrogram thumbnail, recording filename, time range, and similarity
   * score. Supports audio playback via a play button or clicking the card.
   * No voting or review actions — this is an exploration-only component.
   */

  import * as m from '$lib/paraglide/messages.js';
  import MiniSpectrogram from '$lib/components/common/MiniSpectrogram.svelte';

  interface Props {
    projectId: string;
    recordingId: string;
    recordingName: string;
    startTime: number;
    endTime: number;
    /** Similarity score (0–1) displayed as a percentage badge */
    similarity: number;
    /** Whether this card is keyboard-focused */
    isSelected?: boolean;
    /** Whether audio is currently playing for this card */
    isPlaying?: boolean;
    /** Whether audio is being loaded for this card */
    isLoadingAudio?: boolean;
    /** Called when the user clicks the play button or the card body */
    onPlayToggle?: () => void;
  }

  let {
    projectId,
    recordingId,
    recordingName,
    startTime,
    endTime,
    similarity,
    isSelected = false,
    isPlaying = false,
    isLoadingAudio = false,
    onPlayToggle,
  }: Props = $props();

  const similarityPercent = $derived(Math.round(similarity * 100));

  const similarityBadgeClass = $derived(
    similarity >= 0.8
      ? 'bg-success-light text-success'
      : similarity >= 0.7
        ? 'bg-primary-100 text-primary-800'
        : similarity >= 0.5
          ? 'bg-warning-light text-warning'
          : 'bg-stone-100 text-stone-600'
  );

  function formatTime(seconds: number): string {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  const timeRange = $derived(`${formatTime(startTime)} – ${formatTime(endTime)}`);
</script>

<div
  class="group overflow-hidden rounded-lg border bg-surface-card shadow-sm transition-all
    {isSelected
      ? 'border-primary-400 ring-2 ring-primary-300'
      : 'border-stone-200 hover:border-stone-300'}"
  role="article"
>
  <!-- Spectrogram with play overlay -->
  <div class="relative cursor-pointer" onclick={onPlayToggle}>
    <MiniSpectrogram
      {projectId}
      {recordingId}
      {startTime}
      {endTime}
    />

    <!-- Similarity badge overlaid on spectrogram -->
    <span
      class="absolute right-1.5 top-1.5 rounded px-1.5 py-0.5 text-xs font-medium {similarityBadgeClass}"
      title={m.search_similarity_score()}
    >
      {similarityPercent}%
    </span>

    <!-- Play / loading button overlay -->
    <button
      type="button"
      class="absolute bottom-1.5 right-1.5 flex h-7 w-7 items-center justify-center rounded-full
             bg-black/50 text-white opacity-0 transition-opacity group-hover:opacity-100
             {isPlaying || isLoadingAudio ? 'opacity-100' : ''}"
      onclick={(e) => { e.stopPropagation(); onPlayToggle?.(); }}
      aria-label={isPlaying ? m.common_pause() : m.common_play()}
    >
      {#if isLoadingAudio}
        <!-- Spinner -->
        <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
      {:else if isPlaying}
        <!-- Pause icon -->
        <svg class="h-4 w-4" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z" />
        </svg>
      {:else}
        <!-- Play icon -->
        <svg class="h-4 w-4" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M8 5v14l11-7z" />
        </svg>
      {/if}
    </button>
  </div>

  <!-- Card info -->
  <div class="flex flex-col gap-1 p-2.5">
    <!-- Filename -->
    <p
      class="truncate text-xs font-medium text-stone-700"
      title={recordingName}
    >
      {recordingName}
    </p>

    <!-- Time range -->
    <p class="text-xs text-stone-400">{timeRange}</p>
  </div>
</div>
