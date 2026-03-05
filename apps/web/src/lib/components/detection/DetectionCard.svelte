<script lang="ts">
  /**
   * DetectionCard - Compact card showing a single detection with review actions.
   *
   * Assembles: MiniSpectrogram + audio playback + ReviewActions + metadata.
   * Supports confirm, reject, and species change operations.
   */

  import type { Detection } from '$lib/types/detection';
  import MiniSpectrogram from './MiniSpectrogram.svelte';
  import ReviewActions from './ReviewActions.svelte';
  import SpeciesCorrector from './SpeciesCorrector.svelte';

  export let detection: Detection;
  export let projectId: string;
  export let isSelected: boolean = false;
  export let isLoading: boolean = false;
  export let onConfirm: (detectionId: string, startTime: number, endTime: number) => void;
  export let onReject: (detectionId: string) => void;
  export let onChangeSpecies: (detectionId: string, newTagId: string) => void;

  let audio: HTMLAudioElement | null = null;
  let isPlaying = false;

  $: audioUrl = buildAudioUrl(detection.recording_id, detection.start_time, detection.end_time);
  $: confidencePercent = detection.confidence != null
    ? Math.round(detection.confidence * 100)
    : null;
  $: recordingName = detection.recording?.filename
    ?? detection.recording_id.slice(0, 8) + '...';
  $: tagName = detection.tag?.common_name ?? detection.tag?.name ?? 'Unidentified';

  function buildAudioUrl(recordingId: string, start: number, end: number): string {
    const params = new URLSearchParams({
      start: start.toString(),
      end: end.toString(),
    });
    return `/api/v1/projects/${projectId}/recordings/${recordingId}/playback?${params}`;
  }

  function formatTime(seconds: number): string {
    const mins = Math.floor(seconds / 60);
    const secs = (seconds % 60).toFixed(1);
    return `${mins}:${secs.padStart(4, '0')}`;
  }

  function formatDuration(start: number, end: number): string {
    return `${formatTime(start)} \u2013 ${formatTime(end)}`;
  }

  function getSourceLabel(source: string): string {
    switch (source) {
      case 'birdnet':
        return 'BirdNET';
      case 'perch_search':
        return 'Perch';
      case 'human':
        return 'Human';
      default:
        return source;
    }
  }

  function toggleAudio() {
    if (!audio) {
      audio = new Audio(audioUrl);
      audio.addEventListener('ended', () => {
        isPlaying = false;
      });
      audio.addEventListener('error', () => {
        isPlaying = false;
      });
    }

    if (isPlaying) {
      audio.pause();
      audio.currentTime = 0;
      isPlaying = false;
    } else {
      audio.play().then(() => {
        isPlaying = true;
      }).catch(() => {
        isPlaying = false;
      });
    }
  }

  function handleConfirm() {
    if (isPlaying) {
      audio?.pause();
      isPlaying = false;
    }
    onConfirm(detection.id, detection.start_time, detection.end_time);
  }

  function handleReject() {
    if (isPlaying) {
      audio?.pause();
      isPlaying = false;
    }
    onReject(detection.id);
  }

  function handleChangeSpecies(newTagId: string) {
    onChangeSpecies(detection.id, newTagId);
  }

  // Stop audio when detection changes
  $: if (detection.id) {
    if (audio && isPlaying) {
      audio.pause();
      audio = null;
      isPlaying = false;
    }
  }

  // Border color based on status
  $: borderClass = detection.status === 'confirmed'
    ? 'border-green-400 ring-1 ring-green-300'
    : detection.status === 'rejected'
    ? 'border-red-400 ring-1 ring-red-300'
    : isSelected
    ? 'border-blue-400 ring-1 ring-blue-300'
    : 'border-stone-200';

  // Brief scale animation when a mutation completes (isLoading transitions true -> false)
  let justUpdated = false;
  let prevIsLoading = false;

  $: {
    if (prevIsLoading && !isLoading) {
      justUpdated = true;
      setTimeout(() => {
        justUpdated = false;
      }, 400);
    }
    prevIsLoading = isLoading;
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_interactive_supports_focus -->
<div
  class="relative flex flex-col overflow-hidden rounded-lg border bg-white shadow-sm transition-all duration-300 ease-in-out hover:shadow-md {borderClass} {justUpdated ? 'scale-[1.02]' : ''}"
  role="article"
  aria-label="Detection: {tagName}"
>
  <!-- Loading overlay: semi-transparent overlay while mutation is in flight -->
  {#if isLoading}
    <div class="absolute inset-0 z-10 flex items-center justify-center rounded-lg bg-white/60">
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
      recordingId={detection.recording_id}
      startTime={detection.start_time}
      endTime={detection.end_time}
      freqLow={detection.freq_low ?? undefined}
      freqHigh={detection.freq_high ?? undefined}
    />

    <!-- Audio play/stop button overlay -->
    <button
      type="button"
      class="absolute right-1 top-1 flex h-7 w-7 items-center justify-center rounded-full bg-black/50 text-white transition-colors hover:bg-black/70 focus:outline-none focus:ring-2 focus:ring-white/50"
      on:click|stopPropagation={toggleAudio}
      aria-label={isPlaying ? 'Stop audio' : 'Play audio'}
      title={isPlaying ? 'Stop' : 'Play clip (Space)'}
    >
      {#if isPlaying}
        <!-- Stop icon -->
        <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="currentColor">
          <rect x="6" y="6" width="12" height="12" rx="1" />
        </svg>
      {:else}
        <!-- Play icon -->
        <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="currentColor">
          <polygon points="5 3 19 12 5 21 5 3" />
        </svg>
      {/if}
    </button>
  </div>

  <!-- Card body -->
  <div class="flex flex-col gap-2 p-2.5">
    <!-- Tag name and confidence -->
    <div class="flex items-center justify-between gap-2">
      <span class="truncate text-sm font-semibold text-stone-800" title={tagName}>
        {tagName}
      </span>
      {#if confidencePercent !== null}
        <span
          class="shrink-0 rounded px-1.5 py-0.5 text-xs font-medium
            {confidencePercent >= 80
              ? 'bg-green-100 text-green-700'
              : confidencePercent >= 50
              ? 'bg-yellow-100 text-yellow-700'
              : 'bg-red-100 text-red-700'}"
          title="Model confidence"
        >
          {confidencePercent}%
        </span>
      {/if}
    </div>

    <!-- Recording name and time -->
    <div class="flex flex-col gap-0.5">
      <span class="truncate text-xs text-stone-500" title={recordingName}>
        {recordingName}
      </span>
      <span class="font-mono text-xs text-stone-400">
        {formatDuration(detection.start_time, detection.end_time)}
      </span>
    </div>

    <!-- Source badge -->
    <div class="flex items-center gap-1">
      <span class="rounded bg-stone-100 px-1.5 py-0.5 text-xs text-stone-500">
        {getSourceLabel(detection.source)}
      </span>
      {#if detection.reviewed_at}
        <span class="text-xs text-stone-400" title={new Date(detection.reviewed_at).toLocaleString()}>
          Reviewed {new Date(detection.reviewed_at).toLocaleDateString()}
        </span>
      {/if}
    </div>

    <!-- Species corrector -->
    <SpeciesCorrector
      currentTagId={detection.tag_id}
      {projectId}
      onChangeSpecies={handleChangeSpecies}
    />

    <!-- Review actions -->
    <ReviewActions
      status={detection.status}
      {isLoading}
      onConfirm={handleConfirm}
      onReject={handleReject}
    />
  </div>
</div>
