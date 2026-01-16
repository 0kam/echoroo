<script lang="ts">
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { listClips, deleteClip, getClipSpectrogramUrl } from '$lib/api/clips';
  import type { Clip } from '$lib/types/data';

  export let projectId: string;
  export let recordingId: string;
  export let onSelect: ((clipId: string) => void) | undefined = undefined;
  export let onEdit: ((clip: Clip) => void) | undefined = undefined;

  let page = 1;
  let pageSize = 20;
  let sortBy = 'start_time';
  let sortOrder = 'asc';

  $: clipsQuery = createQuery({
    queryKey: ['clips', projectId, recordingId, page, sortBy, sortOrder],
    queryFn: () => listClips({ projectId, recordingId, page, pageSize, sortBy, sortOrder }),
  });

  const queryClient = useQueryClient();
  const deleteMut = createMutation({
    mutationFn: (clipId: string) => deleteClip(projectId, recordingId, clipId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['clips', projectId, recordingId] });
      queryClient.invalidateQueries({ queryKey: ['recording', projectId, recordingId] });
    },
  });

  function formatTime(seconds: number): string {
    const mins = Math.floor(seconds / 60);
    const secs = (seconds % 60).toFixed(2);
    return `${mins}:${secs.padStart(5, '0')}`;
  }

  function handleDelete(clip: Clip) {
    if (confirm(`Delete clip ${formatTime(clip.start_time)} - ${formatTime(clip.end_time)}?`)) {
      $deleteMut.mutate(clip.id);
    }
  }

  function handleSort(newSortBy: string) {
    if (sortBy === newSortBy) {
      sortOrder = sortOrder === 'asc' ? 'desc' : 'asc';
    } else {
      sortBy = newSortBy;
      sortOrder = 'asc';
    }
  }

  function nextPage() {
    if ($clipsQuery.data && page < $clipsQuery.data.pages) {
      page++;
    }
  }

  function prevPage() {
    if (page > 1) {
      page--;
    }
  }
</script>

