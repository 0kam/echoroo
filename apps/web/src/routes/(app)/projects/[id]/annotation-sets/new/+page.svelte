<script lang="ts">
  /**
   * AnnotationSet create wizard.
   *
   * A 4-step linear wizard:
   *   1. Dataset (required)
   *   2. Filters (optional date range + time-of-day range)
   *   3. Geometry (segment_length_sec, num_segments)
   *   4. Name + confirm
   *
   * Creation triggers backend sampling via Celery; on success we redirect
   * to the detail page which polls the set's status.
   */
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { createQuery, createMutation } from '@tanstack/svelte-query';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import { fetchDatasets } from '$lib/api/datasets';
  import { createAnnotationSet } from '$lib/api/annotation-sets';
  import { toasts } from '$lib/stores/toast';
  import type { Dataset } from '$lib/types/data';
  import type {
    AnnotationSetCreate,
    DateRange,
    SegmentMode,
    TimeOfDayRange,
  } from '$lib/types/annotation-set';

  const projectId = $derived($page.params.id as string);

  // ---- Wizard state
  let step = $state<1 | 2 | 3 | 4>(1);

  // Step 1
  let datasetId = $state<string>('');

  // Step 2 (all optional)
  let useDateRange = $state(false);
  let dateStart = $state<string>('');
  let dateEnd = $state<string>('');
  let useTodRange = $state(false);
  let todStart = $state<string>('06:00');
  let todEnd = $state<string>('10:00');

  // Step 3
  let segmentMode = $state<SegmentMode>('fixed');
  let segmentLengthSec = $state<number>(60);
  let numSegments = $state<number>(50);

  // ToriTore participation gate (preview). Empty string => no requirement
  // (sent as `null`). Prefilled to 0.2 per the locked default. The bound
  // value can be a number or '' (cleared), so it is typed as `number | ''`.
  let minTotalScore = $state<number | ''>(0.2);

  // Step 4
  let name = $state<string>('');

  let submitError = $state<string | null>(null);

  // ---- Datasets query
  const datasetsQuery = $derived(
    createQuery({
      queryKey: ['datasets', projectId, 'for-annotation-set'],
      queryFn: () => fetchDatasets(projectId, { page_size: 200 }),
      enabled: !!projectId,
    }),
  );

  const selectedDataset = $derived<Dataset | null>(
    $datasetsQuery.data?.items.find((d) => d.id === datasetId) ?? null,
  );

  // ---- Mutation
  const createMutationState = createMutation({
    mutationFn: (body: AnnotationSetCreate) => createAnnotationSet(body),
    onSuccess: (created) => {
      toasts.success('Annotation set created.');
      void goto(localizeHref(`/projects/${projectId}/annotation-sets/${created.id}`));
    },
    onError: (err: Error) => {
      submitError = err.message || m.annotation_sets_create_error();
    },
  });

  // ---- Validation helpers (return error message or null)
  function validateStep1(): string | null {
    if (!datasetId) return m.annotation_sets_create_validation_dataset();
    return null;
  }

  function validateStep2(): string | null {
    if (useDateRange && dateStart && dateEnd && dateStart > dateEnd) {
      return m.annotation_sets_create_validation_date();
    }
    return null;
  }

  function validateStep3(): string | null {
    // The segment length only matters in fixed mode; whole_recording uses the
    // full duration and ignores it.
    if (
      segmentMode === 'fixed' &&
      (!Number.isFinite(segmentLengthSec) || segmentLengthSec < 10)
    ) {
      return m.annotation_sets_create_validation_length();
    }
    if (!Number.isFinite(numSegments) || numSegments < 1) {
      return m.annotation_sets_create_validation_count();
    }
    return null;
  }

  function validateStep4(): string | null {
    if (!name.trim()) return m.annotation_sets_create_validation_name();
    return null;
  }

  const currentStepError = $derived.by(() => {
    switch (step) {
      case 1:
        return validateStep1();
      case 2:
        return validateStep2();
      case 3:
        return validateStep3();
      case 4:
        return validateStep4();
    }
  });

  function next() {
    const err = currentStepError;
    if (err) {
      submitError = err;
      return;
    }
    submitError = null;
    if (step < 4) step = (step + 1) as typeof step;
  }

  function back() {
    submitError = null;
    if (step > 1) step = (step - 1) as typeof step;
  }

  function submit() {
    const err = validateStep1() ?? validateStep2() ?? validateStep3() ?? validateStep4();
    if (err) {
      submitError = err;
      return;
    }
    submitError = null;

    const body: AnnotationSetCreate = {
      project_id: projectId,
      dataset_id: datasetId,
      name: name.trim(),
      segment_mode: segmentMode,
      num_segments: Math.floor(numSegments),
      // Empty input clears the requirement (null); a number sets the threshold.
      min_total_score: minTotalScore === '' ? null : minTotalScore,
    };

    // segment_length_sec is only sent in fixed mode; whole_recording leaves it
    // unset so the backend stores NULL.
    if (segmentMode === 'fixed') {
      body.segment_length_sec = Math.floor(segmentLengthSec);
    }

    if (useDateRange && dateStart && dateEnd) {
      const range: DateRange = { start: dateStart, end: dateEnd };
      body.filter_date_range = range;
    }
    if (useTodRange && todStart && todEnd) {
      const range: TimeOfDayRange = { start: todStart, end: todEnd };
      body.filter_time_of_day_range = range;
    }

    $createMutationState.mutate(body);
  }
