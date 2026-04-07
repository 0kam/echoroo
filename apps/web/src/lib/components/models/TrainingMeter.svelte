<script lang="ts">
  /**
   * TrainingMeter - Displays training data readiness for a selected search session.
   *
   * Shows agree/disagree vote counts as progress bars and enables the
   * "Train Custom Model" button when minimum labeling requirements are met
   * (5+ agrees and 5+ disagrees).
   */

  import * as m from '$lib/paraglide/messages';

  interface Props {
    /** Number of results voted as agree (positive) */
    agreeCount: number;
    /** Number of results voted as disagree (negative) */
    disagreeCount: number;
    /** Total number of results in the session */
    totalCount: number;
    /** Called when the user clicks "Train Custom Model" */
    onTrainRequest: () => void;
    /** Whether a training action is in progress */
    isTraining?: boolean;
  }

  let {
    agreeCount,
    disagreeCount,
    totalCount,
    onTrainRequest,
    isTraining = false,
  }: Props = $props();

  const MIN_POSITIVES = 5;
  const MIN_NEGATIVES = 5;

  const positivePercent = $derived(
    totalCount > 0 ? Math.min(100, (agreeCount / totalCount) * 100) : 0
  );
  const negativePercent = $derived(
    totalCount > 0 ? Math.min(100, (disagreeCount / totalCount) * 100) : 0
  );

  const canTrain = $derived(agreeCount >= MIN_POSITIVES && disagreeCount >= MIN_NEGATIVES);
  const reviewedCount = $derived(agreeCount + disagreeCount);
  const reviewedPercent = $derived(
    totalCount > 0 ? Math.min(100, (reviewedCount / totalCount) * 100) : 0
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
              {agreeCount} / {MIN_POSITIVES} {m.models_review_min_label()}
            </span>
          </div>
          <div class="h-2 w-full overflow-hidden rounded-full bg-stone-100 dark:bg-stone-800">
            <div
              class="h-full rounded-full bg-success transition-all duration-500"
              style="width: {positivePercent}%"
              role="progressbar"
              aria-valuenow={agreeCount}
              aria-valuemin={0}
              aria-valuemax={totalCount}
              aria-label={m.models_review_positives()}
            ></div>
          </div>
        </div>

        <!-- Negatives (disagree) -->
        <div>
          <div class="mb-1 flex items-center justify-between text-xs">
            <span class="text-danger font-medium">{m.models_review_negatives()}</span>
            <span class="font-mono text-stone-600">
              {disagreeCount} / {MIN_NEGATIVES} {m.models_review_min_label()}
            </span>
          </div>
          <div class="h-2 w-full overflow-hidden rounded-full bg-stone-100 dark:bg-stone-800">
            <div
              class="h-full rounded-full bg-danger transition-all duration-500"
              style="width: {negativePercent}%"
              role="progressbar"
              aria-valuenow={disagreeCount}
              aria-valuemin={0}
              aria-valuemax={totalCount}
              aria-label={m.models_review_negatives()}
            ></div>
          </div>
        </div>

        <!-- Overall reviewed -->
        <div>
          <div class="mb-1 flex items-center justify-between text-xs">
            <span class="text-stone-500">{m.models_review_reviewed()}</span>
            <span class="font-mono text-stone-400">
              {reviewedCount} / {totalCount}
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
            ? 'bg-primary-600 dark:bg-primary-300 text-white hover:bg-primary-700 dark:hover:bg-primary-200'
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
          {m.models_review_train_button()}
        {/if}
      </button>

      {#if !canTrain}
        <p class="text-xs text-stone-400 text-right max-w-32">
          {m.models_review_train_hint({ positives: MIN_POSITIVES, negatives: MIN_NEGATIVES })}
        </p>
      {/if}
    </div>
  </div>
</div>
