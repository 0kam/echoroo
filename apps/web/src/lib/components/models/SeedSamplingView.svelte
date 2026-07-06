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

  import { onDestroy, untrack } from 'svelte';
  import * as m from '$lib/paraglide/messages';
  import { toastError } from '$lib/stores/toast';
  import { castAnnotationVote, deleteAnnotationVote } from '$lib/api/votes';
  import type { SamplingRound, SamplingRoundItem } from '$lib/types/custom-model';
  import type { DetectionStatus, VoteSummary, VoteValue, SignalQuality } from '$lib/types/detection';
  import ReviewCard from '$lib/components/common/ReviewCard.svelte';
  import { createReviewNavigation } from '$lib/utils/reviewNavigation.svelte';

  interface Props {
    projectId: string;
    modelId: string;
    round: SamplingRound;
    /** Called after any vote mutation so the parent can refresh data. */
    onVoteChanged: () => void;
  }

  let { projectId, modelId: _modelId, round, onVoteChanged }: Props = $props();

  // ============================================================
  // Per-item vote summary cache (keyed by annotation_id)
  // ============================================================

  let voteSummaryCache = $state<Record<string, VoteSummary>>({});
  let loadingIds = $state<Set<string>>(new Set());

  // ============================================================
  // Keyboard navigation state
  // ============================================================

  let cardElements = $state<(HTMLElement | null)[]>([]);

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

  /**
   * Flat list of all reviewable items ordered by lane (easy_positive →
   * boundary → others), used for keyboard navigation index mapping.
   */
  const allItems = $derived.by<SamplingRoundItem[]>(() => {
    return LANES.flatMap((lane) => itemsForLane(lane.sampleType)).filter(
      (it) => it.recording_id && it.start_time !== null && it.end_time !== null
    );
  });

  const nav = createReviewNavigation({
    // Captured once at mount — the helper is configured once and not
    // re-created on prop changes, so untrack() is appropriate here.
    projectId: untrack(() => projectId),
    simpleMode: true,
    itemCount: () => allItems.length,
    // Legacy callbacks not used in simple mode — provide no-op stubs
    onConfirm: () => {},
    onReject: () => {},
    onAgree: (i) => {
      const item = allItems[i];
      if (item) handleVote(item, 'agree', undefined);
    },
    onDisagree: (i) => {
      const item = allItems[i];
      if (item) handleVote(item, 'disagree', undefined);
    },
    onUnsure: (i) => {
      const item = allItems[i];
      if (item) handleVote(item, 'unsure', undefined);
    },
    getPlaybackInfo: (i) => {
      const item = allItems[i];
      if (!item || !item.recording_id || item.start_time === null || item.end_time === null) return null;
      return { recordingId: item.recording_id, startTime: item.start_time, endTime: item.end_time };
    },
    getElement: (i) => cardElements[i] ?? null,
  });

  onDestroy(() => nav.cleanup());

  // ============================================================
  // Score badge colour helper
  // ============================================================

  function scoreBadgeClass(similarity: number | null): string {
    if (similarity === null) return 'bg-stone-100 text-stone-600 dark:bg-stone-700 dark:text-stone-400';
    if (similarity >= 0.9) return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400';
    if (similarity >= 0.8) return 'bg-success-light text-success';
    if (similarity >= 0.7) return 'bg-warning-light text-warning';
    if (similarity >= 0.6) return 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400';
    if (similarity >= 0.5) return 'bg-danger-light text-danger';
    return 'bg-stone-100 text-stone-600 dark:bg-stone-700 dark:text-stone-400';
  }

  // ============================================================
  // Vote mutations
  // ============================================================

  async function handleVote(
    item: SamplingRoundItem,
    vote: VoteValue,
    signalQuality?: SignalQuality | undefined
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
      toastError(err, m.vote_failed());
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
      toastError(err, m.vote_remove_failed());
    } finally {
      loadingIds = new Set([...loadingIds].filter((id) => id !== annotationId));
    }
  }
</script>

<svelte:window onkeydown={nav.handleKeydown} />

<div class="space-y-6">
  <!-- Keyboard shortcut hint -->
  <div class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-stone-400">
    <span><kbd class="rounded border border-stone-200 bg-stone-50 px-1 font-mono text-[10px] dark:border-stone-700 dark:bg-stone-800">1</kbd> {m.review_keyboard_agree()}</span>
    <span><kbd class="rounded border border-stone-200 bg-stone-50 px-1 font-mono text-[10px] dark:border-stone-700 dark:bg-stone-800">2</kbd> {m.review_keyboard_disagree()}</span>
    <span><kbd class="rounded border border-stone-200 bg-stone-50 px-1 font-mono text-[10px] dark:border-stone-700 dark:bg-stone-800">3</kbd> {m.review_keyboard_unsure()}</span>
    <span><kbd class="rounded border border-stone-200 bg-stone-50 px-1 font-mono text-[10px] dark:border-stone-700 dark:bg-stone-800">Space</kbd> {m.review_keyboard_play()}</span>
    <span><kbd class="rounded border border-stone-200 bg-stone-50 px-1 font-mono text-[10px] dark:border-stone-700 dark:bg-stone-800">↑↓</kbd> {m.review_keyboard_navigate()}</span>
  </div>

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
                {@const globalIndex = allItems.indexOf(item)}
                <div class="w-48 shrink-0" bind:this={cardElements[globalIndex]}>
                  <ReviewCard
                    {projectId}
                    recordingId={item.recording_id}
                    recordingName={item.recording_filename ?? item.recording_id}
                    startTime={item.start_time}
                    endTime={item.end_time}
                    status={(item.review_status as DetectionStatus) ?? 'unreviewed'}
                    scoreValue={item.similarity}
                    scoreLabel={m.models_review_similarity_label()}
                    scoreBadgeClass={scoreBadgeClass(item.similarity)}
                    isLoading={loadingIds.has(item.annotation_id)}
                    voteSummary={voteSummaryCache[item.annotation_id] ?? null}
                    compact={true}
                    simpleMode={true}
                    isSelected={nav.selectedIndex === globalIndex}
                    externalIsPlaying={nav.playingIndex === globalIndex && nav.isPlaying}
                    externalIsLoadingAudio={nav.playingIndex === globalIndex && nav.isLoadingAudio}
                    onPlayToggle={() => nav.togglePlay(globalIndex)}
                    onClickSelect={() => nav.select(globalIndex)}
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
