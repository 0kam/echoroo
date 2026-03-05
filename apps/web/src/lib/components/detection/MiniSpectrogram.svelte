<script lang="ts">
  /**
   * MiniSpectrogram - Compact spectrogram image for a detection time window.
   *
   * Renders a small spectrogram from the backend API for the given recording
   * and time range, with a semi-transparent overlay for the detection region.
   */

  export let projectId: string;
  export let recordingId: string;
  export let startTime: number;
  export let endTime: number;
  export let freqLow: number | undefined = undefined;
  export let freqHigh: number | undefined = undefined;

  // Add a small buffer around the detection for context
  const BUFFER_SECONDS = 0.5;

  $: windowStart = Math.max(0, startTime - BUFFER_SECONDS);
  $: windowEnd = endTime + BUFFER_SECONDS;

  $: spectrogramUrl = buildSpectrogramUrl(projectId, recordingId, windowStart, windowEnd);

  function buildSpectrogramUrl(projId: string, id: string, start: number, end: number): string {
    const params = new URLSearchParams({
      start: start.toString(),
      end: end.toString(),
      width: '300',
      height: '120',
    });
    return `/api/v1/projects/${projId}/recordings/${id}/spectrogram?${params}`;
  }

  function formatTime(seconds: number): string {
    const mins = Math.floor(seconds / 60);
    const secs = (seconds % 60).toFixed(1);
    return `${mins}:${secs.padStart(4, '0')}`;
  }

  // Calculate overlay position as percentage within the window
  $: windowDuration = windowEnd - windowStart;
  $: overlayLeft = windowDuration > 0 ? ((startTime - windowStart) / windowDuration) * 100 : 0;
  $: overlayRight = windowDuration > 0 ? ((windowEnd - endTime) / windowDuration) * 100 : 0;

  let isLoaded = false;
  let isError = false;

  function handleLoad() {
    isLoaded = true;
    isError = false;
  }

  function handleError() {
    isError = true;
    isLoaded = false;
  }
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
      Spectrogram unavailable
    </div>
  {/if}

  <!-- Spectrogram image -->
  <img
    src={spectrogramUrl}
    alt="Spectrogram {formatTime(startTime)} to {formatTime(endTime)}"
    class="h-full w-full object-fill"
    class:opacity-0={!isLoaded}
    on:load={handleLoad}
    on:error={handleError}
  />

  <!-- Detection region overlay -->
  {#if isLoaded}
    <div
      class="pointer-events-none absolute inset-y-0 border-x-2 border-emerald-400 bg-emerald-400/10"
      style="left: {overlayLeft}%; right: {overlayRight}%;"
    ></div>
  {/if}

  <!-- Frequency range label -->
  {#if isLoaded && freqLow !== undefined && freqHigh !== undefined}
    <div class="pointer-events-none absolute bottom-0.5 right-1 font-mono text-xs text-emerald-300/80">
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
