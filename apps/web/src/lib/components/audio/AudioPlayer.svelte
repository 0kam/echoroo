<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { getPlaybackUrl } from '$lib/api/recordings';
  import type { SpeedOption } from '$lib/types/audio';
  import type { SpectrogramWindow } from '$lib/types/audio';
  import {
    adjustWindowToBounds,
    centerWindowOn,
  } from '$lib/utils/viewport';

  interface Props {
    projectId: string;
    recordingId: string;
    duration: number;
    speed: number;
    speedOptions: SpeedOption[];
    viewport: SpectrogramWindow;
    bounds: SpectrogramWindow;
    onViewportChange?: (viewport: SpectrogramWindow) => void;
    onTimeUpdate?: (time: number) => void;
    onSeek?: (time: number) => void;
  }

  let {
    projectId,
    recordingId,
    duration,
    speed,
    speedOptions,
    viewport,
    bounds,
    onViewportChange,
    onTimeUpdate,
    onSeek,
  }: Props = $props();

  // Audio element reference
  let audioEl: HTMLAudioElement | undefined = $state();

  // Audio state
  let currentTime = $state(0);
  let isPlaying = $state(false);
  let loop = $state(false);
  let volume = $state(1);
  let isDragging = $state(false);
  let lockPlay = false;
  let animFrameId: number | null = null;

  // Speed dropdown state
  let showSpeedMenu = $state(false);

  let audioUrl = $derived(getPlaybackUrl(projectId, recordingId, { speed }));

  // When URL changes (speed change), reload audio
  $effect(() => {
    if (!audioEl) return;
    const wasPlaying = isPlaying;
    const savedTime = currentTime;
    audioEl.src = audioUrl;
    audioEl.currentTime = savedTime;
    if (wasPlaying) {
      audioEl.play().catch(() => {});
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

  function handleTimeUpdate(time: number) {
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

  function handleSliderInput(e: Event) {
    const target = e.target as HTMLInputElement;
    currentTime = parseFloat(target.value);
    isDragging = true;
  }

  function handleSliderChange() {
    if (!audioEl) return;
    audioEl.currentTime = currentTime;
    onSeek?.(currentTime);
    onViewportChange?.(
      adjustWindowToBounds(centerWindowOn(viewport, { time: currentTime }), bounds)
    );
    isDragging = false;
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
    isPlaying = true;
    startTimeTracking();
  }

  function onAudioPause() {
    isPlaying = false;
    stopTimeTracking();
  }

  // Expose seek for external control (parent can call this)
  export function seek(time: number) {
    currentTime = time;
    if (audioEl) {
      audioEl.currentTime = time;
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
      ? 'text-emerald-500 hover:text-emerald-700 dark:hover:text-emerald-300'
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
      <span>{formatTime(duration)}</span>
    </div>
    <div class="relative w-full h-3 flex items-center cursor-pointer">
      <div class="absolute w-full h-1 rounded-full bg-stone-300 dark:bg-stone-600">
        <div
          class="h-1 bg-emerald-500 rounded-full dark:bg-emerald-400"
          style="width: {Math.min((currentTime / duration) * 100, 100)}%"
        ></div>
      </div>
      <input
        type="range"
        min="0"
        max={duration}
        step="0.01"
        value={currentTime}
        oninput={handleSliderInput}
        onchange={handleSliderChange}
        class="timeline-input absolute w-full opacity-0 cursor-pointer h-3"
        aria-label="Seek position"
      />
      <!-- Thumb indicator -->
      <div
        class="absolute w-3 h-3 bg-emerald-500 rounded-full shadow pointer-events-none"
        style="left: calc({Math.min((currentTime / duration) * 100, 100)}% - 6px)"
      ></div>
    </div>
  </div>

  <!-- Speed selector -->
  <div class="relative">
    <button
      type="button"
      class="player-btn flex items-center gap-1 text-stone-600 hover:text-stone-800 dark:text-stone-400 dark:hover:text-stone-200 text-xs font-mono"
      onclick={() => (showSpeedMenu = !showSpeedMenu)}
      aria-label="Playback speed"
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
            class="block w-full px-3 py-1.5 text-left text-sm font-mono hover:bg-emerald-100 dark:hover:bg-emerald-900 {speed === option.value
              ? 'text-emerald-600 dark:text-emerald-400 font-semibold'
              : 'text-stone-700 dark:text-stone-300'}"
            onclick={() => {
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
      class="w-16 h-1 cursor-pointer accent-emerald-500"
      aria-label="Volume"
    />
  </div>

  <!-- Hidden audio element -->
  <audio
    bind:this={audioEl}
    src={audioUrl}
    preload="auto"
    onplay={onAudioPlay}
    onpause={onAudioPause}
    onended={onAudioEnded}
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
    outline: 2px solid #10b981;
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
