/**
 * useAnnotationDraft — Svelte 5 runes hook that owns draft-range selection
 * state for the AnnotationEditor overlay.
 *
 * Extracted from AnnotationEditor.svelte as Step 1 of the P2-B refactor
 * (see plan.md §3.1, §4 Step 1). The hook:
 *   - Owns drag/geometry state (dragStartX / dragCurrentX / isDragging).
 *   - Derives `draftRange` in ABSOLUTE recording seconds after a valid drag.
 *   - Exposes `dragPreview` (percentage geometry) for the transient preview bar.
 *   - Subscribes window `mousemove` / `mouseup` via a single `$effect`.
 *
 * Explicitly NOT handled here:
 *   - Keydown subscription — the parent owns a single `window keydown` effect
 *     and invokes `draft.clear()` on Escape (see plan.md §3.4).
 *   - Time origin conversion (absolute -> segment-relative) — that happens
 *     at commit time inside the upcoming mutation hook (see plan.md §5.1).
 *   - Readonly gating — current behaviour allows drag on readonly segments;
 *     the readonly banner is displayed separately and the mutation layer
 *     is the real guardrail (see plan.md §3.3, v3 decision in §0).
 */
import { onDestroy } from 'svelte';
import { pixelsToPosition, timeToPixel } from '$lib/utils/viewport';
import type { DraftHookApi, DraftHookInput, DraftRange } from './types';

/**
 * Threshold (in seconds) below which a drag is treated as a trivial click
 * and discarded without producing a draft range. Matches the original
 * inline value in AnnotationEditor.svelte (L194–196 pre-refactor).
 */
const TRIVIAL_DRAG_SECONDS = 0.05;

/**
 * Pointer movement (in CSS px) below which a press-release is treated as a
 * CLICK rather than a drag. A click moves the playhead via `onSeek`; a drag
 * beyond this produces a draft range. Using a pixel threshold (instead of a
 * seconds threshold) keeps the click/drag boundary stable across zoom levels,
 * where the same pixel travel maps to very different time spans.
 */
const CLICK_MOVEMENT_PX = 5;

