/**
 * useChunkManager — Svelte 5 runes hook that owns spectrogram chunk state,
 * lazy-loading, and retry/token-refresh logic.
 *
 * Extracted from SpectrogramViewer.svelte as Step 1 of the P2-B refactor
 * (see plan.md §4). The hook deliberately exposes `chunks` as a reactive
 * getter and does NOT drive redraws directly — consumers observe
 * `chunkMgr.chunks` inside their own `$effect` and call their scheduler.
 */
import { onDestroy, untrack } from 'svelte';
import { getSpectrogramUrl } from '$lib/api/recordings';
import { apiClient } from '$lib/api/client';
import type { SpectrogramChunk } from '$lib/types/audio';
import { SPECTROGRAM_CHUNK_DURATION, SPECTROGRAM_CHUNK_BUFFER } from '$lib/types/audio';
import { intersectIntervals, scaleInterval, calculateChunkIntervals } from '$lib/utils/viewport';
import type { ChunkManagerInput, ChunkManagerApi } from './types';

// Maximum number of retry attempts per chunk before giving up permanently
const MAX_CHUNK_RETRIES = 3;
// Delay (ms) before retrying a failed chunk to avoid hammering the server
const CHUNK_RETRY_DELAY_MS = 1500;

export function useChunkManager(input: ChunkManagerInput): ChunkManagerApi {
  // Reactive chunk metadata — consumers observe this via the getter below.
  let chunks = $state<SpectrogramChunk[]>([]);
  // One HTMLImageElement per chunk; src is set lazily based on viewport proximity.
  // Kept as a plain (non-reactive) parallel array — identity is stable across
  // rebuilds and image.complete/naturalWidth are read synchronously at draw time.
  let chunkImages: HTMLImageElement[] = [];
  // Tracks setTimeout handles for pending retries, keyed by chunk index.
  const retryTimers: Map<number, ReturnType<typeof setTimeout>> = new Map();
  // Guards against concurrent token refresh calls (thundering herd prevention).
  let tokenRefreshPromise: Promise<void> | null = null;
  // Set to true in dispose(); every async continuation checks this before
  // touching state to avoid operating on a torn-down hook.
  let disposed = false;

  // Build a spectrogram URL for a single chunk including the auth token as a
  // query parameter. This allows the browser to load the image directly without
  // a custom fetch wrapper, which avoids keeping all chunks in memory as blobs.
  function buildChunkUrl(chunkBufferInterval: { min: number; max: number }): string {
    const recording = input.recording();
    const spectrogramSettings = input.spectrogramSettings();
    const projectId = input.projectId();

    const effectiveSamplerate = recording.samplerate;
    const duration = recording.duration;
    const n_fft = Math.round(spectrogramSettings.window_size * effectiveSamplerate);
    const hop_length = Math.round(n_fft * (1 - spectrogramSettings.overlap));
    // Must match bounds.freq.max consumed by SpectrogramCanvas draw code.
    // Both are expected to equal Nyquist for the viewport to render correctly.
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
    if (disposed) return;

    // Cancel all pending retry timers from the previous set
    retryTimers.forEach((handle) => clearTimeout(handle));
    retryTimers.clear();

    // Cancel all pending image loads from the previous set
    chunkImages.forEach((img) => {
      img.onload = null;
      img.onerror = null;
      img.src = '';
    });

    const recording = input.recording();
    const spectrogramSettings = input.spectrogramSettings();
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
        if (disposed) return;
        chunks = chunks.map((c) =>
          c.index === index ? { ...c, isReady: true, isLoading: false, isError: false } : c
        );
      };

      img.onerror = () => {
        if (disposed) return;
        chunks = chunks.map((c) => {
          if (c.index !== index) return c;
          const newRetryCount = c.retryCount + 1;
          return { ...c, isError: true, isLoading: false, isReady: false, retryCount: newRetryCount };
        });
        scheduleChunkRetry(index);
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
    if (disposed) return;

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
      if (disposed) return;
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

      if (disposed) return;
      retryChunk(index);
    }, CHUNK_RETRY_DELAY_MS);

    retryTimers.set(index, handle);
  }

  /**
   * Immediately retry loading a single chunk.
   * If the chunk has already recovered or is being loaded, this is a no-op.
   */
  function retryChunk(index: number) {
    if (disposed) return;

    const chunk = chunks.find((c) => c.index === index);
    if (!chunk || chunk.isReady || chunk.isLoading) return;

    // Only retry chunks that are near the current viewport
    const viewport = input.viewport();
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
    if (disposed) return;
    try {
      await apiClient.refreshToken();
    } catch {
      // Refresh failed; leave chunks in their current state
      return;
    }

    if (disposed) return;
    // After a successful refresh, immediately retry all eligible error chunks
    chunks.forEach((chunk) => {
      if (chunk.isError && chunk.retryCount < MAX_CHUNK_RETRIES) {
        retryChunk(chunk.index);
      }
    });
  }

  // Load chunks whose time interval overlaps with the viewport expanded by
  // a factor of 4 (2 chunks ahead and behind), matching the old/ strategy.
  // Chunks that are already loading or ready are skipped.
  // Chunks in the error state are re-queued for a delayed retry if they
  // have not yet exceeded MAX_CHUNK_RETRIES and are near the viewport.
  function triggerLazyLoad() {
    if (disposed) return;

    const viewport = input.viewport();
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
    const _recordingId = input.recording().id;
    const s = input.spectrogramSettings();
    const _windowSize = s.window_size;
    const _overlap = s.overlap;
    const _cmap = s.cmap;
    const _pcen = s.pcen;
    const _height = s.height;

    // Suppress unused-variable warnings — these are read only to register deps
    void _recordingId; void _windowSize; void _overlap; void _cmap; void _pcen; void _height;

    untrack(() => rebuildChunks());
  });

  // When the viewport moves, trigger lazy loading for newly visible chunks.
  // This is intentionally a separate effect so it does not cause a full rebuild.
  // triggerLazyLoad() reads/writes `chunks`, so we untrack to avoid a loop.
  $effect(() => {
    const _viewport = input.viewport();
    void _viewport;
    untrack(() => triggerLazyLoad());
  });

  function dispose() {
    if (disposed) return;
    disposed = true;
    // Cancel all pending retry timers
    retryTimers.forEach((handle) => clearTimeout(handle));
    retryTimers.clear();
    // Detach handlers and clear image sources to cancel any pending network requests
    chunkImages.forEach((img) => {
      img.onload = null;
      img.onerror = null;
      img.src = '';
    });
    chunkImages = [];
  }

  onDestroy(dispose);

  return {
    get chunks() {
      return chunks;
    },
    get chunkImages() {
      return chunkImages;
    },
    refreshTokenAndRetryErrors,
    dispose,
  };
}
