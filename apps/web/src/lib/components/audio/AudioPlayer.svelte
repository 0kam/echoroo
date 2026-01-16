<script lang="ts">
  import { onMount } from 'svelte';
  import { getPlaybackUrl } from '$lib/api/recordings';

  export let projectId: string;
  export let recordingId: string;
  export let duration: number;
  export let speed: number = 1.0;
  export let isUltrasonic: boolean = false;
  export let currentTime: number = 0;
  export let onTimeUpdate: ((time: number) => void) | undefined = undefined;

  let audioElement: HTMLAudioElement;
  let isPlaying = false;
  let volume = 1.0;
  let isDragging = false;
  let containerElement: HTMLDivElement;
  let isFocused = false;

  $: audioUrl = getPlaybackUrl(projectId, recordingId, { speed });

  // Reload audio when speed changes
  $: if (audioElement && speed) {
    const wasPlaying = isPlaying;
    const time = currentTime;
    audioElement.src = audioUrl;
    audioElement.currentTime = time;
    if (wasPlaying) {
      audioElement.play();
    }
  }

  export function play() {
    audioElement?.play();
    isPlaying = true;
  }

  export function pause() {
    audioElement?.pause();
    isPlaying = false;
  }

  export function seek(time: number) {
    if (audioElement) {
      audioElement.currentTime = time;
      currentTime = time;
    }
  }

  function togglePlay() {
    if (isPlaying) {
      pause();
    } else {
      play();
    }
  }

  function handleTimeUpdate() {
    if (!isDragging) {
      currentTime = audioElement?.currentTime ?? 0;
      onTimeUpdate?.(currentTime);
    }
  }

  function handleSliderInput(event: Event) {
    const target = event.target as HTMLInputElement;
    currentTime = parseFloat(target.value);
  }

  function handleSliderChange() {
    seek(currentTime);
    isDragging = false;
  }

  function handleSliderMouseDown() {
    isDragging = true;
  }

  function formatTime(seconds: number): string {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    const ms = Math.floor((seconds % 1) * 100);
    return `${mins}:${secs.toString().padStart(2, '0')}.${ms.toString().padStart(2, '0')}`;
  }

  function handleVolumeChange(event: Event) {
    const target = event.target as HTMLInputElement;
    volume = parseFloat(target.value);
  }

  function handleKeydown(event: KeyboardEvent) {
    if (!isFocused) return;

    switch (event.code) {
      case 'Space':
        event.preventDefault();
        togglePlay();
        break;
      case 'ArrowLeft':
        event.preventDefault();
        seek(Math.max(0, currentTime - (event.shiftKey ? 1 : 5)));
        break;
      case 'ArrowRight':
        event.preventDefault();
        seek(Math.min(duration, currentTime + (event.shiftKey ? 1 : 5)));
        break;
    }
  }
</script>

<svelte:window on:keydown={handleKeydown} />

<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
<div
  bind:this={containerElement}
  class="audio-player"
  role="region"
  aria-label="Audio player"
  tabindex="0"
  on:focus={() => (isFocused = true)}
  on:blur={() => (isFocused = false)}
