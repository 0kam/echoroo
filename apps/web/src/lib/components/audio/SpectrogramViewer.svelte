<script lang="ts">
  import { getSpectrogramUrl } from '$lib/api/recordings';
  import type { SpectrogramParams } from '$lib/types/data';

  export let projectId: string;
  export let recordingId: string;
  export let duration: number;
  export let params: SpectrogramParams = {};
  export let onTimeClick: ((time: number) => void) | undefined = undefined;
  export let currentTime: number = 0;
  export let isPlaying: boolean = false;

  let containerWidth = 1200;
  let imageLoaded = false;
  let imageError = false;
  let containerElement: HTMLDivElement;
  let imageElement: HTMLImageElement;

  $: spectrogramUrl = getSpectrogramUrl(projectId, recordingId, {
    ...params,
    width: containerWidth,
  });

  // Auto-scroll spectrogram during playback to keep playhead visible
  $: if (isPlaying && imageLoaded && containerElement && imageElement) {
    const progress = currentTime / duration;
    const imageWidth = imageElement.clientWidth;
    const containerWidth = containerElement.clientWidth;
    const playheadPosition = imageWidth * progress;
    const scrollPosition = containerElement.scrollLeft;
    const viewportEnd = scrollPosition + containerWidth;

    // Scroll if playhead is outside visible viewport or near edges
    const margin = containerWidth * 0.2; // 20% margin
    if (playheadPosition < scrollPosition + margin || playheadPosition > viewportEnd - margin) {
      // Center the playhead in the viewport
      const targetScroll = playheadPosition - containerWidth / 2;
      containerElement.scrollTo({
        left: Math.max(0, targetScroll),
        behavior: 'smooth'
      });
    }
  }

  function handleImageClick(event: MouseEvent) {
    if (!onTimeClick) return;
    const img = event.target as HTMLImageElement;
    const rect = img.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const time = (x / rect.width) * duration;
    onTimeClick(time);
  }

  function handleImageLoad() {
    imageLoaded = true;
    imageError = false;
  }

  function handleImageError() {
    imageError = true;
    imageLoaded = false;
  }
</script>

<div class="spectrogram-container" bind:this={containerElement} bind:clientWidth={containerWidth}>
  {#if !imageLoaded && !imageError}
    <div class="loading-state">
      <div class="spinner"></div>
      <span>Loading spectrogram...</span>
    </div>
  {/if}

  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <img
    bind:this={imageElement}
    src={spectrogramUrl}
    alt="Spectrogram"
    class="spectrogram-image"
    class:hidden={!imageLoaded}
    on:load={handleImageLoad}
    on:error={handleImageError}
    on:click={handleImageClick}
    role="button"
    tabindex={onTimeClick ? 0 : -1}
  />

  {#if imageError}
    <div class="error-state">
      <svg class="error-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <circle cx="12" cy="12" r="10" stroke-width="2" />
        <line x1="12" y1="8" x2="12" y2="12" stroke-width="2" />
        <line x1="12" y1="16" x2="12.01" y2="16" stroke-width="2" />
      </svg>
      <span>Failed to load spectrogram</span>
    </div>
  {/if}

  <!-- Time axis labels -->
  {#if imageLoaded}
    <div class="time-axis">
      <span>0:00</span>
      <span>{Math.floor(duration / 60)}:{(Math.floor(duration % 60)).toString().padStart(2, '0')}</span>
    </div>
  {/if}
</div>

<style>
  .spectrogram-container {
    position: relative;
    width: 100%;
    min-height: 400px;
    background: #f9fafb;
    border-radius: 0.5rem;
    overflow-x: auto;
    overflow-y: hidden;
  }

  .loading-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 400px;
    gap: 1rem;
  }

  .loading-state span {
    color: #6b7280;
    font-size: 0.875rem;
  }

  .spinner {
    width: 40px;
    height: 40px;
    border: 4px solid #e5e7eb;
    border-top-color: #3b82f6;
    border-radius: 50%;
    animation: spin 1s linear infinite;
  }

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }

  .spectrogram-image {
    width: 100%;
    display: block;
    cursor: crosshair;
  }

  .spectrogram-image.hidden {
    display: none;
  }

  .error-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 400px;
    gap: 1rem;
    background: #fee2e2;
    color: #991b1b;
  }

  .error-icon {
    width: 48px;
    height: 48px;
  }

  .error-state span {
    font-size: 0.875rem;
  }

  .time-axis {
    display: flex;
    justify-content: space-between;
    padding: 0.5rem 0.75rem;
    background: #f9fafb;
    border-top: 1px solid #e5e7eb;
    font-size: 0.75rem;
    color: #6b7280;
    font-family: monospace;
  }
</style>
