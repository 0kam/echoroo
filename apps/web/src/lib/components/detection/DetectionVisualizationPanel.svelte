<script lang="ts">
  /**
   * DetectionVisualizationPanel - Grid of PolarHeatmap charts for multiple species.
   *
   * Displays up to 12 species by default with a toggle to show all.
   */

  import type { SpeciesTemporalData } from '$lib/types/detection';
  import PolarHeatmap from './PolarHeatmap.svelte';
  import * as m from '$lib/paraglide/messages';

  export let species: SpeciesTemporalData[];

  const DEFAULT_VISIBLE = 12;

  let showAll = false;

  $: visibleSpecies = showAll ? species : species.slice(0, DEFAULT_VISIBLE);
  $: hasMore = species.length > DEFAULT_VISIBLE;
  $: hiddenCount = species.length - DEFAULT_VISIBLE;
</script>

<div class="space-y-6">
  {#if species.length === 0}
    <div class="rounded-lg border border-stone-200 bg-stone-50 px-4 py-12 text-center">
      <svg
        class="mx-auto h-10 w-10 text-stone-300"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
        aria-hidden="true"
      >
        <path
          stroke-linecap="round"
          stroke-linejoin="round"
          stroke-width="1.5"
          d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
        />
      </svg>
      <p class="mt-3 text-sm font-medium text-stone-700">{m.detection_viz_no_activity_title()}</p>
      <p class="mt-1 text-xs text-stone-500">
        {m.detection_viz_no_activity_body()}
      </p>
    </div>
  {:else}
    <!-- Species count -->
    <p class="text-sm text-stone-500">
      {#if !showAll && hasMore}
        {m.detection_viz_showing_top({ top: DEFAULT_VISIBLE, total: species.length })}
      {:else}
        {m.detection_viz_species_detected({ count: species.length })}
      {/if}
    </p>

    <!-- Responsive grid -->
    <div class="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {#each visibleSpecies as sp (sp.tag_id)}
        <div class="rounded-lg border border-card bg-surface-card p-4 shadow-sm">
          <PolarHeatmap
            data={sp.detections}
            scientificName={sp.scientific_name}
            commonName={sp.common_name}
            totalDetections={sp.total_detections}
            size={220}
          />
        </div>
      {/each}
    </div>

    <!-- Show all / collapse toggle -->
    {#if hasMore}
      <div class="flex justify-center">
        <button
          type="button"
          on:click={() => (showAll = !showAll)}
          class="inline-flex items-center gap-1.5 rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-600 hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-emerald-400 transition-colors"
        >
          {#if showAll}
            <svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
              <path fill-rule="evenodd" d="M14.707 12.707a1 1 0 01-1.414 0L10 9.414l-3.293 3.293a1 1 0 01-1.414-1.414l4-4a1 1 0 011.414 0l4 4a1 1 0 010 1.414z" clip-rule="evenodd" />
            </svg>
            {m.detection_viz_show_fewer()}
          {:else}
            <svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
              <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd" />
            </svg>
            {m.detection_viz_show_all({ count: species.length })}
          {/if}
        </button>
      </div>
    {/if}
  {/if}
</div>
