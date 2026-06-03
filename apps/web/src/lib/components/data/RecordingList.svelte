<script lang="ts">
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { listRecordings, deleteRecording } from '$lib/api/recordings';
  import type { ProjectRecordingItem } from '$lib/api/recordings';
  import DeleteConfirmDialog from '$lib/components/ui/DeleteConfirmDialog.svelte';
  import * as m from '$lib/paraglide/messages';
  import { getLocale } from '$lib/paraglide/runtime';

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

  let recordingToDelete = $state<ProjectRecordingItem | null>(null);
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

  function formatDuration(seconds: number | null): string {
    if (seconds === null) return 'N/A';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  }

  function formatSamplerate(sr: number): string {
    return sr >= 1000 ? `${(sr / 1000).toFixed(1)} kHz` : `${sr} Hz`;
  }

  function formatDatetime(datetime: string | null): string {
    if (!datetime) return 'N/A';
    return new Date(datetime).toLocaleString(getLocale());
  }

  function handleRowClick(recording: ProjectRecordingItem) {
    onSelect?.(recording.id);
  }

  function handleDeleteClick(recording: ProjectRecordingItem) {
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
      placeholder={m.recording_list_search_placeholder()}
      bind:value={search}
      oninput={handleSearchInput}
      class="min-w-[200px] flex-1 rounded-md border border-stone-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
    />

    <div class="flex gap-2">
      <input
        type="datetime-local"
        bind:value={datetimeFrom}
        oninput={handleSearchInput}
        title={m.recording_list_from_date()}
        class="rounded-md border border-stone-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none"
      />
      <input
        type="datetime-local"
        bind:value={datetimeTo}
        oninput={handleSearchInput}
        title={m.recording_list_to_date()}
        class="rounded-md border border-stone-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none"
      />
    </div>

    <select
      bind:value={sortOrder}
      class="rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-sm focus:border-primary-500 focus:outline-none"
    >
      <option value="desc">{m.recording_list_sort_desc()}</option>
      <option value="asc">{m.recording_list_sort_asc()}</option>
    </select>
  </div>

  <!-- Loading and error states -->
  {#if $recordingsQuery.isLoading}
    <div class="flex items-center justify-center rounded-lg bg-stone-50 py-12">
      <svg class="mr-3 h-5 w-5 animate-spin text-primary-600" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      <span class="text-sm text-stone-600">{m.common_loading_recordings()}</span>
    </div>
  {:else if $recordingsQuery.error}
    <div class="rounded-lg bg-danger-light px-4 py-3 text-sm text-danger">
      {m.recording_list_error({ message: $recordingsQuery.error.message })}
    </div>
  {:else if $recordingsQuery.data}
    {@const recordings = $recordingsQuery.data.items}

    {#if recordings.length === 0}
      <div class="rounded-lg bg-stone-50 py-12 text-center">
        <svg class="mx-auto mb-3 h-10 w-10 text-stone-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
        </svg>
        <p class="text-sm text-stone-500">{m.recording_list_empty()}</p>
      </div>
    {:else}
      <!-- Recordings table -->
      <div class="overflow-x-auto rounded-lg border border-card bg-surface-card">
        <table class="w-full border-collapse">
          <thead class="border-b border-stone-200 bg-stone-50">
            <tr>
              <th
                class="cursor-pointer px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-stone-500 hover:bg-stone-100"
                onclick={() => handleSort('filename')}
              >
                <span class="flex items-center gap-1">
                  {m.recording_list_col_filename()}
                  {#if sortBy === 'filename'}
                    <svg class="h-3 w-3 {sortOrder === 'desc' ? 'rotate-180' : ''}" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7" />
                    </svg>
                  {/if}
                </span>
              </th>
              <th
                class="cursor-pointer px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-stone-500 hover:bg-stone-100"
                onclick={() => handleSort('datetime')}
              >
                <span class="flex items-center gap-1">
                  {m.recording_list_col_datetime()}
                  {#if sortBy === 'datetime'}
                    <svg class="h-3 w-3 {sortOrder === 'desc' ? 'rotate-180' : ''}" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7" />
                    </svg>
                  {/if}
                </span>
              </th>
              <th
                class="cursor-pointer px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-stone-500 hover:bg-stone-100"
                onclick={() => handleSort('duration')}
              >
                <span class="flex items-center gap-1">
                  {m.recording_list_col_duration()}
                  {#if sortBy === 'duration'}
                    <svg class="h-3 w-3 {sortOrder === 'desc' ? 'rotate-180' : ''}" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7" />
                    </svg>
                  {/if}
                </span>
              </th>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-stone-500">
                {m.recording_list_col_sample_rate()}
              </th>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-stone-500">
                {m.recording_list_col_channels()}
              </th>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-stone-500">
                {m.recording_list_col_status()}
              </th>
              <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-stone-500">
                {m.recording_list_col_actions()}
              </th>
            </tr>
          </thead>
          <tbody>
            {#each recordings as recording (recording.id)}
              <tr
                class="border-b border-stone-100 transition-colors last:border-b-0 hover:bg-stone-50 {onSelect ? 'cursor-pointer' : ''}"
                onclick={() => onSelect && handleRowClick(recording)}
              >
                <td class="px-4 py-3">
                  <span class="font-mono text-sm font-medium text-stone-900">{recording.name}</span>
                </td>
                <td class="px-4 py-3 text-sm text-stone-600">{formatDatetime(recording.datetime)}</td>
                <td class="px-4 py-3 text-sm text-stone-600">{formatDuration(recording.duration_seconds)}</td>
                <td class="px-4 py-3 text-sm text-stone-600">{formatSamplerate(recording.samplerate)}</td>
                <td class="px-4 py-3 text-sm text-stone-600">{recording.channels}</td>
                <td class="px-4 py-3">
                  <span
                    class="inline-flex items-center rounded px-2 py-0.5 text-xs font-medium capitalize
                      {recording.datetime_parse_status === 'success' ? 'bg-success-light text-success' : ''}
                      {recording.datetime_parse_status === 'pending' ? 'bg-warning-light text-warning' : ''}
                      {recording.datetime_parse_status === 'failed' ? 'bg-danger-light text-danger' : ''}"
                  >
                    {recording.datetime_parse_status}
                  </span>
                </td>
                <td class="px-4 py-3">
                  <button
                    class="rounded border border-danger/20 bg-surface-card px-2 py-1 text-xs font-medium text-danger transition-colors hover:bg-danger-light hover:border-danger/30"
                    onclick={(e) => { e.stopPropagation(); handleDeleteClick(recording); }}
                    disabled={$deleteMutation.isPending}
                    aria-label={m.recording_list_delete_aria()}
                  >
                    {m.common_delete()}
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
          class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {m.common_previous()}
        </button>
        <span class="text-sm text-stone-500">
          {m.recording_list_page_info({ page: $recordingsQuery.data.page, pages: $recordingsQuery.data.pages, total: $recordingsQuery.data.total })}
        </span>
        <button
          onclick={nextPage}
          disabled={page >= $recordingsQuery.data.pages}
          class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {m.common_next()}
        </button>
      </div>
    {/if}
  {/if}
</div>

<!-- Delete confirmation dialog -->
<DeleteConfirmDialog
  isOpen={showDeleteDialog}
  title={m.recording_list_delete_title()}
  message={recordingToDelete ? m.recording_list_delete_message({ filename: recordingToDelete.name }) : ''}
  warnings={[m.recording_list_delete_warnings()]}
  confirmText={m.recording_list_delete_confirm()}
  isDeleting={$deleteMutation.isPending}
  onConfirm={confirmDelete}
  onCancel={cancelDelete}
/>
