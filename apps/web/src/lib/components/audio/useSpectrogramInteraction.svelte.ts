/**
 * useSpectrogramInteraction — Svelte 5 runes hook that owns mouse/wheel/keyboard
 * interaction state for the spectrogram viewer.
 *
 * Extracted from SpectrogramViewer.svelte as Step 2 of the P2-B refactor
 * (see plan.md §5). The hook exposes reactive getters for `mousePos`,
 * `zoomBox`, and `isDragging` so that consumers can observe them from a
 * redraw `$effect`. The canvas element itself and its event wiring remain
 * owned by the parent — this hook only manages the interaction logic.
 *
 * Responsibilities:
 *   - Pan / zoom-box drag state machine
 *   - Wheel-based scroll / expand / zoom-to-cursor
 *   - Double-click seek
 *   - Keyboard mode switching (X → panning, Z → zooming)
 *
 * Explicitly NOT handled here:
 *   - `B` (viewport history back) — parent route owns the viewport history
 *     stack, so B is processed by the parent page's `svelte:window onkeydown`.
 */
import { onDestroy } from 'svelte';
import type {
  SpectrogramWindow,
  SpectrogramPosition,
} from '$lib/types/audio';
import {
  pixelsToPosition,
  adjustWindowToBounds,
  shiftWindow,
  applyWheelToViewport,
} from '$lib/utils/viewport';
import type {
  SpectrogramInteractionInput,
  SpectrogramInteractionApi,
  ZoomBox,
} from './types';

export function useSpectrogramInteraction(
  input: SpectrogramInteractionInput,
): SpectrogramInteractionApi {
  // Mouse cursor position in spectrogram coordinates (seconds / Hz).
  let mousePos = $state<SpectrogramPosition | null>(null);

  // Drag / interaction state. `dragStart` tracks both pixel and data-space
  // origins so incremental pan deltas can be computed without re-reading the
  // viewport state.
  let isDragging = $state(false);
  let dragStart = $state<{ x: number; y: number; time: number; freq: number } | null>(null);
  let zoomBox = $state<ZoomBox | null>(null);

  // Set to true in dispose(). All handlers are currently synchronous, but we
  // keep the guard for consistency with useChunkManager and to be safe if any
  // future handler schedules async work.
  let disposed = false;

  function getCanvasPos(e: MouseEvent): { x: number; y: number } {
    const canvas = input.canvas();
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    return {
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
    };
  }

  function handleMouseMove(e: MouseEvent) {
    if (disposed) return;
    if (input.readonly()) return;
    const viewport = input.viewport();
    const bounds = input.bounds();
    const canvasWidth = input.canvasWidth();
    const canvasHeight = input.canvasHeight();
    const interactionMode = input.interactionMode();

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
      input.onViewportChange(newViewport);

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
    if (disposed) return;
    if (input.readonly() || e.button !== 0) return;
    const viewport = input.viewport();
    const canvasWidth = input.canvasWidth();
    const canvasHeight = input.canvasHeight();
    const interactionMode = input.interactionMode();

    const { x, y } = getCanvasPos(e);
    const pos = pixelsToPosition(x, y, canvasWidth, canvasHeight, viewport);
    isDragging = true;
    dragStart = { x, y, time: pos.time, freq: pos.freq };

    if (interactionMode === 'panning') {
      input.onViewportSave?.();
    } else if (interactionMode === 'zooming') {
      zoomBox = { start: pos, end: pos };
    }
  }

  function handleMouseUp(_e: MouseEvent) {
    if (disposed) return;
    if (!isDragging) return;

    const bounds = input.bounds();
    const interactionMode = input.interactionMode();

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
        input.onViewportSave?.();
        input.onViewportChange(adjustWindowToBounds(zoomedWindow, bounds));
        // After zoom, switch to panning mode
        input.onModeChange?.('panning');
      }
    }

    isDragging = false;
    dragStart = null;
    zoomBox = null;
  }

  function handleMouseLeave() {
    if (disposed) return;
    mousePos = null;
    if (isDragging) {
      isDragging = false;
      dragStart = null;
      zoomBox = null;
    }
  }

  function handleDoubleClick(e: MouseEvent) {
    if (disposed) return;
    if (input.readonly()) return;
    const viewport = input.viewport();
    const canvasWidth = input.canvasWidth();
    const canvasHeight = input.canvasHeight();

    const { x, y } = getCanvasPos(e);
    const pos = pixelsToPosition(x, y, canvasWidth, canvasHeight, viewport);
    input.onSeek?.(pos.time);
  }

  function handleWheel(e: WheelEvent) {
    if (disposed) return;
    if (input.readonly()) return;
    e.preventDefault();
    const viewport = input.viewport();
    const bounds = input.bounds();
    const canvasWidth = input.canvasWidth();
    const canvasHeight = input.canvasHeight();

    const { x, y } = getCanvasPos(e);
    const pos = pixelsToPosition(x, y, canvasWidth, canvasHeight, viewport);

    // Shared wheel math (pan / Ctrl-expand / Alt-zoom) — also used by the
    // annotation overlay so both surfaces navigate identically.
    input.onViewportChange(applyWheelToViewport(e, viewport, bounds, pos, canvasWidth));
  }

  function handleKeyDown(e: KeyboardEvent) {
    // Only X / Z are handled here. `B` (viewport history back) is NOT handled
    // in this hook — the parent route owns the viewport history stack and
    // processes B via its own `svelte:window onkeydown`.
    if (disposed) return;
    if (input.readonly()) return;
    const canvas = input.canvas();
    const containerEl = input.containerEl();
    if (document.activeElement !== canvas && document.activeElement !== containerEl) return;

    switch (e.key.toLowerCase()) {
      case 'x':
        input.onModeChange?.('panning');
        break;
      case 'z':
        input.onModeChange?.('zooming');
        break;
    }
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
  }

  onDestroy(dispose);

  return {
    get mousePos() {
      return mousePos;
    },
    get zoomBox() {
      return zoomBox;
    },
    get isDragging() {
      return isDragging;
    },
    handleMouseMove,
    handleMouseDown,
    handleMouseUp,
    handleMouseLeave,
    handleDoubleClick,
    handleWheel,
    handleKeyDown,
    dispose,
  };
}
