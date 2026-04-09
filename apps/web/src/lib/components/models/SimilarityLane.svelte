<script lang="ts">
  /**
   * SimilarityLane - A horizontal lane of ReviewCards within a similarity band.
   *
   * Displays cards for a single similarity score band (e.g. 90%+, 80-90%, etc.)
   * with bulk action buttons to mark all results in the lane as positive or negative.
   *
   * Cards use the shared ReviewCard component with voting via the annotation vote API.
   */

  import * as m from '$lib/paraglide/messages';
  import type { VoteSummary, SignalQuality, VoteValue } from '$lib/types/detection';
  import ReviewCard from '$lib/components/common/ReviewCard.svelte';

  export interface LaneResult {
    /** Embedding ID (used as a stable key) */
    embeddingId: string;
    /** Annotation ID for voting — may be null if not yet created */
    annotationId: string | null;
    recordingId: string;
    recordingName: string;
    startTime: number;
    endTime: number;
    freqLow?: number;
    freqHigh?: number;
    /** Cosine similarity score (0.0–1.0) */
    similarity: number;
    /** Current vote summary from server */
    voteSummary: VoteSummary | null;
  }

  interface Props {
    projectId: string;
    /** Display label for this band (e.g. "90%+") */
    bandLabel: string;
    /** Results belonging to this similarity band */
    results: LaneResult[];
    /** Set of embedding IDs currently loading (mutation in flight) */
    loadingIds: Set<string>;
    /** Index of the currently keyboard-focused card (global) */
    selectedIndex: number | null;
    /** Global index offset — the first card in this lane has this global index */
    indexOffset: number;
    /** Called when the user votes on a card */
    onVote: (embeddingId: string, annotationId: string | null, vote: VoteValue, signalQuality?: SignalQuality) => void;
    /** Called when the user removes their vote on a card */
    onRemoveVote: (embeddingId: string, annotationId: string | null) => void;
    /** Called when "Mark all Positive" button is clicked */
    onMarkAllPositive: (results: LaneResult[]) => void;
    /** Called when "Mark all Negative" button is clicked */
    onMarkAllNegative: (results: LaneResult[]) => void;
    /** Array of DOM element refs, indexed by global position */
    cardElements: (HTMLElement | null)[];
  }

  let {
    projectId,
    bandLabel,
    results,
    loadingIds,
    selectedIndex,
    indexOffset,
    onVote,
    onRemoveVote,
    onMarkAllPositive,
    onMarkAllNegative,
    cardElements,
  }: Props = $props();

  /** Tailwind colour class for the band label based on score range */
  const bandColorClass = $derived.by(() => {
    // Parse the lower bound from labels like "90%+", "80-90%", "<50%"
    const match = bandLabel.match(/(\d+)/);
    if (!match) return 'text-stone-500 bg-stone-50';
    const lower = parseInt(match[1] ?? '0', 10);
    if (lower >= 90) return 'text-emerald-700 bg-emerald-50 border-emerald-200 dark:text-emerald-300 dark:bg-emerald-950/30 dark:border-emerald-800';
    if (lower >= 80) return 'text-success bg-success-light border-success/30';
    if (lower >= 70) return 'text-warning bg-warning-light border-warning/30';
    if (lower >= 60) return 'text-orange-700 bg-orange-50 border-orange-200 dark:text-orange-300 dark:bg-orange-950/30 dark:border-orange-800';
    if (lower >= 50) return 'text-danger bg-danger-light border-danger/30';
    return 'text-stone-600 bg-stone-50 border-stone-200 dark:text-stone-400 dark:bg-stone-800 dark:border-stone-700';
  });

  function handleAgree(result: LaneResult, signalQuality: SignalQuality) {
    onVote(result.embeddingId, result.annotationId, 'agree', signalQuality);
  }

  function handleVote(result: LaneResult, vote: VoteValue) {
    onVote(result.embeddingId, result.annotationId, vote);
  }

  function handleRemoveVote(result: LaneResult) {
    onRemoveVote(result.embeddingId, result.annotationId);
  }

  function scoreBadgeClass(similarity: number): string {
    if (similarity >= 0.9) return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400';
    if (similarity >= 0.8) return 'bg-success-light text-success';
    if (similarity >= 0.7) return 'bg-warning-light text-warning';
    if (similarity >= 0.6) return 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400';
    if (similarity >= 0.5) return 'bg-danger-light text-danger';
    return 'bg-stone-100 text-stone-600 dark:bg-stone-700 dark:text-stone-400';
  }
