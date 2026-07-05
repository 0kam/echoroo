<script lang="ts">
  /**
   * Custom model detail view.
   *
   * Full-width view for a single model: header/actions, source-session links,
   * training notice, review & labeling section, metrics, confusion matrix,
   * hyperparameters and training stats. The parent owns the query, polling and
   * mutations and threads the resolved model + callbacks in.
   */

  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import type { CustomModel } from '$lib/types/custom-model';
  import ReviewTab from './ReviewTab.svelte';
  import RecentApplications from './RecentApplications.svelte';
  import { statusLabel, statusClasses, formatDate, formatDuration, formatPercent } from './modelFormatters';

  let {
    projectId,
    model,
    detailLoading,
    trainPending,
    trainVariables,
    onBackToList,
    onApply,
    onTrain,
    onDeleteRequest,
    onReviewTrainRequest,
  }: {
    projectId: string;
    model: CustomModel | null;
    detailLoading: boolean;
    trainPending: boolean;
    trainVariables: string | undefined;
    onBackToList: () => void;
    onApply: () => void;
    onTrain: (modelId: string) => void;
    onDeleteRequest: (modelId: string) => void;
    onReviewTrainRequest: (modelId: string) => void;
  } = $props();
</script>

<div class="space-y-6">
  <!-- Back link -->
  <button
    type="button"
    class="inline-flex items-center gap-1.5 text-sm text-stone-500 transition-colors hover:text-stone-900 dark:hover:text-stone-100"
    onclick={onBackToList}
  >
    <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
      <path d="M19 12H5M12 19l-7-7 7-7" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
    {m.models_back_to_list()}
  </button>

  {#if detailLoading && !model}
    <div class="flex items-center gap-2 text-sm text-stone-400">
      <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      {m.nav_loading()}
    </div>

  {:else if model}

    <!-- Model header -->
    <div class="rounded-xl border border-card bg-surface-card p-6 shadow-sm">
      <div class="flex items-start justify-between gap-4">
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-2">
            <h1 class="text-2xl font-bold text-stone-900">{model.name}</h1>
            <span class="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium {statusClasses(model.status)}">
              {#if model.status === 'training'}
                <svg class="h-3 w-3 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                </svg>
              {/if}
              {statusLabel(model.status)}
            </span>
          </div>

          {#if model.description}
            <p class="mt-2 text-sm text-stone-500">{model.description}</p>
          {/if}

          <dl class="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-stone-400">
            <div class="flex items-center gap-1">
              <dt class="font-medium">{m.models_embedding_model()}:</dt>
              <dd>{model.embedding_model_name}</dd>
            </div>
            <div class="flex items-center gap-1">
              <dt class="font-medium">{m.models_created_at()}:</dt>
              <dd>{formatDate(model.created_at)}</dd>
            </div>
            {#if model.completed_at}
              <div class="flex items-center gap-1">
                <dt class="font-medium">{m.models_trained_at()}:</dt>
                <dd>{formatDate(model.completed_at)}</dd>
              </div>
            {/if}
          </dl>
        </div>

        <!-- Actions -->
        <div class="flex shrink-0 flex-wrap gap-2">
          {#if model.status === 'trained' || model.status === 'deployed'}
            <button
              type="button"
              class="inline-flex items-center gap-2 rounded-lg border border-success/40 bg-success-light px-4 py-2 text-sm font-medium text-success transition-colors hover:bg-success/20"
              onclick={onApply}
            >
              <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              {m.models_apply()}
            </button>
          {/if}
          {#if model.status === 'failed'}
            <button
              type="button"
              class="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:opacity-50 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
              onclick={() => onTrain(model.id)}
              disabled={trainPending}
            >
              {#if trainPending && trainVariables === model.id}
                <svg class="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                </svg>
                {m.models_training()}
              {:else}
                {m.models_train()}
              {/if}
            </button>
          {/if}
          <button
            type="button"
            class="inline-flex items-center gap-2 rounded-lg border border-danger/40 px-4 py-2 text-sm font-medium text-danger transition-colors hover:bg-danger-light"
            onclick={() => onDeleteRequest(model.id)}
          >
            {m.models_delete()}
          </button>
        </div>
      </div>
    </div>

    <!-- Source session links (only shown when search_session_id is set) -->
    {#if model.search_session_id}
      <div class="flex flex-wrap gap-3 rounded-lg border border-stone-200 bg-stone-50 px-4 py-3 dark:border-stone-700 dark:bg-stone-800/40">
        <span class="text-xs font-medium text-stone-500 self-center">Origin:</span>
        <a
          href={localizeHref(`/projects/${projectId}/search?session=${model.search_session_id}`)}
          class="inline-flex items-center gap-1.5 text-sm text-primary-600 hover:text-primary-700 dark:text-primary-400 dark:hover:text-primary-300"
        >
          <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          Source: Search Session
        </a>
        {#if model.status === 'draft' || model.status === 'training' || model.status === 'failed'}
          <span class="text-stone-300 dark:text-stone-600 self-center">|</span>
          <a
            href={localizeHref(`/projects/${projectId}/search?session=${model.search_session_id}`)}
            class="inline-flex items-center gap-1.5 text-sm text-warning hover:opacity-80"
          >
            <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
            </svg>
            Continue in Search
          </a>
        {/if}
      </div>
    {/if}

    <!-- Training in progress notice -->
    {#if model.status === 'training'}
      <div class="flex items-center gap-3 rounded-lg border border-warning/20 bg-warning-light p-4 text-sm text-warning">
        <svg class="h-4 w-4 shrink-0 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
        <span>{m.models_status_training()} Polling for updates every 3 seconds...</span>
      </div>
    {/if}

    <!-- Error message -->
    {#if model.error_message}
      <div class="rounded-lg border border-danger/30 bg-danger-light p-4 text-sm text-danger">
        <span class="font-medium">{m.models_error_prefix()}</span> {model.error_message}
      </div>
    {/if}

    <!-- Recent Applications: show progress/history of Apply-to-Dataset jobs.
         Only relevant once the model is trainable/trained (trained/deployed),
         since Apply is only enabled in those states. -->
    {#if model.status === 'trained' || model.status === 'deployed'}
      <RecentApplications {projectId} modelId={model.id} />
    {/if}

    <!-- Review & Labeling section (draft/failed/trained models).
         For trained models, the user can continue the active-learning loop:
         label more samples from new AL rounds, then retrain to improve. -->
    {#if model.status === 'draft' || model.status === 'failed' || model.status === 'trained'}
      <div class="rounded-xl border border-card bg-surface-card p-5 shadow-sm">
        <h2 class="mb-4 text-base font-semibold text-stone-800 dark:text-stone-200">
          {m.models_review_and_labeling()}
        </h2>
        {#if model.status === 'trained'}
          <p class="mb-4 text-xs text-stone-500 dark:text-stone-400">
            {m.models_trained_continue_al_hint()}
          </p>
        {/if}
        <ReviewTab
          {projectId}
          modelId={model.id}
          isTrained={model.status === 'trained'}
          onTrainRequest={() => onReviewTrainRequest(model.id)}
        />
      </div>
    {/if}

    <!-- Metrics (only shown when trained) -->
    {#if model.metrics}
      {@const metrics = model.metrics}
      <div class="rounded-xl border border-card bg-surface-card p-6 shadow-sm">
        <div class="mb-5 flex flex-wrap items-center gap-2">
          <h2 class="text-sm font-semibold uppercase tracking-wider text-stone-500">
            Internal Validation
          </h2>
          {#if metrics.cv_method}
            <span class="rounded-full bg-stone-100 px-2 py-0.5 text-xs text-stone-500 dark:bg-stone-800">
              {metrics.cv_method}
            </span>
          {/if}
        </div>

        {#if metrics.cv_warning}
          <div class="mb-4 flex items-start gap-2 rounded-lg border border-warning/20 bg-warning-light p-3 text-xs text-warning">
            <svg class="mt-0.5 h-3.5 w-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
            </svg>
            {metrics.cv_warning}
          </div>
        {/if}

        <!-- Primary metric bars -->
        <div class="space-y-4">
          {#each [
            { label: m.models_metrics_f1(), value: metrics.f1 },
            { label: m.models_metrics_auc_roc(), value: metrics.roc_auc },
            { label: m.models_metrics_pr_auc(), value: metrics.pr_auc },
            { label: m.models_metrics_accuracy(), value: metrics.accuracy },
            { label: m.models_metrics_precision(), value: metrics.precision },
            { label: m.models_metrics_recall(), value: metrics.recall },
          ] as metric}
            <div>
              <div class="mb-1 flex items-center justify-between text-sm">
                <span class="font-medium text-stone-700">{metric.label}</span>
                <span class="font-mono text-stone-900">{formatPercent(metric.value as number)}</span>
              </div>
              <div class="h-2 w-full overflow-hidden rounded-full bg-stone-100 dark:bg-stone-800">
                <div
                  class="h-full rounded-full bg-primary-500 transition-all"
                  style="width: {((metric.value as number) * 100).toFixed(1)}%"
                ></div>
              </div>
            </div>
          {/each}
        </div>
      </div>

      <!-- Confusion matrix + hyperparameters -->
      <div class="grid gap-4 sm:grid-cols-2">
        <!-- Confusion matrix -->
        <div class="rounded-xl border border-card bg-surface-card p-6 shadow-sm">
          <h2 class="mb-4 text-sm font-semibold uppercase tracking-wider text-stone-500">
            {m.models_detail_confusion_matrix()}
          </h2>
          {#if metrics.confusion_matrix}
            {@const [[tn, fp], [fn, tp]] = metrics.confusion_matrix}
            <div class="grid grid-cols-2 gap-2 text-center text-sm">
              <div class="rounded-lg bg-success-light p-3">
                <p class="text-xs font-medium text-success">{m.models_detail_true_positive()}</p>
                <p class="mt-1 text-xl font-bold text-success">{tp}</p>
              </div>
              <div class="rounded-lg bg-danger-light p-3">
                <p class="text-xs font-medium text-danger">{m.models_detail_false_positive()}</p>
                <p class="mt-1 text-xl font-bold text-danger">{fp}</p>
              </div>
              <div class="rounded-lg bg-danger-light p-3">
                <p class="text-xs font-medium text-danger">{m.models_detail_false_negative()}</p>
                <p class="mt-1 text-xl font-bold text-danger">{fn}</p>
              </div>
              <div class="rounded-lg bg-success-light p-3">
                <p class="text-xs font-medium text-success">{m.models_detail_true_negative()}</p>
                <p class="mt-1 text-xl font-bold text-success">{tn}</p>
              </div>
            </div>
          {/if}
        </div>

        <!-- Hyperparameters -->
        <div class="rounded-xl border border-card bg-surface-card p-6 shadow-sm">
          <h2 class="mb-4 text-sm font-semibold uppercase tracking-wider text-stone-500">
            {m.models_detail_hyperparameters()}
          </h2>
          <dl class="space-y-2 text-sm">
            {#if model.hyperparameters?.best_c !== undefined}
              <div class="flex items-center justify-between">
                <dt class="text-stone-500">{m.models_detail_best_c()}</dt>
                <dd class="font-mono font-semibold text-stone-900">{model.hyperparameters.best_c}</dd>
              </div>
            {/if}
          </dl>
          {#if model.hyperparameters}
            {#each Object.entries(model.hyperparameters).filter(([k]) => k !== 'best_c') as [key, value]}
              <dl class="mt-2 space-y-2 text-sm">
                <div class="flex items-center justify-between">
                  <dt class="text-stone-500">{key}</dt>
                  <dd class="font-mono font-semibold text-stone-900">{String(value)}</dd>
                </div>
              </dl>
            {/each}
          {/if}
        </div>
      </div>
    {/if}

    <!-- Training stats -->
    {#if model.training_stats}
      {@const stats = model.training_stats}
      <div class="rounded-xl border border-card bg-surface-card p-6 shadow-sm">
        <h2 class="mb-4 text-sm font-semibold uppercase tracking-wider text-stone-500">
          {m.models_detail_training_stats()}
        </h2>
        <div class="flex flex-wrap gap-6">
          <div>
            <p class="text-xs font-medium uppercase tracking-wider text-stone-400">{m.models_detail_positive()}</p>
            <p class="mt-1 text-2xl font-bold text-stone-900">{stats.positive_count.toLocaleString()}</p>
          </div>
          <div>
            <p class="text-xs font-medium uppercase tracking-wider text-stone-400">{m.models_detail_negative()}</p>
            <p class="mt-1 text-2xl font-bold text-stone-900">{stats.negative_count.toLocaleString()}</p>
          </div>
          <div>
            <p class="text-xs font-medium uppercase tracking-wider text-stone-400">{m.models_detail_unlabeled()}</p>
            <p class="mt-1 text-2xl font-bold text-stone-900">{stats.unlabeled_count.toLocaleString()}</p>
          </div>
          <div>
            <p class="text-xs font-medium uppercase tracking-wider text-stone-400">{m.models_detail_duration()}</p>
            <p class="mt-1 text-2xl font-bold text-stone-900">{formatDuration(stats.training_duration_s)}</p>
          </div>
        </div>
      </div>
    {/if}
  {/if}
</div>
