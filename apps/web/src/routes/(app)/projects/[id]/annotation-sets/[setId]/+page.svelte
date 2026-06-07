<script lang="ts">
  /**
   * AnnotationSet detail / progress page.
   *
   * Behaviour per status:
   *   - sampling : show loading state, poll detail every 2s until ready
   *   - ready    : show palette editor + segment summary, enable "Start annotating"
   *   - in_progress / completed : same as ready plus completion affordances
   *
   * Palette management uses the global taxa search (GBIF + local) through the
   * existing `searchTaxa` / `searchGBIF` helpers, so the user can add any
   * species without leaving this page.
   */
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { getLocale, localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import { fetchDataset } from '$lib/api/datasets';
  import { searchTaxa, createTaxonFromGbif } from '$lib/api/taxa';
  import {
    getAnnotationSet,
    listSegments,
    updateAnnotationSet,
    deleteAnnotationSet,
    addPalette,
    removePalette,
  } from '$lib/api/annotation-sets';
  import { toasts } from '$lib/stores/toast';
  import type {
    AnnotationSetDetail,
    AnnotationSetStatus,
    AnnotationSegmentStatus,
    PaletteEntry,
  } from '$lib/types/annotation-set';
  import type { SpeciesPickerResult } from '$lib/types/species-picker';
  import { formatSpeciesName } from '$lib/utils/speciesFormatters';
  import UnifiedSpeciesPicker from '$lib/components/shared/UnifiedSpeciesPicker.svelte';
  import { norm } from '$lib/components/shared/unifiedSpeciesPicker';
  import EvaluationRunDialog from '$lib/components/annotation-sets/EvaluationRunDialog.svelte';
  import EvaluationRunList from '$lib/components/annotation-sets/EvaluationRunList.svelte';

  const projectId = $derived($page.params.id as string);
  const setId = $derived($page.params.setId as string);
  const queryClient = useQueryClient();

  // ============================================================
  // Queries
  // ============================================================

  const detailQuery = $derived(
    createQuery({
      // Include locale in the key so palette common_name resolution is cached
      // per-locale (the backend resolves palette[].common_name for `locale`).
      queryKey: ['annotation-set', setId, getLocale()],
      queryFn: () => getAnnotationSet(projectId, setId, getLocale()),
      enabled: !!setId,
      refetchOnWindowFocus: false,
      // Poll while sampling; stop once ready/in_progress/completed.
      refetchInterval: (query): number | false => {
        const d = query.state.data as AnnotationSetDetail | undefined;
        return d?.status === 'sampling' ? 2000 : false;
      },
    }),
  );

  const detail = $derived<AnnotationSetDetail | null>($detailQuery.data ?? null);

  // Invalidate dependent queries when sampling completes.
  let previousStatus = $state<AnnotationSetStatus | null>(null);
  $effect(() => {
    const s = detail?.status ?? null;
    if (previousStatus === 'sampling' && s && s !== 'sampling') {
      queryClient.invalidateQueries({ queryKey: ['annotation-sets', projectId] });
      queryClient.invalidateQueries({ queryKey: ['annotation-set-segments', setId] });
    }
    previousStatus = s;
  });

  // Dataset name for display
  const datasetQuery = $derived(
    createQuery({
      queryKey: ['dataset', projectId, detail?.dataset_id],
      queryFn: () =>
        detail ? fetchDataset(projectId, detail.dataset_id) : Promise.reject('no dataset'),
      enabled: !!detail,
      refetchOnWindowFocus: false,
    }),
  );

  // Filter for segment list
  let segmentFilter = $state<AnnotationSegmentStatus | 'all'>('all');

  const segmentsQuery = $derived(
    createQuery({
      queryKey: ['annotation-set-segments', setId, segmentFilter],
      queryFn: () =>
        listSegments(projectId, setId, {
          status: segmentFilter === 'all' ? undefined : segmentFilter,
          page_size: 100,
        }),
      enabled: !!setId && !!detail && detail.status !== 'sampling',
      refetchOnWindowFocus: false,
    }),
  );

  // ============================================================
  // Rename
  // ============================================================

  let isRenaming = $state(false);
  let renameValue = $state('');

  const renameMutationState = createMutation({
    mutationFn: (name: string) => updateAnnotationSet(projectId, setId, { name }),
    onSuccess: (updated) => {
      queryClient.setQueryData(['annotation-set', setId, getLocale()], updated);
      queryClient.invalidateQueries({ queryKey: ['annotation-sets', projectId] });
      isRenaming = false;
      toasts.success(m.annotation_sets_rename_success());
    },
    onError: () => toasts.error(m.annotation_sets_rename_error()),
  });

  function startRename() {
    renameValue = detail?.name ?? '';
    isRenaming = true;
  }

  function cancelRename() {
    isRenaming = false;
  }

  function submitRename() {
    const trimmed = renameValue.trim();
    if (!trimmed || trimmed === detail?.name) {
      isRenaming = false;
      return;
    }
    $renameMutationState.mutate(trimmed);
  }

  // ============================================================
  // Delete
  // ============================================================

  let deleteConfirming = $state(false);
  let evaluationDialogOpen = $state(false);

  const deleteMutationState = createMutation({
    mutationFn: () => deleteAnnotationSet(projectId, setId),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: ['annotation-set', setId] });
      queryClient.invalidateQueries({ queryKey: ['annotation-sets', projectId] });
      toasts.success(m.annotation_sets_delete_success());
      void goto(localizeHref(`/projects/${projectId}/annotation-sets`));
    },
    onError: () => toasts.error(m.annotation_sets_delete_error()),
  });

  // ============================================================
  // Palette management
  // ============================================================

  const addPaletteMutationState = createMutation({
    mutationFn: (speciesId: string) => addPalette(projectId, setId, { species_id: speciesId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['annotation-set', setId] });
    },
    onError: (err: Error) => {
      toasts.error(err.message || m.annotation_sets_palette_add_error());
    },
  });

  /**
   * Resolve a unified-picker pick to a `taxon_id` and add it to the palette.
   *
   * The palette only stores real taxa, so non-taxon picks are resolved first:
   *   - taxon pick → use its id directly
   *   - tag pick   → use the tag's taxon_id; legacy tags without a link fall
   *     back to a single taxa search by scientific name
   *   - gbif pick  → get-or-create a local taxon via `createTaxonFromGbif`
   * (custom entry is disabled in palette-search, so it never reaches here.)
   */
  // Normalized scientific names with an in-flight resolve/add. Passed to the
  // picker so the row stays disabled until the async add settles, preventing a
  // double-POST before the palette query refetches with the new entry.
  let pendingKeys = $state(new Set<string>());

  async function handlePaletteAdd(result: SpeciesPickerResult) {
    const key = norm(result.scientific_name);
    // Defense-in-depth: a row already in the palette or mid-add is a no-op (no
    // POST → no 409). The picker greys these out, but guard here regardless.
    if (addedKeys.has(key) || pendingKeys.has(key)) return;

    pendingKeys = new Set(pendingKeys).add(key);
    try {
      let taxonId: string | null = null;

      if (result.source === 'taxon' && result.taxon_id) {
        taxonId = result.taxon_id;
      } else if (result.source === 'tag') {
        if (result.taxon_id) {
          taxonId = result.taxon_id;
        } else {
          // Legacy tag with no taxon link: resolve by scientific name, then
          // materialise from GBIF so the pick never silently no-ops.
          const matches = await searchTaxa(result.scientific_name, getLocale(), 1);
          taxonId = matches[0]?.id ?? null;
          if (!taxonId) {
            const taxon = await createTaxonFromGbif(
              result.scientific_name,
              result.gbif_key,
              result.common_name,
              getLocale(),
              result.vernacular_names,
            );
            taxonId = taxon.id;
          }
        }
      } else if (result.source === 'gbif') {
        const taxon = await createTaxonFromGbif(
          result.scientific_name,
          result.gbif_key,
          result.common_name,
          getLocale(),
          result.vernacular_names,
        );
        taxonId = taxon.id;
      }

      if (taxonId) {
        $addPaletteMutationState.mutate(taxonId);
      } else {
        toasts.error(m.annotation_sets_palette_add_error());
      }
    } catch (err) {
      toasts.error(
        err instanceof Error ? err.message : m.annotation_sets_palette_add_error(),
      );
    } finally {
      const next = new Set(pendingKeys);
      next.delete(key);
      pendingKeys = next;
    }
  }

  const removePaletteMutationState = createMutation({
    mutationFn: (speciesId: string) => removePalette(projectId, setId, speciesId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['annotation-set', setId] });
    },
    onError: () => toasts.error(m.annotation_sets_palette_remove_error()),
  });

  // ============================================================
  // Formatting helpers
  // ============================================================

  function statusLabel(status: AnnotationSetStatus): string {
    switch (status) {
      case 'sampling':
        return m.annotation_sets_status_sampling();
      case 'ready':
        return m.annotation_sets_status_ready();
      case 'in_progress':
        return m.annotation_sets_status_in_progress();
      case 'completed':
        return m.annotation_sets_status_completed();
    }
  }

  function statusClass(status: AnnotationSetStatus): string {
    switch (status) {
      case 'sampling':
        return 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300';
      case 'ready':
        return 'bg-primary-100 text-primary-800 dark:bg-primary-900/30 dark:text-primary-300';
      case 'in_progress':
        return 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300';
      case 'completed':
        return 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300';
    }
  }

  function segmentStatusLabel(status: AnnotationSegmentStatus): string {
    switch (status) {
      case 'unannotated':
        return m.annotation_sets_segment_status_unannotated();
      case 'annotated':
        return m.annotation_sets_segment_status_annotated();
      case 'skipped':
        return m.annotation_sets_segment_status_skipped();
    }
  }

  function segmentStatusClass(status: AnnotationSegmentStatus): string {
    switch (status) {
      case 'annotated':
        return 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300';
      case 'skipped':
        return 'bg-stone-200 text-stone-700 dark:bg-stone-700 dark:text-stone-300';
      default:
        return 'bg-stone-100 text-stone-600 dark:bg-stone-800 dark:text-stone-400';
    }
  }

  function formatDate(iso: string): string {
    return new Date(iso).toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  function startAnnotatingHref(segmentId: string): string {
    // B2 will implement this editor; the route is pre-reserved.
    return localizeHref(
      `/projects/${projectId}/annotation-sets/${setId}/annotate/${segmentId}`,
    );
  }

  const progressPercent = $derived.by(() => {
    const p = detail?.progress;
    if (!p || p.total === 0) return 0;
    return Math.round((p.annotated / p.total) * 100);
  });

  const paletteDisplay = $derived<PaletteEntry[]>(detail?.palette ?? []);

  // Authoritative grey-out: normalized scientific names already in the palette.
  const addedKeys = $derived(new Set(paletteDisplay.map((e) => norm(e.scientific_name))));

  function paletteDisplayName(entry: PaletteEntry): string {
    return formatSpeciesName(entry.common_name, entry.scientific_name);
  }
</script>

<svelte:head>
  <title>{detail?.name ?? m.annotation_sets_page_title()}</title>
</svelte:head>

<div class="mx-auto max-w-5xl px-4 py-6">
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
      {m.annotation_sets_detail_breadcrumb()}
    </a>
    <span>/</span>
    <span class="truncate font-medium text-stone-900 dark:text-stone-100">
      {detail?.name ?? '...'}
    </span>
  </nav>

  {#if $detailQuery.isLoading && !detail}
    <p class="text-sm text-stone-400">{m.annotation_sets_detail_loading()}</p>
  {:else if $detailQuery.isError}
    <div class="rounded-lg border border-danger/30 bg-danger-light p-4 text-sm text-danger">
      {m.annotation_sets_detail_error()}
    </div>
  {:else if !detail}
    <p class="text-sm text-stone-500">{m.annotation_sets_detail_not_found()}</p>
  {:else}
    <!-- Header card -->
    <section class="rounded-xl border border-card bg-surface-card p-6 shadow-sm">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div class="min-w-0 flex-1">
          {#if isRenaming}
            <div class="flex items-center gap-2">
              <input
                type="text"
                class="flex-1 rounded-lg border border-stone-300 bg-white px-3 py-2 text-lg font-semibold shadow-sm dark:border-stone-600 dark:bg-stone-800 dark:text-stone-100"
                bind:value={renameValue}
                maxlength="200"
                onkeydown={(e) => {
                  if (e.key === 'Enter') submitRename();
                  if (e.key === 'Escape') cancelRename();
                }}
              />
              <button
                type="button"
                class="rounded-lg bg-primary-600 px-3 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
                onclick={submitRename}
                disabled={$renameMutationState.isPending}
              >
                {m.annotation_sets_detail_rename_save()}
              </button>
              <button
                type="button"
                class="rounded-lg border border-stone-300 px-3 py-2 text-sm hover:bg-stone-50 dark:border-stone-600 dark:hover:bg-stone-800"
                onclick={cancelRename}
              >
                {m.annotation_sets_detail_rename_cancel()}
              </button>
            </div>
          {:else}
            <div class="flex flex-wrap items-center gap-2">
              <h1 class="text-2xl font-bold text-stone-900 dark:text-stone-100">{detail.name}</h1>
              <span class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium {statusClass(detail.status)}">
                {statusLabel(detail.status)}
              </span>
              <button
                type="button"
                class="rounded p-1 text-stone-400 transition-colors hover:text-stone-900 dark:hover:text-stone-200"
                onclick={startRename}
                aria-label={m.annotation_sets_detail_rename()}
                title={m.annotation_sets_detail_rename()}
              >
                <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                </svg>
              </button>
            </div>
          {/if}

          <dl class="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-stone-500">
            <div class="flex items-center gap-1">
              <dt class="font-medium">{m.annotation_sets_detail_dataset()}:</dt>
              <dd>{$datasetQuery.data?.name ?? '...'}</dd>
            </div>
            <div class="flex items-center gap-1">
              <dt class="font-medium">{m.annotation_sets_detail_segment_length()}:</dt>
              <dd>{detail.segment_length_sec}s</dd>
            </div>
            <div class="flex items-center gap-1">
              <dt class="font-medium">{m.annotation_sets_detail_segment_count()}:</dt>
              <dd>{detail.num_segments}</dd>
            </div>
            <div class="flex items-center gap-1">
              <dt class="font-medium">{m.annotation_sets_detail_created_at()}:</dt>
              <dd>{formatDate(detail.created_at)}</dd>
            </div>
            <div class="flex items-center gap-1">
              <dt class="font-medium">{m.annotation_sets_detail_filters()}:</dt>
              <dd>
                {#if detail.filter_date_range}
                  {detail.filter_date_range.start} – {detail.filter_date_range.end}
                {/if}
                {#if detail.filter_time_of_day_range}
                  {#if detail.filter_date_range}, {/if}
                  {detail.filter_time_of_day_range.start}–{detail.filter_time_of_day_range.end}
                {/if}
                {#if !detail.filter_date_range && !detail.filter_time_of_day_range}
                  {m.annotation_sets_detail_filters_none()}
                {/if}
              </dd>
            </div>
          </dl>

          {#if detail.sampling_warning}
            <div class="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-900/40 dark:bg-amber-900/20 dark:text-amber-300">
              <strong>{m.annotation_sets_detail_warning()}:</strong>
              {detail.sampling_warning}
            </div>
          {/if}
        </div>

        <div class="flex flex-shrink-0 items-center gap-2">
          <button
            type="button"
            class="rounded-lg border border-danger/40 bg-danger-light px-3 py-1.5 text-xs font-medium text-danger transition-colors hover:bg-danger/20"
            onclick={() => (deleteConfirming = true)}
          >
            {m.annotation_sets_detail_delete()}
          </button>
        </div>
      </div>
    </section>

    <!-- Sampling in progress -->
    {#if detail.status === 'sampling'}
      <section class="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-6 text-center dark:border-amber-900/40 dark:bg-amber-900/20">
        <svg class="mx-auto h-8 w-8 animate-spin text-amber-600" fill="none" viewBox="0 0 24 24" aria-hidden="true">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
        <h2 class="mt-3 text-base font-semibold text-amber-800 dark:text-amber-200">
          {m.annotation_sets_detail_sampling_title()}
        </h2>
        <p class="mt-1 text-sm text-amber-700 dark:text-amber-300">
          {m.annotation_sets_detail_sampling_description()}
        </p>
      </section>
    {:else}
      <!-- Progress -->
      <section class="mt-6 rounded-xl border border-card bg-surface-card p-6 shadow-sm">
        <h2 class="text-lg font-semibold text-stone-900 dark:text-stone-100">
          {m.annotation_sets_progress_title()}
        </h2>

        <div class="mt-3 h-3 overflow-hidden rounded-full bg-stone-200 dark:bg-stone-700">
          <div
            class="h-full rounded-full bg-primary-500 transition-all"
            style:width="{progressPercent}%"
          ></div>
        </div>
        <p class="mt-1 text-xs text-stone-500">
          {m.annotation_sets_progress_percent({ percent: String(progressPercent) })}
        </p>

        <dl class="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-5">
          <div class="rounded-lg bg-stone-50 p-3 dark:bg-stone-800/40">
            <dt class="text-xs text-stone-500">{m.annotation_sets_progress_total()}</dt>
            <dd class="mt-0.5 text-lg font-semibold text-stone-900 dark:text-stone-100">
              {detail.progress.total}
            </dd>
          </div>
          <div class="rounded-lg bg-green-50 p-3 dark:bg-green-900/20">
            <dt class="text-xs text-green-700 dark:text-green-300">{m.annotation_sets_progress_annotated()}</dt>
            <dd class="mt-0.5 text-lg font-semibold text-green-800 dark:text-green-200">
              {detail.progress.annotated}
            </dd>
          </div>
          <div class="rounded-lg bg-stone-50 p-3 dark:bg-stone-800/40">
            <dt class="text-xs text-stone-500">{m.annotation_sets_progress_unannotated()}</dt>
            <dd class="mt-0.5 text-lg font-semibold text-stone-900 dark:text-stone-100">
              {detail.progress.unannotated}
            </dd>
          </div>
          <div class="rounded-lg bg-stone-50 p-3 dark:bg-stone-800/40">
            <dt class="text-xs text-stone-500">{m.annotation_sets_progress_skipped()}</dt>
            <dd class="mt-0.5 text-lg font-semibold text-stone-900 dark:text-stone-100">
              {detail.progress.skipped}
            </dd>
          </div>
          <div class="rounded-lg bg-stone-50 p-3 dark:bg-stone-800/40">
            <dt class="text-xs text-stone-500">{m.annotation_sets_progress_empty()}</dt>
            <dd class="mt-0.5 text-lg font-semibold text-stone-900 dark:text-stone-100">
              {detail.progress.empty}
            </dd>
          </div>
        </dl>
      </section>

      <!-- Species palette -->
      <section class="mt-6 rounded-xl border border-card bg-surface-card p-6 shadow-sm">
        <h2 class="text-lg font-semibold text-stone-900 dark:text-stone-100">
          {m.annotation_sets_palette_title()}
        </h2>
        <p class="mt-1 text-sm text-stone-500">{m.annotation_sets_palette_description()}</p>

        <div class="mt-4 flex flex-wrap gap-2">
          {#if paletteDisplay.length === 0}
            <p class="text-sm text-stone-400">{m.annotation_sets_palette_empty()}</p>
          {/if}
          {#each paletteDisplay as entry (entry.species_id)}
            <span class="inline-flex items-center gap-1.5 rounded-full bg-primary-100 px-3 py-1 text-xs font-medium text-primary-800 dark:bg-primary-900/30 dark:text-primary-300">
              <span class="truncate">{paletteDisplayName(entry)}</span>
              <button
                type="button"
                class="text-primary-700 hover:text-primary-900 dark:text-primary-300 dark:hover:text-primary-100"
                aria-label={m.annotation_sets_palette_remove_aria({
                  name: entry.common_name ?? entry.scientific_name,
                })}
                onclick={() => $removePaletteMutationState.mutate(entry.species_id)}
                disabled={$removePaletteMutationState.isPending}
              >
                &times;
              </button>
            </span>
          {/each}
        </div>

        <div class="mt-4">
          <UnifiedSpeciesPicker
            mode="palette-search"
            showGBIF
            {addedKeys}
            {pendingKeys}
            placeholder={m.annotation_sets_palette_add_placeholder()}
            onPick={handlePaletteAdd}
          />
        </div>
      </section>

      <!-- Segments table -->
      <section class="mt-6 rounded-xl border border-card bg-surface-card p-6 shadow-sm">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <h2 class="text-lg font-semibold text-stone-900 dark:text-stone-100">
            {m.annotation_sets_segments_title()}
          </h2>

          <div class="inline-flex rounded-lg border border-stone-200 bg-stone-50 p-1 text-xs dark:border-stone-700 dark:bg-stone-800/40" role="tablist" aria-label={m.annotation_sets_segments_title()}>
            {#each [
              { key: 'all' as const, label: m.annotation_sets_segments_filter_all() },
              { key: 'unannotated' as const, label: m.annotation_sets_segments_filter_unannotated() },
              { key: 'annotated' as const, label: m.annotation_sets_segments_filter_annotated() },
              { key: 'skipped' as const, label: m.annotation_sets_segments_filter_skipped() },
            ] as tab}
              <button
                type="button"
                role="tab"
                aria-selected={segmentFilter === tab.key}
                class="rounded-md px-3 py-1 font-medium transition-colors {segmentFilter === tab.key
                  ? 'bg-white text-stone-900 shadow-sm dark:bg-stone-900 dark:text-stone-100'
                  : 'text-stone-500 hover:text-stone-900 dark:hover:text-stone-200'}"
                onclick={() => (segmentFilter = tab.key)}
              >
                {tab.label}
              </button>
            {/each}
          </div>
        </div>

        {#if $segmentsQuery.isLoading}
          <p class="mt-4 text-sm text-stone-400">{m.annotation_sets_segments_loading()}</p>
        {:else if $segmentsQuery.isError}
          <div class="mt-4 rounded-lg border border-danger/30 bg-danger-light p-3 text-sm text-danger">
            {m.annotation_sets_segments_error()}
          </div>
        {:else if $segmentsQuery.data?.items.length === 0}
          <p class="mt-4 text-sm text-stone-400">{m.annotation_sets_segments_empty()}</p>
        {:else if $segmentsQuery.data}
          <div class="mt-4 overflow-x-auto">
            <table class="min-w-full text-sm">
              <thead class="text-left text-xs font-semibold uppercase tracking-wider text-stone-500">
                <tr>
                  <th class="py-2 pr-4">{m.annotation_sets_segments_column_filename()}</th>
                  <th class="py-2 pr-4">{m.annotation_sets_segments_column_range()}</th>
                  <th class="py-2 pr-4">{m.annotation_sets_segments_column_status()}</th>
                  <th class="py-2 pr-4">{m.annotation_sets_segments_column_annotations()}</th>
                  <th class="py-2"></th>
                </tr>
              </thead>
              <tbody class="divide-y divide-stone-200 dark:divide-stone-700">
                {#each $segmentsQuery.data.items as seg (seg.id)}
                  <tr>
                    <td class="py-2 pr-4 text-stone-900 dark:text-stone-100">
                      <span class="block truncate" title={seg.recording_filename}>
                        {seg.recording_filename}
                      </span>
                    </td>
                    <td class="py-2 pr-4 text-stone-500 tabular-nums">
                      {seg.start_time_sec.toFixed(1)}–{seg.end_time_sec.toFixed(1)}
                    </td>
                    <td class="py-2 pr-4">
                      <span class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium {segmentStatusClass(seg.status)}">
                        {segmentStatusLabel(seg.status)}
                      </span>
                      {#if seg.is_empty}
                        <span class="ml-1 inline-flex items-center rounded-full bg-stone-100 px-2 py-0.5 text-xs text-stone-500 dark:bg-stone-800 dark:text-stone-400">
                          {m.annotation_sets_segment_is_empty()}
                        </span>
                      {/if}
                    </td>
                    <td class="py-2 pr-4 text-stone-500 tabular-nums">{seg.annotation_count}</td>
                    <td class="py-2 text-right">
                      <a
                        href={startAnnotatingHref(seg.id)}
                        class="inline-flex items-center gap-1 rounded-lg border border-primary-300 bg-primary-50 px-2.5 py-1 text-xs font-medium text-primary-700 transition-colors hover:bg-primary-100 dark:border-primary-700 dark:bg-primary-900/20 dark:text-primary-300 dark:hover:bg-primary-900/40"
                      >
                        {m.annotation_sets_segments_start_annotation()}
                      </a>
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      </section>

      <!-- Evaluation -->
      <section class="mt-6 rounded-xl border border-card bg-surface-card p-6 shadow-sm">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <h2 class="text-lg font-semibold text-stone-900 dark:text-stone-100">
              {m.annotation_sets_evaluation_title()}
            </h2>
            <p class="mt-1 text-sm text-stone-500">
              {m.annotation_sets_evaluation_description()}
            </p>
          </div>
          <button
            type="button"
            class="flex-shrink-0 rounded-lg bg-primary-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-primary-700"
            onclick={() => (evaluationDialogOpen = true)}
          >
            {m.annotation_sets_evaluation_run()}
          </button>
        </div>

        <div class="mt-4">
          <EvaluationRunList {setId} {projectId} />
        </div>
      </section>
    {/if}
  {/if}

  <!-- Evaluation run dialog -->
  {#if evaluationDialogOpen && detail}
    <EvaluationRunDialog
      {setId}
      {projectId}
      setStatus={detail.status}
      onClose={() => (evaluationDialogOpen = false)}
    />
  {/if}

  <!-- Delete confirmation modal -->
  {#if deleteConfirming}
    <div
      class="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="delete-title"
    >
      <div class="w-full max-w-sm rounded-xl bg-surface-card p-6 shadow-xl">
        <h2 id="delete-title" class="text-base font-semibold text-stone-900 dark:text-stone-100">
          {m.annotation_sets_detail_delete()}
        </h2>
        <p class="mt-2 text-sm text-stone-500">
          {m.annotation_sets_detail_delete_confirm()}
        </p>
        <div class="mt-5 flex justify-end gap-2">
          <button
            type="button"
            class="rounded-lg border border-stone-300 px-3 py-1.5 text-sm hover:bg-stone-50 dark:border-stone-600 dark:hover:bg-stone-800"
            onclick={() => (deleteConfirming = false)}
            disabled={$deleteMutationState.isPending}
          >
            {m.annotation_sets_create_cancel()}
          </button>
          <button
            type="button"
            class="rounded-lg bg-danger px-3 py-1.5 text-sm font-medium text-white hover:bg-danger/90 disabled:opacity-50"
            onclick={() => $deleteMutationState.mutate()}
            disabled={$deleteMutationState.isPending}
          >
            {m.annotation_sets_detail_delete()}
          </button>
        </div>
      </div>
    </div>
  {/if}
</div>
