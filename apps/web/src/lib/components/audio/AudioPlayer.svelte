<script lang="ts">
  import { onDestroy, untrack } from 'svelte';
  import {
    getAuthenticatedRecordingMediaUrl,
    getPlaybackUrl,
  } from '$lib/api/recordings';
  import type { SpeedOption } from '$lib/types/audio';
  import { HIGHEST_PLAYBACK_SAMPLERATE } from '$lib/types/audio';
  import type { SpectrogramWindow } from '$lib/types/audio';
  import {
    adjustWindowToBounds,
    centerWindowOn,
  } from '$lib/utils/viewport';
  import * as m from '$lib/paraglide/messages';

  interface Props {
    projectId: string;
    recordingId: string;
    duration: number;
    speed: number;
    speedOptions: SpeedOption[];
    viewport: SpectrogramWindow;
    bounds: SpectrogramWindow;
    /**
     * Native sample rate of the recording (Hz). Used to decide whether the
     * playback speed is applied client-side (audioEl.playbackRate) or
     * server-side (re-fetch with a `speed` query param). Ultrasonic recordings
     * require server-side time-expansion to become audible.
     */
    samplerate?: number;
    /**
     * Opt-in CLIP mode. When both `clipStart` and `clipEnd` are provided the
     * player requests a clip-bounded audio source (`?start&end`) from the
     * backend, so the `<audio>` element loads only the clip and its media
     * duration equals the clip length. The seek slider and time readout then
     * operate in CLIP-LOCAL seconds (`0 .. clipDuration`), while all viewport /
     * spectrogram interactions keep working in recording-ABSOLUTE seconds.
     *
     * When these are left `undefined` (the recording-detail use case) the
     * player loads the full recording and behaves exactly as before (the
     * ultrasonic real-time / `effectiveDuration` behaviour from PR #141 is
     * unchanged).
     */
    clipStart?: number;
    clipEnd?: number;
    /**
     * When this value changes, the audio element will seek to this time.
     * In clip mode this is interpreted in recording-ABSOLUTE seconds (the
     * spectrogram's native domain) and converted to clip-local internally.
     */
    seekTo?: number;
    onViewportChange?: (viewport: SpectrogramWindow) => void;
    /** Reports the current playback time. In clip mode this is recording-ABSOLUTE seconds. */
    onTimeUpdate?: (time: number) => void;
    /** Reports a user seek. In clip mode this is recording-ABSOLUTE seconds. */
    onSeek?: (time: number) => void;
    /** Invoked when the user picks a playback speed from the speed menu. */
    onSpeedChange?: (speed: number) => void;
  }

  let {
    projectId,
    recordingId,
    duration,
    speed,
    speedOptions,
    viewport,
    bounds,
    samplerate,
    clipStart,
    clipEnd,
    seekTo,
    onViewportChange,
    onTimeUpdate,
    onSeek,
    onSpeedChange,
  }: Props = $props();

  // Clip mode is active only when an explicit, valid clip window is provided.
  // The audio element is clip-bounded, so `currentTime` is already clip-local
  // (0 .. clipDuration); we only need the offset to translate to/from the
  // recording-absolute domain used by the spectrogram + viewport.
  const isClipMode = $derived(
    clipStart !== undefined &&
      clipEnd !== undefined &&
      clipEnd > clipStart
  );
  /** Offset added to clip-local time to obtain recording-absolute time. */
  const clipOffset = $derived(isClipMode ? (clipStart as number) : 0);
  /** Convert a clip-local time to the recording-absolute domain. */
  function toAbsolute(localTime: number): number {
    return localTime + clipOffset;
  }
  /** Convert a recording-absolute time to the clip-local domain. */
  function toLocal(absoluteTime: number): number {
    return absoluteTime - clipOffset;
  }

  // Audio element reference
  let audioEl: HTMLAudioElement | undefined = $state();

  // Audio state
  let currentTime = $state(0);
  let isPlaying = $state(false);
  let loop = $state(false);
  let volume = $state(1);
  let _isDragging = $state(false);
  let lockPlay = false;
  let animFrameId: number | null = null;

  // Actual duration of the loaded media, populated from the audio element once
  // metadata is known. This is authoritative for the seek slider because it
  // accounts for backend resampling / time-expansion (the static `duration`
  // prop only reflects the original recording length). Falls back to the prop
  // until the media reports a finite duration.
  let mediaDuration = $state<number | null>(null);
  const effectiveDuration = $derived(
    mediaDuration !== null && isFinite(mediaDuration) && mediaDuration > 0
      ? mediaDuration
      : duration
  );

  // Whether the media is loaded enough to seek (HAVE_CURRENT_DATA or better).
  let canSeek = $state(false);

  // Ultrasonic recordings cannot be sped/slowed purely client-side: shifting an
  // inaudible spectrum into the audible range requires the backend to
  // time-expand and resample the audio. We detect this from the native sample
  // rate and, for ultrasonic sources, send the chosen speed to the playback
  // endpoint instead of using audioEl.playbackRate.
  const useServerSpeed = $derived(
    samplerate !== undefined && samplerate > HIGHEST_PLAYBACK_SAMPLERATE
  );

  let _audioLoadError = $state(false);

  // Track whether we have already attempted to re-issue a media token for the
  // current audio element error, so we never enter an infinite retry loop.
  let hasRetriedAfterMediaTokenRefresh = false;
  let audioSrcRequestId = 0;

  // Speed dropdown state
  let showSpeedMenu = $state(false);

  // Build the playback URL with a scoped media token. The native <audio>
  // element still owns Range requests and buffering; the full access JWT never
  // appears in the URL.
  //
  // For ultrasonic sources we thread the selected speed into the playback
  // endpoint so the backend time-expands the audio (making it audible). For
  // normal sources speed is applied client-side via audioEl.playbackRate, so
  // the URL omits it and the file does not need re-fetching on speed change.
  async function buildAudioSrc(
    pid: string,
    rid: string,
    serverSpeed?: number
  ): Promise<string> {
    // In clip mode the backend already supports trimming via `start`/`end`, so
    // the streamed media is bounded to the clip and reports a clip-length
    // duration. The recording-detail (full-file) call site leaves the clip
    // props undefined, producing the original full-recording URL.
    const params: Parameters<typeof getPlaybackUrl>[2] = {};
    if (serverSpeed !== undefined && serverSpeed !== 1) {
      params.speed = serverSpeed;
    }
    if (isClipMode) {
      params.start = clipStart;
      params.end = clipEnd;
    }
    const fullUrl = getPlaybackUrl(pid, rid, params);
    return getAuthenticatedRecordingMediaUrl(pid, rid, 'playback', fullUrl);
  }

  // When projectId or recordingId changes, update the audio element source.
  // Keep the current playback position and playing state if possible.
  $effect(() => {
    const _projectId = projectId;
    const _recordingId = recordingId;
    const _audioEl = audioEl;
    // Track the server-side speed inputs so ultrasonic speed changes re-request
    // the backend-time-expanded audio. For non-ultrasonic sources `useServerSpeed`
    // is false and the URL ignores `speed`, so changing speed must NOT re-run this
    // effect (it would needlessly re-fetch a media token and reset the element).
    // We therefore only treat `speed` as a tracked dependency when the speed is
    // applied server-side; otherwise we read it untracked.
    const _useServerSpeed = useServerSpeed;
    const _speed = _useServerSpeed ? speed : untrack(() => speed);

    // In clip mode the playback URL is bounded by `start`/`end`, so a change in
    // the clip window must re-fetch a freshly trimmed source. Track these so a
    // segment switch reloads the correct clip. (Full-file mode leaves them
    // undefined; reading them is harmless and keeps the dependency explicit.)
    const _isClipMode = isClipMode;
    void clipStart;
    void clipEnd;

    if (!_projectId || !_recordingId || !_audioEl) return;

    // `currentTime` and `isPlaying` are read untracked so time updates during
    // playback do not re-run this effect and reset audio src repeatedly.
    // In clip mode the media is reloaded as a fresh clip, so playback restarts
    // from the clip start (local 0); in full-file mode we preserve the position.
    const savedTime = _isClipMode ? 0 : untrack(() => currentTime);
    const wasPlaying = untrack(() => isPlaying);

    _audioLoadError = false;
    // The newly assigned src has no metadata yet; gate seeking until it loads.
    canSeek = false;
    mediaDuration = null;
    // In clip mode the fresh clip starts at local 0; reset the slider state so
    // the thumb/progress reflect the new clip immediately (before metadata).
    if (_isClipMode) {
      untrack(() => {
        currentTime = 0;
      });
    }
    // Reset the retry flag whenever we load a new recording
    hasRetriedAfterMediaTokenRefresh = false;
    const requestId = ++audioSrcRequestId;

    void (async () => {
      try {
        const src = await buildAudioSrc(
          _projectId,
          _recordingId,
          _useServerSpeed ? _speed : undefined
        );
        if (requestId !== audioSrcRequestId || audioEl !== _audioEl) return;

        // Set src directly; the browser handles Range requests and buffering.
        _audioEl.src = src;
        _audioEl.currentTime = savedTime;

        if (wasPlaying) {
          _audioEl.play().catch(() => {});
        }
      } catch {
        if (requestId !== audioSrcRequestId || audioEl !== _audioEl) return;
        _audioLoadError = true;
      }
    })();
  });

  // Sync playbackRate whenever the speed prop changes — but ONLY for sources
  // where speed is handled client-side. For ultrasonic sources the backend has
  // already time-expanded the audio, so we keep playbackRate at 1 and let the
  // re-fetched media play at its natural (now-audible) rate.
  $effect(() => {
    if (!audioEl) return;
    audioEl.playbackRate = useServerSpeed ? 1 : speed;
  });

  // When the parent requests a seek (e.g., after a spectrogram click), apply it
  // to the audio element.  The threshold of 0.05 s prevents this from firing on
  // every time-update tick during normal playback.
  $effect(() => {
    if (seekTo === undefined || !audioEl) return;
    // `seekTo` is recording-absolute; the clip-bounded media element is
    // clip-local, so translate before writing currentTime. In full-file mode
    // the offset is 0 and this is a no-op.
    const localSeek = toLocal(seekTo);
    if (Math.abs(audioEl.currentTime - localSeek) > 0.05) {
      audioEl.currentTime = localSeek;
      // Keep local state in sync so the progress bar reflects the new position
      // immediately, even before the next animation frame fires.
      untrack(() => {
        currentTime = localSeek;
      });
    }
  });

  function startTimeTracking() {
    stopTimeTracking();
    function tick() {
      if (!audioEl) return;
      if (!audioEl.paused) {
        currentTime = audioEl.currentTime;
        handleTimeUpdate(currentTime);
        animFrameId = requestAnimationFrame(tick);
      }
    }
    animFrameId = requestAnimationFrame(tick);
  }

  function stopTimeTracking() {
    if (animFrameId !== null) {
      cancelAnimationFrame(animFrameId);
      animFrameId = null;
    }
  }

  function handleTimeUpdate(localTime: number) {
    // `localTime` is the (clip-local in clip mode) media position. The
    // spectrogram, viewport and consumer callbacks all speak the
    // recording-absolute domain, so translate once here.
    const time = toAbsolute(localTime);
    onTimeUpdate?.(time);

    // Auto-center viewport during playback
    const { min, max } = viewport.time;
    const viewDuration = max - min;

    if (time >= max - 0.1 * viewDuration) {
      const newVp = adjustWindowToBounds(
        centerWindowOn(viewport, { time: time + 0.4 * viewDuration }),
        bounds
      );
      onViewportChange?.(newVp);
    } else if (time <= min + 0.1 * viewDuration) {
      const newVp = adjustWindowToBounds(
        centerWindowOn(viewport, { time: time - 0.4 * viewDuration }),
        bounds
      );
      onViewportChange?.(newVp);
    }
  }

  function handlePlay() {
    if (lockPlay || !audioEl) return;
    lockPlay = true;
    const promise = audioEl.play();
    if (promise) {
      promise
        .then(() => {
          isPlaying = true;
          lockPlay = false;
          startTimeTracking();
        })
        .catch(() => {
          lockPlay = false;
        });
    } else {
      isPlaying = true;
      lockPlay = false;
      startTimeTracking();
    }
  }

  function handlePause() {
    if (!audioEl) return;
    audioEl.pause();
    isPlaying = false;
    stopTimeTracking();
  }

  function togglePlay() {
    if (isPlaying) {
      handlePause();
    } else {
      handlePlay();
    }
  }

  // True once the media reports a finite, seekable duration. Until then the
  // slider is a no-op so we never write an out-of-range currentTime.
  function isSeekable(): boolean {
    if (!audioEl) return false;
    return (
      audioEl.readyState >= 2 &&
      isFinite(audioEl.duration) &&
      audioEl.duration > 0
    );
  }

  function handleSliderInput(e: Event) {
    if (!isSeekable()) return;
    const target = e.target as HTMLInputElement;
    currentTime = parseFloat(target.value);
    _isDragging = true;
  }

  function handleSliderChange() {
    if (!audioEl || !isSeekable()) {
      _isDragging = false;
      return;
    }
    // Clamp to the actual media duration before writing currentTime. The
    // slider operates in the media's own (clip-local in clip mode) domain.
    const clamped = Math.max(0, Math.min(currentTime, audioEl.duration));
    currentTime = clamped;
    audioEl.currentTime = clamped;
    // Consumer callbacks + viewport math use the recording-absolute domain.
    const absolute = toAbsolute(clamped);
    onSeek?.(absolute);
    onViewportChange?.(
      adjustWindowToBounds(centerWindowOn(viewport, { time: absolute }), bounds)
    );
    _isDragging = false;
  }

  // Refresh the cached media duration / seekable state from the audio element.
  // Driven by loadedmetadata + durationchange so the slider always reflects the
  // real loaded media (including resampled / time-expanded ultrasonic audio).
  function refreshMediaMetadata() {
    if (!audioEl) return;
    mediaDuration =
      isFinite(audioEl.duration) && audioEl.duration > 0 ? audioEl.duration : null;
    canSeek = isSeekable();
  }

  function handleVolumeChange(e: Event) {
    const target = e.target as HTMLInputElement;
    volume = parseFloat(target.value);
    if (audioEl) audioEl.volume = volume;
  }

  function toggleLoop() {
    loop = !loop;
    if (audioEl) audioEl.loop = loop;
  }

  function onAudioEnded() {
    isPlaying = false;
    currentTime = 0;
    stopTimeTracking();
  }

  function onAudioPlay() {
    hasRetriedAfterMediaTokenRefresh = false;
    _audioLoadError = false;
    isPlaying = true;
    startTimeTracking();
  }

  function onAudioPause() {
    isPlaying = false;
    stopTimeTracking();
  }

  function onAudioCanPlay() {
    hasRetriedAfterMediaTokenRefresh = false;
    _audioLoadError = false;
    refreshMediaMetadata();
  }

  function onAudioLoadedMetadata() {
    refreshMediaMetadata();
  }

  function onAudioDurationChange() {
    refreshMediaMetadata();
  }

  async function onAudioError() {
    // When the audio element fails, the MediaError code is available on
    // audioEl.error.  Code 4 (MEDIA_ERR_SRC_NOT_SUPPORTED) is what browsers
    // surface for HTTP-level errors such as 401 Unauthorized.
    //
    // Attempt media-token re-issue exactly once. If it succeeds we rebuild the
    // src and resume from where we left off. If it fails (or we already retried
    // once), fall through to the visible error state.
    const mediaErrCode = audioEl?.error?.code ?? 0;
    const likelyAuthError = mediaErrCode === MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED ||
                            mediaErrCode === MediaError.MEDIA_ERR_NETWORK;

    if (likelyAuthError && !hasRetriedAfterMediaTokenRefresh) {
      hasRetriedAfterMediaTokenRefresh = true;
      try {
        // Rebuild with the SAME arguments as the normal src effect so the two
        // paths can't drift: the server-speed param (so ultrasonic/server-speed
        // mode keeps its time-expansion) plus the clip start/end (preserved via
        // the buildAudioSrc closure). Passing `useServerSpeed ? speed : undefined`
        // mirrors the main effect exactly; non-clip behaviour is unchanged.
        const src = await buildAudioSrc(
          projectId,
          recordingId,
          useServerSpeed ? speed : undefined
        );
        // Rebuild the src with a freshly issued scoped media token.
        if (audioEl && projectId && recordingId) {
          const savedTime = audioEl.currentTime;
          const wasPlaying = isPlaying;
          audioEl.src = src;
          audioEl.currentTime = savedTime;
          if (wasPlaying) {
            audioEl.play().catch(() => {});
          }
        }
        // Do NOT set audioLoadError — give the retry a chance to succeed
        return;
      } catch {
        // Media-token issue failed; fall through to show the error state.
      }
    }

    _audioLoadError = true;
    isPlaying = false;
    stopTimeTracking();
  }

  // Expose seek for external control (parent can call this).
  // `time` is recording-ABSOLUTE seconds, matching the rest of the public
  // boundary (seekTo, onSeek, onTimeUpdate). The clip-bounded media element is
  // clip-local, so translate via toLocal before writing currentTime. In
  // full-file mode the offset is 0 and toLocal is the identity.
  export function seek(time: number) {
    const local = toLocal(time);
    currentTime = local;
    if (audioEl) {
      audioEl.currentTime = local;
    }
  }

  export function play() {
    handlePlay();
  }

  export function pause() {
    handlePause();
  }

  function formatTime(seconds: number): string {
    if (!isFinite(seconds)) return '0:00.00';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    const ms = Math.floor((seconds % 1) * 100);
    return `${mins}:${secs.toString().padStart(2, '0')}.${ms.toString().padStart(2, '0')}`;
  }

  // Global keyboard shortcut: Space = toggle play
  function handleKeyDown(e: KeyboardEvent) {
    if (e.code === 'Space' && e.target === document.body) {
      e.preventDefault();
      togglePlay();
    }
  }

  onDestroy(() => {
    stopTimeTracking();
    // Clear audio source to stop any in-progress network requests
    if (audioEl) {
      audioEl.pause();
      audioEl.src = '';
      audioEl.load();
    }
  });
