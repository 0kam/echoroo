<script lang="ts">
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { fetchAnnotationTask, completeAnnotationTask, fetchNextAnnotationTask } from '$lib/api/annotation-tasks';
  import { localizeHref, getLocale } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import {
    getOrCreateClipAnnotation,
    createSoundEvent,
    deleteSoundEvent,
    addSoundEventTag,
    removeSoundEventTag,
    addClipTag,
    removeClipTag,
  } from '$lib/api/annotations';
  import type {
    SoundEventAnnotation,
    Geometry,
    ClipAnnotationDetail,
    AnnotationTaskDetail,
    TagSummary,
    Tag,
  } from '$lib/types/annotation';
  import type { SpeciesPickerResult } from '$lib/types/species-picker';
  import ClipSpectrogramPlayer from '$lib/components/audio/ClipSpectrogramPlayer.svelte';
  import AnnotationCanvas from '$lib/components/annotation/AnnotationCanvas.svelte';
  import AnnotationList from '$lib/components/annotation/AnnotationList.svelte';
  import UnifiedSpeciesPicker from '$lib/components/shared/UnifiedSpeciesPicker.svelte';
  import TaskNavigator from '$lib/components/annotation/TaskNavigator.svelte';

  // ============================================================
  // Route parameters
  // ============================================================

  $: projectId = $page.params.id as string;
  $: annotationProjectId = $page.params.annotationProjectId as string;
  $: taskId = $page.params.taskId as string;

  // ============================================================
  // Local state
  // ============================================================

  let drawMode: 'select' | 'bbox' | 'timeinterval' = 'select';
  let selectedAnnotationId: string | null = null;
  let _currentTime: number = 0;
  let _isPlaying: boolean = false;
  let spectrogramWidth: number = 0;
  let spectrogramHeight: number = 400;
  let showInstructions: boolean = false;
  let hasUnsavedChanges: boolean = false;

  // ============================================================
  // Query client
  // ============================================================

  const queryClient = useQueryClient();

  // ============================================================
  // Queries
  // ============================================================

  // Include the active locale in the query keys so cached task/clip data is
  // separated per language (embedded tag/species names are locale-resolved).
  $: locale = getLocale();

  $: taskQuery = createQuery({
    queryKey: ['annotation-task', projectId, annotationProjectId, taskId, locale],
    queryFn: () => fetchAnnotationTask(projectId, annotationProjectId, taskId),
  });

  $: clipAnnotationQuery = createQuery({
    queryKey: ['clip-annotation', projectId, taskId, locale],
    queryFn: () => getOrCreateClipAnnotation(projectId, taskId),
    enabled: !!$taskQuery.data,
  });

  // ============================================================
  // Derived data
  // ============================================================

  $: task = $taskQuery.data as AnnotationTaskDetail | undefined;
  $: clipAnnotation = $clipAnnotationQuery.data as ClipAnnotationDetail | undefined;
  $: soundEvents = clipAnnotation?.sound_events ?? [];
  $: clipTags = clipAnnotation?.tags ?? [];
  $: notes = clipAnnotation?.notes ?? [];
  $: recording = task?.clip?.recording;
  $: clipDuration = task?.clip ? task.clip.end_time - task.clip.start_time : 0;
  $: projectTags = task?.annotation_project?.tags ?? [];
  $: instructions = task?.annotation_project?.instructions;

  /**
   * Map TagSummary[] to Tag[] for the species picker's availableTags prop.
   * The picker requires the full Tag interface (project_id, created_at, updated_at).
   */
  function toTagArray(summaries: TagSummary[]): Tag[] {
    return summaries.map((s) => ({
      id: s.id,
      name: s.name,
      category: s.category as Tag['category'],
      project_id: projectId,
      created_at: '',
      updated_at: '',
    }));
  }

  $: availableTagsFull = toTagArray(projectTags);

  // ============================================================
  // Mutations
  // ============================================================

  const createSoundEventMutation = createMutation({
    mutationFn: ({ clipAnnotationId, geometry }: { clipAnnotationId: string; geometry: Geometry }) =>
      createSoundEvent(projectId, clipAnnotationId, { geometry }),
    onSuccess: (newEvent: SoundEventAnnotation) => {
      queryClient.invalidateQueries({ queryKey: ['clip-annotation', projectId, taskId] });
      selectedAnnotationId = newEvent.id;
      hasUnsavedChanges = true;
    },
  });

  const deleteSoundEventMutation = createMutation({
    mutationFn: (soundEventId: string) => deleteSoundEvent(projectId, soundEventId),
    onSuccess: (_: void, deletedId: string) => {
      queryClient.invalidateQueries({ queryKey: ['clip-annotation', projectId, taskId] });
      if (selectedAnnotationId === deletedId) {
        selectedAnnotationId = null;
      }
    },
  });

  const addSoundEventTagMutation = createMutation({
    mutationFn: ({ soundEventId, tagId }: { soundEventId: string; tagId: string }) =>
      addSoundEventTag(projectId, soundEventId, tagId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['clip-annotation', projectId, taskId] });
    },
  });

  const removeSoundEventTagMutation = createMutation({
    mutationFn: ({ soundEventId, tagId }: { soundEventId: string; tagId: string }) =>
      removeSoundEventTag(projectId, soundEventId, tagId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['clip-annotation', projectId, taskId] });
    },
  });

  const addClipTagMutation = createMutation({
    mutationFn: ({ clipAnnotationId, tagId }: { clipAnnotationId: string; tagId: string }) =>
      addClipTag(projectId, clipAnnotationId, tagId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['clip-annotation', projectId, taskId] });
    },
  });

  const removeClipTagMutation = createMutation({
    mutationFn: ({ clipAnnotationId, tagId }: { clipAnnotationId: string; tagId: string }) =>
      removeClipTag(projectId, clipAnnotationId, tagId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['clip-annotation', projectId, taskId] });
    },
  });

  const completeTaskMutation = createMutation({
    mutationFn: () => completeAnnotationTask(projectId, annotationProjectId, taskId),
    onSuccess: (result) => {
      if (result.next_task) {
        goto(
          localizeHref(`/projects/${projectId}/annotations/${annotationProjectId}/tasks/${result.next_task.id}`)
        );
      } else {
        goto(localizeHref(`/projects/${projectId}/annotations/${annotationProjectId}`));
      }
    },
  });

  // ============================================================
  // Event handlers
  // ============================================================

  function handleCanvasCreate(event: { detail: { geometry: Geometry } }) {
    if (!clipAnnotation) return;
    $createSoundEventMutation.mutate({
      clipAnnotationId: clipAnnotation.id,
      geometry: event.detail.geometry,
    });
  }

  function handleCanvasSelect(event: { detail: { id: string } }) {
    selectedAnnotationId = event.detail.id;
  }

  function handleCanvasDelete(event: { detail: { id: string } }) {
    $deleteSoundEventMutation.mutate(event.detail.id);
  }

  function handleTagSelect(tagId: string) {
    if (selectedAnnotationId) {
      $addSoundEventTagMutation.mutate({ soundEventId: selectedAnnotationId, tagId });
    } else if (clipAnnotation) {
      $addClipTagMutation.mutate({ clipAnnotationId: clipAnnotation.id, tagId });
    }
  }

  function handleTagRemove(tagId: string) {
    if (selectedAnnotationId) {
      $removeSoundEventTagMutation.mutate({ soundEventId: selectedAnnotationId, tagId });
    } else if (clipAnnotation) {
      $removeClipTagMutation.mutate({ clipAnnotationId: clipAnnotation.id, tagId });
    }
  }

  function handleClipTagSelect(tagId: string) {
    if (clipAnnotation) {
      $addClipTagMutation.mutate({ clipAnnotationId: clipAnnotation.id, tagId });
    }
  }

  function handleClipTagRemove(tagId: string) {
    if (clipAnnotation) {
      $removeClipTagMutation.mutate({ clipAnnotationId: clipAnnotation.id, tagId });
    }
  }

  // UnifiedSpeciesPicker (mode `tag-select`) adapters. Only existing project
  // tags are selectable here (GBIF is off for parity), so a pick always
  // carries a `tag_id`; non-tag picks are ignored.
  function handleSelectedTagPick(result: SpeciesPickerResult) {
    if (result.tag_id) handleTagSelect(result.tag_id);
  }

  function handleClipTagPick(result: SpeciesPickerResult) {
    if (result.tag_id) handleClipTagSelect(result.tag_id);
  }

  function handleComplete() {
    $completeTaskMutation.mutate();
  }

  async function handleNavigateNext() {
    const nextTask = await fetchNextAnnotationTask(projectId, annotationProjectId);
    if (nextTask) {
      goto(localizeHref(`/projects/${projectId}/annotations/${annotationProjectId}/tasks/${nextTask.id}`));
    }
  }

  // ============================================================
  // Keyboard shortcuts
  // ============================================================

  function handleKeydown(event: KeyboardEvent) {
    // Ignore shortcuts when typing in an input or textarea
    const target = event.target as HTMLElement;
    if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') return;

    switch (event.key) {
      case 'v':
      case 'Escape':
        drawMode = 'select';
        break;
      case 'b':
        drawMode = 'bbox';
        break;
      case 't':
        drawMode = 'timeinterval';
        break;
      case 'Delete':
      case 'Backspace':
        if (selectedAnnotationId) {
          $deleteSoundEventMutation.mutate(selectedAnnotationId);
        }
        break;
    }

    // Ctrl+Enter to complete task
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
      event.preventDefault();
      handleComplete();
    }
  }
