<script lang="ts">
  /**
   * ClipSpectrogramPlayer - lightweight spectrogram + audio player for a clip
   * (a time-bounded segment of a recording). Used by annotation pages where only
   * the clip region is displayed rather than the full recording.
   *
   * Internally manages viewport and bounds state so callers only need to
   * provide basic clip/recording metadata. The annotation editor layers an
   * interaction overlay on top of the spectrogram; to keep that overlay's
   * coordinate model in sync, this component:
   *   - owns `viewport` + `spectrogramSettings` as `$state`,
   *   - exposes the live `viewport` and `canvasWidth` OUTWARD via callbacks
   *     (`onViewportChange` / `onCanvasWidthChange`) — never `bind:`, to avoid
   *     a reactive write-back loop, and
   *   - accepts inbound viewport changes (overlay pan/zoom) via the exported
   *     `setViewport()` method, which clamps to the clip bounds.
   * Dataset-parity time/freq scale controls drive a relative viewport zoom.
   */
  import SpectrogramViewer from '$lib/components/audio/SpectrogramViewer.svelte';
  import AudioPlayer from '$lib/components/audio/AudioPlayer.svelte';
  import ScaleControls from '$lib/components/audio/ScaleControls.svelte';
  import ViewportToolbar from '$lib/components/audio/ViewportToolbar.svelte';
  import ViewportBar from '$lib/components/audio/ViewportBar.svelte';
  import type { RecordingDetail } from '$lib/types/data';
  import type {
    SpectrogramWindow,
    InteractionMode,
    SpectrogramSettings,
  } from '$lib/types/audio';
  import {
    DEFAULT_SPECTROGRAM_SETTINGS,
    DEFAULT_AUDIO_SETTINGS,
    getSpeedOptions,
  } from '$lib/types/audio';
  import {
    getInitialViewingWindow,
    adjustWindowToBounds,
    centerWindowOn,
  } from '$lib/utils/viewport';
  import { untrack } from 'svelte';

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
    /**
     * Optional: target playhead position in recording-ABSOLUTE seconds,
     * clamped to the clip range via `handleSeek`. Used by the annotation
     * editor for click-to-seek on the overlay. Leave undefined
     * (recording-detail) to keep prior behaviour.
     */
    seekTo?: number;
    /**
     * Optional: bump this counter to force a re-seek to `seekTo` even when the
     * target time is unchanged (e.g. clicking the same spot twice after
     * playback has moved on). Without it Svelte would dedupe the unchanged
     * `seekTo` value and skip the effect.
     */
    seekNonce?: number;
    /**
     * Optional: when true, mount the dataset-parity viewport controls
     * (time/freq scale sliders + Pan/Zoom/Annotate/Back/Reset toolbar) and
     * surface the live viewport + canvas width to the caller. Off by default
     * so existing call sites (recording-detail clip preview) are unchanged.
     */
    showViewportControls?: boolean;
    /** Optional: current annotation interaction mode (drives the toolbar UI). */
    annotationMode?: 'annotating' | 'panning' | 'zooming';
    /** Optional: notified when the mode toolbar requests a mode change. */
    onAnnotationModeChange?: (mode: 'annotating' | 'panning' | 'zooming') => void;
    /** Optional: notified when the live viewport changes (pan/zoom/scale/seek). */
    onViewportChange?: (viewport: SpectrogramWindow) => void;
    /** Optional: notified when the spectrogram canvas width (CSS px) changes. */
    onCanvasWidthChange?: (width: number) => void;
    /** Optional: notified when the clip bounds change (segment switch). */
    onBoundsChange?: (bounds: SpectrogramWindow) => void;
    /**
     * Optional: notified with the vertical offset (CSS px) of the spectrogram
     * canvas from the top of the clip player. The annotation overlay uses this
     * to align itself below the viewport-controls toolbar row.
     */
    onSpectrogramTopChange?: (top: number) => void;
    /** Optional: notified when playback time changes */
    onTimeUpdate?: (time: number) => void;
  }

  let {
    projectId,
    recording,
    clipStart,
    clipEnd,
    seekTo,
    seekNonce,
    showViewportControls = false,
    annotationMode = 'annotating',
    onAnnotationModeChange,
    onViewportChange,
    onCanvasWidthChange,
    onBoundsChange,
    onSpectrogramTopChange,
    onTimeUpdate,
  }: Props = $props();

  // Cast to RecordingDetail for SpectrogramViewer (it only uses id, samplerate, duration)
  const recordingForViewer = $derived(recording as unknown as RecordingDetail);

  const clipDuration = $derived(clipEnd - clipStart);

  // Bounds = the clip region only
  const bounds = $derived<SpectrogramWindow>({
    time: { min: clipStart, max: clipEnd },
    freq: { min: 0, max: recording.samplerate / 2 },
  });

  // Surface bounds changes outward (clip/segment switch) so the overlay clamps
  // pan/zoom against the right region.
  $effect(() => {
    onBoundsChange?.(bounds);
  });

  // Initial viewport = the full clip (up to 20s).
  // We start with a placeholder and set the real value in an effect to avoid
  // capturing only the initial prop values in $state().
  let viewport = $state<SpectrogramWindow>({
    time: { min: 0, max: 1 },
    freq: { min: 0, max: 1 },
  });

  // Surface the live viewport outward via a callback (NOT `bind:`). The caller
  // mirrors this into its overlay coordinate model; it must never write back
  // to this `viewport` directly — inbound changes go through `setViewport()`.
  $effect(() => {
    onViewportChange?.(viewport);
  });

  // Track previous scale values so a slider change applies a RELATIVE zoom
  // about the current viewport centre (mirrors the recording-detail page).
  let prevTimeScale = $state(untrack(() => DEFAULT_SPECTROGRAM_SETTINGS.time_scale));
  let prevFreqScale = $state(untrack(() => DEFAULT_SPECTROGRAM_SETTINGS.freq_scale));

  // Initialize viewport reactively so it always reflects the latest props.
  // Also sync when clip range or recording samplerate changes. Resetting the
  // scale baseline here keeps the slider-driven zoom consistent across
  // segment switches.
  $effect(() => {
    const initial = getInitialViewingWindow({
      startTime: clipStart,
      endTime: clipEnd,
      samplerate: recording.samplerate,
    });
    viewport = adjustWindowToBounds(initial, untrack(() => bounds));
  });

  let currentTime = $state(0);

  // Sync currentTime initial value to clipStart reactively.
  // Intentionally segment-switch-scoped: this depends ONLY on clipStart (the
  // clip bound), so it re-runs to reset the playhead when the user switches to
  // a different segment — not on every currentTime update during playback.
  $effect(() => {
    currentTime = clipStart;
  });

  // Parent-driven seek (annotation editor click-to-seek). When the parent
  // requests a seek (new `seekTo` value, or a bumped `seekNonce` for a repeat
  // request at the same spot), route it through the existing clamping path so
  // the playhead respects the clip boundaries. Reading `seekNonce` registers
  // it as a dependency so repeated identical-target clicks still re-seek.
  // Depends ONLY on seek inputs — not on internal currentTime updates during
  // playback.
  $effect(() => {
    void seekNonce;
    const target = seekTo;
    if (target === undefined) return;
    handleSeek(target);
  });

  // The dataset viewer's own interaction never fires on the annotation page
  // (the overlay sits above it), so we pin the viewer to a neutral mode. The
  // real annotation mode lives in the parent via `annotationMode`.
  let interactionMode = $state<InteractionMode>('panning');

  // Spectrogram settings as $state so the time/freq scale sliders can drive a
  // relative viewport zoom (mirrors the recording-detail page).
  let spectrogramSettings = $state<SpectrogramSettings>({ ...DEFAULT_SPECTROGRAM_SETTINGS });

  // Viewport history for the toolbar Back button.
  let viewportHistory: SpectrogramWindow[] = [];

  // Live spectrogram canvas width (CSS px). Bound from the outer wrapper which
  // shares the 100%-width SpectrogramViewer container width.
  let canvasWidth = $state(0);
  $effect(() => {
    onCanvasWidthChange?.(canvasWidth);
  });

  // Height (CSS px) of the viewport-controls toolbar row, when shown. The
  // spectrogram canvas begins right below it, so the overlay must offset by
  // this amount to stay aligned. Measured via `bind:clientHeight`.
  let toolbarRowHeight = $state(0);
  $effect(() => {
    onSpectrogramTopChange?.(showViewportControls ? toolbarRowHeight : 0);
  });

  const speedOptions = $derived(getSpeedOptions(recording.samplerate));
  // Local playback speed, seeded from defaults. Updated when the user picks a
  // speed in the AudioPlayer menu so the selection persists for this clip.
  let speed = $state(DEFAULT_AUDIO_SETTINGS.speed);

  function handleSpeedChange(newSpeed: number) {
    speed = newSpeed;
  }

  function handleViewportChange(newViewport: SpectrogramWindow) {
    viewport = adjustWindowToBounds(newViewport, bounds);
  }

  /**
   * Inbound viewport setter for the annotation overlay (pan/zoom). Exported so
   * the parent pushes changes here instead of `bind:`-ing the viewport, which
   * would create a reactive write-back loop. Always clamped to the clip bounds.
   */
  export function setViewport(newViewport: SpectrogramWindow) {
    viewport = adjustWindowToBounds(newViewport, bounds);
  }

  /** Save the current viewport onto the history stack (before pan/zoom). */
  export function saveViewport() {
    viewportHistory = [...viewportHistory, { ...viewport }];
  }

  function handleViewportBack() {
    if (viewportHistory.length > 0) {
      const prev = viewportHistory[viewportHistory.length - 1] as SpectrogramWindow;
      viewportHistory = viewportHistory.slice(0, -1);
      viewport = adjustWindowToBounds(prev, bounds);
    }
  }
  /** Public alias so the parent can wire a keyboard `B` shortcut. */
  export function back() {
    handleViewportBack();
  }

  function handleViewportReset() {
    viewportHistory = [];
    spectrogramSettings = { ...spectrogramSettings, time_scale: 1.0, freq_scale: 1.0 };
    prevTimeScale = 1.0;
    prevFreqScale = 1.0;
    viewport = adjustWindowToBounds(
      getInitialViewingWindow({
        startTime: clipStart,
        endTime: clipEnd,
        samplerate: recording.samplerate,
      }),
      bounds,
    );
  }

  function handleSeek(time: number) {
    currentTime = Math.max(clipStart, Math.min(clipEnd, time));
  }

  function handleTimeUpdate(time: number) {
    currentTime = time;
    onTimeUpdate?.(time);
  }

  // When time_scale or freq_scale changes, zoom the viewport relative to its
  // current size (not the full clip bounds). Mirrors the recording-detail page.
  $effect(() => {
    const timeScale = spectrogramSettings.time_scale;
    const freqScale = spectrogramSettings.freq_scale;

    const currentViewport = untrack(() => viewport);
    const currentBounds = untrack(() => bounds);
    const oldTimeScale = untrack(() => prevTimeScale);
    const oldFreqScale = untrack(() => prevFreqScale);

    if (timeScale === oldTimeScale && freqScale === oldFreqScale) return;

    const currentDuration = currentViewport.time.max - currentViewport.time.min;
    const currentBandwidth = currentViewport.freq.max - currentViewport.freq.min;

    const newDuration = currentDuration * (oldTimeScale / timeScale);
    const newBandwidth = currentBandwidth * (oldFreqScale / freqScale);

    const timeCenter = (currentViewport.time.min + currentViewport.time.max) / 2;
    const freqCenter = (currentViewport.freq.min + currentViewport.freq.max) / 2;

    const proposed: SpectrogramWindow = {
      time: { min: timeCenter - newDuration / 2, max: timeCenter + newDuration / 2 },
      freq: { min: freqCenter - newBandwidth / 2, max: freqCenter + newBandwidth / 2 },
    };

    viewport = adjustWindowToBounds(proposed, currentBounds);

    untrack(() => {
      prevTimeScale = timeScale;
      prevFreqScale = freqScale;
    });
  });

  // Optional: when seeking outside the current viewport, recentre so the
  // playhead stays visible. Only relevant when viewport controls are active.
  // Depends ONLY on the seek inputs — viewport/bounds are read via untrack so
  // the write-back to `viewport` never re-triggers this effect.
  $effect(() => {
    void seekNonce;
    const target = seekTo;
    if (target === undefined) return;
    if (!showViewportControls) return;
    const time = Math.max(clipStart, Math.min(clipEnd, target));
    const currentViewport = untrack(() => viewport);
    if (time < currentViewport.time.min || time > currentViewport.time.max) {
      viewport = adjustWindowToBounds(
        centerWindowOn(currentViewport, { time }),
        untrack(() => bounds),
      );
    }
  });
