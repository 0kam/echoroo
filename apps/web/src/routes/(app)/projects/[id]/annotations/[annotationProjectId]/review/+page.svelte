<script lang="ts">
  import { page } from '$app/stores';
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { fetchAnnotationTasks, fetchAnnotationTask } from '$lib/api/annotation-tasks';
  import { getOrCreateClipAnnotation, reviewClipAnnotation } from '$lib/api/annotations';
  import { fetchAnnotationProject } from '$lib/api/annotation-projects';
  import type {
    AnnotationTask,
    AnnotationTaskDetail,
    ClipAnnotationDetail,
  } from '$lib/types/annotation';
  import ReviewPanel from '$lib/components/annotation/ReviewPanel.svelte';
  import ClipSpectrogramPlayer from '$lib/components/audio/ClipSpectrogramPlayer.svelte';

  const queryClient = useQueryClient();

  $: projectId = $page.params.id as string;
  $: annotationProjectId = $page.params.annotationProjectId as string;

  let expandedTaskId: string | null = null;
  let currentPage = 1;

  // Per-task state maps
  let clipAnnotationByTaskId: Record<string, ClipAnnotationDetail> = {};
  let clipAnnotationLoadingByTaskId: Record<string, boolean> = {};
  let clipAnnotationErrorByTaskId: Record<string, string> = {};
  let taskDetailByTaskId: Record<string, AnnotationTaskDetail> = {};
  let reviewSuccessTaskId: string | null = null;
  let reviewErrorByTaskId: Record<string, string> = {};

  // Fetch annotation project for the page title and breadcrumb
  $: projectQuery = createQuery({
    queryKey: ['annotation-project', projectId, annotationProjectId],
    queryFn: () => fetchAnnotationProject(projectId, annotationProjectId),
  });

  // Fetch tasks filtered to review_pending status
  $: tasksQuery = createQuery({
    queryKey: [
      'annotation-tasks',
      projectId,
      annotationProjectId,
      'review_pending',
      currentPage,
    ],
    queryFn: () =>
      fetchAnnotationTasks(projectId, annotationProjectId, {
        status: 'review_pending',
        page: currentPage,
        page_size: 20,
        sort_by: 'priority',
        sort_order: 'desc',
      }),
  });

  // Review mutation
  const reviewMutation = createMutation({
    mutationFn: async (vars: {
      clipAnnotationId: string;
      taskId: string;
      status: 'approved' | 'rejected';
      comment?: string;
    }) => reviewClipAnnotation(projectId, vars.clipAnnotationId, vars.status, vars.comment),
    onSuccess: (data, variables) => {
      const { taskId } = variables;
      clipAnnotationByTaskId = { ...clipAnnotationByTaskId, [taskId]: data };
      reviewSuccessTaskId = taskId;
      reviewErrorByTaskId = { ...reviewErrorByTaskId, [taskId]: '' };
      // Refresh task list so the item is removed from review_pending queue
      queryClient.invalidateQueries({
        queryKey: ['annotation-tasks', projectId, annotationProjectId, 'review_pending'],
      });
      queryClient.invalidateQueries({
        queryKey: ['annotation-project', projectId, annotationProjectId],
      });
      // Collapse and clear success indicator after a short delay
      setTimeout(() => {
        if (expandedTaskId === taskId) {
          expandedTaskId = null;
        }
        if (reviewSuccessTaskId === taskId) {
          reviewSuccessTaskId = null;
        }
      }, 2000);
    },
    onError: (error, variables) => {
      const { taskId } = variables;
      reviewErrorByTaskId = {
        ...reviewErrorByTaskId,
        [taskId]:
          error instanceof Error ? error.message : 'Failed to submit review.',
      };
    },
  });

  async function toggleExpand(task: AnnotationTask) {
    if (expandedTaskId === task.id) {
      expandedTaskId = null;
      return;
    }
    expandedTaskId = task.id;

    // Lazy-load clip annotation and task detail if not yet fetched
    if (!clipAnnotationByTaskId[task.id]) {
      clipAnnotationLoadingByTaskId = {
        ...clipAnnotationLoadingByTaskId,
        [task.id]: true,
      };
      clipAnnotationErrorByTaskId = {
        ...clipAnnotationErrorByTaskId,
        [task.id]: '',
      };
      try {
        const [clipAnnotation, taskDetail] = await Promise.all([
          getOrCreateClipAnnotation(projectId, task.id),
          fetchAnnotationTask(projectId, annotationProjectId, task.id),
        ]);
        clipAnnotationByTaskId = {
          ...clipAnnotationByTaskId,
          [task.id]: clipAnnotation,
        };
        taskDetailByTaskId = { ...taskDetailByTaskId, [task.id]: taskDetail };
      } catch (err) {
        clipAnnotationErrorByTaskId = {
          ...clipAnnotationErrorByTaskId,
          [task.id]:
            err instanceof Error
              ? err.message
              : 'Failed to load annotation data.',
        };
      } finally {
        clipAnnotationLoadingByTaskId = {
          ...clipAnnotationLoadingByTaskId,
          [task.id]: false,
        };
      }
    }
  }

  function handleApprove(task: AnnotationTask, comment?: string) {
    const clipAnnotation = clipAnnotationByTaskId[task.id];
    if (!clipAnnotation) return;
    $reviewMutation.mutate({
      clipAnnotationId: clipAnnotation.id,
      taskId: task.id,
      status: 'approved',
      comment,
    });
  }

  function handleReject(task: AnnotationTask, comment: string) {
    const clipAnnotation = clipAnnotationByTaskId[task.id];
    if (!clipAnnotation) return;
    $reviewMutation.mutate({
      clipAnnotationId: clipAnnotation.id,
      taskId: task.id,
      status: 'rejected',
      comment,
    });
  }

  function formatTime(seconds: number): string {
    const mins = Math.floor(seconds / 60);
    const secs = (seconds % 60).toFixed(1);
    return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
  }

  function formatClipRange(start: number, end: number): string {
    return `${formatTime(start)} – ${formatTime(end)}`;
  }
