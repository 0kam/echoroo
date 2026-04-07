<script lang="ts">
  /**
   * ReviewTab - Main container for the Models page Review tab.
   *
   * Workflow:
   * 1. Shows a list of completed search sessions (session picker on the left).
   * 2. When a session is selected, loads its full detail and renders results
   *    grouped by similarity band in horizontal SimilarityLane rows.
   * 3. TrainingMeter at the top tracks labeling progress and triggers the
   *    "Create Model" dialog when minimum requirements are met.
   *
   * Data flow:
   * - listSearchSessions() → session list
   * - getSearchSession()   → full results with injected annotation_id & review_status
   * - castAnnotationVote() / deleteAnnotationVote() → vote mutations
   * - createAnnotationFromSearch() → creates annotation on-the-fly for unreviewed results
   */

  import { onDestroy } from 'svelte';
  import * as m from '$lib/paraglide/messages';
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { getSearchSession, listSearchSessions, createAnnotationFromSearch } from '$lib/api/search';
  import { castAnnotationVote, deleteAnnotationVote } from '$lib/api/votes';
  import { createReviewNavigation } from '$lib/utils/reviewNavigation.svelte';
  import type { VoteSummary, VoteValue, SignalQuality } from '$lib/types/detection';
  import type { SearchSessionListItem } from '$lib/types/search';
  import TrainingMeter from './TrainingMeter.svelte';
  import SimilarityLane, { type LaneResult } from './SimilarityLane.svelte';

  interface Props {
    projectId: string;
    /** Called when the user clicks "Train Custom Model" — opens the create dialog */
    onTrainRequest: (preselectedSessionId: string) => void;
  }

  let { projectId, onTrainRequest }: Props = $props();

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
    {#if !selectedSessionId}
      <!-- Empty state -->
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
