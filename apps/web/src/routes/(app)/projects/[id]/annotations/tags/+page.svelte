<script lang="ts">
  import { page } from '$app/stores';
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import {
    fetchTags,
    createTag,
    updateTag,
    deleteTag,
    fetchGBIFSuggestions,
    fetchTagStatistics,
  } from '$lib/api/tags';
  import type {
    Tag,
    TagCreate,
    TagUpdate,
    TagCategory,
    GBIFSuggestion,
  } from '$lib/types/annotation';
  import ConfirmDialog from '$lib/components/ui/ConfirmDialog.svelte';

  const queryClient = useQueryClient();

  $: projectId = $page.params.id as string;

  // Filter / pagination state
  let currentPage = 1;
  let search = '';
  let categoryFilter: TagCategory | '' = '';

  // Form state
  let showForm = false;
  let editingTag: Tag | null = null;

  let formName = '';
  let formCategory: TagCategory = 'species';
  let formParentId = '';
  let formScientificName = '';
  let formCommonName = '';
  let formGbifTaxonKey: number | null = null;
  let formGbifSearch = '';
  let gbifSuggestions: GBIFSuggestion[] = [];
  let isLoadingGBIF = false;
  let gbifDebounceTimer: ReturnType<typeof setTimeout> | null = null;

  // Delete state
  let tagToDelete: Tag | null = null;
  let showDeleteDialog = false;

  // Tags query
  $: tagsQuery = createQuery({
    queryKey: ['tags', projectId, currentPage, search, categoryFilter],
    queryFn: () =>
      fetchTags(projectId, {
        page: currentPage,
        page_size: 20,
        search: search || undefined,
        category: categoryFilter || undefined,
      }),
  });

  // Statistics query
  $: statisticsQuery = createQuery({
    queryKey: ['tags-statistics', projectId],
    queryFn: () => fetchTagStatistics(projectId),
  });

  // Create mutation
  const createMutationStore = createMutation({
    mutationFn: (data: TagCreate) => createTag(projectId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tags', projectId] });
      queryClient.invalidateQueries({ queryKey: ['tags-statistics', projectId] });
      closeForm();
    },
  });

  // Update mutation
  const updateMutationStore = createMutation({
    mutationFn: ({ tagId, data }: { tagId: string; data: TagUpdate }) =>
      updateTag(projectId, tagId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tags', projectId] });
      closeForm();
    },
  });

  // Delete mutation
  const deleteMutationStore = createMutation({
    mutationFn: (tagId: string) => deleteTag(projectId, tagId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tags', projectId] });
      queryClient.invalidateQueries({ queryKey: ['tags-statistics', projectId] });
      tagToDelete = null;
    },
  });

  function openCreateForm() {
    editingTag = null;
    resetForm();
    showForm = true;
  }

  function openEditForm(tag: Tag) {
    editingTag = tag;
    formName = tag.name;
    formCategory = tag.category;
    formParentId = tag.parent_id ?? '';
    formScientificName = tag.scientific_name ?? '';
    formCommonName = tag.common_name ?? '';
    formGbifTaxonKey = tag.gbif_taxon_key ?? null;
    formGbifSearch = '';
    gbifSuggestions = [];
    showForm = true;
  }

  function closeForm() {
    showForm = false;
    editingTag = null;
    resetForm();
  }

  function resetForm() {
    formName = '';
    formCategory = 'species';
    formParentId = '';
    formScientificName = '';
    formCommonName = '';
    formGbifTaxonKey = null;
    formGbifSearch = '';
    gbifSuggestions = [];
  }

  async function handleFormSubmit() {
    if (!formName.trim()) return;

    if (editingTag) {
      const data: TagUpdate = {
        name: formName.trim(),
        parent_id: formParentId || null,
        common_name: formCommonName.trim() || undefined,
      };
      await $updateMutationStore.mutateAsync({ tagId: editingTag.id, data });
    } else {
      const data: TagCreate = {
        name: formName.trim(),
        category: formCategory,
        parent_id: formParentId || undefined,
        gbif_taxon_key: formGbifTaxonKey ?? undefined,
        scientific_name: formScientificName.trim() || undefined,
        common_name: formCommonName.trim() || undefined,
      };
      await $createMutationStore.mutateAsync(data);
    }
  }

  function handleDeleteClick(tag: Tag) {
    tagToDelete = tag;
    showDeleteDialog = true;
  }

  async function confirmDelete() {
    if (tagToDelete) {
      await $deleteMutationStore.mutateAsync(tagToDelete.id);
      showDeleteDialog = false;
      tagToDelete = null;
    }
  }

  function cancelDelete() {
    showDeleteDialog = false;
    tagToDelete = null;
  }

  function handleCategoryFilterChange(cat: TagCategory | '') {
    categoryFilter = cat;
    currentPage = 1;
  }

  function handleSearchInput() {
    currentPage = 1;
  }

  // GBIF search within form
  function handleGBIFSearchInput() {
    if (!formGbifSearch || formGbifSearch.length < 2) {
      gbifSuggestions = [];
      return;
    }

    if (gbifDebounceTimer) clearTimeout(gbifDebounceTimer);
    gbifDebounceTimer = setTimeout(async () => {
      isLoadingGBIF = true;
      try {
        gbifSuggestions = await fetchGBIFSuggestions(projectId, formGbifSearch);
      } catch {
        gbifSuggestions = [];
      } finally {
        isLoadingGBIF = false;
      }
    }, 300);
  }

  function applyGBIFSuggestion(suggestion: GBIFSuggestion) {
    formGbifTaxonKey = suggestion.key;
    formScientificName = suggestion.scientific_name;
    formCommonName = ''; // common name not available in suggestion shape
    if (!formName) {
      formName = suggestion.canonical_name;
    }
    formGbifSearch = suggestion.canonical_name;
    gbifSuggestions = [];
  }

  function getCategoryLabel(category: string): string {
    switch (category) {
      case 'species':
        return m.annotation_tag_category_species();
      case 'sound_type':
        return m.annotation_tag_category_sound_type();
      case 'quality':
        return m.annotation_tag_category_quality();
      default:
        return category;
    }
  }

  // Resolve parent name from current tags list
  function getParentName(parentId: string | null | undefined): string {
    if (!parentId || !$tagsQuery.data) return '';
    const found = $tagsQuery.data.items.find((t) => t.id === parentId);
    return found ? found.name : parentId;
  }

  $: isMutating =
    $createMutationStore.isPending || $updateMutationStore.isPending;
