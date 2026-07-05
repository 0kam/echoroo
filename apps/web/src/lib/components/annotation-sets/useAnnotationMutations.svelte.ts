/**
 * useAnnotationMutations — Svelte 5 runes hook that owns TanStack Query
 * mutations for the AnnotationEditor surface.
 *
 * Extracted from AnnotationEditor.svelte as Step 2 of the P2-B refactor
 * (see plan.md §3.2, §4 Step 2). The hook:
 *   - Owns all seven `createMutation()` instances used by the editor.
 *   - Derives a consolidated `isBusy` flag from the pending state of each.
 *   - Exposes a stable `actions` surface the parent dispatches against
 *     (see {@link MutationHookActions}). All absolute→segment-relative
 *     coordinate conversion happens here at commit time, so neither the
 *     parent nor the draft hook needs to know about the time origin.
 *   - Forwards server errors to the global toast stream (same behaviour as
 *     pre-refactor) and invalidates the same TanStack Query keys so the
 *     segment / set caches re-fetch after every successful write.
 *
 * Explicitly NOT handled here:
 *   - Navigation (`goto` to prev/next segment) — stays on the parent, it
 *     never interacts with mutations other than via `mutateAsync` which
 *     the parent can await on `actions.markEmpty()` / `clearEmpty()`.
 *   - Keydown subscription — the parent keeps the single `window keydown`
 *     effect and routes Delete through `actions.deleteAnnotation()`.
 *   - `pickSpecies` branching (`draftRange` vs `selectedAnnotationId`) —
 *     the parent wraps `createFromDraft` / `updateSpeciesOf` based on its
 *     selection state, keeping the hook ignorant of draft-hook internals.
 *
 * Stale-segment guard:
 *   After `createAnnotation` / `deleteAnnotation` resolve we re-check
 *   `input.segmentId()` against the value captured when `mutate()` was
 *   invoked. If the user navigated to a different segment in the interim
 *   we skip the `onCreated` / `onDeleted` callbacks — those would otherwise
 *   surface "phantom" selection changes on the wrong segment. Cache
 *   invalidation ALWAYS runs against the captured segment/set keys: the
 *   captured key identifies the segment whose data actually changed on
 *   the server, which is correct regardless of which segment is currently
 *   displayed (matches pre-refactor behaviour).
 */
import { onDestroy } from 'svelte';
import { get, type Readable } from 'svelte/store';
import { createMutation, useQueryClient } from '@tanstack/svelte-query';
import type { CreateMutationResult } from '@tanstack/svelte-query';
import * as m from '$lib/paraglide/messages';
import { toasts } from '$lib/stores/toast';
import {
  addPalette,
  createAnnotation,
  createAnnotationNote,
  createSegmentNote,
  deleteAnnotation,
  updateAnnotation,
  updateSegment,
} from '$lib/api/annotation-sets';
import type {
  AnnotationSegmentDetail,
  TimeRangeAnnotation,
  TimeRangeAnnotationCreate,
} from '$lib/types/annotation-set';
import type {
  DraftRange,
  MutationHookActions,
  MutationHookApi,
  MutationHookInput,
} from './types';

