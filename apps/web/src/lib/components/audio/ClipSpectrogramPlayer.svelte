<script lang="ts">
  /**
   * ClipSpectrogramPlayer - lightweight spectrogram + audio player for a clip
   * (a time-bounded segment of a recording). Used by annotation pages where only
   * the clip region is displayed rather than the full recording.
   *
   * Internally manages viewport and bounds state so callers only need to
   * provide basic clip/recording metadata.
   */
  import SpectrogramViewer from '$lib/components/audio/SpectrogramViewer.svelte';
  import AudioPlayer from '$lib/components/audio/AudioPlayer.svelte';
  import type { RecordingDetail } from '$lib/types/data';
  import type { SpectrogramWindow, InteractionMode } from '$lib/types/audio';
  import {
    DEFAULT_SPECTROGRAM_SETTINGS,
    DEFAULT_AUDIO_SETTINGS,
    getSpeedOptions,
  } from '$lib/types/audio';
  import { getInitialViewingWindow, adjustWindowToBounds } from '$lib/utils/viewport';

  /**
   * Minimum recording fields required by this component.
   * Compatible with both RecordingDetail and RecordingSummaryForTask.
   */
  interface RecordingMinimal {
    id: string;
    filename: string;
    samplerate: number;
    duration: number;
  }

  interface Props {
    projectId: string;
    recording: RecordingMinimal;
    /** Clip start time within the recording (seconds) */
    clipStart: number;
    /** Clip end time within the recording (seconds) */
    clipEnd: number;
    /** Optional: notified when playback time changes */
    onTimeUpdate?: (time: number) => void;
  }

  let { projectId, recording, clipStart, clipEnd, onTimeUpdate }: Props = $props();

  // Cast to RecordingDetail for SpectrogramViewer (it only uses id, samplerate, duration)
  const recordingForViewer = $derived(recording as unknown as RecordingDetail);

  const clipDuration = $derived(clipEnd - clipStart);

  // Bounds = the clip region only
  const bounds = $derived<SpectrogramWindow>({
    time: { min: clipStart, max: clipEnd },
    freq: { min: 0, max: recording.samplerate / 2 },
  });

  // Initial viewport = the full clip (up to 20s).
  // We start with a placeholder and set the real value in an effect to avoid
  // capturing only the initial prop values in $state().
  let viewport = $state<SpectrogramWindow>({
    time: { min: 0, max: 1 },
    freq: { min: 0, max: 1 },
  });

  // Initialize viewport reactively so it always reflects the latest props.
  // Also sync when clip range or recording samplerate changes.
  $effect(() => {
    const initial = getInitialViewingWindow({
      startTime: clipStart,
      endTime: clipEnd,
      samplerate: recording.samplerate,
    });
    viewport = adjustWindowToBounds(initial, bounds);
  });

  let currentTime = $state(0);

  // Sync currentTime initial value to clipStart reactively
  $effect(() => {
    currentTime = clipStart;
  });
  let interactionMode = $state<InteractionMode>('idle');

  const spectrogramSettings = DEFAULT_SPECTROGRAM_SETTINGS;
  const audioSettings = DEFAULT_AUDIO_SETTINGS;

  const speedOptions = $derived(getSpeedOptions(recording.samplerate));
  const speed = $derived(audioSettings.speed);

  function handleViewportChange(newViewport: SpectrogramWindow) {
    viewport = adjustWindowToBounds(newViewport, bounds);
  }

  function handleSeek(time: number) {
    currentTime = Math.max(clipStart, Math.min(clipEnd, time));
  }

  function handleTimeUpdate(time: number) {
    currentTime = time;
    onTimeUpdate?.(time);
  }
</script>

<div class="clip-player">
  <SpectrogramViewer
    recording={recordingForViewer}
    {projectId}
    {spectrogramSettings}
    {viewport}
    {bounds}
    {currentTime}
    {interactionMode}
    onViewportChange={handleViewportChange}
    onSeek={handleSeek}
    onModeChange={(mode) => (interactionMode = mode)}
  />

  <div class="audio-player-wrapper">
    <AudioPlayer
      {projectId}
      recordingId={recording.id}
      duration={clipDuration}
      {speed}
      {speedOptions}
      {viewport}
      {bounds}
      seekTo={currentTime}
      onViewportChange={handleViewportChange}
      onTimeUpdate={handleTimeUpdate}
      onSeek={handleSeek}
    />
  </div>
</div>

<style>
  .clip-player {
    display: flex;
    flex-direction: column;
    gap: 0;
  }

  .audio-player-wrapper {
    border-top: 1px solid #e5e7eb;
    background: #ffffff;
  }

  :global(.dark) .audio-player-wrapper {
    background: #18181b;
    border-top-color: #3f3f46;
  }
</style>
