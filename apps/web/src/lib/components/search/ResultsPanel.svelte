<script lang="ts">
  /**
   * ResultsPanel - Displays batch similarity search results using a detection-review-style layout.
   *
   * Features:
   * - Species tabs at the top (one per species)
   * - Client-side threshold and max-per-species filter bar
   * - Spectrogram card grid for the selected species
   * - Voting actions (Agree/Disagree/Unsure) on each card
   * - Keyboard shortcuts: Space=Play, 1=Solo, 2=Dominant, 3=Mixed, D=Disagree, U=Unsure, Arrow Up/Down=Navigate
   */

  import { onDestroy } from 'svelte';
  import { createMutation } from '@tanstack/svelte-query';
  import * as m from '$lib/paraglide/messages.js';
  import type { SpeciesMatchResult, TargetSpecies, SimilarityResult } from '$lib/types/search';
  import type { VoteSummary, VoteValue, SignalQuality } from '$lib/types/detection';
  import { castAnnotationVote, deleteAnnotationVote, getAnnotationVotes } from '$lib/api/votes';
  import { createAnnotationFromSearch } from '$lib/api/search';
  import { createReviewNavigation } from '$lib/utils/reviewNavigation.svelte';
  import SearchResultCard from './SearchResultCard.svelte';

  interface Props {
    projectId: string;
    results: Record<string, SpeciesMatchResult> | null;
    totalMatches: number;
    searchDurationMs: number;
    isSearching: boolean;
    searchingSpecies: TargetSpecies[];
    searchSessionId?: string;
  }

  let {
    projectId,
    results,
    totalMatches,
    searchDurationMs,
    isSearching,
    searchingSpecies,
    searchSessionId,
  }: Props = $props();

  // Client-side filter state
  let filterThreshold = $state(0.1);
  let filterMaxPerSpecies = $state(20);

  // Currently selected species tab key
  let selectedTabKey = $state<string | null>(null);

  // DOM references for scroll-into-view
  let cardElements: (HTMLElement | null)[] = $state([]);

  // Track which embedding is currently being mutated (voting)
  let mutatingId: string | null = $state(null);

  // Vote summaries keyed by embedding_id
  let voteSummaries = $state<Record<string, VoteSummary>>({});

  // Mapping from embedding_id to annotation_id (created on first vote)
  let annotationIds = $state<Record<string, string>>({});

  // In-flight annotation creation promises to avoid duplicate requests
  const pendingAnnotations = new Map<string, Promise<string>>();

  /**
   * Ensure an annotation record exists for the given search result.
   * Creates one via the search annotation endpoint if not already tracked.
   * Returns the annotation ID.
   */
  async function ensureAnnotation(match: SimilarityResult): Promise<string> {
    // Already resolved
    const existing = annotationIds[match.embedding_id];
    if (existing) return existing;

    // Already in-flight
    const pending = pendingAnnotations.get(match.embedding_id);
    if (pending) return pending;

    // Determine the tag_id from the currently selected species group
    const tagId = selectedTabKey !== null && selectedGroup
      ? getTagId(selectedTabKey, selectedGroup)
      : null;
    if (!tagId) {
      throw new Error('No tag available for annotation creation');
    }

    const promise = createAnnotationFromSearch(projectId, {
      recording_id: match.recording_id,
      tag_id: tagId,
      start_time: match.start_time,
      end_time: match.end_time,
      confidence: match.similarity,
      review_status: 'unreviewed',
      source: 'similarity_search',
      search_session_id: searchSessionId,
    }).then((response) => {
      const annId = (response as { id: string }).id;
      annotationIds = { ...annotationIds, [match.embedding_id]: annId };
      pendingAnnotations.delete(match.embedding_id);
      return annId;
    }).catch((err) => {
      pendingAnnotations.delete(match.embedding_id);
      throw err;
    });

    pendingAnnotations.set(match.embedding_id, promise);
    return promise;
  }

  // Vote mutation: ensures annotation exists, then casts the vote
  const voteMutation = createMutation({
    mutationFn: async ({
      embeddingId,
      match,
      vote,
      signalQuality,
    }: {
      embeddingId: string;
      match: SimilarityResult;
      vote: VoteValue;
      signalQuality?: SignalQuality;
    }) => {
      const annotationId = await ensureAnnotation(match);
      return castAnnotationVote(projectId, annotationId, vote, signalQuality);
    },
    onMutate: ({ embeddingId }) => {
      mutatingId = embeddingId;
    },
    onSuccess: (summary, { embeddingId }) => {
      voteSummaries = { ...voteSummaries, [embeddingId]: summary };
    },
    onSettled: () => {
      mutatingId = null;
    },
  });

  // Remove vote mutation: uses the annotation ID we already tracked
  const removeVoteMutation = createMutation({
    mutationFn: async ({ embeddingId }: { embeddingId: string }) => {
      const annotationId = annotationIds[embeddingId];
      if (!annotationId) {
        throw new Error('No annotation found for this result');
      }
      return deleteAnnotationVote(projectId, annotationId);
    },
    onMutate: ({ embeddingId }) => {
      mutatingId = embeddingId;
    },
    onSuccess: (summary, { embeddingId }) => {
      voteSummaries = { ...voteSummaries, [embeddingId]: summary };
    },
    onSettled: () => {
      mutatingId = null;
    },
  });

  function handleAgree(match: SimilarityResult, signalQuality: SignalQuality) {
    $voteMutation.mutate({ embeddingId: match.embedding_id, match, vote: 'agree', signalQuality });
  }

  function handleVote(match: SimilarityResult, vote: VoteValue) {
    $voteMutation.mutate({ embeddingId: match.embedding_id, match, vote });
  }

  function handleRemoveVote(embeddingId: string) {
    $removeVoteMutation.mutate({ embeddingId });
  }

  // Shared keyboard navigation and audio playback
  const nav = createReviewNavigation({
    projectId,
    itemCount: () => filteredMatches.length,
    onConfirm: () => {
      // No-op: voting mode does not use legacy confirm
    },
    onReject: () => {
      // No-op: voting mode does not use legacy reject
    },
    onAgreeSolo: (i) => {
      const match = filteredMatches[i];
      if (match && mutatingId === null) {
        handleAgree(match, 'solo');
      }
    },
    onAgreeDominant: (i) => {
      const match = filteredMatches[i];
      if (match && mutatingId === null) {
        handleAgree(match, 'dominant');
      }
    },
    onAgreeMixed: (i) => {
      const match = filteredMatches[i];
      if (match && mutatingId === null) {
        handleAgree(match, 'mixed');
      }
    },
    onDisagree: (i) => {
      const match = filteredMatches[i];
      if (match && mutatingId === null) {
        handleVote(match, 'disagree');
      }
    },
    onUnsure: (i) => {
      const match = filteredMatches[i];
      if (match && mutatingId === null) {
        handleVote(match, 'unsure');
      }
    },
    getPlaybackInfo: (i) => {
      const match = filteredMatches[i];
      if (!match) return null;
      return {
        recordingId: match.recording_id,
        startTime: match.start_time,
        endTime: match.end_time,
      };
    },
    getElement: (i) => cardElements[i] ?? null,
  });

  onDestroy(() => {
    nav.cleanup();
  });

  // Species entry list derived from results
  const speciesEntries = $derived(
    results !== null ? Object.entries(results) : []
  );

  // When results change (new search or session load), reset the tab selection
  // and clear the vote summary and annotation ID caches.
  $effect(() => {
    if (results !== null) {
      const keys = Object.keys(results);
      selectedTabKey = keys.length > 0 ? (keys[0] ?? null) : null;
      nav.select(0);
      voteSummaries = {};
      annotationIds = {};
      pendingAnnotations.clear();
    }
  });

  // Load vote summaries for the currently visible filtered matches.
  // Only loads votes for results that already have a tracked annotation ID.
  $effect(() => {
    const matches = filteredMatches;
    if (matches.length === 0) return;

    for (const match of matches) {
      if (!(match.embedding_id in voteSummaries)) {
        const annId = annotationIds[match.embedding_id];
        if (annId) {
          getAnnotationVotes(projectId, annId)
            .then((summary) => {
              voteSummaries = { ...voteSummaries, [match.embedding_id]: summary };
            })
            .catch(() => {
              // Silently ignore — vote summaries are optional enhancement
            });
        }
        // If no annotation exists yet, votes will be loaded after first vote
      }
    }
  });

  // Filtered matches for the currently selected species
  const selectedGroup = $derived(
    selectedTabKey !== null && results !== null ? results[selectedTabKey] : null
  );

  const filteredMatches = $derived(
    selectedGroup !== null && selectedGroup !== undefined
      ? selectedGroup.matches
          .filter((r) => r.similarity >= filterThreshold)
          .slice(0, filterMaxPerSpecies)
      : []
  );

  // Filtered count per species tab (for badges)
  function getFilteredCount(group: SpeciesMatchResult): number {
    return group.matches
      .filter((r) => r.similarity >= filterThreshold)
      .slice(0, filterMaxPerSpecies).length;
  }

  function getTagId(tagKey: string, group: SpeciesMatchResult): string {
    // Use tag_id from group if present, otherwise fall back to the key
    return group.tag_id ?? tagKey;
  }

  function getDisplayName(group: SpeciesMatchResult): string {
    return group.common_name ?? group.scientific_name;
  }

  function getSecondaryName(group: SpeciesMatchResult): string | undefined {
    return group.common_name ? group.scientific_name : undefined;
  }
