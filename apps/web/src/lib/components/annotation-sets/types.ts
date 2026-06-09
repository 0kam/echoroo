/**
 * Type contracts for the AnnotationEditor split (P2-B refactor).
 *
 * Declares the API surface for BOTH hooks up-front so that Step 2
 * (mutation extraction) does not require re-typing when it lands:
 *   - Step 1: `useAnnotationDraft` implements {@link DraftHookApi}
 *   - Step 2: `useAnnotationMutations` implements {@link MutationHookApi}
 *
 * Conventions (mirrors `apps/web/src/lib/components/audio/types.ts`):
 *   - Every reactive input is a getter (`() => T`) so Svelte 5 runes can
 *     observe value changes across the hook's lifetime.
 *   - Every hook exposes a `dispose()` method that the parent calls from
 *     `onDestroy` to guarantee deterministic cleanup.
 */

import type { SpectrogramWindow } from '$lib/types/audio';

// --- Shared primitives ---------------------------------------------------

/**
 * Interaction mode for the annotation-editor overlay. Mirrors the
 * dataset-viewer `InteractionMode` but adds an `annotating` mode (the
 * default) where a left-drag draws a draft range / a click seeks.
 *   - annotating: left-drag → draft range; click (<5px) → seek the playhead.
 *   - panning:    left-drag → pan the shared viewport (shiftWindow).
 *   - zooming:    left-drag → zoom box; on mouseup, zoom-to-box.
 */
export type AnnotationInteractionMode = 'annotating' | 'panning' | 'zooming';

/**
 * A draft range expressed in ABSOLUTE recording seconds (not segment-relative).
 * The mutation hook converts to segment-relative when committing.
 */
export interface DraftRange {
  start: number;
  end: number;
}

// --- useAnnotationDraft --------------------------------------------------

/**
 * Reactive inputs for the draft-selection hook. Each field is a getter so
 * the hook continues to see the latest parent value without wiring `$effect`
 * dependencies at the call site.
 */
export interface DraftHookInput {
  /** DOM reference for the overlay `<div>` owned by the parent via `bind:this`. */
  overlayEl: () => HTMLDivElement | undefined;
  /** Absolute recording seconds where the clip (segment) starts. */
  clipStart: () => number;
  /** Duration in seconds of the clip (segment). */
  clipDuration: () => number;
  /**
   * Live overlay/canvas width in CSS px. Required for viewport-aware
   * coordinate math: pixel↔time conversion depends on the current viewport
   * window, NOT on a fixed clip-duration fraction. The overlay is laid out
   * `inset-x-0` so its width matches the spectrogram canvas width exactly.
   */
  canvasWidth: () => number;
  /** Live canvas height in CSS px (used only for completeness in pixel↔pos math). */
  canvasHeight: () => number;
  /**
   * Live spectrogram viewport (recording-absolute time + Hz). Drives the
   * pixel↔time transform so click/drag math stays correct under any
   * zoom/pan. The same transform positions the annotation boxes, so seek and
   * box geometry share a single coordinate model.
   */
  viewport: () => SpectrogramWindow;
  /**
   * Optional: invoked when a press-release on the overlay is a trivial CLICK
   * (movement below the drag threshold) rather than a drag. The argument is
   * the clicked position in ABSOLUTE recording seconds. The parent uses this
   * to move the audio playhead (seek), while a real drag still produces a
   * draft range as before.
   */
  onSeek?: (time: number) => void;
}

/**
 * Imperative API returned by {@link useAnnotationDraft}. The parent wires
 * `handlers.onMouseDown` onto the overlay and renders `dragPreview` while
 * the user is dragging.
 */
export interface DraftHookApi {
  /** The finalised draft range in absolute recording seconds, or null. */
  readonly draftRange: DraftRange | null;
  /** True while the mouse is held down after a valid `onMouseDown`. */
  readonly isDragging: boolean;
  /**
   * Pixel geometry (CSS px) for the transient drag-preview bar, computed via
   * the live viewport transform so the preview tracks zoom/pan. `left`/`width`
   * are clamped to non-negative; the overlay container clips overflow.
   */
  readonly dragPreview: { left: number; width: number };
  /** Event handlers the parent attaches to the overlay element. */
  readonly handlers: { onMouseDown: (e: MouseEvent) => void };
  /** Reset draft + drag state (e.g. Escape, new selection, segment change). */
  clear(): void;
  /**
   * Short-circuit pending async continuations (sets a `disposed` flag).
   * Must be called from the parent's `onDestroy`; window listeners are
   * detached by the hook's own `$effect` cleanup when the parent unmounts.
   */
  dispose(): void;
}

// --- useAnnotationOverlay -----------------------------------------------

/**
 * A pending zoom-box selection on the annotation overlay. `start`/`end` are
 * positions in spectrogram coordinates (recording-absolute seconds / Hz),
 * matching the dataset-viewer {@link import('../audio/types').ZoomBox}.
 */
export interface AnnotationZoomBox {
  start: { time: number; freq: number };
  end: { time: number; freq: number };
}

/**
 * Reactive inputs for the overlay-interaction hook. The hook is the SOLE
 * interaction surface on the annotation page: the overlay sits above the
 * spectrogram with `pointer-events-auto`, so the dataset viewer's own
 * pan/zoom/seek never fire. The hook dispatches by mode:
 *   - annotating → delegates mousedown to the draft hook (drag → range / click → seek).
 *   - panning    → left-drag pans the shared viewport via `onViewportChange`.
 *   - zooming    → left-drag draws a zoom box; mouseup zooms-to-box.
 */
