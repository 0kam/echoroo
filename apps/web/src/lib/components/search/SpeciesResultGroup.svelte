<script lang="ts">
  /**
   * SpeciesResultGroup - Collapsible group showing all match results for one species.
   *
   * Shows a bordered group header with the species name, match count badge,
   * and an expandable list of ResultItem rows. Starts expanded by default.
   */

  import * as m from '$lib/paraglide/messages.js';
  import type { SpeciesMatchResult } from '$lib/types/search';
  import ResultItem from './ResultItem.svelte';

  interface Props {
    projectId: string;
    tagId: string;
    group: SpeciesMatchResult;
  }

  let { projectId, group }: Props = $props();

  let expanded = $state(true);
</script>

<div class="rounded-lg border-l-[3px] border-l-primary-400 bg-surface-page">
  <!-- Group header toggle -->
  <button
    class="w-full rounded-t-lg px-3 py-3 text-left transition-colors hover:bg-stone-50"
    onclick={() => (expanded = !expanded)}
    type="button"
    aria-expanded={expanded}
  >
    <div class="flex items-start justify-between gap-2">
      <div class="flex items-center gap-2">
        <!-- Chevron icon -->
        <svg
          class="h-4 w-4 shrink-0 text-stone-400 transition-transform {expanded ? '' : '-rotate-90'}"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          stroke-width="2"
          aria-hidden="true"
        >
          <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
        <div>
          <p class="text-base font-semibold text-stone-900">{group.scientific_name}</p>
          {#if group.common_name}
            <p class="text-sm text-stone-500">{group.common_name}</p>
          {/if}
        </div>
      </div>

      <!-- Match count badge -->
      <span class="shrink-0 rounded-full bg-primary-100 px-2 py-0.5 text-sm font-medium text-primary-800">
        {group.matches.length === 1
          ? m.search_results_match_one()
          : m.search_results_matches({ count: group.matches.length.toString() })}
      </span>
    </div>
  </button>

  <!-- Match list -->
  {#if expanded}
    <div class="space-y-2 px-3 pb-3">
      {#if group.matches.length === 0}
        <div class="py-4 text-center text-sm text-stone-400">
          <p>{m.search_results_no_matches_species({ species: group.scientific_name })}</p>
          <p class="mt-1 text-xs">{m.search_results_no_matches_species_hint()}</p>
        </div>
      {:else}
        {#each group.matches as match (match.embedding_id)}
          <ResultItem {projectId} {match} />
        {/each}
      {/if}
    </div>
  {/if}
</div>
