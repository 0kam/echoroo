<script lang="ts">
  /**
   * DetectionReviewGrid - Main grid for reviewing detections filtered by species tag.
   *
   * Features:
   * - TanStack Query for data fetching and mutations
   * - Status filter bar (All / Unreviewed / Confirmed / Rejected)
   * - Confidence slider filter
   * - Pagination controls
   * - Keyboard shortcuts: C=Confirm, R=Reject, Space=Play, Arrow=Navigate
   */

  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { fetchDetections, confirmDetection, rejectDetection, changeDetectionSpecies } from '$lib/api/detections';
  import type { DetectionStatus, DetectionListResponse } from '$lib/types/detection';
  import DetectionCard from './DetectionCard.svelte';

  export let projectId: string;
  export let tagId: string;

  const queryClient = useQueryClient();

  // Filter state
  let statusFilter: DetectionStatus | undefined = undefined;
  let confidenceMin = 0;
  let confidenceMax = 1;
  let page = 1;
  const PAGE_SIZE = 12;

  // Selected card index for keyboard navigation
  let selectedIndex = 0;

  // Track which detection is currently being mutated
  let mutatingId: string | null = null;

  // Query key includes all filter params
  $: queryKey = ['detections', projectId, tagId, statusFilter, confidenceMin, page, PAGE_SIZE];

  $: detectionsQuery = createQuery({
    queryKey: queryKey,
    queryFn: () =>
      fetchDetections(projectId, {
        tag_id: tagId,
        status: statusFilter,
        confidence_min: confidenceMin > 0 ? confidenceMin : undefined,
        confidence_max: confidenceMax < 1 ? confidenceMax : undefined,
        page,
        page_size: PAGE_SIZE,
      }),
    placeholderData: (prev: DetectionListResponse | undefined) => prev,
  });

  $: detections = $detectionsQuery.data?.items ?? [];
  $: totalPages = $detectionsQuery.data?.pages ?? 1;
  $: totalItems = $detectionsQuery.data?.total ?? 0;

  // Status counts from current page (approximate - server should provide totals ideally)
  $: confirmedCount = detections.filter((d) => d.status === 'confirmed').length;
  $: rejectedCount = detections.filter((d) => d.status === 'rejected').length;
  $: unreviewedCount = detections.filter((d) => d.status === 'unreviewed').length;

  // Mutations
  const confirmMutation = createMutation({
    mutationFn: ({ detectionId }: { detectionId: string; startTime: number; endTime: number }) =>
      confirmDetection(projectId, detectionId),
    onMutate: ({ detectionId }) => {
      mutatingId = detectionId;
    },
    onSettled: () => {
      mutatingId = null;
      queryClient.invalidateQueries({ queryKey: ['detections', projectId, tagId] });
    },
  });

  const rejectMutation = createMutation({
    mutationFn: ({ detectionId }: { detectionId: string }) =>
      rejectDetection(projectId, detectionId),
    onMutate: ({ detectionId }) => {
      mutatingId = detectionId;
    },
    onSettled: () => {
      mutatingId = null;
      queryClient.invalidateQueries({ queryKey: ['detections', projectId, tagId] });
    },
  });

  const changeSpeciesMutation = createMutation({
    mutationFn: ({ detectionId, newTagId }: { detectionId: string; newTagId: string }) =>
      changeDetectionSpecies(projectId, detectionId, { new_tag_id: newTagId }),
    onMutate: ({ detectionId }) => {
      mutatingId = detectionId;
    },
    onSettled: () => {
      mutatingId = null;
      queryClient.invalidateQueries({ queryKey: ['detections', projectId, tagId] });
    },
  });

  function handleConfirm(detectionId: string, startTime: number, endTime: number) {
    $confirmMutation.mutate({ detectionId, startTime, endTime });
  }

  function handleReject(detectionId: string) {
    $rejectMutation.mutate({ detectionId });
  }

  function handleChangeSpecies(detectionId: string, newTagId: string) {
    $changeSpeciesMutation.mutate({ detectionId, newTagId });
  }

  function handleStatusFilter(status: DetectionStatus | undefined) {
    statusFilter = status;
    page = 1;
    selectedIndex = 0;
  }

  function handleConfidenceChange() {
    page = 1;
    selectedIndex = 0;
  }

  function prevPage() {
    if (page > 1) {
      page -= 1;
      selectedIndex = 0;
    }
  }

  function nextPage() {
    if (page < totalPages) {
      page += 1;
      selectedIndex = 0;
    }
  }

  // Keyboard shortcuts
  function handleKeydown(e: KeyboardEvent) {
    // Ignore if focus is on an input/button/select
    const target = e.target as HTMLElement;
    if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT') {
      return;
    }

    if (detections.length === 0) return;

    const selected = detections[selectedIndex];

    switch (e.key) {
      case 'c':
      case 'C':
        if (selected && mutatingId === null) {
          e.preventDefault();
          handleConfirm(selected.id, selected.start_time, selected.end_time);
        }
        break;

      case 'r':
      case 'R':
        if (selected && mutatingId === null) {
          e.preventDefault();
          handleReject(selected.id);
        }
        break;

      case 'ArrowRight':
      case 'ArrowDown':
        e.preventDefault();
        selectedIndex = Math.min(selectedIndex + 1, detections.length - 1);
        break;

      case 'ArrowLeft':
      case 'ArrowUp':
        e.preventDefault();
        selectedIndex = Math.max(selectedIndex - 1, 0);
        break;
    }
  }