>
  <button class="play-button" on:click={togglePlay} aria-label={isPlaying ? 'Pause' : 'Play'}>
    {#if isPlaying}
      <!-- Pause icon -->
      <svg class="icon" viewBox="0 0 24 24" fill="currentColor">
        <rect x="6" y="4" width="4" height="16" />
        <rect x="14" y="4" width="4" height="16" />
      </svg>
    {:else}
      <!-- Play icon -->
      <svg class="icon" viewBox="0 0 24 24" fill="currentColor">
        <polygon points="5 3 19 12 5 21 5 3" />
      </svg>
    {/if}
  </button>

  <div class="timeline-container">
    <input
      type="range"
      min="0"
      max={duration}
      step="0.01"
      value={currentTime}
      on:input={handleSliderInput}
      on:change={handleSliderChange}
      on:mousedown={handleSliderMouseDown}
      class="timeline-slider"
    />
    <div class="time-display">
      <span class="current-time">{formatTime(currentTime)}</span>
      <span class="total-time">{formatTime(duration)}</span>
    </div>
  </div>

  <div class="volume-control">
    <svg class="volume-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
      <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" stroke-width="2" />
      {#if volume > 0.5}
        <path d="M15.54 8.46a5 5 0 0 1 0 7.07" stroke-width="2" />
        <path d="M19.07 4.93a10 10 0 0 1 0 14.14" stroke-width="2" />
      {:else if volume > 0}
        <path d="M15.54 8.46a5 5 0 0 1 0 7.07" stroke-width="2" />
      {/if}
    </svg>
    <input
      type="range"
      min="0"
      max="1"
      step="0.1"
      value={volume}
      on:input={handleVolumeChange}
      class="volume-slider"
    />
  </div>

  <audio
    bind:this={audioElement}
    src={audioUrl}
    bind:volume
    on:timeupdate={handleTimeUpdate}
    on:play={() => (isPlaying = true)}
    on:pause={() => (isPlaying = false)}
    on:ended={() => (isPlaying = false)}
    preload="auto"
  ></audio>
</div>

{#if isUltrasonic}
  <div class="ultrasonic-notice">
    <svg class="warning-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
      <path
        d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"
        stroke-width="2"
      />
      <line x1="12" y1="9" x2="12" y2="13" stroke-width="2" />
      <line x1="12" y1="17" x2="12.01" y2="17" stroke-width="2" />
    </svg>
    <span>Ultrasonic recording - playback speed adjusted for audibility</span>
  </div>
{/if}

<style>
  .audio-player {
    display: flex;
    align-items: center;
    gap: 1rem;
    padding: 1rem;
    background: #f9fafb;
    border-radius: 0.5rem;
    border: 1px solid #e5e7eb;
  }

  .play-button {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 48px;
    height: 48px;
    background: #3b82f6;
    color: white;
    border: none;
    border-radius: 50%;
    cursor: pointer;
    transition: all 0.15s ease;
    flex-shrink: 0;
  }

  .play-button:hover {
    background: #2563eb;
    transform: scale(1.05);
  }

  .play-button:active {
    transform: scale(0.95);
  }

  .icon {
    width: 24px;
    height: 24px;
  }

  .timeline-container {
    flex: 1;
    min-width: 0;
  }

  .timeline-slider {
    width: 100%;
    height: 6px;
    -webkit-appearance: none;
    appearance: none;
    background: #e5e7eb;
    border-radius: 3px;
    outline: none;
    cursor: pointer;
  }

  .timeline-slider::-webkit-slider-thumb {
    -webkit-appearance: none;
    appearance: none;
    width: 16px;
    height: 16px;
    background: #3b82f6;
    border-radius: 50%;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .timeline-slider::-webkit-slider-thumb:hover {
    background: #2563eb;
    transform: scale(1.2);
  }

  .timeline-slider::-moz-range-thumb {
    width: 16px;
    height: 16px;
    background: #3b82f6;
    border: none;
    border-radius: 50%;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .timeline-slider::-moz-range-thumb:hover {
    background: #2563eb;
    transform: scale(1.2);
  }

  .time-display {
    display: flex;
    justify-content: space-between;
    margin-top: 0.5rem;
    font-size: 0.75rem;
    font-family: monospace;
    color: #6b7280;
  }

  .volume-control {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-shrink: 0;
  }

  .volume-icon {
    width: 20px;
    height: 20px;
    color: #6b7280;
  }

  .volume-slider {
    width: 80px;
    height: 4px;
    -webkit-appearance: none;
    appearance: none;
    background: #e5e7eb;
    border-radius: 2px;
    outline: none;
    cursor: pointer;
  }

  .volume-slider::-webkit-slider-thumb {
    -webkit-appearance: none;
    appearance: none;
    width: 12px;
    height: 12px;
    background: #6b7280;
    border-radius: 50%;
    cursor: pointer;
  }

  .volume-slider::-webkit-slider-thumb:hover {
    background: #374151;
  }

  .volume-slider::-moz-range-thumb {
    width: 12px;
    height: 12px;
    background: #6b7280;
    border: none;
    border-radius: 50%;
    cursor: pointer;
  }

  .volume-slider::-moz-range-thumb:hover {
    background: #374151;
  }

  .ultrasonic-notice {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-top: 0.5rem;
    padding: 0.75rem 1rem;
    background: #fef3c7;
    border: 1px solid #fcd34d;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    color: #92400e;
  }

  .warning-icon {
    width: 20px;
    height: 20px;
    color: #f59e0b;
    flex-shrink: 0;
  }
</style>
