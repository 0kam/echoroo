<script lang="ts">
  import type { AnnotationProjectDetail } from '$lib/types/annotation';

  export let projects: AnnotationProjectDetail[] = [];
  export let onSelect: (project: AnnotationProjectDetail) => void = () => {};
  export let onDelete: (project: AnnotationProjectDetail) => void = () => {};

  function formatDate(dateStr: string): string {
    return new Date(dateStr).toLocaleDateString();
  }

  function getProgressPercent(project: AnnotationProjectDetail): number {
    const total = project.progress.total_tasks;
    if (total === 0) return 0;
    return Math.round((project.progress.completed_tasks / total) * 100);
  }

  function getVisibilityClass(visibility: string): string {
    return visibility === 'public' ? 'badge-public' : 'badge-private';
  }

  function truncateText(text: string, maxLength: number): string {
    if (text.length <= maxLength) return text;
    return text.slice(0, maxLength) + '...';
  }
</script>

<div class="annotation-project-list">
  {#if projects.length === 0}
    <div class="empty-state">
      <p>No annotation projects found. Create your first annotation project to get started.</p>
    </div>
  {:else}
    <ul>
      {#each projects as project (project.id)}
        <!-- svelte-ignore a11y_no_noninteractive_element_to_interactive_role -->
        <li
          class="project-item"
          role="button"
          tabindex="0"
          on:click={() => onSelect(project)}
          on:keydown={(e) => e.key === 'Enter' && onSelect(project)}
        >
          <div class="project-info">
            <div class="project-header">
              <h3>{project.name}</h3>
              <span class="visibility-badge {getVisibilityClass(project.visibility)}">
                {project.visibility}
              </span>
            </div>

            {#if project.description}
              <p class="description">{truncateText(project.description, 120)}</p>
            {/if}

            <!-- Progress bar -->
            <div class="progress-section">
              <div class="progress-labels">
                <span class="progress-text">
                  {project.progress.completed_tasks} / {project.progress.total_tasks} tasks completed
                </span>
                <span class="progress-percent">{getProgressPercent(project)}%</span>
              </div>
              <div class="progress-bar">
                <div
                  class="progress-fill"
                  style="width: {getProgressPercent(project)}%"
                ></div>
              </div>
              {#if project.progress.total_tasks > 0}
                <div class="progress-details">
                  {#if project.progress.in_progress_tasks > 0}
                    <span class="detail-item detail-in-progress">
                      {project.progress.in_progress_tasks} in progress
                    </span>
                  {/if}
                  {#if project.progress.review_pending_tasks > 0}
                    <span class="detail-item detail-review">
                      {project.progress.review_pending_tasks} pending review
                    </span>
                  {/if}
                  {#if project.progress.pending_tasks > 0}
                    <span class="detail-item detail-pending">
                      {project.progress.pending_tasks} pending
                    </span>
                  {/if}
                </div>
              {/if}
            </div>

            <div class="project-meta">
              {#if project.datasets.length > 0}
                <span class="meta-item">
                  <span class="meta-label">Datasets:</span>
                  {project.datasets.map((d) => d.name).join(', ')}
                </span>
              {/if}
              <span class="meta-item">
                <span class="meta-label">Created:</span>
                {formatDate(project.created_at)}
              </span>
            </div>
          </div>

          <div class="project-actions">
            <button
              class="delete-btn"
              on:click|stopPropagation={() => onDelete(project)}
              aria-label="Delete annotation project"
            >
              Delete
            </button>
          </div>
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .annotation-project-list {
    width: 100%;
  }

  .empty-state {
    padding: 2rem;
    text-align: center;
    color: #6b7280;
    background: #f9fafb;
    border-radius: 0.5rem;
  }

  ul {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .project-item {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    padding: 1.25rem;
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 0.5rem;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .project-item:hover {
    background: #f9fafb;
    border-color: #d1d5db;
  }

  .project-info {
    flex: 1;
  }

  .project-header {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 0.5rem;
  }

  .project-info h3 {
    margin: 0;
    font-size: 1rem;
    font-weight: 600;
    color: #111827;
  }

  .visibility-badge {
    padding: 0.25rem 0.625rem;
    border-radius: 0.25rem;
    font-size: 0.75rem;
    font-weight: 500;
    text-transform: capitalize;
  }

  .badge-private {
    background: #f3f4f6;
    color: #374151;
  }

  .badge-public {
    background: #dbeafe;
    color: #1e40af;
  }

  .description {
    margin: 0 0 0.75rem 0;
    font-size: 0.875rem;
    color: #6b7280;
    line-height: 1.5;
  }

  .progress-section {
    margin-bottom: 0.75rem;
  }

  .progress-labels {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.375rem;
  }

  .progress-text {
    font-size: 0.75rem;
    color: #6b7280;
  }

  .progress-percent {
    font-size: 0.75rem;
    font-weight: 600;
    color: #374151;
  }

  .progress-bar {
    height: 6px;
    background: #e5e7eb;
    border-radius: 3px;
    overflow: hidden;
    margin-bottom: 0.375rem;
  }

  .progress-fill {
    height: 100%;
    background: #3b82f6;
    border-radius: 3px;
    transition: width 0.3s ease;
  }

  .progress-details {
    display: flex;
    gap: 0.75rem;
    flex-wrap: wrap;
  }

  .detail-item {
    font-size: 0.6875rem;
    padding: 0.125rem 0.5rem;
    border-radius: 0.25rem;
  }

  .detail-in-progress {
    background: #dbeafe;
    color: #1e40af;
  }

  .detail-review {
    background: #fef3c7;
    color: #92400e;
  }

  .detail-pending {
    background: #f3f4f6;
    color: #6b7280;
  }

  .project-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 1rem;
  }

  .meta-item {
    font-size: 0.75rem;
    color: #6b7280;
  }

  .meta-label {
    font-weight: 500;
    margin-right: 0.25rem;
  }

  .project-actions {
    margin-left: 1rem;
    flex-shrink: 0;
  }

  .delete-btn {
    padding: 0.375rem 0.75rem;
    font-size: 0.75rem;
    color: #dc2626;
    background: white;
    border: 1px solid #fecaca;
    border-radius: 0.375rem;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .delete-btn:hover {
    background: #fef2f2;
    border-color: #f87171;
  }
</style>