</script>

<svelte:head>
  <title>{m.annotation_sets_create_title()}</title>
</svelte:head>

<div class="mx-auto max-w-3xl px-4 py-6">
  <!-- Breadcrumb -->
  <nav class="mb-4 flex items-center gap-2 text-sm text-stone-500">
    <a href={localizeHref(`/projects/${projectId}`)} class="hover:text-stone-900 dark:hover:text-stone-200">
      {m.search_breadcrumb_project()}
    </a>
    <span>/</span>
    <a
      href={localizeHref(`/projects/${projectId}/annotation-sets`)}
      class="hover:text-stone-900 dark:hover:text-stone-200"
    >
      {m.annotation_sets_list_title()}
    </a>
    <span>/</span>
    <span class="font-medium text-stone-900 dark:text-stone-100">
      {m.annotation_sets_create_title()}
    </span>
  </nav>

  <header class="mb-6">
    <h1 class="text-2xl font-bold text-stone-900 dark:text-stone-100">
      {m.annotation_sets_create_title()}
    </h1>
    <p class="mt-1 text-sm text-stone-500">{m.annotation_sets_create_subtitle()}</p>
    <p class="mt-2 text-xs text-stone-400">
      {m.annotation_sets_create_step_count({ current: String(step), total: '4' })}
    </p>
  </header>

  <!-- Step indicators -->
  <ol class="mb-6 flex items-center gap-2 text-xs" aria-label="Wizard progress">
    {#each [
      { n: 1 as const, label: m.annotation_sets_create_step_dataset() },
      { n: 2 as const, label: m.annotation_sets_create_step_filters() },
      { n: 3 as const, label: m.annotation_sets_create_step_geometry() },
      { n: 4 as const, label: m.annotation_sets_create_step_name() },
    ] as s}
      <li
        class="flex flex-1 items-center gap-2 rounded-lg border px-3 py-2 {step === s.n
          ? 'border-primary-400 bg-primary-50 text-primary-700 dark:border-primary-500 dark:bg-primary-900/30 dark:text-primary-300'
          : step > s.n
            ? 'border-stone-200 bg-stone-50 text-stone-500 dark:border-stone-700 dark:bg-stone-800/40'
            : 'border-stone-200 text-stone-400 dark:border-stone-700'}"
      >
        <span class="inline-flex h-5 w-5 items-center justify-center rounded-full border border-current text-[10px] font-bold">
          {s.n}
        </span>
        <span class="truncate">{s.label}</span>
      </li>
    {/each}
  </ol>

  <section class="rounded-xl border border-card bg-surface-card p-6 shadow-sm">
    <!-- Step 1: Dataset -->
    {#if step === 1}
      <h2 class="text-lg font-semibold text-stone-900 dark:text-stone-100">
        {m.annotation_sets_create_step_dataset()}
      </h2>
      <p class="mt-1 text-sm text-stone-500">{m.annotation_sets_create_dataset_hint()}</p>

      <div class="mt-4">
        <label for="dataset-select" class="block text-sm font-medium text-stone-700 dark:text-stone-300">
          {m.annotation_sets_create_dataset_label()}
        </label>
        {#if $datasetsQuery.isLoading}
          <p class="mt-2 text-sm text-stone-400">{m.annotation_sets_create_dataset_loading()}</p>
        {:else if $datasetsQuery.data?.items.length === 0}
          <p class="mt-2 text-sm text-danger">{m.annotation_sets_create_dataset_empty()}</p>
        {:else}
          <select
            id="dataset-select"
            class="mt-1 block w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/20 dark:border-stone-600 dark:bg-stone-800 dark:text-stone-100"
            bind:value={datasetId}
          >
            <option value="">{m.annotation_sets_create_dataset_select_placeholder()}</option>
            {#each $datasetsQuery.data?.items ?? [] as ds (ds.id)}
              <option value={ds.id}>{ds.name}</option>
            {/each}
          </select>
        {/if}
      </div>

    <!-- Step 2: Filters -->
    {:else if step === 2}
      <h2 class="text-lg font-semibold text-stone-900 dark:text-stone-100">
        {m.annotation_sets_create_step_filters()}
      </h2>
      <p class="mt-1 text-sm text-stone-500">
        {m.annotation_sets_create_filters_description()}
      </p>

      <!-- Date range -->
      <fieldset class="mt-6 rounded-lg border border-stone-200 p-4 dark:border-stone-700">
        <legend class="px-2 text-sm font-medium text-stone-700 dark:text-stone-300">
          <label class="inline-flex items-center gap-2">
            <input type="checkbox" class="rounded" bind:checked={useDateRange} />
            {m.annotation_sets_create_filters_date_range()}
          </label>
        </legend>
        <div class="mt-2 grid grid-cols-2 gap-3" class:opacity-50={!useDateRange}>
          <div>
            <label for="date-start" class="block text-xs text-stone-500">
              {m.annotation_sets_create_filters_date_start()}
            </label>
            <input
              id="date-start"
              type="date"
              class="mt-1 w-full rounded-lg border border-stone-300 bg-white px-2 py-1.5 text-sm dark:border-stone-600 dark:bg-stone-800 dark:text-stone-100"
              bind:value={dateStart}
              disabled={!useDateRange}
            />
          </div>
          <div>
            <label for="date-end" class="block text-xs text-stone-500">
              {m.annotation_sets_create_filters_date_end()}
            </label>
            <input
              id="date-end"
              type="date"
              class="mt-1 w-full rounded-lg border border-stone-300 bg-white px-2 py-1.5 text-sm dark:border-stone-600 dark:bg-stone-800 dark:text-stone-100"
              bind:value={dateEnd}
              disabled={!useDateRange}
            />
          </div>
        </div>
      </fieldset>

      <!-- Time-of-day range -->
      <fieldset class="mt-4 rounded-lg border border-stone-200 p-4 dark:border-stone-700">
        <legend class="px-2 text-sm font-medium text-stone-700 dark:text-stone-300">
          <label class="inline-flex items-center gap-2">
            <input type="checkbox" class="rounded" bind:checked={useTodRange} />
            {m.annotation_sets_create_filters_tod_range()}
          </label>
        </legend>
        <div class="mt-2 grid grid-cols-2 gap-3" class:opacity-50={!useTodRange}>
          <div>
            <label for="tod-start" class="block text-xs text-stone-500">
              {m.annotation_sets_create_filters_tod_start()}
            </label>
            <input
              id="tod-start"
              type="time"
              class="mt-1 w-full rounded-lg border border-stone-300 bg-white px-2 py-1.5 text-sm dark:border-stone-600 dark:bg-stone-800 dark:text-stone-100"
              bind:value={todStart}
              disabled={!useTodRange}
            />
          </div>
          <div>
            <label for="tod-end" class="block text-xs text-stone-500">
              {m.annotation_sets_create_filters_tod_end()}
            </label>
            <input
              id="tod-end"
              type="time"
              class="mt-1 w-full rounded-lg border border-stone-300 bg-white px-2 py-1.5 text-sm dark:border-stone-600 dark:bg-stone-800 dark:text-stone-100"
              bind:value={todEnd}
              disabled={!useTodRange}
            />
          </div>
        </div>
        <p class="mt-2 text-xs text-stone-400">{m.annotation_sets_create_filters_tod_hint()}</p>
      </fieldset>

    <!-- Step 3: Geometry -->
    {:else if step === 3}
      <h2 class="text-lg font-semibold text-stone-900 dark:text-stone-100">
        {m.annotation_sets_create_step_geometry()}
      </h2>
      <p class="mt-1 text-sm text-stone-500">
        {m.annotation_sets_create_geometry_description()}
      </p>

      <!-- Segment mode -->
      <fieldset class="mt-4">
        <legend class="block text-sm font-medium text-stone-700 dark:text-stone-300">
          {m.annotation_sets_create_geometry_mode()}
        </legend>
        <div class="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
          <label
            class="flex cursor-pointer items-start gap-2 rounded-lg border p-3 text-sm {segmentMode === 'fixed'
              ? 'border-primary-400 bg-primary-50 dark:border-primary-500 dark:bg-primary-900/30'
              : 'border-stone-200 dark:border-stone-700'}"
          >
            <input
              type="radio"
              name="segment-mode"
              value="fixed"
              class="mt-0.5"
              bind:group={segmentMode}
            />
            <span>
              <span class="block font-medium text-stone-900 dark:text-stone-100">
                {m.annotation_sets_create_geometry_mode_fixed()}
              </span>
              <span class="mt-0.5 block text-xs text-stone-400">
                {m.annotation_sets_create_geometry_mode_fixed_hint()}
              </span>
            </span>
          </label>
          <label
            class="flex cursor-pointer items-start gap-2 rounded-lg border p-3 text-sm {segmentMode === 'whole_recording'
              ? 'border-primary-400 bg-primary-50 dark:border-primary-500 dark:bg-primary-900/30'
              : 'border-stone-200 dark:border-stone-700'}"
          >
            <input
              type="radio"
              name="segment-mode"
              value="whole_recording"
              class="mt-0.5"
              bind:group={segmentMode}
            />
            <span>
              <span class="block font-medium text-stone-900 dark:text-stone-100">
                {m.annotation_sets_create_geometry_mode_whole()}
              </span>
              <span class="mt-0.5 block text-xs text-stone-400">
                {m.annotation_sets_create_geometry_mode_whole_hint()}
              </span>
            </span>
          </label>
        </div>
      </fieldset>

      <div class="mt-4 grid grid-cols-2 gap-4">
        {#if segmentMode === 'fixed'}
          <div>
            <label for="seg-length" class="block text-sm font-medium text-stone-700 dark:text-stone-300">
              {m.annotation_sets_create_geometry_length()}
            </label>
            <input
              id="seg-length"
              type="number"
              min="10"
              step="1"
              class="mt-1 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm dark:border-stone-600 dark:bg-stone-800 dark:text-stone-100"
              bind:value={segmentLengthSec}
            />
            <p class="mt-1 text-xs text-stone-400">{m.annotation_sets_create_geometry_length_hint()}</p>
          </div>
        {/if}
        <div>
          <label for="seg-count" class="block text-sm font-medium text-stone-700 dark:text-stone-300">
            {segmentMode === 'whole_recording'
              ? m.annotation_sets_create_geometry_count_whole()
              : m.annotation_sets_create_geometry_count()}
          </label>
          <input
            id="seg-count"
            type="number"
            min="1"
            step="1"
            class="mt-1 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm dark:border-stone-600 dark:bg-stone-800 dark:text-stone-100"
            bind:value={numSegments}
          />
          <p class="mt-1 text-xs text-stone-400">
            {segmentMode === 'whole_recording'
              ? m.annotation_sets_create_geometry_count_whole_hint()
              : m.annotation_sets_create_geometry_count_hint()}
          </p>
        </div>
      </div>

      <!-- ToriTore participation gate (preview) -->
      <div class="mt-4">
        <label for="min-total-score" class="block text-sm font-medium text-stone-700 dark:text-stone-300">
          {m.annotation_sets_create_min_total_score()}
        </label>
        <input
          id="min-total-score"
          type="number"
          min="0"
          max="1"
          step="0.01"
          class="mt-1 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm dark:border-stone-600 dark:bg-stone-800 dark:text-stone-100"
          bind:value={minTotalScore}
        />
        <p class="mt-1 text-xs text-stone-400">{m.annotation_sets_create_min_total_score_hint()}</p>
      </div>

    <!-- Step 4: Name + summary -->
    {:else if step === 4}
      <h2 class="text-lg font-semibold text-stone-900 dark:text-stone-100">
        {m.annotation_sets_create_step_name()}
      </h2>

      <div class="mt-4">
        <label for="set-name" class="block text-sm font-medium text-stone-700 dark:text-stone-300">
          {m.annotation_sets_create_name_label()}
        </label>
        <input
          id="set-name"
          type="text"
          class="mt-1 w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm dark:border-stone-600 dark:bg-stone-800 dark:text-stone-100"
          placeholder={m.annotation_sets_create_name_placeholder()}
          bind:value={name}
          maxlength="200"
        />
        <p class="mt-1 text-xs text-stone-400">{m.annotation_sets_create_name_hint()}</p>
      </div>

      <section class="mt-6 rounded-lg border border-stone-200 bg-stone-50 p-4 dark:border-stone-700 dark:bg-stone-800/40">
        <h3 class="text-sm font-semibold text-stone-700 dark:text-stone-200">
          {m.annotation_sets_create_summary_title()}
        </h3>
        <dl class="mt-3 grid grid-cols-[120px_1fr] gap-y-1.5 text-sm">
          <dt class="text-stone-500">{m.annotation_sets_create_summary_dataset()}:</dt>
          <dd class="text-stone-900 dark:text-stone-100">
            {selectedDataset?.name ?? '—'}
          </dd>

          <dt class="text-stone-500">{m.annotation_sets_create_summary_filters()}:</dt>
          <dd class="text-stone-900 dark:text-stone-100">
            {#if useDateRange && dateStart && dateEnd}
              {dateStart} – {dateEnd}
            {/if}
            {#if useTodRange && todStart && todEnd}
              {#if useDateRange && dateStart && dateEnd}, {/if}
              {todStart}–{todEnd}
            {/if}
            {#if !(useDateRange && dateStart && dateEnd) && !(useTodRange && todStart && todEnd)}
              {m.annotation_sets_create_summary_filters_none()}
            {/if}
          </dd>

          <dt class="text-stone-500">{m.annotation_sets_create_summary_mode()}:</dt>
          <dd class="text-stone-900 dark:text-stone-100">
            {segmentMode === 'whole_recording'
              ? m.annotation_sets_create_geometry_mode_whole()
              : m.annotation_sets_create_geometry_mode_fixed()}
          </dd>

          {#if segmentMode === 'fixed'}
            <dt class="text-stone-500">{m.annotation_sets_create_summary_length()}:</dt>
            <dd class="text-stone-900 dark:text-stone-100">{segmentLengthSec}s</dd>
          {/if}

          <dt class="text-stone-500">
            {segmentMode === 'whole_recording'
              ? m.annotation_sets_create_geometry_count_whole()
              : m.annotation_sets_create_summary_count()}:
          </dt>
          <dd class="text-stone-900 dark:text-stone-100">{numSegments}</dd>

          <dt class="text-stone-500">{m.annotation_sets_create_summary_min_total_score()}:</dt>
          <dd class="text-stone-900 dark:text-stone-100">
            {minTotalScore === ''
              ? m.annotation_sets_create_summary_min_total_score_none()
              : minTotalScore}
          </dd>
        </dl>
      </section>
    {/if}

    {#if submitError}
      <div class="mt-4 rounded-lg border border-danger/30 bg-danger-light p-3 text-sm text-danger" role="alert">
        {submitError}
      </div>
    {/if}

    <div class="mt-6 flex items-center justify-between">
      <a
        href={localizeHref(`/projects/${projectId}/annotation-sets`)}
        class="text-sm text-stone-500 hover:text-stone-900 dark:hover:text-stone-200"
      >
        {m.annotation_sets_create_cancel()}
      </a>

      <div class="flex items-center gap-2">
        {#if step > 1}
          <button
            type="button"
            class="rounded-lg border border-stone-300 px-4 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50 dark:border-stone-600 dark:text-stone-200 dark:hover:bg-stone-800"
            onclick={back}
            disabled={$createMutationState.isPending}
          >
            {m.annotation_sets_create_back()}
          </button>
        {/if}

        {#if step < 4}
          <button
            type="button"
            class="rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700 disabled:opacity-50 dark:bg-primary-500 dark:hover:bg-primary-400"
            onclick={next}
          >
            {m.annotation_sets_create_next()}
          </button>
        {:else}
          <button
            type="button"
            class="rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700 disabled:opacity-50 dark:bg-primary-500 dark:hover:bg-primary-400"
            onclick={submit}
            disabled={$createMutationState.isPending}
          >
            {$createMutationState.isPending
              ? m.annotation_sets_create_submitting()
              : m.annotation_sets_create_submit()}
          </button>
        {/if}
      </div>
    </div>
  </section>
</div>