export interface OverlayHookInput {
  /** DOM ref for the overlay `<div>` (parent owns it via `bind:this`). */
  overlayEl: () => HTMLDivElement | undefined;
  /** Live spectrogram viewport (recording-absolute time + Hz). */
  viewport: () => SpectrogramWindow;
  /** Clip bounds — pan/zoom is clamped within these via `adjustWindowToBounds`. */
  bounds: () => SpectrogramWindow;
  /** Live overlay/canvas width in CSS px. */
  canvasWidth: () => number;
  /** Live overlay/canvas height in CSS px. */
  canvasHeight: () => number;
  /** Current interaction mode. */
  mode: () => AnnotationInteractionMode;
  /** Delegate for `annotating` mode — the draft hook's `onMouseDown`. */
  onAnnotateMouseDown: (e: MouseEvent) => void;
  /** Push a new viewport (pan/zoom result); parent clamps + commits. */
  onViewportChange: (vp: SpectrogramWindow) => void;
  /** Save the current viewport to history before a pan/zoom gesture begins. */
  onViewportSave?: () => void;
  /** Switch mode (e.g. back to `annotating` after a zoom completes). */
  onModeChange?: (mode: AnnotationInteractionMode) => void;
}

/**
 * Imperative API returned by {@link useAnnotationOverlay}. The parent wires
 * `handlers.onMouseDown` onto the overlay element and renders `zoomBox`
 * (pixel geometry) while a zoom drag is in progress.
 */
export interface OverlayHookApi {
  /** Pixel geometry for the transient zoom-box rectangle, or null when idle. */
  readonly zoomBoxPx: { left: number; width: number } | null;
  /** Event handler the parent attaches to the overlay element. */
  readonly handlers: { onMouseDown: (e: MouseEvent) => void };
  /** Detach window listeners / short-circuit async continuations. */
  dispose(): void;
}

// --- useAnnotationMutations ---------------------------------------------

/**
 * Reactive inputs for the mutation hook (Step 2). Declared now so the
 * Step 1 `types.ts` file does not need to be touched in the follow-up PR.
 */
export interface MutationHookInput {
  /** Owning project id (spec/009 PR 4 — required by the BFF path). */
  projectId: () => string;
  /** Current segment id. */
  segmentId: () => string;
  /** Current annotation set id. */
  setId: () => string;
  /** Absolute recording seconds where the clip (segment) starts. */
  clipStart: () => number;
  /** Duration in seconds of the clip (segment). */
  clipDuration: () => number;
  /**
   * Optional callback fired after a successful `createFromDraft`. The hook
   * must verify that `segmentId()` matches the value captured at mutate
   * time before invoking this — guards against stale segment races.
   */
  onCreated?: (annotationId: string) => void;
  /**
   * Optional callback fired after a successful `deleteAnnotation`. The
   * parent uses this to clear `selectedAnnotationId` so the UI drops the
   * selection ring on the now-removed row. Matches the pre-refactor
   * behaviour where the mutation's `onSuccess` reset selection inline.
   */
  onDeleted?: (annotationId: string) => void;
}

/**
 * High-level action surface returned by the mutation hook. All functions
 * are thin wrappers around TanStack Query `createMutation` instances; the
 * hook owns error toasts and invalidation keys.
 */
export interface MutationHookActions {
  /** Create a new annotation from a draft range (converted to segment-relative). */
  createFromDraft: (range: DraftRange, speciesId: string) => void;
  /** Re-assign the species of an existing annotation. */
  updateSpeciesOf: (annotationId: string, speciesId: string) => void;
  /** Delete an annotation after confirm(). Returns `true` if confirmed. */
  deleteAnnotation: (annotationId: string) => boolean;
  /** Mark the segment as empty (no vocalisations) + annotated. */
  markEmpty: () => void;
  /** Revert an empty-segment flag back to `unannotated`. */
  clearEmpty: () => void;
  /**
   * Set the segment status without touching `is_empty`. Awaitable so that
   * callers like `completeAndNext` / `skipAndNext` can navigate only after
   * the server confirms the transition.
   */
  updateSegmentStatus: (body: { status: 'annotated' | 'skipped' | 'unannotated' }) => Promise<void>;
  /** Add a species to the set palette. */
  addSpeciesToPalette: (speciesId: string) => void;
  /** Append a note to the segment. */
  addSegmentNote: (content: string, isIssue: boolean) => Promise<void>;
  /** Append a note to a specific annotation. */
  addAnnotationNote: (
    annotationId: string,
    content: string,
    isIssue: boolean,
  ) => Promise<void>;
}

/**
 * Imperative API returned by {@link useAnnotationMutations}.
 */
export interface MutationHookApi {
  /** True when any of the owned mutations is pending (drives child busy state). */
  readonly isBusy: boolean;
  /**
   * Finer-grained pending flags for the note mutations. `NotesPanel` uses
   * these to disable its per-panel submit button without flipping the
   * global busy state; exposing them preserves pre-refactor behaviour
   * where each NotesPanel watched its own mutation's `isPending`.
   */
  readonly isCreatingSegmentNote: boolean;
  readonly isCreatingAnnotationNote: boolean;
  readonly actions: MutationHookActions;
  /** Detach listeners / short-circuit callbacks. */
  dispose(): void;
}
