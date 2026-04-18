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
  import { untrack } from 'svelte';
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
    /**
     * When true, the model has already been trained at least once.
     * The training button relabels to "Retrain" to reflect the retraining
     * semantics used during the active-learning loop.
     */
    isTrained?: boolean;
  }

  let { projectId, modelId, onTrainRequest, isTrained = false }: Props = $props();

  // Minimum confirmed + rejected labels required to dispatch an active-learning
  // round. Intentionally lower than the training threshold (see TrainingMeter)
  // so users can request more samples when the seed round is unbalanced and a
  // full 15/15 training set is not yet reachable. Must stay in sync with the
  // backend constant `_MIN_LABELS_FOR_AL_ROUND` in services/custom_model.py.
  const MIN_LABELS_FOR_AL_ROUND = 5;

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

  // Tracks the number of rounds seen during the previous $effect run so we can
  // detect when a brand-new round appears (e.g. an AL round just finished
  // dispatching) and auto-switch the accordion to it.
  let prevRoundCount = 0;

  $effect(() => {
    const rounds = sortedRounds;
    if (rounds.length === 0) {
      if (expandedRoundId !== null) expandedRoundId = null;
      untrack(() => {
        prevRoundCount = 0;
      });
      return;
    }
    const latest = rounds[rounds.length - 1];
    // Read prevRoundCount inside untrack so writing to it later does not
    // re-trigger this effect.
    const prev = untrack(() => prevRoundCount);
    if (rounds.length > prev && prev > 0 && latest) {
      // A new round appeared — auto-switch the accordion to it.
      expandedRoundId = latest.id;
      fetchRoundDetail(latest.id);
    } else if (
      latest &&
      (expandedRoundId === null || !rounds.some((r) => r.id === expandedRoundId))
    ) {
      // Fallback: no expanded round yet, or the expanded round no longer exists.
      expandedRoundId = latest.id;
      fetchRoundDetail(latest.id);
    }
    untrack(() => {
      prevRoundCount = rounds.length;
    });
  });

  // Cache of fully-loaded round details (with items populated).
  // The list endpoint returns items=[], so we fetch the detail on expand.
  let roundDetailCache = $state<Record<string, SamplingRound>>({});
  let roundDetailLoading = $state<Set<string>>(new Set());

  async function fetchRoundDetail(roundId: string, force = false, silent = false) {
    if (!modelId) return;
    if (!force && (roundDetailCache[roundId] || roundDetailLoading.has(roundId))) return;
    // When silent, skip loading-state updates so the accordion body does not
    // unmount/remount the inner view (preserves scroll position and local state).
    if (!silent) {
      roundDetailLoading = new Set([...roundDetailLoading, roundId]);
    }
    try {
      const detail = await getSamplingRound(projectId, modelId, roundId);
      roundDetailCache = { ...roundDetailCache, [roundId]: detail };
    } catch (err) {
      console.error('Failed to fetch round detail:', err);
    } finally {
      if (!silent) {
        roundDetailLoading = new Set([...roundDetailLoading].filter((id) => id !== roundId));
      }
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

  // When the list query picks up a status change (e.g. running → completed),
  // force-refresh the detail cache so the UI reflects the new status immediately.
  // Silent mode prevents the accordion body from remounting during background polling.
  $effect(() => {
    const rounds = $samplingRoundsQuery.data?.rounds ?? [];
    untrack(() => {
      for (const round of rounds) {
        const cached = roundDetailCache[round.id];
        if (cached && cached.status !== round.status) {
          fetchRoundDetail(round.id, true, true);
        }
      }
    });
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
   * Decoupled from the 15/15 training threshold: the backend only requires
   * MIN_LABELS_FOR_AL_ROUND confirmed + MIN_LABELS_FOR_AL_ROUND rejected
   * across completed rounds to dispatch the next active-learning iteration.
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
    return (
      totalConfirmed >= MIN_LABELS_FOR_AL_ROUND &&
      totalRejected >= MIN_LABELS_FOR_AL_ROUND
    );
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
          canSuggestNextSamples={seedRoundReady && !lastRoundBusy}
          {isSuggestingNextSamples}
          {suggestError}
          onSuggestNextSamples={handleSuggestNextSamples}
          {isTrained}
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
                      // Silent mode prevents the accordion body from toggling its loading
                      // condition, which would unmount/remount SeedSamplingView (losing
                      // scroll position and local vote-summary state).
                      fetchRoundDetail(round.id, true, true);
                    }}
                  />
                {:else}
                  <ALRoundView
                    {projectId}
                    {modelId}
                    round={getRoundWithItems(round)}
                    onVoteChanged={() => {
                      // Refetch round detail to update confirmed/rejected counts in header.
                      // Silent mode prevents the accordion body from toggling its loading
                      // condition, which would unmount/remount ALRoundView (losing
                      // scroll position and local vote-summary state).
                      fetchRoundDetail(round.id, true, true);
                    }}
                  />
                {/if}
              </div>
            {/if}
          </div>
        {/each}

      </div>

    {/if}
  </div>
</div>
