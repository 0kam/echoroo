<script lang="ts">
  /**
   * TagList — the paginated tag table with loading / error / empty states.
   *
   * Extracted from the tag settings page. Receives the tags query result and
   * dispatches edit / delete / page-change actions back to the parent shell,
   * which owns the TanStack query and pagination state.
   */
  import * as m from '$lib/paraglide/messages';
  import type { Tag, TagCategory, TagListResponse } from '$lib/types/tag';
  import { getCategoryLabel } from './categoryLabel';

  interface Props {
    /** Current page of the tags query, or `undefined` while unresolved. */
    data: TagListResponse | undefined;
    isLoading: boolean;
    isError: boolean;
    /** Raw error message (empty string when none). */
    errorMessage: string;
    /** Active free-text search (drives the empty-state copy). */
    search: string;
    /** Active category filter (drives the empty-state copy). */
    categoryFilter: TagCategory | '';
    currentPage: number;
    onEdit: (tag: Tag) => void;
    onDelete: (tag: Tag) => void;
    onPageChange: (page: number) => void;
  }

  const {
    data,
    isLoading,
    isError,
    errorMessage,
    search,
    categoryFilter,
    currentPage,
    onEdit,
    onDelete,
    onPageChange,
  }: Props = $props();

  // Resolve parent name from the current tags list.
  function getParentName(parentId: string | null | undefined): string {
    if (!parentId || !data) return '';
    const found = data.items.find((t) => t.id === parentId);
    return found ? found.name : parentId;
  }
</script>

{#if isLoading}
  <div class="state-message state-message--loading">{m.annotation_tag_loading()}</div>
{:else if isError}
  <div class="state-message state-message--error">
    {m.annotation_tag_error_load({ message: errorMessage })}
  </div>
{:else if data}
  {#if data.items.length === 0}
    <div class="state-message">
      {search || categoryFilter ? m.annotation_tag_empty_filter() : m.annotation_tag_empty()}
    </div>
  {:else}
    <div class="tag-table-wrapper">
      <table class="tag-table">
        <thead>
          <tr>
            <th>{m.annotation_tag_col_name()}</th>
            <th>{m.annotation_tag_col_category()}</th>
            <th>{m.annotation_tag_col_scientific()}</th>
            <th>{m.annotation_tag_col_common()}</th>
            <th>{m.annotation_tag_col_parent()}</th>
            <th class="col-actions">{m.annotation_tag_col_actions()}</th>
          </tr>
        </thead>
        <tbody>
          {#each data.items as tag}
            <tr>
              <td class="cell-name">{tag.name}</td>
              <td>
                <span class="category-badge category-badge--{tag.category}">
                  {getCategoryLabel(tag.category)}
                </span>
              </td>
              <td class="cell-italic">{tag.scientific_name ?? '—'}</td>
              <td>{tag.common_name ?? '—'}</td>
              <td>{tag.parent_id ? getParentName(tag.parent_id) : '—'}</td>
              <td class="cell-actions">
                <button
                  class="action-btn action-btn--edit"
                  onclick={() => onEdit(tag)}
                  aria-label="{m.annotation_tag_edit_button()} {tag.name}"
                >
                  {m.annotation_tag_edit_button()}
                </button>
                <button
                  class="action-btn action-btn--delete"
                  onclick={() => onDelete(tag)}
                  aria-label="{m.annotation_tag_delete_button()} {tag.name}"
                >
                  {m.annotation_tag_delete_button()}
                </button>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    <!-- Pagination -->
    {#if data.pages > 1}
      <div class="pagination">
        <button
          class="page-btn"
          onclick={() => onPageChange(Math.max(1, currentPage - 1))}
          disabled={currentPage === 1}
        >
          {m.annotation_tag_previous()}
        </button>
        <span class="page-info">
          {m.annotation_tag_page_info({ page: currentPage, total: data.pages })}
        </span>
        <button
          class="page-btn"
          onclick={() => onPageChange(Math.min(data.pages, currentPage + 1))}
          disabled={currentPage === data.pages}
        >
          {m.annotation_tag_next()}
        </button>
      </div>
    {/if}

    {#if data.total > 0}
      <div class="pagination-info">
        {m.annotation_tag_showing({ showing: data.items.length, total: data.total })}
      </div>
    {/if}
  {/if}
{/if}

<style>
  /* State messages */
  .state-message {
    padding: 2rem;
    text-align: center;
    border-radius: 0.5rem;
    background: #f3f4f6;
    color: #6b7280;
    font-size: 0.875rem;
  }

  .state-message--loading {
    background: #f3f4f6;
    color: #6b7280;
  }

  .state-message--error {
    background: #fef2f2;
    color: #dc2626;
  }

  /* Tag table */
  .tag-table-wrapper {
    border: 1px solid #e5e7eb;
    border-radius: 0.5rem;
    overflow: hidden;
  }

  .tag-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.875rem;
  }

  .tag-table thead {
    background: #f9fafb;
  }

  .tag-table th {
    padding: 0.75rem 1rem;
    text-align: left;
    font-weight: 600;
    color: #374151;
    border-bottom: 1px solid #e5e7eb;
  }

  .tag-table td {
    padding: 0.75rem 1rem;
    border-bottom: 1px solid #f3f4f6;
    color: #374151;
    vertical-align: middle;
  }

  .tag-table tr:last-child td {
    border-bottom: none;
  }

  .tag-table tr:hover td {
    background: #f9fafb;
  }

  .cell-name {
    font-weight: 500;
    color: #111827;
  }

  .cell-italic {
    font-style: italic;
    color: #6b7280;
  }

  .col-actions {
    width: 140px;
    text-align: right;
  }

  .cell-actions {
    display: flex;
    justify-content: flex-end;
    gap: 0.5rem;
  }

  /* Category badges */
  .category-badge {
    display: inline-block;
    font-size: 0.75rem;
    font-weight: 500;
    padding: 0.125rem 0.5rem;
    border-radius: 0.25rem;
  }

  .category-badge--species {
    background: #dcfce7;
    color: #166534;
  }

  .category-badge--sound_type {
    background: #dbeafe;
    color: #1e40af;
  }

  .category-badge--quality {
    background: #fef9c3;
    color: #854d0e;
  }

  /* Action buttons */
  .action-btn {
    padding: 0.25rem 0.625rem;
    font-size: 0.8125rem;
    border-radius: 0.25rem;
    cursor: pointer;
    border: none;
    font-weight: 500;
    transition: background 0.15s;
  }

  .action-btn--edit {
    background: #f3f4f6;
    color: #374151;
  }

  .action-btn--edit:hover {
    background: #e5e7eb;
  }

  .action-btn--delete {
    background: #fef2f2;
    color: #dc2626;
  }

  .action-btn--delete:hover {
    background: #fee2e2;
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
    background: rgb(var(--color-card-bg));
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
</style>