</script>

<svelte:head>
  <title>{m.annotation_tag_page_title()}</title>
</svelte:head>

<div class="tags-page">
  <!-- Page header -->
  <header class="page-header">
    <div class="page-header__left">
      <a href={localizeHref(`/projects/${projectId}/annotations`)} class="back-link">
        &larr; {m.annotation_tag_back_link()}
      </a>
      <h1>{m.annotation_tag_heading()}</h1>
      <p>{m.annotation_tag_description()}</p>
    </div>
    {#if !showForm}
      <button class="btn-primary" on:click={openCreateForm}>
        {m.annotation_tag_new_button()}
      </button>
    {/if}
  </header>

  <!-- Create / Edit form -->
  {#if showForm}
    <div class="form-container">
      <h2>{editingTag ? m.annotation_tag_edit_form_title() : m.annotation_tag_create_form_title()}</h2>

      <form on:submit|preventDefault={handleFormSubmit} class="tag-form">
        <!-- Name -->
        <div class="field">
          <label for="tag-name" class="label">{m.annotation_tag_form_name_label()} <span class="required">{m.annotation_tag_form_name_required()}</span></label>
          <input
            id="tag-name"
            type="text"
            class="input"
            bind:value={formName}
            placeholder={m.annotation_tag_form_name_placeholder()}
            required
          />
        </div>

        <!-- Category (only for new tags) -->
        {#if !editingTag}
          <div class="field">
            <label for="tag-category" class="label">{m.annotation_tag_form_category_label()}</label>
            <select id="tag-category" class="select" bind:value={formCategory}>
              <option value="species">{m.annotation_tag_form_category_species()}</option>
              <option value="sound_type">{m.annotation_tag_form_category_sound_type()}</option>
              <option value="quality">{m.annotation_tag_form_category_quality()}</option>
            </select>
          </div>
        {/if}

        <!-- Parent tag -->
        <div class="field">
          <label for="tag-parent" class="label">{m.annotation_tag_form_parent_label()}</label>
          <select id="tag-parent" class="select" bind:value={formParentId}>
            <option value="">{m.annotation_tag_form_parent_none()}</option>
            {#if $tagsQuery.data}
              {#each $tagsQuery.data.items.filter((t) => !editingTag || t.id !== editingTag.id) as tag}
                <option value={tag.id}>{tag.name} ({getCategoryLabel(tag.category)})</option>
              {/each}
            {/if}
          </select>
        </div>

        <!-- GBIF search (species only) -->
        {#if formCategory === 'species' && !editingTag}
          <div class="field">
            <label for="gbif-search" class="label">{m.annotation_tag_form_gbif_label()}</label>
            <div class="gbif-search-wrapper">
              <input
                id="gbif-search"
                type="text"
                class="input"
                bind:value={formGbifSearch}
                on:input={handleGBIFSearchInput}
                placeholder={m.annotation_tag_form_gbif_placeholder()}
                autocomplete="off"
              />
              {#if isLoadingGBIF}
                <div class="gbif-results gbif-results--loading">{m.annotation_tag_form_gbif_searching()}</div>
              {:else if gbifSuggestions.length > 0}
                <div class="gbif-results">
                  {#each gbifSuggestions as suggestion}
                    <button
                      type="button"
                      class="gbif-result-item"
                      on:click={() => applyGBIFSuggestion(suggestion)}
                    >
                      <span class="gbif-result-item__canonical">{suggestion.canonical_name}</span>
                      <span class="gbif-result-item__scientific">{suggestion.scientific_name}</span>
                      <span class="gbif-result-item__rank">{suggestion.rank}</span>
                    </button>
                  {/each}
                </div>
              {/if}
            </div>
            {#if formGbifTaxonKey}
              <p class="gbif-key-info">{m.annotation_tag_form_gbif_key_info({ key: formGbifTaxonKey })}</p>
            {/if}
          </div>
        {/if}

        <!-- Scientific name -->
        {#if formCategory === 'species' || (editingTag && editingTag.category === 'species')}
          <div class="field">
            <label for="scientific-name" class="label">{m.annotation_tag_form_scientific_name_label()}</label>
            <input
              id="scientific-name"
              type="text"
              class="input"
              bind:value={formScientificName}
              placeholder={m.annotation_tag_form_scientific_name_placeholder()}
            />
          </div>

          <!-- Common name -->
          <div class="field">
            <label for="common-name" class="label">{m.annotation_tag_form_common_name_label()}</label>
            <input
              id="common-name"
              type="text"
              class="input"
              bind:value={formCommonName}
              placeholder={m.annotation_tag_form_common_name_placeholder()}
            />
          </div>
        {/if}

        <!-- Form actions -->
        <div class="form-actions">
          <button type="button" class="btn-secondary" on:click={closeForm} disabled={isMutating}>
            {m.annotation_tag_form_cancel()}
          </button>
          <button type="submit" class="btn-primary" disabled={isMutating || !formName.trim()}>
            {#if isMutating}
              {m.annotation_tag_form_saving()}
            {:else}
              {editingTag ? m.annotation_tag_form_save_changes() : m.annotation_tag_form_create()}
            {/if}
          </button>
        </div>

        {#if $createMutationStore.isError}
          <div class="form-error">
            {$createMutationStore.error?.message || m.annotation_tag_form_error_create()}
          </div>
        {/if}
        {#if $updateMutationStore.isError}
          <div class="form-error">
            {$updateMutationStore.error?.message || m.annotation_tag_form_error_update()}
          </div>
        {/if}
      </form>
    </div>
  {/if}

  <!-- Filters -->
  <div class="filters">
    <!-- Category tabs -->
    <div class="category-tabs">
      <button
        class="tab-btn"
        class:tab-btn--active={categoryFilter === ''}
        on:click={() => handleCategoryFilterChange('')}
      >
        {m.annotation_tag_filter_all()}
      </button>
      <button
        class="tab-btn"
        class:tab-btn--active={categoryFilter === 'species'}
        on:click={() => handleCategoryFilterChange('species')}
      >
        {m.annotation_tag_filter_species()}
      </button>
      <button
        class="tab-btn"
        class:tab-btn--active={categoryFilter === 'sound_type'}
        on:click={() => handleCategoryFilterChange('sound_type')}
      >
        {m.annotation_tag_filter_sound_type()}
      </button>
      <button
        class="tab-btn"
        class:tab-btn--active={categoryFilter === 'quality'}
        on:click={() => handleCategoryFilterChange('quality')}
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
      on:input={handleSearchInput}
    />
  </div>

  <!-- Tag list -->
  {#if $tagsQuery.isLoading}
    <div class="state-message state-message--loading">{m.annotation_tag_loading()}</div>
  {:else if $tagsQuery.isError}
    <div class="state-message state-message--error">
      {m.annotation_tag_error_load({ message: $tagsQuery.error?.message ?? '' })}
    </div>
  {:else if $tagsQuery.data}
    {#if $tagsQuery.data.items.length === 0}
      <div class="state-message">
        {search || categoryFilter ? m.annotation_tag_empty_filter() : m.annotation_tag_empty()}
      </div>
    {:else}
      <div class="tag-table-wrapper">
        <table class="tag-table">
          <thead>
            <tr>
              <th>{m.annotation_tag_col_name()}</th>
              <th>{m.annotation_tag_col_category()}</th>
              <th>{m.annotation_tag_col_scientific()}</th>
              <th>{m.annotation_tag_col_common()}</th>
              <th>{m.annotation_tag_col_parent()}</th>
              <th class="col-actions">{m.annotation_tag_col_actions()}</th>
            </tr>
          </thead>
          <tbody>
            {#each $tagsQuery.data.items as tag}
              <tr>
                <td class="cell-name">{tag.name}</td>
                <td>
                  <span class="category-badge category-badge--{tag.category}">
                    {getCategoryLabel(tag.category)}
                  </span>
                </td>
                <td class="cell-italic">{tag.scientific_name ?? '—'}</td>
                <td>{tag.common_name ?? '—'}</td>
                <td>{tag.parent_id ? getParentName(tag.parent_id) : '—'}</td>
                <td class="cell-actions">
                  <button
                    class="action-btn action-btn--edit"
                    on:click={() => openEditForm(tag)}
                    aria-label="{m.annotation_tag_edit_button()} {tag.name}"
                  >
                    {m.annotation_tag_edit_button()}
                  </button>
                  <button
                    class="action-btn action-btn--delete"
                    on:click={() => handleDeleteClick(tag)}
                    aria-label="{m.annotation_tag_delete_button()} {tag.name}"
                  >
                    {m.annotation_tag_delete_button()}
                  </button>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      {#if $tagsQuery.data.pages > 1}
        <div class="pagination">
          <button
            class="page-btn"
            on:click={() => (currentPage = Math.max(1, currentPage - 1))}
            disabled={currentPage === 1}
          >
            {m.annotation_tag_previous()}
          </button>
          <span class="page-info">
            {m.annotation_tag_page_info({ page: currentPage, total: $tagsQuery.data.pages })}
          </span>
          <button
            class="page-btn"
            on:click={() => (currentPage = Math.min($tagsQuery.data.pages, currentPage + 1))}
            disabled={currentPage === $tagsQuery.data.pages}
          >
            {m.annotation_tag_next()}
          </button>
        </div>
      {/if}

      {#if $tagsQuery.data.total > 0}
        <div class="pagination-info">
          {m.annotation_tag_showing({ showing: $tagsQuery.data.items.length, total: $tagsQuery.data.total })}
        </div>
      {/if}
    {/if}
  {/if}

  <!-- Statistics section -->
  {#if $statisticsQuery.data && $statisticsQuery.data.length > 0}
    <div class="statistics-section">
      <h2>{m.annotation_tag_stats_title()}</h2>
      <div class="statistics-grid">
        {#each $statisticsQuery.data as stat}
          <div class="stat-card">
            <div class="stat-card__name">{stat.tag.name}</div>
            <div class="stat-card__meta">
              <span class="category-badge category-badge--{stat.tag.category}">
                {getCategoryLabel(stat.tag.category)}
              </span>
            </div>
            <div class="stat-card__count">{m.annotation_tag_stats_uses({ count: stat.usage_count })}</div>
          </div>
        {/each}
      </div>
    </div>
  {/if}

  <!-- Delete confirmation dialog -->
  <ConfirmDialog
    isOpen={showDeleteDialog}
    title={m.annotation_tag_delete_title()}
    message={tagToDelete
      ? m.annotation_tag_delete_message({ name: tagToDelete.name })
      : ''}
    confirmText={m.annotation_tag_delete_confirm()}
    cancelText={m.annotation_tag_delete_cancel()}
    isDanger={true}
    warningItems={[m.annotation_tag_delete_warning()]}
    onConfirm={confirmDelete}
    onCancel={cancelDelete}
  />
</div>

<style>
  .tags-page {
    max-width: 1200px;
    margin: 0 auto;
    padding: 2rem;
  }

  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 2rem;
  }

  .page-header__left {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .back-link {
    font-size: 0.875rem;
    color: #6b7280;
    text-decoration: none;
    margin-bottom: 0.25rem;
  }

  .back-link:hover {
    color: #374151;
  }

  .page-header h1 {
    margin: 0;
    font-size: 1.5rem;
    font-weight: 600;
  }

  .page-header p {
    margin: 0;
    color: #6b7280;
    font-size: 0.875rem;
  }

  /* Form */
  .form-container {
    background: rgb(var(--color-card-bg));
    padding: 1.5rem;
    border-radius: 0.5rem;
    border: 1px solid #e5e7eb;
    margin-bottom: 2rem;
  }

  .form-container h2 {
    margin: 0 0 1.5rem 0;
    font-size: 1.125rem;
    font-weight: 600;
  }

  .tag-form {
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .field {
    display: flex;
    flex-direction: column;
    gap: 0.375rem;
  }

  .label {
    font-size: 0.875rem;
    font-weight: 500;
    color: #374151;
  }

  .required {
    color: #dc2626;
  }

  .input,
  .select {
    padding: 0.5rem 0.75rem;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    outline: none;
  }

  .input:focus,
  .select:focus {
    border-color: rgb(var(--primary-500));
    box-shadow: 0 0 0 3px rgb(var(--primary-500) / 0.15);
  }

  .gbif-search-wrapper {
    position: relative;
  }

  .gbif-results {
    position: absolute;
    top: calc(100% + 4px);
    left: 0;
    right: 0;
    background: rgb(var(--color-card-bg));
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    z-index: 20;
    max-height: 240px;
    overflow-y: auto;
  }

  .gbif-results--loading {
    padding: 0.75rem;
    font-size: 0.875rem;
    color: #6b7280;
    text-align: center;
  }

  .gbif-result-item {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
    width: 100%;
    padding: 0.5rem 0.75rem;
    text-align: left;
    background: transparent;
    border: none;
    cursor: pointer;
    font-size: 0.875rem;
  }

  .gbif-result-item:hover {
    background: #f9fafb;
  }

  .gbif-result-item__canonical {
    font-weight: 500;
    color: #111827;
    flex-shrink: 0;
  }

  .gbif-result-item__scientific {
    font-style: italic;
    color: #6b7280;
    font-size: 0.8125rem;
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .gbif-result-item__rank {
    font-size: 0.75rem;
    color: #9ca3af;
    flex-shrink: 0;
  }

  .gbif-key-info {
    margin: 0.25rem 0 0 0;
    font-size: 0.75rem;
    color: #6b7280;
  }

  .form-actions {
    display: flex;
    justify-content: flex-end;
    gap: 0.75rem;
    padding-top: 0.5rem;
  }

  .form-error {
    padding: 0.75rem;
    background: #fef2f2;
    border: 1px solid #fecaca;
    border-radius: 0.375rem;
    color: #dc2626;
    font-size: 0.875rem;
  }

  /* Filters */
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

  /* State messages */
  .state-message {
    padding: 2rem;
    text-align: center;
    border-radius: 0.5rem;
    background: #f3f4f6;
    color: #6b7280;
    font-size: 0.875rem;
  }

  .state-message--loading {
    background: #f3f4f6;
    color: #6b7280;
  }

  .state-message--error {
    background: #fef2f2;
    color: #dc2626;
  }

  /* Tag table */
  .tag-table-wrapper {
    border: 1px solid #e5e7eb;
    border-radius: 0.5rem;
    overflow: hidden;
  }

  .tag-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.875rem;
  }

  .tag-table thead {
    background: #f9fafb;
  }

  .tag-table th {
    padding: 0.75rem 1rem;
    text-align: left;
    font-weight: 600;
    color: #374151;
    border-bottom: 1px solid #e5e7eb;
  }

  .tag-table td {
    padding: 0.75rem 1rem;
    border-bottom: 1px solid #f3f4f6;
    color: #374151;
    vertical-align: middle;
  }

  .tag-table tr:last-child td {
    border-bottom: none;
  }

  .tag-table tr:hover td {
    background: #f9fafb;
  }

  .cell-name {
    font-weight: 500;
    color: #111827;
  }

  .cell-italic {
    font-style: italic;
    color: #6b7280;
  }

  .col-actions {
    width: 140px;
    text-align: right;
  }

  .cell-actions {
    display: flex;
    justify-content: flex-end;
    gap: 0.5rem;
  }

  /* Category badges */
  .category-badge {
    display: inline-block;
    font-size: 0.75rem;
    font-weight: 500;
    padding: 0.125rem 0.5rem;
    border-radius: 0.25rem;
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

  /* Action buttons */
  .action-btn {
    padding: 0.25rem 0.625rem;
    font-size: 0.8125rem;
    border-radius: 0.25rem;
    cursor: pointer;
    border: none;
    font-weight: 500;
    transition: background 0.15s;
  }

  .action-btn--edit {
    background: #f3f4f6;
    color: #374151;
  }

  .action-btn--edit:hover {
    background: #e5e7eb;
  }

  .action-btn--delete {
    background: #fef2f2;
    color: #dc2626;
  }

  .action-btn--delete:hover {
    background: #fee2e2;
  }

  /* Pagination */
  .pagination {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 1rem;
    margin-top: 1.5rem;
  }

  .page-btn {
    padding: 0.5rem 1rem;
    background: rgb(var(--color-card-bg));
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    cursor: pointer;
  }

  .page-btn:hover:not(:disabled) {
    background: #f9fafb;
  }

  .page-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .page-info {
    font-size: 0.875rem;
    color: #6b7280;
  }

  .pagination-info {
    margin-top: 1rem;
    text-align: center;
    font-size: 0.875rem;
    color: #6b7280;
  }

  /* Statistics */
  .statistics-section {
    margin-top: 2.5rem;
    padding-top: 2rem;
    border-top: 1px solid #e5e7eb;
  }

  .statistics-section h2 {
    margin: 0 0 1.25rem 0;
    font-size: 1.125rem;
    font-weight: 600;
  }

  .statistics-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 1rem;
  }

  .stat-card {
    background: rgb(var(--color-card-bg));
    border: 1px solid #e5e7eb;
    border-radius: 0.5rem;
    padding: 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.375rem;
  }

  .stat-card__name {
    font-weight: 500;
    color: #111827;
    font-size: 0.875rem;
  }

  .stat-card__meta {
    display: flex;
    gap: 0.375rem;
  }

  .stat-card__count {
    font-size: 1.25rem;
    font-weight: 600;
    color: rgb(var(--primary-500));
    margin-top: 0.25rem;
  }

  /* Global buttons */
  .btn-primary {
    padding: 0.625rem 1rem;
    background: rgb(var(--primary-500));
    color: white;
    border: none;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    font-weight: 500;
    cursor: pointer;
  }

  .btn-primary:hover:not(:disabled) {
    background: rgb(var(--primary-600));
  }

  .btn-primary:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .btn-secondary {
    padding: 0.625rem 1rem;
    background: rgb(var(--color-card-bg));
    color: #374151;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    font-weight: 500;
    cursor: pointer;
  }

  .btn-secondary:hover:not(:disabled) {
    background: #f9fafb;
  }

  .btn-secondary:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
