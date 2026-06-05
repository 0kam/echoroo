<script lang="ts">
  /**
   * AnnotationEditor — the core authoring surface for a single segment.
   *
   * Composition:
   *   - SegmentNavigator (top): progress, skip / complete, segment nav
   *   - Spectrogram + audio player (ClipSpectrogramPlayer) with an overlay
   *     layer for existing TimeRangeAnnotations and drag-to-select
   *   - AnnotationList (left rail)
   *   - SpeciesPalette + NotesPanel (right rail)
   *
   * The component owns the TanStack Query / mutation logic and wires the
   * various child components together. See the route page
   * `(app)/projects/[id]/annotation-sets/[setId]/annotate/[segmentId]` for
   * the URL-level navigation wrapper.
   */
  import { onDestroy } from 'svelte';
  import { goto } from '$app/navigation';
  import { createQuery } from '@tanstack/svelte-query';
  import * as m from '$lib/paraglide/messages';
  import { localizeHref, getLocale } from '$lib/paraglide/runtime';
  import { toasts } from '$lib/stores/toast';
  import { formatSpeciesName } from '$lib/utils/speciesFormatters';
  import ClipSpectrogramPlayer from '$lib/components/audio/ClipSpectrogramPlayer.svelte';
  import SegmentNavigator from '$lib/components/annotation-sets/SegmentNavigator.svelte';
  import SpeciesPalette from '$lib/components/annotation-sets/SpeciesPalette.svelte';
  import AnnotationList from '$lib/components/annotation-sets/AnnotationList.svelte';
  import NotesPanel from '$lib/components/annotation-sets/NotesPanel.svelte';
  import { useAnnotationDraft } from '$lib/components/annotation-sets/useAnnotationDraft.svelte';
  import { useAnnotationMutations } from '$lib/components/annotation-sets/useAnnotationMutations.svelte';
  import {
    getAnnotationSet,
    getSegment,
    listSegments,
  } from '$lib/api/annotation-sets';
  import { getRecording } from '$lib/api/recordings';
  import type {
    AnnotationSegmentSummary,
    AnnotationSetDetail,
    AnnotationSegmentDetail,
    TimeRangeAnnotation,
  } from '$lib/types/annotation-set';
  import type { RecordingDetail } from '$lib/types/data';

  interface Props {
    projectId: string;
    setId: string;
    segmentId: string;
  }

  let { projectId, setId, segmentId }: Props = $props();

  // ============================================================
  // Queries
  // ============================================================

  const setQuery = $derived(
    createQuery({
      queryKey: ['annotation-set', setId],
      queryFn: () => getAnnotationSet(projectId, setId),
      refetchOnWindowFocus: false,
    }),
  );

  const segmentQuery = $derived(
    createQuery({
      queryKey: ['annotation-segment', segmentId],
      queryFn: () => getSegment(projectId, segmentId),
      refetchOnWindowFocus: false,
    }),
  );

  // Full ordered list of segments for prev/next navigation.
  const segmentsListQuery = $derived(
    createQuery({
      queryKey: ['annotation-set-segments', setId, 'all'],
      queryFn: () => listSegments(projectId, setId, { page_size: 500 }),
      refetchOnWindowFocus: false,
    }),
  );

  // Recording metadata needed by the spectrogram player.
  const recordingQuery = $derived(
    createQuery({
      queryKey: ['recording', projectId, $segmentQuery.data?.recording_id],
      queryFn: () => {
        const rid = $segmentQuery.data?.recording_id;
        if (!rid) return Promise.reject(new Error('no recording id'));
        return getRecording(projectId, rid);
      },
      enabled: !!$segmentQuery.data?.recording_id,
      refetchOnWindowFocus: false,
    }),
  );

  const setDetail = $derived<AnnotationSetDetail | null>($setQuery.data ?? null);
  const segment = $derived<AnnotationSegmentDetail | null>($segmentQuery.data ?? null);
  const recording = $derived<RecordingDetail | null>($recordingQuery.data ?? null);
  const segmentItems = $derived<AnnotationSegmentSummary[]>(
    $segmentsListQuery.data?.items ?? [],
  );

  const currentIndex = $derived(
    segmentItems.findIndex((s) => s.id === segmentId),
  );
  const hasPrevious = $derived(currentIndex > 0);
  const hasNext = $derived(
    currentIndex >= 0 && currentIndex < segmentItems.length - 1,
  );
  const isReadonly = $derived(
    segment?.status === 'annotated' || segment?.status === 'skipped',
  );

  // ============================================================
  // Selection + clip geometry
  // ============================================================

  /** Currently selected existing annotation id (for edit / note / delete). */
  let selectedAnnotationId = $state<string | null>(null);

  const selectedAnnotation = $derived<TimeRangeAnnotation | null>(
    segment?.annotations.find((a) => a.id === selectedAnnotationId) ?? null,
  );

  const clipStart = $derived(segment?.start_time_sec ?? 0);
  const clipEnd = $derived(segment?.end_time_sec ?? 0);
  const clipDuration = $derived(Math.max(0, clipEnd - clipStart));

  // ============================================================
  // Spectrogram overlay — drag-to-select draft range (hook-owned)
  // ============================================================

  /**
   * DOM ref for the overlay. Ownership stays on the parent — the draft hook
   * only reads it via the getter so the bind:this mechanics remain simple.
   */
  let overlayEl: HTMLDivElement | undefined = $state();

  /**
   * Requested playhead position (absolute recording seconds) for click-to-seek.
   * `seekNonce` is bumped on every click so that clicking the SAME spot twice
   * still re-triggers ClipSpectrogramPlayer's seek effect (a plain value prop
   * would be deduplicated by Svelte when the value is unchanged).
   */
  let seekTime = $state<number | null>(null);
  let seekNonce = $state(0);

  /** Seek the playhead to an absolute recording time (click-to-seek). */
  function seekTo(absoluteTime: number) {
    seekTime = absoluteTime;
    seekNonce += 1;
  }

  /**
   * Draft state machine + drag geometry. See
   * `./useAnnotationDraft.svelte.ts` for details; the hook owns window
   * mousemove / mouseup subscriptions and exposes the finalised draft range
   * plus a transient drag-preview bar geometry. A trivial click (below the
   * drag threshold) is reported via `onSeek` and moves the playhead instead
   * of creating a draft range.
   */
  const draft = useAnnotationDraft({
    overlayEl: () => overlayEl,
    clipStart: () => clipStart,
    clipDuration: () => clipDuration,
    onSeek: seekTo,
  });

  /**
   * Helper used to position existing annotation overlays. The draft hook
   * does not expose this — it is trivial and is used only for the rendered
   * annotation overlays on the spectrogram, not for drag math.
   */
  function timeToPercent(t: number): number {
    if (clipDuration <= 0) return 0;
    return ((t - clipStart) / clipDuration) * 100;
  }

  // When the segment changes, clear both draft and selection state. This
  // replaces the pre-refactor inline reset + the L136-141 $effect.
  $effect(() => {
    // Reference segmentId to make the dependency explicit.
    void segmentId;
    draft.clear();
    selectedAnnotationId = null;
    // Drop any pending click-to-seek target so it cannot fire against the new
    // clip; ClipSpectrogramPlayer already resets its own playhead to clipStart.
    seekTime = null;
  });

  // A newly-committed draft should clear any previous annotation selection
  // (pre-refactor this lived inside handleWindowMouseUp).
  $effect(() => {
    if (draft.draftRange) {
      selectedAnnotationId = null;
    }
  });

  // ============================================================
  // Mutations (Step 2 refactor — see plan.md §3.2, §4 Step 2)
  // ============================================================
  //
  // Every write-side interaction is routed through the mutation hook. The
  // parent keeps only the "which mutation to dispatch" decisions (e.g.
  // `pickSpecies` picks between `createFromDraft` and `updateSpeciesOf`)
  // plus post-write selection management (`onCreated` -> `selectedAnnotationId`).
  // All TanStack Query invalidation + toast wiring lives in the hook.
  //
  // `onCreated` fires from the hook only when it has verified that the
  // currently-displayed segment still matches the segment the annotation was
  // committed to (stale-segment guard, plan.md §3.2 last bullet). So here
  // we can safely sync selection and clear the draft unconditionally.
  const mutations = useAnnotationMutations({
    projectId: () => projectId,
    segmentId: () => segmentId,
    setId: () => setId,
    clipStart: () => clipStart,
    clipDuration: () => clipDuration,
    onCreated: (annotationId) => {
      draft.clear();
      selectedAnnotationId = annotationId;
    },
    onDeleted: (annotationId) => {
      // Server has confirmed the delete — drop the selection if it still
      // points at the removed row. This mirrors the pre-refactor semantics
      // where the selection was reset inside the mutation's `onSuccess`:
      // a failed DELETE must leave the selection intact so the user can
      // retry or inspect the still-present annotation. The id guard also
      // covers the edge case where the user re-selected a different
      // annotation while the DELETE was in flight.
      if (selectedAnnotationId === annotationId) selectedAnnotationId = null;
    },
  });

  const isBusy = $derived(mutations.isBusy);

  // ============================================================
  // Actions
  // ============================================================

  /**
   * Dispatch a species pick. When a draft range is active we commit it as a
   * new annotation; when an existing annotation is selected we re-assign its
   * species. This branching lives on the parent so the mutation hook stays
   * ignorant of draft-hook internals (plan.md §3.2, §3.3).
   */
  function pickSpecies(speciesId: string) {
    const currentDraft = draft.draftRange;
    if (currentDraft) {
      mutations.actions.createFromDraft(currentDraft, speciesId);
      return;
    }
    if (selectedAnnotationId) {
      mutations.actions.updateSpeciesOf(selectedAnnotationId, speciesId);
    }
  }

  function cancelDraft() {
    draft.clear();
  }

  function onDeleteAnnotation(id: string) {
    // The hook owns the confirm() + mutate dispatch. We intentionally do
    // NOT clear `selectedAnnotationId` eagerly here: pre-refactor the
    // selection was only reset inside the mutation's `onSuccess`, so a
    // failed DELETE leaves the annotation in the list WITH its selection
    // preserved (the user can retry). The `onDeleted` callback wired
    // into `useAnnotationMutations` above clears the selection once the
    // server has confirmed the delete, which is the same moment the
    // pre-refactor code cleared it.
    mutations.actions.deleteAnnotation(id);
  }

  function onSelectAnnotation(id: string) {
    selectedAnnotationId = id === selectedAnnotationId ? null : id;
    if (selectedAnnotationId) draft.clear();
  }

  function navigateToSegment(newSegmentId: string) {
    const href = localizeHref(
      `/projects/${projectId}/annotation-sets/${setId}/annotate/${newSegmentId}`,
    );
    void goto(href, { replaceState: false });
  }

  function navigatePrevious() {
    if (!hasPrevious) return;
    const prev = segmentItems[currentIndex - 1];
    if (prev) navigateToSegment(prev.id);
  }

  function navigateNext() {
    if (!hasNext) return;
    const next = segmentItems[currentIndex + 1];
    if (next) navigateToSegment(next.id);
  }

  /** Find the next unannotated segment after the current index. */
  function findNextUnannotated(): AnnotationSegmentSummary | null {
    for (let i = currentIndex + 1; i < segmentItems.length; i++) {
      const item = segmentItems[i];
      if (item && item.status === 'unannotated') return item;
    }
    // Wrap around — look from the start (exclude current).
    for (let i = 0; i < currentIndex; i++) {
      const item = segmentItems[i];
      if (item && item.status === 'unannotated') return item;
    }
    return null;
  }

  async function completeAndNext() {
    if (!segment) return;
    await mutations.actions.updateSegmentStatus({ status: 'annotated' });
    const target = findNextUnannotated();
    if (target) {
      navigateToSegment(target.id);
    } else {
      toasts.success(m.annotation_editor_no_more_segments());
      // Navigate back to the set detail page.
      void goto(localizeHref(`/projects/${projectId}/annotation-sets/${setId}`));
    }
  }

  async function skipAndNext() {
    if (!segment) return;
    await mutations.actions.updateSegmentStatus({ status: 'skipped' });
    const target = findNextUnannotated();
    if (target) {
      navigateToSegment(target.id);
    }
  }

  function markNoVocalization() {
    if (!segment) return;
    if (segment.annotations.length > 0) {
      toasts.error(m.annotation_editor_no_vocalization_error());
      return;
    }
    mutations.actions.markEmpty();
  }

  function clearNoVocalization() {
    if (!segment) return;
    mutations.actions.clearEmpty();
  }

  function addSpeciesToPalette(speciesId: string) {
    mutations.actions.addSpeciesToPalette(speciesId);
  }

  async function addSegmentNote(content: string, isIssue: boolean) {
    await mutations.actions.addSegmentNote(content, isIssue);
  }

  async function addAnnotationNote(content: string, isIssue: boolean) {
    if (!selectedAnnotationId) return;
    await mutations.actions.addAnnotationNote(
      selectedAnnotationId,
      content,
      isIssue,
    );
  }

  // ============================================================
  // Keyboard: Esc cancels draft/selection, Delete removes selected annotation
  // ============================================================
  //
  // Keydown is owned exclusively by this parent component (plan.md §3.4).
  // Both hooks deliberately stay keyboard-agnostic; centralising here keeps
  // the IME / input-focus guard in one place. The Delete branch dispatches
  // through the mutation hook (via `onDeleteAnnotation`), which handles the
  // confirm() + mutate + selection-reset chain.
  $effect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      // IME / text-entry guard — ignore keystrokes targeting inputs so that
      // typing a species name or a note never triggers editor shortcuts.
      const target = e.target as HTMLElement | null;
      if (target) {
        const tag = target.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || target.isContentEditable) return;
      }
      if (e.key === 'Escape') {
        if (draft.draftRange || selectedAnnotationId) {
          e.preventDefault();
          draft.clear();
          selectedAnnotationId = null;
        }
      } else if (e.key === 'Delete' && selectedAnnotationId) {
        e.preventDefault();
        onDeleteAnnotation(selectedAnnotationId);
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  });

  onDestroy(() => {
    draft.dispose();
    mutations.dispose();
  });

  // ============================================================
  // Navigation helpers
  // ============================================================

  const backHref = $derived(
    localizeHref(`/projects/${projectId}/annotation-sets/${setId}`),
  );

  // ============================================================
  // Presentation helpers
  // ============================================================

  function colorForSpecies(id: string): string {
    let hash = 0;
    for (let i = 0; i < id.length; i++) {
      hash = (hash * 31 + id.charCodeAt(i)) | 0;
    }
    const hue = Math.abs(hash) % 360;
    return `hsl(${hue}, 65%, 45%)`;
  }

  function annotationLabel(a: TimeRangeAnnotation): string {
    return formatSpeciesName(a.species_common_name, a.species_scientific_name);
  }

  /**
   * Recording datetime formatted in the viewer's LOCAL timezone, matching the
   * recording-detail page. `null` when the recording has no parsed datetime.
   */
  const recordingDatetimeLabel = $derived.by<string | null>(() => {
    const dt = recording?.datetime;
    if (!dt) return null;
    return new Date(dt).toLocaleString(getLocale());
  });
