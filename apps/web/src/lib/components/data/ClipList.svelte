<script lang="ts">
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { listClips, deleteClip, getClipSpectrogramUrl } from '$lib/api/clips';
  import type { Clip } from '$lib/types/data';
  import DeleteConfirmDialog from '$lib/components/ui/DeleteConfirmDialog.svelte';

  interface Props {
    projectId: string;
    recordingId: string;
    onSelect?: (clipId: string) => void;
    onEdit?: (clip: Clip) => void;
  }

  let { projectId, recordingId, onSelect, onEdit }: Props = $props();

  let page = $state(1);
  const pageSize = 20;
  let sortBy = $state('start_time');
  let sortOrder = $state('asc');
  let clipToDelete = $state<Clip | null>(null);
  let showDeleteDialog = $state(false);

  const queryClient = useQueryClient();

  const clipsQuery = $derived(
    createQuery({
      queryKey: ['clips', projectId, recordingId, page, sortBy, sortOrder],
      queryFn: () => listClips({ projectId, recordingId, page, pageSize, sortBy, sortOrder }),
    })
  );

  const deleteMut = createMutation({
    mutationFn: (clipId: string) => deleteClip(projectId, recordingId, clipId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['clips', projectId, recordingId] });
      queryClient.invalidateQueries({ queryKey: ['recording', projectId, recordingId] });
      clipToDelete = null;
      showDeleteDialog = false;
    },
  });

  function formatTime(seconds: number): string {
    const mins = Math.floor(seconds / 60);
    const secs = (seconds % 60).toFixed(2);
    return `${mins}:${secs.padStart(5, '0')}`;
  }

  function handleDeleteClick(clip: Clip) {
    clipToDelete = clip;
    showDeleteDialog = true;
  }

  function confirmDelete() {
    if (clipToDelete) {
      $deleteMut.mutate(clipToDelete.id);
    }
  }

  function cancelDelete() {
    showDeleteDialog = false;
    clipToDelete = null;
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

<div class="w-full">
  <div class="mb-4 flex items-center justify-between">
    <h3 class="m-0 text-lg font-semibold text-gray-900">Clips</h3>
    {#if $clipsQuery.data}
      <span class="text-sm font-medium text-gray-500">{$clipsQuery.data.total} total</span>
    {/if}
  </div>

  {#if $clipsQuery.isLoading}
    <div class="flex flex-col items-center justify-center gap-3 py-12">
      <svg class="h-8 w-8 animate-spin text-blue-600" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      <p class="text-sm text-gray-500">Loading clips...</p>
    </div>
  {:else if $clipsQuery.error}
    <div class="flex flex-col items-center gap-2 rounded-lg bg-red-50 py-8">
      <svg class="h-10 w-10 text-red-400" viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <circle cx="12" cy="12" r="10" stroke-width="2" />
        <line x1="12" y1="8" x2="12" y2="12" stroke-width="2" />
        <line x1="12" y1="16" x2="12.01" y2="16" stroke-width="2" />
      </svg>
      <p class="text-sm text-red-600">Error: {$clipsQuery.error.message}</p>
    </div>
  {:else if $clipsQuery.data && $clipsQuery.data.items.length === 0}
    <div class="flex flex-col items-center gap-2 rounded-lg bg-gray-50 py-12">
      <svg class="h-10 w-10 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor">
        <path d="M9 11l3 3L22 4" stroke-width="2" />
        <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" stroke-width="2" />
      </svg>
      <p class="text-sm text-gray-500">No clips found</p>
      <p class="text-xs text-gray-400">Create clips manually or use auto-generation</p>
    </div>
  {:else if $clipsQuery.data}
    <div class="overflow-x-auto rounded-lg border border-gray-200">
      <table class="w-full border-collapse bg-white">
        <thead class="border-b border-gray-200 bg-gray-50">
          <tr>
            <th class="w-44 px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
              Preview
            </th>
            <th
              class="w-52 cursor-pointer select-none px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500 hover:bg-gray-100"
              onclick={() => handleSort('start_time')}
            >
              <span class="flex items-center gap-1">
                Time Range
                {#if sortBy === 'start_time'}
                  <svg class="h-3 w-3 {sortOrder === 'desc' ? 'rotate-180' : ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                    <polyline points="18 15 12 9 6 15" stroke-width="2" />
                  </svg>
                {/if}
              </span>
            </th>
            <th class="w-24 px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
              Duration
            </th>
            <th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
              Note
            </th>
            <th class="w-28 px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
              Actions
            </th>
          </tr>
        </thead>
        <tbody>
          {#each $clipsQuery.data.items as clip (clip.id)}
            <tr
              class="border-b border-gray-100 transition-colors last:border-b-0 hover:bg-gray-50 {onSelect ? 'cursor-pointer' : ''}"
              onclick={() => onSelect?.(clip.id)}
              role={onSelect ? 'button' : undefined}
              tabindex={onSelect ? 0 : undefined}
              onkeydown={(e) => e.key === 'Enter' && onSelect?.(clip.id)}
            >
              <td class="p-2">
                <img
                  src={getClipSpectrogramUrl(projectId, recordingId, clip.id, { width: 160, height: 60 })}
                  alt="Clip preview"
                  class="block h-16 w-40 rounded bg-gray-900 object-cover"
                />
              </td>
              <td class="px-4 py-3">
                <span class="font-mono text-sm font-medium text-gray-900">
                  {formatTime(clip.start_time)} - {formatTime(clip.end_time)}
                </span>
              </td>
              <td class="px-4 py-3">
                <span class="font-mono text-sm text-gray-500">
                  {(clip.end_time - clip.start_time).toFixed(2)}s
                </span>
              </td>
              <td class="px-4 py-3">
                {#if clip.note}
                  <span class="text-sm leading-relaxed text-gray-700">{clip.note}</span>
                {:else}
                  <span class="text-sm text-gray-400">-</span>
                {/if}
              </td>
              <td class="px-4 py-3">
                <div class="flex gap-2">
                  {#if onEdit}
                    <button
                      onclick={(e) => { e.stopPropagation(); onEdit?.(clip); }}
                      class="rounded border border-gray-200 p-1.5 transition-colors hover:bg-gray-100"
                      title="Edit clip"
                    >
                      <svg class="h-4 w-4 text-gray-500" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" stroke-width="2" />
                        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" stroke-width="2" />
                      </svg>
                    </button>
                  {/if}
                  <button
                    onclick={(e) => { e.stopPropagation(); handleDeleteClick(clip); }}
                    class="rounded border border-gray-200 p-1.5 transition-colors hover:border-red-200 hover:bg-red-50"
                    title="Delete clip"
                    disabled={$deleteMut.isPending}
                  >
                    <svg class="h-4 w-4 text-gray-500 hover:text-red-500" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                      <polyline points="3 6 5 6 21 6" stroke-width="2" />
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" stroke-width="2" />
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
      <div class="mt-4 flex items-center justify-between py-2">
        <button
          onclick={prevPage}
          disabled={page === 1}
          class="flex items-center gap-1 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <polyline points="15 18 9 12 15 6" stroke-width="2" />
          </svg>
          Previous
        </button>

        <span class="text-sm font-medium text-gray-500">
          Page {page} of {$clipsQuery.data.pages}
        </span>

        <button
          onclick={nextPage}
          disabled={page >= $clipsQuery.data.pages}
          class="flex items-center gap-1 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Next
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <polyline points="9 18 15 12 9 6" stroke-width="2" />
          </svg>
        </button>
      </div>
    {/if}
  {/if}
</div>

<!-- Delete confirmation -->
<DeleteConfirmDialog
  isOpen={showDeleteDialog}
  title="Delete Clip"
  message={clipToDelete ? `Delete clip ${formatTime(clipToDelete.start_time)} - ${formatTime(clipToDelete.end_time)}?` : ''}
  warnings={['All associated annotations']}
  confirmText="Delete Clip"
  isDeleting={$deleteMut.isPending}
  onConfirm={confirmDelete}
  onCancel={cancelDelete}
/>
