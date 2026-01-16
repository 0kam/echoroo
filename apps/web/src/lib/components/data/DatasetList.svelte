<script lang="ts">
  import type { Dataset, DatasetStatus, DatasetVisibility } from '$lib/types/data';

  export let datasets: Dataset[] = [];
  export let onSelect: (dataset: Dataset) => void = () => {};
  export let onDelete: (dataset: Dataset) => void = () => {};
  export let selectedId: string | null = null;

  // Filter states
  export let search: string = '';
  export let statusFilter: DatasetStatus | '' = '';
  export let visibilityFilter: DatasetVisibility | '' = '';
  export let onFilterChange: () => void = () => {};

  function formatDate(dateStr: string): string {
    return new Date(dateStr).toLocaleDateString();
  }

  function getStatusColor(status: DatasetStatus): string {
    switch (status) {
      case 'pending':
        return 'status-pending';
      case 'scanning':
      case 'processing':
        return 'status-processing';
      case 'completed':
        return 'status-completed';
      case 'failed':
        return 'status-failed';
      default:
        return 'status-pending';
    }
  }

  function getStatusLabel(status: DatasetStatus): string {
    switch (status) {
      case 'pending':
        return 'Pending';
      case 'scanning':
        return 'Scanning';
      case 'processing':
        return 'Processing';
      case 'completed':
        return 'Ready';
      case 'failed':
        return 'Failed';
      default:
        return status;
    }
  }
</script>

<div class="dataset-list">
  <!-- Filters -->
  <div class="filters">
    <input
      type="text"
      placeholder="Search datasets..."
      bind:value={search}
      on:input={onFilterChange}
      class="search-input"
    />

    <select bind:value={statusFilter} on:change={onFilterChange} class="filter-select">
      <option value="">All Statuses</option>
      <option value="pending">Pending</option>
      <option value="scanning">Scanning</option>
      <option value="processing">Processing</option>
      <option value="completed">Ready</option>
      <option value="failed">Failed</option>
    </select>

    <select bind:value={visibilityFilter} on:change={onFilterChange} class="filter-select">
      <option value="">All Visibility</option>
      <option value="private">Private</option>
      <option value="public">Public</option>
    </select>
  </div>

  <!-- Dataset list -->
  {#if datasets.length === 0}
    <div class="empty-state">
      <p>No datasets found. Create your first dataset to get started.</p>
    </div>
  {:else}
    <ul>
      {#each datasets as dataset (dataset.id)}
        <!-- svelte-ignore a11y_no_noninteractive_element_to_interactive_role -->
        <li
          class="dataset-item"
          class:selected={dataset.id === selectedId}
          role="button"
          tabindex="0"
          on:click={() => onSelect(dataset)}
          on:keydown={(e) => e.key === 'Enter' && onSelect(dataset)}
        >
          <div class="dataset-info">
            <div class="dataset-header">
              <h3>{dataset.name}</h3>
              <span class="status-badge {getStatusColor(dataset.status)}">
                {getStatusLabel(dataset.status)}
              </span>
            </div>

            {#if dataset.description}
              <p class="description">{dataset.description}</p>
            {/if}

            <div class="dataset-meta">
              <span class="meta-item">
                <span class="meta-label">Path:</span>
                <code>{dataset.audio_dir}</code>
              </span>
              <span class="meta-item">
                <span class="meta-label">Visibility:</span>
                {dataset.visibility}
              </span>
              <span class="meta-item">
                <span class="meta-label">Files:</span>
                {dataset.processed_files} / {dataset.total_files}
              </span>
            </div>

            <p class="date">Created: {formatDate(dataset.created_at)}</p>
          </div>

          <div class="dataset-actions">
            <button
              class="delete-btn"
              on:click|stopPropagation={() => onDelete(dataset)}
              aria-label="Delete dataset"
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
  .dataset-list {
    width: 100%;
  }

  .filters {
    display: flex;
    gap: 0.75rem;
    margin-bottom: 1rem;
    flex-wrap: wrap;
  }

  .search-input {
    flex: 1;
    min-width: 200px;
    padding: 0.625rem 0.75rem;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    font-size: 0.875rem;
  }

  .search-input:focus {
    outline: none;
    border-color: #3b82f6;
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
  }

  .filter-select {
    padding: 0.625rem 0.75rem;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    background: white;
    cursor: pointer;
  }

  .filter-select:focus {
    outline: none;
    border-color: #3b82f6;
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
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

  .dataset-item {
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

  .dataset-item:hover {
    background: #f9fafb;
    border-color: #d1d5db;
  }

  .dataset-item.selected {
    background: #eff6ff;
    border-color: #3b82f6;
  }

  .dataset-info {
    flex: 1;
  }

  .dataset-header {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 0.5rem;
  }

  .dataset-info h3 {
    margin: 0;
    font-size: 1rem;
    font-weight: 600;
    color: #111827;
  }

  .status-badge {
    padding: 0.25rem 0.625rem;
    border-radius: 0.25rem;
    font-size: 0.75rem;
    font-weight: 500;
  }

  .status-pending {
    background: #fef3c7;
    color: #92400e;
  }

  .status-processing {
    background: #dbeafe;
    color: #1e40af;
  }

  .status-completed {
    background: #d1fae5;
    color: #065f46;
  }

  .status-failed {
    background: #fee2e2;
    color: #991b1b;
  }

  .description {
    margin: 0 0 0.75rem 0;
    font-size: 0.875rem;
    color: #6b7280;
  }

  .dataset-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 1rem;
    margin-bottom: 0.5rem;
  }

  .meta-item {
    font-size: 0.75rem;
    color: #6b7280;
  }

  .meta-label {
    font-weight: 500;
    margin-right: 0.25rem;
  }

  .meta-item code {
    background: #f3f4f6;
    padding: 0.125rem 0.375rem;
    border-radius: 0.25rem;
    font-family: monospace;
    font-size: 0.75rem;
  }

  .date {
    margin: 0;
    font-size: 0.75rem;
    color: #9ca3af;
  }

  .dataset-actions {
    margin-left: 1rem;
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