</script>

<svelte:head>
  <title>{m.annotation_workspace_page_title()}</title>
</svelte:head>

<svelte:window on:keydown={handleKeydown} />

<div class="workspace">
  {#if $taskQuery.isLoading}
    <div class="loading">
      <div class="spinner"></div>
      <span>{m.annotation_workspace_loading()}</span>
    </div>
  {:else if $taskQuery.isError}
    <div class="error">
      <p>{m.annotation_workspace_error_load({ message: $taskQuery.error?.message ?? '' })}</p>
      <a href={localizeHref(`/projects/${projectId}/annotations/${annotationProjectId}`)} class="back-link">
        {m.annotation_workspace_back_link()}
      </a>
    </div>
  {:else if task}
    <!-- Task Navigator bar -->
    <TaskNavigator
      {projectId}
      {annotationProjectId}
      currentTaskId={taskId}
      totalTasks={0}
      completedTasks={0}
      {hasUnsavedChanges}
      onComplete={handleComplete}
      onNavigateNext={handleNavigateNext}
    />

    <div class="workspace-content">
      <!-- Main area: Spectrogram + Canvas + Player -->
      <div class="main-panel" bind:clientWidth={spectrogramWidth}>
        <!-- Drawing mode toolbar -->
        <div class="toolbar" role="toolbar" aria-label="Drawing tools">
          <button
            class="toolbar-btn"
            class:active={drawMode === 'select'}
            on:click={() => (drawMode = 'select')}
            title={m.annotation_workspace_tool_select_title()}
            aria-pressed={drawMode === 'select'}
          >
            <svg class="tool-icon" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
              <path d="M6.3 2.841A1.5 1.5 0 004 4.11V15.89a1.5 1.5 0 002.3 1.269l9.344-5.89a1.5 1.5 0 000-2.538L6.3 2.84z" />
            </svg>
            {m.annotation_workspace_tool_select()}
            <kbd class="shortcut">V</kbd>
          </button>
          <button
            class="toolbar-btn"
            class:active={drawMode === 'bbox'}
            on:click={() => (drawMode = 'bbox')}
            title={m.annotation_workspace_tool_bbox_title()}
            aria-pressed={drawMode === 'bbox'}
          >
            <svg class="tool-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
              <rect x="3" y="5" width="14" height="10" rx="1" />
            </svg>
            {m.annotation_workspace_tool_bbox()}
            <kbd class="shortcut">B</kbd>
          </button>
          <button
            class="toolbar-btn"
            class:active={drawMode === 'timeinterval'}
            on:click={() => (drawMode = 'timeinterval')}
            title={m.annotation_workspace_tool_timeinterval_title()}
            aria-pressed={drawMode === 'timeinterval'}
          >
            <svg class="tool-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
              <line x1="3" y1="5" x2="17" y2="5" />
              <line x1="3" y1="10" x2="17" y2="10" />
              <line x1="3" y1="15" x2="17" y2="15" />
            </svg>
            {m.annotation_workspace_tool_timeinterval()}
            <kbd class="shortcut">T</kbd>
          </button>

          <div class="toolbar-separator" aria-hidden="true"></div>

          <!-- Recording info -->
          {#if recording}
            <span class="recording-info">
              {recording.filename}
            </span>
          {/if}

          <!-- Clip annotation loading state -->
          {#if $clipAnnotationQuery.isLoading}
            <span class="status-text">{m.annotation_workspace_loading_annotations()}</span>
          {/if}
        </div>

        <!-- Spectrogram with annotation canvas overlay -->
        <div class="spectrogram-wrapper" style="height: {spectrogramHeight}px;">
          {#if recording}
            <ClipSpectrogramPlayer
              {projectId}
              {recording}
              clipStart={task.clip.start_time}
              clipEnd={task.clip.end_time}
              onTimeUpdate={(t) => (_currentTime = t)}
            />
          {:else}
            <div class="spectrogram-placeholder">
              <span>{m.annotation_workspace_no_recording()}</span>
            </div>
          {/if}

          <!-- Canvas overlay positioned on top of the spectrogram -->
          <div class="canvas-overlay">
            <AnnotationCanvas
              width={spectrogramWidth}
              height={spectrogramHeight}
              duration={clipDuration}
              annotations={soundEvents}
              {selectedAnnotationId}
              mode={drawMode}
              {projectTags}
              oncreate={(detail) => handleCanvasCreate({ detail })}
              onselect={(detail) => handleCanvasSelect({ detail })}
              ondelete={(detail) => handleCanvasDelete({ detail })}
            />
          </div>
        </div>
      </div>

      <!-- Right Sidebar -->
      <aside class="sidebar" aria-label="Annotation tools">
        <!-- Tag Selector section -->
        <div class="sidebar-section">
          <h3 class="sidebar-heading">
            {#if selectedAnnotationId}
              {m.annotation_workspace_tags_sound_event()}
            {:else}
              {m.annotation_workspace_tags_clip()}
            {/if}
          </h3>

          {#if selectedAnnotationId}
            {@const selectedAnnotation = soundEvents.find((a) => a.id === selectedAnnotationId)}
            {#if selectedAnnotation}
              <UnifiedSpeciesPicker
                mode="tag-select"
                availableTags={availableTagsFull}
                selectedTagIds={selectedAnnotation.tags.map((t) => t.id)}
                onTagRemove={handleTagRemove}
                onPick={handleSelectedTagPick}
              />
            {:else}
              <p class="sidebar-hint">{m.annotation_workspace_selection_not_found()}</p>
            {/if}
          {:else}
            <p class="sidebar-hint">{m.annotation_workspace_select_annotation_hint()}</p>
            <UnifiedSpeciesPicker
              mode="tag-select"
              availableTags={availableTagsFull}
              selectedTagIds={clipTags.map((t) => t.id)}
              onTagRemove={handleClipTagRemove}
              onPick={handleClipTagPick}
            />
          {/if}
        </div>

        <!-- Annotation List section -->
        <div class="sidebar-section sidebar-section--grow">
          <h3 class="sidebar-heading">
            {m.annotation_workspace_sound_events()}
            <span class="count-badge">{soundEvents.length}</span>
          </h3>
          <AnnotationList
            annotations={soundEvents}
            {selectedAnnotationId}
            onSelect={(id) => (selectedAnnotationId = id)}
            onDelete={(id) => $deleteSoundEventMutation.mutate(id)}
          />
        </div>

        <!-- Notes summary (read-only) -->
        {#if notes.length > 0}
          <div class="sidebar-section">
            <h3 class="sidebar-heading">
              {m.annotation_workspace_notes()}
              <span class="count-badge">{notes.length}</span>
            </h3>
            <ul class="notes-list">
              {#each notes as note (note.id)}
                <li class="note-item" class:note-item--review={note.is_review}>
                  <p class="note-content">{note.content}</p>
                  {#if note.is_review}
                    <span class="note-badge">{m.annotation_workspace_note_review_badge()}</span>
                  {/if}
                </li>
              {/each}
            </ul>
          </div>
        {/if}
      </aside>
    </div>

    <!-- Instructions panel (collapsible) -->
    {#if instructions}
      <div class="instructions-panel">
        <button
          class="instructions-toggle"
          on:click={() => (showInstructions = !showInstructions)}
          aria-expanded={showInstructions}
        >
          <svg
            class="instructions-chevron"
            class:rotated={showInstructions}
            viewBox="0 0 20 20"
            fill="currentColor"
            aria-hidden="true"
          >
            <path
              fill-rule="evenodd"
              clip-rule="evenodd"
              d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
            />
          </svg>
          {showInstructions ? m.annotation_workspace_hide_instructions() : m.annotation_workspace_show_instructions()} {m.annotation_workspace_instructions_label()}
        </button>
        {#if showInstructions}
          <div class="instructions-content">
            {instructions}
          </div>
        {/if}
      </div>
    {/if}
  {/if}
</div>

<style>
  /* ============================================================
   * Workspace layout
   * ============================================================ */

  .workspace {
    display: flex;
    flex-direction: column;
    height: 100vh;
    overflow: hidden;
    background: #f9fafb;
  }

  .workspace-content {
    display: flex;
    flex: 1;
    overflow: hidden;
  }

  /* ============================================================
   * Main panel
   * ============================================================ */

  .main-panel {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: auto;
    min-width: 0;
  }

  /* ============================================================
   * Toolbar
   * ============================================================ */

  .toolbar {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    padding: 0.5rem 0.75rem;
    background: rgb(var(--color-card-bg));
    border-bottom: 1px solid #e5e7eb;
    flex-shrink: 0;
  }

  .toolbar-btn {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    padding: 0.375rem 0.625rem;
    border: 1px solid #e5e7eb;
    background: rgb(var(--color-card-bg));
    border-radius: 0.375rem;
    font-size: 0.8125rem;
    font-weight: 500;
    color: #374151;
    cursor: pointer;
    transition: background-color 0.1s ease, border-color 0.1s ease, color 0.1s ease;
    white-space: nowrap;
  }

  .toolbar-btn:hover {
    background: #f3f4f6;
    border-color: #d1d5db;
  }

  .toolbar-btn.active {
    background: #eff6ff;
    border-color: #93c5fd;
    color: #1d4ed8;
  }

  .tool-icon {
    width: 1rem;
    height: 1rem;
    flex-shrink: 0;
  }

  .shortcut {
    font-family: ui-monospace, monospace;
    font-size: 0.625rem;
    background: #f3f4f6;
    border: 1px solid #e5e7eb;
    border-radius: 0.25rem;
    padding: 0.0625rem 0.25rem;
    color: #6b7280;
    margin-left: 0.125rem;
  }

  .toolbar-btn.active .shortcut {
    background: #dbeafe;
    border-color: #bfdbfe;
    color: #1d4ed8;
  }

  .toolbar-separator {
    width: 1px;
    height: 1.5rem;
    background: #e5e7eb;
    margin: 0 0.25rem;
  }

  .recording-info {
    font-size: 0.75rem;
    color: #9ca3af;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 300px;
  }

  .status-text {
    font-size: 0.75rem;
    color: #9ca3af;
    font-style: italic;
  }

  /* ============================================================
   * Spectrogram wrapper
   * ============================================================ */

  .spectrogram-wrapper {
    position: relative;
    flex-shrink: 0;
    background: #111827;
    overflow: hidden;
  }

  .canvas-overlay {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    pointer-events: auto;
  }

  .spectrogram-placeholder {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: #6b7280;
    font-size: 0.875rem;
  }

  /* ============================================================
   * Sidebar
   * ============================================================ */

  .sidebar {
    width: 320px;
    flex-shrink: 0;
    border-left: 1px solid #e5e7eb;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    background: rgb(var(--color-card-bg));
  }

  .sidebar-section {
    padding: 0.875rem 1rem;
    border-bottom: 1px solid #f3f4f6;
  }

  .sidebar-section--grow {
    flex: 1;
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }

  .sidebar-heading {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.875rem;
    font-weight: 600;
    color: #374151;
    margin: 0 0 0.625rem 0;
  }

  .count-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 1.25rem;
    height: 1.25rem;
    padding: 0 0.25rem;
    background: #f3f4f6;
    color: #6b7280;
    border-radius: 9999px;
    font-size: 0.6875rem;
    font-weight: 600;
  }

  .sidebar-hint {
    font-size: 0.8125rem;
    color: #9ca3af;
    margin: 0 0 0.75rem 0;
    line-height: 1.4;
  }

  /* ============================================================
   * Notes
   * ============================================================ */

  .notes-list {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .note-item {
    padding: 0.5rem 0.625rem;
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 0.375rem;
  }

  .note-item--review {
    background: #fefce8;
    border-color: #fde68a;
  }

  .note-content {
    font-size: 0.8125rem;
    color: #374151;
    margin: 0 0 0.25rem 0;
    line-height: 1.4;
  }

  .note-badge {
    font-size: 0.625rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #92400e;
    background: #fef3c7;
    padding: 0.0625rem 0.375rem;
    border-radius: 9999px;
    border: 1px solid #fde68a;
  }

  /* ============================================================
   * Instructions panel
   * ============================================================ */

  .instructions-panel {
    flex-shrink: 0;
    background: rgb(var(--color-card-bg));
    border-top: 1px solid #e5e7eb;
  }

  .instructions-toggle {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    width: 100%;
    padding: 0.5rem 1rem;
    background: transparent;
    border: none;
    font-size: 0.8125rem;
    font-weight: 500;
    color: #6b7280;
    cursor: pointer;
    text-align: left;
    transition: background-color 0.1s ease, color 0.1s ease;
  }

  .instructions-toggle:hover {
    background: #f9fafb;
    color: #374151;
  }

  .instructions-chevron {
    width: 1rem;
    height: 1rem;
    transition: transform 0.2s ease;
    flex-shrink: 0;
  }

  .instructions-chevron.rotated {
    transform: rotate(180deg);
  }

  .instructions-content {
    padding: 0.75rem 1rem 1rem;
    font-size: 0.875rem;
    color: #374151;
    line-height: 1.6;
    white-space: pre-wrap;
    border-top: 1px solid #f3f4f6;
    max-height: 200px;
    overflow-y: auto;
  }

  /* ============================================================
   * Loading & error states
   * ============================================================ */

  .loading {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100vh;
    gap: 1rem;
    color: #6b7280;
    font-size: 0.875rem;
  }

  .spinner {
    width: 2.5rem;
    height: 2.5rem;
    border: 3px solid #e5e7eb;
    border-top-color: #3b82f6;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }

  .error {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100vh;
    gap: 1rem;
    color: #991b1b;
    font-size: 0.875rem;
    text-align: center;
    padding: 2rem;
  }

  .error p {
    margin: 0;
  }

  .back-link {
    color: #2563eb;
    text-decoration: none;
    font-weight: 500;
  }

  .back-link:hover {
    text-decoration: underline;
  }
</style>
