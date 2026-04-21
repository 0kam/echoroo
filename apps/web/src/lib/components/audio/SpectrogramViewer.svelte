<script lang="ts">
  import { onDestroy, untrack } from 'svelte';
  import type { SpectrogramWindow, InteractionMode } from '$lib/types/audio';
  import {
    intersectWindows,
    intersectIntervals,
    timeToPixel,
    getViewportPosition,
  } from '$lib/utils/viewport';
  import type { RecordingDetail } from '$lib/types/data';
  import type { SpectrogramSettings } from '$lib/types/audio';
  import { createSpectrogramScheduler } from './useSpectrogramScheduler';
  import { useChunkManager } from './useChunkManager.svelte';
  import { useSpectrogramInteraction } from './useSpectrogramInteraction.svelte';

  interface Props {
    recording: RecordingDetail;
    projectId: string;
    spectrogramSettings: SpectrogramSettings;
    viewport: SpectrogramWindow;
    bounds: SpectrogramWindow;
    currentTime: number;
    interactionMode: InteractionMode;
    /**
     * When true, all mouse interaction (pan, zoom, seek, crosshair) is disabled.
     * The spectrogram renders identically but the user cannot navigate or seek.
     */
    readonly?: boolean;
    onViewportChange?: (viewport: SpectrogramWindow) => void;
    onViewportSave?: () => void;
    onSeek?: (time: number) => void;
    onModeChange?: (mode: InteractionMode) => void;
  }

  let {
    recording,
    projectId,
    spectrogramSettings,
    viewport,
    bounds,
    currentTime,
    interactionMode,
    readonly = false,
    onViewportChange,
    onViewportSave,
    onSeek,
    onModeChange,
  }: Props = $props();

  // Canvas references
  let canvas: HTMLCanvasElement | undefined = $state();
  let containerEl: HTMLDivElement | undefined = $state();

  // Canvas dimensions — initial height is taken from settings once; the
  // $effect that reacts to settings.height later updates this value.
  let canvasWidth = $state(0);
  let canvasHeight = $state(untrack(() => spectrogramSettings.height));

  // Spectrogram chunk state is owned by the chunk-manager hook.
  // The hook reactively rebuilds on recording/settings changes and lazy-loads
  // on viewport changes. Consumers (this parent) observe `chunkMgr.chunks`
  // inside a redraw $effect below to request canvas redraws.
  const chunkMgr = useChunkManager({
    recording: () => recording,
    projectId: () => projectId,
    spectrogramSettings: () => spectrogramSettings,
    viewport: () => viewport,
  });

  // Interaction state (mouse/wheel/keyboard) is owned by the interaction hook.
  // The canvas element and its event-prop wiring remain here in the parent;
  // the hook only manages the drag/zoom state machine and exposes reactive
  // getters (`mousePos`, `zoomBox`, `isDragging`) that drive crosshair /
  // zoom-box drawing.
  //
  // Note: `B` (viewport history back) is NOT handled by this hook — the
  // parent route owns the viewport history stack and handles B via its own
  // `svelte:window onkeydown`.
  const interaction = useSpectrogramInteraction({
    canvas: () => canvas,
    containerEl: () => containerEl,
    viewport: () => viewport,
    bounds: () => bounds,
    canvasWidth: () => canvasWidth,
    canvasHeight: () => canvasHeight,
    spectrogramSettings: () => spectrogramSettings,
    interactionMode: () => interactionMode,
    readonly: () => readonly,
    // Wrap callbacks in closures so the hook always reads the current prop
    // value (destructured $props bindings are frozen at destructure time).
    onViewportChange: (vp) => onViewportChange?.(vp),
    onViewportSave: () => onViewportSave?.(),
    onSeek: (time) => onSeek?.(time),
    onModeChange: (mode) => onModeChange?.(mode),
  });

  /**
   * Refresh the auth token and retry all chunks currently in the error state.
   * Thin wrapper preserved for external callers that already use this export.
   */
  export function refreshTokenAndRetryErrors() {
    return chunkMgr.refreshTokenAndRetryErrors();
  }

  // RAF scheduler — coalesces redraw requests into one frame.
  // Initialized lazily so `drawAll` is hoisted by the time it's invoked.
  const scheduler = createSpectrogramScheduler(() => drawAll());

  function requestRedraw() {
    scheduler.request();
  }

  // Redraw canvas on every render-relevant state change.
  // Observes `chunkMgr.chunks` (a reactive getter from the chunk hook) and
  // `interaction.{mousePos,zoomBox,isDragging}` (reactive getters from the
  // interaction hook) so that chunk image loads / errors / retries and
  // cursor / drag state changes trigger a fresh draw.
  $effect(() => {
    // Read reactive dependencies
    const _vp = viewport;
    const _ct = currentTime;
    const _mp = interaction.mousePos;
    const _zb = interaction.zoomBox;
    const _dr = interaction.isDragging;
    const _chunks = chunkMgr.chunks;
    const _mode = interactionMode;
    const _w = canvasWidth;
    const _h = canvasHeight;
    void _vp; void _ct; void _mp; void _zb; void _dr; void _chunks; void _mode; void _w; void _h;
    requestRedraw();
  });

  // Resize canvas to match container
  $effect(() => {
    if (!canvas) return;
    canvas.width = canvasWidth;
    canvas.height = spectrogramSettings.height;
    canvasHeight = spectrogramSettings.height;
    requestRedraw();
  });

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
    const effectiveSamplerate = recording.samplerate;
    const maxFreq = effectiveSamplerate / 2;
    const fullFreq: SpectrogramWindow = { time: viewport.time, freq: { min: 0, max: maxFreq } };
    void fullFreq;

    chunkMgr.chunks.forEach((chunk, idx) => {
      const img = chunkMgr.chunkImages[idx];
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
    const mousePos = interaction.mousePos;
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
    const zoomBox = interaction.zoomBox;
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

  onDestroy(() => {
    scheduler.dispose();
    // Chunk / image / retry-timer cleanup is handled by useChunkManager's
    // own onDestroy. Interaction cleanup is handled by
    // useSpectrogramInteraction's own onDestroy. No duplication needed here.
  });
</script>

<svelte:window onkeydown={interaction.handleKeyDown} />

<div
  bind:this={containerEl}
  class="spectrogram-container"
  style="height: {spectrogramSettings.height}px;"
  bind:clientWidth={canvasWidth}
>
  <canvas
    bind:this={canvas}
    width={canvasWidth}
    height={spectrogramSettings.height}
    class="spectrogram-canvas"
    class:cursor-crosshair={!readonly && interactionMode === 'idle'}
    class:cursor-grab={!readonly && interactionMode === 'panning' && !interaction.isDragging}
    class:cursor-grabbing={!readonly && interactionMode === 'panning' && interaction.isDragging}
    class:cursor-crosshair-zoom={!readonly && interactionMode === 'zooming'}
    tabindex={readonly ? undefined : 0}
    aria-label="Spectrogram visualization"
    onmousemove={interaction.handleMouseMove}
    onmousedown={interaction.handleMouseDown}
    onmouseup={interaction.handleMouseUp}
    onmouseleave={interaction.handleMouseLeave}
    ondblclick={interaction.handleDoubleClick}
    onwheel={interaction.handleWheel}
  ></canvas>

  {#if interaction.mousePos}
    <div class="cursor-info">
      <span>{interaction.mousePos.time.toFixed(3)}s</span>
      <span>{(interaction.mousePos.freq / 1000).toFixed(1)} kHz</span>
    </div>
  {/if}
</div>

<style>
  .spectrogram-container {
    position: relative;
    width: 100%;
    background: #1c1917;
    border-radius: 0.375rem;
    overflow: hidden;
  }

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

  .cursor-info {
    position: absolute;
    bottom: 0.5rem;
    right: 0.5rem;
    display: flex;
    gap: 0.5rem;
    padding: 0.25rem 0.5rem;
    background: rgba(0, 0, 0, 0.6);
    color: rgba(255, 255, 255, 0.9);
    font-size: 0.75rem;
    font-family: monospace;
    border-radius: 0.25rem;
    pointer-events: none;
  }
</style>
