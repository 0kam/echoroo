<script lang="ts">
  /**
   * Filter controls for the detection review list.
   * Includes status dropdown, confidence range, and species search.
   */

  import type { DetectionFilters, DetectionStatus } from '$lib/types/detection';
  import * as m from '$lib/paraglide/messages';

  export let filters: DetectionFilters;
  export let onFilterChange: (filters: DetectionFilters) => void;

  // Local editable copies of filter values
  let statusValue: DetectionStatus | '' = filters.status ?? '';
  let confidenceMin: number = filters.confidence_min !== undefined ? Math.round(filters.confidence_min * 100) : 0;
  let confidenceMax: number = filters.confidence_max !== undefined ? Math.round(filters.confidence_max * 100) : 100;
  let searchValue: string = '';

  $: statusOptions = [
    { value: '' as DetectionStatus | '', label: m.detection_filter_all_statuses() },
    { value: 'unreviewed' as DetectionStatus, label: m.detection_filter_unreviewed() },
    { value: 'confirmed' as DetectionStatus, label: m.detection_filter_confirmed() },
    { value: 'rejected' as DetectionStatus, label: m.detection_filter_rejected() },
  ];

  function emitChange() {
    const updated: DetectionFilters = { ...filters };

    if (statusValue !== '') {
      updated.status = statusValue;
    } else {
      delete updated.status;
    }

    updated.confidence_min = confidenceMin / 100;
    updated.confidence_max = confidenceMax / 100;

    onFilterChange(updated);
  }

  function handleStatusChange(event: Event) {
    statusValue = (event.target as HTMLSelectElement).value as DetectionStatus | '';
    emitChange();
  }

  function handleConfidenceMinChange(event: Event) {
    const val = parseInt((event.target as HTMLInputElement).value, 10);
    confidenceMin = Math.min(val, confidenceMax);
    emitChange();
  }

  function handleConfidenceMaxChange(event: Event) {
    const val = parseInt((event.target as HTMLInputElement).value, 10);
    confidenceMax = Math.max(val, confidenceMin);
    emitChange();
  }

  function handleSearchInput(event: Event) {
    searchValue = (event.target as HTMLInputElement).value;
    // Search is handled externally by the parent via onFilterChange with a search param
    onFilterChange({ ...filters, status: statusValue || undefined, confidence_min: confidenceMin / 100, confidence_max: confidenceMax / 100 });
  }

  function handleReset() {
    statusValue = '';
    confidenceMin = 0;
    confidenceMax = 100;
    searchValue = '';
    onFilterChange({});
  }

  $: hasActiveFilters =
    statusValue !== '' || confidenceMin > 0 || confidenceMax < 100 || searchValue !== '';
</script>

<div class="flex flex-wrap items-end gap-3 rounded-lg border border-card bg-surface-card p-4">
  <!-- Species search -->
  <div class="min-w-48 flex-1">
    <label for="species-search" class="mb-1 block text-xs font-medium text-stone-700">
      {m.detection_filter_search_species_label()}
    </label>
    <input
      id="species-search"
      type="text"
      placeholder={m.detection_filter_search_species_placeholder()}
      value={searchValue}
      on:input={handleSearchInput}
      class="w-full rounded-md border border-stone-300 px-3 py-1.5 text-sm text-stone-900 placeholder-stone-400
        focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
    />
  </div>

  <!-- Status filter -->
  <div class="min-w-40">
    <label for="status-filter" class="mb-1 block text-xs font-medium text-stone-700">
      {m.detection_filter_status_dropdown_label()}
    </label>
    <select
      id="status-filter"
      value={statusValue}
      on:change={handleStatusChange}
      class="w-full rounded-md border border-stone-300 px-3 py-1.5 text-sm text-stone-900
        focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
    >
      {#each statusOptions as opt}
        <option value={opt.value}>{opt.label}</option>
      {/each}
    </select>
  </div>

  <!-- Confidence range -->
  <div class="min-w-48 flex-1">
    <div class="mb-1 flex items-center justify-between">
      <span class="text-xs font-medium text-stone-700">{m.detection_filter_confidence_label()}</span>
      <span class="text-xs text-stone-500">{confidenceMin}% – {confidenceMax}%</span>
    </div>
    <div class="flex items-center gap-2">
      <input
        type="range"
        min="0"
        max="100"
        value={confidenceMin}
        on:input={handleConfidenceMinChange}
        class="h-1.5 w-full cursor-pointer accent-primary-600"
        aria-label={m.detection_filter_min_confidence_aria()}
      />
      <input
        type="range"
        min="0"
        max="100"
        value={confidenceMax}
        on:input={handleConfidenceMaxChange}
        class="h-1.5 w-full cursor-pointer accent-primary-600"
        aria-label={m.detection_filter_max_confidence_aria()}
      />
    </div>
  </div>

  <!-- Reset button -->
  {#if hasActiveFilters}
    <div>
      <button
        type="button"
        on:click={handleReset}
        class="rounded-md border border-stone-300 bg-surface-card px-3 py-1.5 text-sm text-stone-600
          hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-primary-500"
      >
        {m.detection_filter_reset_button()}
      </button>
    </div>
  {/if}
</div>
