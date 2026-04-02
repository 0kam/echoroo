<script lang="ts">
  /**
   * SpeciesCard - Card for a single target species with its reference sound sources.
   *
   * Shows species name, source count, an inline AddSourcePanel (collapsible),
   * and the list of SourceCards for each added reference sound.
   */

  import * as m from '$lib/paraglide/messages.js';
  import type { SoundSource, TargetSpecies } from '$lib/types/search';
  import AddSourcePanel from './AddSourcePanel.svelte';
  import SourceCard from './SourceCard.svelte';

  interface Props {
    species: TargetSpecies;
    modelName: string;
    /** Project ID passed through to AddSourcePanel for Xeno-canto search */
    projectId: string;
    onUpdate: (species: TargetSpecies) => void;
    onRemove: () => void;
    /** When true, hides add/remove controls and passes readonly down to SourceCards */
    readonly?: boolean;
  }

  let { species, modelName, projectId, onUpdate, onRemove, readonly = false }: Props = $props();

  let showAddSource = $state(false);

  function handleAddSource(incoming: SoundSource | SoundSource[]) {
    const newSources = Array.isArray(incoming) ? incoming : [incoming];
    onUpdate({
      ...species,
      sources: [...species.sources, ...newSources],
    });
    showAddSource = false;
  }

  function removeSource(sourceId: string) {
    onUpdate({
      ...species,
      sources: species.sources.filter((s) => s.id !== sourceId),
    });
  }

  function updateSourceClip(sourceId: string, updates: { start_time?: number; end_time?: number }) {
    onUpdate({
      ...species,
      sources: species.sources.map((s) =>
        s.id === sourceId ? { ...s, ...updates } : s
      ),
    });
  }

  function handleRemove() {
    // Simple confirm dialog via window.confirm
    const msg = m.search_remove_species_confirm({ count: species.sources.length.toString() });
    if (species.sources.length === 0 || window.confirm(msg)) {
      onRemove();
    }
  }

  let sourceCountLabel = $derived(() => {
    if (species.sources.length === 1) return m.search_source_count_one();
    return m.search_source_count({ count: species.sources.length.toString() });
  });
</script>

<div class="overflow-hidden rounded-lg border border-stone-200 border-l-[3px] border-l-primary-400
            bg-white shadow-sm dark:border-stone-700 dark:bg-stone-900">
  <!-- Header -->
  <div class="flex items-start justify-between p-3">
    <div class="min-w-0 flex-1">
      <p class="text-base font-semibold italic text-stone-900 dark:text-stone-100">
        {species.scientific_name}
      </p>
      {#if species.common_name || species.sources.length > 0}
        <p class="text-sm text-stone-500 dark:text-stone-400">
          {species.common_name ?? ''}
          {#if species.sources.length > 0}
            <span class="ml-1 text-stone-400">({sourceCountLabel()})</span>
          {/if}
        </p>
      {/if}
    </div>

    {#if !readonly}
      <div class="ml-2 flex shrink-0 items-center gap-2">
        <!-- Add Source toggle -->
        <button
          type="button"
          class="flex items-center rounded border border-stone-300 px-2 py-1 text-xs text-stone-700
                 transition-colors hover:border-primary-400 hover:text-primary-700
                 dark:border-stone-600 dark:text-stone-300 dark:hover:border-primary-500"
          onclick={() => (showAddSource = !showAddSource)}
        >
          <!-- Plus icon -->
          <svg class="mr-1 h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <path d="M12 5v14M5 12h14" stroke-linecap="round" />
          </svg>
          {m.search_add_source()}
        </button>

        <!-- Remove species -->
        <button
          type="button"
          class="text-stone-300 transition-colors hover:text-stone-500 dark:text-stone-600 dark:hover:text-stone-400"
          onclick={handleRemove}
          aria-label="Remove species"
          title={m.search_remove_species_confirm({ count: species.sources.length.toString() })}
        >
          <!-- X icon -->
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        </button>
      </div>
    {/if}
  </div>

  <!-- Add Source Panel (collapsible, hidden in readonly mode) -->
  {#if showAddSource && !readonly}
    <AddSourcePanel
      {modelName}
      {projectId}
      scientificName={species.scientific_name}
      onAdd={handleAddSource}
      onCancel={() => (showAddSource = false)}
    />
  {/if}

  <!-- Source list -->
  {#if species.sources.length > 0}
    <div class="space-y-2 px-3 pb-3">
      {#each species.sources as source (source.id)}
        <SourceCard
          {source}
          {projectId}
          {modelName}
          onRemove={() => removeSource(source.id)}
          onUpdate={(updates) => updateSourceClip(source.id, updates)}
          {readonly}
        />
      {/each}
    </div>
  {:else if !showAddSource && !readonly}
    <!-- Empty state (not shown in readonly mode) -->
    <div class="px-3 pb-4 pt-1 text-center">
      <!-- Upload icon -->
      <svg class="mx-auto mb-2 h-8 w-8 text-stone-300 dark:text-stone-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
      <p class="text-sm text-stone-400 dark:text-stone-500">{m.search_no_sources()}</p>
      <p class="mt-0.5 text-xs text-stone-400 dark:text-stone-500">{m.search_no_sources_hint()}</p>
    </div>
  {/if}
</div>
