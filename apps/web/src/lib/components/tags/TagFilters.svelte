<script lang="ts">
  /**
   * TagFilters — category tabs plus the free-text search box for the tag list.
   *
   * Extracted from the tag settings page. The parent owns `search` and
   * `categoryFilter` (both feed the tags query key), so `search` is two-way
   * bound and category changes are dispatched via callback.
   */
  import * as m from '$lib/paraglide/messages';
  import type { TagCategory } from '$lib/types/tag';

  interface Props {
    categoryFilter: TagCategory | '';
    /** Free-text search (two-way bound; part of the tags query key). */
    search: string;
    onCategoryChange: (cat: TagCategory | '') => void;
    onSearchInput: () => void;
  }

  let {
    categoryFilter,
    search = $bindable(),
    onCategoryChange,
    onSearchInput,
  }: Props = $props();
</script>

<div class="filters">
  <!-- Category tabs -->
  <div class="category-tabs">
    <button
      class="tab-btn"
      class:tab-btn--active={categoryFilter === ''}
      onclick={() => onCategoryChange('')}
    >
      {m.annotation_tag_filter_all()}
    </button>
    <button
      class="tab-btn"
      class:tab-btn--active={categoryFilter === 'species'}
      onclick={() => onCategoryChange('species')}
    >
      {m.annotation_tag_filter_species()}
    </button>
    <button
      class="tab-btn"
      class:tab-btn--active={categoryFilter === 'sound_type'}
      onclick={() => onCategoryChange('sound_type')}
    >
      {m.annotation_tag_filter_sound_type()}
    </button>
    <button
      class="tab-btn"
      class:tab-btn--active={categoryFilter === 'quality'}
      onclick={() => onCategoryChange('quality')}
    >
      {m.annotation_tag_filter_quality()}
    </button>
  </div>

  <!-- Search bar -->
  <input
    type="text"
    class="search-input"
    placeholder={m.annotation_tag_search_placeholder()}
    bind:value={search}
    oninput={onSearchInput}
  />
</div>

<style>
  .filters {
    display: flex;
    align-items: center;
    gap: 1rem;
    margin-bottom: 1.5rem;
    flex-wrap: wrap;
  }

  .category-tabs {
    display: flex;
    gap: 0.25rem;
  }

  .tab-btn {
    padding: 0.375rem 0.875rem;
    background: rgb(var(--color-card-bg));
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    cursor: pointer;
    color: #374151;
    transition: all 0.15s;
  }

  .tab-btn:hover:not(.tab-btn--active) {
    background: #f9fafb;
  }

  .tab-btn--active {
    background: rgb(var(--primary-500));
    border-color: rgb(var(--primary-500));
    color: white;
  }

  .search-input {
    flex: 1;
    min-width: 200px;
    padding: 0.5rem 0.75rem;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    outline: none;
  }

  .search-input:focus {
    border-color: rgb(var(--primary-500));
    box-shadow: 0 0 0 3px rgb(var(--primary-500) / 0.15);
  }
</style>
