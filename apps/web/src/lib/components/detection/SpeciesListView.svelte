<script lang="ts">
  /**
   * Species detection summary list view.
   * Fetches species statistics via TanStack Query and renders
   * a filterable, searchable list of SpeciesListItem rows.
   */

  import { createQuery } from '@tanstack/svelte-query';
  import { fetchSpeciesSummary } from '$lib/api/detections';
  import type { DetectionFilters } from '$lib/types/detection';
  import SpeciesListItem from './SpeciesListItem.svelte';
  import DetectionFiltersComponent from './DetectionFilters.svelte';

  export let projectId: string;

  let filters: DetectionFilters = {};
  let searchText: string = '';

  $: speciesSummaryQuery = createQuery({
    queryKey: ['species-summary', projectId, searchText],
    queryFn: () =>
      fetchSpeciesSummary(projectId, {
        search: searchText || undefined,
      }),
    enabled: !!projectId,
  });

  function handleFilterChange(newFilters: DetectionFilters) {
    filters = newFilters;
  }

  // Client-side filter by status so we can also use confidence range from filters
  $: filteredItems = (() => {
    const items = $speciesSummaryQuery.data?.items ?? [];
    return items.filter((species) => {
      if (filters.status) {
        // Filter species that have at least one detection of the given status
        if (filters.status === 'confirmed' && species.confirmed_count === 0) return false;
        if (filters.status === 'rejected' && species.rejected_count === 0) return false;
        if (filters.status === 'unreviewed' && species.unreviewed_count === 0) return false;
      }
      if (filters.confidence_min !== undefined && species.avg_confidence !== null) {
        if (species.avg_confidence < filters.confidence_min) return false;
      }
      if (filters.confidence_max !== undefined && species.avg_confidence !== null) {
        if (species.avg_confidence > filters.confidence_max) return false;
      }
      return true;
    });
  })();

  // Extract search text from the filter change callback
  function handleFilterChangeWithSearch(newFilters: DetectionFilters & { _search?: string }) {
    filters = newFilters;
  }

  // We drive search through the query key via a separate input
  function handleSearchChange(event: Event) {
    searchText = (event.target as HTMLInputElement).value;
  }
</script>

<div class="space-y-4">
  <!-- Filter bar -->
  <DetectionFiltersComponent {filters} onFilterChange={handleFilterChangeWithSearch} />

  <!-- Header with total count -->
  <div class="flex items-center justify-between">
    <div class="text-sm text-gray-600">
      {#if $speciesSummaryQuery.isLoading}
        Loading species...
      {:else if $speciesSummaryQuery.data}
        {#if filteredItems.length !== $speciesSummaryQuery.data.total_species}
          Showing {filteredItems.length} of {$speciesSummaryQuery.data.total_species} species
        {:else}
          {$speciesSummaryQuery.data.total_species}
          {$speciesSummaryQuery.data.total_species === 1 ? 'species' : 'species'} detected
        {/if}
      {/if}
    </div>
  </div>

  <!-- Content -->
  {#if $speciesSummaryQuery.isLoading}
    <div class="space-y-2">
      {#each { length: 5 } as _}
        <div class="h-16 animate-pulse rounded-lg bg-gray-100"></div>
      {/each}
    </div>
  {:else if $speciesSummaryQuery.isError}
    <div class="rounded-lg border border-red-200 bg-red-50 px-4 py-6 text-center">
      <p class="text-sm font-medium text-red-700">Failed to load species detections</p>
      <p class="mt-1 text-xs text-red-500">
        {$speciesSummaryQuery.error?.message ?? 'An unexpected error occurred'}
      </p>
      <button
        type="button"
        on:click={() => $speciesSummaryQuery.refetch()}
        class="mt-3 rounded-md bg-red-100 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-200"
      >
        Retry
      </button>
    </div>
  {:else if filteredItems.length === 0}
    <div class="rounded-lg border border-gray-200 bg-white px-4 py-12 text-center">
      {#if $speciesSummaryQuery.data?.total_species === 0}
        <p class="text-sm font-medium text-gray-900">No detections yet</p>
        <p class="mt-1 text-xs text-gray-500">
          Run a detection model or add detections manually to get started.
        </p>
      {:else}
        <p class="text-sm font-medium text-gray-900">No species match the current filters</p>
        <p class="mt-1 text-xs text-gray-500">Try adjusting your search or filter criteria.</p>
      {/if}
    </div>
  {:else}
    <div class="space-y-2">
      {#each filteredItems as species (species.tag_id)}
        <SpeciesListItem {species} {projectId} isSelected={false} />
      {/each}
    </div>
  {/if}
</div>
