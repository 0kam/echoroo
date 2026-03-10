<script lang="ts">
  /**
   * ReferenceSoundsPanel - Container card for the entire reference sounds section.
   *
   * Manages the species-first hierarchy: users add target species, then add
   * reference sounds under each species via SpeciesCard children.
   */

  import * as m from '$lib/paraglide/messages.js';
  import type { TargetSpecies } from '$lib/types/search';
  import { generateId } from '$lib/utils/id';
  import SpeciesSelector from './SpeciesSelector.svelte';
  import SpeciesCard from './SpeciesCard.svelte';

  interface Props {
    projectId: string;
    species: TargetSpecies[];
    /** Model name forwarded to SpectrogramClipEditor for min clip duration */
    modelName: string;
    onSpeciesChange: (species: TargetSpecies[]) => void;
  }

  let { projectId, species, modelName, onSpeciesChange }: Props = $props();

  let showSelector = $state(false);

  // Set of tag_ids already added (for SpeciesSelector to gray them out)
  let addedTagIds = $derived(
    new Set(species.map((sp) => sp.tag_id).filter((id): id is string => id !== null))
  );

  function handleAddSpecies(entry: {
    tag_id: string | null;
    scientific_name: string;
    common_name?: string;
  }) {
    // Prevent duplicate tag_ids
    if (entry.tag_id && addedTagIds.has(entry.tag_id)) return;

    const newSpecies: TargetSpecies = {
      id: generateId(),
      tag_id: entry.tag_id,
      scientific_name: entry.scientific_name,
      common_name: entry.common_name,
      sources: [],
    };

    onSpeciesChange([...species, newSpecies]);
    // Keep selector open so the user can add multiple species quickly
  }

  function updateSpecies(id: string, updated: TargetSpecies) {
    onSpeciesChange(species.map((sp) => (sp.id === id ? updated : sp)));
  }

  function removeSpecies(id: string) {
    onSpeciesChange(species.filter((sp) => sp.id !== id));
  }
</script>

<div class="rounded-lg border border-stone-200 bg-white shadow-sm dark:border-stone-700 dark:bg-stone-900">
  <!-- Panel header -->
  <div class="flex items-center justify-between border-b border-stone-200 p-4 dark:border-stone-700">
    <h2 class="text-lg font-semibold text-stone-900 dark:text-stone-100">
      {m.search_reference_sounds()}
    </h2>
    <button
      type="button"
      class="flex items-center rounded-md border border-primary-300 px-3 py-1.5 text-sm
             text-primary-600 transition-colors hover:bg-primary-50
             dark:border-primary-600 dark:text-primary-400 dark:hover:bg-primary-950/30"
      onclick={() => (showSelector = !showSelector)}
    >
      <!-- Plus icon -->
      <svg class="mr-1 h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
        <path d="M12 5v14M5 12h14" stroke-linecap="round" />
      </svg>
      {m.search_add_species()}
    </button>
  </div>

  <div class="space-y-3 p-4">
    <!-- Species Selector (inline, shown when Add Species clicked) -->
    {#if showSelector}
      <SpeciesSelector
        {projectId}
        addedSpeciesIds={addedTagIds}
        onAdd={handleAddSpecies}
        onClose={() => (showSelector = false)}
      />
    {/if}

    <!-- Species Cards -->
    {#each species as sp (sp.id)}
      <SpeciesCard
        species={sp}
        {modelName}
        onUpdate={(updated) => updateSpecies(sp.id, updated)}
        onRemove={() => removeSpecies(sp.id)}
      />
    {/each}

    <!-- Empty state (no species yet, selector closed) -->
    {#if species.length === 0 && !showSelector}
      <div class="py-8 text-center">
        <!-- Bird icon -->
      <svg class="mx-auto mb-3 h-12 w-12 text-stone-300 dark:text-stone-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
        <path d="M16 7c0-1.1-.4-2-1-2.8M16 7c0 1.1-.4 2-1 2.8M16 7h2a2 2 0 0 1 0 4h-2M6 7h3l2.5 5L16 7m0 9c-4 1-8 0-8-4l1-5" stroke-linecap="round" stroke-linejoin="round" />
        <circle cx="17" cy="5" r="1" fill="currentColor" />
      </svg>
        <p class="font-medium text-stone-400 dark:text-stone-500">{m.search_no_species()}</p>
        <p class="mt-1 text-sm text-stone-400 dark:text-stone-500">{m.search_no_species_hint()}</p>
      </div>
    {/if}
  </div>
</div>
