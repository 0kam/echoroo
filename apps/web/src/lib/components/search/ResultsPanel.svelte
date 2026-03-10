<script lang="ts">
  /**
   * ResultsPanel - Displays batch similarity search results grouped by species.
   *
   * Shows skeleton loading during search, an empty state when no matches are found,
   * and collapsible SpeciesResultGroup components for each species result.
   */

  import * as m from '$lib/paraglide/messages.js';
  import type { SpeciesMatchResult, TargetSpecies } from '$lib/types/search';
  import SpeciesResultGroup from './SpeciesResultGroup.svelte';

  interface Props {
    projectId: string;
    results: Record<string, SpeciesMatchResult> | null;
    totalMatches: number;
    searchDurationMs: number;
    isSearching: boolean;
    searchingSpecies: TargetSpecies[];
  }

  let {
    projectId,
    results,
    totalMatches,
    searchDurationMs,
    isSearching,
    searchingSpecies,
  }: Props = $props();
</script>

<div class="rounded-lg border border-card bg-surface-card shadow-sm">
  <!-- Panel header -->
  <div class="flex items-center justify-between border-b border-card px-4 py-4">
    <h2 class="text-lg font-semibold text-stone-900">{m.search_results_title()}</h2>
    {#if isSearching}
      <span class="text-sm text-stone-400">{m.search_searching()}</span>
    {:else if results !== null}
      <span class="text-sm text-stone-400">
        {m.search_results_total({ count: totalMatches.toString() })}
      </span>
    {/if}
  </div>

  <div class="space-y-4 p-4">
    {#if isSearching}
      <!-- Skeleton loading state: one placeholder row per species being searched -->
      {#each searchingSpecies as sp (sp.id)}
        <div class="rounded-lg border-l-[3px] border-l-primary-400 bg-surface-page p-3">
          <p class="text-sm font-semibold italic text-stone-700">{sp.scientific_name}</p>
          <div class="mt-2 space-y-2">
            {#each { length: 3 } as _}
              <div class="flex animate-pulse items-center gap-3">
                <div class="h-4 w-4 rounded bg-stone-200"></div>
                <div class="h-4 flex-1 rounded bg-stone-200"></div>
                <div class="h-4 w-12 rounded bg-stone-200"></div>
              </div>
            {/each}
          </div>
        </div>
      {/each}
    {:else if results !== null}
      {#if totalMatches === 0}
        <!-- No results across all species -->
        <div class="py-8 text-center text-stone-400">
          <!-- Music note icon -->
          <svg
            class="mx-auto mb-3 h-12 w-12 opacity-50"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            stroke-width="1.5"
            aria-hidden="true"
          >
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
          </svg>
          <p class="font-medium">{m.search_results_no_matches()}</p>
          <p class="mt-1 text-sm">{m.search_results_no_matches_hint()}</p>
        </div>
      {:else}
        <!-- Species result groups -->
        {#each Object.entries(results) as [tagId, group] (tagId)}
          <SpeciesResultGroup {projectId} {tagId} {group} />
        {/each}

        <!-- Search timing -->
        <p class="text-right text-xs text-stone-400">
          {m.search_search_duration({ ms: searchDurationMs.toString() })}
        </p>
      {/if}
    {/if}
  </div>
</div>