export function useAnnotationMutations(
  input: MutationHookInput,
): MutationHookApi {
  const queryClient = useQueryClient();

  // Set to true by `dispose()`. Individual mutations' onSuccess / onError
  // callbacks short-circuit when disposed so that a late response from the
  // server (e.g. arriving after the parent has unmounted) does not schedule
  // cache invalidations or toast messages against a gone component tree.
  let disposed = false;

  // --------------------------------------------------------------------
  // Mutations
  // --------------------------------------------------------------------

  // Create a TimeRangeAnnotation on the CURRENT segment. We capture the
  // segmentId / setId at the point `mutate()` is invoked (see `createFromDraft`)
  // so that invalidation and the `onCreated` callback target the correct
  // segment even if the user navigates away mid-flight.
  interface CreateArgs {
    body: TimeRangeAnnotationCreate;
    capturedSegmentId: string;
    capturedSetId: string;
  }

  const createAnnotationMutation = createMutation({
    // Surfaces its own toast error in `onError`; opt out of the
    // global generic error-toast fallback to avoid double feedback.
    meta: { suppressErrorToast: true },
    mutationFn: (args: CreateArgs) =>
      createAnnotation(input.projectId(), args.capturedSegmentId, args.body),
    onSuccess: (annotation: TimeRangeAnnotation, args: CreateArgs) => {
      if (disposed) return;
      queryClient.invalidateQueries({
        queryKey: ['annotation-segment', args.capturedSegmentId],
      });
      queryClient.invalidateQueries({
        queryKey: ['annotation-set', args.capturedSetId],
      });
      toasts.success(m.annotation_editor_create_success());
      // Stale-segment guard: only notify the parent when the editor is
      // still showing the same segment we committed against.
      if (input.segmentId() === args.capturedSegmentId) {
        input.onCreated?.(annotation.id);
      }
    },
    onError: (err: Error) => {
      if (disposed) return;
      toasts.error(err.message || m.annotation_editor_create_error());
    },
  });

  const updateAnnotationSpeciesMutation = createMutation({
    // Surfaces its own toast error in `onError`; opt out of the
    // global generic error-toast fallback to avoid double feedback.
    meta: { suppressErrorToast: true },
    mutationFn: (args: { id: string; speciesId: string }) =>
      updateAnnotation(input.projectId(), args.id, { species_id: args.speciesId }),
    onSuccess: () => {
      if (disposed) return;
      queryClient.invalidateQueries({
        queryKey: ['annotation-segment', input.segmentId()],
      });
      toasts.success(m.annotation_editor_update_success());
    },
    onError: () => {
      if (disposed) return;
      toasts.error(m.annotation_editor_update_error());
    },
  });

  // Capture the segmentId/setId at mutate time so the invalidation after
  // the request resolves always targets the segment the delete was issued
  // against — matches the create/stale-segment pattern used above.
  interface DeleteArgs {
    id: string;
    capturedSegmentId: string;
    capturedSetId: string;
  }

  const deleteAnnotationMutation = createMutation({
    // Surfaces its own toast error in `onError`; opt out of the
    // global generic error-toast fallback to avoid double feedback.
    meta: { suppressErrorToast: true },
    mutationFn: (args: DeleteArgs) => deleteAnnotation(input.projectId(), args.id),
    onSuccess: (_result, args: DeleteArgs) => {
      if (disposed) return;
      queryClient.invalidateQueries({
        queryKey: ['annotation-segment', args.capturedSegmentId],
      });
      queryClient.invalidateQueries({
        queryKey: ['annotation-set', args.capturedSetId],
      });
      toasts.success(m.annotation_editor_delete_success());
      if (input.segmentId() === args.capturedSegmentId) {
        input.onDeleted?.(args.id);
      }
    },
    onError: () => {
      if (disposed) return;
      toasts.error(m.annotation_editor_delete_error());
    },
  });

  const updateSegmentMutation = createMutation({
    // Surfaces its own toast error in `onError`; opt out of the
    // global generic error-toast fallback to avoid double feedback.
    meta: { suppressErrorToast: true },
    mutationFn: (body: {
      status?: AnnotationSegmentDetail['status'];
      is_empty?: boolean;
    }) => updateSegment(input.projectId(), input.segmentId(), body),
    onSuccess: () => {
      if (disposed) return;
      const setId = input.setId();
      queryClient.invalidateQueries({
        queryKey: ['annotation-segment', input.segmentId()],
      });
      queryClient.invalidateQueries({ queryKey: ['annotation-set', setId] });
      queryClient.invalidateQueries({
        queryKey: ['annotation-set-segments', setId],
      });
    },
    onError: (err: Error) => {
      if (disposed) return;
      toasts.error(err.message || m.annotation_editor_status_update_error());
    },
  });

  const addPaletteMutation = createMutation({
    // Surfaces its own toast error in `onError`; opt out of the
    // global generic error-toast fallback to avoid double feedback.
    meta: { suppressErrorToast: true },
    mutationFn: (speciesId: string) =>
      addPalette(input.projectId(), input.setId(), { species_id: speciesId }),
    onSuccess: () => {
      if (disposed) return;
      queryClient.invalidateQueries({
        queryKey: ['annotation-set', input.setId()],
      });
    },
    onError: () => {
      if (disposed) return;
      toasts.error(m.annotation_sets_palette_add_error());
    },
  });

  const createSegmentNoteMutation = createMutation({
    // Surfaces its own toast error in `onError`; opt out of the
    // global generic error-toast fallback to avoid double feedback.
    meta: { suppressErrorToast: true },
    mutationFn: (body: { content: string; is_issue: boolean }) =>
      createSegmentNote(input.projectId(), input.segmentId(), body),
    onSuccess: () => {
      if (disposed) return;
      queryClient.invalidateQueries({
        queryKey: ['annotation-segment', input.segmentId()],
      });
      toasts.success(m.annotation_editor_note_create_success());
    },
    onError: () => {
      if (disposed) return;
      toasts.error(m.annotation_editor_note_create_error());
    },
  });

  const createAnnotationNoteMutation = createMutation({
    // Surfaces its own toast error in `onError`; opt out of the
    // global generic error-toast fallback to avoid double feedback.
    meta: { suppressErrorToast: true },
    mutationFn: (args: {
      annotationId: string;
      content: string;
      is_issue: boolean;
    }) =>
      createAnnotationNote(input.projectId(), args.annotationId, {
        content: args.content,
        is_issue: args.is_issue,
      }),
    onSuccess: () => {
      if (disposed) return;
      queryClient.invalidateQueries({
        queryKey: ['annotation-segment', input.segmentId()],
      });
      toasts.success(m.annotation_editor_note_create_success());
    },
    onError: () => {
      if (disposed) return;
      toasts.error(m.annotation_editor_note_create_error());
    },
  });

  // TanStack Query's `createMutation` returns a plain Svelte store, not a
  // `$state`-compatible object. Inside `.svelte`-files the `$store` prefix
  // auto-subscribes for us, but `.svelte.ts` hooks do not support that
  // syntax — so we mirror each mutation's `isPending` flag into a local
  // `$state` via explicit `subscribe()` calls. The subscriptions tear down
  // through the `onDestroy` handler below.
  //
  // Keeping the sub handles lets the parent call `.mutate` / `.mutateAsync`
  // via `get(store).mutate(...)` (see `mutate()` helper below).
  let pendingCreateAnnotation = $state(false);
  let pendingUpdateAnnotationSpecies = $state(false);
  let pendingDeleteAnnotation = $state(false);
  let pendingUpdateSegment = $state(false);
  let pendingAddPalette = $state(false);
  let pendingCreateSegmentNote = $state(false);
  let pendingCreateAnnotationNote = $state(false);

  function subscribePending<
    TData,
    TError,
    TVariables,
    TContext,
  >(
    store: CreateMutationResult<TData, TError, TVariables, TContext>,
    setter: (v: boolean) => void,
  ): () => void {
    // Cast needed because `CreateMutationResult` is a Readable of the
    // observer result augmented with `mutate` / `mutateAsync` — which is
    // exactly what we want to read via `subscribe`.
    return (store as unknown as Readable<{ isPending: boolean }>).subscribe(
      ($r) => setter($r.isPending),
    );
  }

  const unsubCreate = subscribePending(createAnnotationMutation, (v) => {
    pendingCreateAnnotation = v;
  });
  const unsubUpdate = subscribePending(
    updateAnnotationSpeciesMutation,
    (v) => {
      pendingUpdateAnnotationSpecies = v;
    },
  );
  const unsubDelete = subscribePending(deleteAnnotationMutation, (v) => {
    pendingDeleteAnnotation = v;
  });
  const unsubSegment = subscribePending(updateSegmentMutation, (v) => {
    pendingUpdateSegment = v;
  });
  const unsubPalette = subscribePending(addPaletteMutation, (v) => {
    pendingAddPalette = v;
  });
  const unsubSegNote = subscribePending(createSegmentNoteMutation, (v) => {
    pendingCreateSegmentNote = v;
  });
  const unsubAnnNote = subscribePending(createAnnotationNoteMutation, (v) => {
    pendingCreateAnnotationNote = v;
  });

  const isBusy = $derived(
    pendingCreateAnnotation ||
      pendingUpdateAnnotationSpecies ||
      pendingDeleteAnnotation ||
      pendingUpdateSegment ||
      pendingAddPalette ||
      pendingCreateSegmentNote ||
      pendingCreateAnnotationNote,
  );

  const isCreatingSegmentNote = $derived(pendingCreateSegmentNote);
  const isCreatingAnnotationNote = $derived(pendingCreateAnnotationNote);

  // --------------------------------------------------------------------
  // Action surface
  // --------------------------------------------------------------------

  /**
   * Commit a draft-selection range as a new annotation. The draft is tracked
   * in ABSOLUTE recording seconds; the API expects SEGMENT-RELATIVE seconds
   * so we convert + clamp here (the sole place that owns this conversion,
   * see plan.md §5.1).
   *
   * A degenerate range (end <= start after clamping) surfaces the same
   * error toast as a server-side validation failure — the backend would
   * reject it anyway.
   */
  function createFromDraft(range: DraftRange, speciesId: string): void {
    if (disposed) return;
    const clipStart = input.clipStart();
    const clipDuration = input.clipDuration();
    const relStart = Math.max(0, range.start - clipStart);
    const relEnd = Math.min(clipDuration, range.end - clipStart);
    if (relEnd <= relStart) {
      toasts.error(m.annotation_editor_create_error());
      return;
    }
    get(createAnnotationMutation).mutate({
      body: {
        start_time_sec: relStart,
        end_time_sec: relEnd,
        species_id: speciesId,
      },
      capturedSegmentId: input.segmentId(),
      capturedSetId: input.setId(),
    });
  }

  function updateSpeciesOf(annotationId: string, speciesId: string): void {
    if (disposed) return;
    get(updateAnnotationSpeciesMutation).mutate({ id: annotationId, speciesId });
  }

  function deleteAnnotationAction(annotationId: string): boolean {
    if (disposed) return false;
    // Behaviour-preserving parity with the pre-refactor inline handler —
    // confirm() stays synchronous so Playwright's `once('dialog')` hook
    // continues to work (see e2e annotation-editor test #6). Returning a
    // boolean lets the parent mirror the "user confirmed" signal to its
    // selection state before the async request resolves (the server-side
    // onSuccess separately fires `onDeleted`).
    if (!confirm(m.annotation_editor_annotation_delete_confirm())) return false;
    get(deleteAnnotationMutation).mutate({
      id: annotationId,
      capturedSegmentId: input.segmentId(),
      capturedSetId: input.setId(),
    });
    return true;
  }

  function markEmpty(): void {
    if (disposed) return;
    get(updateSegmentMutation).mutate({ is_empty: true, status: 'annotated' });
  }

  function clearEmpty(): void {
    if (disposed) return;
    get(updateSegmentMutation).mutate({ is_empty: false, status: 'unannotated' });
  }

  async function updateSegmentStatus(body: {
    status: 'annotated' | 'skipped' | 'unannotated';
  }): Promise<void> {
    if (disposed) return;
    // `mutateAsync` resolves after the invalidation callbacks have run,
    // so `completeAndNext` / `skipAndNext` can navigate synchronously
    // against fresh cache state.
    await get(updateSegmentMutation).mutateAsync(body);
  }

  function addSpeciesToPalette(speciesId: string): void {
    if (disposed) return;
    get(addPaletteMutation).mutate(speciesId);
  }

  async function addSegmentNote(content: string, isIssue: boolean): Promise<void> {
    if (disposed) return;
    await get(createSegmentNoteMutation).mutateAsync({
      content,
      is_issue: isIssue,
    });
  }

  async function addAnnotationNote(
    annotationId: string,
    content: string,
    isIssue: boolean,
  ): Promise<void> {
    if (disposed) return;
    await get(createAnnotationNoteMutation).mutateAsync({
      annotationId,
      content,
      is_issue: isIssue,
    });
  }

  const actions: MutationHookActions = {
    createFromDraft,
    updateSpeciesOf,
    deleteAnnotation: deleteAnnotationAction,
    markEmpty,
    clearEmpty,
    updateSegmentStatus,
    addSpeciesToPalette,
    addSegmentNote,
    addAnnotationNote,
  };

  function dispose() {
    if (disposed) return;
    disposed = true;
    // Tear down the pending-state subscriptions so the store observers can
    // be garbage-collected alongside the hook instance. Each `unsub*` is
    // idempotent, so calling `dispose()` twice is harmless.
    unsubCreate();
    unsubUpdate();
    unsubDelete();
    unsubSegment();
    unsubPalette();
    unsubSegNote();
    unsubAnnNote();
  }

  // Defence-in-depth: when the hook is invoked from a component context the
  // hook itself also reacts to `onDestroy`. The parent is still expected to
  // call `dispose()` explicitly from its own `onDestroy` to set the flag
  // before any child effects tear down.
  onDestroy(dispose);

  return {
    get isBusy() {
      return isBusy;
    },
    get isCreatingSegmentNote() {
      return isCreatingSegmentNote;
    },
    get isCreatingAnnotationNote() {
      return isCreatingAnnotationNote;
    },
    actions,
    dispose,
  };
}