</script>

<svelte:window onkeydown={handleKeyDown} />

<div class="player flex flex-row gap-2 items-center px-3 py-2 max-w-max rounded-md border border-stone-300 bg-stone-100 dark:border-stone-600 dark:bg-stone-700">
  <!-- Play/Pause button -->
  <button
    type="button"
    class="player-btn text-stone-600 hover:text-stone-800 dark:text-stone-400 dark:hover:text-stone-200"
    onclick={togglePlay}
    aria-label={isPlaying ? 'Pause' : 'Play'}
  >
    {#if isPlaying}
      <!-- Pause icon -->
      <svg class="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
        <rect x="6" y="4" width="4" height="16" rx="1" />
        <rect x="14" y="4" width="4" height="16" rx="1" />
      </svg>
    {:else}
      <!-- Play icon -->
      <svg class="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
        <polygon points="5 3 19 12 5 21 5 3" />
      </svg>
    {/if}
  </button>

  <!-- Loop button -->
  <button
    type="button"
    class="player-btn {loop
      ? 'text-primary-500 hover:text-primary-700 dark:hover:text-primary-300'
      : 'text-stone-600 hover:text-stone-800 dark:text-stone-400 dark:hover:text-stone-200'}"
    onclick={toggleLoop}
    aria-label={loop ? 'Disable loop' : 'Enable loop'}
    title="Loop"
  >
    <!-- Loop icon -->
    <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <polyline points="17 1 21 5 17 9" />
      <path d="M3 11V9a4 4 0 0 1 4-4h14" />
      <polyline points="7 23 3 19 7 15" />
      <path d="M21 13v2a4 4 0 0 1-4 4H3" />
    </svg>
  </button>

  <!-- Timeline slider -->
  <div class="timeline ml-2 w-48">
    <div class="flex justify-between text-xs text-stone-500 dark:text-stone-400 mb-0.5 font-mono">
      <span>{formatTime(currentTime)}</span>
      <span>{formatTime(effectiveDuration)}</span>
    </div>
    <div
      class="relative w-full h-3 flex items-center {canSeek
        ? 'cursor-pointer'
        : 'cursor-progress opacity-60'}"
    >
      <div class="absolute w-full h-1 rounded-full bg-stone-300 dark:bg-stone-600">
        <div
          class="h-1 bg-primary-500 rounded-full dark:bg-primary-400"
          style="width: {effectiveDuration > 0
            ? Math.min((currentTime / effectiveDuration) * 100, 100)
            : 0}%"
        ></div>
      </div>
      <input
        type="range"
        min="0"
        max={effectiveDuration}
        step="0.01"
        value={currentTime}
        disabled={!canSeek}
        oninput={handleSliderInput}
        onchange={handleSliderChange}
        class="timeline-input absolute w-full opacity-0 h-3 {canSeek
          ? 'cursor-pointer'
          : 'cursor-progress'}"
        aria-label={m.audio_player_seek_position()}
      />
      <!-- Thumb indicator -->
      <div
        class="absolute w-3 h-3 bg-primary-500 rounded-full shadow pointer-events-none"
        style="left: calc({effectiveDuration > 0
          ? Math.min((currentTime / effectiveDuration) * 100, 100)
          : 0}% - 6px)"
      ></div>
    </div>
  </div>

  <!-- Speed selector -->
  <div class="relative">
    <button
      type="button"
      class="player-btn flex items-center gap-1 text-stone-600 hover:text-stone-800 dark:text-stone-400 dark:hover:text-stone-200 text-xs font-mono"
      onclick={() => (showSpeedMenu = !showSpeedMenu)}
      aria-label={m.audio_player_playback_speed()}
    >
      <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
      </svg>
      <span>{speed}x</span>
      <svg class="w-3 h-3" viewBox="0 0 24 24" fill="currentColor">
        <path d="M7 10l5 5 5-5z" />
      </svg>
    </button>

    {#if showSpeedMenu}
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div
        class="speed-menu absolute bottom-full mb-1 left-0 bg-stone-50 dark:bg-stone-700 border border-stone-200 dark:border-stone-600 rounded-md shadow-lg overflow-hidden z-50 min-w-16"
        onmouseleave={() => (showSpeedMenu = false)}
      >
        {#each speedOptions as option}
          <button
            type="button"
            aria-pressed={speed === option.value}
            class="block w-full px-3 py-1.5 text-left text-sm font-mono hover:bg-primary-100 dark:hover:bg-primary-900 {speed === option.value
              ? 'text-primary-600 dark:text-primary-400 font-semibold'
              : 'text-stone-700 dark:text-stone-300'}"
            onclick={() => {
              onSpeedChange?.(option.value);
              showSpeedMenu = false;
            }}
          >
            {option.label}
          </button>
        {/each}
      </div>
    {/if}
  </div>

  <!-- Volume control -->
  <div class="flex items-center gap-1.5">
    <svg class="w-4 h-4 text-stone-500 dark:text-stone-400 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
      {#if volume > 0.5}
        <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
        <path d="M19.07 4.93a10 10 0 0 1 0 14.14" />
      {:else if volume > 0}
        <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
      {/if}
    </svg>
    <input
      type="range"
      min="0"
      max="1"
      step="0.05"
      value={volume}
      oninput={handleVolumeChange}
      class="w-16 h-1 cursor-pointer accent-primary-500"
      aria-label="Volume"
    />
  </div>

  <!-- Hidden audio element: src is set reactively via $effect above -->
  <!-- preload="auto" tells the browser to buffer ahead, preventing stuttered playback -->
  <audio
    bind:this={audioEl}
    preload="auto"
    oncanplay={onAudioCanPlay}
    onloadedmetadata={onAudioLoadedMetadata}
    ondurationchange={onAudioDurationChange}
    onplay={onAudioPlay}
    onpause={onAudioPause}
    onended={onAudioEnded}
    onerror={onAudioError}
  ></audio>
</div>

<style>
  .player-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    border: none;
    background: transparent;
    cursor: pointer;
    padding: 0.25rem;
    border-radius: 9999px;
    transition: color 0.15s;
    flex-shrink: 0;
  }

  .player-btn:focus-visible {
    outline: 2px solid rgb(var(--primary-500));
    outline-offset: 2px;
  }

  .timeline-input::-webkit-slider-thumb {
    opacity: 0;
  }

  .timeline-input::-moz-range-thumb {
    opacity: 0;
  }

  .speed-menu {
    white-space: nowrap;
  }
</style>
