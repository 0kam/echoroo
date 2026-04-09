<script lang="ts">
  /**
   * ALRoundView - Displays an active-learning sampling round.
   *
   * Active-learning rounds differ from seed rounds in that every item is
   * selected because it is close to the model's current decision boundary
   * (i.e., the model is most uncertain about it).  Items are sorted so the
   * most-uncertain clip (|decision_distance| nearest to 0) appears first.
   *
   * Each card reuses ReviewCard and augments it with a decision-distance badge
   * colour-coded from red (very uncertain) to green (more confident).
   */

  import * as m from '$lib/paraglide/messages';
  import { castAnnotationVote, deleteAnnotationVote } from '$lib/api/votes';
  import type { SamplingRound, SamplingRoundItem } from '$lib/types/custom-model';
  import type { VoteSummary, VoteValue, SignalQuality } from '$lib/types/detection';
  import ReviewCard from '$lib/components/common/ReviewCard.svelte';

  interface Props {
    projectId: string;
    modelId: string;
    round: SamplingRound;
    /** Called after any vote mutation so the parent can refresh. */
    onVoteChanged: () => void;
  }

  let { projectId, modelId, round, onVoteChanged }: Props = $props();

  // ============================================================
  // Per-item vote summary cache (keyed by annotation_id)
  // ============================================================

  let voteSummaryCache = $state<Record<string, VoteSummary>>({});
  let loadingIds = $state<Set<string>>(new Set());

  // ============================================================
  // Derived: items sorted by |decision_distance| ascending
  // ============================================================

  const sortedItems = $derived.by<SamplingRoundItem[]>(() => {
    return [...round.items].sort((a, b) => {
      const da = a.decision_distance === null ? Infinity : Math.abs(a.decision_distance);
      const db = b.decision_distance === null ? Infinity : Math.abs(b.decision_distance);
      return da - db;
    });
  });

  // ============================================================
  // Decision-distance badge colour helper
  // ============================================================

  /**
   * Returns Tailwind classes for the decision-distance badge.
   *
   * The scale goes from red (|distance| near 0 = very uncertain) to green
   * (|distance| large = more confident).  Typical SVM distances cluster in
   * the 0–2 range for un-scaled feature spaces; values beyond 1 are treated
   * as "confident enough".
   */
  function distanceBadgeClass(distance: number | null): string {
    if (distance === null)
      return 'bg-stone-100 text-stone-600 border-stone-200 dark:bg-stone-800 dark:text-stone-400 dark:border-stone-700';
    const abs = Math.abs(distance);
    if (abs < 0.1)
      return 'bg-danger-light text-danger border-danger/20 dark:bg-danger-light dark:text-danger/50 dark:border-danger/60';
    if (abs < 0.3)
      return 'bg-orange-100 text-orange-700 border-orange-200 dark:bg-orange-950/30 dark:text-orange-300 dark:border-orange-800';
    if (abs < 0.6)
      return 'bg-warning-light text-warning border-warning/30';
    if (abs < 1.0)
      return 'bg-lime-100 text-lime-700 border-lime-200 dark:bg-lime-950/30 dark:text-lime-300 dark:border-lime-800';
    return 'bg-emerald-100 text-emerald-700 border-emerald-200 dark:bg-emerald-950/30 dark:text-emerald-300 dark:border-emerald-800';
  }

  function formatDistance(distance: number | null): string {
    if (distance === null) return '—';
    return distance.toFixed(3);
  }

  // ============================================================
  // Vote mutations
  // ============================================================

  async function handleVote(
    item: SamplingRoundItem,
    vote: VoteValue,
    signalQuality?: SignalQuality
  ) {
    const annotationId = item.annotation_id;
    if (!annotationId) return;

    loadingIds = new Set([...loadingIds, annotationId]);
    try {
      const summary = await castAnnotationVote(projectId, annotationId, vote, signalQuality);
      voteSummaryCache = { ...voteSummaryCache, [annotationId]: summary };
      onVoteChanged();
    } catch (err) {
      console.error('AL round vote error:', err);
    } finally {
      loadingIds = new Set([...loadingIds].filter((id) => id !== annotationId));
    }
  }

  async function handleRemoveVote(item: SamplingRoundItem) {
    const annotationId = item.annotation_id;
    if (!annotationId) return;

    loadingIds = new Set([...loadingIds, annotationId]);
    try {
      const summary = await deleteAnnotationVote(projectId, annotationId);
      voteSummaryCache = { ...voteSummaryCache, [annotationId]: summary };
      onVoteChanged();
    } catch (err) {
      console.error('AL round remove-vote error:', err);
    } finally {
      loadingIds = new Set([...loadingIds].filter((id) => id !== annotationId));
    }
  }
</script>

<div class="space-y-4">
  <!-- Round header -->
  <div class="flex items-center gap-3">
    <span class="text-sm font-semibold text-stone-700 dark:text-stone-300">
      {m.models_al_round_label({ number: round.round_number })}
    </span>
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

    <!-- Labeling progress summary -->
    {#if round.status === 'completed' && round.items.length > 0}
      {@const confirmedCount = round.items.filter((it) =>
        (voteSummaryCache[it.annotation_id]?.user_vote ?? it.review_status) === 'agree' ||
        it.review_status === 'confirmed'
      ).length}
      {@const rejectedCount = round.items.filter((it) =>
        (voteSummaryCache[it.annotation_id]?.user_vote ?? it.review_status) === 'disagree' ||
        it.review_status === 'rejected'
      ).length}
      <span class="ml-auto text-xs text-stone-400">
        <span class="text-success">{confirmedCount} {m.models_seed_confirmed()}</span>
        &middot;
        <span class="text-danger">{rejectedCount} {m.models_seed_rejected()}</span>
      </span>
    {/if}
  </div>

  {#if round.status === 'failed' && round.error_message}
    <div class="rounded-lg border border-danger/30 bg-danger-light px-4 py-3 text-sm text-danger">
      {round.error_message}
    </div>
  {:else if round.status === 'pending' || round.status === 'running'}
    <div class="flex items-center gap-2 text-sm text-stone-400">
      <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      {m.models_suggest_samples_running()}
    </div>
  {:else if round.status === 'completed'}
    <!-- Horizontal scroll lane sorted by |decision_distance| ascending -->
    {#if sortedItems.length === 0}
      <p class="pl-1 text-xs italic text-stone-400">{m.models_review_lane_empty()}</p>
    {:else}
      <div class="flex gap-3 overflow-x-auto pb-2">
        {#each sortedItems as item (item.id)}
          {#if item.recording_id && item.start_time !== null && item.end_time !== null}
            <div class="w-48 shrink-0">
              <ReviewCard
                {projectId}
                recordingId={item.recording_id}
                recordingName={item.recording_id}
                startTime={item.start_time}
                endTime={item.end_time}
                status="unreviewed"
                scoreValue={item.decision_distance}
                scoreLabel="distance"
                scoreBadgeClass={distanceBadgeClass(item.decision_distance)}
                isLoading={loadingIds.has(item.annotation_id)}
                voteSummary={voteSummaryCache[item.annotation_id] ?? null}
                compact={true}
                onAgree={(sq) => handleVote(item, 'agree', sq)}
                onVote={(v) => handleVote(item, v)}
                onRemoveVote={() => handleRemoveVote(item)}
              />
            </div>
          {/if}
        {/each}
      </div>
    {/if}
  {/if}
</div>
