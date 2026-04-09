<script lang="ts">
  import type { Tag, GBIFSuggestion } from '$lib/types/annotation';
  import { fetchGBIFSuggestions } from '$lib/api/tags';
  import * as m from '$lib/paraglide/messages';

  let {
    projectId,
    selectedTagIds = [] as string[],
    availableTags = [] as Tag[],
    onTagSelect,
    onTagRemove,
    showGBIF = false,
  }: {
    projectId: string;
    selectedTagIds?: string[];
    availableTags?: Tag[];
    onTagSelect: (tagId: string) => void;
    onTagRemove: (tagId: string) => void;
    showGBIF?: boolean;
  } = $props();

  let searchQuery = $state('');
  let isDropdownOpen = $state(false);
  let gbifSuggestions: GBIFSuggestion[] = $state([]);
  let isLoadingGBIF = $state(false);
  let gbifDebounceTimer: ReturnType<typeof setTimeout> | null = $state(null);
  let inputElement: HTMLInputElement | undefined = $state(undefined);

  // Selected tag objects for display
  const selectedTags = $derived(availableTags.filter((t) => selectedTagIds.includes(t.id)));

  // Filter available tags by search query (excluding already selected)
  const filteredTags = $derived(availableTags.filter(
    (t) =>
      !selectedTagIds.includes(t.id) &&
      (searchQuery === '' ||
        t.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (t.scientific_name && t.scientific_name.toLowerCase().includes(searchQuery.toLowerCase())))
  ));

  function openDropdown() {
    isDropdownOpen = true;
  }

  function closeDropdown() {
    isDropdownOpen = false;
    gbifSuggestions = [];
    if (gbifDebounceTimer) {
      clearTimeout(gbifDebounceTimer);
      gbifDebounceTimer = null;
    }
  }

  function handleInputFocus() {
    openDropdown();
  }

  function handleInputBlur() {
    // Delay close to allow click events on dropdown items
    setTimeout(() => closeDropdown(), 150);
  }

  function handleTagSelect(tagId: string) {
    onTagSelect(tagId);
    searchQuery = '';
    gbifSuggestions = [];
    isDropdownOpen = false;
    inputElement?.focus();
  }

  function handleTagRemove(tagId: string) {
    onTagRemove(tagId);
  }

  function handleSearchInput() {
    isDropdownOpen = true;

    if (!showGBIF || searchQuery.length < 2) {
      gbifSuggestions = [];
      return;
    }

    // Debounce GBIF search
    if (gbifDebounceTimer) {
      clearTimeout(gbifDebounceTimer);
    }
    gbifDebounceTimer = setTimeout(async () => {
      isLoadingGBIF = true;
      try {
        gbifSuggestions = await fetchGBIFSuggestions(projectId, searchQuery);
      } catch {
        gbifSuggestions = [];
      } finally {
        isLoadingGBIF = false;
      }
    }, 300);
  }

  function handleKeydown(event: KeyboardEvent) {
    // Keyboard shortcuts 1-9 for quick tag selection
    if (event.key >= '1' && event.key <= '9') {
      const index = parseInt(event.key, 10) - 1;
      const tag = filteredTags[index];
      if (tag) {
        handleTagSelect(tag.id);
        event.preventDefault();
      }
    }

    if (event.key === 'Escape') {
      closeDropdown();
      inputElement?.blur();
    }
  }

  function getCategoryLabel(category: string): string {
    switch (category) {
      case 'species':
        return m.annotation_tag_filter_species();
      case 'sound_type':
        return m.annotation_tag_filter_sound_type();
      case 'quality':
        return m.annotation_tag_filter_quality();
      default:
        return category;
    }
  }
</script>

