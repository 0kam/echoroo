<script lang="ts">
  /**
   * SpectrogramClipEditor - Interactive spectrogram with draggable time range selection.
   *
   * Decodes audio client-side using Web Audio API, computes STFT spectrogram,
   * renders it on a Canvas, and provides draggable handles to select a clip range.
   * Supports playback of the selected range.
   */

  import { onDestroy } from 'svelte';
  import * as m from '$lib/paraglide/messages.js';

  interface Props {
    audioFile: File | ArrayBuffer;
    duration: number;
    sampleRate?: number;
    modelName?: 'perch' | 'birdnet';
    startTime?: number;
    endTime?: number;
    onRangeChange?: (start: number, end: number) => void;
  }

  let {
    audioFile,
    duration,
    sampleRate = 48000,
    modelName = 'perch',
    startTime = $bindable(0),
    endTime = $bindable(duration),
    onRangeChange,
  }: Props = $props();

  // Canvas and container DOM references
  let canvasEl: HTMLCanvasElement | undefined = $state();
  let containerEl: HTMLDivElement | undefined = $state();
  let canvasWidth = $state(0);
  const CANVAS_HEIGHT = 160;

  // Spectrogram data
  let spectrogramData: Float32Array[] | null = $state(null); // [freqBins][timeFrames]
  let isDecoding = $state(false);
  let decodeError = $state<string | null>(null);
  let decodedAudioBuffer = $state<AudioBuffer | null>(null);

  // Drag interaction
  let isDragging = $state<'start' | 'end' | null>(null);

  // Playback state
  let isPlaying = $state(false);
  let playbackProgress = $state(0); // 0 to 1 within selection
  let audioCtx: AudioContext | null = null;
  let sourceNode: AudioBufferSourceNode | null = null;
  let animFrameHandle: number | null = null;

  // Derived percentages for overlay/handle positioning
  let startPercent = $derived(duration > 0 ? (startTime / duration) * 100 : 0);
  let endPercent = $derived(duration > 0 ? (endTime / duration) * 100 : 100);
  let clipDuration = $derived(endTime - startTime);
  let minClipDuration = $derived(modelName === 'perch' ? 5 : 3);

  // Progress line position within selection region
  let progressPercent = $derived(
    startPercent + (endPercent - startPercent) * playbackProgress
  );

  // ============================================================
  // FFT utilities
  // ============================================================

  /**
   * In-place radix-2 Cooley-Tukey FFT.
   * real and imag must have length that is a power of two.
   */
  function fft(real: Float32Array, imag: Float32Array): void {
    const n = real.length;
    if (n <= 1) return;

    // Bit reversal permutation
    for (let i = 1, j = 0; i < n; i++) {
      let bit = n >> 1;
      for (; j & bit; bit >>= 1) {
        j ^= bit;
      }
      j ^= bit;
      if (i < j) {
        let tmp = real[i]!;
        real[i] = real[j]!;
        real[j] = tmp;
        tmp = imag[i]!;
        imag[i] = imag[j]!;
        imag[j] = tmp;
      }
    }

    // Iterative FFT butterfly
    for (let len = 2; len <= n; len <<= 1) {
      const ang = (2 * Math.PI) / len;
      const wReal = Math.cos(ang);
      const wImag = Math.sin(ang);
      for (let i = 0; i < n; i += len) {
        let curReal = 1;
        let curImag = 0;
        for (let j = 0; j < len >> 1; j++) {
          const uReal = real[i + j]!;
          const uImag = imag[i + j]!;
          const vReal =
            real[i + j + (len >> 1)]! * curReal - imag[i + j + (len >> 1)]! * curImag;
          const vImag =
            real[i + j + (len >> 1)]! * curImag + imag[i + j + (len >> 1)]! * curReal;
          real[i + j] = uReal + vReal;
          imag[i + j] = uImag + vImag;
          real[i + j + (len >> 1)] = uReal - vReal;
          imag[i + j + (len >> 1)] = uImag - vImag;
          const newCurReal = curReal * wReal - curImag * wImag;
          curImag = curReal * wImag + curImag * wReal;
          curReal = newCurReal;
        }
      }
    }
  }

  /**
   * Build a Hann window of the given length.
   */
  function hannWindow(length: number): Float32Array {
    const win = new Float32Array(length);
    for (let i = 0; i < length; i++) {
      win[i] = 0.5 * (1 - Math.cos((2 * Math.PI * i) / (length - 1)));
    }
    return win;
  }

  /**
   * Compute STFT magnitude spectrogram from mono PCM samples.
   * Returns an array of magnitude columns (one per time frame),
   * each with fftSize/2+1 frequency bins.
   */
  function computeSpectrogram(
    samples: Float32Array,
    fftSize: number,
    hopSize: number
  ): Float32Array[] {
    const win = hannWindow(fftSize);
    const numBins = fftSize / 2 + 1;
    const numFrames = Math.max(1, Math.floor((samples.length - fftSize) / hopSize) + 1);
    const columns: Float32Array[] = [];

    const real = new Float32Array(fftSize);
    const imag = new Float32Array(fftSize);

    for (let frame = 0; frame < numFrames; frame++) {
      const offset = frame * hopSize;
      real.fill(0);
      imag.fill(0);

      // Apply Hann window to the frame
      for (let i = 0; i < fftSize; i++) {
        const sampleIdx = offset + i;
        real[i] = sampleIdx < samples.length ? (samples[sampleIdx]! * win[i]!) : 0;
      }

      fft(real, imag);

      // Compute log-magnitude spectrum
      const col = new Float32Array(numBins);
      for (let k = 0; k < numBins; k++) {
        const mag = Math.sqrt(real[k]! * real[k]! + imag[k]! * imag[k]!);
        col[k] = 10 * Math.log10(mag + 1e-10);
      }
      columns.push(col);
    }

    return columns;
  }

  // ============================================================
  // Canvas rendering
  // ============================================================

  /**
   * Map a normalized intensity value (0–1) to a warm colormap RGBA.
   * Color ramp: dark brown → deep orange → bright orange → yellow → white
   */
  function warmColormap(t: number): [number, number, number] {
    // Clamp
    t = Math.max(0, Math.min(1, t));

    if (t < 0.25) {
      // dark brown (#1a0a00) → deep orange (#7a2800)
      const s = t / 0.25;
      return [
        Math.round(26 + s * (122 - 26)),
        Math.round(10 + s * (40 - 10)),
        Math.round(0),
      ];
    } else if (t < 0.5) {
      // deep orange (#7a2800) → bright orange (#FF5A00)
      const s = (t - 0.25) / 0.25;
      return [
        Math.round(122 + s * (255 - 122)),
        Math.round(40 + s * (90 - 40)),
        Math.round(0),
      ];
    } else if (t < 0.75) {
      // bright orange (#FF5A00) → yellow (#FFE000)
      const s = (t - 0.5) / 0.25;
      return [255, Math.round(90 + s * (224 - 90)), Math.round(s * 0)];
    } else {
      // yellow (#FFE000) → white (#FFFFFF)
      const s = (t - 0.75) / 0.25;
      return [255, Math.round(224 + s * (255 - 224)), Math.round(s * 255)];
    }
  }

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

    // Find global min/max for normalization
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

    // Build ImageData
    const imageData = ctx.createImageData(canvasWidth, CANVAS_HEIGHT);
    const data = imageData.data;

    for (let px = 0; px < canvasWidth; px++) {
      // Map pixel column to spectrogram frame
      const frameIdx = Math.min(
        Math.floor((px / canvasWidth) * numFrames),
        numFrames - 1
      );
      const col = cols[frameIdx]!;

      for (let py = 0; py < CANVAS_HEIGHT; py++) {
        // Map pixel row to frequency bin (bottom = low freq, top = high freq)
        const binIdx = Math.min(
          Math.floor(((CANVAS_HEIGHT - 1 - py) / CANVAS_HEIGHT) * numBins),
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

  async function decodeAudio(input: File | ArrayBuffer): Promise<void> {
    isDecoding = true;
    decodeError = null;
    spectrogramData = null;

    try {
      const arrayBuffer =
        input instanceof File ? await input.arrayBuffer() : input;

      // Close any existing AudioContext from previous decode
      if (audioCtx) {
        audioCtx.close().catch(() => {});
      }
      audioCtx = new AudioContext({ sampleRate });

      decodedAudioBuffer = await audioCtx.decodeAudioData(arrayBuffer.slice(0));
      const channelData = decodedAudioBuffer.getChannelData(0);

      // Compute spectrogram off the main thread via a short yield
      await new Promise<void>((resolve) => setTimeout(resolve, 0));

      const FFT_SIZE = 1024;
      const HOP_SIZE = 256;
      spectrogramData = computeSpectrogram(channelData, FFT_SIZE, HOP_SIZE);
    } catch (err) {
      decodeError = err instanceof Error ? err.message : 'Failed to decode audio';
      decodedAudioBuffer = null;
    } finally {
      isDecoding = false;
    }
  }

  // Re-decode when audioFile changes
  $effect(() => {
    const file = audioFile;
    void decodeAudio(file);
  });

  // Redraw when spectrogram data or canvas size changes
  $effect(() => {
    const _data = spectrogramData;
    const _w = canvasWidth;
    void _data;
    void _w;
    if (canvasEl) {
      canvasEl.width = canvasWidth;
      canvasEl.height = CANVAS_HEIGHT;
    }
    requestRedraw();
  });

  // ============================================================
  // Drag interaction
  // ============================================================

  function onPointerDown(e: PointerEvent, handle: 'start' | 'end') {
    e.preventDefault();
    isDragging = handle;
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }

  function onPointerMove(e: PointerEvent) {
    if (!isDragging || !canvasEl) return;
    const rect = canvasEl.getBoundingClientRect();
    const x = Math.max(0, Math.min(e.clientX - rect.left, rect.width));
    const time = (x / rect.width) * duration;
    const minDur = minClipDuration;

    if (isDragging === 'start') {
      startTime = Math.max(0, Math.min(time, endTime - minDur));
    } else {
      endTime = Math.min(duration, Math.max(time, startTime + minDur));
    }
    onRangeChange?.(startTime, endTime);
  }

  function onPointerUp() {
    isDragging = null;
  }

  // ============================================================
  // Playback
  // ============================================================

  function playSelection() {
    if (isPlaying) {
      stopPlayback();
      return;
    }
    if (!decodedAudioBuffer) return;

    // Re-create AudioContext if it was closed
    if (!audioCtx || audioCtx.state === 'closed') {
      audioCtx = new AudioContext({ sampleRate });
    }

    sourceNode = audioCtx.createBufferSource();
    sourceNode.buffer = decodedAudioBuffer;
    sourceNode.connect(audioCtx.destination);

    const selStart = startTime;
    const selDuration = endTime - startTime;

    sourceNode.start(0, selStart, selDuration);
    isPlaying = true;
    playbackProgress = 0;

    const startedAt = audioCtx.currentTime;

    function updateProgress() {
      if (!isPlaying) return;
      const elapsed = (audioCtx?.currentTime ?? 0) - startedAt;
      playbackProgress = Math.min(elapsed / selDuration, 1);
      if (playbackProgress >= 1) {
        stopPlayback();
        return;
      }
      animFrameHandle = requestAnimationFrame(updateProgress);
    }
    animFrameHandle = requestAnimationFrame(updateProgress);

    sourceNode.onended = () => stopPlayback();
  }

  function stopPlayback() {
    if (animFrameHandle !== null) {
      cancelAnimationFrame(animFrameHandle);
      animFrameHandle = null;
    }
    try {
      sourceNode?.stop();
    } catch {
      // Already stopped
    }
    sourceNode = null;
    isPlaying = false;
    playbackProgress = 0;
  }

  // ============================================================
  // Time input handlers
  // ============================================================

  function handleStartChange(e: Event) {
    const val = parseFloat((e.target as HTMLInputElement).value);
    if (!isNaN(val)) {
      startTime = Math.max(0, Math.min(val, endTime - minClipDuration));
      onRangeChange?.(startTime, endTime);
    }
  }

  function handleEndChange(e: Event) {
    const val = parseFloat((e.target as HTMLInputElement).value);
    if (!isNaN(val)) {
      endTime = Math.min(duration, Math.max(val, startTime + minClipDuration));
      onRangeChange?.(startTime, endTime);
    }
  }

  function useFullAudio() {
    startTime = 0;
    endTime = duration;
    onRangeChange?.(startTime, endTime);
  }

  // ============================================================
  // Cleanup
  // ============================================================

  onDestroy(() => {
    stopPlayback();
    if (audioCtx) {
      audioCtx.close().catch(() => {});
      audioCtx = null;
    }
    if (animRedrawId !== null) {
      cancelAnimationFrame(animRedrawId);
    }
  });
</script>

<div class="space-y-3">
  <!-- Recommendation text -->
  <p class="text-xs text-stone-500">
    {m.search_clip_recommendation()}
  </p>

  <!-- Spectrogram with selection overlay -->
  <div
    class="relative select-none overflow-hidden rounded"
    style="height: {CANVAS_HEIGHT}px; background: #1a0a00;"
    bind:this={containerEl}
    bind:clientWidth={canvasWidth}
  >
    <!-- Loading state -->
    {#if isDecoding}
      <div class="absolute inset-0 flex items-center justify-center">
        <div
          class="h-5 w-5 animate-spin rounded-full border-2 border-stone-500 border-t-primary-400"
        ></div>
      </div>
    {/if}

    <!-- Error state -->
    {#if decodeError}
      <div class="absolute inset-0 flex items-center justify-center">
        <p class="text-xs text-danger">{decodeError}</p>
      </div>
    {/if}

    <!-- Spectrogram canvas -->
    <canvas
      bind:this={canvasEl}
      class="block h-full w-full"
      width={canvasWidth}
      height={CANVAS_HEIGHT}
      style="image-rendering: pixelated;"
    ></canvas>

    <!-- Left unselected region dim overlay -->
    <div
      class="pointer-events-none absolute bottom-0 top-0 left-0 rounded-l bg-black/40"
      style="width: {startPercent}%;"
    ></div>

    <!-- Right unselected region dim overlay -->
    <div
      class="pointer-events-none absolute bottom-0 top-0 right-0 rounded-r bg-black/40"
      style="width: {100 - endPercent}%;"
    ></div>

    <!-- Playback progress line -->
    {#if isPlaying}
      <div
        class="pointer-events-none absolute top-0 bottom-0 w-0.5 bg-stone-50/80 dark:bg-stone-950/80"
        style="left: {progressPercent}%;"
      ></div>
    {/if}

    <!-- Left handle (start time) -->
    <div
      class="absolute top-0 bottom-0 z-10 flex cursor-col-resize touch-none items-stretch"
      style="left: {startPercent}%; transform: translateX(-50%);"
      role="slider"
      aria-label="Start time"
      aria-valuenow={startTime}
      aria-valuemin={0}
      aria-valuemax={endTime - minClipDuration}
      tabindex="0"
      onpointerdown={(e) => onPointerDown(e, 'start')}
      onpointermove={onPointerMove}
      onpointerup={onPointerUp}
    >
      <!-- Invisible wide touch target -->
      <div class="absolute inset-y-0 -left-5 -right-5"></div>
      <!-- Visible handle bar -->
      <div
        class="relative mx-auto transition-all duration-100"
        class:w-2={isDragging === 'start'}
        style="width: {isDragging === 'start' ? '8px' : '6px'};"
      >
        <div class="h-full w-full rounded-sm bg-primary-500 shadow-md opacity-90"></div>
        <!-- Grip dots -->
        <div class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2">
          <div class="flex flex-col gap-0.5">
            <div class="h-0.5 w-1 rounded-full bg-stone-50/50"></div>
            <div class="h-0.5 w-1 rounded-full bg-stone-50/50"></div>
            <div class="h-0.5 w-1 rounded-full bg-stone-50/50"></div>
          </div>
        </div>
      </div>
      <!-- Time label -->
      <div
        class="pointer-events-none absolute top-1 left-2 whitespace-nowrap rounded bg-primary-600/90 px-1 py-0.5 font-mono text-xs text-white shadow-sm dark:bg-primary-500/90 dark:text-stone-50"
      >
        {startTime.toFixed(1)}s
      </div>
    </div>

    <!-- Right handle (end time) -->
    <div
      class="absolute top-0 bottom-0 z-10 flex cursor-col-resize touch-none items-stretch"
      style="left: {endPercent}%; transform: translateX(-50%);"
      role="slider"
      aria-label="End time"
      aria-valuenow={endTime}
      aria-valuemin={startTime + minClipDuration}
      aria-valuemax={duration}
      tabindex="0"
      onpointerdown={(e) => onPointerDown(e, 'end')}
      onpointermove={onPointerMove}
      onpointerup={onPointerUp}
    >
      <!-- Invisible wide touch target -->
      <div class="absolute inset-y-0 -left-5 -right-5"></div>
      <!-- Visible handle bar -->
      <div
        class="relative mx-auto transition-all duration-100"
        style="width: {isDragging === 'end' ? '8px' : '6px'};"
      >
        <div class="h-full w-full rounded-sm bg-primary-500 shadow-md opacity-90"></div>
        <!-- Grip dots -->
        <div class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2">
          <div class="flex flex-col gap-0.5">
            <div class="h-0.5 w-1 rounded-full bg-stone-50/50"></div>
            <div class="h-0.5 w-1 rounded-full bg-stone-50/50"></div>
            <div class="h-0.5 w-1 rounded-full bg-stone-50/50"></div>
          </div>
        </div>
      </div>
      <!-- Time label -->
      <div
        class="pointer-events-none absolute top-1 right-2 whitespace-nowrap rounded bg-primary-600/90 px-1 py-0.5 font-mono text-xs text-white shadow-sm dark:bg-primary-500/90 dark:text-stone-50"
      >
        {endTime.toFixed(1)}s
      </div>
    </div>
  </div>

  <!-- Controls row -->
  <div class="flex flex-wrap items-center gap-3">
    <!-- Play / Stop button -->
    <button
      type="button"
      class="flex items-center gap-1.5 rounded-md bg-primary-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
      onclick={playSelection}
      disabled={!decodedAudioBuffer || isDecoding}
    >
      {#if isPlaying}
        <!-- Stop icon (inline SVG) -->
        <svg
          class="h-4 w-4"
          viewBox="0 0 24 24"
          fill="currentColor"
          aria-hidden="true"
        >
          <rect x="6" y="6" width="12" height="12" rx="1" />
        </svg>
        {m.search_clip_stop()}
      {:else}
        <!-- Play icon (inline SVG) -->
        <svg
          class="h-4 w-4"
          viewBox="0 0 24 24"
          fill="currentColor"
          aria-hidden="true"
        >
          <path d="M8 5.14v13.72a1 1 0 0 0 1.5.86l11-6.86a1 1 0 0 0 0-1.72l-11-6.86A1 1 0 0 0 8 5.14z" />
        </svg>
        {m.search_clip_play_selection()}
      {/if}
    </button>

    <!-- Duration display -->
    <span class="text-sm text-stone-500">
      {startTime.toFixed(1)}s &ndash; {endTime.toFixed(1)}s
      ({m.search_clip_selected({ duration: clipDuration.toFixed(1) })})
    </span>

    <!-- Numeric time inputs -->
    <div class="flex items-center gap-2">
      <label for="clip-start-input" class="text-xs text-stone-500">{m.search_clip_start()}</label>
      <input
        id="clip-start-input"
        type="number"
        class="w-16 rounded border border-stone-300 bg-surface-card px-2 py-1 text-xs text-stone-900 dark:border-stone-600"
        step="0.1"
        min="0"
        max={endTime - minClipDuration}
        value={startTime}
        onchange={handleStartChange}
      />

      <label for="clip-end-input" class="text-xs text-stone-500">{m.search_clip_end()}</label>
      <input
        id="clip-end-input"
        type="number"
        class="w-16 rounded border border-stone-300 bg-surface-card px-2 py-1 text-xs text-stone-900 dark:border-stone-600"
        step="0.1"
        min={startTime + minClipDuration}
        max={duration}
        value={endTime}
        onchange={handleEndChange}
      />
    </div>

    <!-- Use full audio shortcut -->
    <button
      type="button"
      class="text-sm text-primary-600 hover:underline"
      onclick={useFullAudio}
    >
      {m.search_clip_use_full()}
    </button>
  </div>

  <!-- Short clip warning -->
  {#if clipDuration < minClipDuration}
    <p class="text-xs text-warning">
      {m.search_clip_short_warning({ seconds: minClipDuration.toString() })}
    </p>
  {/if}
</div>
