<script lang="ts">
  /**
   * ReviewTab - Main container for the Models page Review tab.
   *
   * Workflow:
   * 1. When a modelId is provided and sampling rounds exist, shows an
   *    accordion of all rounds (seed first, then active-learning rounds).
   *    A "Suggest Next Samples" button appears after the last completed seed
   *    round to trigger the next active-learning round.
   * 2. Otherwise shows a list of completed search sessions (session picker
   *    on the left) and renders results grouped by similarity band.
   * 3. TrainingMeter at the top tracks labeling progress and triggers the
   *    "Create Model" dialog when minimum requirements are met.
   *
   * Data flow:
   * - listSearchSessions() → session list
   * - getSearchSession()   → full results with injected annotation_id & review_status
   * - castAnnotationVote() / deleteAnnotationVote() → vote mutations
   * - createAnnotationFromSearch() → creates annotation on-the-fly for unreviewed results
   * - getSamplingRounds() → all rounds (seed + AL)
   * - suggestNextSamples() → trigger new AL round
   */

  import { onDestroy } from 'svelte';
  import * as m from '$lib/paraglide/messages';
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { getSearchSession, listSearchSessions, createAnnotationFromSearch } from '$lib/api/search';
  import { castAnnotationVote, deleteAnnotationVote } from '$lib/api/votes';
  import { getSamplingRounds, getSamplingRound, suggestNextSamples } from '$lib/api/custom-models';
  import { createReviewNavigation } from '$lib/utils/reviewNavigation.svelte';
  import type { VoteSummary, VoteValue, SignalQuality } from '$lib/types/detection';
  import type { SamplingRound } from '$lib/types/custom-model';
  import type { SearchSessionListItem } from '$lib/types/search';
  import TrainingMeter from './TrainingMeter.svelte';
  import SimilarityLane, { type LaneResult } from './SimilarityLane.svelte';
  import SeedSamplingView from './SeedSamplingView.svelte';
  import ALRoundView from './ALRoundView.svelte';

  interface Props {
    projectId: string;
    /** Custom model ID — when provided, sampling rounds are queried and shown if available */
    modelId?: string;
    /** Called when the user clicks "Train Custom Model" — opens the create dialog */
    onTrainRequest: (preselectedSessionId: string) => void;
  }

  let { projectId, modelId, onTrainRequest }: Props = $props();

  const queryClient = useQueryClient();

  // ============================================
  // Session selection state
  // ============================================

  let selectedSessionId = $state<string | null>(null);

  // ============================================
  // Per-card vote summary cache (keyed by embeddingId)
  // ============================================

  let voteSummaryCache = $state<Record<string, VoteSummary>>({});

  // Track annotation IDs discovered from getSearchSession (keyed by embeddingId)
  let annotationIdMap = $state<Record<string, string>>({});

  // Mutation loading set (keyed by embeddingId)
  let loadingIds = $state<Set<string>>(new Set());

  // ============================================
  // Queries
  // ============================================

  const sessionsQuery = $derived(
    createQuery({
      queryKey: ['search-sessions', projectId, 'review-tab'],
      queryFn: () => listSearchSessions(projectId, 100, 0),
      enabled: !!projectId,
    })
  );

  const sessionDetailQuery = $derived(
    createQuery({
      queryKey: ['search-session', projectId, selectedSessionId],
      queryFn: () =>
        selectedSessionId
          ? getSearchSession(projectId, selectedSessionId)
          : Promise.reject('No session selected'),
      enabled: !!selectedSessionId,
      refetchOnWindowFocus: false,
    })
  );

  // Query sampling rounds when a model ID is available.
  // Re-fetches on window focus to pick up background job completions.
  const samplingRoundsQuery = $derived(
    createQuery({
      queryKey: ['sampling-rounds', projectId, modelId],
      queryFn: () =>
        modelId
          ? getSamplingRounds(projectId, modelId)
          : Promise.reject('No model ID'),
      enabled: !!modelId,
      refetchOnWindowFocus: true,
      // Poll while any round is still pending/running
      refetchInterval: (query) => {
        const rounds = query.state.data?.rounds ?? [];
        const hasPendingRound = rounds.some(
          (r) => r.status === 'pending' || r.status === 'running'
        );
        return hasPendingRound ? 3000 : false;
      },
    })
  );

  const hasSamplingRounds = $derived(
    !!modelId &&
    !$samplingRoundsQuery.isLoading &&
    ($samplingRoundsQuery.data?.rounds?.length ?? 0) > 0
  );

  // Rounds sorted by round_number ascending for display
  const sortedRounds = $derived<SamplingRound[]>(
    ($samplingRoundsQuery.data?.rounds ?? []).slice().sort(
      (a, b) => a.round_number - b.round_number
    )
  );

  // Accordion collapse state: round id → expanded boolean.
  // The latest round starts expanded by default.
  let expandedRoundIds = $state<Set<string>>(new Set());

  $effect(() => {
    const rounds = sortedRounds;
    if (rounds.length === 0) return;
    const latestRound = rounds[rounds.length - 1];
    if (!latestRound) return;
    if (!expandedRoundIds.has(latestRound.id)) {
      expandedRoundIds = new Set([...expandedRoundIds, latestRound.id]);
      // Fetch detail for the initially expanded round
      fetchRoundDetail(latestRound.id);
    }
  });

  // Cache of fully-loaded round details (with items populated).
  // The list endpoint returns items=[], so we fetch the detail on expand.
  let roundDetailCache = $state<Record<string, SamplingRound>>({});
  let roundDetailLoading = $state<Set<string>>(new Set());

  async function fetchRoundDetail(roundId: string) {
    if (!modelId || roundDetailCache[roundId] || roundDetailLoading.has(roundId)) return;
    roundDetailLoading = new Set([...roundDetailLoading, roundId]);
    try {
      const detail = await getSamplingRound(projectId, modelId, roundId);
      roundDetailCache = { ...roundDetailCache, [roundId]: detail };
    } catch (err) {
      console.error('Failed to fetch round detail:', err);
    } finally {
      roundDetailLoading = new Set([...roundDetailLoading].filter((id) => id !== roundId));
    }
  }

  /** Get the round data with items: prefer the detail cache, fall back to list entry. */
  function getRoundWithItems(round: SamplingRound): SamplingRound {
    return roundDetailCache[round.id] ?? round;
  }

  function toggleRound(roundId: string) {
    const next = new Set(expandedRoundIds);
    if (next.has(roundId)) {
      next.delete(roundId);
    } else {
      next.add(roundId);
      // Fetch detail when expanding (items are needed)
      fetchRoundDetail(roundId);
    }
    expandedRoundIds = next;
  }

  // ============================================
  // "Suggest Next Samples" state
  // ============================================

  let isSuggestingNextSamples = $state(false);
  let suggestError = $state<string | null>(null);

  /**
   * Whether the seed round has been labeled enough to allow an AL round.
   * Backend requires at least 5 confirmed + 5 rejected across completed rounds.
   */
  const seedRoundReady = $derived.by(() => {
    const completedRounds = sortedRounds.filter((r) => r.status === 'completed');
    if (completedRounds.length === 0) return false;
    let totalConfirmed = 0;
    let totalRejected = 0;
    for (const r of completedRounds) {
      const detailed = getRoundWithItems(r);
      totalConfirmed += detailed.items.filter((it) => it.review_status === 'confirmed').length;
      totalRejected += detailed.items.filter((it) => it.review_status === 'rejected').length;
    }
    return totalConfirmed >= 5 && totalRejected >= 5;
  });

  /** True when the last round is still pending/running (no new AL round allowed yet). */
  const lastRoundBusy = $derived.by(() => {
    if (sortedRounds.length === 0) return false;
    const last = sortedRounds[sortedRounds.length - 1];
    if (!last) return false;
    return last.status === 'pending' || last.status === 'running';
  });

  async function handleSuggestNextSamples() {
    if (!modelId) return;
    isSuggestingNextSamples = true;
    suggestError = null;
    try {
      await suggestNextSamples(projectId, modelId);
      // Invalidate so the new round appears immediately
      await queryClient.invalidateQueries({ queryKey: ['sampling-rounds', projectId, modelId] });
    } catch (err) {
      console.error('suggestNextSamples error:', err);
      suggestError = err instanceof Error ? err.message : 'Failed to suggest samples';
    } finally {
      isSuggestingNextSamples = false;
    }
  }

  // ============================================
  // Sync annotation IDs from loaded session data into the mutable map
  // ============================================

  $effect(() => {
    const session = $sessionDetailQuery.data;
    if (!session?.results?.results) return;

    const updates: Record<string, string> = {};
    for (const [_speciesKey, speciesData] of Object.entries(session.results.results)) {
      const matches = (speciesData.matches as unknown[]).filter(
        (m): m is Record<string, unknown> => typeof m === 'object' && m !== null
      );
      for (const match of matches) {
        const embeddingId = String(match['embedding_id'] ?? '');
        const rawAnnotationId = match['annotation_id'] as string | undefined;
        if (embeddingId && rawAnnotationId && !annotationIdMap[embeddingId]) {
          updates[embeddingId] = rawAnnotationId;
        }
      }
    }
    if (Object.keys(updates).length > 0) {
      annotationIdMap = { ...annotationIdMap, ...updates };
    }
  });

  // ============================================
  // Derived: flatten all results into LaneResult[]
  // ============================================

  /** All results from the selected session, enriched with vote summaries. */
  const allLaneResults = $derived.by<LaneResult[]>(() => {
    const session = $sessionDetailQuery.data;
    if (!session?.results?.results) return [];

    const items: LaneResult[] = [];
    for (const [_speciesKey, speciesData] of Object.entries(session.results.results)) {
      // The backend injects annotation_id and review_status into match objects at runtime,
      // but the TypeScript type for SimilarityResult does not include those fields.
      // We cast to unknown[] to allow dynamic field access.
      const matches = (speciesData.matches as unknown[]).filter(
        (m): m is Record<string, unknown> => typeof m === 'object' && m !== null
      );

      for (const match of matches) {
        const embeddingId = String(match['embedding_id'] ?? '');
        if (!embeddingId) continue;

        // annotation_id is injected server-side for results that already have an annotation
        const rawAnnotationId = match['annotation_id'] as string | undefined;

        items.push({
          embeddingId,
          annotationId: annotationIdMap[embeddingId] ?? rawAnnotationId ?? null,
          recordingId: String(match['recording_id'] ?? ''),
          recordingName: String(match['recording_filename'] ?? ''),
          startTime: Number(match['start_time'] ?? 0),
          endTime: Number(match['end_time'] ?? 0),
          similarity: Number(match['similarity'] ?? 0),
          voteSummary: voteSummaryCache[embeddingId] ?? null,
        });
      }
    }

    // Sort descending by similarity
    return items.sort((a, b) => b.similarity - a.similarity);
  });

  // ============================================
  // Stratified lanes (similarity bands)
  // ============================================

  const BANDS: { label: string; min: number; max: number }[] = [
    { label: '90%+', min: 0.9, max: 1.0 },
    { label: '80-90%', min: 0.8, max: 0.9 },
    { label: '70-80%', min: 0.7, max: 0.8 },
    { label: '60-70%', min: 0.6, max: 0.7 },
    { label: '50-60%', min: 0.5, max: 0.6 },
    { label: '<50%', min: 0.0, max: 0.5 },
  ];

  /** Compute results per band, also tracking each band's index offset into the flat array. */
  const laneBands = $derived.by(() => {
    const results = allLaneResults;
    let offset = 0;
    return BANDS.map((band) => {
      const bandResults = results.filter(
        (r) => r.similarity >= band.min && r.similarity < band.max
      );
      const currentOffset = offset;
      offset += bandResults.length;
      return {
        ...band,
        results: bandResults,
        indexOffset: currentOffset,
      };
    }).filter((band) => band.results.length > 0);
  });

  // ============================================
  // Training meter counts
  // ============================================

  const agreeCount = $derived(
    allLaneResults.filter((r) => r.voteSummary?.user_vote === 'agree').length
  );

  const disagreeCount = $derived(
    allLaneResults.filter((r) => r.voteSummary?.user_vote === 'disagree').length
  );

  // ============================================
  // Keyboard navigation
  // ============================================

  let cardElements = $state<(HTMLElement | null)[]>([]);

  const nav = createReviewNavigation({
    projectId,
    itemCount: () => allLaneResults.length,
    onConfirm: () => {
      /* handled by card-level ReviewActions */
    },
    onReject: () => {
      /* handled by card-level ReviewActions */
    },
    getPlaybackInfo: (i) => {
      const item = allLaneResults[i];
      if (!item) return null;
      return {
        recordingId: item.recordingId,
        startTime: item.startTime,
        endTime: item.endTime,
      };
    },
    getElement: (i) => cardElements[i] ?? null,
  });

  onDestroy(() => {
    nav.cleanup();
  });

  // ============================================
  // Mutations: vote helpers
  // ============================================

  async function handleVote(
    embeddingId: string,
    annotationId: string | null,
    vote: VoteValue,
    signalQuality?: SignalQuality
  ) {
    loadingIds = new Set([...loadingIds, embeddingId]);

    try {
      let finalAnnotationId = annotationId ?? annotationIdMap[embeddingId] ?? null;

      // If no annotation exists yet, create one first (unreviewed state)
      if (!finalAnnotationId) {
        const session = $sessionDetailQuery.data;
        const result = allLaneResults.find((r) => r.embeddingId === embeddingId);
        if (!result || !session) return;

        // Find species tag_id for this embedding from the session data
        let tagId: string | null = null;
        if (session.results?.results) {
          for (const [_key, speciesData] of Object.entries(session.results.results)) {
            const matches = (speciesData.matches as unknown[]).filter(
              (x): x is Record<string, unknown> => typeof x === 'object' && x !== null
            );
            const found = matches.find(
              (x) => String(x['embedding_id']) === embeddingId
            );
            if (found) {
              tagId = speciesData.tag_id ?? null;
              break;
            }
          }
        }

        const created = await createAnnotationFromSearch(projectId, {
          recording_id: result.recordingId,
          tag_id: tagId ?? '',
          start_time: result.startTime,
          end_time: result.endTime,
          confidence: result.similarity,
          review_status: 'unreviewed',
          source: 'similarity_search',
          search_session_id: session.id,
        }) as { id?: string };

        if (created?.id) {
          finalAnnotationId = created.id;
          annotationIdMap = { ...annotationIdMap, [embeddingId]: created.id };
        }
      }

      if (!finalAnnotationId) return;

      const summary = await castAnnotationVote(
        projectId,
        finalAnnotationId,
        vote,
        signalQuality
      );
      voteSummaryCache = { ...voteSummaryCache, [embeddingId]: summary };
    } catch (err) {
      console.error('Vote error:', err);
    } finally {
      loadingIds = new Set([...loadingIds].filter((id) => id !== embeddingId));
    }
  }

  async function handleRemoveVote(embeddingId: string, annotationId: string | null) {
    const finalAnnotationId = annotationId ?? annotationIdMap[embeddingId] ?? null;
    if (!finalAnnotationId) return;

    loadingIds = new Set([...loadingIds, embeddingId]);
    try {
      const summary = await deleteAnnotationVote(projectId, finalAnnotationId);
      voteSummaryCache = { ...voteSummaryCache, [embeddingId]: summary };
    } catch (err) {
      console.error('Remove vote error:', err);
    } finally {
      loadingIds = new Set([...loadingIds].filter((id) => id !== embeddingId));
    }
  }

  async function handleMarkAllPositive(results: LaneResult[]) {
    for (const result of results) {
      if (result.voteSummary?.user_vote === 'agree') continue;
      await handleVote(result.embeddingId, result.annotationId, 'agree', 'dominant');
    }
  }

  async function handleMarkAllNegative(results: LaneResult[]) {
    for (const result of results) {
      if (result.voteSummary?.user_vote === 'disagree') continue;
      await handleVote(result.embeddingId, result.annotationId, 'disagree');
    }
  }

  // ============================================
  // Session picker helpers
  // ============================================

  function formatSessionDate(iso: string): string {
    return new Date(iso).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  }

  function getSessionSpecies(session: SearchSessionListItem): string {
    if (!session.species_config?.length) return '—';
    return session.species_config
      .map((s) => s.scientific_name)
      .join(', ');
  }

  function handleSelectSession(id: string) {
    if (selectedSessionId === id) return;
    // Clear per-session state
    voteSummaryCache = {};
    annotationIdMap = {};
    loadingIds = new Set();
    selectedSessionId = id;
    nav.select(0);
  }

  function handleTrainRequest() {
    if (selectedSessionId) {
      onTrainRequest(selectedSessionId);
    }
  }
