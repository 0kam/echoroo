<script lang="ts">
  import { onDestroy } from 'svelte';
  import type { SpectrogramWindow } from '$lib/types/audio';
  import {
    intersectWindows,
    intersectIntervals,
    timeToPixel,
    getViewportPosition,
  } from '$lib/utils/viewport';
  import { createSpectrogramScheduler } from './useSpectrogramScheduler';
  import type { SpectrogramCanvasProps } from './types';

  // Pure presentational canvas component extracted from SpectrogramViewer
  // (P2-B Step 3). Owns the RAF scheduler and the draw pipeline; the parent
  // passes all reactive state through props. The `canvas` prop is $bindable
  // so the parent can retain a reference for the interaction hook.
  let {
    canvas = $bindable<HTMLCanvasElement | undefined>(undefined),
    canvasWidth,
    canvasHeight,
    viewport,
    bounds,
    chunks,
    chunkImages,
    currentTime,
    mousePos,
    zoomBox,
    interactionMode,
    spectrogramSettings,
    readonly = false,
    isDragging = false,
    onmousemove,
    onmousedown,
    onmouseup,
    onmouseleave,
    ondblclick,
    onwheel,
  }: SpectrogramCanvasProps = $props();

  // `bounds` and `spectrogramSettings` are declared for API symmetry with the
  // props contract. They are observed inside the redraw $effect below to
  // ensure changes trigger a redraw through the scheduler.

  function drawAll() {
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.clearRect(0, 0, canvasWidth, canvasHeight);
    drawSpectrogram(ctx);
    drawPlayCursor(ctx);
    drawMouseCrosshair(ctx);
    drawZoomBox(ctx);
    drawTimeAxis(ctx);
    drawFreqAxis(ctx);
  }

  function drawSpectrogram(ctx: CanvasRenderingContext2D) {
    // The recording's samplerate is already baked into `bounds.freq.max` via
    // the parent's viewport/bounds computation, so we derive `maxFreq` from
    // bounds rather than re-reading the recording here.
    // Invariant: bounds.freq.max == recording.samplerate / 2 (Nyquist). Chunk
    // URLs are generated at that freq range in useChunkManager, so a narrower
    // bounds here would mismatch the decoded chunks.
    const maxFreq = bounds.freq.max;

    chunks.forEach((chunk, idx) => {
      const img = chunkImages[idx];
      if (!img) return;

      const overlap = intersectIntervals(chunk.interval, viewport.time);
      if (!overlap) return;

      const imageBounds: SpectrogramWindow = {
        time: chunk.interval,
        freq: { min: 0, max: maxFreq },
      };

      const bufferBounds: SpectrogramWindow = {
        time: chunk.buffer,
        freq: { min: 0, max: maxFreq },
      };

      if (chunk.isLoading) {
        // Draw loading placeholder
        const pos = getViewportPosition({
          width: canvasWidth,
          height: canvasHeight,
          viewport: { time: chunk.interval, freq: viewport.freq },
          bounds: viewport,
        });
        ctx.fillStyle = '#d6d3d1';
        ctx.fillRect(pos.left, pos.top, pos.width, pos.height);
        return;
      }

      if (chunk.isError) {
        // Draw error placeholder
        const pos = getViewportPosition({
          width: canvasWidth,
          height: canvasHeight,
          viewport: { time: chunk.interval, freq: viewport.freq },
          bounds: viewport,
        });
        ctx.fillStyle = '#fecaca';
        ctx.fillRect(pos.left, pos.top, pos.width, pos.height);
        return;
      }

      if (!chunk.isReady || !img.complete || img.naturalWidth === 0) {
        // Not yet loaded — lazy load will be triggered by the viewport effect
        return;
      }

      // Draw image onto canvas
      const intersection = intersectWindows(viewport, imageBounds);
      if (!intersection) return;

      const srcPos = getViewportPosition({
        width: img.width,
        height: img.height,
        viewport: intersection,
        bounds: bufferBounds,
      });

      const dstPos = getViewportPosition({
        width: canvasWidth,
        height: canvasHeight,
        viewport: intersection,
        bounds: viewport,
      });

      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = 'high';
      ctx.globalAlpha = 1;
      ctx.drawImage(
        img,
        srcPos.left,
        srcPos.top,
        srcPos.width + 1,
        srcPos.height,
        dstPos.left,
        dstPos.top,
        dstPos.width + 1,
        dstPos.height
      );
    });
  }

  function drawPlayCursor(ctx: CanvasRenderingContext2D) {
    if (currentTime < viewport.time.min || currentTime > viewport.time.max) return;
    const x = timeToPixel(currentTime, canvasWidth, viewport);
    ctx.globalAlpha = 1;
    ctx.strokeStyle = '#ef4444'; // red-500
    ctx.lineWidth = 2;
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, canvasHeight);
    ctx.stroke();
  }

  function drawMouseCrosshair(ctx: CanvasRenderingContext2D) {
    if (!mousePos) return;
    const x = timeToPixel(mousePos.time, canvasWidth, viewport);
    const y = canvasHeight - ((mousePos.freq - viewport.freq.min) / (viewport.freq.max - viewport.freq.min)) * canvasHeight;

    ctx.globalAlpha = 0.6;
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);

    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, canvasHeight);
    ctx.stroke();

    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(canvasWidth, y);
    ctx.stroke();

    ctx.setLineDash([]);
    ctx.globalAlpha = 1;
  }

  function drawZoomBox(ctx: CanvasRenderingContext2D) {
    if (!zoomBox || !zoomBox.start || !zoomBox.end) return;

    const { start, end } = zoomBox;
    const timeSorted = [start.time, end.time].toSorted((a, b) => a - b);
    const freqSorted = [start.freq, end.freq].toSorted((a, b) => a - b);

    const boxWindow: SpectrogramWindow = {
      time: { min: timeSorted[0] ?? 0, max: timeSorted[1] ?? 0 },
      freq: { min: freqSorted[0] ?? 0, max: freqSorted[1] ?? 0 },
    };

    const isValid =
      boxWindow.time.max > boxWindow.time.min &&
      boxWindow.freq.max > boxWindow.freq.min;

    const pos = getViewportPosition({
      width: canvasWidth,
      height: canvasHeight,
      viewport: boxWindow,
      bounds: viewport,
    });

    ctx.globalAlpha = 0.3;
    ctx.fillStyle = isValid ? '#facc15' : '#ef4444'; // yellow or red
    ctx.fillRect(pos.left, pos.top, pos.width, pos.height);
    ctx.globalAlpha = 1;
    ctx.strokeStyle = isValid ? '#facc15' : '#ef4444';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.strokeRect(pos.left, pos.top, pos.width, pos.height);
    ctx.setLineDash([]);
  }

  function drawTimeAxis(ctx: CanvasRenderingContext2D) {
    const { min, max } = viewport.time;
    const range = max - min;
    if (range <= 0) return;

    const valPerPixel = range / canvasWidth;
    let digits = Math.floor(Math.log10(valPerPixel * 50)) + 1;
    let step = Math.pow(10, digits);
    if (range / step <= 3) {
      step /= 2;
      digits -= 1;
    }
    const minorStep = step / 5;

    ctx.globalAlpha = 0.8;
    ctx.strokeStyle = 'rgba(255,255,255,0.6)';
    ctx.fillStyle = 'rgba(255,255,255,0.9)';
    ctx.font = '10px system-ui';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';

    // Minor ticks
    const minorStart = Math.ceil(min / minorStep);
    const minorCount = Math.floor((max - min) / minorStep) + 1;
    for (let i = 0; i < minorCount; i++) {
      const t = (minorStart + i) * minorStep;
      const x = (canvasWidth * (t - min)) / range;
      ctx.lineWidth = 0.5;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, 5);
      ctx.stroke();
    }

    // Major ticks with labels
    const majorStart = Math.ceil(min / step);
    const majorCount = Math.floor((max - min) / step) + 1;
    for (let i = 0; i < majorCount; i++) {
      const t = (majorStart + i) * step;
      const x = (canvasWidth * (t - min)) / range;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, 10);
      ctx.stroke();

      const label = formatAxisNum(t, digits);
      ctx.fillText(label, x + 2, 10);
    }
    ctx.globalAlpha = 1;
  }

  function drawFreqAxis(ctx: CanvasRenderingContext2D) {
    const { min, max } = viewport.freq;
    const range = max - min;
    if (range <= 0) return;

    const valPerPixel = range / canvasHeight;
    let digits = Math.floor(Math.log10(valPerPixel * 50)) + 1;
    let step = Math.pow(10, digits);
    if (range / step <= 3) {
      step /= 2;
      digits -= 1;
    }
    const minorStep = step / 5;

    ctx.globalAlpha = 0.8;
    ctx.strokeStyle = 'rgba(255,255,255,0.6)';
    ctx.fillStyle = 'rgba(255,255,255,0.9)';
    ctx.font = '10px system-ui';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'bottom';

    // Minor ticks
    const minorStart = Math.ceil(min / minorStep);
    const minorCount = Math.floor((max - min) / minorStep) + 1;
    for (let i = 0; i < minorCount; i++) {
      const f = (minorStart + i) * minorStep;
      const y = (canvasHeight * (max - f)) / range;
      ctx.lineWidth = 0.5;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(5, y);
      ctx.stroke();
    }

    // Major ticks with labels
    const majorStart = Math.ceil(min / step);
    const majorCount = Math.floor((max - min) / step) + 1;
    for (let i = 0; i < majorCount; i++) {
      const f = (majorStart + i) * step;
      const y = (canvasHeight * (max - f)) / range;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(10, y);
      ctx.stroke();

      const label = formatAxisNum(f / 1000, digits - 3) + 'k';
      ctx.fillText(label, 12, y);
    }
    ctx.globalAlpha = 1;
  }

  function formatAxisNum(value: number, digits: number): string {
    const numDigits = Math.floor(Math.log10(Math.max(Math.abs(value), 1e-10))) + 1;
    const precision = numDigits - Math.min(digits, 0);
    if (precision <= 0 || !isFinite(value)) return value.toFixed(2);
    return value.toPrecision(Math.max(precision, 1));
  }

  // RAF scheduler — coalesces multiple `request()` calls into a single draw on
  // the next animation frame. Ownership lives here (Step 3): the parent no
  // longer imports or constructs a scheduler.
  const scheduler = createSpectrogramScheduler(drawAll);

  // Size sync — run BEFORE redraw so drawAll sees the new dimensions. Using
  // $effect.pre guarantees the canvas element's intrinsic pixel size is
  // updated before the redraw $effect fires in the same flush.
  $effect.pre(() => {
    if (!canvas) return;
    canvas.width = canvasWidth;
    canvas.height = canvasHeight;
  });

  // Redraw trigger — observe every prop that affects rendering.
  // canvasWidth/Height are in the dep list so a resize still triggers a
  // redraw even though $effect.pre already mutated the canvas element.
  // This is the v3 "pivotal point" noted in plan.md §6 — omitting these
  // deps caused intermittent redraw misses on container resize.
  $effect(() => {
    void chunks;
    void chunkImages;
    void viewport;
    void bounds;
    void currentTime;
    void mousePos;
    void zoomBox;
    void interactionMode;
    void spectrogramSettings;
    void canvasWidth;
    void canvasHeight;
    scheduler.request();
  });

  onDestroy(() => scheduler.dispose());
</script>

<canvas
  bind:this={canvas}
  width={canvasWidth}
  height={canvasHeight}
  class="spectrogram-canvas"
  class:cursor-crosshair={!readonly && interactionMode === 'idle'}
  class:cursor-grab={!readonly && interactionMode === 'panning' && !isDragging}
  class:cursor-grabbing={!readonly && interactionMode === 'panning' && isDragging}
  class:cursor-crosshair-zoom={!readonly && interactionMode === 'zooming'}
  tabindex={readonly ? undefined : 0}
  aria-label="Spectrogram visualization"
  {onmousemove}
  {onmousedown}
  {onmouseup}
  {onmouseleave}
  {ondblclick}
  {onwheel}
></canvas>

<style>
  .spectrogram-canvas {
    display: block;
    width: 100%;
    height: 100%;
    user-select: none;
    -webkit-user-select: none;
  }

  .spectrogram-canvas:focus {
    outline: 2px solid #10b981;
    outline-offset: -2px;
  }

  .cursor-crosshair {
    cursor: crosshair;
  }

  .cursor-grab {
    cursor: grab;
  }

  .cursor-grabbing {
    cursor: grabbing;
  }

  .cursor-crosshair-zoom {
    cursor: crosshair;
  }
</style>
