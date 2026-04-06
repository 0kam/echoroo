<script lang="ts">
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { fetchAnnotationTasks, fetchNextAnnotationTask } from '$lib/api/annotation-tasks';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import { fetchAnnotationProject, generateTasks } from '$lib/api/annotation-projects';
  import { apiClient } from '$lib/api/client';
  import type { AnnotationTaskStatus, AnnotationTask, AnnotationProjectDetail } from '$lib/types/annotation';
  import { getAnnotationTaskStatusClass, getAnnotationTaskStatusLabel } from '$lib/utils/statusFormatters';
  import ExportDialog from '$lib/components/annotation/ExportDialog.svelte';

  const queryClient = useQueryClient();

  $: projectId = $page.params.id as string;
  $: annotationProjectId = $page.params.annotationProjectId as string;

  // Filter and sort state
  let statusFilter: AnnotationTaskStatus | '' = '';
  let currentPage = 1;
  let sortBy: 'priority' | 'created_at' | 'status' = 'priority';
  let sortOrder: 'asc' | 'desc' = 'desc';

  // Feedback state
  let noTasksMessage = '';

  // Batch tag mode state
  let batchMode = false;
  let selectedTaskIds: string[] = [];
  let showBatchTagDialog = false;
  let batchTagId = '';
  let batchTagError = '';
  let isBatchTagPending = false;

  // Export dialog state
  let showExportDialog = false;

  // Fetch annotation project details
  $: projectQuery = createQuery({
    queryKey: ['annotation-project', projectId, annotationProjectId],
    queryFn: () => fetchAnnotationProject(projectId, annotationProjectId),
  });

  // Fetch task list with filters
  $: tasksQuery = createQuery({
    queryKey: ['annotation-tasks', projectId, annotationProjectId, statusFilter, currentPage, sortBy, sortOrder],
    queryFn: () =>
      fetchAnnotationTasks(projectId, annotationProjectId, {
        status: statusFilter || undefined,
        page: currentPage,
        page_size: 20,
        sort_by: sortBy,
        sort_order: sortOrder,
      }),
  });

  // Mutation: generate tasks
  const generateTasksMutation = createMutation({
    mutationFn: () => generateTasks(projectId, annotationProjectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['annotation-tasks', projectId, annotationProjectId] });
      queryClient.invalidateQueries({ queryKey: ['annotation-project', projectId, annotationProjectId] });
    },
  });

  // Mutation: start annotating (fetch next task and navigate)
  const startAnnotatingMutation = createMutation({
    mutationFn: () => fetchNextAnnotationTask(projectId, annotationProjectId),
    onSuccess: (task) => {
      if (task) {
        goto(localizeHref(`/projects/${projectId}/annotations/${annotationProjectId}/tasks/${task.id}`));
      } else {
        noTasksMessage = m.annotation_task_no_tasks();
      }
    },
  });

  function handleStatusFilterChange(event: Event) {
    const target = event.target as HTMLSelectElement;
    statusFilter = target.value as AnnotationTaskStatus | '';
    currentPage = 1;
  }

  function handleSortChange(event: Event) {
    const target = event.target as HTMLSelectElement;
    const value = target.value;
    if (value === 'priority_desc') {
      sortBy = 'priority';
      sortOrder = 'desc';
    } else if (value === 'created_at_asc') {
      sortBy = 'created_at';
      sortOrder = 'asc';
    } else if (value === 'created_at_desc') {
      sortBy = 'created_at';
      sortOrder = 'desc';
    } else if (value === 'status_asc') {
      sortBy = 'status';
      sortOrder = 'asc';
    }
    currentPage = 1;
  }

  $: sortSelectValue =
    sortBy === 'priority' && sortOrder === 'desc'
      ? 'priority_desc'
      : sortBy === 'created_at' && sortOrder === 'asc'
        ? 'created_at_asc'
        : sortBy === 'created_at' && sortOrder === 'desc'
          ? 'created_at_desc'
          : 'status_asc';

  function navigateToTask(task: AnnotationTask) {
    if (batchMode) return;
    goto(localizeHref(`/projects/${projectId}/annotations/${annotationProjectId}/tasks/${task.id}`));
  }

  function getStatusBadgeClass(status: AnnotationTaskStatus): string {
    return getAnnotationTaskStatusClass(status);
  }

  function getStatusLabel(status: AnnotationTaskStatus): string {
    return getAnnotationTaskStatusLabel(status, {
      pending: m.annotation_task_status_pending,
      in_progress: m.annotation_task_status_in_progress,
      completed: m.annotation_task_status_completed,
      review_pending: m.annotation_task_status_review_pending,
    });
  }

  function formatTime(seconds: number): string {
    const mins = Math.floor(seconds / 60);
    const secs = (seconds % 60).toFixed(1);
    return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
  }

  $: progressData = $projectQuery.data?.progress;
  $: completedPercent =
    progressData && progressData.total_tasks > 0
      ? Math.round((progressData.completed_tasks / progressData.total_tasks) * 100)
      : 0;

  // Batch mode helpers
  function toggleBatchMode() {
    batchMode = !batchMode;
    if (!batchMode) {
      selectedTaskIds = [];
      showBatchTagDialog = false;
      batchTagId = '';
      batchTagError = '';
    }
  }

  function toggleTaskSelection(taskId: string) {
    if (selectedTaskIds.includes(taskId)) {
      selectedTaskIds = selectedTaskIds.filter((id) => id !== taskId);
    } else {
      selectedTaskIds = [...selectedTaskIds, taskId];
    }
  }

  function selectAllTasks() {
    const items = $tasksQuery.data?.items ?? [];
    selectedTaskIds = items.map((t) => t.id);
  }

  function clearSelection() {
    selectedTaskIds = [];
  }

  function openBatchTagDialog() {
    batchTagId = '';
    batchTagError = '';
    showBatchTagDialog = true;
  }

  function closeBatchTagDialog() {
    showBatchTagDialog = false;
    batchTagId = '';
    batchTagError = '';
  }

  async function executeBatchTag() {
    if (!batchTagId) {
      batchTagError = m.annotation_task_batch_error_no_tag();
      return;
    }
    if (selectedTaskIds.length === 0) {
      batchTagError = m.annotation_task_batch_error_no_tasks();
      return;
    }

    isBatchTagPending = true;
    batchTagError = '';

    try {
      await apiClient.post(
        `/api/v1/projects/${projectId}/clip-annotations/batch-tag`,
        { task_ids: selectedTaskIds, tag_id: batchTagId }
      );

      // Invalidate queries to refresh task list
      queryClient.invalidateQueries({ queryKey: ['annotation-tasks', projectId, annotationProjectId] });

      // Reset batch state
      showBatchTagDialog = false;
      selectedTaskIds = [];
      batchTagId = '';
      batchMode = false;
    } catch (err) {
      batchTagError = err instanceof Error ? err.message : m.annotation_task_batch_error_failed();
    } finally {
      isBatchTagPending = false;
    }
  }

  // Available tags from the annotation project
  $: availableTags = $projectQuery.data?.tags ?? [];
