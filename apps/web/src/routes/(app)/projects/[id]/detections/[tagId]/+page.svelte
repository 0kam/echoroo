<script lang="ts">
  /**
   * Detection Review page for a specific species tag.
   *
   * Displays:
   * - Species header with review statistics
   * - Collapsible "Activity Pattern" section with a PolarHeatmap
   * - Detection review grid (confirm / reject / change species)
   */

  import { page } from '$app/stores';
  import { createQuery } from '@tanstack/svelte-query';
  import { fetchSpeciesSummary, fetchTemporalData } from '$lib/api/detections';
  import { localizeHref, getLocale } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import DetectionReviewGrid from '$lib/components/detection/DetectionReviewGrid.svelte';
  import PolarHeatmap from '$lib/components/detection/PolarHeatmap.svelte';

  // projectId and tagId come from the URL params (always defined for this route)
  $: projectId = $page.params.id ?? '';
  $: tagId = $page.params.tagId ?? '';
  $: locale = getLocale();

  // Fetch species summary to display the species name in the page title
  $: summaryQuery = createQuery({
    queryKey: ['species-summary', projectId, locale],
    queryFn: () => fetchSpeciesSummary(projectId, { locale }),
  });

  $: speciesSummary = $summaryQuery.data?.items ?? [];
  $: currentSpecies = speciesSummary.find((s) => s.tag_id === tagId) ?? null;
  $: speciesName = currentSpecies?.common_name ?? currentSpecies?.tag_name ?? 'Species';
  $: scientificName = currentSpecies?.scientific_name ?? null;

  $: backUrl = localizeHref(`/projects/${projectId}/detections`);

  // Activity pattern section
  let activityExpanded = false;

  // Fetch temporal data only when the section is expanded
  $: temporalQuery = createQuery({
    queryKey: ['temporal-data', projectId, locale],
    queryFn: () => fetchTemporalData(projectId, undefined, locale),
    enabled: !!projectId && activityExpanded,
  });

  // Find the temporal data entry for this species
  $: speciesTemporalData = $temporalQuery.data?.species.find((s) => s.tag_id === tagId) ?? null;
</script>

<svelte:head>
  <title>{speciesName} - {m.detection_heading()} - Echoroo</title>
</svelte:head>

<div class="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
  <!-- Page header -->
  <div class="mb-6 flex items-start justify-between gap-4">
    <div class="flex items-center gap-3">
      <!-- Back button -->
      <a
        href={backUrl}
        class="inline-flex items-center gap-1 rounded border border-stone-300 bg-white px-3 py-1.5 text-sm text-stone-600 hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-blue-400"
        aria-label={m.detection_all_species_back()}
      >
        <svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M9.707 16.707a1 1 0 01-1.414 0l-6-6a1 1 0 010-1.414l6-6a1 1 0 011.414 1.414L5.414 9H17a1 1 0 110 2H5.414l4.293 4.293a1 1 0 010 1.414z" clip-rule="evenodd" />
        </svg>
        {m.detection_all_species_back()}
      </a>

      <!-- Species name -->
      <div>
        <h1 class="text-2xl font-bold text-stone-900">
          {speciesName}
        </h1>
        {#if scientificName}
          <p class="mt-0.5 text-sm italic text-stone-500">{scientificName}</p>
        {/if}
      </div>
    </div>

    <!-- Summary stats -->
    {#if currentSpecies}
      <div class="flex items-center gap-4 rounded-lg border border-stone-200 bg-stone-50 px-4 py-2.5">
        <div class="text-center">
          <div class="text-lg font-semibold text-stone-800">{currentSpecies.total_count}</div>
          <div class="text-xs text-stone-500">{m.detection_total_label()}</div>
        </div>
        <div class="h-8 w-px bg-stone-200"></div>
        <div class="text-center">
          <div class="text-lg font-semibold text-stone-500">{currentSpecies.unreviewed_count}</div>
          <div class="text-xs text-stone-500">{m.detection_unreviewed_label()}</div>
        </div>
        <div class="h-8 w-px bg-stone-200"></div>
        <div class="text-center">
          <div class="text-lg font-semibold text-green-600">{currentSpecies.confirmed_count}</div>
          <div class="text-xs text-stone-500">{m.detection_confirmed_label()}</div>
        </div>
        <div class="h-8 w-px bg-stone-200"></div>
        <div class="text-center">
          <div class="text-lg font-semibold text-red-600">{currentSpecies.rejected_count}</div>
          <div class="text-xs text-stone-500">{m.detection_rejected_label()}</div>
        </div>
        {#if currentSpecies.avg_confidence !== null}
          <div class="h-8 w-px bg-stone-200"></div>
          <div class="text-center">
            <div class="text-lg font-semibold text-stone-800">
              {Math.round(currentSpecies.avg_confidence * 100)}%
            </div>
            <div class="text-xs text-stone-500">{m.detection_avg_confidence_label()}</div>
          </div>
        {/if}
      </div>
    {/if}
  </div>

  <!-- Activity Pattern collapsible section -->
  <div class="mb-6 overflow-hidden rounded-lg border border-stone-200 bg-white">
    <button
      type="button"
      on:click={() => (activityExpanded = !activityExpanded)}
      class="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-emerald-400 transition-colors"
      aria-expanded={activityExpanded}
    >
      <div class="flex items-center gap-2">
        <svg
          class="h-4 w-4 text-emerald-600"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
          />
        </svg>
        <span class="text-sm font-medium text-stone-700">{m.detection_activity_pattern_section()}</span>
      </div>
      <svg
        class="h-4 w-4 text-stone-400 transition-transform duration-200 {activityExpanded ? 'rotate-180' : ''}"
        viewBox="0 0 20 20"
        fill="currentColor"
        aria-hidden="true"
      >
        <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd" />
      </svg>
    </button>

    {#if activityExpanded}
      <div class="border-t border-stone-100 px-4 py-6">
        {#if $temporalQuery.isLoading}
          <div class="flex items-center justify-center py-8">
            <div class="flex items-center gap-3 text-stone-500">
              <svg class="h-5 w-5 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span class="text-sm">{m.detection_loading_activity_pattern()}</span>
            </div>
          </div>
        {:else if $temporalQuery.isError}
          <div class="rounded-lg border border-red-200 bg-red-50 px-4 py-4 text-center">
            <p class="text-sm font-medium text-red-700">{m.detection_activity_pattern_load_error()}</p>
            <p class="mt-1 text-xs text-red-500">
              {$temporalQuery.error?.message ?? m.common_error_unexpected()}
            </p>
            <button
              type="button"
              on:click={() => $temporalQuery.refetch()}
              class="mt-3 rounded-md bg-red-100 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-200"
            >
              {m.detection_retry()}
            </button>
          </div>
        {:else if speciesTemporalData}
          <div class="flex justify-center">
            <PolarHeatmap
              data={speciesTemporalData.detections}
              scientificName={speciesTemporalData.scientific_name}
              commonName={speciesTemporalData.common_name}
              totalDetections={speciesTemporalData.total_detections}
              size={320}
            />
          </div>
        {:else if $temporalQuery.isSuccess}
          <div class="py-6 text-center text-sm text-stone-500">
            {m.detection_no_activity_data()}
          </div>
        {/if}
      </div>
    {/if}
  </div>

  <!-- Detection review grid -->
  <DetectionReviewGrid {projectId} {tagId} />
</div>
