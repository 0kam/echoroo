<script lang="ts">
  /**
   * A single row in the species detection summary list.
   * Shows species name, detection count, confidence, and review progress.
   */

  import { goto } from '$app/navigation';
  import type { SpeciesSummary } from '$lib/types/detection';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import { displaySpeciesName } from '$lib/utils/speciesFormatters';

  let {
    species,
    projectId,
    isSelected = false,
    detectionRunId = undefined,
  }: {
    species: SpeciesSummary;
    projectId: string;
    isSelected?: boolean;
    detectionRunId?: string;
  } = $props();

  // Build the shared "common (scientific)" label. Prefer the backend-resolved
  // vernacular name for the active locale, then the English common name, then
  // the raw tag label. `SpeciesSummary` uses `tag_name`, so we remap it here.
  const displayName = $derived(
    displaySpeciesName({
      vernacular_name: species.vernacular_name,
      common_name: species.common_name,
      name: species.tag_name,
      scientific_name: species.scientific_name,
    }),
  );

  const confirmedPct = $derived(
    species.total_count > 0 ? (species.confirmed_count / species.total_count) * 100 : 0
  );
  const rejectedPct = $derived(
    species.total_count > 0 ? (species.rejected_count / species.total_count) * 100 : 0
  );
  const unreviewedPct = $derived(
    species.total_count > 0 ? (species.unreviewed_count / species.total_count) * 100 : 0
  );

  const avgConfidencePct = $derived(
    species.avg_confidence !== null ? Math.round(species.avg_confidence * 100) : null
  );

  function handleClick() {
    const base = `/projects/${projectId}/detections/${species.tag_id}`;
    const url = detectionRunId ? `${base}?run=${encodeURIComponent(detectionRunId)}` : base;
    goto(localizeHref(url));
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
    ? 'border-primary-300 bg-primary-50'
    : 'border-card bg-surface-card hover:border-stone-300 hover:bg-stone-50'}"
  onclick={handleClick}
  onkeydown={handleKeydown}
>
  <!-- Species name (common + scientific via shared formatter) -->
  <div class="min-w-0 flex-1">
    <div class="flex items-baseline gap-2">
      <span class="truncate text-sm font-semibold text-stone-900" title={displayName}>{displayName}</span>
    </div>

    <!-- Review progress bar -->
    <div class="mt-2 flex h-1.5 w-full overflow-hidden rounded-full bg-stone-100">
      {#if confirmedPct > 0}
        <div
          class="h-full bg-success"
          style="width: {confirmedPct}%"
          title="{m.detection_confirmed_label()}: {species.confirmed_count}"
        ></div>
      {/if}
      {#if rejectedPct > 0}
        <div
          class="h-full bg-danger/70"
          style="width: {rejectedPct}%"
          title="{m.detection_rejected_label()}: {species.rejected_count}"
        ></div>
      {/if}
      {#if unreviewedPct > 0}
        <div
          class="h-full bg-stone-200"
          style="width: {unreviewedPct}%"
          title="{m.detection_unreviewed_label()}: {species.unreviewed_count}"
        ></div>
      {/if}
    </div>

    <!-- Progress counts -->
    <div class="mt-1 flex gap-3 text-xs text-stone-500">
      {#if species.confirmed_count > 0}
        <span class="text-success">{species.confirmed_count} {m.detection_status_confirmed()}</span>
      {/if}
      {#if species.rejected_count > 0}
        <span class="text-danger">{species.rejected_count} {m.detection_status_rejected()}</span>
      {/if}
      {#if species.unreviewed_count > 0}
        <span>{species.unreviewed_count} {m.detection_status_unreviewed()}</span>
      {/if}
    </div>
  </div>

  <!-- Stats -->
  <div class="flex flex-shrink-0 items-center gap-4 text-right">
    <!-- Total count -->
    <div>
      <div class="text-sm font-semibold text-stone-900">{species.total_count}</div>
      <div class="text-xs text-stone-500">{m.detection_total_label()}</div>
    </div>

    <!-- Avg confidence -->
    <div>
      {#if avgConfidencePct !== null}
        <div class="text-sm font-semibold text-stone-900">{avgConfidencePct}%</div>
      {:else}
        <div class="text-sm text-stone-400">—</div>
      {/if}
      <div class="text-xs text-stone-500">{m.detection_avg_confidence_label()}</div>
    </div>

    <!-- Chevron -->
    <svg class="h-4 w-4 flex-shrink-0 text-stone-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
    </svg>
  </div>
</div>