export function useAnnotationDraft(input: DraftHookInput): DraftHookApi {
  // Finalised draft range in absolute recording seconds, or null when idle.
  let draftRange = $state<DraftRange | null>(null);
  // Drag state machine. `isDragging` is true between mousedown and mouseup.
  let isDragging = $state(false);
  // Client-x (CSS px) captured at mousedown and updated on each mousemove.
  // We intentionally store the raw clientX (not a data-space time) so that
  // `clientXToTime` remains the single source of truth for coordinate math
  // — the overlay rect can change mid-drag if the layout reflows.
  let dragStartX = $state(0);
  let dragCurrentX = $state(0);

  // Set to true by `dispose()`. All DOM listeners already unsubscribe via
  // the `$effect` cleanup below, but we keep the flag so async continuations
  // (if any are added later) can early-return safely.
  let disposed = false;

  /**
   * Convert a client-x (CSS px) within the overlay to absolute recording
   * seconds, using the CURRENT viewport window rather than a fixed clip
   * fraction. This is the single source of truth for click/drag → time math
   * and is what makes seek + draft-range correct under any zoom/pan (the old
   * implementation assumed the viewport always spanned the entire clip, which
   * produced wrong times whenever the viewport was zoomed or panned).
   *
   * Returns `clipStart` when the overlay is missing or has zero width so
   * callers never produce NaN values. The result is clamped to the clip
   * bounds so a click on an out-of-clip pixel can never escape the segment.
   */
  function clientXToTime(clientX: number): number {
    const overlayEl = input.overlayEl();
    const clipStart = input.clipStart();
    const clipDuration = input.clipDuration();
    const canvasWidth = input.canvasWidth();
    const viewport = input.viewport();
    if (!overlayEl || canvasWidth <= 0) return clipStart;
    const rect = overlayEl.getBoundingClientRect();
    const offsetX = clientX - rect.left;
    // The overlay (`inset-x-0`) shares the canvas's left edge and width, so
    // offsetX maps directly onto the canvas pixel x used by the viewport math.
    const { time } = pixelsToPosition(offsetX, 0, canvasWidth, 1, viewport);
    const clipEnd = clipStart + clipDuration;
    return Math.max(clipStart, Math.min(clipEnd, time));
  }

  /**
   * Convert an absolute recording-seconds time to a CSS px x-coordinate within
   * the overlay, using the live viewport transform. Shared with the parent's
   * annotation-box geometry so the preview bar and committed boxes line up.
   */
  function timeToPx(t: number): number {
    const canvasWidth = input.canvasWidth();
    const viewport = input.viewport();
    if (canvasWidth <= 0) return 0;
    return timeToPixel(t, canvasWidth, viewport);
  }

  function onMouseDown(e: MouseEvent) {
    if (disposed) return;
    const clipDuration = input.clipDuration();
    if (!clipDuration) return;
    e.preventDefault();
    isDragging = true;
    dragStartX = e.clientX;
    dragCurrentX = e.clientX;
  }

  function onWindowMouseMove(e: MouseEvent) {
    if (disposed) return;
    if (!isDragging) return;
    dragCurrentX = e.clientX;
  }

  function onWindowMouseUp() {
    if (disposed) return;
    if (!isDragging) return;
    isDragging = false;
    const t1 = clientXToTime(dragStartX);
    const t2 = clientXToTime(dragCurrentX);
    const start = Math.min(t1, t2);
    const end = Math.max(t1, t2);
    // Distinguish a trivial CLICK from a DRAG using pointer travel in CSS px.
    // Pixel movement is the SOLE click/drag discriminator: it stays stable
    // across zoom levels and is independent of how fast the gesture was. A
    // click (movement below the threshold) seeks the playhead; any movement
    // at or beyond the threshold is a drag and draws a draft.
    const movedPx = Math.abs(dragCurrentX - dragStartX);
    if (movedPx < CLICK_MOVEMENT_PX) {
      // Seek to the press position (the click point). Use dragStartX so the
      // playhead lands where the user pressed, independent of tiny jitter.
      input.onSeek?.(clientXToTime(dragStartX));
      return;
    }
    // Safety net for the draft-creation path only (NOT the click/seek
    // decision): a real >=5px drag essentially always spans > 0 seconds, but
    // guard against a degenerate zero-width range so we never produce an
    // invalid draft. We deliberately do NOT fire `onSeek` here — the gesture
    // was a drag, not a click.
    if (end - start < TRIVIAL_DRAG_SECONDS) {
      return;
    }
    const clipStart = input.clipStart();
    const clipDuration = input.clipDuration();
    const clipEnd = clipStart + clipDuration;
    draftRange = {
      start: Math.max(clipStart, start),
      end: Math.min(clipEnd, end),
    };
  }

  // Pixel geometry for the transient drag-preview bar, computed via the live
  // viewport transform so the bar tracks zoom/pan. `left`/`width` are clamped
  // to non-negative; the overlay container clips any overflow.
  const dragPreviewLeft = $derived(
    isDragging
      ? Math.max(0, timeToPx(clientXToTime(Math.min(dragStartX, dragCurrentX))))
      : 0,
  );
  const dragPreviewWidth = $derived(
    isDragging
      ? Math.max(
          0,
          timeToPx(clientXToTime(Math.max(dragStartX, dragCurrentX))) -
            timeToPx(clientXToTime(Math.min(dragStartX, dragCurrentX))),
        )
      : 0,
  );

  // Subscribe to window mouse events for the drag state machine. We use a
  // single $effect with a cleanup closure so the listeners detach both on
  // hot-reload re-runs and when the parent's `onDestroy` eventually fires.
  $effect(() => {
    window.addEventListener('mousemove', onWindowMouseMove);
    window.addEventListener('mouseup', onWindowMouseUp);
    return () => {
      window.removeEventListener('mousemove', onWindowMouseMove);
      window.removeEventListener('mouseup', onWindowMouseUp);
    };
  });

  function clear() {
    draftRange = null;
    isDragging = false;
    dragStartX = 0;
    dragCurrentX = 0;
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
  }

  // Defence-in-depth: if the hook is invoked from a component context the
  // hook itself will also react to `onDestroy`. The parent is expected to
  // call `dispose()` explicitly from its own `onDestroy` as well.
  onDestroy(dispose);

  return {
    get draftRange() {
      return draftRange;
    },
    get isDragging() {
      return isDragging;
    },
    get dragPreview() {
      return { left: dragPreviewLeft, width: dragPreviewWidth };
    },
    handlers: {
      onMouseDown,
    },
    clear,
    dispose,
  };
}