<div class="tag-selector">
  <!-- Selected tags as chips -->
  {#if selectedTags.length > 0}
    <div class="selected-tags">
      {#each selectedTags as tag}
        <span class="tag-chip tag-chip--{tag.category}">
          <span class="tag-chip__name">{tag.name}</span>
          <button
            type="button"
            class="tag-chip__remove"
            onclick={() => handleTagRemove(tag.id)}
            aria-label="Remove {tag.name}"
          >
            &times;
          </button>
        </span>
      {/each}
    </div>
  {/if}

  <!-- Search input -->
  <div class="search-wrapper">
    <input
      bind:this={inputElement}
      type="text"
      class="search-input"
      placeholder={m.annotation_tag_selector_search_placeholder()}
      bind:value={searchQuery}
      oninput={handleSearchInput}
      onfocus={handleInputFocus}
      onblur={handleInputBlur}
      onkeydown={handleKeydown}
      autocomplete="off"
    />

    <!-- Dropdown -->
    {#if isDropdownOpen}
      <div class="dropdown" role="listbox" aria-label="Tag suggestions">
        <!-- Local tags -->
        {#if filteredTags.length > 0}
          <div class="dropdown-section">
            <div class="dropdown-section__header">{m.annotation_tag_selector_tags_header()}</div>
            {#each filteredTags as tag, index}
              <!-- svelte-ignore a11y_click_events_have_key_events -->
              <!-- svelte-ignore a11y_interactive_supports_focus -->
              <div
                class="dropdown-item"
                role="option"
                aria-selected="false"
                onclick={() => handleTagSelect(tag.id)}
              >
                <span class="dropdown-item__shortcut">{index < 9 ? index + 1 : ''}</span>
                <span class="dropdown-item__content">
                  <span class="dropdown-item__name">{tag.name}</span>
                  {#if tag.scientific_name}
                    <span class="dropdown-item__scientific">{tag.scientific_name}</span>
                  {/if}
                </span>
                <span class="category-badge category-badge--{tag.category}">
                  {getCategoryLabel(tag.category)}
                </span>
              </div>
            {/each}
          </div>
        {:else if searchQuery === ''}
          <div class="dropdown-empty">{m.annotation_tag_selector_type_to_search()}</div>
        {:else}
          <div class="dropdown-empty">{m.annotation_tag_selector_no_match()}</div>
        {/if}

        <!-- GBIF suggestions -->
        {#if showGBIF && searchQuery.length >= 2}
          <div class="dropdown-section">
            <div class="dropdown-section__header">{m.annotation_tag_selector_gbif_header()}</div>
            {#if isLoadingGBIF}
              <div class="dropdown-loading">{m.annotation_tag_selector_gbif_searching()}</div>
            {:else if gbifSuggestions.length > 0}
              {#each gbifSuggestions as suggestion}
                <!-- svelte-ignore a11y_click_events_have_key_events -->
                <!-- svelte-ignore a11y_interactive_supports_focus -->
                <div
                  class="dropdown-item dropdown-item--gbif"
                  role="option"
                  aria-selected="false"
                  onclick={() => {
                    // Dispatch GBIF selection to parent for tag creation form auto-fill
                    const event = new CustomEvent('gbifSelect', { detail: suggestion, bubbles: true });
                    inputElement?.dispatchEvent(event);
                    closeDropdown();
                    searchQuery = '';
                  }}
                >
                  <span class="dropdown-item__content">
                    <span class="dropdown-item__name">{suggestion.canonical_name}</span>
                    <span class="dropdown-item__scientific">{suggestion.scientific_name}</span>
                  </span>
                  <span class="gbif-rank">{suggestion.rank}</span>
                </div>
              {/each}
            {:else}
              <div class="dropdown-empty">{m.annotation_tag_selector_gbif_no_results()}</div>
            {/if}
          </div>
        {/if}
      </div>
    {/if}
  </div>
</div>

<style>
  .tag-selector {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .selected-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 0.375rem;
  }

  .tag-chip {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    padding: 0.25rem 0.5rem;
    border-radius: 1rem;
    font-size: 0.75rem;
    font-weight: 500;
  }

  .tag-chip--species {
    background: #dcfce7;
    color: #166534;
  }

  .tag-chip--sound_type {
    background: #dbeafe;
    color: #1e40af;
  }

  .tag-chip--quality {
    background: #fef9c3;
    color: #854d0e;
  }

  .tag-chip__name {
    max-width: 200px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .tag-chip__remove {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1rem;
    height: 1rem;
    background: transparent;
    border: none;
    border-radius: 50%;
    cursor: pointer;
    font-size: 0.875rem;
    line-height: 1;
    color: inherit;
    opacity: 0.7;
    padding: 0;
  }

  .tag-chip__remove:hover {
    opacity: 1;
    background: rgba(0, 0, 0, 0.1);
  }

  .search-wrapper {
    position: relative;
  }

  .search-input {
    width: 100%;
    padding: 0.5rem 0.75rem;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    outline: none;
    box-sizing: border-box;
  }

  .search-input:focus {
    border-color: rgb(var(--primary-500));
    box-shadow: 0 0 0 3px rgb(var(--primary-500) / 0.15);
  }

  .dropdown {
    position: absolute;
    top: calc(100% + 4px);
    left: 0;
    right: 0;
    background: rgb(var(--color-card-bg));
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    max-height: 320px;
    overflow-y: auto;
    z-index: 50;
  }

  .dropdown-section {
    padding: 0.25rem 0;
  }

  .dropdown-section + .dropdown-section {
    border-top: 1px solid #e5e7eb;
  }

  .dropdown-section__header {
    padding: 0.375rem 0.75rem;
    font-size: 0.75rem;
    font-weight: 600;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .dropdown-item {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 0.75rem;
    cursor: pointer;
    transition: background 0.1s;
  }

  .dropdown-item:hover {
    background: #f9fafb;
  }

  .dropdown-item__shortcut {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.25rem;
    height: 1.25rem;
    background: #f3f4f6;
    border-radius: 0.25rem;
    font-size: 0.6875rem;
    color: #9ca3af;
    flex-shrink: 0;
  }

  .dropdown-item__content {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 0.125rem;
  }

  .dropdown-item__name {
    font-size: 0.875rem;
    color: #111827;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .dropdown-item__scientific {
    font-size: 0.75rem;
    color: #6b7280;
    font-style: italic;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .category-badge {
    font-size: 0.6875rem;
    font-weight: 500;
    padding: 0.125rem 0.375rem;
    border-radius: 0.25rem;
    flex-shrink: 0;
  }

  .category-badge--species {
    background: #dcfce7;
    color: #166534;
  }

  .category-badge--sound_type {
    background: #dbeafe;
    color: #1e40af;
  }

  .category-badge--quality {
    background: #fef9c3;
    color: #854d0e;
  }

  .gbif-rank {
    font-size: 0.6875rem;
    color: #9ca3af;
    flex-shrink: 0;
  }

  .dropdown-item--gbif .dropdown-item__name {
    font-weight: 500;
  }

  .dropdown-empty {
    padding: 0.75rem;
    font-size: 0.875rem;
    color: #9ca3af;
    text-align: center;
  }

  .dropdown-loading {
    padding: 0.75rem;
    font-size: 0.875rem;
    color: #6b7280;
    text-align: center;
  }
</style>