</script>

<div class="flex h-screen flex-col bg-surface-body">
  <!-- Top navigator -->
  {#if setDetail && segment}
    <SegmentNavigator
      setName={setDetail.name}
      {backHref}
      currentIndex={currentIndex < 0 ? 0 : currentIndex}
      totalSegments={segmentItems.length || setDetail.num_segments}
      status={segment.status}
      isEmpty={segment.is_empty}
      annotationCount={segment.annotations.length}
      {hasPrevious}
      {hasNext}
      {isBusy}
      onPrevious={navigatePrevious}
      onNext={navigateNext}
      onSkip={skipAndNext}
      onComplete={completeAndNext}
      onMarkNoVocalization={markNoVocalization}
      onClearNoVocalization={clearNoVocalization}
    />
  {/if}

  <!-- Body: spectrogram on top, two-column panels below -->
  <div class="flex min-h-0 flex-1 flex-col">
    <!-- Loading / error states -->
    {#if $segmentQuery.isLoading && !segment}
      <div class="flex flex-1 items-center justify-center">
        <p class="text-sm text-stone-400">{m.annotation_editor_loading()}</p>
      </div>
    {:else if $segmentQuery.isError}
      <div class="flex flex-1 flex-col items-center justify-center gap-3">
        <p class="text-sm text-danger">{m.annotation_editor_error()}</p>
        <button
          type="button"
          class="rounded-md border border-stone-300 px-3 py-1.5 text-sm hover:bg-stone-50 dark:border-stone-600 dark:hover:bg-stone-800"
          onclick={() => $segmentQuery.refetch()}
        >
          {m.annotation_editor_retry()}
        </button>
      </div>
    {:else if !segment}
      <div class="flex flex-1 items-center justify-center">
        <p class="text-sm text-stone-500">{m.annotation_editor_not_found()}</p>
      </div>
    {:else}
      <!-- Readonly banner -->
      {#if isReadonly}
        <div
          class="border-b border-amber-200 bg-amber-50 px-4 py-1.5 text-xs text-amber-800 dark:border-amber-900/40 dark:bg-amber-900/20 dark:text-amber-300"
        >
          <strong>{m.annotation_editor_already_completed()}:</strong>
          {m.annotation_editor_readonly_hint()}
        </div>
      {/if}

      <!-- Spectrogram + audio -->
      <section
        class="relative flex-shrink-0 border-b border-stone-200 dark:border-stone-700"
        aria-label={m.annotation_editor_spectrogram_title()}
      >
        {#if $recordingQuery.isLoading && !recording}
          <div class="flex h-64 items-center justify-center bg-stone-100 dark:bg-stone-800">
            <p class="text-sm text-stone-400">{m.annotation_editor_recording_loading()}</p>
          </div>
        {:else if $recordingQuery.isError || !recording}
          <div class="flex h-64 items-center justify-center bg-stone-100 dark:bg-stone-800">
            <p class="text-sm text-danger">{m.annotation_editor_recording_error()}</p>
          </div>
        {:else}
          <!-- Recording metadata header: filename + recording datetime (local time) -->
          <div
            class="flex flex-wrap items-center gap-x-3 gap-y-0.5 border-b border-stone-200 bg-surface-card px-4 py-1.5 text-xs dark:border-stone-700"
          >
            <span class="truncate font-medium text-stone-700 dark:text-stone-200">
              {recording.filename}
            </span>
            <span class="flex items-center gap-1 text-stone-500 dark:text-stone-400">
              <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
                <line x1="16" y1="2" x2="16" y2="6" />
                <line x1="8" y1="2" x2="8" y2="6" />
                <line x1="3" y1="10" x2="21" y2="10" />
              </svg>
              <span class="sr-only">{m.annotation_editor_recording_recorded_at()}:</span>
              {#if recordingDatetimeLabel}
                <span class="tabular-nums">{recordingDatetimeLabel}</span>
              {:else}
                <span>{m.annotation_editor_recording_datetime_unknown()}</span>
              {/if}
            </span>
          </div>

          <div class="relative">
            <ClipSpectrogramPlayer
              {projectId}
              recording={{
                id: recording.id,
                filename: recording.filename,
                samplerate: recording.samplerate,
                duration: recording.duration,
              }}
              clipStart={clipStart}
              clipEnd={clipEnd}
              seekTo={seekTime ?? undefined}
              {seekNonce}
            />

            <!-- Drag-select + annotation overlay (absolute over the spectrogram area) -->
            <div
              bind:this={overlayEl}
              class="pointer-events-auto absolute inset-x-0 top-0 cursor-crosshair select-none"
              style:height="{recording ? '400px' : '0'}"
              style:z-index="3"
              role="presentation"
              onmousedown={draft.handlers.onMouseDown}
            >
              <!-- Existing annotations -->
              {#each segment.annotations as a (a.id)}
                {@const color = colorForSpecies(a.species_id)}
                {@const isSel = a.id === selectedAnnotationId}
                {@const absStart = clipStart + a.start_time_sec}
                {@const absEnd = clipStart + a.end_time_sec}
                {@const left = timeToPercent(absStart)}
                {@const width = timeToPercent(absEnd) - timeToPercent(absStart)}
                <button
                  type="button"
                  class="absolute top-0 bottom-0 overflow-hidden rounded-sm border transition-opacity"
                  class:opacity-90={isSel}
                  class:opacity-70={!isSel}
                  style:left="{left}%"
                  style:width="{width}%"
                  style:background-color={`${color}33`}
                  style:border-color={color}
                  style:border-width={isSel ? '2.5px' : '1.5px'}
                  aria-label={annotationLabel(a)}
                  aria-pressed={isSel}
                  onclick={(e) => {
                    e.stopPropagation();
                    onSelectAnnotation(a.id);
                  }}
                  onmousedown={(e) => e.stopPropagation()}
                >
                  <!-- Label badge -->
                  <span
                    class="absolute top-1 left-1 max-w-full truncate rounded px-1 py-0.5 text-[10px] font-semibold text-white"
                    style:background-color={color}
                  >
                    {annotationLabel(a)}
                  </span>
                </button>
              {/each}

              <!-- Draft range -->
              {#if draft.draftRange && !draft.isDragging}
                {@const left = timeToPercent(draft.draftRange.start)}
                {@const width = timeToPercent(draft.draftRange.end) - timeToPercent(draft.draftRange.start)}
                <div
                  class="pointer-events-none absolute top-0 bottom-0 border-2 border-dashed bg-primary-500/20"
                  style:left="{left}%"
                  style:width="{width}%"
                  style:border-color="rgb(var(--primary-500))"
                  aria-hidden="true"
                ></div>
              {/if}

              <!-- Drag preview -->
              {#if draft.isDragging}
                <div
                  class="pointer-events-none absolute top-0 bottom-0 border-2 border-dashed bg-primary-500/20"
                  style:left="{draft.dragPreview.left}%"
                  style:width="{draft.dragPreview.width}%"
                  style:border-color="rgb(var(--primary-500))"
                  aria-hidden="true"
                ></div>
              {/if}
            </div>
          </div>
        {/if}
      </section>

      <!-- Hint / draft action bar -->
      <div
        class="flex flex-wrap items-center gap-2 border-b border-stone-200 bg-surface-card px-4 py-1.5 text-xs text-stone-600 dark:border-stone-700 dark:text-stone-300"
      >
        {#if draft.draftRange}
          <span class="font-semibold text-primary-700 dark:text-primary-300">
            {m.annotation_editor_draft_title()}:
          </span>
          <span class="tabular-nums">
            {m.annotation_editor_draft_range({
              start: (draft.draftRange.start - clipStart).toFixed(2),
              end: (draft.draftRange.end - clipStart).toFixed(2),
            })}
          </span>
          <span>·</span>
          <span>{m.annotation_editor_draft_prompt()}</span>
          <button
            type="button"
            class="ml-auto rounded-md border border-stone-300 px-2 py-0.5 text-xs hover:bg-stone-50 dark:border-stone-600 dark:hover:bg-stone-800"
            onclick={cancelDraft}
          >
            {m.annotation_editor_draft_cancel()}
          </button>
        {:else if selectedAnnotation}
          <span>{m.annotation_editor_palette_click_hint()}</span>
        {:else}
          <span>{m.annotation_editor_drag_hint()}</span>
        {/if}
      </div>

      <!-- Two-column panels -->
      <div class="grid min-h-0 flex-1 gap-3 overflow-hidden p-3 md:grid-cols-[320px_1fr_320px]">
        <!-- Left: annotation list -->
        <aside
          class="overflow-y-auto rounded-lg border border-stone-200 bg-surface-card p-3 dark:border-stone-700"
          aria-label={m.annotation_editor_annotations_title()}
        >
          <AnnotationList
            annotations={segment.annotations}
            selectedId={selectedAnnotationId}
            segmentStart={clipStart}
            isBusy={isBusy}
            onSelect={onSelectAnnotation}
            onDelete={onDeleteAnnotation}
          />
        </aside>

        <!-- Middle: palette -->
        <section
          class="overflow-y-auto rounded-lg border border-stone-200 bg-surface-card p-3 dark:border-stone-700"
        >
          {#if setDetail}
            <SpeciesPalette
              palette={setDetail.palette}
              highlightedSpeciesId={selectedAnnotation?.species_id ?? null}
              isBusy={isBusy}
              onPick={pickSpecies}
              onAddSpecies={addSpeciesToPalette}
            />
          {/if}

          <!-- Shortcut cheatsheet -->
          <details class="mt-4 rounded-md border border-stone-200 p-2 text-xs text-stone-600 dark:border-stone-700 dark:text-stone-400">
            <summary class="cursor-pointer font-medium">
              {m.annotation_editor_shortcuts_title()}
            </summary>
            <ul class="mt-2 flex flex-col gap-1">
              <li>{m.annotation_editor_shortcuts_nav()}</li>
              <li>{m.annotation_editor_shortcuts_palette()}</li>
              <li>{m.annotation_editor_shortcuts_complete()}</li>
              <li>{m.annotation_editor_shortcuts_cancel()}</li>
              <li>{m.annotation_editor_shortcuts_delete()}</li>
            </ul>
          </details>
        </section>

        <!-- Right: notes -->
        <aside
          class="flex flex-col gap-4 overflow-y-auto rounded-lg border border-stone-200 bg-surface-card p-3 dark:border-stone-700"
          aria-label={m.annotation_editor_notes_title()}
        >
          <NotesPanel
            title={m.annotation_editor_notes_segment()}
            notes={segment.notes}
            isBusy={mutations.isCreatingSegmentNote}
            onAddNote={addSegmentNote}
          />

          {#if selectedAnnotation}
            <div class="border-t border-stone-200 pt-3 dark:border-stone-700">
              <NotesPanel
                title={m.annotation_editor_notes_annotation()}
                notes={[]}
                isBusy={mutations.isCreatingAnnotationNote}
                onAddNote={addAnnotationNote}
              />
              <p class="mt-1 text-[10px] text-stone-400">
                {m.annotation_editor_notes_annotation()} ·
                {selectedAnnotation.note_count}
              </p>
            </div>
          {/if}
        </aside>
      </div>
    {/if}
  </div>
</div>