</script>

<div class="flex gap-6 min-h-0">
  <!-- ============================================
       Left column: session picker
  ============================================ -->
  <div class="w-64 shrink-0 space-y-2">
    <h2 class="text-sm font-semibold text-stone-600 uppercase tracking-wider">
      {m.models_review_sessions_title()}
    </h2>

    {#if $sessionsQuery.isLoading}
      <div class="flex items-center gap-2 py-4 text-sm text-stone-400">
        <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
        {m.nav_loading()}
      </div>

    {:else if $sessionsQuery.isError}
      <p class="text-sm text-danger">{m.models_review_sessions_error()}</p>

    {:else if $sessionsQuery.data && $sessionsQuery.data.sessions.length === 0}
      <div class="rounded-lg border border-dashed border-stone-200 p-4 text-center">
        <p class="text-sm text-stone-400">{m.models_review_no_sessions()}</p>
      </div>

    {:else if $sessionsQuery.data}
      <div class="space-y-1 max-h-[calc(100vh-220px)] overflow-y-auto pr-1">
        {#each $sessionsQuery.data.sessions.filter((s) => s.status === 'completed') as session (session.id)}
          <button
            type="button"
            class="w-full text-left rounded-lg border px-3 py-2.5 transition-colors text-sm focus:outline-none focus:ring-2 focus:ring-primary-500
              {selectedSessionId === session.id
                ? 'border-primary-300 bg-primary-50 dark:border-primary-700 dark:bg-primary-950/20'
                : 'border-transparent bg-stone-50 hover:bg-stone-100 dark:bg-stone-800/50 dark:hover:bg-stone-800'}"
            onclick={() => handleSelectSession(session.id)}
          >
            <p class="font-medium text-stone-800 dark:text-stone-200 truncate">
              {session.name ?? session.id.slice(0, 12)}
            </p>
            <p class="mt-0.5 text-xs text-stone-400 truncate" title={getSessionSpecies(session)}>
              {getSessionSpecies(session)}
            </p>
            <p class="mt-0.5 text-xs text-stone-400">
              {formatSessionDate(session.created_at)}
              &middot; {session.result_count} {m.models_review_results_count()}
            </p>
          </button>
        {/each}
      </div>
    {/if}
  </div>

  <!-- ============================================
       Right column: review content
  ============================================ -->
  <div class="flex-1 min-w-0 space-y-4">

    <!-- ========================================
         Sampling rounds view (takes priority when rounds exist)
         Renders all rounds in accordion order: seed first, then AL rounds.
    ======================================== -->
    {#if hasSamplingRounds && $samplingRoundsQuery.data}
      <div class="space-y-3">

        <!-- Training meter from round data -->
        <TrainingMeter
          agreeCount={0}
          disagreeCount={0}
          totalCount={0}
          samplingRounds={sortedRounds}
          onTrainRequest={handleTrainRequest}
        />

        <!-- Accordion of rounds -->
        {#each sortedRounds as round (round.id)}
          <div class="rounded-xl border border-card bg-surface-card shadow-sm overflow-hidden">
            <!-- Accordion header (always visible) -->
            <button
              type="button"
              class="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-stone-50 dark:hover:bg-stone-800/40 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-primary-500"
              onclick={() => toggleRound(round.id)}
              aria-expanded={expandedRoundIds.has(round.id)}
            >
              <!-- Chevron icon -->
              <svg
                class="h-4 w-4 shrink-0 text-stone-400 transition-transform duration-200
                  {expandedRoundIds.has(round.id) ? 'rotate-90' : ''}"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                aria-hidden="true"
              >
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
              </svg>

              <!-- Round type badge + round label -->
              <span class="inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium
                {round.round_type === 'seed'
                  ? 'border-violet-200 bg-violet-50 text-violet-700 dark:border-violet-800 dark:bg-violet-950/30 dark:text-violet-300'
                  : 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-950/30 dark:text-blue-300'}">
                {round.round_type === 'seed'
                  ? m.models_seed_round_label({ number: round.round_number })
                  : m.models_al_round_label({ number: round.round_number })}
              </span>

              <!-- Status badge -->
              <span class="inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium
                {round.status === 'completed'
                  ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-300'
                  : round.status === 'failed'
                    ? 'border-danger/40 bg-danger-light text-danger'
                    : round.status === 'running'
                      ? 'border-info/40 bg-info-light text-info'
                      : 'border-stone-200 bg-stone-50 text-stone-500 dark:border-stone-700 dark:bg-stone-800 dark:text-stone-400'}">
                {round.status}
              </span>

              <span class="text-xs text-stone-400">
                {round.sample_count} {m.models_seed_samples_count()}
              </span>

              <!-- Inline progress: confirmed / rejected -->
              {#if round.status === 'completed'}
                {@const detailedRound = getRoundWithItems(round)}
                {@const confirmedCount = detailedRound.items.filter((it) => it.review_status === 'confirmed').length}
                {@const rejectedCount = detailedRound.items.filter((it) => it.review_status === 'rejected').length}
                <span class="ml-auto text-xs text-stone-400">
                  <span class="text-success">{confirmedCount} {m.models_seed_confirmed()}</span>
                  &middot;
                  <span class="text-danger">{rejectedCount} {m.models_seed_rejected()}</span>
                </span>
              {:else if round.status === 'pending' || round.status === 'running'}
                <span class="ml-auto flex items-center gap-1 text-xs text-stone-400">
                  <svg class="h-3 w-3 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                  </svg>
                  {round.round_type === 'active_learning'
                    ? m.models_suggest_samples_running()
                    : m.models_seed_round_processing()}
                </span>
              {/if}
            </button>

            <!-- Accordion body (collapsible) -->
            {#if expandedRoundIds.has(round.id)}
              <div class="border-t border-stone-100 dark:border-stone-800 px-4 py-4">
                {#if roundDetailLoading.has(round.id)}
                  <div class="flex items-center gap-2 py-4 text-sm text-stone-400">
                    <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                    </svg>
                    {m.nav_loading()}
                  </div>
                {:else if round.round_type === 'seed'}
                  <SeedSamplingView
                    {projectId}
                    modelId={modelId ?? ''}
                    round={getRoundWithItems(round)}
                    onVoteChanged={() => {
                      /* Invalidate to refresh confirmed/rejected counts in header */
                      delete roundDetailCache[round.id];
                      roundDetailCache = { ...roundDetailCache };
                      fetchRoundDetail(round.id);
                      queryClient.invalidateQueries({ queryKey: ['sampling-rounds', projectId, modelId] });
                    }}
                  />
                {:else}
                  <ALRoundView
                    {projectId}
                    modelId={modelId ?? ''}
                    round={getRoundWithItems(round)}
                    onVoteChanged={() => {
                      delete roundDetailCache[round.id];
                      roundDetailCache = { ...roundDetailCache };
                      fetchRoundDetail(round.id);
                      queryClient.invalidateQueries({ queryKey: ['sampling-rounds', projectId, modelId] });
                    }}
                  />
                {/if}
              </div>
            {/if}
          </div>
        {/each}

        <!-- "Suggest Next Samples" button (shown after seed round is labeled) -->
        {#if seedRoundReady && !lastRoundBusy}
          <div class="flex flex-col items-start gap-2">
            {#if suggestError}
              <p class="text-xs text-danger">{suggestError}</p>
            {/if}
            <button
              type="button"
              class="inline-flex items-center gap-2 rounded-lg border border-primary-300 bg-primary-50 px-4 py-2 text-sm font-medium text-primary-700 shadow-sm transition-colors hover:bg-primary-100 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 dark:border-primary-700 dark:bg-primary-950/20 dark:text-primary-400 dark:hover:bg-primary-950/40"
              disabled={isSuggestingNextSamples}
              onclick={handleSuggestNextSamples}
            >
              {#if isSuggestingNextSamples}
                <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                </svg>
                {m.models_suggest_samples_running()}
              {:else}
                <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.347.347a3.001 3.001 0 01-.468 3.525L12 20.5l-2.626-2.626a3.001 3.001 0 01-.468-3.525l-.347-.347z" />
                </svg>
                {m.models_suggest_samples()}
              {/if}
            </button>
          </div>
        {/if}

      </div>

    {:else if !selectedSessionId}
      <!-- Empty state: no rounds and no session selected -->
      <div class="flex h-64 items-center justify-center rounded-xl border-2 border-dashed border-stone-200 dark:border-stone-700">
        <div class="text-center">
          <svg class="mx-auto h-10 w-10 text-stone-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
          </svg>
          <p class="mt-3 text-sm text-stone-400">{m.models_review_select_session_hint()}</p>
        </div>
      </div>

    {:else if $sessionDetailQuery.isLoading}
      <div class="flex items-center gap-2 py-8 text-sm text-stone-400">
        <svg class="h-5 w-5 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
        {m.nav_loading()}
      </div>

    {:else if $sessionDetailQuery.isError}
      <p class="text-sm text-danger">{m.models_review_session_load_error()}</p>

    {:else if $sessionDetailQuery.data}
      {@const session = $sessionDetailQuery.data}
      {@const totalCount = allLaneResults.length}

      <!-- Session title -->
      <div>
        <h2 class="text-base font-semibold text-stone-800 dark:text-stone-200">
          {session.name ?? session.id.slice(0, 12)}
        </h2>
        <p class="text-xs text-stone-400">
          {formatSessionDate(session.created_at)}
          &middot; {session.model_name}
          &middot; {totalCount} {m.models_review_results_count()}
        </p>
      </div>

      <!-- Training meter -->
      <TrainingMeter
        agreeCount={agreeCount}
        disagreeCount={disagreeCount}
        totalCount={totalCount}
        onTrainRequest={handleTrainRequest}
      />

      <!-- Keyboard shortcut hint -->
      <p class="text-xs text-stone-400">
        {m.models_review_keyboard_hint()}
      </p>

      <!-- Stratified lanes -->
      {#if laneBands.length === 0}
        <div class="rounded-lg border border-dashed border-stone-200 p-8 text-center dark:border-stone-700">
          <p class="text-sm text-stone-400">{m.models_review_no_results()}</p>
        </div>
      {:else}
        <div class="space-y-6">
          {#each laneBands as band (band.label)}
            <SimilarityLane
              {projectId}
              bandLabel={band.label}
              results={band.results}
              {loadingIds}
              selectedIndex={nav.selectedIndex}
              indexOffset={band.indexOffset}
              onVote={handleVote}
              onRemoveVote={handleRemoveVote}
              onMarkAllPositive={handleMarkAllPositive}
              onMarkAllNegative={handleMarkAllNegative}
              {cardElements}
            />
          {/each}
        </div>
      {/if}
    {/if}
  </div>
</div>
