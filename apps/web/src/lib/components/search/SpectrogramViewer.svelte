<script lang="ts">
  /**
   * SpectrogramViewer - Read-only spectrogram display with clip range highlight.
   *
   * Decodes audio client-side using Web Audio API, computes STFT spectrogram,
   * renders it on a Canvas, and draws static overlay bars to show the selected
   * clip range. No interactive drag handles or editing controls are provided.
   *
   * Used in session detail readonly mode to preview reference sounds.
   */

  import { onDestroy } from 'svelte';
  import { computeSpectrogram, warmColormap } from '$lib/utils/spectrogramAnalysis';

  interface Props {
    /** Raw audio bytes to decode and display */
    audioData: ArrayBuffer;
    /** Full duration of the audio in seconds */
    duration: number;
    /** Sample rate used for decoding (Hz) */
    sampleRate?: number;
    /** Clip start time in seconds (start of highlighted region) */
    startTime?: number;
    /** Clip end time in seconds (end of highlighted region) */
    endTime?: number;
    /** Canvas height in pixels */
    height?: number;
  }

  let {
    audioData,
    duration,
    sampleRate = 48000,
    startTime = 0,
    endTime = duration,
    height = 100,
  }: Props = $props();

  // DOM references
  let canvasEl: HTMLCanvasElement | undefined = $state();
  let containerEl: HTMLDivElement | undefined = $state();
  let canvasWidth = $state(0);

  // Spectrogram computation state
  let spectrogramData: Float32Array[] | null = $state(null);
  let isDecoding = $state(false);
  let decodeError = $state<string | null>(null);

  // AudioContext used only for decoding (no playback)
  let audioCtx: AudioContext | null = null;

  // Derived overlay percentages
  let startPercent = $derived(duration > 0 ? (startTime / duration) * 100 : 0);
  let endPercent = $derived(duration > 0 ? (endTime / duration) * 100 : 100);

  // ============================================================
  // Canvas rendering
  // ============================================================

  let animRedrawId: number | null = null;

  function requestRedraw() {
    if (animRedrawId !== null) return;
    animRedrawId = requestAnimationFrame(drawCanvas);
  }

  function drawCanvas() {
    animRedrawId = null;
    if (!canvasEl || !spectrogramData || canvasWidth === 0) return;

    const ctx = canvasEl.getContext('2d');
    if (!ctx) return;

    const cols = spectrogramData;
    const numFrames = cols.length;
    const numBins = cols[0]?.length ?? 0;
    if (numFrames === 0 || numBins === 0) return;

    let globalMin = Infinity;
    let globalMax = -Infinity;
    for (const col of cols) {
      for (let k = 0; k < col.length; k++) {
        const v = col[k]!;
        if (v < globalMin) globalMin = v;
        if (v > globalMax) globalMax = v;
      }
    }
    const range = globalMax - globalMin || 1;

    const imageData = ctx.createImageData(canvasWidth, height);
    const data = imageData.data;

    for (let px = 0; px < canvasWidth; px++) {
      const frameIdx = Math.min(
        Math.floor((px / canvasWidth) * numFrames),
        numFrames - 1
      );
      const col = cols[frameIdx]!;

      for (let py = 0; py < height; py++) {
        const binIdx = Math.min(
          Math.floor(((height - 1 - py) / height) * numBins),
          numBins - 1
        );
        const normalized = (col[binIdx]! - globalMin) / range;
        const [r, g, b] = warmColormap(normalized);
        const idx = (py * canvasWidth + px) * 4;
        data[idx] = r;
        data[idx + 1] = g;
        data[idx + 2] = b;
        data[idx + 3] = 255;
      }
    }

    ctx.putImageData(imageData, 0, 0);
  }

  // ============================================================
  // Audio decoding
  // ============================================================

  async function decodeAudio(input: ArrayBuffer): Promise<void> {
    isDecoding = true;
    decodeError = null;
    spectrogramData = null;

    try {
      if (audioCtx) {
        audioCtx.close().catch(() => {});
      }
      audioCtx = new AudioContext({ sampleRate });

      const decoded = await audioCtx.decodeAudioData(input.slice(0));
      const channelData = decoded.getChannelData(0);

      // Yield to avoid blocking the main thread
      await new Promise<void>((resolve) => setTimeout(resolve, 0));

      const FFT_SIZE = 1024;
      const HOP_SIZE = 256;
      spectrogramData = computeSpectrogram(channelData, FFT_SIZE, HOP_SIZE);
    } catch (err) {
      decodeError = err instanceof Error ? err.message : 'Failed to decode audio';
    } finally {
      isDecoding = false;
      // Close decoding context to free resources (no playback needed)
      if (audioCtx) {
        audioCtx.close().catch(() => {});
        audioCtx = null;
      }
    }
  }

  // Re-decode when audioData changes
  $effect(() => {
    const data = audioData;
    void decodeAudio(data);
  });

  // Redraw when spectrogram data or canvas size changes
  $effect(() => {
    const _data = spectrogramData;
    const _w = canvasWidth;
    void _data;
    void _w;
    if (canvasEl) {
      canvasEl.width = canvasWidth;
      canvasEl.height = height;
    }
    requestRedraw();
  });

  // ============================================================
  // Cleanup
  // ============================================================

  onDestroy(() => {
    if (animRedrawId !== null) {
      cancelAnimationFrame(animRedrawId);
    }
    if (audioCtx) {
      audioCtx.close().catch(() => {});
      audioCtx = null;
    }
  });