</script>

<svelte:head>
  <title>
    {$projectQuery.data?.name ?? m.annotation_task_page_title()} | Annotation
  </title>
</svelte:head>

<div class="tasks-page">
  <!-- Back link -->
  <a href={localizeHref(`/projects/${projectId}/annotations`)} class="back-link">
    &larr; {m.annotation_task_back_link()}
  </a>

  <!-- Header -->
  <header class="page-header">
    <div class="header-info">
      {#if $projectQuery.isLoading}
        <h1 class="placeholder-text">{m.common_loading()}</h1>
      {:else if $projectQuery.data}
        <h1>{$projectQuery.data.name}</h1>
        {#if $projectQuery.data.description}
          <p class="description">{$projectQuery.data.description}</p>
        {/if}
      {:else}
        <h1>{m.annotation_task_loading()}</h1>
      {/if}
    </div>

    <div class="header-actions">
      <button
        class="btn-secondary"
        on:click={() => (showExportDialog = true)}
      >
        {m.annotation_task_export_button()}
      </button>
      <button
        class="btn-secondary"
        class:btn-active={batchMode}
        on:click={toggleBatchMode}
      >
        {batchMode ? m.annotation_task_exit_batch() : m.annotation_task_batch_tag()}
      </button>
      <a
        href={localizeHref(`/projects/${projectId}/annotations/${annotationProjectId}/review`)}
        class="btn-secondary"
      >
        {m.annotation_task_review_button()}
      </a>
      <button
        class="btn-secondary"
        on:click={() => $generateTasksMutation.mutate()}
        disabled={$generateTasksMutation.isPending}
      >
        {$generateTasksMutation.isPending ? m.annotation_task_generating() : m.annotation_task_generate_button()}
      </button>
      <button
        class="btn-primary"
        on:click={() => {
          noTasksMessage = '';
          $startAnnotatingMutation.mutate();
        }}
        disabled={$startAnnotatingMutation.isPending}
      >
        {$startAnnotatingMutation.isPending ? m.annotation_task_finding() : m.annotation_task_start_annotating()}
      </button>
    </div>
  </header>

  <!-- Mutation feedback -->
  {#if $generateTasksMutation.isError}
    <div class="alert alert-error">
      {m.annotation_task_generate_error({ message: $generateTasksMutation.error?.message ?? '' })}
    </div>
  {/if}

  {#if $generateTasksMutation.isSuccess}
    <div class="alert alert-success">
      {m.annotation_task_generate_success()}
    </div>
  {/if}

  {#if $startAnnotatingMutation.isError}
    <div class="alert alert-error">
      {m.annotation_task_fetch_error({ message: $startAnnotatingMutation.error?.message ?? '' })}
    </div>
  {/if}

  {#if noTasksMessage}
    <div class="alert alert-info">
      {noTasksMessage}
    </div>
  {/if}

  <!-- Progress summary -->
  {#if progressData}
    <div class="progress-card">
      <h2 class="progress-title">{m.annotation_task_progress_title()}</h2>
      <div class="progress-stats">
        <div class="stat">
          <span class="stat-value">{progressData.total_tasks}</span>
          <span class="stat-label">{m.annotation_task_total()}</span>
        </div>
        <div class="stat">
          <span class="stat-value stat-completed">{progressData.completed_tasks}</span>
          <span class="stat-label">{m.annotation_task_completed()}</span>
        </div>
        <div class="stat">
          <span class="stat-value stat-in-progress">{progressData.in_progress_tasks}</span>
          <span class="stat-label">{m.annotation_task_in_progress()}</span>
        </div>
        <div class="stat">
          <span class="stat-value stat-pending">{progressData.pending_tasks}</span>
          <span class="stat-label">{m.annotation_task_pending()}</span>
        </div>
        <div class="stat">
          <span class="stat-value stat-review">{progressData.review_pending_tasks}</span>
          <span class="stat-label">{m.annotation_task_review_pending()}</span>
        </div>
      </div>
      <div class="progress-bar-container">
        <div class="progress-bar" style="width: {completedPercent}%"></div>
      </div>
      <p class="progress-label">{m.annotation_task_complete_percent({ percent: completedPercent })}</p>
    </div>
  {/if}

  <!-- Filters -->
  <div class="filters">
    <div class="filter-group">
      <label for="status-filter" class="filter-label">{m.annotation_task_filter_status()}</label>
      <select
        id="status-filter"
        class="filter-select"
        value={statusFilter}
        on:change={handleStatusFilterChange}
      >
        <option value="">{m.annotation_task_filter_all()}</option>
        <option value="pending">{m.annotation_task_filter_pending()}</option>
        <option value="in_progress">{m.annotation_task_filter_in_progress()}</option>
        <option value="completed">{m.annotation_task_filter_completed()}</option>
        <option value="review_pending">{m.annotation_task_filter_review_pending()}</option>
      </select>
    </div>

    <div class="filter-group">
      <label for="sort-select" class="filter-label">{m.annotation_task_sort_by()}</label>
      <select
        id="sort-select"
        class="filter-select"
        value={sortSelectValue}
        on:change={handleSortChange}
      >
        <option value="priority_desc">{m.annotation_task_sort_priority()}</option>
        <option value="created_at_desc">{m.annotation_task_sort_created_newest()}</option>
        <option value="created_at_asc">{m.annotation_task_sort_created_oldest()}</option>
        <option value="status_asc">{m.annotation_task_sort_status()}</option>
      </select>
    </div>

    {#if batchMode && ($tasksQuery.data?.items.length ?? 0) > 0}
      <div class="batch-select-actions">
        <button class="btn-link" on:click={selectAllTasks}>{m.annotation_task_select_all()}</button>
        <span class="separator">|</span>
        <button class="btn-link" on:click={clearSelection}>{m.annotation_task_clear_selection()}</button>
      </div>
    {/if}
  </div>

  <!-- Task list -->
  {#if $tasksQuery.isLoading}
    <div class="loading">{m.annotation_task_loading_tasks()}</div>
  {:else if $tasksQuery.isError}
    <div class="error">
      {m.annotation_task_error_load({ message: $tasksQuery.error?.message ?? '' })}
    </div>
  {:else if $tasksQuery.data}
    {#if $tasksQuery.data.items.length === 0}
      <div class="empty-state">
        {#if statusFilter}
          <p>{m.annotation_task_empty_filter()}</p>
        {:else}
          <p>{m.annotation_task_empty_no_tasks()}</p>
          <p class="empty-hint">
            {m.annotation_task_empty_hint()}
          </p>
        {/if}
      </div>
    {:else}
      <div class="table-container">
        <table class="tasks-table">
          <thead>
            <tr>
              {#if batchMode}
                <th class="checkbox-col">
                  <input
                    type="checkbox"
                    aria-label={m.annotation_task_select_all_aria()}
                    checked={selectedTaskIds.length === $tasksQuery.data.items.length && $tasksQuery.data.items.length > 0}
                    on:change={(e) => {
                      if ((e.target as HTMLInputElement).checked) {
                        selectAllTasks();
                      } else {
                        clearSelection();
                      }
                    }}
                  />
                </th>
              {/if}
              <th>{m.annotation_task_col_status()}</th>
              <th>{m.annotation_task_col_clip()}</th>
              <th>{m.annotation_task_col_time_range()}</th>
              <th>{m.annotation_task_col_priority()}</th>
              <th>{m.annotation_task_col_assigned()}</th>
              <th>{m.annotation_task_col_actions()}</th>
            </tr>
          </thead>
          <tbody>
            {#each $tasksQuery.data.items as task (task.id)}
              <tr
                class="task-row"
                class:task-row--selected={batchMode && selectedTaskIds.includes(task.id)}
                on:click={() => {
                  if (batchMode) {
                    toggleTaskSelection(task.id);
                  } else {
                    navigateToTask(task);
                  }
                }}
                on:keydown={(e) => {
                  if (e.key === 'Enter') {
                    if (batchMode) {
                      toggleTaskSelection(task.id);
                    } else {
                      navigateToTask(task);
                    }
                  }
                }}
                tabindex="0"
                role="button"
                aria-label={batchMode ? m.annotation_task_batch_select_aria({ id: task.id }) : m.annotation_task_open_aria({ id: task.id })}
                aria-pressed={batchMode ? selectedTaskIds.includes(task.id) : undefined}
              >
                {#if batchMode}
                  <td class="checkbox-col" on:click|stopPropagation>
                    <input
                      type="checkbox"
                      checked={selectedTaskIds.includes(task.id)}
                      aria-label={m.annotation_task_select_aria()}
                      on:change={() => toggleTaskSelection(task.id)}
                    />
                  </td>
                {/if}
                <td>
                  <span class={getStatusBadgeClass(task.status)}>
                    {getStatusLabel(task.status)}
                  </span>
                </td>
                <td class="clip-cell">
                  <span class="clip-id" title={task.clip_id}>
                    {task.clip_id.slice(0, 8)}&hellip;
                  </span>
                </td>
                <td class="time-cell">
                  &mdash;
                </td>
                <td class="priority-cell">
                  <span class="priority-value">{task.priority}</span>
                </td>
                <td class="assigned-cell">
                  {#if task.assigned_to_id}
                    <span class="assigned-id" title={task.assigned_to_id}>
                      {task.assigned_to_id.slice(0, 8)}&hellip;
                    </span>
                  {:else}
                    <span class="unassigned">{m.annotation_task_unassigned()}</span>
                  {/if}
                </td>
                <td class="actions-cell">
                  {#if !batchMode}
                    <button
                      class="btn-action"
                      on:click|stopPropagation={() => navigateToTask(task)}
                    >
                      {m.annotation_task_open_button()}
                    </button>
                  {/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      {#if $tasksQuery.data.pages > 1}
        <div class="pagination">
          <button
            class="page-btn"
            on:click={() => (currentPage = Math.max(1, currentPage - 1))}
            disabled={currentPage === 1}
          >
            {m.annotation_task_previous()}
          </button>

          <span class="page-info">
            {m.annotation_task_page_info({ page: currentPage, total: $tasksQuery.data.pages })}
          </span>

          <button
            class="page-btn"
            on:click={() => (currentPage = Math.min($tasksQuery.data.pages, currentPage + 1))}
            disabled={currentPage === $tasksQuery.data.pages}
          >
            {m.annotation_task_next()}
          </button>
        </div>
      {/if}

      <div class="pagination-info">
        {m.annotation_task_showing({ showing: $tasksQuery.data.items.length, total: $tasksQuery.data.total })}
      </div>
    {/if}
  {/if}
</div>

<!-- Batch mode floating action bar -->
{#if batchMode}
  <div class="batch-action-bar" role="toolbar" aria-label="Batch actions">
    <span class="batch-count">
      {selectedTaskIds.length !== 1
        ? m.annotation_task_batch_count_plural({ count: selectedTaskIds.length })
        : m.annotation_task_batch_count_singular({ count: selectedTaskIds.length })}
    </span>
    <div class="batch-buttons">
      <button
        class="btn-primary"
        on:click={openBatchTagDialog}
        disabled={selectedTaskIds.length === 0}
      >
        {m.annotation_task_apply_tag()}
      </button>
      <button class="btn-secondary" on:click={toggleBatchMode}>
        {m.annotation_task_batch_cancel()}
      </button>
    </div>
  </div>
{/if}

<!-- Batch tag dialog -->
{#if showBatchTagDialog}
  <!-- svelte-ignore a11y-click-events-have-key-events -->
  <!-- svelte-ignore a11y-no-static-element-interactions -->
  <div class="modal-overlay" on:click={closeBatchTagDialog}>
    <!-- svelte-ignore a11y-click-events-have-key-events -->
    <!-- svelte-ignore a11y-no-static-element-interactions -->
    <!-- svelte-ignore a11y-interactive-supports-focus -->
    <div class="modal" on:click|stopPropagation role="dialog" aria-modal="true" aria-labelledby="batch-tag-title" tabindex="-1">
      <div class="modal-header">
        <h3 id="batch-tag-title">
          {selectedTaskIds.length !== 1
            ? m.annotation_task_batch_tag_title_plural({ count: selectedTaskIds.length })
            : m.annotation_task_batch_tag_title({ count: selectedTaskIds.length })}
        </h3>
        <button
          type="button"
          class="close-btn"
          on:click={closeBatchTagDialog}
          aria-label={m.annotation_task_batch_close_aria()}
        >
          &times;
        </button>
      </div>

      <div class="modal-body">
        {#if batchTagError}
          <div class="alert alert-error" style="margin-bottom: 1rem;">
            {batchTagError}
          </div>
        {/if}

        <label class="field-label" for="batch-tag-select">{m.annotation_task_batch_select_tag()}</label>
        {#if availableTags.length === 0}
          <p class="no-tags-hint">{m.annotation_task_batch_no_tags()}</p>
        {:else}
          <select
            id="batch-tag-select"
            class="filter-select"
            bind:value={batchTagId}
          >
            <option value="">{m.annotation_task_batch_choose_tag()}</option>
            {#each availableTags as tag}
              <option value={tag.id}>{tag.name} ({tag.category})</option>
            {/each}
          </select>
        {/if}
      </div>

      <div class="modal-footer">
        <button
          type="button"
          class="btn-secondary"
          on:click={closeBatchTagDialog}
          disabled={isBatchTagPending}
        >
          {m.annotation_task_batch_cancel()}
        </button>
        <button
          type="button"
          class="btn-primary"
          on:click={executeBatchTag}
          disabled={isBatchTagPending || !batchTagId || availableTags.length === 0}
        >
          {isBatchTagPending ? m.annotation_task_applying() : m.annotation_task_apply_tag_button()}
        </button>
      </div>
    </div>
  </div>
{/if}

<!-- Export dialog -->
<ExportDialog
  {projectId}
  {annotationProjectId}
  annotationProjectName={$projectQuery.data?.name ?? ''}
  isOpen={showExportDialog}
  onClose={() => (showExportDialog = false)}
/>

<style>
  .tasks-page {
    max-width: 1200px;
    margin: 0 auto;
    padding: 2rem;
  }

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

  /* Header */
  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 1.5rem;
  }

  .header-info h1 {
    margin: 0 0 0.25rem 0;
    font-size: 1.5rem;
    font-weight: 600;
    color: #111827;
  }

  .header-info .description {
    margin: 0;
    font-size: 0.875rem;
    color: #6b7280;
  }

  .placeholder-text {
    color: #9ca3af;
  }

  .header-actions {
    display: flex;
    gap: 0.75rem;
    align-items: center;
    flex-shrink: 0;
    flex-wrap: wrap;
  }

  /* Buttons */
  .btn-primary {
    padding: 0.625rem 1rem;
    background: #3b82f6;
    color: white;
    border: none;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    font-weight: 500;
    cursor: pointer;
    white-space: nowrap;
    text-decoration: none;
    display: inline-flex;
    align-items: center;
  }

  .btn-primary:hover:not(:disabled) {
    background: #2563eb;
  }

  .btn-primary:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .btn-secondary {
    padding: 0.625rem 1rem;
    background: white;
    color: #374151;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    font-weight: 500;
    cursor: pointer;
    white-space: nowrap;
    text-decoration: none;
    display: inline-flex;
    align-items: center;
  }

  .btn-secondary:hover:not(:disabled) {
    background: #f9fafb;
  }

  .btn-secondary:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .btn-active {
    background: #eff6ff;
    border-color: #93c5fd;
    color: #1d4ed8;
  }

  .btn-action {
    padding: 0.375rem 0.75rem;
    background: white;
    color: #3b82f6;
    border: 1px solid #bfdbfe;
    border-radius: 0.375rem;
    font-size: 0.8125rem;
    font-weight: 500;
    cursor: pointer;
  }

  .btn-action:hover {
    background: #eff6ff;
  }

  .btn-link {
    background: none;
    border: none;
    color: #3b82f6;
    font-size: 0.875rem;
    cursor: pointer;
    padding: 0;
    text-decoration: underline;
  }

  .btn-link:hover {
    color: #2563eb;
  }

  /* Alerts */
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

  .alert-info {
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    color: #2563eb;
  }

  /* Progress card */
  .progress-card {
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 0.5rem;
    padding: 1.25rem 1.5rem;
    margin-bottom: 1.5rem;
  }

  .progress-title {
    margin: 0 0 1rem 0;
    font-size: 0.9375rem;
    font-weight: 600;
    color: #374151;
  }

  .progress-stats {
    display: flex;
    gap: 2rem;
    margin-bottom: 1rem;
    flex-wrap: wrap;
  }

  .stat {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.25rem;
  }

  .stat-value {
    font-size: 1.5rem;
    font-weight: 700;
    color: #111827;
    line-height: 1;
  }

  .stat-completed {
    color: #16a34a;
  }

  .stat-in-progress {
    color: #2563eb;
  }

  .stat-pending {
    color: #6b7280;
  }

  .stat-review {
    color: #d97706;
  }

  .stat-label {
    font-size: 0.75rem;
    color: #9ca3af;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .progress-bar-container {
    height: 0.5rem;
    background: #e5e7eb;
    border-radius: 9999px;
    overflow: hidden;
    margin-bottom: 0.5rem;
  }

  .progress-bar {
    height: 100%;
    background: #22c55e;
    border-radius: 9999px;
    transition: width 0.3s ease;
  }

  .progress-label {
    margin: 0;
    font-size: 0.8125rem;
    color: #6b7280;
    text-align: right;
  }

  /* Filters */
  .filters {
    display: flex;
    gap: 1rem;
    margin-bottom: 1rem;
    flex-wrap: wrap;
    align-items: flex-end;
  }

  .filter-group {
    display: flex;
    flex-direction: column;
    gap: 0.375rem;
  }

  .filter-label {
    font-size: 0.75rem;
    font-weight: 500;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .filter-select {
    padding: 0.5rem 0.75rem;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    color: #374151;
    background: white;
    cursor: pointer;
    min-width: 160px;
  }

  .filter-select:focus {
    outline: none;
    border-color: #3b82f6;
    box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
  }

  .batch-select-actions {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding-bottom: 0.125rem;
  }

  .separator {
    color: #d1d5db;
    font-size: 0.875rem;
  }

  /* Loading / Error */
  .loading,
  .error {
    padding: 2rem;
    text-align: center;
    border-radius: 0.5rem;
  }

  .loading {
    background: #f3f4f6;
    color: #6b7280;
  }

  .error {
    background: #fef2f2;
    color: #dc2626;
  }

  /* Empty state */
  .empty-state {
    padding: 3rem 2rem;
    text-align: center;
    border: 2px dashed #e5e7eb;
    border-radius: 0.5rem;
    color: #6b7280;
  }

  .empty-state p {
    margin: 0 0 0.5rem 0;
    font-size: 0.9375rem;
  }

  .empty-hint {
    font-size: 0.875rem;
    color: #9ca3af;
  }

  /* Table */
  .table-container {
    overflow-x: auto;
    border: 1px solid #e5e7eb;
    border-radius: 0.5rem;
  }

  .tasks-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.875rem;
  }

  .tasks-table thead {
    background: #f9fafb;
    border-bottom: 1px solid #e5e7eb;
  }

  .tasks-table th {
    padding: 0.75rem 1rem;
    text-align: left;
    font-size: 0.75rem;
    font-weight: 600;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    white-space: nowrap;
  }

  .tasks-table td {
    padding: 0.875rem 1rem;
    border-bottom: 1px solid #f3f4f6;
    color: #374151;
    vertical-align: middle;
  }

  .task-row {
    cursor: pointer;
    transition: background-color 0.1s;
  }

  .task-row:hover {
    background: #f9fafb;
  }

  .task-row:focus {
    outline: none;
    background: #eff6ff;
  }

  .task-row--selected {
    background: #eff6ff;
  }

  .task-row--selected:hover {
    background: #dbeafe;
  }

  .task-row:last-child td {
    border-bottom: none;
  }

  .checkbox-col {
    width: 2.5rem;
    text-align: center;
  }

  /* Status badges */
  .badge {
    display: inline-block;
    padding: 0.25rem 0.625rem;
    border-radius: 9999px;
    font-size: 0.75rem;
    font-weight: 500;
    white-space: nowrap;
  }

  .badge-pending {
    background: #f3f4f6;
    color: #4b5563;
  }

  .badge-in-progress {
    background: #dbeafe;
    color: #1d4ed8;
  }

  .badge-completed {
    background: #dcfce7;
    color: #15803d;
  }

  .badge-review-pending {
    background: #fef9c3;
    color: #a16207;
  }

  /* Table cell specifics */
  .clip-cell {
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 0.8125rem;
    color: #6b7280;
  }

  .clip-id {
    cursor: default;
  }

  .time-cell {
    color: #9ca3af;
    font-size: 0.8125rem;
  }

  .priority-cell {
    text-align: center;
  }

  .priority-value {
    font-weight: 600;
    color: #374151;
  }

  .assigned-cell {
    font-size: 0.8125rem;
  }

  .assigned-id {
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    color: #6b7280;
    cursor: default;
  }

  .unassigned {
    color: #d1d5db;
    font-style: italic;
  }

  .actions-cell {
    white-space: nowrap;
  }

  /* Pagination */
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
    color: #6b7280;
  }

  /* Batch action floating bar */
  .batch-action-bar {
    position: fixed;
    bottom: 1.5rem;
    left: 50%;
    transform: translateX(-50%);
    background: #1f2937;
    color: white;
    border-radius: 0.75rem;
    padding: 0.875rem 1.5rem;
    display: flex;
    align-items: center;
    gap: 1.5rem;
    box-shadow: 0 10px 25px rgba(0, 0, 0, 0.3);
    z-index: 40;
    min-width: 320px;
  }

  .batch-count {
    font-size: 0.875rem;
    font-weight: 500;
    flex: 1;
  }

  .batch-buttons {
    display: flex;
    gap: 0.75rem;
  }

  .batch-action-bar .btn-primary {
    background: #3b82f6;
    padding: 0.5rem 1rem;
  }

  .batch-action-bar .btn-primary:disabled {
    opacity: 0.4;
  }

  .batch-action-bar .btn-secondary {
    background: transparent;
    color: #d1d5db;
    border-color: #4b5563;
    padding: 0.5rem 1rem;
  }

  .batch-action-bar .btn-secondary:hover {
    background: #374151;
    color: white;
  }

  /* Modal */
  .modal-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 50;
    padding: 1rem;
  }

  .modal {
    background: white;
    border-radius: 0.5rem;
    max-width: 440px;
    width: 100%;
    box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
  }

  .modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1rem 1.5rem;
    border-bottom: 1px solid #e5e7eb;
  }

  .modal-header h3 {
    margin: 0;
    font-size: 1rem;
    font-weight: 600;
    color: #111827;
  }

  .close-btn {
    background: none;
    border: none;
    padding: 0.25rem 0.5rem;
    cursor: pointer;
    color: #9ca3af;
    font-size: 1.25rem;
    line-height: 1;
    border-radius: 0.25rem;
  }

  .close-btn:hover {
    color: #4b5563;
    background: #f3f4f6;
  }

  .modal-body {
    padding: 1.5rem;
  }

  .field-label {
    display: block;
    font-size: 0.875rem;
    font-weight: 500;
    color: #374151;
    margin-bottom: 0.5rem;
  }

  .no-tags-hint {
    margin: 0;
    font-size: 0.875rem;
    color: #9ca3af;
    font-style: italic;
  }

  .modal-footer {
    display: flex;
    justify-content: flex-end;
    gap: 0.75rem;
    padding: 1rem 1.5rem;
    border-top: 1px solid #e5e7eb;
    background: #f9fafb;
    border-radius: 0 0 0.5rem 0.5rem;
  }
</style>
