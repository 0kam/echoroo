<script lang="ts">
  /**
   * TrainingMeter - Displays training data readiness for a selected search session.
   *
   * Shows agree/disagree vote counts as progress bars and enables the
   * "Train Custom Model" button when minimum labeling requirements are met
   * (5+ agrees and 5+ disagrees).
   */

  import * as m from '$lib/paraglide/messages';
  import type { SamplingRound } from '$lib/types/custom-model';

  interface Props {
    /** Number of results voted as agree (positive) — from session-based review */
    agreeCount: number;
    /** Number of results voted as disagree (negative) — from session-based review */
    disagreeCount: number;
    /** Total number of results in the session */
    totalCount: number;
    /** Called when the user clicks "Train Custom Model" */
    onTrainRequest: () => void;
    /** Whether a training action is in progress */
    isTraining?: boolean;
    /**
     * Optional sampling rounds. When provided and non-empty, the confirmed/rejected
     * counts from round items take priority over agreeCount/disagreeCount.
     */
    samplingRounds?: SamplingRound[];
    /**
     * When true, show the "Suggest Next Samples" button below the train button.
     * The parent is responsible for computing whether the seed/last round state
     * allows an AL round dispatch.
     */
    canSuggestNextSamples?: boolean;
    /** Whether a "Suggest Next Samples" request is in-flight */
    isSuggestingNextSamples?: boolean;
    /** Error message from the most recent "Suggest Next Samples" attempt */
    suggestError?: string | null;
    /** Called when the user clicks "Suggest Next Samples" */
    onSuggestNextSamples?: () => void;
    /**
     * When true, the model has already been trained at least once.
     * The primary action button relabels from "Train" to "Retrain" to
     * reflect the active-learning retraining semantics.
     */
    isTrained?: boolean;
  }

  let {
    agreeCount,
    disagreeCount,
    totalCount,
    onTrainRequest,
    isTraining = false,
    samplingRounds,
    canSuggestNextSamples = false,
    isSuggestingNextSamples = false,
    suggestError = null,
    onSuggestNextSamples,
    isTrained = false,
  }: Props = $props();

  // Determine whether any AL rounds exist — used for the recommendation message.
  const hasALRounds = $derived(
    (samplingRounds ?? []).some((r) => r.round_type === 'active_learning')
  );

  // Count how many distinct rounds have any reviewed items.
  const reviewedRoundsCount = $derived(
    (samplingRounds ?? []).filter((r) =>
      r.items.some(
        (it) => it.review_status === 'confirmed' || it.review_status === 'rejected'
      )
    ).length
  );

  // Compute effective counts: sampling rounds take priority over session-based votes
  const effectiveAgreeCount = $derived.by(() => {
    if (!samplingRounds || samplingRounds.length === 0) return agreeCount;
    return samplingRounds
      .flatMap((r) => r.items)
      .filter((it) => it.review_status === 'confirmed')
      .length;
  });

  const effectiveDisagreeCount = $derived.by(() => {
    if (!samplingRounds || samplingRounds.length === 0) return disagreeCount;
    return samplingRounds
      .flatMap((r) => r.items)
      .filter((it) => it.review_status === 'rejected')
      .length;
  });

  const effectiveTotalCount = $derived.by(() => {
    if (!samplingRounds || samplingRounds.length === 0) return totalCount;
    return samplingRounds.flatMap((r) => r.items).length;
  });

  const MIN_POSITIVES = 15;
  const MIN_NEGATIVES = 15;

  const positivePercent = $derived(
    effectiveTotalCount > 0 ? Math.min(100, (effectiveAgreeCount / effectiveTotalCount) * 100) : 0
  );
  const negativePercent = $derived(
    effectiveTotalCount > 0 ? Math.min(100, (effectiveDisagreeCount / effectiveTotalCount) * 100) : 0
  );

  const canTrain = $derived(effectiveAgreeCount >= MIN_POSITIVES && effectiveDisagreeCount >= MIN_NEGATIVES);
  const reviewedCount = $derived(effectiveAgreeCount + effectiveDisagreeCount);
  const reviewedPercent = $derived(
    effectiveTotalCount > 0 ? Math.min(100, (reviewedCount / effectiveTotalCount) * 100) : 0
  );
</script>

