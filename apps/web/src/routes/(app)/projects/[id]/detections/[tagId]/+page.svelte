<script lang="ts">
  /**
   * Detection Review page for a specific species tag.
   *
   * Displays all detections for the given species within the project,
   * with full review workflow (confirm / reject / change species).
   */

  import { page } from '$app/stores';
  import { createQuery } from '@tanstack/svelte-query';
  import { fetchSpeciesSummary } from '$lib/api/detections';
  import DetectionReviewGrid from '$lib/components/detection/DetectionReviewGrid.svelte';

  // projectId and tagId come from the URL params (always defined for this route)
  $: projectId = $page.params.id ?? '';
  $: tagId = $page.params.tagId ?? '';

  // Fetch species summary to display the species name in the page title
  $: summaryQuery = createQuery({
    queryKey: ['species-summary', projectId],
    queryFn: () => fetchSpeciesSummary(projectId),
  });

  $: speciesSummary = $summaryQuery.data?.items ?? [];
  $: currentSpecies = speciesSummary.find((s) => s.tag_id === tagId) ?? null;
  $: speciesName = currentSpecies?.tag_name ?? 'Species';
  $: scientificName = currentSpecies?.scientific_name ?? null;

  $: backUrl = `/projects/${projectId}/detections`;
</script>

<svelte:head>
  <title>{speciesName} - Detection Review - Echoroo</title>
</svelte:head>

<div class="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
  <!-- Page header -->
  <div class="mb-6 flex items-start justify-between gap-4">
    <div class="flex items-center gap-3">
      <!-- Back button -->
      <a
        href={backUrl}
        class="inline-flex items-center gap-1 rounded border border-stone-300 bg-white px-3 py-1.5 text-sm text-stone-600 hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-blue-400"
        aria-label="Back to species list"
      >
        <svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M9.707 16.707a1 1 0 01-1.414 0l-6-6a1 1 0 010-1.414l6-6a1 1 0 011.414 1.414L5.414 9H17a1 1 0 110 2H5.414l4.293 4.293a1 1 0 010 1.414z" clip-rule="evenodd" />
        </svg>
        All Species
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
          <div class="text-xs text-stone-500">Total</div>
        </div>
        <div class="h-8 w-px bg-stone-200"></div>
        <div class="text-center">
          <div class="text-lg font-semibold text-stone-500">{currentSpecies.unreviewed_count}</div>
          <div class="text-xs text-stone-500">Unreviewed</div>
        </div>
        <div class="h-8 w-px bg-stone-200"></div>
        <div class="text-center">
          <div class="text-lg font-semibold text-green-600">{currentSpecies.confirmed_count}</div>
          <div class="text-xs text-stone-500">Confirmed</div>
        </div>
        <div class="h-8 w-px bg-stone-200"></div>
        <div class="text-center">
          <div class="text-lg font-semibold text-red-600">{currentSpecies.rejected_count}</div>
          <div class="text-xs text-stone-500">Rejected</div>
        </div>
        {#if currentSpecies.avg_confidence !== null}
          <div class="h-8 w-px bg-stone-200"></div>
          <div class="text-center">
            <div class="text-lg font-semibold text-stone-800">
              {Math.round(currentSpecies.avg_confidence * 100)}%
            </div>
            <div class="text-xs text-stone-500">Avg. conf.</div>
          </div>
        {/if}
      </div>
    {/if}
  </div>

  <!-- Detection review grid -->
  <DetectionReviewGrid {projectId} {tagId} />
</div>