</script>

<div class="space-y-2">
  <!-- Lane header -->
  <div class="flex items-center gap-3">
    <!-- Band label chip -->
    <span class="inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold {bandColorClass}">
      {bandLabel}
    </span>
    <!-- Result count -->
    <span class="text-xs text-stone-400">
      {results.length} {m.models_review_lane_results()}
    </span>

    <!-- Bulk action buttons -->
    {#if results.length > 0}
      <div class="ml-auto flex items-center gap-1.5">
        <button
          type="button"
          class="inline-flex items-center gap-1 rounded border border-success/40 bg-success-light px-2 py-0.5 text-xs font-medium text-success transition-colors hover:bg-success/20"
          onclick={() => onMarkAllPositive(results)}
          title={m.models_review_mark_all_positive_title()}
        >
          <svg class="h-3 w-3" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
            <path d="M2 10.5a1.5 1.5 0 113 0v6a1.5 1.5 0 01-3 0v-6zM6 10.333v5.43a2 2 0 001.106 1.79l.05.025A4 4 0 008.943 18h5.416a2 2 0 001.962-1.608l1.2-6A2 2 0 0015.56 8H12V4a2 2 0 00-2-2 1 1 0 00-1 1v.667a4 4 0 01-.8 2.4L6.8 7.933a4 4 0 00-.8 2.4z" />
          </svg>
          {m.models_review_mark_all_positive()}
        </button>
        <button
          type="button"
          class="inline-flex items-center gap-1 rounded border border-danger/40 bg-danger-light px-2 py-0.5 text-xs font-medium text-danger transition-colors hover:bg-danger/20"
          onclick={() => onMarkAllNegative(results)}
          title={m.models_review_mark_all_negative_title()}
        >
          <svg class="h-3 w-3" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
            <path d="M18 9.5a1.5 1.5 0 11-3 0v-6a1.5 1.5 0 013 0v6zM14 9.667v-5.43a2 2 0 00-1.105-1.79l-.05-.025A4 4 0 0011.055 2H5.64a2 2 0 00-1.962 1.608l-1.2 6A2 2 0 004.44 12H8v4a2 2 0 002 2 1 1 0 001-1v-.667a4 4 0 01.8-2.4l1.4-1.866a4 4 0 00.8-2.4z" />
          </svg>
          {m.models_review_mark_all_negative()}
        </button>
      </div>
    {/if}
  </div>

  <!-- Horizontal scroll row of cards -->
  {#if results.length === 0}
    <p class="text-xs text-stone-400 italic pl-1">{m.models_review_lane_empty()}</p>
  {:else}
    <div class="flex gap-3 overflow-x-auto pb-2">
      {#each results as result, localIdx (result.embeddingId)}
        {@const globalIdx = indexOffset + localIdx}
        <div
          class="shrink-0 w-48"
          bind:this={cardElements[globalIdx]}
        >
          <ReviewCard
            {projectId}
            recordingId={result.recordingId}
            recordingName={result.recordingName}
            startTime={result.startTime}
            endTime={result.endTime}
            freqLow={result.freqLow}
            freqHigh={result.freqHigh}
            status="unreviewed"
            scoreValue={result.similarity}
            scoreLabel={m.models_review_similarity_label()}
            scoreBadgeClass={scoreBadgeClass(result.similarity)}
            isLoading={loadingIds.has(result.embeddingId)}
            isSelected={selectedIndex === globalIdx}
            voteSummary={result.voteSummary}
            compact={true}
            onAgree={(sq) => handleAgree(result, sq)}
            onVote={(v) => handleVote(result, v)}
            onRemoveVote={() => handleRemoveVote(result)}
          />
        </div>
      {/each}
    </div>
  {/if}
</div>