<div class="rounded-xl border border-card bg-surface-card p-4 shadow-sm">
  <div class="flex items-start justify-between gap-4">
    <!-- Left: meter content -->
    <div class="flex-1 min-w-0">
      <h3 class="text-sm font-semibold text-stone-700 mb-3">
        {m.models_review_training_readiness()}
      </h3>

      <!-- Progress bars -->
      <div class="space-y-2">
        <!-- Positives (agree) -->
        <div>
          <div class="mb-1 flex items-center justify-between text-xs">
            <span class="text-success font-medium">{m.models_review_positives()}</span>
            <span class="font-mono text-stone-600">
              {effectiveAgreeCount} / {MIN_POSITIVES} {m.models_review_min_label()}
            </span>
          </div>
          <div class="h-2 w-full overflow-hidden rounded-full bg-stone-100 dark:bg-stone-800">
            <div
              class="h-full rounded-full bg-success transition-all duration-500"
              style="width: {positivePercent}%"
              role="progressbar"
              aria-valuenow={effectiveAgreeCount}
              aria-valuemin={0}
              aria-valuemax={effectiveTotalCount}
              aria-label={m.models_review_positives()}
            ></div>
          </div>
        </div>

        <!-- Negatives (disagree) -->
        <div>
          <div class="mb-1 flex items-center justify-between text-xs">
            <span class="text-danger font-medium">{m.models_review_negatives()}</span>
            <span class="font-mono text-stone-600">
              {effectiveDisagreeCount} / {MIN_NEGATIVES} {m.models_review_min_label()}
            </span>
          </div>
          <div class="h-2 w-full overflow-hidden rounded-full bg-stone-100 dark:bg-stone-800">
            <div
              class="h-full rounded-full bg-danger transition-all duration-500"
              style="width: {negativePercent}%"
              role="progressbar"
              aria-valuenow={effectiveDisagreeCount}
              aria-valuemin={0}
              aria-valuemax={effectiveTotalCount}
              aria-label={m.models_review_negatives()}
            ></div>
          </div>
        </div>

        <!-- Overall reviewed -->
        <div>
          <div class="mb-1 flex items-center justify-between text-xs">
            <span class="text-stone-500">{m.models_review_reviewed()}</span>
            <span class="font-mono text-stone-400">
              {reviewedCount} / {effectiveTotalCount}
              ({Math.round(reviewedPercent)}%)
            </span>
          </div>
          <div class="h-1.5 w-full overflow-hidden rounded-full bg-stone-100 dark:bg-stone-800">
            <div
              class="h-full rounded-full bg-stone-400 transition-all duration-500"
              style="width: {reviewedPercent}%"
            ></div>
          </div>
        </div>
      </div>
    </div>

    <!-- Right: Train button -->
    <div class="shrink-0 flex flex-col items-end gap-2">
      <button
        type="button"
        class="inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium shadow-sm transition-colors focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50
          {canTrain
            ? 'bg-primary-600 text-white hover:bg-primary-700 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400'
            : 'border border-stone-200 bg-stone-50 text-stone-400 cursor-not-allowed dark:border-stone-700 dark:bg-stone-800'}"
        onclick={onTrainRequest}
        disabled={!canTrain || isTraining}
        title={canTrain ? m.models_review_train_tooltip() : m.models_review_train_tooltip_disabled()}
      >
        {#if isTraining}
          <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
          </svg>
          {m.models_training()}
        {:else}
          <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          {isTrained ? m.models_review_retrain_button() : m.models_review_train_button()}
        {/if}
      </button>

      <!-- "Suggest Next Samples" secondary action. Rendered directly beneath the
           train button so both "next action" buttons are grouped together. -->
      {#if canSuggestNextSamples}
        <button
          type="button"
          class="inline-flex items-center gap-2 rounded-lg border border-primary-300 bg-primary-50 px-4 py-2 text-sm font-medium text-primary-700 shadow-sm transition-colors hover:bg-primary-100 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 dark:border-primary-700 dark:bg-primary-950/20 dark:text-primary-400 dark:hover:bg-primary-950/40"
          disabled={isSuggestingNextSamples}
          onclick={onSuggestNextSamples}
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
        {#if suggestError}
          <p class="text-xs text-danger text-right max-w-40">{suggestError}</p>
        {/if}
      {/if}

      {#if !canTrain}
        <p class="text-xs text-stone-400 text-right max-w-40">
          {m.models_review_train_hint({ positives: MIN_POSITIVES, negatives: MIN_NEGATIVES })}
        </p>
      {:else if hasALRounds}
        <!-- Model has gone through at least one AL round — recommend training or another round -->
        <p class="text-xs text-success text-right max-w-40">
          {m.models_ready_to_train()} &mdash;
          {effectiveAgreeCount}+/{effectiveDisagreeCount}&minus;
          &middot; {reviewedRoundsCount} {reviewedRoundsCount === 1 ? 'round' : 'rounds'}
        </p>
      {:else if canTrain}
        <!-- Enough data from seed round; encourage training -->
        <p class="text-xs text-success text-right max-w-40">
          {m.models_ready_to_train()} &mdash;
          {effectiveAgreeCount}+/{effectiveDisagreeCount}&minus;
        </p>
      {/if}
    </div>
  </div>
</div>
