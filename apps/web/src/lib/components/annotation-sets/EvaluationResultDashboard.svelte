<script lang="ts">
  /**
   * Cross-model evaluation result dashboard.
   *
   * Displays an EvaluationSummary grouped by model reference:
   *   1. Summary table (precision / recall / F1 + TP/FP/FN per model).
   *   2. Per-species breakdown as a species x model matrix with F1 values
   *      rendered as a heatmap. Shows top-N by total occurrences with a
   *      "show all" toggle.
   *
   * No external chart library is used — all visualisation is CSS + inline
   * SVG to keep the bundle light.
   */
  import { createQuery } from '@tanstack/svelte-query';
  import * as m from '$lib/paraglide/messages';
  import { getEvaluationRun } from '$lib/api/annotation-sets';
  import type {
    EvaluationModelRef,
    EvaluationSummary,
    SpeciesMetric,
  } from '$lib/types/annotation-set';
  import type { CustomModelListItem } from '$lib/types/custom-model';
  import { fetchCustomModels } from '$lib/api/custom-models';

  interface Props {
    evaluationRunId: string;
    projectId: string;
  }

  const { evaluationRunId, projectId }: Props = $props();

  const TOP_N_SPECIES = 20;

  // ------------------------------------------------------------
  // Data
  // ------------------------------------------------------------

  const summaryQuery = $derived(
    createQuery({
      queryKey: ['evaluation-run', evaluationRunId],
      queryFn: () => getEvaluationRun(projectId, evaluationRunId),
      enabled: !!evaluationRunId,
      refetchOnWindowFocus: false,
      refetchInterval: (query): number | false => {
        const d = query.state.data as EvaluationSummary | undefined;
        return d && (d.status === 'pending' || d.status === 'running')
          ? 3000
          : false;
      },
    }),
  );

  const summary = $derived<EvaluationSummary | null>($summaryQuery.data ?? null);

  // Custom model name lookup — for pretty labels.
  const customModelsQuery = $derived(
    createQuery({
      queryKey: ['custom-models-name-lookup', projectId],
      queryFn: () => fetchCustomModels(projectId, { limit: 500 }),
      refetchOnWindowFocus: false,
    }),
  );

  const customModelsById = $derived<Record<string, CustomModelListItem>>(
    Object.fromEntries(
      ($customModelsQuery.data?.models ?? []).map((m) => [m.id, m]),
    ),
  );

  function modelRefLabel(ref: EvaluationModelRef): string {
    switch (ref.kind) {
      case 'birdnet':
        return m.evaluation_dialog_model_birdnet();
      case 'perch':
        return m.evaluation_dialog_model_perch();
      case 'custom': {
        const match = customModelsById[ref.model_id];
        return match?.name ?? m.evaluation_dashboard_custom_model_unknown();
      }
    }
  }

  // Stable colour per model index (Rosé Pine accent rotation).
  const MODEL_COLOURS = [
    '#d7827e', // rose (primary)
    '#9ccfd8', // foam
    '#f6c177', // gold
    '#31748f', // pine
    '#c4a7e7', // iris
    '#ebbcba', // rose soft
  ];

  function modelColour(index: number): string {
    return MODEL_COLOURS[index % MODEL_COLOURS.length] as string;
  }

  // ------------------------------------------------------------
  // Formatting helpers
  // ------------------------------------------------------------

  function fmt(value: number | null | undefined): string {
    if (value === null || value === undefined || Number.isNaN(value)) {
      return m.evaluation_dashboard_no_data();
    }
    return value.toFixed(2);
  }

  function fmtInt(value: number | null | undefined): string {
    if (value === null || value === undefined) {
      return m.evaluation_dashboard_no_data();
    }
    return String(value);
  }

  function speciesDisplay(row: SpeciesMetric): string {
    if (row.common_name) {
      return `${row.common_name} (${row.scientific_name ?? ''})`.trim();
    }
    if (row.scientific_name) return row.scientific_name;
    return m.evaluation_dashboard_species_name_fallback();
  }

  /** Map F1 [0,1] to a colour ramp red -> yellow -> green. */
  function f1Colour(value: number | null | undefined): string {
    if (value === null || value === undefined || Number.isNaN(value)) {
      return 'transparent';
    }
    const v = Math.max(0, Math.min(1, value));
    // Map: 0 -> red (Love #eb6f92), 0.5 -> gold (#f6c177), 1 -> pine (#31748f-green).
    // Use CSS hsl for smooth ramp.
    // 0   -> hue 0   (red)
    // 0.5 -> hue 45  (amber)
    // 1   -> hue 140 (green)
    const hue = v * 140;
    const lightness = 70 - v * 15; // brighter for low, darker-saturated for high
    return `hsl(${hue}, 65%, ${lightness}%)`;
  }

  /** Sort species rows by descending total occurrences for ranking. */
  function totalCount(row: SpeciesMetric): number {
    return Math.max(row.detections_total, row.ground_truths_total);
  }

  // ------------------------------------------------------------
  // Species matrix: union of all species across models, ranked by frequency
  // ------------------------------------------------------------

  interface MatrixRow {
    taxon_id: string;
    label: string;
    /** Max occurrence count across models, for ranking. */
    rank: number;
    /** Map: model index -> SpeciesMetric or undefined. */
    perModel: Array<SpeciesMetric | undefined>;
  }

  let showAllSpecies = $state(false);

  const matrixRows = $derived.by<MatrixRow[]>(() => {
    if (!summary) return [];
    const models = summary.models;
    const byTaxon = new Map<string, MatrixRow>();

    models.forEach((model, idx) => {
      for (const row of model.species) {
        const existing = byTaxon.get(row.taxon_id);
        if (existing) {
          existing.perModel[idx] = row;
          existing.rank = Math.max(existing.rank, totalCount(row));
        } else {
          const perModel = new Array<SpeciesMetric | undefined>(models.length).fill(
            undefined,
          );
          perModel[idx] = row;
          byTaxon.set(row.taxon_id, {
            taxon_id: row.taxon_id,
            label: speciesDisplay(row),
            rank: totalCount(row),
            perModel,
          });
        }
      }
    });

    return Array.from(byTaxon.values()).sort((a, b) => b.rank - a.rank);
  });

  const visibleRows = $derived<MatrixRow[]>(
    showAllSpecies ? matrixRows : matrixRows.slice(0, TOP_N_SPECIES),
  );