<div class="clip-list">
  <div class="header">
    <h3 class="title">Clips</h3>
    {#if $clipsQuery.data}
      <span class="count">{$clipsQuery.data.total} total</span>
    {/if}
  </div>

  {#if $clipsQuery.isLoading}
    <div class="loading-state">
      <div class="spinner"></div>
      <p>Loading clips...</p>
    </div>
  {:else if $clipsQuery.error}
    <div class="error-state">
      <svg class="error-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <circle cx="12" cy="12" r="10" stroke-width="2" />
        <line x1="12" y1="8" x2="12" y2="12" stroke-width="2" />
        <line x1="12" y1="16" x2="12.01" y2="16" stroke-width="2" />
      </svg>
      <p>Error: {$clipsQuery.error.message}</p>
    </div>
  {:else if $clipsQuery.data && $clipsQuery.data.items.length === 0}
    <div class="empty-state">
      <svg class="empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <path d="M9 11l3 3L22 4" stroke-width="2" />
        <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" stroke-width="2" />
      </svg>
      <p>No clips found</p>
      <p class="hint">Create clips manually or use auto-generation above</p>
    </div>
  {:else if $clipsQuery.data}
    <div class="table-container">
      <table class="clips-table">
        <thead>
          <tr>
            <th class="col-preview">Preview</th>
            <th class="col-time sortable" on:click={() => handleSort('start_time')} on:keydown={(e) => e.key === 'Enter' && handleSort('start_time')} role="button" tabindex="0">
              Time Range
              {#if sortBy === 'start_time'}
                <svg class="sort-icon" class:desc={sortOrder === 'desc'} viewBox="0 0 24 24" fill="none" stroke="currentColor">
                  <polyline points="18 15 12 9 6 15" stroke-width="2" />
                </svg>
              {/if}
            </th>
            <th class="col-duration">Duration</th>
            <th class="col-note">Note</th>
            <th class="col-actions">Actions</th>
          </tr>
        </thead>
        <tbody>
          {#each $clipsQuery.data.items as clip (clip.id)}
            <tr
              class="clip-row"
              class:clickable={onSelect}
              on:click={() => onSelect?.(clip.id)}
              on:keydown={(e) => e.key === 'Enter' && onSelect?.(clip.id)}
              role={onSelect ? 'button' : undefined}
              tabindex={onSelect ? 0 : undefined}
            >
              <td class="cell-preview">
                <img
                  src={getClipSpectrogramUrl(projectId, recordingId, clip.id, {
                    width: 160,
                    height: 60,
                  })}
                  alt="Clip preview"
                  class="thumbnail"
                />
              </td>
              <td class="cell-time">
                <span class="time-range">{formatTime(clip.start_time)} - {formatTime(clip.end_time)}</span>
              </td>
              <td class="cell-duration">
                <span class="duration">{(clip.end_time - clip.start_time).toFixed(2)}s</span>
              </td>
              <td class="cell-note">
                {#if clip.note}
                  <span class="note">{clip.note}</span>
                {:else}
                  <span class="no-note">-</span>
                {/if}
              </td>
              <td class="cell-actions">
                <div class="action-buttons">
                  {#if onEdit}
                    <button
                      on:click|stopPropagation={() => onEdit?.(clip)}
                      class="btn-action btn-edit"
                      title="Edit clip"
                    >
                      <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" stroke-width="2" />
                        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" stroke-width="2" />
                      </svg>
                    </button>
                  {/if}
                  <button
                    on:click|stopPropagation={() => handleDelete(clip)}
                    class="btn-action btn-delete"
                    title="Delete clip"
                    disabled={$deleteMut.isPending}
                  >
                    <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                      <polyline points="3 6 5 6 21 6" stroke-width="2" />
                      <path
                        d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"
                        stroke-width="2"
                      />
                    </svg>
                  </button>
                </div>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    <!-- Pagination -->
    {#if $clipsQuery.data.pages > 1}
      <div class="pagination">
        <button on:click={prevPage} disabled={page === 1} class="btn-page">
          <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <polyline points="15 18 9 12 15 6" stroke-width="2" />
          </svg>
          Previous
        </button>

        <span class="page-info">
          Page {page} of {$clipsQuery.data.pages}
        </span>

        <button on:click={nextPage} disabled={page >= $clipsQuery.data.pages} class="btn-page">
          Next
          <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <polyline points="9 18 15 12 9 6" stroke-width="2" />
          </svg>
        </button>
      </div>
    {/if}
  {/if}
</div>

<style>
  .clip-list {
    width: 100%;
  }

  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1rem;
  }

  .title {
    margin: 0;
    font-size: 1.125rem;
    font-weight: 600;
    color: #111827;
  }

  .count {
    font-size: 0.875rem;
    color: #6b7280;
    font-weight: 500;
  }

  .loading-state,
  .error-state,
  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 3rem 1rem;
    gap: 1rem;
  }

  .spinner {
    width: 40px;
    height: 40px;
    border: 4px solid #e5e7eb;
    border-top-color: #3b82f6;
    border-radius: 50%;
    animation: spin 1s linear infinite;
  }

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }

  .loading-state p,
  .error-state p,
  .empty-state p {
    margin: 0;
    color: #6b7280;
    font-size: 0.875rem;
  }

  .error-state {
    background: #fee2e2;
    border-radius: 0.5rem;
    color: #991b1b;
  }

  .error-icon,
  .empty-icon {
    width: 48px;
    height: 48px;
    color: #9ca3af;
  }

  .error-state .error-icon {
    color: #991b1b;
  }

  .empty-state .hint {
    font-size: 0.813rem;
    color: #9ca3af;
  }

  .table-container {
    overflow-x: auto;
    border: 1px solid #e5e7eb;
    border-radius: 0.5rem;
  }

  .clips-table {
    width: 100%;
    border-collapse: collapse;
    background: white;
  }

  thead {
    background: #f9fafb;
    border-bottom: 1px solid #e5e7eb;
  }

  th {
    padding: 0.75rem 1rem;
    text-align: left;
    font-size: 0.75rem;
    font-weight: 600;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  th.sortable {
    cursor: pointer;
    user-select: none;
    transition: background 0.15s ease;
  }

  th.sortable:hover {
    background: #f3f4f6;
  }

  .sort-icon {
    display: inline-block;
    width: 14px;
    height: 14px;
    margin-left: 0.25rem;
    vertical-align: middle;
    transition: transform 0.2s ease;
  }

  .sort-icon.desc {
    transform: rotate(180deg);
  }

  .col-preview {
    width: 180px;
  }

  .col-time {
    width: 220px;
  }

  .col-duration {
    width: 100px;
  }

  .col-note {
    min-width: 200px;
  }

  .col-actions {
    width: 120px;
  }

  .clip-row {
    border-bottom: 1px solid #e5e7eb;
    transition: background 0.15s ease;
  }

  .clip-row:last-child {
    border-bottom: none;
  }

  .clip-row:hover {
    background: #f9fafb;
  }

  .clip-row.clickable {
    cursor: pointer;
  }

  td {
    padding: 0.75rem 1rem;
    font-size: 0.875rem;
  }

  .cell-preview {
    padding: 0.5rem;
  }

  .thumbnail {
    display: block;
    width: 160px;
    height: 60px;
    border-radius: 0.25rem;
    object-fit: cover;
    background: #1f2937;
  }

  .time-range {
    font-family: monospace;
    color: #111827;
    font-weight: 500;
  }

  .duration {
    font-family: monospace;
    color: #6b7280;
  }

  .note {
    color: #374151;
    line-height: 1.4;
  }

  .no-note {
    color: #9ca3af;
  }

  .action-buttons {
    display: flex;
    gap: 0.5rem;
  }

  .btn-action {
    padding: 0.375rem;
    background: none;
    border: 1px solid #d1d5db;
    border-radius: 0.25rem;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .btn-action:hover:not(:disabled) {
    background: #f3f4f6;
  }

  .btn-action:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .btn-action .icon {
    width: 16px;
    height: 16px;
    color: #6b7280;
  }

  .btn-edit:hover:not(:disabled) .icon {
    color: #3b82f6;
  }

  .btn-delete:hover:not(:disabled) {
    background: #fee2e2;
    border-color: #fecaca;
  }

  .btn-delete:hover:not(:disabled) .icon {
    color: #dc2626;
  }

  .pagination {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 1rem;
    padding: 0.75rem 0;
  }

  .page-info {
    font-size: 0.875rem;
    color: #6b7280;
    font-weight: 500;
  }

  .btn-page {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 0.75rem;
    font-size: 0.875rem;
    font-weight: 500;
    background: white;
    color: #374151;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .btn-page:hover:not(:disabled) {
    background: #f9fafb;
    border-color: #3b82f6;
  }

  .btn-page:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .btn-page .icon {
    width: 16px;
    height: 16px;
  }
</style>
