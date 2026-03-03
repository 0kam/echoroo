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
    <!-- Skeleton cards matching the 3-column grid layout -->
    <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {#each { length: 6 } as _}
        <div class="animate-pulse overflow-hidden rounded-lg border border-stone-200 bg-white shadow-sm">
          <!-- Spectrogram area placeholder -->
          <div class="h-[120px] bg-stone-200"></div>
          <!-- Card body placeholder -->
          <div class="flex flex-col gap-2 p-2.5">
            <!-- Name + confidence badge row -->
            <div class="flex items-center justify-between gap-2">
              <div class="h-4 w-2/3 rounded bg-stone-200"></div>
              <div class="h-5 w-10 shrink-0 rounded bg-stone-100"></div>
            </div>
            <!-- Recording name line -->
            <div class="h-3 w-4/5 rounded bg-stone-100"></div>
            <!-- Time range line -->
            <div class="h-3 w-1/2 rounded bg-stone-100"></div>
            <!-- Source badge placeholder -->
            <div class="h-5 w-16 rounded bg-stone-100"></div>
          </div>
        </div>
      {/each}
    </div>
  {:else if $detectionsQuery.isError}
    <!-- Error state with retry button -->
    <div class="rounded-lg border border-red-200 bg-red-50 px-4 py-6 text-center">
      <svg class="mx-auto mb-2 h-8 w-8 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
      </svg>
      <p class="text-sm font-medium text-red-700">Failed to load detections</p>
      <p class="mt-1 text-xs text-red-500">
        {$detectionsQuery.error?.message ?? 'An unexpected error occurred'}
      </p>
      <button
        type="button"
        on:click={() => $detectionsQuery.refetch()}
        class="mt-3 rounded-md bg-red-100 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-200"
      >
        Retry
      </button>
    </div>
  {:else if detections.length === 0}
    <div class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-stone-200 py-16 text-center">
      {#if statusFilter}
        <!-- Filtered empty state: no results for the active status filter -->
        <svg class="mb-3 h-12 w-12 text-stone-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2a1 1 0 01-.293.707L13 13.414V19a1 1 0 01-.553.894l-4 2A1 1 0 017 21v-7.586L3.293 6.707A1 1 0 013 6V4z" />
        </svg>
        <p class="text-sm font-medium text-stone-500">No {statusFilter} detections</p>
        <p class="mt-1 text-xs text-stone-400">
          There are no detections with status "{statusFilter}" for the current filters.
        </p>
      {:else}
        <!-- Truly empty: no detections at all -->
        <svg class="mb-3 h-12 w-12 text-stone-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <p class="text-sm font-medium text-stone-500">No detections found</p>
        <p class="mt-1 text-xs text-stone-400">No detections match the current filters.</p>
      {/if}
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