</script>

<div
  class="relative select-none overflow-hidden rounded"
  style="height: {height}px; background: #1a0a00;"
  bind:this={containerEl}
  bind:clientWidth={canvasWidth}
>
  <!-- Loading spinner -->
  {#if isDecoding}
    <div class="absolute inset-0 flex items-center justify-center">
      <div class="h-4 w-4 animate-spin rounded-full border-2 border-stone-500 border-t-primary-400"></div>
    </div>
  {/if}

  <!-- Error message -->
  {#if decodeError}
    <div class="absolute inset-0 flex items-center justify-center px-2">
      <p class="text-center text-xs text-danger">{decodeError}</p>
    </div>
  {/if}

  <!-- Spectrogram canvas -->
  <canvas
    bind:this={canvasEl}
    class="block h-full w-full"
    width={canvasWidth}
    height={height}
    style="image-rendering: pixelated;"
    aria-hidden="true"
  ></canvas>

  <!-- Dimmed region: before clip start -->
  {#if startPercent > 0}
    <div
      class="pointer-events-none absolute bottom-0 top-0 left-0 bg-black/50"
      style="width: {startPercent}%;"
    ></div>
  {/if}

  <!-- Dimmed region: after clip end -->
  {#if endPercent < 100}
    <div
      class="pointer-events-none absolute bottom-0 top-0 right-0 bg-black/50"
      style="width: {100 - endPercent}%;"
    ></div>
  {/if}

  <!-- Start marker line -->
  {#if startPercent > 0}
    <div
      class="pointer-events-none absolute top-0 bottom-0 w-0.5 bg-primary-400/80"
      style="left: {startPercent}%;"
    ></div>
    <!-- Start time label -->
    <div
      class="pointer-events-none absolute top-1 whitespace-nowrap rounded bg-primary-600/80 px-1 py-0.5 font-mono text-xs text-white dark:bg-primary-500/80 dark:text-stone-50"
      style="left: calc({startPercent}% + 3px);"
    >
      {startTime.toFixed(1)}s
    </div>
  {/if}

  <!-- End marker line -->
  {#if endPercent < 100}
    <div
      class="pointer-events-none absolute top-0 bottom-0 w-0.5 bg-primary-400/80"
      style="left: {endPercent}%;"
    ></div>
    <!-- End time label -->
    <div
      class="pointer-events-none absolute top-1 whitespace-nowrap rounded bg-primary-600/80 px-1 py-0.5 font-mono text-xs text-white dark:bg-primary-500/80 dark:text-stone-50"
      style="right: calc({100 - endPercent}% + 3px);"
    >
      {endTime.toFixed(1)}s
    </div>
  {/if}
</div>