</script>

<div>
  {#if $summaryQuery.isLoading}
    <p class="text-sm text-stone-400">{m.evaluation_dashboard_loading()}</p>
  {:else if $summaryQuery.isError}
    <div
      class="rounded-lg border border-danger/30 bg-danger-light p-3 text-sm text-danger"
    >
      {m.evaluation_dashboard_error()}
    </div>
  {:else if !summary}
    <p class="text-sm text-stone-400">{m.evaluation_dashboard_loading()}</p>
  {:else if summary.status === 'failed'}
    <div
      class="rounded-lg border border-danger/30 bg-danger-light p-3 text-sm text-danger"
    >
      <strong>{m.evaluation_run_error_prefix()}:</strong>
      {summary.error_message ?? m.evaluation_dashboard_error()}
    </div>
  {:else if summary.status === 'pending' || summary.status === 'running'}
    <p class="text-sm text-stone-500">{m.evaluation_dashboard_pending()}</p>
  {:else if summary.models.length === 0}
    <p class="text-sm text-stone-400">{m.evaluation_dashboard_species_empty()}</p>
  {:else}
    <!-- Summary table -->
    <section>
      <h3 class="text-sm font-semibold text-stone-900 dark:text-stone-100">
        {m.evaluation_dashboard_summary_title()}
      </h3>
      <p class="mt-0.5 text-xs text-stone-500">
        {m.evaluation_dashboard_summary_description()}
      </p>

      <div class="mt-3 overflow-x-auto">
        <table class="min-w-full text-sm">
          <thead
            class="text-left text-xs font-semibold uppercase tracking-wider text-stone-500"
          >
            <tr class="border-b border-stone-200 dark:border-stone-700">
              <th class="py-2 pr-4">{m.evaluation_dashboard_column_model()}</th>
              <th
                class="py-2 pr-4 text-right tabular-nums"
                title={m.evaluation_dashboard_tooltip_precision()}
              >
                {m.evaluation_dashboard_column_precision()}
              </th>
              <th
                class="py-2 pr-4 text-right tabular-nums"
                title={m.evaluation_dashboard_tooltip_recall()}
              >
                {m.evaluation_dashboard_column_recall()}
              </th>
              <th
                class="py-2 pr-4 text-right tabular-nums"
                title={m.evaluation_dashboard_tooltip_f1()}
              >
                {m.evaluation_dashboard_column_f1()}
              </th>
              <th
                class="py-2 pr-4 text-right tabular-nums"
                title={m.evaluation_dashboard_tooltip_tp_p()}
              >
                {m.evaluation_dashboard_column_tp_p()}
              </th>
              <th
                class="py-2 pr-4 text-right tabular-nums"
                title={m.evaluation_dashboard_tooltip_fp()}
              >
                {m.evaluation_dashboard_column_fp()}
              </th>
              <th
                class="py-2 pr-4 text-right tabular-nums"
                title={m.evaluation_dashboard_tooltip_tp_r()}
              >
                {m.evaluation_dashboard_column_tp_r()}
              </th>
              <th
                class="py-2 pr-4 text-right tabular-nums"
                title={m.evaluation_dashboard_tooltip_fn()}
              >
                {m.evaluation_dashboard_column_fn()}
              </th>
              <th class="py-2 pr-4 text-right tabular-nums">
                {m.evaluation_dashboard_column_detections()}
              </th>
              <th class="py-2 text-right tabular-nums">
                {m.evaluation_dashboard_column_ground_truths()}
              </th>
            </tr>
          </thead>
          <tbody class="divide-y divide-stone-200 dark:divide-stone-700">
            {#each summary.models as model, idx (idx)}
              {@const noData = model.overall.detections_total === 0 && model.overall.ground_truths_total === 0}
              <tr>
                <td class="py-2 pr-4 align-top">
                  <div class="flex items-center gap-2">
                    <span
                      class="inline-block h-3 w-3 flex-shrink-0 rounded-sm"
                      style:background-color={modelColour(idx)}
                      aria-hidden="true"
                    ></span>
                    <span class="font-medium text-stone-900 dark:text-stone-100">
                      {modelRefLabel(model.model_ref)}
                    </span>
                  </div>
                </td>
                <td class="py-2 pr-4 text-right tabular-nums">
                  {fmt(model.overall.precision)}
                </td>
                <td class="py-2 pr-4 text-right tabular-nums">
                  {fmt(model.overall.recall)}
                </td>
                <td
                  class="py-2 pr-4 text-right font-semibold tabular-nums"
                  style:background-color={f1Colour(model.overall.f1)}
                  style:color="#1c1917"
                >
                  {fmt(model.overall.f1)}
                </td>
                <td class="py-2 pr-4 text-right tabular-nums text-stone-500">
                  {fmtInt(model.overall.tp_precision)}
                </td>
                <td class="py-2 pr-4 text-right tabular-nums text-stone-500">
                  {fmtInt(model.overall.fp)}
                </td>
                <td class="py-2 pr-4 text-right tabular-nums text-stone-500">
                  {fmtInt(model.overall.tp_recall)}
                </td>
                <td class="py-2 pr-4 text-right tabular-nums text-stone-500">
                  {fmtInt(model.overall.fn)}
                </td>
                <td class="py-2 pr-4 text-right tabular-nums text-stone-500">
                  {fmtInt(model.overall.detections_total)}
                </td>
                <td class="py-2 text-right tabular-nums text-stone-500">
                  {fmtInt(model.overall.ground_truths_total)}
                </td>
              </tr>
              {#if noData}
                <tr>
                  <td colspan="10" class="py-1 pr-4 text-xs text-stone-400">
                    {m.evaluation_dashboard_empty_model()}
                  </td>
                </tr>
              {/if}
            {/each}
          </tbody>
        </table>
      </div>
    </section>

    <!-- Per-species matrix -->
    {#if matrixRows.length > 0}
      <section class="mt-6">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <h3 class="text-sm font-semibold text-stone-900 dark:text-stone-100">
              {m.evaluation_dashboard_species_title()}
            </h3>
            <p class="mt-0.5 text-xs text-stone-500">
              {m.evaluation_dashboard_species_description()}
            </p>
          </div>
          {#if matrixRows.length > TOP_N_SPECIES}
            <button
              type="button"
              class="flex-shrink-0 rounded-lg border border-stone-300 px-2.5 py-1 text-xs font-medium hover:bg-stone-50 dark:border-stone-600 dark:hover:bg-stone-800"
              onclick={() => (showAllSpecies = !showAllSpecies)}
            >
              {showAllSpecies
                ? m.evaluation_dashboard_show_top_species({
                    count: String(TOP_N_SPECIES),
                  })
                : m.evaluation_dashboard_show_all_species({
                    count: String(matrixRows.length),
                  })}
            </button>
          {/if}
        </div>

        <div class="mt-3 overflow-x-auto">
          <table class="min-w-full text-xs">
            <thead
              class="text-left text-xs font-semibold uppercase tracking-wider text-stone-500"
            >
              <tr class="border-b border-stone-200 dark:border-stone-700">
                <th class="py-2 pr-4">
                  {m.evaluation_dashboard_column_species()}
                </th>
                {#each summary.models as model, idx (idx)}
                  <th class="py-2 px-2 text-center" scope="col">
                    <div class="flex items-center justify-center gap-1.5">
                      <span
                        class="inline-block h-2.5 w-2.5 rounded-sm"
                        style:background-color={modelColour(idx)}
                        aria-hidden="true"
                      ></span>
                      <span class="truncate max-w-[8rem]" title={modelRefLabel(model.model_ref)}>
                        {modelRefLabel(model.model_ref)}
                      </span>
                    </div>
                  </th>
                {/each}
              </tr>
            </thead>
            <tbody class="divide-y divide-stone-100 dark:divide-stone-800">
              {#each visibleRows as row (row.taxon_id)}
                <tr>
                  <th
                    scope="row"
                    class="py-1.5 pr-4 text-left font-normal text-stone-900 dark:text-stone-100"
                  >
                    <span class="block truncate" title={row.label}>{row.label}</span>
                  </th>
                  {#each row.perModel as cell, idx (idx)}
                    {#if cell}
                      <td
                        class="py-1.5 px-2 text-center tabular-nums"
                        style:background-color={f1Colour(cell.f1)}
                        style:color="#1c1917"
                        title={`P=${fmt(cell.precision)} R=${fmt(cell.recall)} TP=${fmtInt(cell.tp_precision)}/${fmtInt(cell.tp_recall)} FP=${fmtInt(cell.fp)} FN=${fmtInt(cell.fn)}`}
                      >
                        {fmt(cell.f1)}
                      </td>
                    {:else}
                      <td class="py-1.5 px-2 text-center text-stone-300 dark:text-stone-600">
                        {m.evaluation_dashboard_no_data()}
                      </td>
                    {/if}
                  {/each}
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      </section>
    {/if}
  {/if}
</div>
