<script lang="ts">
  /**
   * SpeciesCorrector - Dropdown/combobox to reassign a detection to a different species tag.
   *
   * Fetches available tags from the project and allows the reviewer to search
   * and select a replacement species.
   */

  import { createQuery } from '@tanstack/svelte-query';
  import { fetchTags } from '$lib/api/tags';
  import type { Tag } from '$lib/types/annotation';

  export let currentTagId: string | null;
  export let projectId: string;
  export let onChangeSpecies: (newTagId: string) => void;

  let searchQuery = '';
  let isOpen = false;
  let inputEl: HTMLInputElement;

  // Fetch all tags for this project (load all, filter client-side for responsiveness)
  $: tagsQuery = createQuery({
    queryKey: ['tags', projectId],
    queryFn: () => fetchTags(projectId, { page_size: 500 }),
  });

  $: allTags = $tagsQuery.data?.items ?? [];

  // Filter tags by search query, exclude the current tag
  $: filteredTags = allTags.filter((tag: Tag) => {
    if (tag.id === currentTagId) return false;
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      tag.name.toLowerCase().includes(q) ||
      (tag.scientific_name != null && tag.scientific_name.toLowerCase().includes(q))
    );
  });

  $: currentTag = allTags.find((t: Tag) => t.id === currentTagId) ?? null;

  function handleInputFocus() {
    isOpen = true;
  }

  function handleInputBlur() {
    // Delay to allow click events on items to fire first
    setTimeout(() => {
      isOpen = false;
    }, 150);
  }

  function handleSelect(tag: Tag) {
    onChangeSpecies(tag.id);
    searchQuery = '';
    isOpen = false;
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      isOpen = false;
      inputEl?.blur();
    }
  }
</script>

<div class="relative">
  <div class="flex items-center gap-1.5">
    <span class="text-xs text-stone-500">Species:</span>

    {#if currentTag}
      <span class="rounded bg-green-100 px-1.5 py-0.5 text-xs font-medium text-green-800">
        {currentTag.name}
      </span>
    {:else}
      <span class="text-xs italic text-stone-400">Unidentified</span>
    {/if}

    <!-- Search input to reassign -->
    <div class="relative">
      <input
        bind:this={inputEl}
        type="text"
        placeholder="Change species..."
        bind:value={searchQuery}
        class="w-36 rounded border border-stone-300 px-2 py-0.5 text-xs focus:border-blue-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
        on:focus={handleInputFocus}
        on:blur={handleInputBlur}
        on:keydown={handleKeydown}
        autocomplete="off"
        role="combobox"
        aria-label="Search for replacement species"
        aria-expanded={isOpen}
        aria-controls="species-listbox"
      />

      {#if isOpen && (filteredTags.length > 0 || $tagsQuery.isLoading)}
        <div
          id="species-listbox"
          class="absolute left-0 top-full z-50 mt-1 max-h-48 w-56 overflow-y-auto rounded-md border border-stone-200 bg-white shadow-lg"
          role="listbox"
          aria-label="Species suggestions"
        >
          {#if $tagsQuery.isLoading}
            <div class="px-3 py-2 text-xs text-stone-400">Loading tags...</div>
          {:else if filteredTags.length === 0}
            <div class="px-3 py-2 text-xs text-stone-400">No matching species</div>
          {:else}
            {#each filteredTags.slice(0, 20) as tag (tag.id)}
              <!-- svelte-ignore a11y_click_events_have_key_events -->
              <!-- svelte-ignore a11y_interactive_supports_focus -->
              <div
                class="flex cursor-pointer flex-col gap-0.5 px-3 py-1.5 hover:bg-stone-50"
                role="option"
                aria-selected="false"
                on:click={() => handleSelect(tag)}
              >
                <span class="text-xs font-medium text-stone-800">{tag.name}</span>
                {#if tag.scientific_name}
                  <span class="text-xs italic text-stone-500">{tag.scientific_name}</span>
                {/if}
              </div>
            {/each}
            {#if filteredTags.length > 20}
              <div class="px-3 py-1.5 text-xs text-stone-400">
                {filteredTags.length - 20} more results - refine search
              </div>
            {/if}
          {/if}
        </div>
      {/if}
    </div>
  </div>
</div>
