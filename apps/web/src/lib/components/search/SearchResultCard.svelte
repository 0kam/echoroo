<script lang="ts">
  /**
   * SearchResultCard - Displays a single similarity search result with spectrogram.
   *
   * Reuses MiniSpectrogram for the visual, provides confirm/reject actions that
   * create annotations via the search API or update client-side state.
   */

  import { onDestroy } from 'svelte';
  import * as m from '$lib/paraglide/messages.js';
  import { apiClient } from '$lib/api/client';
  import { createAnnotationFromSearch } from '$lib/api/search';
  import type { SimilarityResult, SearchResultStatus } from '$lib/types/search';
  import MiniSpectrogram from '$lib/components/detection/MiniSpectrogram.svelte';

  interface Props {
    projectId: string;
    result: SimilarityResult;
    tagId: string;
    status: SearchResultStatus;
    onConfirm: () => void;
    onReject: () => void;
  }

  let { projectId, result, tagId, status, onConfirm, onReject }: Props = $props();

  let isPlaying = $state(false);
  let isLoadingAudio = $state(false);
  let isConfirming = $state(false);
  let audio: HTMLAudioElement | null = null;
  let audioBlobUrl: string | null = null;

  const similarityPercent = $derived(Math.round(result.similarity * 100));
  const recordingName = $derived(result.recording_filename ?? result.recording_id.slice(0, 8) + '...');

  function formatTime(seconds: number): string {
    const mins = Math.floor(seconds / 60);
    const secs = (seconds % 60).toFixed(1);
    return `${mins}:${secs.padStart(4, '0')}`;
  }

  function formatDuration(start: number, end: number): string {
    return `${formatTime(start)} \u2013 ${formatTime(end)}`;
  }

  function getSimilarityBadgeClass(similarity: number): string {
    if (similarity >= 0.8) return 'bg-green-100 text-green-700';
    if (similarity >= 0.7) return 'bg-primary-100 text-primary-800';
    if (similarity >= 0.5) return 'bg-yellow-100 text-yellow-700';
    return 'bg-stone-100 text-stone-600';
  }

  function getBorderClass(s: SearchResultStatus): string {
    if (s === 'confirmed') return 'border-green-400 ring-1 ring-green-300';
    if (s === 'rejected') return 'border-red-400 ring-1 ring-red-300 opacity-50';
    return 'border-stone-200';
  }

  function buildAudioUrl(recordingId: string, start: number, end: number): string {
    const params = new URLSearchParams({
      start: start.toString(),
      end: end.toString(),
    });
    return `/api/v1/projects/${projectId}/recordings/${recordingId}/playback?${params}`;
  }

  function stopAndCleanAudio() {
    if (audio) {
      audio.pause();
      audio = null;
    }
    if (audioBlobUrl) {
      URL.revokeObjectURL(audioBlobUrl);
      audioBlobUrl = null;
    }
    isPlaying = false;
  }

  async function toggleAudio() {
    if (isPlaying) {
      stopAndCleanAudio();
      return;
    }

    isLoadingAudio = true;
    try {
      const url = buildAudioUrl(result.recording_id, result.start_time, result.end_time);
      const res = await apiClient.fetchRaw(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();

      if (audioBlobUrl) URL.revokeObjectURL(audioBlobUrl);
      audioBlobUrl = URL.createObjectURL(blob);

      audio = new Audio(audioBlobUrl);
      audio.addEventListener('ended', () => { isPlaying = false; });
      audio.addEventListener('error', () => { isPlaying = false; });

      await audio.play();
      isPlaying = true;
    } catch {
      isPlaying = false;
      stopAndCleanAudio();
    } finally {
      isLoadingAudio = false;
    }
  }

  async function handleConfirm() {
    if (isConfirming || status === 'confirmed') return;
    stopAndCleanAudio();
    isConfirming = true;
    try {
      await createAnnotationFromSearch(projectId, {
        recording_id: result.recording_id,
        tag_id: tagId,
        start_time: result.start_time,
        end_time: result.end_time,
        confidence: result.similarity,
      });
      onConfirm();
    } catch {
      // Silently fail — user can retry
    } finally {
      isConfirming = false;
    }
  }

  function handleReject() {
    stopAndCleanAudio();
    onReject();
  }

  onDestroy(() => {
    stopAndCleanAudio();
  });
</script>

<div
  class="relative flex flex-col overflow-hidden rounded-lg border bg-surface-card shadow-sm transition-all duration-200 ease-in-out hover:shadow-md {getBorderClass(status)}"
  role="article"
  aria-label="Search result: {recordingName}"
>
  <!-- Loading overlay while confirming -->
  {#if isConfirming}
    <div class="absolute inset-0 z-10 flex items-center justify-center rounded-lg bg-surface-card/60">
      <svg class="h-5 w-5 animate-spin text-stone-400" viewBox="0 0 24 24" fill="none">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
    </div>
  {/if}

  <!-- Spectrogram -->
  <div class="relative">
    <MiniSpectrogram
      {projectId}
      recordingId={result.recording_id}
      startTime={result.start_time}
      endTime={result.end_time}
    />

    <!-- Similarity badge overlay -->
    <span
      class="absolute left-1 top-1 rounded px-1.5 py-0.5 text-xs font-semibold {getSimilarityBadgeClass(result.similarity)}"
      title={m.search_similarity()}
    >
      {similarityPercent}%
    </span>

    <!-- Play/stop button -->
    <button
      type="button"
      class="absolute right-1 top-1 flex h-7 w-7 items-center justify-center rounded-full bg-black/50 text-white transition-colors hover:bg-black/70 focus:outline-none focus:ring-2 focus:ring-white/50 disabled:cursor-not-allowed disabled:opacity-60"
      onclick={toggleAudio}
      disabled={isLoadingAudio}
      aria-label={isPlaying ? m.search_stop() : m.search_play()}
      title={isPlaying ? m.search_stop() : m.search_play()}
    >
      {#if isLoadingAudio}
        <div class="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/40 border-t-white"></div>
      {:else if isPlaying}
        <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="currentColor">
          <rect x="6" y="6" width="12" height="12" rx="1" />
        </svg>
      {:else}
        <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="currentColor">
          <polygon points="5 3 19 12 5 21 5 3" />
        </svg>
      {/if}
    </button>
  </div>

  <!-- Card body -->
  <div class="flex flex-col gap-2 p-2.5">
    <!-- Recording name -->
    <span class="truncate text-xs text-stone-500" title={recordingName}>
      {recordingName}
    </span>
    <!-- Time range -->
    <span class="font-mono text-xs text-stone-400">
      {formatDuration(result.start_time, result.end_time)}
    </span>

    <!-- Confirm / Reject actions -->
    <div class="flex items-center gap-2">
      <!-- Status badge -->
      {#if status === 'confirmed'}
        <span class="inline-flex items-center rounded-full border border-green-200 bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800">
          {m.search_confirmed()}
        </span>
      {:else if status === 'rejected'}
        <span class="inline-flex items-center rounded-full border border-red-200 bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800">
          {m.search_rejected()}
        </span>
      {/if}

      <!-- Confirm button -->
      <button
        type="button"
        class="inline-flex items-center gap-1 rounded px-2.5 py-1 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50
          {status === 'confirmed'
            ? 'bg-green-600 text-white hover:bg-green-700'
            : 'border border-green-300 bg-green-50 text-green-700 hover:bg-green-100'}"
        onclick={handleConfirm}
        disabled={isConfirming}
        title={m.search_confirm()}
        aria-label={m.search_confirm()}
      >
        <svg class="h-3 w-3" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
        </svg>
        {m.search_confirm()}
      </button>

      <!-- Reject button -->
      <button
        type="button"
        class="inline-flex items-center gap-1 rounded px-2.5 py-1 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50
          {status === 'rejected'
            ? 'bg-red-600 text-white hover:bg-red-700'
            : 'border border-red-300 bg-red-50 text-red-700 hover:bg-red-100'}"
        onclick={handleReject}
        disabled={isConfirming}
        title={m.search_reject()}
        aria-label={m.search_reject()}
      >
        <svg class="h-3 w-3" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
        </svg>
        {m.search_reject()}
      </button>
    </div>
  </div>
</div>