</script>

<svelte:head>
  <title>
    Review – {$projectQuery.data?.name ?? 'Annotation'} | Echoroo
  </title>
</svelte:head>

<div class="review-page">
  <!-- Back link -->
  <a
    href="/projects/{projectId}/annotations/{annotationProjectId}"
    class="back-link"
  >
    &larr; Back to tasks
  </a>

  <!-- Page header -->
  <header class="page-header">
    <div class="header-info">
      {#if $projectQuery.isLoading}
        <h1 class="placeholder-text">Loading...</h1>
      {:else if $projectQuery.data}
        <h1>{$projectQuery.data.name}</h1>
        <p class="header-subtitle">Annotation Review</p>
      {:else}
        <h1>Annotation Review</h1>
      {/if}
    </div>

    {#if $tasksQuery.data}
      <span class="pending-count">
        {$tasksQuery.data.total} task{$tasksQuery.data.total !== 1 ? 's' : ''} pending review
      </span>
    {/if}
  </header>

  <!-- Task list -->
  {#if $tasksQuery.isLoading}
    <div class="loading">Loading tasks pending review...</div>
  {:else if $tasksQuery.isError}
    <div class="alert alert-error">
      Error loading tasks: {$tasksQuery.error?.message ?? 'Unknown error'}
    </div>
  {:else if $tasksQuery.data}
    {#if $tasksQuery.data.items.length === 0}
      <div class="empty-state">
        <svg
          class="empty-icon"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.5"
          aria-hidden="true"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
          />
        </svg>
        <p class="empty-title">No tasks pending review</p>
        <p class="empty-hint">
          All annotations have been reviewed, or no tasks have been submitted for
          review yet.
        </p>
      </div>
    {:else}
      <div class="task-list">
        {#each $tasksQuery.data.items as task (task.id)}
          {@const isExpanded = expandedTaskId === task.id}
          {@const clipAnnotation = clipAnnotationByTaskId[task.id]}
          {@const taskDetail = taskDetailByTaskId[task.id]}
          {@const isLoadingClip = clipAnnotationLoadingByTaskId[task.id] ?? false}
          {@const clipError = clipAnnotationErrorByTaskId[task.id] ?? ''}
          {@const reviewError = reviewErrorByTaskId[task.id] ?? ''}
          {@const reviewedSuccessfully = reviewSuccessTaskId === task.id}

          <div
            class="task-card"
            class:task-card--expanded={isExpanded}
          >
            <!-- Task header row (click to expand/collapse) -->
            <button
              type="button"
              class="task-header"
              on:click={() => toggleExpand(task)}
              aria-expanded={isExpanded}
              aria-controls="task-body-{task.id}"
            >
              <div class="task-header-left">
                <svg
                  class="chevron"
                  class:chevron--open={isExpanded}
                  viewBox="0 0 16 16"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  aria-hidden="true"
                >
                  <path stroke-linecap="round" stroke-linejoin="round" d="M4 6l4 4 4-4" />
                </svg>

                <span class="task-clip-id" title="Clip ID: {task.clip_id}">
                  Clip <code>{task.clip_id.slice(0, 8)}&hellip;</code>
                </span>

                <!-- Review status pill -->
                {#if clipAnnotation}
                  <span
                    class="review-status-badge review-status-badge--{clipAnnotation.review_status}"
                  >
                    {clipAnnotation.review_status}
                  </span>
                {:else}
                  <span class="review-status-badge review-status-badge--unreviewed">
                    pending
                  </span>
                {/if}
              </div>

              <div class="task-header-right">
                {#if clipAnnotation}
                  <span class="meta-chip">
                    {clipAnnotation.tags.length} tag{clipAnnotation.tags.length !== 1 ? 's' : ''}
                  </span>
                  <span class="meta-chip">
                    {clipAnnotation.sound_events.length} event{clipAnnotation.sound_events.length !== 1 ? 's' : ''}
                  </span>
                {/if}
                {#if task.priority > 0}
                  <span class="priority-chip" title="Priority">
                    P{task.priority}
                  </span>
                {/if}
              </div>
            </button>

            <!-- Expandable task body -->
            {#if isExpanded}
              <div id="task-body-{task.id}" class="task-body">
                {#if isLoadingClip}
                  <div class="body-loading">
                    <div class="spinner"></div>
                    <span>Loading annotation data...</span>
                  </div>
                {:else if clipError}
                  <div class="alert alert-error body-alert">
                    {clipError}
                  </div>
                {:else if clipAnnotation && taskDetail}
                  <!-- Spectrogram and audio player -->
                  {#if taskDetail.clip.recording}
                    <div class="media-section">
                      <div class="media-header">
                        <span class="media-filename">
                          {taskDetail.clip.recording.filename}
                        </span>
                        <span class="media-range">
                          {formatClipRange(
                            taskDetail.clip.start_time,
                            taskDetail.clip.end_time
                          )}
                        </span>
                      </div>

                      <div class="spectrogram-wrapper">
                        <ClipSpectrogramPlayer
                          {projectId}
                          recording={taskDetail.clip.recording}
                          clipStart={taskDetail.clip.start_time}
                          clipEnd={taskDetail.clip.end_time}
                        />
                      </div>
                    </div>
                  {/if}

                  <!-- Annotation summary -->
                  <div class="annotation-summary">
                    <!-- Clip-level tags -->
                    {#if clipAnnotation.tags.length > 0}
                      <div class="summary-row">
                        <span class="summary-label">Clip Tags</span>
                        <div class="tag-chips">
                          {#each clipAnnotation.tags as tag (tag.id)}
                            <span
                              class="tag-chip tag-chip--{tag.category}"
                              title={tag.category}
                            >
                              {tag.name}
                            </span>
                          {/each}
                        </div>
                      </div>
                    {/if}

                    <!-- Sound events -->
                    <div class="summary-row">
                      <span class="summary-label">
                        Events ({clipAnnotation.sound_events.length})
                      </span>
                      {#if clipAnnotation.sound_events.length === 0}
                        <span class="no-events">No sound events annotated</span>
                      {:else}
                        <ul class="sound-events-list">
                          {#each clipAnnotation.sound_events as event (event.id)}
                            <li class="sound-event-item">
                              <span
                                class="event-source event-source--{event.source}"
                              >
                                {event.source}
                              </span>
                              {#if event.tags.length > 0}
                                <span class="event-tags">
                                  {event.tags.map((t) => t.name).join(', ')}
                                </span>
                              {:else}
                                <span class="event-no-tags">No tags</span>
                              {/if}
                              {#if event.confidence !== null && event.confidence !== undefined}
                                <span class="event-confidence">
                                  {Math.round(event.confidence * 100)}%
                                </span>
                              {/if}
                            </li>
                          {/each}
                        </ul>
                      {/if}
                    </div>
                  </div>

                  <!-- Review feedback -->
                  {#if reviewedSuccessfully}
                    <div class="alert alert-success body-alert">
                      Review submitted successfully.
                    </div>
                  {/if}
                  {#if reviewError}
                    <div class="alert alert-error body-alert">
                      {reviewError}
                    </div>
                  {/if}

                  <!-- Review panel -->
                  <div class="review-panel-wrapper">
                    <ReviewPanel
                      clipAnnotationId={clipAnnotation.id}
                      reviewStatus={clipAnnotation.review_status}
                      reviewedById={clipAnnotation.reviewed_by_id ?? null}
                      reviewedAt={clipAnnotation.reviewed_at ?? null}
                      notes={clipAnnotation.notes}
                      onApprove={(comment) => handleApprove(task, comment)}
                      onReject={(comment) => handleReject(task, comment)}
                    />
                  </div>
                {:else if clipAnnotation}
                  <!-- Clip annotation loaded but task detail still loading -->
                  <div class="body-loading">
                    <div class="spinner"></div>
                    <span>Loading task details...</span>
                  </div>
                {/if}
              </div>
            {/if}
          </div>
        {/each}
      </div>

      <!-- Pagination -->
      {#if $tasksQuery.data.pages > 1}
        <div class="pagination">
          <button
            class="page-btn"
            on:click={() => (currentPage = Math.max(1, currentPage - 1))}
            disabled={currentPage === 1}
          >
            Previous
          </button>
          <span class="page-info">
            Page {currentPage} of {$tasksQuery.data.pages}
          </span>
          <button
            class="page-btn"
            on:click={() =>
              (currentPage = Math.min($tasksQuery.data.pages, currentPage + 1))}
            disabled={currentPage === $tasksQuery.data.pages}
          >
            Next
          </button>
        </div>
      {/if}

      <div class="pagination-info">
        Showing {$tasksQuery.data.items.length} of {$tasksQuery.data.total} tasks
      </div>
    {/if}
  {/if}
</div>

<style>
  .review-page {
    max-width: 1100px;
    margin: 0 auto;
    padding: 2rem;
  }

  /* ---- Back link ---- */
  .back-link {
    display: inline-block;
    margin-bottom: 1.25rem;
    font-size: 0.875rem;
    color: #6b7280;
    text-decoration: none;
  }

  .back-link:hover {
    color: #374151;
  }

  /* ---- Page header ---- */
  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 1.75rem;
    gap: 1rem;
    flex-wrap: wrap;
  }

  .header-info h1 {
    margin: 0 0 0.125rem 0;
    font-size: 1.5rem;
    font-weight: 600;
    color: #111827;
  }

  .header-subtitle {
    margin: 0;
    font-size: 0.875rem;
    color: #6b7280;
  }

  .placeholder-text {
    color: #9ca3af;
  }

  .pending-count {
    padding: 0.375rem 0.875rem;
    background: #fef9c3;
    color: #a16207;
    border: 1px solid #fde68a;
    border-radius: 9999px;
    font-size: 0.8125rem;
    font-weight: 500;
    white-space: nowrap;
    flex-shrink: 0;
  }

  /* ---- Alerts ---- */
  .alert {
    padding: 0.75rem 1rem;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    margin-bottom: 1rem;
  }

  .alert-error {
    background: #fef2f2;
    border: 1px solid #fecaca;
    color: #dc2626;
  }

  .alert-success {
    background: #f0fdf4;
    border: 1px solid #bbf7d0;
    color: #16a34a;
  }

  .body-alert {
    margin: 0.75rem;
    margin-bottom: 0;
  }

  /* ---- Loading ---- */
  .loading {
    padding: 3rem 2rem;
    text-align: center;
    background: #f3f4f6;
    border-radius: 0.5rem;
    color: #6b7280;
    font-size: 0.875rem;
  }

  /* ---- Empty state ---- */
  .empty-state {
    padding: 4rem 2rem;
    text-align: center;
    border: 2px dashed #e5e7eb;
    border-radius: 0.5rem;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.75rem;
    color: #6b7280;
  }

  .empty-icon {
    width: 48px;
    height: 48px;
    color: #9ca3af;
  }

  .empty-title {
    margin: 0;
    font-size: 1rem;
    font-weight: 600;
    color: #374151;
  }

  .empty-hint {
    margin: 0;
    font-size: 0.875rem;
    color: #9ca3af;
    max-width: 400px;
    line-height: 1.5;
  }

  /* ---- Task list ---- */
  .task-list {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  /* ---- Task card ---- */
  .task-card {
    background: #fff;
    border: 1px solid #e5e7eb;
    border-radius: 0.5rem;
    overflow: hidden;
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
  }

  .task-card--expanded {
    border-color: #93c5fd;
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.08);
  }

  /* ---- Task header button ---- */
  .task-header {
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.875rem 1rem;
    background: none;
    border: none;
    cursor: pointer;
    text-align: left;
    gap: 0.75rem;
    font-family: inherit;
    transition: background-color 0.1s ease;
  }

  .task-header:hover {
    background: #f9fafb;
  }

  .task-header:focus-visible {
    outline: 2px solid #3b82f6;
    outline-offset: -2px;
  }

  .task-header-left {
    display: flex;
    align-items: center;
    gap: 0.625rem;
    flex: 1;
    min-width: 0;
  }

  .task-header-right {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-shrink: 0;
  }

  /* ---- Chevron ---- */
  .chevron {
    width: 1rem;
    height: 1rem;
    color: #9ca3af;
    flex-shrink: 0;
    transition: transform 0.15s ease;
  }

  .chevron--open {
    transform: rotate(180deg);
  }

  /* ---- Task clip ID ---- */
  .task-clip-id {
    font-size: 0.875rem;
    color: #374151;
    white-space: nowrap;
  }

  .task-clip-id code {
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 0.8125rem;
    color: #6b7280;
    background: #f3f4f6;
    padding: 0.0625rem 0.25rem;
    border-radius: 0.25rem;
  }

  /* ---- Review status pill ---- */
  .review-status-badge {
    display: inline-flex;
    align-items: center;
    padding: 0.125rem 0.5rem;
    border-radius: 9999px;
    font-size: 0.6875rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .review-status-badge--unreviewed,
  .review-status-badge--pending {
    background: #fef9c3;
    color: #a16207;
    border: 1px solid #fde68a;
  }

  .review-status-badge--approved {
    background: #f0fdf4;
    color: #15803d;
    border: 1px solid #bbf7d0;
  }

  .review-status-badge--rejected {
    background: #fef2f2;
    color: #dc2626;
    border: 1px solid #fecaca;
  }

  /* ---- Meta chips (tag/event count) ---- */
  .meta-chip {
    display: inline-flex;
    align-items: center;
    padding: 0.125rem 0.5rem;
    background: #f3f4f6;
    color: #6b7280;
    border-radius: 9999px;
    font-size: 0.6875rem;
    font-weight: 500;
    white-space: nowrap;
  }

  .priority-chip {
    display: inline-flex;
    align-items: center;
    padding: 0.125rem 0.5rem;
    background: #eff6ff;
    color: #1d4ed8;
    border: 1px solid #bfdbfe;
    border-radius: 9999px;
    font-size: 0.6875rem;
    font-weight: 600;
    white-space: nowrap;
  }

  /* ---- Task body ---- */
  .task-body {
    border-top: 1px solid #e5e7eb;
  }

  .body-loading {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 1.5rem 1rem;
    color: #6b7280;
    font-size: 0.875rem;
  }

  /* ---- Spinner ---- */
  .spinner {
    width: 20px;
    height: 20px;
    border: 2px solid #e5e7eb;
    border-top-color: #3b82f6;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    flex-shrink: 0;
  }

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }

  /* ---- Media section ---- */
  .media-section {
    padding: 0.75rem;
    border-bottom: 1px solid #f3f4f6;
    display: flex;
    flex-direction: column;
    gap: 0.625rem;
  }

  .media-header {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
  }

  .media-filename {
    font-size: 0.8125rem;
    font-weight: 500;
    color: #374151;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    word-break: break-all;
  }

  .media-range {
    font-size: 0.75rem;
    color: #9ca3af;
    white-space: nowrap;
  }

  .spectrogram-wrapper {
    border-radius: 0.375rem;
    overflow: hidden;
    border: 1px solid #e5e7eb;
  }

  .audio-wrapper {
    border-radius: 0.375rem;
    overflow: hidden;
  }

  /* ---- Annotation summary ---- */
  .annotation-summary {
    padding: 0.75rem;
    border-bottom: 1px solid #f3f4f6;
    display: flex;
    flex-direction: column;
    gap: 0.625rem;
  }

  .summary-row {
    display: flex;
    align-items: flex-start;
    gap: 0.625rem;
    flex-wrap: wrap;
  }

  .summary-label {
    font-size: 0.6875rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #9ca3af;
    white-space: nowrap;
    padding-top: 0.125rem;
    min-width: 5.5rem;
    flex-shrink: 0;
  }

  /* ---- Tag chips ---- */
  .tag-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 0.375rem;
  }

  .tag-chip {
    display: inline-flex;
    align-items: center;
    padding: 0.125rem 0.5rem;
    border-radius: 9999px;
    font-size: 0.6875rem;
    font-weight: 500;
  }

  .tag-chip--species {
    background: #dcfce7;
    color: #166534;
  }

  .tag-chip--sound_type {
    background: #dbeafe;
    color: #1e40af;
  }

  .tag-chip--quality {
    background: #fef9c3;
    color: #854d0e;
  }

  /* ---- Sound events list ---- */
  .sound-events-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    flex: 1;
  }

  .sound-event-item {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.8125rem;
    color: #374151;
    padding: 0.25rem 0;
  }

  .event-source {
    display: inline-flex;
    align-items: center;
    padding: 0.0625rem 0.375rem;
    border-radius: 0.25rem;
    font-size: 0.6875rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    flex-shrink: 0;
  }

  .event-source--human {
    background: #eff6ff;
    color: #1d4ed8;
  }

  .event-source--model {
    background: #f3e8ff;
    color: #7c3aed;
  }

  .event-tags {
    color: #374151;
    font-size: 0.8125rem;
    flex: 1;
  }

  .event-no-tags {
    color: #9ca3af;
    font-size: 0.8125rem;
    font-style: italic;
    flex: 1;
  }

  .event-confidence {
    font-size: 0.75rem;
    color: #6b7280;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    flex-shrink: 0;
  }

  .no-events {
    font-size: 0.8125rem;
    color: #9ca3af;
    font-style: italic;
  }

  /* ---- Review panel wrapper ---- */
  .review-panel-wrapper {
    border-top: 1px solid #f3f4f6;
    background: #fafafa;
  }

  /* ---- Pagination ---- */
  .pagination {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 1rem;
    margin-top: 1.5rem;
  }

  .page-btn {
    padding: 0.5rem 1rem;
    background: white;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    cursor: pointer;
    font-family: inherit;
    transition: background-color 0.1s ease;
  }

  .page-btn:hover:not(:disabled) {
    background: #f9fafb;
  }

  .page-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .page-info {
    font-size: 0.875rem;
    color: #6b7280;
  }

  .pagination-info {
    margin-top: 1rem;
    text-align: center;
    font-size: 0.875rem;
    color: #9ca3af;
  }
</style>
