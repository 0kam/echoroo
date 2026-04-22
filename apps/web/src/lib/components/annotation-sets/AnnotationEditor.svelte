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
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import * as m from '$lib/paraglide/messages';
  import { localizeHref } from '$lib/paraglide/runtime';
  import { toasts } from '$lib/stores/toast';
  import ClipSpectrogramPlayer from '$lib/components/audio/ClipSpectrogramPlayer.svelte';
  import SegmentNavigator from '$lib/components/annotation-sets/SegmentNavigator.svelte';
  import SpeciesPalette from '$lib/components/annotation-sets/SpeciesPalette.svelte';
  import AnnotationList from '$lib/components/annotation-sets/AnnotationList.svelte';
  import NotesPanel from '$lib/components/annotation-sets/NotesPanel.svelte';
  import { useAnnotationDraft } from '$lib/components/annotation-sets/useAnnotationDraft.svelte';
  import {
    addPalette,
    createAnnotation,
    createAnnotationNote,
    createSegmentNote,
    deleteAnnotation,
    getAnnotationSet,
    getSegment,
    listSegments,
    updateAnnotation,
    updateSegment,
  } from '$lib/api/annotation-sets';
  import { getRecording } from '$lib/api/recordings';
  import type {
    AnnotationSegmentDetail,
    AnnotationSegmentSummary,
    AnnotationSetDetail,
    TimeRangeAnnotation,
    TimeRangeAnnotationCreate,
  } from '$lib/types/annotation-set';
  import type { RecordingDetail } from '$lib/types/data';

  interface Props {
    projectId: string;
    setId: string;
    segmentId: string;
  }

  let { projectId, setId, segmentId }: Props = $props();

  const queryClient = useQueryClient();

  // ============================================================
  // Queries
  // ============================================================

  const setQuery = $derived(
    createQuery({
      queryKey: ['annotation-set', setId],
      queryFn: () => getAnnotationSet(setId),
      refetchOnWindowFocus: false,
    }),
  );

  const segmentQuery = $derived(
    createQuery({
      queryKey: ['annotation-segment', segmentId],
      queryFn: () => getSegment(segmentId),
      refetchOnWindowFocus: false,
    }),
  );

  // Full ordered list of segments for prev/next navigation.
  const segmentsListQuery = $derived(
    createQuery({
      queryKey: ['annotation-set-segments', setId, 'all'],
      queryFn: () => listSegments(setId, { page_size: 500 }),
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
   * Draft state machine + drag geometry. See
   * `./useAnnotationDraft.svelte.ts` for details; the hook owns window
   * mousemove / mouseup subscriptions and exposes the finalised draft range
   * plus a transient drag-preview bar geometry.
   */
  const draft = useAnnotationDraft({
    overlayEl: () => overlayEl,
    clipStart: () => clipStart,
    clipDuration: () => clipDuration,
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
  });

  // A newly-committed draft should clear any previous annotation selection
  // (pre-refactor this lived inside handleWindowMouseUp).
  $effect(() => {
    if (draft.draftRange) {
      selectedAnnotationId = null;
    }
  });

  // ============================================================
  // Mutations
  // ============================================================

  const createAnnotationMutation = createMutation({
    mutationFn: (body: TimeRangeAnnotationCreate) =>
      createAnnotation(segmentId, body),
    onSuccess: () => {
      draft.clear();
      queryClient.invalidateQueries({ queryKey: ['annotation-segment', segmentId] });
      queryClient.invalidateQueries({ queryKey: ['annotation-set', setId] });
      toasts.success(m.annotation_editor_create_success());
    },
    onError: (err: Error) => {
      toasts.error(err.message || m.annotation_editor_create_error());
    },
  });

  const updateAnnotationSpeciesMutation = createMutation({
    mutationFn: (args: { id: string; speciesId: string }) =>
      updateAnnotation(args.id, { species_id: args.speciesId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['annotation-segment', segmentId] });
      toasts.success(m.annotation_editor_update_success());
    },
    onError: () => toasts.error(m.annotation_editor_update_error()),
  });

  const deleteAnnotationMutation = createMutation({
    mutationFn: (id: string) => deleteAnnotation(id),
    onSuccess: () => {
      selectedAnnotationId = null;
      queryClient.invalidateQueries({ queryKey: ['annotation-segment', segmentId] });
      queryClient.invalidateQueries({ queryKey: ['annotation-set', setId] });
      toasts.success(m.annotation_editor_delete_success());
    },
    onError: () => toasts.error(m.annotation_editor_delete_error()),
  });

  const updateSegmentMutation = createMutation({
    mutationFn: (body: { status?: AnnotationSegmentDetail['status']; is_empty?: boolean }) =>
      updateSegment(segmentId, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['annotation-segment', segmentId] });
      queryClient.invalidateQueries({ queryKey: ['annotation-set', setId] });
      queryClient.invalidateQueries({ queryKey: ['annotation-set-segments', setId] });
    },
    onError: (err: Error) => {
      toasts.error(err.message || m.annotation_editor_status_update_error());
    },
  });

  const addPaletteMutation = createMutation({
    mutationFn: (speciesId: string) => addPalette(setId, { species_id: speciesId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['annotation-set', setId] });
    },
    onError: () => toasts.error(m.annotation_sets_palette_add_error()),
  });

  const createSegmentNoteMutation = createMutation({
    mutationFn: (body: { content: string; is_issue: boolean }) =>
      createSegmentNote(segmentId, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['annotation-segment', segmentId] });
      toasts.success(m.annotation_editor_note_create_success());
    },
    onError: () => toasts.error(m.annotation_editor_note_create_error()),
  });

  const createAnnotationNoteMutation = createMutation({
    mutationFn: (args: { annotationId: string; content: string; is_issue: boolean }) =>
      createAnnotationNote(args.annotationId, {
        content: args.content,
        is_issue: args.is_issue,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['annotation-segment', segmentId] });
      toasts.success(m.annotation_editor_note_create_success());
    },
    onError: () => toasts.error(m.annotation_editor_note_create_error()),
  });

  const isBusy = $derived(
    $createAnnotationMutation.isPending ||
      $updateAnnotationSpeciesMutation.isPending ||
      $deleteAnnotationMutation.isPending ||
      $updateSegmentMutation.isPending ||
      $addPaletteMutation.isPending ||
      $createSegmentNoteMutation.isPending ||
      $createAnnotationNoteMutation.isPending,
  );

  // ============================================================
  // Actions
  // ============================================================

  function pickSpecies(speciesId: string) {
    const currentDraft = draft.draftRange;
    if (currentDraft) {
      // Backend expects seconds relative to the segment start
      // (0..segment_duration). Convert from the absolute recording-seconds
      // draft we track internally and clamp to valid range.
      const relStart = Math.max(0, currentDraft.start - clipStart);
      const relEnd = Math.min(clipDuration, currentDraft.end - clipStart);
      if (relEnd <= relStart) {
        toasts.error(m.annotation_editor_create_error());
        return;
      }
      $createAnnotationMutation.mutate({
        start_time_sec: relStart,
        end_time_sec: relEnd,
        species_id: speciesId,
      });
      return;
    }
    if (selectedAnnotationId) {
      $updateAnnotationSpeciesMutation.mutate({
        id: selectedAnnotationId,
        speciesId,
      });
    }
  }

  function cancelDraft() {
    draft.clear();
  }

  function onDeleteAnnotation(id: string) {
    if (confirm(m.annotation_editor_annotation_delete_confirm())) {
      $deleteAnnotationMutation.mutate(id);
    }
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
    await $updateSegmentMutation.mutateAsync({ status: 'annotated' });
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
    await $updateSegmentMutation.mutateAsync({ status: 'skipped' });
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
    $updateSegmentMutation.mutate({ is_empty: true, status: 'annotated' });
  }

  function clearNoVocalization() {
    if (!segment) return;
    $updateSegmentMutation.mutate({ is_empty: false, status: 'unannotated' });
  }

  function addSpeciesToPalette(speciesId: string) {
    $addPaletteMutation.mutate(speciesId);
  }

  async function addSegmentNote(content: string, isIssue: boolean) {
    await $createSegmentNoteMutation.mutateAsync({ content, is_issue: isIssue });
  }

  async function addAnnotationNote(content: string, isIssue: boolean) {
    if (!selectedAnnotationId) return;
    await $createAnnotationNoteMutation.mutateAsync({
      annotationId: selectedAnnotationId,
      content,
      is_issue: isIssue,
    });
  }

  // ============================================================
  // Keyboard: Esc cancels draft/selection, Delete removes selected annotation
  // ============================================================
  //
  // Keydown is owned exclusively by this parent component (plan.md §3.4).
  // The draft hook deliberately does NOT subscribe to keyboard events —
  // centralising here keeps the IME / input-focus guard in one place and
  // avoids hook-to-hook coupling when the mutation hook lands in Step 2.
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
        // Routed directly to the local action; Step 2 will dispatch this
        // through the mutation hook instead.
        onDeleteAnnotation(selectedAnnotationId);
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  });

  onDestroy(() => {
    draft.dispose();
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
    return a.species_common_name ?? a.species_scientific_name;
  }
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
            isBusy={$createSegmentNoteMutation.isPending}
            onAddNote={addSegmentNote}
          />

          {#if selectedAnnotation}
            <div class="border-t border-stone-200 pt-3 dark:border-stone-700">
              <NotesPanel
                title={m.annotation_editor_notes_annotation()}
                notes={[]}
                isBusy={$createAnnotationNoteMutation.isPending}
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
