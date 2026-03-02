<script lang="ts">
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { listRecordings, deleteRecording } from '$lib/api/recordings';
  import type { Recording } from '$lib/types/data';
  import DeleteConfirmDialog from '$lib/components/ui/DeleteConfirmDialog.svelte';

  interface Props {
    projectId: string;
    datasetId?: string;
    siteId?: string;
    onSelect?: (recordingId: string) => void;
  }

  let { projectId, datasetId, siteId, onSelect }: Props = $props();

  const queryClient = useQueryClient();

  let page = $state(1);
  let search = $state('');
  let sortBy = $state('datetime');
  let sortOrder = $state('desc');
  let datetimeFrom = $state('');
  let datetimeTo = $state('');
  const pageSize = 20;

  let recordingToDelete = $state<Recording | null>(null);
  let showDeleteDialog = $state(false);

  const recordingsQuery = $derived(
    createQuery({
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
    })
  );

  const deleteMutation = createMutation({
    mutationFn: (recordingId: string) => deleteRecording(projectId, recordingId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['recordings', projectId] });
      recordingToDelete = null;
      showDeleteDialog = false;
    },
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
    onSelect?.(recording.id);
  }

  function handleDeleteClick(recording: Recording) {
    recordingToDelete = recording;
    showDeleteDialog = true;
  }

  function confirmDelete() {
    if (recordingToDelete) {
      $deleteMutation.mutate(recordingToDelete.id);
    }
  }

  function cancelDelete() {
    showDeleteDialog = false;
    recordingToDelete = null;
  }

  function handleSort(column: string) {
    if (sortBy === column) {
      sortOrder = sortOrder === 'asc' ? 'desc' : 'asc';
    } else {
      sortBy = column;
      sortOrder = 'asc';
    }
    page = 1;
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

  function handleSearchInput() {
    page = 1;
  }
</script>

<div class="w-full">
  <!-- Search and filters -->
  <div class="mb-4 flex flex-wrap gap-3">
    <input
      type="text"
      placeholder="Search recordings..."
      bind:value={search}
      oninput={handleSearchInput}
      class="min-w-[200px] flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
    />

    <div class="flex gap-2">
      <input
        type="datetime-local"
        bind:value={datetimeFrom}
        oninput={handleSearchInput}
        title="From date"
        class="rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
      />
      <input
        type="datetime-local"
        bind:value={datetimeTo}
        oninput={handleSearchInput}
        title="To date"
        class="rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
      />
    </div>

    <select
      bind:value={sortOrder}
      class="rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
    >
      <option value="desc">Descending</option>
      <option value="asc">Ascending</option>
    </select>
  </div>

  <!-- Loading and error states -->
  {#if $recordingsQuery.isLoading}
    <div class="flex items-center justify-center rounded-lg bg-gray-50 py-12">
      <svg class="mr-3 h-5 w-5 animate-spin text-blue-600" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      <span class="text-sm text-gray-600">Loading recordings...</span>
    </div>
  {:else if $recordingsQuery.error}
    <div class="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
      Error: {$recordingsQuery.error.message}
    </div>
  {:else if $recordingsQuery.data}
    {@const recordings = $recordingsQuery.data.items}

    {#if recordings.length === 0}
      <div class="rounded-lg bg-gray-50 py-12 text-center">
        <svg class="mx-auto mb-3 h-10 w-10 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
        </svg>
        <p class="text-sm text-gray-500">No recordings found.</p>
      </div>
    {:else}
      <!-- Recordings table -->
      <div class="overflow-x-auto rounded-lg border border-gray-200 bg-white">
        <table class="w-full border-collapse">
          <thead class="border-b border-gray-200 bg-gray-50">
            <tr>
              <th
                class="cursor-pointer px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500 hover:bg-gray-100"
                onclick={() => handleSort('filename')}
              >
                <span class="flex items-center gap-1">
                  Filename
                  {#if sortBy === 'filename'}
                    <svg class="h-3 w-3 {sortOrder === 'desc' ? 'rotate-180' : ''}" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7" />
                    </svg>
                  {/if}
                </span>
              </th>
              <th
                class="cursor-pointer px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500 hover:bg-gray-100"
                onclick={() => handleSort('datetime')}
              >
                <span class="flex items-center gap-1">
                  Date/Time
                  {#if sortBy === 'datetime'}
                    <svg class="h-3 w-3 {sortOrder === 'desc' ? 'rotate-180' : ''}" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7" />
                    </svg>
                  {/if}
                </span>
              </th>
              <th
                class="cursor-pointer px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500 hover:bg-gray-100"
                onclick={() => handleSort('duration')}
              >
                <span class="flex items-center gap-1">
                  Duration
                  {#if sortBy === 'duration'}
                    <svg class="h-3 w-3 {sortOrder === 'desc' ? 'rotate-180' : ''}" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7" />
                    </svg>
                  {/if}
                </span>
              </th>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                Sample Rate
              </th>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                Ch
              </th>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                Status
              </th>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                Actions
              </th>
            </tr>
          </thead>
          <tbody>
            {#each recordings as recording (recording.id)}
              <tr
                class="border-b border-gray-100 transition-colors last:border-b-0 hover:bg-gray-50 {onSelect ? 'cursor-pointer' : ''}"
                onclick={() => onSelect && handleRowClick(recording)}
              >
                <td class="px-4 py-3">
                  <span class="font-mono text-sm font-medium text-gray-900">{recording.filename}</span>
                </td>
                <td class="px-4 py-3 text-sm text-gray-600">{formatDatetime(recording.datetime)}</td>
                <td class="px-4 py-3 text-sm text-gray-600">{formatDuration(recording.duration)}</td>
                <td class="px-4 py-3 text-sm text-gray-600">{formatSamplerate(recording.samplerate)}</td>
                <td class="px-4 py-3 text-sm text-gray-600">{recording.channels}</td>
                <td class="px-4 py-3">
                  <span
                    class="inline-flex items-center rounded px-2 py-0.5 text-xs font-medium capitalize
                      {recording.datetime_parse_status === 'success' ? 'bg-green-100 text-green-800' : ''}
                      {recording.datetime_parse_status === 'pending' ? 'bg-yellow-100 text-yellow-800' : ''}
                      {recording.datetime_parse_status === 'failed' ? 'bg-red-100 text-red-800' : ''}"
                  >
                    {recording.datetime_parse_status}
                  </span>
                </td>
                <td class="px-4 py-3">
                  <button
                    class="rounded border border-red-200 bg-white px-2 py-1 text-xs font-medium text-red-600 transition-colors hover:bg-red-50 hover:border-red-300"
                    onclick={(e) => { e.stopPropagation(); handleDeleteClick(recording); }}
                    disabled={$deleteMutation.isPending}
                    aria-label="Delete recording"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <div class="mt-4 flex items-center justify-between py-2">
        <button
          onclick={prevPage}
          disabled={page <= 1}
          class="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Previous
        </button>
        <span class="text-sm text-gray-500">
          Page {$recordingsQuery.data.page} of {$recordingsQuery.data.pages}
          ({$recordingsQuery.data.total} total)
        </span>
        <button
          onclick={nextPage}
          disabled={page >= $recordingsQuery.data.pages}
          class="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Next
        </button>
      </div>
    {/if}
  {/if}
</div>

<!-- Delete confirmation dialog -->
<DeleteConfirmDialog
  isOpen={showDeleteDialog}
  title="Delete Recording"
  message={recordingToDelete ? `Are you sure you want to delete "${recordingToDelete.filename}"? This will also delete all associated clips.` : ''}
  warnings={['All associated clips and annotations']}
  confirmText="Delete Recording"
  isDeleting={$deleteMutation.isPending}
  onConfirm={confirmDelete}
  onCancel={cancelDelete}
/>
