<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import * as m from '$lib/paraglide/messages';

  export let projectId: string;
  export let annotationProjectId: string;
  // currentTaskId is exposed for parent components to identify the active task
  export let currentTaskId: string;
  $: void currentTaskId; // suppress unused export warning
  export let totalTasks: number = 0;
  export let completedTasks: number = 0;
  export let hasUnsavedChanges: boolean = false;
  export let onComplete: () => void;
  export let onNavigateNext: () => void;
  export let onNavigatePrevious: (() => void) | null = null;

  $: backHref = `/projects/${projectId}/annotations/${annotationProjectId}`;
  $: progressPercent = totalTasks > 0 ? (completedTasks / totalTasks) * 100 : 0;

  function handleKeyDown(event: KeyboardEvent) {
    // Ctrl+Enter (or Cmd+Enter on Mac) to complete task
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
      event.preventDefault();
      onComplete();
    }
  }

  onMount(() => {
    window.addEventListener('keydown', handleKeyDown);
  });

  onDestroy(() => {
    window.removeEventListener('keydown', handleKeyDown);
  });
</script>

<nav class="task-navigator" aria-label="Task navigation">
  <!-- Left section: back link -->
  <div class="nav-left">
    <a href={backHref} class="back-link" title={m.annotation_navigator_back_title()}>
      <svg viewBox="0 0 20 20" fill="currentColor" class="back-icon">
        <path fill-rule="evenodd" clip-rule="evenodd"
          d="M17 10a.75.75 0 01-.75.75H5.612l4.158 3.96a.75.75 0 11-1.04 1.08l-5.5-5.25a.75.75 0 010-1.08l5.5-5.25a.75.75 0 111.04 1.08L5.612 9.25H16.25A.75.75 0 0117 10z"/>
      </svg>
      <span class="back-label">{m.annotation_navigator_back()}</span>
    </a>
  </div>

  <!-- Center section: progress -->
  <div class="nav-center">
    <div class="progress-info">
      <span class="progress-text">
        {m.annotation_navigator_completed({ completed: completedTasks, total: totalTasks })}
      </span>
      {#if hasUnsavedChanges}
        <span class="unsaved-indicator" title={m.annotation_navigator_unsaved_title()}>
          <span class="unsaved-dot" aria-hidden="true"></span>
          {m.annotation_navigator_unsaved()}
        </span>
      {/if}
    </div>
    <div class="progress-bar-track" role="progressbar" aria-valuenow={progressPercent} aria-valuemin={0} aria-valuemax={100}>
      <div class="progress-bar-fill" style="width: {progressPercent}%;"></div>
    </div>
  </div>

  <!-- Right section: navigation controls -->
  <div class="nav-right">
    <!-- Previous button -->
    <button
      class="nav-arrow-btn"
      disabled={!onNavigatePrevious}
      title={m.annotation_navigator_previous_title()}
      aria-label={m.annotation_navigator_previous_aria()}
      on:click={() => onNavigatePrevious && onNavigatePrevious()}
    >
      <svg viewBox="0 0 20 20" fill="currentColor" class="arrow-icon">
        <path fill-rule="evenodd" clip-rule="evenodd"
          d="M12.79 5.23a.75.75 0 01-.02 1.06L8.832 10l3.938 3.71a.75.75 0 11-1.04 1.08l-4.5-4.25a.75.75 0 010-1.08l4.5-4.25a.75.75 0 011.06.02z"/>
      </svg>
    </button>

    <!-- Next button -->
    <button
      class="nav-arrow-btn"
      title={m.annotation_navigator_next_title()}
      aria-label={m.annotation_navigator_next_aria()}
      on:click={onNavigateNext}
    >
      <svg viewBox="0 0 20 20" fill="currentColor" class="arrow-icon">
        <path fill-rule="evenodd" clip-rule="evenodd"
          d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z"/>
      </svg>
    </button>

    <!-- Complete & Next button -->
    <button
      class="complete-btn"
      title={m.annotation_navigator_complete_title()}
      aria-label={m.annotation_navigator_complete_aria()}
      on:click={onComplete}
    >
      <svg viewBox="0 0 20 20" fill="currentColor" class="complete-icon">
        <path fill-rule="evenodd" clip-rule="evenodd"
          d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z"/>
      </svg>
      {m.annotation_navigator_complete_button()}
      <kbd class="shortcut-hint" aria-hidden="true">Ctrl+Enter</kbd>
    </button>
  </div>
</nav>

<style>
  .task-navigator {
    display: flex;
    align-items: center;
    gap: 1rem;
    padding: 0 1rem;
    height: 3.25rem;
    background-color: #fff;
    border-bottom: 1px solid #e5e7eb;
    flex-shrink: 0;
  }

  /* ---- Left ---- */
  .nav-left {
    flex-shrink: 0;
  }

  .back-link {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    text-decoration: none;
    color: #6b7280;
    font-size: 0.875rem;
    font-weight: 500;
    padding: 0.25rem 0.5rem;
    border-radius: 0.375rem;
    transition: background-color 0.1s ease, color 0.1s ease;
  }

  .back-link:hover {
    background-color: #f3f4f6;
    color: #111827;
  }

  .back-icon {
    width: 1.125rem;
    height: 1.125rem;
  }

  .back-label {
    white-space: nowrap;
  }

  /* ---- Center ---- */
  .nav-center {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .progress-info {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }

  .progress-text {
    font-size: 0.8125rem;
    color: #374151;
    font-weight: 500;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }

  .unsaved-indicator {
    display: flex;
    align-items: center;
    gap: 0.25rem;
    font-size: 0.75rem;
    color: #92400e;
    background-color: #fef3c7;
    padding: 0.125rem 0.5rem;
    border-radius: 9999px;
    border: 1px solid #fde68a;
    white-space: nowrap;
  }

  .unsaved-dot {
    display: inline-block;
    width: 0.5rem;
    height: 0.5rem;
    border-radius: 9999px;
    background-color: #f59e0b;
    flex-shrink: 0;
  }

  /* Progress bar */
  .progress-bar-track {
    width: 100%;
    height: 0.3125rem;
    background-color: #e5e7eb;
    border-radius: 9999px;
    overflow: hidden;
  }

  .progress-bar-fill {
    height: 100%;
    background-color: #22c55e;
    border-radius: 9999px;
    transition: width 0.3s ease;
  }

  /* ---- Right ---- */
  .nav-right {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    flex-shrink: 0;
  }

  /* Arrow nav buttons */
  .nav-arrow-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 2rem;
    height: 2rem;
    border: 1px solid #e5e7eb;
    background: #fff;
    border-radius: 0.375rem;
    cursor: pointer;
    color: #374151;
    padding: 0;
    transition: background-color 0.1s ease, border-color 0.1s ease, color 0.1s ease;
  }

  .nav-arrow-btn:hover:not(:disabled) {
    background-color: #f3f4f6;
    border-color: #d1d5db;
    color: #111827;
  }

  .nav-arrow-btn:disabled {
    opacity: 0.35;
    cursor: not-allowed;
  }

  .arrow-icon {
    width: 1.125rem;
    height: 1.125rem;
  }

  /* Complete button */
  .complete-btn {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    padding: 0.4375rem 0.875rem;
    background-color: #22c55e;
    color: #fff;
    border: none;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    font-weight: 600;
    cursor: pointer;
    white-space: nowrap;
    transition: background-color 0.1s ease;
  }

  .complete-btn:hover {
    background-color: #16a34a;
  }

  .complete-btn:active {
    background-color: #15803d;
  }

  .complete-icon {
    width: 1rem;
    height: 1rem;
    flex-shrink: 0;
  }

  .shortcut-hint {
    font-size: 0.6875rem;
    font-family: ui-monospace, monospace;
    background-color: rgba(255, 255, 255, 0.25);
    padding: 0.0625rem 0.3125rem;
    border-radius: 0.25rem;
    margin-left: 0.125rem;
    letter-spacing: 0;
    font-weight: 500;
    border: 1px solid rgba(255, 255, 255, 0.3);
  }
</style>
