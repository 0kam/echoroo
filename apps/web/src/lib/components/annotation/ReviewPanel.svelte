<script lang="ts">
  import type { Note } from '$lib/types/annotation';
  import { getLocale } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';

  export let clipAnnotationId: string;
  export let reviewStatus: string;  // 'unreviewed' | 'approved' | 'rejected'
  export let reviewedById: string | null = null;
  export let reviewedAt: string | null = null;
  export let notes: Note[] = [];
  export let onApprove: (comment?: string) => void;
  export let onReject: (comment: string) => void;

  // Suppress unused variable warning - clipAnnotationId is exposed as a prop
  // for parent components that may need it for API calls or context.
  $: void clipAnnotationId;

  let comment = '';
  let rejectError = '';

  $: isApproved = reviewStatus === 'approved';
  $: isRejected = reviewStatus === 'rejected';
  $: isReviewed = isApproved || isRejected;

  $: reviewNotes = notes.filter((n) => n.is_review);

  function handleApprove() {
    rejectError = '';
    onApprove(comment.trim() || undefined);
    comment = '';
  }

  function handleReject() {
    if (!comment.trim()) {
      rejectError = m.annotation_review_panel_reject_error();
      return;
    }
    rejectError = '';
    onReject(comment.trim());
    comment = '';
  }

  function formatDate(isoString: string): string {
    const date = new Date(isoString);
    return date.toLocaleString(getLocale(), {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  function getStatusLabel(status: string): string {
    switch (status) {
      case 'approved':
        return m.annotation_review_panel_status_approved();
      case 'rejected':
        return m.annotation_review_panel_status_rejected();
      default:
        return m.annotation_review_panel_status_unreviewed();
    }
  }

  function truncateId(id: string): string {
    return id.length > 8 ? id.slice(0, 8) + '...' : id;
  }
</script>

<div class="panel">
  <!-- Status badge row -->
  <div class="status-row">
    <span
      class="status-badge status-badge--{reviewStatus}"
      aria-label="Review status: {getStatusLabel(reviewStatus)}"
    >
      {#if reviewStatus === 'approved'}
        <svg
          class="status-icon"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          aria-hidden="true"
        >
          <path stroke-linecap="round" stroke-linejoin="round" d="M3 8l3.5 3.5L13 4.5" />
        </svg>
      {:else if reviewStatus === 'rejected'}
        <svg
          class="status-icon"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          aria-hidden="true"
        >
          <path stroke-linecap="round" d="M4 4l8 8M12 4l-8 8" />
        </svg>
      {:else}
        <svg
          class="status-icon"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          aria-hidden="true"
        >
          <circle cx="8" cy="8" r="5.5" />
          <path stroke-linecap="round" d="M8 5.5v3l1.5 1.5" />
        </svg>
      {/if}
      {getStatusLabel(reviewStatus)}
    </span>

    <!-- Reviewer info when reviewed -->
    {#if isReviewed && (reviewedById || reviewedAt)}
      <span class="reviewer-info">
        {#if reviewedById}
          <span class="reviewer-id" title="Reviewer ID: {reviewedById}">
            by {truncateId(reviewedById)}
          </span>
        {/if}
        {#if reviewedAt}
          <time class="reviewer-time" datetime={reviewedAt}>
            {formatDate(reviewedAt)}
          </time>
        {/if}
      </span>
    {/if}
  </div>

  <!-- Comment textarea -->
  <div class="comment-section" aria-label="Review comment">
    <label class="comment-label" for="review-comment">
      {reviewStatus !== 'approved' ? m.annotation_review_panel_comment_label_required() : m.annotation_review_panel_comment_label_optional()}
    </label>
    <textarea
      id="review-comment"
      class="comment-textarea"
      class:comment-textarea--error={!!rejectError}
      placeholder={m.annotation_review_panel_comment_placeholder()}
      bind:value={comment}
      disabled={isApproved}
      rows={3}
      aria-describedby={rejectError ? 'reject-error' : undefined}
    ></textarea>
    {#if rejectError}
      <p id="reject-error" class="error-message" role="alert">{rejectError}</p>
    {/if}
  </div>

  <!-- Action buttons -->
  <div class="action-row">
    <button
      type="button"
      class="btn btn--approve"
      on:click={handleApprove}
      disabled={isApproved}
      aria-label={isApproved ? m.annotation_review_panel_already_approved_aria() : m.annotation_review_panel_approve_aria()}
    >
      <svg
        class="btn-icon"
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        aria-hidden="true"
      >
        <path stroke-linecap="round" stroke-linejoin="round" d="M3 8l3.5 3.5L13 4.5" />
      </svg>
      {isApproved ? m.annotation_review_panel_approved_button() : m.annotation_review_panel_approve_button()}
    </button>

    <button
      type="button"
      class="btn btn--reject"
      on:click={handleReject}
      disabled={isApproved}
      aria-label={m.annotation_review_panel_reject_aria()}
    >
      <svg
        class="btn-icon"
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        aria-hidden="true"
      >
        <path stroke-linecap="round" d="M4 4l8 8M12 4l-8 8" />
      </svg>
      {isRejected ? m.annotation_review_panel_rejected_button() : m.annotation_review_panel_reject_button()}
    </button>
  </div>

  {#if isApproved}
    <p class="approved-notice" role="status">
      {m.annotation_review_panel_approved_notice()}
    </p>
  {/if}

  <!-- Review notes history -->
  {#if reviewNotes.length > 0}
    <div class="divider" role="separator"></div>
    <section aria-labelledby="review-history-heading">
      <h4 class="section-title" id="review-history-heading">{m.annotation_review_panel_history_title()}</h4>
      <ul class="notes-list" aria-label={m.annotation_review_panel_history_title()}>
        {#each reviewNotes as note (note.id)}
          <li class="note-item">
            <div class="note-meta">
              <span class="note-author">{m.annotation_review_panel_reviewer()}</span>
              <time class="note-time" datetime={note.created_at}>
                {formatDate(note.created_at)}
              </time>
            </div>
            <p class="note-content">{note.content}</p>
          </li>
        {/each}
      </ul>
    </section>
  {/if}
</div>

<style>
  .panel {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    padding: 0.75rem;
    font-size: 0.8125rem;
    color: #111827;
  }

  /* ---- Status badge ---- */
  .status-row {
    display: flex;
    align-items: center;
    gap: 0.625rem;
    flex-wrap: wrap;
  }

  .status-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    padding: 0.25rem 0.75rem;
    border-radius: 9999px;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.025em;
  }

  .status-badge--unreviewed {
    background: #f3f4f6;
    color: #6b7280;
    border: 1px solid #d1d5db;
  }

  .status-badge--approved {
    background: #f0fdf4;
    color: #15803d;
    border: 1px solid #bbf7d0;
  }

  .status-badge--rejected {
    background: #fef2f2;
    color: #dc2626;
    border: 1px solid #fecaca;
  }

  .status-icon {
    width: 0.875rem;
    height: 0.875rem;
    flex-shrink: 0;
  }

  /* ---- Reviewer info ---- */
  .reviewer-info {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    font-size: 0.6875rem;
    color: #9ca3af;
  }

  .reviewer-id {
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    color: #6b7280;
    font-size: 0.6875rem;
    cursor: default;
  }

  .reviewer-time {
    color: #9ca3af;
    font-size: 0.6875rem;
  }

  /* ---- Comment textarea ---- */
  .comment-section {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .comment-label {
    font-size: 0.75rem;
    font-weight: 500;
    color: #374151;
  }

  .comment-textarea {
    width: 100%;
    padding: 0.5rem;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    font-size: 0.8125rem;
    font-family: inherit;
    resize: vertical;
    min-height: 4rem;
    outline: none;
    box-sizing: border-box;
    color: #111827;
    background: #fff;
    line-height: 1.45;
    transition: border-color 0.1s ease, box-shadow 0.1s ease;
  }

  .comment-textarea:focus {
    border-color: #3b82f6;
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
  }

  .comment-textarea--error {
    border-color: #ef4444;
  }

  .comment-textarea--error:focus {
    border-color: #ef4444;
    box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.1);
  }

  .comment-textarea:disabled {
    background: #f9fafb;
    color: #9ca3af;
    cursor: not-allowed;
  }

  .comment-textarea::placeholder {
    color: #9ca3af;
  }

  .error-message {
    margin: 0;
    font-size: 0.75rem;
    color: #dc2626;
  }

  /* ---- Action buttons ---- */
  .action-row {
    display: flex;
    gap: 0.5rem;
  }

  .btn {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    padding: 0.5rem 1rem;
    border: none;
    border-radius: 0.375rem;
    font-size: 0.8125rem;
    font-weight: 500;
    font-family: inherit;
    cursor: pointer;
    transition: background 0.1s ease, opacity 0.1s ease;
    flex: 1;
    justify-content: center;
  }

  .btn:focus-visible {
    outline: 2px solid #3b82f6;
    outline-offset: 2px;
  }

  .btn:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  .btn-icon {
    width: 0.875rem;
    height: 0.875rem;
    flex-shrink: 0;
  }

  .btn--approve {
    background: #16a34a;
    color: #fff;
  }

  .btn--approve:hover:not(:disabled) {
    background: #15803d;
  }

  .btn--reject {
    background: #dc2626;
    color: #fff;
  }

  .btn--reject:hover:not(:disabled) {
    background: #b91c1c;
  }

  /* ---- Approved notice ---- */
  .approved-notice {
    margin: 0;
    padding: 0.5rem 0.625rem;
    font-size: 0.75rem;
    color: #15803d;
    background: #f0fdf4;
    border: 1px solid #bbf7d0;
    border-radius: 0.375rem;
  }

  /* ---- Divider ---- */
  .divider {
    height: 1px;
    background: #e5e7eb;
    margin: 0 -0.75rem;
  }

  /* ---- Section title ---- */
  .section-title {
    font-size: 0.6875rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #6b7280;
    margin: 0 0 0.5rem;
  }

  /* ---- Review notes ---- */
  .notes-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .note-item {
    padding: 0.5rem;
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 0.375rem;
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .note-meta {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 0.5rem;
  }

  .note-author {
    font-size: 0.6875rem;
    font-weight: 600;
    color: #374151;
  }

  .note-time {
    font-size: 0.6875rem;
    color: #9ca3af;
    white-space: nowrap;
  }

  .note-content {
    margin: 0;
    font-size: 0.8125rem;
    color: #374151;
    line-height: 1.45;
    word-break: break-word;
  }
</style>
