<script lang="ts">
  /**
   * ALRoundView - Displays an active-learning sampling round in three labeling lanes.
   *
   * Active-learning rounds now mirror the seed round's 3-lane layout but the
   * lanes are derived from SVM ``decision_distance`` instead of cosine
   * similarity:
   *
   *   - Easy Positives: largest signed ``decision_distance`` (the model is
   *     most confident these are positives).
   *   - Boundary:       smallest ``|decision_distance|`` (the model is most
   *     uncertain about these — the classic active-learning selection).
   *   - Others:         diverse points selected via farthest-first from the
   *     remainder (exploration of under-sampled regions).
   *
   * Each card reuses ReviewCard. The score badge shows the sigmoid of the
   * signed decision distance (a 0-1 "probability") colour-coded by distance
   * magnitude.
   */

  import { onDestroy, untrack } from 'svelte';
  import * as m from '$lib/paraglide/messages';
  import { toastError } from '$lib/stores/toast';
  import { castAnnotationVote, deleteAnnotationVote } from '$lib/api/votes';
  import type { SamplingRound, SamplingRoundItem } from '$lib/types/custom-model';
  import type { DetectionStatus, VoteSummary, VoteValue, SignalQuality } from '$lib/types/detection';
  import ReviewCard from '$lib/components/common/ReviewCard.svelte';
  import ScoreHistogram from '$lib/components/models/ScoreHistogram.svelte';
  import { createReviewNavigation } from '$lib/utils/reviewNavigation.svelte';

  interface Props {
    projectId: string;
    modelId: string;
    round: SamplingRound;
    /** Called after any vote mutation so the parent can refresh. */
    onVoteChanged: () => void;
  }

  let { projectId, modelId: _modelId, round, onVoteChanged }: Props = $props();

  // ============================================================
  // Sigmoid helper
  // ============================================================

  /**
   * Convert a signed SVM decision distance into a 0-1 probability via the
   * logistic sigmoid. A distance of 0 maps to 0.5 (at the decision boundary,
   * i.e. maximally uncertain), large positive distances approach 1.0
   * (confident positive), and large negative distances approach 0.0
   * (confident negative).
   */
  function sigmoid(d: number): number {
    return 1 / (1 + Math.exp(-d));
  }

  // ============================================================
  // Per-item vote summary cache (keyed by annotation_id)
  // ============================================================

  let voteSummaryCache = $state<Record<string, VoteSummary>>({});
  let loadingIds = $state<Set<string>>(new Set());

  // Histogram section is open by default so users see the distribution shift
  // without having to expand it for every round.
  let histogramOpen = $state(true);

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
    badgeClass: string;
    // Sort comparator for ordering items inside this lane.
    sortCompare: (a: SamplingRoundItem, b: SamplingRoundItem) => number;
  }

  /**
   * Sort helper: largest signed decision_distance first (easy positives).
   */
  function byDistanceDesc(a: SamplingRoundItem, b: SamplingRoundItem): number {
    const da = a.decision_distance ?? -Infinity;
    const db = b.decision_distance ?? -Infinity;
    return db - da;
  }

  /**
   * Sort helper: smallest |decision_distance| first (boundary / most uncertain).
   */
  function byAbsDistanceAsc(a: SamplingRoundItem, b: SamplingRoundItem): number {
    const da = a.decision_distance === null || a.decision_distance === undefined
      ? Infinity
      : Math.abs(a.decision_distance);
    const db = b.decision_distance === null || b.decision_distance === undefined
      ? Infinity
      : Math.abs(b.decision_distance);
    return da - db;
  }

  const LANES: LaneDef[] = [
    {
      sampleType: 'easy_positive',
      label: m.models_seed_lane_easy_positives(),
      badgeClass:
        'bg-emerald-100 text-emerald-700 border-emerald-200 dark:bg-emerald-950/30 dark:text-emerald-300 dark:border-emerald-800',
      sortCompare: byDistanceDesc,
    },
    {
      sampleType: 'boundary',
      label: m.models_seed_lane_boundary(),
      badgeClass:
        'bg-amber-100 text-amber-700 border-amber-200 dark:bg-amber-950/30 dark:text-amber-300 dark:border-amber-800',
      sortCompare: byAbsDistanceAsc,
    },
    {
      sampleType: 'others',
      label: m.models_seed_lane_others(),
      badgeClass:
        'bg-stone-100 text-stone-600 border-stone-200 dark:bg-stone-800 dark:text-stone-400 dark:border-stone-700',
      sortCompare: byAbsDistanceAsc,
    },
  ];

  // ============================================================
  // Derived: items per lane
  // ============================================================

  function itemsForLane(lane: LaneDef): SamplingRoundItem[] {
    return round.items
      .filter((it) => it.sample_type === lane.sampleType)
      .sort(lane.sortCompare);
  }

  /**
   * Legacy fallback: if the round was produced before multi-lane AL landed
   * (i.e. every item has ``sample_type === 'active_learning'``), show them
   * all in a single "boundary"-style lane sorted by |distance| ascending.
   */
  const isLegacySingleLane = $derived(
    round.items.length > 0 &&
      round.items.every((it) => it.sample_type === 'active_learning')
  );

  /**
   * Flat list of all reviewable items ordered by lane (easy_positive →
   * boundary → others), used for keyboard navigation index mapping.
   */
  const allItems = $derived.by<SamplingRoundItem[]>(() => {
    if (isLegacySingleLane) {
      return [...round.items]
        .sort(byAbsDistanceAsc)
        .filter(
          (it) => it.recording_id && it.start_time !== null && it.end_time !== null
        );
    }
    return LANES.flatMap((lane) => itemsForLane(lane)).filter(
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
      console.error('AL round vote error:', err);
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
      console.error('AL round remove-vote error:', err);
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

  <!-- Score distribution histogram (only shown when the round has one) -->
  {#if round.score_distribution}
    <div class="rounded-lg border border-stone-200 bg-white p-3 dark:border-stone-700 dark:bg-stone-900">
      <button
        type="button"
        class="flex w-full items-center justify-between text-left text-xs font-medium text-stone-600 hover:text-stone-800 dark:text-stone-300 dark:hover:text-stone-100"
        onclick={() => (histogramOpen = !histogramOpen)}
        aria-expanded={histogramOpen}
      >
        <span class="flex items-center gap-2">
          <svg
            class="h-3.5 w-3.5 transition-transform"
            style="transform: rotate({histogramOpen ? 90 : 0}deg);"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
          </svg>
          Score distribution
        </span>
        <span class="font-mono text-[10px] text-stone-400 dark:text-stone-500">
          mean {round.score_distribution.mean_score.toFixed(3)} · total {round.score_distribution.total_scored.toLocaleString()}
        </span>
      </button>
      {#if histogramOpen}
        <div class="mt-3">
          <ScoreHistogram distribution={round.score_distribution} />
        </div>
      {/if}
    </div>
  {/if}

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
    {#if allItems.length === 0}
      <p class="pl-1 text-xs italic text-stone-400">{m.models_review_lane_empty()}</p>
    {:else if isLegacySingleLane}
      <!-- Legacy single-lane rendering: sorted by |decision_distance| asc. -->
      <div class="flex gap-3 overflow-x-auto pb-2">
        {#each allItems as item, globalIndex (item.id)}
          <div class="w-48 shrink-0" bind:this={cardElements[globalIndex]}>
            <ReviewCard
              {projectId}
              recordingId={item.recording_id!}
              recordingName={item.recording_filename ?? item.recording_id!}
              startTime={item.start_time!}
              endTime={item.end_time!}
              status={(item.review_status as DetectionStatus) ?? 'unreviewed'}
              scoreValue={item.decision_distance !== null && item.decision_distance !== undefined ? sigmoid(item.decision_distance) : null}
              scoreLabel="distance"
              scoreBadgeClass={distanceBadgeClass(item.decision_distance)}
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
        {/each}
      </div>
    {:else}
      <!-- Three category lanes -->
      {#each LANES as lane (lane.sampleType)}
        {@const laneItems = itemsForLane(lane)}
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
                      scoreValue={item.decision_distance !== null && item.decision_distance !== undefined ? sigmoid(item.decision_distance) : null}
                      scoreLabel="distance"
                      scoreBadgeClass={distanceBadgeClass(item.decision_distance)}
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
  {/if}
</div>