</script>

<svelte:window onkeydown={nav.handleKeydown} />

<div class="flex flex-col gap-4">
  <!-- Filter bar (only show after search completes) -->
  {#if results !== null && !isSearching}
    <div class="flex flex-wrap items-center gap-4 rounded-lg border border-stone-200 bg-stone-50 p-3">
      <!-- Threshold slider -->
      <div class="flex items-center gap-2">
        <label for="rf-threshold" class="text-xs font-medium whitespace-nowrap text-stone-600">
          {m.search_threshold()} {Math.round(filterThreshold * 100)}%
        </label>
        <input
          id="rf-threshold"
          type="range"
          min="0"
          max="1"
          step="0.05"
          bind:value={filterThreshold}
          class="w-28 accent-primary-500"
          aria-label={m.search_threshold()}
        />
      </div>

      <!-- Max per species -->
      <div class="flex items-center gap-2">
        <label for="rf-max" class="text-xs font-medium whitespace-nowrap text-stone-600">
          {m.search_max_per_species()}
        </label>
        <input
          id="rf-max"
          type="number"
          min="1"
          max="200"
          bind:value={filterMaxPerSpecies}
          class="w-16 rounded-md border border-stone-300 bg-surface-card px-2 py-1 text-xs focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
          aria-label={m.search_max_per_species()}
        />
      </div>

      <!-- Summary -->
      <span class="text-xs text-stone-400">
        {m.search_results_total({ count: totalMatches.toString() })}
        &bull;
        {m.search_search_duration({ ms: searchDurationMs.toString() })}
      </span>

      <!-- Keyboard shortcuts hint -->
      <div class="ml-auto flex items-center gap-2 text-xs text-stone-400">
        <kbd class="rounded border border-stone-200 bg-surface-card px-1.5 py-0.5 font-mono text-xs">1</kbd> {m.detection_keyboard_solo()}
        <kbd class="rounded border border-stone-200 bg-surface-card px-1.5 py-0.5 font-mono text-xs">2</kbd> {m.detection_keyboard_dominant()}
        <kbd class="rounded border border-stone-200 bg-surface-card px-1.5 py-0.5 font-mono text-xs">3</kbd> {m.detection_keyboard_mixed()}
        <kbd class="rounded border border-stone-200 bg-surface-card px-1.5 py-0.5 font-mono text-xs">D</kbd> {m.vote_disagree_button()}
        <kbd class="rounded border border-stone-200 bg-surface-card px-1.5 py-0.5 font-mono text-xs">U</kbd> {m.vote_unsure_button()}
        <kbd class="rounded border border-stone-200 bg-surface-card px-1.5 py-0.5 font-mono text-xs">Space</kbd> {m.search_keyboard_play()}
        <kbd class="rounded border border-stone-200 bg-surface-card px-1.5 py-0.5 font-mono text-xs">&#8593;&#8595;</kbd> {m.search_keyboard_navigate()}
      </div>
    </div>
  {/if}

  {#if isSearching}
    <!-- Skeleton loading while search runs -->
    <div class="rounded-lg border border-card bg-surface-card shadow-sm">
      <div class="border-b border-card px-4 py-3">
        <div class="flex gap-2">
          {#each searchingSpecies as sp (sp.id)}
            <div class="h-8 w-24 animate-pulse rounded-md bg-stone-200"></div>
          {/each}
        </div>
      </div>
      <div class="grid grid-cols-2 gap-3 p-4 sm:grid-cols-3 lg:grid-cols-4">
        {#each { length: 8 } as _}
          <div class="animate-pulse overflow-hidden rounded-lg border border-stone-200 bg-surface-card shadow-sm">
            <div class="h-[120px] bg-stone-200"></div>
            <div class="flex flex-col gap-2 p-2.5">
              <div class="h-3 w-4/5 rounded bg-stone-100"></div>
              <div class="h-3 w-1/2 rounded bg-stone-100"></div>
              <div class="h-6 w-full rounded bg-stone-100"></div>
            </div>
          </div>
        {/each}
      </div>
    </div>
  {:else if results !== null}
    {#if speciesEntries.length === 0 || totalMatches === 0}
      <!-- No results at all -->
      <div class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-stone-200 py-16 text-center">
        <svg
          class="mx-auto mb-3 h-12 w-12 opacity-40 text-stone-400"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          stroke-width="1.5"
          aria-hidden="true"
        >
          <path stroke-linecap="round" stroke-linejoin="round" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
        </svg>
        <p class="font-medium text-stone-500">{m.search_results_no_matches()}</p>
        <p class="mt-1 text-sm text-stone-400">{m.search_results_no_matches_hint()}</p>
      </div>
    {:else}
      <div class="rounded-lg border border-card bg-surface-card shadow-sm">
        <!-- Species tabs -->
        <div class="flex flex-wrap gap-1 border-b border-card p-2">
          {#each speciesEntries as [key, group] (key)}
            {@const filteredCount = getFilteredCount(group)}
            <button
              type="button"
              class="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors
                {selectedTabKey === key
                  ? 'bg-primary-600 text-white shadow-sm'
                  : 'border border-stone-200 bg-stone-50 text-stone-700 hover:bg-stone-100'}"
              onclick={() => { selectedTabKey = key; nav.select(0); }}
            >
              <span class="max-w-[140px] truncate">{getDisplayName(group)}</span>
              <span
                class="rounded-full px-1.5 py-0.5 text-xs font-semibold
                  {selectedTabKey === key
                    ? 'bg-white/25 text-white'
                    : 'bg-primary-100 text-primary-800'}"
              >
                {filteredCount}
              </span>
            </button>
          {/each}
        </div>

        <!-- Selected species details + grid -->
        {#if selectedGroup !== null && selectedGroup !== undefined}
          <div class="p-4">
            <!-- Species name header -->
            <div class="mb-4">
              <h3 class="text-base font-semibold text-stone-900">{getDisplayName(selectedGroup)}</h3>
              {#if getSecondaryName(selectedGroup)}
                <p class="text-sm italic text-stone-400">{getSecondaryName(selectedGroup)}</p>
              {/if}
            </div>

            {#if filteredMatches.length === 0}
              <!-- No results above threshold -->
              <div class="flex flex-col items-center justify-center py-10 text-center">
                <svg class="mb-2 h-10 w-10 text-stone-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2a1 1 0 01-.293.707L13 13.414V19a1 1 0 01-.553.894l-4 2A1 1 0 017 21v-7.586L3.293 6.707A1 1 0 013 6V4z" />
                </svg>
                <p class="text-sm text-stone-500">{m.search_no_results_above_threshold()}</p>
              </div>
            {:else}
              <!-- Result card grid -->
              <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                {#each filteredMatches as result, i (result.embedding_id)}
                  <div bind:this={cardElements[i]}>
                    <SearchResultCard
                      {projectId}
                      {result}
                      {searchSessionId}
                      isSelected={i === nav.selectedIndex}
                      externalIsPlaying={nav.playingIndex === i && nav.isPlaying}
                      externalIsLoadingAudio={nav.playingIndex === i && nav.isLoadingAudio}
                      onPlayToggle={() => nav.togglePlay(i)}
                      voteSummary={voteSummaries[result.embedding_id] ?? null}
                      isVoting={mutatingId === result.embedding_id}
                      onAgree={(q) => handleAgree(result, q)}
                      onVote={(vote) => handleVote(result, vote)}
                      onRemoveVote={() => handleRemoveVote(result.embedding_id)}
                    />
                  </div>
                {/each}
              </div>
            {/if}
          </div>
        {/if}
      </div>
    {/if}
  {/if}
</div>
