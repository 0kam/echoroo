<script lang="ts">
  /**
   * A single row in the species detection summary list.
   * Shows species name, detection count, confidence, and review progress.
   */

  import { goto } from '$app/navigation';
  import type { SpeciesSummary } from '$lib/types/detection';

  export let species: SpeciesSummary;
  export let projectId: string;
  export let isSelected: boolean = false;

  $: confirmedPct =
    species.total_count > 0 ? (species.confirmed_count / species.total_count) * 100 : 0;
  $: rejectedPct =
    species.total_count > 0 ? (species.rejected_count / species.total_count) * 100 : 0;
  $: unreviewedPct =
    species.total_count > 0 ? (species.unreviewed_count / species.total_count) * 100 : 0;

  $: avgConfidencePct =
    species.avg_confidence !== null ? Math.round(species.avg_confidence * 100) : null;

  function handleClick() {
    goto(`/projects/${projectId}/detections/${species.tag_id}`);
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      handleClick();
    }
  }
</script>

<div
  role="button"
  tabindex="0"
  class="flex cursor-pointer items-center gap-4 rounded-lg border px-4 py-3 transition-colors
    {isSelected
    ? 'border-blue-300 bg-blue-50'
    : 'border-gray-200 bg-white hover:border-gray-300 hover:bg-gray-50'}"
  on:click={handleClick}
  on:keydown={handleKeydown}
>
  <!-- Species names -->
  <div class="min-w-0 flex-1">
    <div class="flex items-baseline gap-2">
      <span class="truncate text-sm font-semibold text-gray-900">{species.common_name ?? species.tag_name}</span>
      {#if species.scientific_name}
        <span class="truncate text-xs italic text-gray-500">{species.scientific_name}</span>
      {/if}
    </div>

    <!-- Review progress bar -->
    <div class="mt-2 flex h-1.5 w-full overflow-hidden rounded-full bg-gray-100">
      {#if confirmedPct > 0}
        <div
          class="h-full bg-green-500"
          style="width: {confirmedPct}%"
          title="Confirmed: {species.confirmed_count}"
        ></div>
      {/if}
      {#if rejectedPct > 0}
        <div
          class="h-full bg-red-400"
          style="width: {rejectedPct}%"
          title="Rejected: {species.rejected_count}"
        ></div>
      {/if}
      {#if unreviewedPct > 0}
        <div
          class="h-full bg-gray-200"
          style="width: {unreviewedPct}%"
          title="Unreviewed: {species.unreviewed_count}"
        ></div>
      {/if}
    </div>

    <!-- Progress counts -->
    <div class="mt-1 flex gap-3 text-xs text-gray-500">
      {#if species.confirmed_count > 0}
        <span class="text-green-600">{species.confirmed_count} confirmed</span>
      {/if}
      {#if species.rejected_count > 0}
        <span class="text-red-500">{species.rejected_count} rejected</span>
      {/if}
      {#if species.unreviewed_count > 0}
        <span>{species.unreviewed_count} unreviewed</span>
      {/if}
    </div>
  </div>

  <!-- Stats -->
  <div class="flex flex-shrink-0 items-center gap-4 text-right">
    <!-- Total count -->
    <div>
      <div class="text-sm font-semibold text-gray-900">{species.total_count}</div>
      <div class="text-xs text-gray-500">detections</div>
    </div>

    <!-- Avg confidence -->
    <div>
      {#if avgConfidencePct !== null}
        <div class="text-sm font-semibold text-gray-900">{avgConfidencePct}%</div>
      {:else}
        <div class="text-sm text-gray-400">—</div>
      {/if}
      <div class="text-xs text-gray-500">avg conf.</div>
    </div>

    <!-- Chevron -->
    <svg class="h-4 w-4 flex-shrink-0 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
    </svg>
  </div>
</div>
