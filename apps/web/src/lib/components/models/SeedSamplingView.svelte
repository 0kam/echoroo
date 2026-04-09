<script lang="ts">
  /**
   * SeedSamplingView - Displays seed-sampling round results in three labeling lanes.
   *
   * The three lanes correspond to the three categories produced by the seed-sampling
   * algorithm:
   *   - Easy Positives: nearest-neighbour clips very close to the reference embeddings
   *   - Boundary: clips near the expected decision boundary (hardest to classify)
   *   - Others: randomly sampled clips for negative / background context
   *
   * Each card shows a spectrogram thumbnail, a similarity badge, and Agree / Disagree
   * vote buttons that write directly to the annotation vote API.
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
    /** Called after any vote mutation so the parent can refresh data. */
    onVoteChanged: () => void;
  }

  let { projectId, modelId, round, onVoteChanged }: Props = $props();

  // ============================================================
  // Per-item vote summary cache (keyed by annotation_id)
  // ============================================================

  let voteSummaryCache = $state<Record<string, VoteSummary>>({});
  let loadingIds = $state<Set<string>>(new Set());

  // ============================================================
  // Lane definitions
  // ============================================================

  interface LaneDef {
    sampleType: SamplingRoundItem['sample_type'];
    label: string;
    accentClass: string;
    badgeClass: string;
    headerClass: string;
  }

  const LANES: LaneDef[] = [
    {
      sampleType: 'easy_positive',
      label: m.models_seed_lane_easy_positives(),
      accentClass: 'border-emerald-200 dark:border-emerald-800',
      badgeClass: 'bg-emerald-100 text-emerald-700 border-emerald-200 dark:bg-emerald-950/30 dark:text-emerald-300 dark:border-emerald-800',
      headerClass: 'text-emerald-700 dark:text-emerald-400',
    },
    {
      sampleType: 'boundary',
      label: m.models_seed_lane_boundary(),
      accentClass: 'border-amber-200 dark:border-amber-800',
      badgeClass: 'bg-amber-100 text-amber-700 border-amber-200 dark:bg-amber-950/30 dark:text-amber-300 dark:border-amber-800',
      headerClass: 'text-amber-700 dark:text-amber-400',
    },
    {
      sampleType: 'others',
      label: m.models_seed_lane_others(),
      accentClass: 'border-stone-200 dark:border-stone-700',
      badgeClass: 'bg-stone-100 text-stone-600 border-stone-200 dark:bg-stone-800 dark:text-stone-400 dark:border-stone-700',
      headerClass: 'text-stone-600 dark:text-stone-400',
    },
  ];

  // ============================================================
  // Derived: items per lane
  // ============================================================

  function itemsForLane(sampleType: SamplingRoundItem['sample_type']): SamplingRoundItem[] {
    return round.items.filter((it) => it.sample_type === sampleType);
  }

  // ============================================================
  // Score badge colour helper
  // ============================================================

  function scoreBadgeClass(similarity: number | null): string {
    if (similarity === null) return 'bg-stone-100 text-stone-600';
    if (similarity >= 0.9) return 'bg-emerald-100 text-emerald-700';
    if (similarity >= 0.8) return 'bg-green-100 text-green-700';
    if (similarity >= 0.7) return 'bg-yellow-100 text-yellow-700';
    if (similarity >= 0.6) return 'bg-orange-100 text-orange-700';
    if (similarity >= 0.5) return 'bg-red-100 text-red-700';
    return 'bg-stone-100 text-stone-600';
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
      console.error('Seed sampling vote error:', err);
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
      console.error('Seed sampling remove-vote error:', err);
    } finally {
      loadingIds = new Set([...loadingIds].filter((id) => id !== annotationId));
    }
  }
</script>

<div class="space-y-6">
  <!-- Round header -->
  <div class="flex items-center gap-3">
    <span class="text-sm font-semibold text-stone-700 dark:text-stone-300">
      {m.models_seed_round_label({ number: round.round_number })}
    </span>
    <span class="inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium
      {round.status === 'completed'
        ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-300'
        : round.status === 'failed'
          ? 'border-danger/40 bg-danger-light text-danger'
          : 'border-stone-200 bg-stone-50 text-stone-500 dark:border-stone-700 dark:bg-stone-800 dark:text-stone-400'}">
      {round.status}
    </span>
    <span class="text-xs text-stone-400">
      {round.sample_count} {m.models_seed_samples_count()}
    </span>
  </div>

  {#if round.status === 'failed' && round.error_message}
    <div class="rounded-lg border border-danger/30 bg-danger-light px-4 py-3 text-sm text-danger">
      {round.error_message}
    </div>
  {:else if round.status !== 'completed'}
    <div class="flex items-center gap-2 text-sm text-stone-400">
      <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      {m.models_seed_round_processing()}
    </div>
  {:else}
    <!-- Three category lanes -->
    {#each LANES as lane (lane.sampleType)}
      {@const laneItems = itemsForLane(lane.sampleType)}
      <div class="space-y-2">
        <!-- Lane header -->
        <div class="flex items-center gap-3">
          <span class="inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold {lane.badgeClass}">
            {lane.label}
          </span>
          <span class="text-xs text-stone-400">
            {laneItems.length} {m.models_review_lane_results()}
          </span>

          <!-- Labeling progress for this lane -->
          {#if laneItems.length > 0}
            {@const confirmedCount = laneItems.filter((it) =>
              (voteSummaryCache[it.annotation_id]?.user_vote ?? it.review_status) === 'agree' ||
              it.review_status === 'confirmed'
            ).length}
            {@const rejectedCount = laneItems.filter((it) =>
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

        <!-- Horizontal scroll row of cards -->
        {#if laneItems.length === 0}
          <p class="pl-1 text-xs italic text-stone-400">{m.models_review_lane_empty()}</p>
        {:else}
          <div class="flex gap-3 overflow-x-auto pb-2">
            {#each laneItems as item (item.id)}
              {#if item.recording_id && item.start_time !== null && item.end_time !== null}
                <div class="w-48 shrink-0">
                  <ReviewCard
                    {projectId}
                    recordingId={item.recording_id}
                    recordingName={item.recording_id}
                    startTime={item.start_time}
                    endTime={item.end_time}
                    status="unreviewed"
                    scoreValue={item.similarity}
                    scoreLabel={m.models_review_similarity_label()}
                    scoreBadgeClass={scoreBadgeClass(item.similarity)}
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
      </div>
    {/each}
  {/if}
</div>
