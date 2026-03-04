<script lang="ts">
  import { onMount, onDestroy, untrack } from 'svelte';
  import { getSpectrogramUrl } from '$lib/api/recordings';
  import { apiClient } from '$lib/api/client';
  import type { SpectrogramWindow, SpectrogramPosition, SpectrogramChunk, InteractionMode } from '$lib/types/audio';
  import { SPECTROGRAM_CHUNK_DURATION, SPECTROGRAM_CHUNK_BUFFER } from '$lib/types/audio';
  import {
    intersectWindows,
    intersectIntervals,
    scaleInterval,
    pixelsToPosition,
    timeToPixel,
    adjustWindowToBounds,
    shiftWindow,
    expandWindow,
    centerWindowOn,
    zoomWindowToPosition,
    getViewportPosition,
    calculateChunkIntervals,
  } from '$lib/utils/viewport';
  import type { RecordingDetail } from '$lib/types/data';
  import type { SpectrogramSettings } from '$lib/types/audio';

  interface Props {
    recording: RecordingDetail;
    projectId: string;
    spectrogramSettings: SpectrogramSettings;
    viewport: SpectrogramWindow;
    bounds: SpectrogramWindow;
    currentTime: number;
    interactionMode: InteractionMode;
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
    onViewportChange,
    onViewportSave,
    onSeek,
    onModeChange,
  }: Props = $props();

  // Canvas references
  let canvas: HTMLCanvasElement | undefined = $state();
  let containerEl: HTMLDivElement | undefined = $state();

  // Canvas dimensions
  let canvasWidth = $state(0);
  let canvasHeight = $state(spectrogramSettings.height);

  // Mouse cursor state
  let mousePos: SpectrogramPosition | null = $state(null);

  // Drag/interaction state
  let isDragging = $state(false);
  let dragStart: { x: number; y: number; time: number; freq: number } | null = $state(null);
  let zoomBox: { start: SpectrogramPosition; end: SpectrogramPosition } | null = $state(null);

  // Spectrogram chunk state
  let chunks = $state<SpectrogramChunk[]>([]);
  // One HTMLImageElement per chunk; src is set lazily based on viewport proximity
  let chunkImages: HTMLImageElement[] = [];

  // Maximum number of retry attempts per chunk before giving up permanently
  const MAX_CHUNK_RETRIES = 3;
  // Delay (ms) before retrying a failed chunk to avoid hammering the server
  const CHUNK_RETRY_DELAY_MS = 1500;
  // Tracks setTimeout handles for pending retries, keyed by chunk index
  const retryTimers: Map<number, ReturnType<typeof setTimeout>> = new Map();
  // Guards against concurrent token refresh calls (thundering herd prevention)
  let tokenRefreshPromise: Promise<void> | null = null;

  // Animation frame handle
  let animFrameId: number | null = null;

  // Build a spectrogram URL for a single chunk including the auth token as a
  // query parameter. This allows the browser to load the image directly without
  // a custom fetch wrapper, which avoids keeping all chunks in memory as blobs.
  function buildChunkUrl(chunkBufferInterval: { min: number; max: number }): string {
    const effectiveSamplerate = recording.samplerate;
    const duration = recording.duration;
    const n_fft = Math.round(spectrogramSettings.window_size * effectiveSamplerate);
    const hop_length = Math.round(n_fft * (1 - spectrogramSettings.overlap));
    const freq_max = effectiveSamplerate / 2;

    const fullUrl = getSpectrogramUrl(projectId, recording.id, {
      start: Math.max(0, chunkBufferInterval.min),
      end: Math.min(duration, chunkBufferInterval.max),
      n_fft,
      hop_length,
      freq_min: 0,
      freq_max,
      colormap: spectrogramSettings.cmap,
      pcen: spectrogramSettings.pcen,
      channel: 0,
      width: 1200,
      height: spectrogramSettings.height,
    });

    // Extract path + query for the Vite proxy (avoids cross-origin issues)
    const parsed = new URL(fullUrl);
    const pathWithQuery = parsed.pathname + parsed.search;

    const token = apiClient.getAccessToken();
    if (token) {
      return `${pathWithQuery}&token=${encodeURIComponent(token)}`;
    }
    return pathWithQuery;
  }

  // Build all chunk metadata but do NOT start loading images yet.
  // Loading is deferred to triggerLazyLoad() which checks viewport proximity.
  function rebuildChunks() {
    // Cancel all pending retry timers from the previous set
    retryTimers.forEach((handle) => clearTimeout(handle));
    retryTimers.clear();

    // Cancel all pending image loads from the previous set
    chunkImages.forEach((img) => {
      img.onload = null;
      img.onerror = null;
      img.src = '';
    });

    const duration = recording.duration;

    const intervals = calculateChunkIntervals(
      duration,
      spectrogramSettings.window_size,
      spectrogramSettings.overlap,
      SPECTROGRAM_CHUNK_DURATION,
      SPECTROGRAM_CHUNK_BUFFER
    );

    chunks = intervals.map(({ index, interval, buffer }) => ({
      index,
      interval,
      buffer,
      isLoading: false,
      isReady: false,
      isError: false,
      retryCount: 0,
    }));

    // Create image elements without setting src — loading is triggered by triggerLazyLoad()
    chunkImages = intervals.map(({ index }) => {
      const img = new Image();

      img.onload = () => {
        chunks = chunks.map((c) =>
          c.index === index ? { ...c, isReady: true, isLoading: false, isError: false } : c
        );
        requestRedraw();
      };

      img.onerror = () => {
        chunks = chunks.map((c) => {
          if (c.index !== index) return c;
          const newRetryCount = c.retryCount + 1;
          return { ...c, isError: true, isLoading: false, isReady: false, retryCount: newRetryCount };
        });
        scheduleChunkRetry(index);
        requestRedraw();
      };

      return img;
    });

    // Immediately load chunks near the current viewport
    triggerLazyLoad();
  }

  /**
   * Schedule a delayed retry for a chunk that failed to load.
   * The retry is skipped if the chunk has exceeded MAX_CHUNK_RETRIES or if it
   * is no longer near the viewport when the timer fires.
   * A token refresh is attempted before retrying to handle expired JWT tokens.
   * Concurrent refresh calls are deduplicated via tokenRefreshPromise.
   */
  function scheduleChunkRetry(index: number) {
    // Clear any existing timer for this chunk
    const existing = retryTimers.get(index);
    if (existing !== undefined) {
      clearTimeout(existing);
    }

    const chunk = chunks.find((c) => c.index === index);
    if (!chunk || chunk.retryCount >= MAX_CHUNK_RETRIES) {
      // Exceeded retry limit — leave the chunk in the permanent error state
      return;
    }

    const handle = setTimeout(async () => {
      retryTimers.delete(index);

      // Refresh the auth token before retrying to handle expired JWT tokens.
      // Multiple concurrent retries share a single refresh call to avoid
      // hammering the auth endpoint (thundering herd prevention).
      if (!tokenRefreshPromise) {
        tokenRefreshPromise = apiClient.refreshToken().finally(() => {
          tokenRefreshPromise = null;
        });
      }
      try {
        await tokenRefreshPromise;
      } catch {
        // Refresh failed — proceed with retryChunk which will use whatever
        // token is currently available (may fail again and exhaust retries).
      }

      retryChunk(index);
    }, CHUNK_RETRY_DELAY_MS);

    retryTimers.set(index, handle);
  }

  /**
   * Immediately retry loading a single chunk.
   * If the chunk has already recovered or is being loaded, this is a no-op.
   */
  function retryChunk(index: number) {
    const chunk = chunks.find((c) => c.index === index);
    if (!chunk || chunk.isReady || chunk.isLoading) return;

    // Only retry chunks that are near the current viewport
    const loadZone = scaleInterval(viewport.time, 4);
    if (!intersectIntervals(chunk.interval, loadZone)) return;

    // Mark as loading and reset the image src to trigger a fresh request
    chunks = chunks.map((c) =>
      c.index === index ? { ...c, isLoading: true, isError: false } : c
    );

    const img = chunkImages[index];
    if (img) {
      img.src = '';
      img.src = buildChunkUrl(chunk.buffer);
    }
  }

  /**
   * Refresh the auth token and then retry all chunks that are in the error
   * state and have not yet exceeded the retry limit.  Called when a token
   * refresh is needed before re-attempting spectrogram image loads.
   */
  async function refreshTokenAndRetryErrors() {
    try {
      await apiClient.refreshToken();
    } catch {
      // Refresh failed; leave chunks in their current state
      return;
    }

    // After a successful refresh, immediately retry all eligible error chunks
    chunks.forEach((chunk) => {
      if (chunk.isError && chunk.retryCount < MAX_CHUNK_RETRIES) {
        retryChunk(chunk.index);
      }
    });
  }

  // Expose for external use if needed (e.g., parent can call after auth update)
  export { refreshTokenAndRetryErrors };

  // Load chunks whose time interval overlaps with the viewport expanded by
  // a factor of 4 (2 chunks ahead and behind), matching the old/ strategy.
  // Chunks that are already loading or ready are skipped.
  // Chunks in the error state are re-queued for a delayed retry if they
  // have not yet exceeded MAX_CHUNK_RETRIES and are near the viewport.
  function triggerLazyLoad() {
    const loadZone = scaleInterval(viewport.time, 4);

    chunks.forEach((chunk) => {
      if (chunk.isLoading || chunk.isReady) return;

      const near = intersectIntervals(chunk.interval, loadZone);
      if (!near) return;

      if (chunk.isError) {
        // Schedule a retry if the chunk has not exceeded the limit and there
        // is not already a timer pending for it.
        if (chunk.retryCount < MAX_CHUNK_RETRIES && !retryTimers.has(chunk.index)) {
          scheduleChunkRetry(chunk.index);
        }
        return;
      }

      // Mark as loading and set the image src
      chunks = chunks.map((c) =>
        c.index === chunk.index ? { ...c, isLoading: true } : c
      );

      const img = chunkImages[chunk.index];
      if (img && !img.src) {
        img.src = buildChunkUrl(chunk.buffer);
      }
    });
  }

  // Build spectrogram chunk images when recording or settings change.
  // The dependency list is tightly controlled to avoid spurious rebuilds:
  // only recording identity and spectrogram parameters trigger a full rebuild.
  // rebuildChunks() reads/writes `chunks` internally, so we call it inside
  // untrack() to prevent an infinite reactive loop.
  $effect(() => {
    // Track only the parameters that require a fresh set of chunk images
    const _recordingId = recording.id;
    const _windowSize = spectrogramSettings.window_size;
    const _overlap = spectrogramSettings.overlap;
    const _cmap = spectrogramSettings.cmap;
    const _pcen = spectrogramSettings.pcen;
    const _height = spectrogramSettings.height;

    // Suppress unused-variable warnings — these are read only to register deps
    void _recordingId; void _windowSize; void _overlap; void _cmap; void _pcen; void _height;

    untrack(() => rebuildChunks());
  });

  // When the viewport moves, trigger lazy loading for newly visible chunks.
  // This is intentionally a separate effect so it does not cause a full rebuild.
  // triggerLazyLoad() reads/writes `chunks`, so we untrack to avoid a loop.
  $effect(() => {
    const _viewport = viewport;
    void _viewport;
    untrack(() => triggerLazyLoad());
  });

  // Redraw canvas on every render-relevant state change
  $effect(() => {
    // Read reactive dependencies
    const _vp = viewport;
    const _ct = currentTime;
    const _mp = mousePos;
    const _zb = zoomBox;
    const _chunks = chunks;
    const _mode = interactionMode;
    void _vp; void _ct; void _mp; void _zb; void _chunks; void _mode;
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

  function requestRedraw() {
    if (animFrameId !== null) return;
    animFrameId = requestAnimationFrame(drawAll);
  }

  function drawAll() {
    animFrameId = null;
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

  // ============================================
  // Event Handlers
  // ============================================

  function getCanvasPos(e: MouseEvent): { x: number; y: number } {
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    return {
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
    };
  }

  function handleMouseMove(e: MouseEvent) {
    const { x, y } = getCanvasPos(e);
    mousePos = pixelsToPosition(x, y, canvasWidth, canvasHeight, viewport);

    if (isDragging && dragStart && interactionMode === 'panning') {
      // Pan the viewport
      const dx = x - dragStart.x;
      const dy = y - dragStart.y;
      const timeDelta = -(dx / canvasWidth) * (viewport.time.max - viewport.time.min);
      const freqDelta = (dy / canvasHeight) * (viewport.freq.max - viewport.freq.min);

      const newViewport = adjustWindowToBounds(
        shiftWindow(viewport, { time: timeDelta, freq: freqDelta }),
        bounds
      );
      onViewportChange?.(newViewport);

      // Reset drag origin to current so delta is incremental
      dragStart = { x, y, time: mousePos.time, freq: mousePos.freq };
    } else if (isDragging && dragStart && interactionMode === 'zooming') {
      zoomBox = {
        start: { time: dragStart.time, freq: dragStart.freq },
        end: mousePos,
      };
    }
  }

  function handleMouseDown(e: MouseEvent) {
    if (e.button !== 0) return;
    const { x, y } = getCanvasPos(e);
    const pos = pixelsToPosition(x, y, canvasWidth, canvasHeight, viewport);
    isDragging = true;
    dragStart = { x, y, time: pos.time, freq: pos.freq };

    if (interactionMode === 'panning') {
      onViewportSave?.();
    } else if (interactionMode === 'zooming') {
      zoomBox = { start: pos, end: pos };
    }
  }

  function handleMouseUp(e: MouseEvent) {
    if (!isDragging) return;

    if (interactionMode === 'zooming' && zoomBox) {
      const { start, end } = zoomBox;
      const timeSorted = [start.time, end.time].toSorted((a, b) => a - b);
      const freqSorted = [start.freq, end.freq].toSorted((a, b) => a - b);

      const t0 = timeSorted[0] ?? 0;
      const t1 = timeSorted[1] ?? 0;
      const f0 = freqSorted[0] ?? 0;
      const f1 = freqSorted[1] ?? 0;
      if (t1 > t0 && f1 > f0) {
        const zoomedWindow: SpectrogramWindow = {
          time: { min: t0, max: t1 },
          freq: { min: f0, max: f1 },
        };
        onViewportSave?.();
        onViewportChange?.(adjustWindowToBounds(zoomedWindow, bounds));
        // After zoom, switch to panning mode
        onModeChange?.('panning');
      }
    }

    isDragging = false;
    dragStart = null;
    zoomBox = null;
  }

  function handleMouseLeave() {
    mousePos = null;
    if (isDragging) {
      isDragging = false;
      dragStart = null;
      zoomBox = null;
    }
  }

  function handleDoubleClick(e: MouseEvent) {
    const { x, y } = getCanvasPos(e);
    const pos = pixelsToPosition(x, y, canvasWidth, canvasHeight, viewport);
    onSeek?.(pos.time);
  }

  function handleWheel(e: WheelEvent) {
    e.preventDefault();
    const { x, y } = getCanvasPos(e);
    const pos = pixelsToPosition(x, y, canvasWidth, canvasHeight, viewport);

    const timeFrac = (viewport.time.max - viewport.time.min) * 0.05;
    const freqFrac = (viewport.freq.max - viewport.freq.min) * 0.05;

    const deltaX = e.deltaX;
    const deltaY = e.deltaY;

    let newViewport: SpectrogramWindow;

    if (e.altKey) {
      // Zoom toward cursor position
      const factor = 1 + 4 * timeFrac * (e.shiftKey ? deltaX : deltaY) / (canvasWidth * timeFrac);
      newViewport = adjustWindowToBounds(
        zoomWindowToPosition(viewport, pos, Math.max(0.1, factor)),
        bounds
      );
    } else if (e.ctrlKey) {
      // Expand/contract viewport
      newViewport = adjustWindowToBounds(
        expandWindow(viewport, {
          time: timeFrac * (e.shiftKey ? deltaX : deltaY) * 0.1,
          freq: freqFrac * (e.shiftKey ? deltaY : deltaX) * 0.1,
        }),
        bounds
      );
    } else {
      // Scroll time/frequency
      newViewport = adjustWindowToBounds(
        shiftWindow(viewport, {
          time: timeFrac * (e.shiftKey ? deltaY : deltaX) * 0.1,
          freq: -freqFrac * (e.shiftKey ? deltaX : deltaY) * 0.1,
        }),
        bounds
      );
    }

    onViewportChange?.(newViewport);
  }

  function handleKeyDown(e: KeyboardEvent) {
    // Only handle if canvas is focused
    if (document.activeElement !== canvas && document.activeElement !== containerEl) return;

    switch (e.key.toLowerCase()) {
      case 'x':
        onModeChange?.('panning');
        break;
      case 'z':
        onModeChange?.('zooming');
        break;
      case 'b':
        // Back is handled by parent
        break;
    }
  }

  onMount(() => {
    rebuildChunks();
  });

  onDestroy(() => {
    if (animFrameId !== null) cancelAnimationFrame(animFrameId);
    // Cancel all pending retry timers
    retryTimers.forEach((handle) => clearTimeout(handle));
    retryTimers.clear();
    // Clear all image sources to cancel any pending network requests
    chunkImages.forEach((img) => {
      img.onload = null;
      img.onerror = null;
      img.src = '';
    });
    chunkImages = [];
  });
</script>

<svelte:window onkeydown={handleKeyDown} />

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
    class:cursor-crosshair={interactionMode === 'idle'}
    class:cursor-grab={interactionMode === 'panning' && !isDragging}
    class:cursor-grabbing={interactionMode === 'panning' && isDragging}
    class:cursor-crosshair-zoom={interactionMode === 'zooming'}
    tabindex="0"
    role="img"
    aria-label="Spectrogram visualization"
    onmousemove={handleMouseMove}
    onmousedown={handleMouseDown}
    onmouseup={handleMouseUp}
    onmouseleave={handleMouseLeave}
    ondblclick={handleDoubleClick}
    onwheel={handleWheel}
  ></canvas>

  {#if mousePos}
    <div class="cursor-info">
      <span>{mousePos.time.toFixed(3)}s</span>
      <span>{(mousePos.freq / 1000).toFixed(1)} kHz</span>
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
