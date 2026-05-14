<script lang="ts">
  /**
   * MiniSpectrogram - Compact spectrogram image for a detection time window.
   *
   * Renders a small spectrogram from the backend API for the given recording
   * and time range, with a semi-transparent overlay for the detection region.
   * Uses authenticated fetch + blob URL to avoid 401 errors from direct <img> requests.
   */

  import { onDestroy, onMount } from 'svelte';
  import { apiClient } from '$lib/api/client';
  import * as m from '$lib/paraglide/messages';

  interface Props {
    projectId: string;
    recordingId: string;
    startTime: number;
    endTime: number;
    freqLow?: number;
    freqHigh?: number;
  }

  let {
    projectId,
    recordingId,
    startTime,
    endTime,
    freqLow,
    freqHigh,
  }: Props = $props();

  // Add a small buffer around the detection for context
  const BUFFER_SECONDS = 0.5;

  const windowStart = $derived(Math.max(0, startTime - BUFFER_SECONDS));
  const windowEnd = $derived(endTime + BUFFER_SECONDS);

  let blobUrl = $state<string | null>(null);
  let isLoaded = $state(false);
  let isError = $state(false);
  let mounted = $state(false);

  function revokeBlobUrl() {
    if (blobUrl) {
      URL.revokeObjectURL(blobUrl);
      blobUrl = null;
    }
  }

  // Track the latest fetch so stale responses are ignored
  let fetchId = 0;

  function fetchSpectrogram(projId: string, recId: string, start: number, end: number) {
    if (!mounted) return;

    const params = new URLSearchParams({
      start: start.toString(),
      end: end.toString(),
      width: '300',
      height: '120',
    });
    const url = `/web-api/v1/projects/${projId}/recordings/${recId}/spectrogram?${params}`;

    const currentFetchId = ++fetchId;
    isLoaded = false;
    isError = false;
    revokeBlobUrl();

    apiClient
      .fetchRaw(url)
      .then((res) => {
        if (currentFetchId !== fetchId) return; // Stale response
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.blob();
      })
      .then((blob) => {
        if (currentFetchId !== fetchId) return; // Stale response
        if (!blob) return;
        revokeBlobUrl();
        blobUrl = URL.createObjectURL(blob);
        isLoaded = true;
        isError = false;
      })
      .catch(() => {
        if (currentFetchId !== fetchId) return; // Stale response
        isError = true;
        isLoaded = false;
      });
  }

  onMount(() => {
    mounted = true;
  });

  // Fetch on mount and re-fetch when props change.
  // Uses a local copy of props to avoid double-fetching from $effect
  // re-running when mounted transitions to true.
  let prevKey = '';
  $effect(() => {
    if (!mounted) return;
    const key = `${projectId}|${recordingId}|${windowStart}|${windowEnd}`;
    if (key === prevKey) return;
    prevKey = key;
    fetchSpectrogram(projectId, recordingId, windowStart, windowEnd);
  });

  onDestroy(() => {
    fetchId++; // Invalidate any in-flight fetch
    revokeBlobUrl();
  });

  function formatTime(seconds: number): string {
    const mins = Math.floor(seconds / 60);
    const secs = (seconds % 60).toFixed(1);
    return `${mins}:${secs.padStart(4, '0')}`;
  }

  // Calculate overlay position as percentage within the window
  const windowDuration = $derived(windowEnd - windowStart);
  const overlayLeft = $derived(windowDuration > 0 ? ((startTime - windowStart) / windowDuration) * 100 : 0);
  const overlayRight = $derived(windowDuration > 0 ? ((windowEnd - endTime) / windowDuration) * 100 : 0);
</script>

<div class="relative w-full overflow-hidden rounded" style="height: 120px; background: #1c1917;">
  {#if !isLoaded && !isError}
    <!-- Loading skeleton -->
    <div class="absolute inset-0 flex items-center justify-center">
      <div class="h-4 w-4 animate-spin rounded-full border-2 border-stone-500 border-t-stone-300"></div>
    </div>
  {/if}

  {#if isError}
    <!-- Error state -->
    <div class="absolute inset-0 flex items-center justify-center text-xs text-stone-400">
      {m.detection_spectrogram_unavailable()}
    </div>
  {/if}

  <!-- Spectrogram image (shown only when blob URL is ready) -->
  {#if blobUrl}
    <img
      src={blobUrl}
      alt="Spectrogram {formatTime(startTime)} to {formatTime(endTime)}"
      class="h-full w-full object-fill"
    />
  {/if}

  <!-- Detection region overlay -->
  {#if isLoaded}
    <div
      class="pointer-events-none absolute inset-y-0 border-x-2 border-primary-400 bg-primary-400/10"
      style="left: {overlayLeft}%; right: {overlayRight}%;"
    ></div>
  {/if}

  <!-- Frequency range label -->
  {#if isLoaded && freqLow !== undefined && freqHigh !== undefined}
    <div class="pointer-events-none absolute bottom-0.5 right-1 font-mono text-xs text-primary-300/80">
      {(freqLow / 1000).toFixed(1)}&ndash;{(freqHigh / 1000).toFixed(1)} kHz
    </div>
  {/if}

  <!-- Time range label -->
  {#if isLoaded}
    <div class="pointer-events-none absolute bottom-0.5 left-1 font-mono text-xs text-white/60">
      {formatTime(startTime)}&ndash;{formatTime(endTime)}
    </div>
  {/if}
</div>
