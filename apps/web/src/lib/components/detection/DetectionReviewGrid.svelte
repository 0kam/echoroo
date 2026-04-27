<script lang="ts">
  /**
   * DetectionReviewGrid - Main grid for reviewing detections filtered by species tag.
   *
   * Features:
   * - TanStack Query for data fetching and mutations
   * - Status filter bar (All / Needs Votes / Agreed / Disputed / Rejected)
   * - Confidence slider filter
   * - Pagination controls
   * - Keyboard shortcuts: 1=Solo, 2=Dominant, 3=Mixed, D=Disagree, U=Unsure, Space=Play, Arrow=Navigate
   * - Vote summaries per detection card
   * - Shared audio playback via reviewNavigation hook
   */

  import { onDestroy, untrack } from 'svelte';
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { fetchDetections, changeDetectionSpecies } from '$lib/api/detections';
  import { castVote, deleteVote } from '$lib/api/votes';
  import type { DetectionStatus, DetectionListResponse, VoteSummary, VoteValue, SignalQuality } from '$lib/types/detection';
  import * as m from '$lib/paraglide/messages';
  import { getLocale } from '$lib/paraglide/runtime';
  import { createReviewNavigation } from '$lib/utils/reviewNavigation.svelte';
  import DetectionCard from './DetectionCard.svelte';

  let {
    projectId,
    tagId,
    detectionRunId = undefined,
  }: {
    projectId: string;
    tagId: string;
    detectionRunId?: string;
  } = $props();

  const queryClient = useQueryClient();

  // Filter state — use legacy DetectionStatus type for API compatibility
  // but also support consensus-based filter labels in UI
  let statusFilter: DetectionStatus | undefined = $state(undefined);
  let confidenceMin = $state(0);
  let confidenceMax = $state(1);
  let page = $state(1);
  const PAGE_SIZE = 12;

  // Track which detection is currently being mutated (voting)
  let mutatingId: string | null = $state(null);

  // Vote summaries keyed by detection ID
  let voteSummaries: Record<string, VoteSummary> = $state({});

  // DOM references for card elements (scroll-into-view)
  let cardElements: (HTMLElement | null)[] = $state([]);

  // Active UI locale — forwarded so the backend attaches `vernacular_name`
  // to embedded Tag records and kept in the query key so a language switch
  // invalidates the client-side cache cleanly.
  const locale = $derived(getLocale());

  // Query key includes all filter params and the active locale.
  const detectionsQueryKey = $derived([
    'detections',
    projectId,
    tagId,
    statusFilter,
    confidenceMin,
    page,
    PAGE_SIZE,
    detectionRunId,
    locale,
  ]);

  const detectionsQuery = $derived(
    createQuery({
      queryKey: detectionsQueryKey,
      queryFn: () =>
        fetchDetections(projectId, {
          tag_id: tagId,
          status: statusFilter,
          confidence_min: confidenceMin > 0 ? confidenceMin : undefined,
          confidence_max: confidenceMax < 1 ? confidenceMax : undefined,
          page,
          page_size: PAGE_SIZE,
          detection_run_id: detectionRunId,
          locale,
        }),
      placeholderData: (prev: DetectionListResponse | undefined) => prev,
    })
  );

  const detections = $derived($detectionsQuery.data?.items ?? []);
  const totalPages = $derived($detectionsQuery.data?.pages ?? 1);
  const totalItems = $derived($detectionsQuery.data?.total ?? 0);

  // Populate vote summaries from the inline votes data returned with each detection.
  // This avoids N+1 API calls — the backend already includes vote counts in the response.
  $effect(() => {
    const currentDetections = detections;
    if (currentDetections.length === 0) return;

    const newSummaries: Record<string, VoteSummary> = { ...voteSummaries };
    let changed = false;
    for (const detection of currentDetections) {
      if (!(detection.id in newSummaries) && detection.votes) {
        newSummaries[detection.id] = {
          annotation_id: detection.id,
          agree_count: detection.votes.agree_count,
          disagree_count: detection.votes.disagree_count,
          unsure_count: detection.votes.unsure_count,
          user_vote: detection.votes.user_vote,
          user_signal_quality: detection.votes.user_signal_quality,
          signal_quality_counts: detection.votes.signal_quality_counts ?? { solo: 0, dominant: 0, mixed: 0 },
          consensus_status: detection.votes.consensus_status,
          // Compact list-response counts do not include voters[] or per-source
          // breakdown; lazy-load via getAnnotationVoteSummary() when needed.
          voters: [],
          member_agree: 0,
          member_disagree: 0,
          guest_authenticated_agree: 0,
          guest_authenticated_disagree: 0,
          trusted_user_agree: 0,
          trusted_user_disagree: 0,
        };
        changed = true;
      }
    }
    if (changed) {
      voteSummaries = newSummaries;
    }
  });

  // Shared keyboard navigation and audio playback. The initial
  // `projectId` value is captured via untrack() because this navigation
  // helper is configured once at mount; dynamic reactivity is not needed.
  const nav = createReviewNavigation({
    projectId: untrack(() => projectId),
    itemCount: () => detections.length,
    onConfirm: () => {
      // Legacy confirm — no-op in voting mode
    },
    onReject: () => {
      // Legacy reject — no-op in voting mode
    },
    onAgreeSolo: (i) => {
      const d = detections[i];
      if (d && mutatingId === null) {
        handleAgree(d.id, 'solo');
      }
    },
    onAgreeDominant: (i) => {
      const d = detections[i];
      if (d && mutatingId === null) {
        handleAgree(d.id, 'dominant');
      }
    },
    onAgreeMixed: (i) => {
      const d = detections[i];
      if (d && mutatingId === null) {
        handleAgree(d.id, 'mixed');
      }
    },
    onDisagree: (i) => {
      const d = detections[i];
      if (d && mutatingId === null) {
        handleVote(d.id, 'disagree');
      }
    },
    onUnsure: (i) => {
      const d = detections[i];
      if (d && mutatingId === null) {
        handleVote(d.id, 'unsure');
      }
    },
    getPlaybackInfo: (i) => {
      const d = detections[i];
      if (!d) return null;
      return {
        recordingId: d.recording_id,
        startTime: d.start_time,
        endTime: d.end_time,
      };
    },
    getElement: (i) => cardElements[i] ?? null,
  });

  onDestroy(() => {
    nav.cleanup();
  });

  // Vote mutation
  const voteMutation = createMutation({
    mutationFn: ({
      detectionId,
      vote,
      signalQuality,
    }: {
      detectionId: string;
      vote: VoteValue;
      signalQuality?: SignalQuality;
    }) => castVote(projectId, detectionId, vote, signalQuality),
    onMutate: ({ detectionId }) => {
      mutatingId = detectionId;
    },
    onSuccess: (summary, { detectionId }) => {
      // Update the local vote summary immediately
      voteSummaries = { ...voteSummaries, [detectionId]: summary };
    },
    onSettled: () => {
      mutatingId = null;
      queryClient.invalidateQueries({ queryKey: ['detections', projectId, tagId] });
    },
  });

  // Remove vote mutation
  const removeVoteMutation = createMutation({
    mutationFn: ({ detectionId }: { detectionId: string }) =>
      deleteVote(projectId, detectionId),
    onMutate: ({ detectionId }) => {
      mutatingId = detectionId;
    },
    onSuccess: (summary, { detectionId }) => {
      // Update the local vote summary immediately from the response
      voteSummaries = { ...voteSummaries, [detectionId]: summary };
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

  function handleAgree(detectionId: string, signalQuality: SignalQuality) {
    $voteMutation.mutate({ detectionId, vote: 'agree', signalQuality });
  }

  function handleVote(detectionId: string, vote: VoteValue) {
    $voteMutation.mutate({ detectionId, vote });
  }

  function handleRemoveVote(detectionId: string) {
    $removeVoteMutation.mutate({ detectionId });
  }

  function handleChangeSpecies(detectionId: string, newTagId: string) {
    $changeSpeciesMutation.mutate({ detectionId, newTagId });
  }

  function handleStatusFilter(status: DetectionStatus | undefined) {
    statusFilter = status;
    page = 1;
    nav.select(0);
  }

  function handleConfidenceChange() {
    page = 1;
    nav.select(0);
  }

  function prevPage() {
    if (page > 1) {
      page -= 1;
      nav.select(0);
    }
  }

  function nextPage() {
    if (page < totalPages) {
      page += 1;
      nav.select(0);
    }
  }
</script>

<svelte:window onkeydown={nav.handleKeydown} />

<div class="flex flex-col gap-4">
  <!-- Filter bar -->
  <div class="flex flex-wrap items-center gap-3 rounded-lg border border-stone-200 bg-stone-50 p-3">
    <!-- Status filters: updated to reflect consensus-based labels -->
    <div class="flex items-center gap-1">
      <span class="mr-1 text-xs font-medium text-stone-500">{m.detection_filter_status_label()}</span>
      <button
        type="button"
        class="rounded px-2.5 py-1 text-xs font-medium transition-colors
          {statusFilter === undefined
            ? 'bg-stone-700 text-white'
            : 'border border-stone-300 bg-surface-card text-stone-600 hover:bg-stone-100'}"
        onclick={() => handleStatusFilter(undefined)}
      >
        {m.detection_filter_all()}
        {#if totalItems > 0}
          <span class="ml-1 opacity-70">({totalItems})</span>
        {/if}
      </button>
      <button
        type="button"
        class="rounded px-2.5 py-1 text-xs font-medium transition-colors
          {statusFilter === 'unreviewed'
            ? 'bg-stone-700 text-white'
            : 'border border-stone-300 bg-surface-card text-stone-600 hover:bg-stone-100'}"
        onclick={() => handleStatusFilter('unreviewed')}
      >
        {m.detection_filter_needs_votes()}
      </button>
      <button
        type="button"
        class="rounded px-2.5 py-1 text-xs font-medium transition-colors
          {statusFilter === 'confirmed'
            ? 'bg-success text-white'
            : 'border border-success/40 bg-success-light text-success hover:bg-success/20'}"
        onclick={() => handleStatusFilter('confirmed')}
      >
        {m.detection_filter_agreed()}
      </button>
      <button
        type="button"
        class="rounded px-2.5 py-1 text-xs font-medium transition-colors
          {statusFilter === 'rejected'
            ? 'bg-danger text-white'
            : 'border border-danger/40 bg-danger-light text-danger hover:bg-danger/20'}"
        onclick={() => handleStatusFilter('rejected')}
      >
        {m.detection_filter_rejected()}
      </button>
    </div>

    <!-- Confidence filter -->
    <div class="flex items-center gap-2">
      <span class="text-xs font-medium text-stone-500">
        {m.detection_filter_min_confidence({ percent: Math.round(confidenceMin * 100) })}
      </span>
      <input
        type="range"
        min="0"
        max="1"
        step="0.05"
        bind:value={confidenceMin}
        onchange={handleConfidenceChange}
        class="w-24 accent-primary-500"
        aria-label={m.detection_filter_confidence_aria()}
      />
    </div>

    <!-- Keyboard shortcuts hint -->
    <div class="ml-auto flex items-center gap-2 text-xs text-stone-400">
      <kbd class="rounded border border-stone-200 bg-surface-card px-1.5 py-0.5 font-mono text-xs">1</kbd> {m.detection_keyboard_solo()}
      <kbd class="rounded border border-stone-200 bg-surface-card px-1.5 py-0.5 font-mono text-xs">2</kbd> {m.detection_keyboard_dominant()}
      <kbd class="rounded border border-stone-200 bg-surface-card px-1.5 py-0.5 font-mono text-xs">3</kbd> {m.detection_keyboard_mixed()}
      <kbd class="rounded border border-stone-200 bg-surface-card px-1.5 py-0.5 font-mono text-xs">D</kbd> {m.detection_keyboard_disagree()}
      <kbd class="rounded border border-stone-200 bg-surface-card px-1.5 py-0.5 font-mono text-xs">U</kbd> {m.detection_keyboard_unsure()}
      <kbd class="rounded border border-stone-200 bg-surface-card px-1.5 py-0.5 font-mono text-xs">Space</kbd> {m.detection_keyboard_play()}
      <kbd class="rounded border border-stone-200 bg-surface-card px-1.5 py-0.5 font-mono text-xs">Arrows</kbd> {m.detection_keyboard_navigate()}
    </div>
  </div>

  <!-- Loading / error state -->
  {#if $detectionsQuery.isLoading}
    <!-- Skeleton cards matching the 3-column grid layout -->
    <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {#each { length: 6 } as _}
        <div class="animate-pulse overflow-hidden rounded-lg border border-stone-200 bg-surface-card shadow-sm">
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
            <!-- Vote buttons placeholder -->
            <div class="flex gap-1.5">
              <div class="h-6 w-14 rounded bg-success-light"></div>
              <div class="h-6 w-14 rounded bg-danger-light"></div>
              <div class="h-6 w-14 rounded bg-warning-light"></div>
            </div>
          </div>
        </div>
      {/each}
    </div>
  {:else if $detectionsQuery.isError}
    <!-- Error state with retry button -->
    <div class="rounded-lg border border-danger/30 bg-danger-light px-4 py-6 text-center">
      <svg class="mx-auto mb-2 h-8 w-8 text-danger" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
      </svg>
      <p class="text-sm font-medium text-danger">{m.detection_load_detections_error()}</p>
      <p class="mt-1 text-xs text-danger/80">
        {$detectionsQuery.error?.message ?? m.common_error_unexpected()}
      </p>
      <button
        type="button"
        onclick={() => $detectionsQuery.refetch()}
        class="mt-3 rounded-md bg-danger-light px-3 py-1.5 text-xs font-medium text-danger hover:bg-danger/20 border border-danger/30"
      >
        {m.detection_retry()}
      </button>
    </div>
  {:else if detections.length === 0}
    <div class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-stone-200 py-16 text-center">
      {#if statusFilter}
        <!-- Filtered empty state: no results for the active status filter -->
        <svg class="mb-3 h-12 w-12 text-stone-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2a1 1 0 01-.293.707L13 13.414V19a1 1 0 01-.553.894l-4 2A1 1 0 017 21v-7.586L3.293 6.707A1 1 0 013 6V4z" />
        </svg>
        <p class="text-sm font-medium text-stone-500">{m.detection_no_status_results_title({ status: statusFilter })}</p>
        <p class="mt-1 text-xs text-stone-400">
          {m.detection_no_status_results_body({ status: statusFilter })}
        </p>
      {:else}
        <!-- Truly empty: no detections at all -->
        <svg class="mb-3 h-12 w-12 text-stone-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <p class="text-sm font-medium text-stone-500">{m.detection_no_results_title()}</p>
        <p class="mt-1 text-xs text-stone-400">{m.detection_no_results_body()}</p>
      {/if}
    </div>
  {:else}
    <!-- Detection grid: responsive 1-3 columns -->
    <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {#each detections as detection, i (detection.id)}
        <div bind:this={cardElements[i]}>
          <DetectionCard
            {detection}
            {projectId}
            isSelected={i === nav.selectedIndex}
            isLoading={mutatingId === detection.id}
            voteSummary={voteSummaries[detection.id] ?? null}
            externalIsPlaying={nav.playingIndex === i && nav.isPlaying}
            externalIsLoadingAudio={nav.playingIndex === i && nav.isLoadingAudio}
            onPlayToggle={() => nav.togglePlay(i)}
            onAgree={handleAgree}
            onVote={handleVote}
            onRemoveVote={handleRemoveVote}
            onChangeSpecies={handleChangeSpecies}
          />
        </div>
      {/each}
    </div>

    <!-- Pagination -->
    {#if totalPages > 1}
      <div class="flex items-center justify-center gap-3 py-2">
        <button
          type="button"
          class="rounded border border-stone-300 bg-surface-card px-3 py-1.5 text-sm text-stone-600 hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-40"
          onclick={prevPage}
          disabled={page === 1}
        >
          {m.detection_previous()}
        </button>
        <span class="text-sm text-stone-500">
          {m.detection_page_of({ page, total: totalPages })}
        </span>
        <button
          type="button"
          class="rounded border border-stone-300 bg-surface-card px-3 py-1.5 text-sm text-stone-600 hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-40"
          onclick={nextPage}
          disabled={page === totalPages}
        >
          {m.detection_next()}
        </button>
      </div>
    {/if}

    <!-- Results summary -->
    <p class="text-center text-xs text-stone-400">
      {m.detection_showing_count({ showing: detections.length, total: totalItems })}
    </p>
  {/if}
</div>