</script>

<div class="clip-player" bind:clientWidth={canvasWidth}>
  {#if showViewportControls}
    <div class="viewport-toolbar-row" bind:clientHeight={toolbarRowHeight}>
      <ViewportToolbar
        mode={interactionMode}
        showAnnotate
        annotateActive={annotationMode === 'annotating'}
        panActive={annotationMode === 'panning'}
        zoomActive={annotationMode === 'zooming'}
        onAnnotate={() => onAnnotationModeChange?.('annotating')}
        onPan={() => onAnnotationModeChange?.('panning')}
        onZoom={() => onAnnotationModeChange?.('zooming')}
        onBack={handleViewportBack}
        onReset={handleViewportReset}
      />
      <div class="scale-controls-wrapper">
        <ScaleControls
          settings={spectrogramSettings}
          onChange={(s) => (spectrogramSettings = s)}
        />
      </div>
    </div>
  {/if}

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
      samplerate={recording.samplerate}
      {viewport}
      {bounds}
      {clipStart}
      {clipEnd}
      seekTo={currentTime}
      onViewportChange={handleViewportChange}
      onTimeUpdate={handleTimeUpdate}
      onSeek={handleSeek}
      onSpeedChange={handleSpeedChange}
    />
  </div>

  {#if showViewportControls}
    <!--
      Minimap/scrollbar (dataset parity). Rendered BELOW the audio player so it
      sits outside the annotation overlay's covered area (the overlay only
      covers the spectrogram height). Does NOT affect `onSpectrogramTopChange`.
    -->
    <div class="viewport-bar-row">
      <ViewportBar
        {viewport}
        {bounds}
        onViewportChange={handleViewportChange}
        onViewportSave={saveViewport}
      />
    </div>
  {/if}
</div>

<style>
  .clip-player {
    display: flex;
    flex-direction: column;
    gap: 0;
  }

  /*
   * Chrome parity with the dataset spectrogram: the toolbar row is transparent
   * and borderless (the enclosing section already supplies a border), matching
   * the dataset's airy `.toolbar-row`.
   */
  .viewport-toolbar-row {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
    padding: 0.375rem 0.5rem;
  }

  .scale-controls-wrapper {
    margin-left: auto;
  }

  /* Airy player row (dataset parity): keep only the top divider. */
  .audio-player-wrapper {
    border-top: 1px solid #e5e7eb;
  }

  :global(.dark) .audio-player-wrapper {
    border-top-color: #3f3f46;
  }

  .viewport-bar-row {
    padding: 0.375rem 0.5rem 0.25rem;
  }
</style>
