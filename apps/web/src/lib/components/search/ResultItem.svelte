<script lang="ts">
  /**
   * ResultItem - Single similarity search result row.
   *
   * Displays recording filename, time range, similarity badge, play/stop button,
   * and a link to the full recording page.
   */

  import { onDestroy } from 'svelte';
  import * as m from '$lib/paraglide/messages.js';
  import { localizeHref } from '$lib/paraglide/runtime';
  import { getAuthenticatedRecordingMediaUrl, getPlaybackUrl } from '$lib/api/recordings';
  import type { SimilarityResult } from '$lib/types/search';

  interface Props {
    projectId: string;
    match: SimilarityResult;
  }

  let { projectId, match }: Props = $props();

  let isPlaying = $state(false);
  let audioEl: HTMLAudioElement | null = null;
  let disposed = false;
  let playbackRequestId = 0;

  function formatTime(seconds: number): string {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  }

  function getSimilarityClass(similarity: number): string {
    if (similarity >= 0.9) return 'bg-success-light text-success';
    if (similarity >= 0.7) return 'bg-primary-100 text-primary-800';
    if (similarity >= 0.5) return 'bg-warning-light text-warning';
    return 'bg-stone-100 text-stone-600';
  }

  async function togglePlay() {
    if (isPlaying) {
      playbackRequestId += 1;
      audioEl?.pause();
      audioEl = null;
      isPlaying = false;
    } else {
      if (audioEl) {
        playbackRequestId += 1;
        audioEl.pause();
        audioEl = null;
      }
      const requestId = ++playbackRequestId;
      const playbackUrl = getPlaybackUrl(projectId, match.recording_id, {
        start: match.start_time,
        end: match.end_time,
      });
      let url: string;
      try {
        url = await getAuthenticatedRecordingMediaUrl(
          projectId,
          match.recording_id,
          'playback',
          playbackUrl
        );
      } catch {
        if (requestId === playbackRequestId) {
          isPlaying = false;
        }
        return;
      }
      if (disposed || requestId !== playbackRequestId) {
        return;
      }
      const audio = new Audio(url);
      audio.addEventListener('ended', () => {
        if (audioEl !== audio) return;
        isPlaying = false;
        audioEl = null;
      });
      audio.addEventListener('error', () => {
        if (audioEl !== audio) return;
        isPlaying = false;
        audioEl = null;
      });
      audioEl = audio;
      isPlaying = true;
      audio.play().catch(() => {
        if (audioEl !== audio) return;
        isPlaying = false;
        audioEl = null;
      });
    }
  }

  onDestroy(() => {
    disposed = true;
    playbackRequestId += 1;
    audioEl?.pause();
    audioEl = null;
  });

  const duration = $derived((match.end_time - match.start_time).toFixed(1));
</script>

<div class="flex items-center gap-3 rounded-lg border border-card bg-surface-card px-3 py-2.5">
  <!-- Play/stop button -->
  <button
    class="shrink-0 text-stone-500 transition-colors hover:text-primary-600"
    onclick={togglePlay}
    aria-label={isPlaying ? m.search_stop() : m.search_play()}
    title={isPlaying ? m.search_stop() : m.search_play()}
    type="button"
  >
    {#if isPlaying}
      <!-- Stop icon -->
      <svg class="h-4 w-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <rect x="6" y="6" width="12" height="12" rx="1" />
      </svg>
    {:else}
      <!-- Play icon -->
      <svg class="h-4 w-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M8 5v14l11-7z" />
      </svg>
    {/if}
  </button>

  <!-- Recording info -->
  <div class="min-w-0 flex-1">
    <p class="truncate text-sm font-medium text-stone-900">{match.recording_filename}</p>
    <p class="text-xs text-stone-400">
      {formatTime(match.start_time)} – {formatTime(match.end_time)} ({duration}s)
    </p>
  </div>

  <!-- Similarity badge -->
  <span class="rounded px-2 py-0.5 text-sm font-medium {getSimilarityClass(match.similarity)}">
    {(match.similarity * 100).toFixed(1)}%
  </span>

  <!-- View recording link -->
  <a
    href={localizeHref(`/projects/${projectId}/recordings/${match.recording_id}`)}
    class="shrink-0 text-xs text-primary-600 hover:underline"
  >
    {m.search_view_recording()}
  </a>
</div>
