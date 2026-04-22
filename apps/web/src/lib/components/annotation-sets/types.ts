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

// --- Shared primitives ---------------------------------------------------

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
  /** CSS percentage geometry for the transient drag preview bar. */
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

// --- useAnnotationMutations ---------------------------------------------

/**
 * Reactive inputs for the mutation hook (Step 2). Declared now so the
 * Step 1 `types.ts` file does not need to be touched in the follow-up PR.
 */
export interface MutationHookInput {
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
  /** Delete an annotation after confirm. */
  deleteAnnotation: (annotationId: string) => void;
  /** Mark the segment as empty (no vocalisations) + annotated. */
  markEmpty: () => void;
  /** Revert an empty-segment flag back to `unannotated`. */
  clearEmpty: () => void;
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
  readonly actions: MutationHookActions;
  /** Detach listeners / short-circuit callbacks. */
  dispose(): void;
}
