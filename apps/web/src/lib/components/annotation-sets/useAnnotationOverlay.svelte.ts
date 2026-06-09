/**
 * useAnnotationOverlay — Svelte 5 runes hook that owns MODE-AWARE pointer
 * dispatch for the AnnotationEditor spectrogram overlay.
 *
 * The annotation overlay sits above `ClipSpectrogramPlayer`'s spectrogram with
 * `pointer-events-auto`, so the dataset viewer's own pan/zoom/seek handlers
 * never receive events. This hook therefore becomes the sole interaction
 * surface and reproduces the dataset-viewer navigation gestures on top of the
 * existing annotate/seek behaviour, dispatching purely by `mode`:
 *
 *   - annotating (default): delegates mousedown to the draft hook. A drag draws
 *     a draft range; a click (<5px) seeks the playhead. (Handled entirely by
 *     `useAnnotationDraft`; this hook just forwards the event.)
 *   - panning: left-drag pans the shared viewport. Uses incremental
 *     `shiftWindow` deltas + `adjustWindowToBounds`, mirroring
 *     `useSpectrogramInteraction.handleMouseMove`.
 *   - zooming: left-drag draws a horizontal zoom box (time axis only — the
 *     overlay represents the time axis); on mouseup, zoom-to-box on the time
 *     range while preserving the current frequency window, then return to
 *     `annotating`.
 *
 * The hook owns its OWN window mousemove/mouseup listeners (separate from the
 * draft hook's) but they early-return unless a pan/zoom gesture is in flight,
 * so the two hooks never fight over the same gesture.
 */
import { onDestroy } from 'svelte';
import type { SpectrogramWindow } from '$lib/types/audio';
import {
  pixelsToPosition,
  timeToPixel,
  shiftWindow,
  adjustWindowToBounds,
} from '$lib/utils/viewport';
import type { OverlayHookApi, OverlayHookInput, AnnotationZoomBox } from './types';

export function useAnnotationOverlay(input: OverlayHookInput): OverlayHookApi {
  // Pan/zoom drag state. `null` when no pan/zoom gesture is active. We store
  // the pixel origin (for incremental pan deltas) plus the data-space origin
  // (for the zoom box). `annotating`-mode gestures are NOT tracked here — they
  // are owned by the draft hook.
  let dragStart = $state<{ x: number; y: number; time: number; freq: number } | null>(
    null,
  );
  // Active zoom-box selection in spectrogram coordinates, or null.
  let zoomBox = $state<AnnotationZoomBox | null>(null);

  let disposed = false;

  /** Pixel x/y of a pointer event relative to the overlay's top-left. */
  function getOverlayPos(e: MouseEvent): { x: number; y: number } {
    const overlayEl = input.overlayEl();
    if (!overlayEl) return { x: 0, y: 0 };
    const rect = overlayEl.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  function onMouseDown(e: MouseEvent) {
    if (disposed) return;
    const mode = input.mode();

    // In annotate mode the draft hook owns the gesture entirely.
    if (mode === 'annotating') {
      input.onAnnotateMouseDown(e);
      return;
    }

    // Pan / zoom gestures are left-button only.
    if (e.button !== 0) return;
    e.preventDefault();

    const viewport = input.viewport();
    const canvasWidth = input.canvasWidth();
    const canvasHeight = input.canvasHeight();
    const { x, y } = getOverlayPos(e);
    const pos = pixelsToPosition(x, y, canvasWidth, canvasHeight, viewport);
    dragStart = { x, y, time: pos.time, freq: pos.freq };

    if (mode === 'panning') {
      input.onViewportSave?.();
    } else if (mode === 'zooming') {
      zoomBox = { start: pos, end: pos };
    }
  }

  function onWindowMouseMove(e: MouseEvent) {
    if (disposed) return;
    if (!dragStart) return;
    const mode = input.mode();
    const viewport = input.viewport();
    const bounds = input.bounds();
    const canvasWidth = input.canvasWidth();
    const canvasHeight = input.canvasHeight();
    if (canvasWidth <= 0) return;

    const { x, y } = getOverlayPos(e);
    const pos = pixelsToPosition(x, y, canvasWidth, canvasHeight, viewport);

    if (mode === 'panning') {
      // Incremental pan: convert the pixel delta since the last move into a
      // time/freq shift, then clamp within the clip bounds. Reset the drag
      // origin so the next move is again incremental (matches the dataset
      // viewer's pan).
      const dx = x - dragStart.x;
      const dy = y - dragStart.y;
      const timeDelta = -(dx / canvasWidth) * (viewport.time.max - viewport.time.min);
      const freqDelta = (dy / canvasHeight) * (viewport.freq.max - viewport.freq.min);
      const next = adjustWindowToBounds(
        shiftWindow(viewport, { time: timeDelta, freq: freqDelta }),
        bounds,
      );
      input.onViewportChange(next);
      dragStart = { x, y, time: pos.time, freq: pos.freq };
    } else if (mode === 'zooming') {
      zoomBox = { start: { time: dragStart.time, freq: dragStart.freq }, end: pos };
    }
  }

  function onWindowMouseUp() {
    if (disposed) return;
    if (!dragStart) return;
    const mode = input.mode();
    const viewport = input.viewport();
    const bounds = input.bounds();

    if (mode === 'zooming' && zoomBox) {
      const t0 = Math.min(zoomBox.start.time, zoomBox.end.time);
      const t1 = Math.max(zoomBox.start.time, zoomBox.end.time);
      // Time axis only: zoom the horizontal range while preserving the current
      // frequency window (the overlay represents the time axis; the annotation
      // boxes span full height). Guard against a degenerate zero-width box.
      if (t1 > t0) {
        const zoomed: SpectrogramWindow = {
          time: { min: t0, max: t1 },
          freq: { ...viewport.freq },
        };
        input.onViewportSave?.();
        input.onViewportChange(adjustWindowToBounds(zoomed, bounds));
        // After a successful zoom, return to annotate mode (mirrors the dataset
        // viewer returning to panning after a zoom-to-box).
        input.onModeChange?.('annotating');
      }
    }

    dragStart = null;
    zoomBox = null;
  }

  // A single window-listener effect for the pan/zoom state machine. Listeners
  // detach on hot-reload re-runs and on parent unmount.
  $effect(() => {
    window.addEventListener('mousemove', onWindowMouseMove);
    window.addEventListener('mouseup', onWindowMouseUp);
    return () => {
      window.removeEventListener('mousemove', onWindowMouseMove);
      window.removeEventListener('mouseup', onWindowMouseUp);
    };
  });

  // Pixel geometry for the transient zoom-box rectangle (time axis → px via the
  // live viewport transform). `null` outside a zoom gesture; width clamped to
  // non-negative and the overlay container clips overflow.
  const zoomBoxPx = $derived.by<{ left: number; width: number } | null>(() => {
    if (!zoomBox) return null;
    const canvasWidth = input.canvasWidth();
    const viewport = input.viewport();
    if (canvasWidth <= 0) return null;
    const a = timeToPixel(zoomBox.start.time, canvasWidth, viewport);
    const b = timeToPixel(zoomBox.end.time, canvasWidth, viewport);
    const left = Math.max(0, Math.min(a, b));
    const width = Math.max(0, Math.abs(b - a));
    return { left, width };
  });

  function dispose() {
    if (disposed) return;
    disposed = true;
  }

  onDestroy(dispose);

  return {
    get zoomBoxPx() {
      return zoomBoxPx;
    },
    handlers: {
      onMouseDown,
    },
    dispose,
  };
}
