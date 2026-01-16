<script lang="ts">
  import { createQuery } from '@tanstack/svelte-query';
  import { listRecordings } from '$lib/api/recordings';
  import type { Recording } from '$lib/types/data';

  export let projectId: string;
  export let datasetId: string | undefined = undefined;
  export let siteId: string | undefined = undefined;
  export let onSelect: ((recordingId: string) => void) | undefined = undefined;

  let page = 1;
  let search = '';
  let sortBy = 'datetime';
  let sortOrder = 'desc';
  let datetimeFrom = '';
  let datetimeTo = '';
  const pageSize = 20;

  $: recordingsQuery = createQuery({
    queryKey: [
      'recordings',
      projectId,
      datasetId,
      siteId,
      page,
      search,
      sortBy,
      sortOrder,
      datetimeFrom,
      datetimeTo,
    ],
    queryFn: () =>
      listRecordings({
        projectId,
        datasetId,
        siteId,
        page,
        pageSize,
        search: search || undefined,
        sortBy,
        sortOrder,
        datetimeFrom: datetimeFrom || undefined,
        datetimeTo: datetimeTo || undefined,
      }),
  });

  function formatDuration(seconds: number): string {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  }

  function formatSamplerate(sr: number): string {
    return sr >= 1000 ? `${(sr / 1000).toFixed(1)} kHz` : `${sr} Hz`;
  }

  function formatDatetime(datetime: string | null): string {
    if (!datetime) return 'N/A';
    return new Date(datetime).toLocaleString();
  }

  function handleRowClick(recording: Recording) {
    if (onSelect) {
      onSelect(recording.id);
    }
  }

  function nextPage() {
    if ($recordingsQuery.data && page < $recordingsQuery.data.pages) {
      page++;
    }
  }

  function prevPage() {
    if (page > 1) {
      page--;
    }
  }
</script>

<div class="recording-list">
  <!-- Search and filters -->
  <div class="filters">
    <input
      type="text"
      placeholder="Search recordings..."
      bind:value={search}
      class="search-input"
    />

    <div class="date-filters">
      <input
        type="datetime-local"
        placeholder="From"
        bind:value={datetimeFrom}
        class="date-input"
      />
      <input type="datetime-local" placeholder="To" bind:value={datetimeTo} class="date-input" />
    </div>

    <select bind:value={sortBy} class="filter-select">
      <option value="datetime">Date/Time</option>
      <option value="filename">Filename</option>
      <option value="duration">Duration</option>
      <option value="created_at">Created</option>
    </select>

    <select bind:value={sortOrder} class="filter-select">
      <option value="desc">Descending</option>
      <option value="asc">Ascending</option>
    </select>
  </div>

  <!-- Loading and error states -->
  {#if $recordingsQuery.isLoading}
    <div class="loading-state">
      <p>Loading recordings...</p>
    </div>
  {:else if $recordingsQuery.error}
    <div class="error-state">
      <p>Error: {$recordingsQuery.error.message}</p>
    </div>
  {:else if $recordingsQuery.data}
    {@const recordings = $recordingsQuery.data.items}

    {#if recordings.length === 0}
      <div class="empty-state">
        <p>No recordings found.</p>
      </div>
    {:else}
      <!-- Recordings table -->
      <div class="table-container">
        <table class="recordings-table">
          <thead>
            <tr>
              <th>Filename</th>
              <th>Date/Time</th>
              <th>Duration</th>
              <th>Sample Rate</th>
              <th>Channels</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {#each recordings as recording (recording.id)}
              <!-- svelte-ignore a11y_click_events_have_key_events -->
              <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
              <tr class="recording-row" on:click={() => handleRowClick(recording)}>
                <td class="filename">{recording.filename}</td>
                <td>{formatDatetime(recording.datetime)}</td>
                <td>{formatDuration(recording.duration)}</td>
                <td>{formatSamplerate(recording.samplerate)}</td>
                <td>{recording.channels}</td>
                <td>
                  <span
                    class="status-badge"
                    class:status-success={recording.datetime_parse_status === 'success'}
                    class:status-pending={recording.datetime_parse_status === 'pending'}
                    class:status-failed={recording.datetime_parse_status === 'failed'}
                  >
                    {recording.datetime_parse_status}
                  </span>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <div class="pagination">
        <button on:click={prevPage} disabled={page <= 1} class="pagination-btn">
          Previous
        </button>
        <span class="pagination-info">
          Page {$recordingsQuery.data.page} of {$recordingsQuery.data.pages}
          ({$recordingsQuery.data.total} total)
        </span>
        <button
          on:click={nextPage}
          disabled={page >= $recordingsQuery.data.pages}
          class="pagination-btn"
        >
          Next
        </button>
      </div>
    {/if}
  {/if}
</div>

<style>
  .recording-list {
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

  .date-filters {
    display: flex;
    gap: 0.5rem;
  }

  .date-input {
    padding: 0.625rem 0.75rem;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    font-size: 0.875rem;
  }

  .date-input:focus {
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

  .loading-state,
  .error-state,
  .empty-state {
    padding: 2rem;
    text-align: center;
    background: #f9fafb;
    border-radius: 0.5rem;
  }

  .error-state {
    background: #fee2e2;
    color: #991b1b;
  }

  .table-container {
    overflow-x: auto;
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 0.5rem;
  }

  .recordings-table {
    width: 100%;
    border-collapse: collapse;
  }

  .recordings-table thead {
    background: #f9fafb;
    border-bottom: 1px solid #e5e7eb;
  }

  .recordings-table th {
    padding: 0.75rem 1rem;
    text-align: left;
    font-size: 0.75rem;
    font-weight: 600;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .recording-row {
    border-bottom: 1px solid #e5e7eb;
    cursor: pointer;
    transition: background-color 0.15s ease;
  }

  .recording-row:hover {
    background: #f9fafb;
  }

  .recording-row:last-child {
    border-bottom: none;
  }

  .recordings-table td {
    padding: 0.875rem 1rem;
    font-size: 0.875rem;
    color: #374151;
  }

  .filename {
    font-family: monospace;
    font-weight: 500;
    color: #111827;
  }

  .status-badge {
    display: inline-block;
    padding: 0.25rem 0.625rem;
    border-radius: 0.25rem;
    font-size: 0.75rem;
    font-weight: 500;
    text-transform: capitalize;
  }

  .status-success {
    background: #d1fae5;
    color: #065f46;
  }

  .status-pending {
    background: #fef3c7;
    color: #92400e;
  }

  .status-failed {
    background: #fee2e2;
    color: #991b1b;
  }

  .pagination {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: 1rem;
    padding: 1rem 0;
  }

  .pagination-btn {
    padding: 0.5rem 1rem;
    font-size: 0.875rem;
    background: white;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .pagination-btn:hover:not(:disabled) {
    background: #f9fafb;
    border-color: #3b82f6;
  }

  .pagination-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .pagination-info {
    font-size: 0.875rem;
    color: #6b7280;
  }
</style>