</script>

<svelte:window on:keydown={handleKeydown} />

<div class="flex flex-col gap-4">
  <!-- Filter bar -->
  <div class="flex flex-wrap items-center gap-3 rounded-lg border border-stone-200 bg-stone-50 p-3">
    <!-- Status filters -->
    <div class="flex items-center gap-1">
      <span class="mr-1 text-xs font-medium text-stone-500">Status:</span>
      <button
        type="button"
        class="rounded px-2.5 py-1 text-xs font-medium transition-colors
          {statusFilter === undefined
            ? 'bg-stone-700 text-white'
            : 'border border-stone-300 bg-white text-stone-600 hover:bg-stone-100'}"
        on:click={() => handleStatusFilter(undefined)}
      >
        All
        {#if totalItems > 0}
          <span class="ml-1 opacity-70">({totalItems})</span>
        {/if}
      </button>
      <button
        type="button"
        class="rounded px-2.5 py-1 text-xs font-medium transition-colors
          {statusFilter === 'unreviewed'
            ? 'bg-stone-700 text-white'
            : 'border border-stone-300 bg-white text-stone-600 hover:bg-stone-100'}"
        on:click={() => handleStatusFilter('unreviewed')}
      >
        Unreviewed
      </button>
      <button
        type="button"
        class="rounded px-2.5 py-1 text-xs font-medium transition-colors
          {statusFilter === 'confirmed'
            ? 'bg-green-600 text-white'
            : 'border border-green-200 bg-green-50 text-green-700 hover:bg-green-100'}"
        on:click={() => handleStatusFilter('confirmed')}
      >
        Confirmed
      </button>
      <button
        type="button"
        class="rounded px-2.5 py-1 text-xs font-medium transition-colors
          {statusFilter === 'rejected'
            ? 'bg-red-600 text-white'
            : 'border border-red-200 bg-red-50 text-red-700 hover:bg-red-100'}"
        on:click={() => handleStatusFilter('rejected')}
      >
        Rejected
      </button>
    </div>

    <!-- Confidence filter -->
    <div class="flex items-center gap-2">
      <span class="text-xs font-medium text-stone-500">
        Min confidence: {Math.round(confidenceMin * 100)}%
      </span>
      <input
        type="range"
        min="0"
        max="1"
        step="0.05"
        bind:value={confidenceMin}
        on:change={handleConfidenceChange}
        class="w-24 accent-blue-500"
        aria-label="Minimum confidence threshold"
      />
    </div>

    <!-- Keyboard shortcuts hint -->
    <div class="ml-auto flex items-center gap-2 text-xs text-stone-400">
      <kbd class="rounded border border-stone-200 bg-white px-1.5 py-0.5 font-mono text-xs">C</kbd> Confirm
      <kbd class="rounded border border-stone-200 bg-white px-1.5 py-0.5 font-mono text-xs">R</kbd> Reject
      <kbd class="rounded border border-stone-200 bg-white px-1.5 py-0.5 font-mono text-xs">Space</kbd> Play
      <kbd class="rounded border border-stone-200 bg-white px-1.5 py-0.5 font-mono text-xs">Arrows</kbd> Navigate
    </div>
  </div>

  <!-- Loading / error state -->
  {#if $detectionsQuery.isLoading}
    <div class="flex items-center justify-center py-12">
      <svg class="h-6 w-6 animate-spin text-stone-400" viewBox="0 0 24 24" fill="none">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      <span class="ml-2 text-sm text-stone-500">Loading detections...</span>
    </div>
  {:else if $detectionsQuery.isError}
    <div class="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
      Failed to load detections: {$detectionsQuery.error?.message ?? 'Unknown error'}
    </div>
  {:else if detections.length === 0}
    <div class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-stone-200 py-16 text-center">
      <svg class="mb-3 h-12 w-12 text-stone-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
      <p class="text-sm font-medium text-stone-500">No detections found</p>
      <p class="mt-1 text-xs text-stone-400">
        {statusFilter ? `No ${statusFilter} detections for this filter.` : 'No detections match the current filters.'}
      </p>
    </div>
  {:else}
    <!-- Detection grid: responsive 1-3 columns -->
    <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {#each detections as detection, i (detection.id)}
        <DetectionCard
          {detection}
          {projectId}
          isSelected={i === selectedIndex}
          isLoading={mutatingId === detection.id}
          onConfirm={handleConfirm}
          onReject={handleReject}
          onChangeSpecies={handleChangeSpecies}
        />
      {/each}
    </div>

    <!-- Pagination -->
    {#if totalPages > 1}
      <div class="flex items-center justify-center gap-3 py-2">
        <button
          type="button"
          class="rounded border border-stone-300 bg-white px-3 py-1.5 text-sm text-stone-600 hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-40"
          on:click={prevPage}
          disabled={page === 1}
        >
          Previous
        </button>
        <span class="text-sm text-stone-500">
          Page {page} of {totalPages}
        </span>
        <button
          type="button"
          class="rounded border border-stone-300 bg-white px-3 py-1.5 text-sm text-stone-600 hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-40"
          on:click={nextPage}
          disabled={page === totalPages}
        >
          Next
        </button>
      </div>
    {/if}

    <!-- Results summary -->
    <p class="text-center text-xs text-stone-400">
      Showing {detections.length} of {totalItems} detections
    </p>
  {/if}
</div>
