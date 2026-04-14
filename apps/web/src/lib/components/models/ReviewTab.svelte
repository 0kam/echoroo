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

  import * as m from '$lib/paraglide/messages';
  import { createQuery, useQueryClient } from '@tanstack/svelte-query';
  import { getSamplingRounds, getSamplingRound, suggestNextSamples, trainCustomModel } from '$lib/api/custom-models';
  import type { SamplingRound } from '$lib/types/custom-model';
  import TrainingMeter from './TrainingMeter.svelte';
  import SeedSamplingView from './SeedSamplingView.svelte';
  import ALRoundView from './ALRoundView.svelte';

  interface Props {
    projectId: string;
    /** Custom model ID — required to query and display sampling rounds */
    modelId: string;
    /** Called when the user clicks "Train Custom Model" */
    onTrainRequest: () => void;
  }

  let { projectId, modelId, onTrainRequest }: Props = $props();

  const queryClient = useQueryClient();

  // ============================================
  // Queries
  // ============================================

  // Query sampling rounds when a model ID is available.
  // Re-fetches on window focus to pick up background job completions.
  const samplingRoundsQuery = $derived(
    createQuery({
      queryKey: ['sampling-rounds', projectId, modelId],
      queryFn: () => getSamplingRounds(projectId, modelId),
      enabled: true,
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
    !$samplingRoundsQuery.isLoading &&
    ($samplingRoundsQuery.data?.rounds?.length ?? 0) > 0
  );

  // Rounds sorted by round_number ascending for display
  const sortedRounds = $derived<SamplingRound[]>(
    ($samplingRoundsQuery.data?.rounds ?? []).slice().sort(
      (a, b) => a.round_number - b.round_number
    )
  );

  // Accordion collapse state: only one round can be expanded at a time.
  // The latest round starts expanded by default.
  let expandedRoundId = $state<string | null>(null);

  $effect(() => {
    const rounds = sortedRounds;
    if (rounds.length === 0) {
      if (expandedRoundId !== null) expandedRoundId = null;
      return;
    }
    // Auto-expand only when there is no expanded round, or the expanded round
    // no longer exists (e.g. data was refreshed). Never override user's collapse.
    if (expandedRoundId === null || !rounds.some((r) => r.id === expandedRoundId)) {
      const latest = rounds[rounds.length - 1];
      if (latest) {
        expandedRoundId = latest.id;
        fetchRoundDetail(latest.id);
      }
    }
  });

  // Cache of fully-loaded round details (with items populated).
  // The list endpoint returns items=[], so we fetch the detail on expand.
  let roundDetailCache = $state<Record<string, SamplingRound>>({});
  let roundDetailLoading = $state<Set<string>>(new Set());

  async function fetchRoundDetail(roundId: string, force = false) {
    if (!modelId) return;
    if (!force && (roundDetailCache[roundId] || roundDetailLoading.has(roundId))) return;
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

  // Rounds merged with detail cache, so TrainingMeter sees populated items
  // without requiring each round to be expanded first.
  const sortedRoundsWithItems = $derived<SamplingRound[]>(
    sortedRounds.map(getRoundWithItems)
  );

  // Auto-fetch detail for all rounds so TrainingMeter gets accurate counts.
  $effect(() => {
    for (const round of sortedRounds) {
      if (!roundDetailCache[round.id] && !roundDetailLoading.has(round.id)) {
        fetchRoundDetail(round.id);
      }
    }
  });

  function toggleRound(roundId: string) {
    if (expandedRoundId === roundId) {
      expandedRoundId = null;
    } else {
      expandedRoundId = roundId;
      // Fetch detail when expanding (items are needed for review)
      fetchRoundDetail(roundId);
    }
  }

  // ============================================
  // "Suggest Next Samples" state
  // ============================================

  let isSuggestingNextSamples = $state(false);
  let suggestError = $state<string | null>(null);

  /**
   * Whether the seed round has been labeled enough to allow an AL round.
   * Backend requires at least 15 confirmed + 15 rejected across completed rounds.
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
    return totalConfirmed >= 15 && totalRejected >= 15;
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

  async function handleTrainRequest() {
    // Trigger model training directly (model ID is always provided).
    try {
      await trainCustomModel(projectId, modelId);
      await queryClient.invalidateQueries({
        queryKey: ['sampling-rounds', projectId, modelId],
      });
      await queryClient.invalidateQueries({
        queryKey: ['custom-models', projectId],
      });
      await queryClient.invalidateQueries({
        queryKey: ['custom-model', projectId, modelId],
      });
    } catch (err) {
      console.error('Failed to start training:', err);
    }
    // Notify parent after all invalidations so it can react to updated state
    onTrainRequest();
  }
</script>

<div class="min-h-0">

  <!-- ============================================
       Review content: sampling rounds accordion
  ============================================ -->
  <div class="min-w-0 space-y-4">

    <!-- ========================================
         Loading state
    ======================================== -->
    {#if $samplingRoundsQuery.isLoading}
      <div class="flex items-center gap-2 py-8 text-sm text-stone-400">
        <svg class="h-5 w-5 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
        {m.nav_loading()}
      </div>

    <!-- ========================================
         Empty state: no rounds yet (seed sampling not triggered or in progress)
    ======================================== -->
    {:else if sortedRounds.length === 0}
      <div class="flex h-32 items-center justify-center rounded-xl border-2 border-dashed border-stone-200 dark:border-stone-700">
        <p class="text-sm text-stone-400">Seed sampling in progress...</p>
      </div>

    <!-- ========================================
         Sampling rounds view
         Renders all rounds in accordion order: seed first, then AL rounds.
    ======================================== -->
    {:else if hasSamplingRounds && $samplingRoundsQuery.data}
      <div class="space-y-3">

        <!-- Training meter from round data -->
        <TrainingMeter
          agreeCount={0}
          disagreeCount={0}
          totalCount={0}
          samplingRounds={sortedRoundsWithItems}
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
              aria-expanded={expandedRoundId === round.id}
            >
              <!-- Chevron icon -->
              <svg
                class="h-4 w-4 shrink-0 text-stone-400 transition-transform duration-200
                  {expandedRoundId === round.id ? 'rotate-90' : ''}"
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
            {#if expandedRoundId === round.id}
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
                    {modelId}
                    round={getRoundWithItems(round)}
                    onVoteChanged={() => {
                      // Refetch round detail to update confirmed/rejected counts in header.
                      // Don't delete cache first — that causes card re-mounts and spectrogram re-fetches.
                      // fetchRoundDetail with force=true overwrites the cache entry atomically.
                      fetchRoundDetail(round.id, true);
                      queryClient.invalidateQueries({ queryKey: ['sampling-rounds', projectId, modelId] });
                    }}
                  />
                {:else}
                  <ALRoundView
                    {projectId}
                    {modelId}
                    round={getRoundWithItems(round)}
                    onVoteChanged={() => {
                      // Refetch round detail to update confirmed/rejected counts in header.
                      // Don't delete cache first — that causes card re-mounts and spectrogram re-fetches.
                      fetchRoundDetail(round.id, true);
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

    {/if}
  </div>
</div>
