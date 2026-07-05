<script lang="ts">
  /**
   * TagForm — create / edit form for a project tag, including the GBIF
   * taxonomy autocomplete (species tags only).
   *
   * Extracted from the tag settings page. Owns all form-field state and the
   * debounced GBIF lookup (via {@link useGbifSuggest}). Emits the built
   * create/update payload via {@link Props.onSubmit}; the parent shell owns the
   * TanStack mutations. Form fields re-initialize whenever the `editingTag`
   * reference changes (matching the original page's open-create / open-edit
   * handlers).
   */
  import * as m from '$lib/paraglide/messages';
  import type { Tag, TagCategory, GBIFSuggestion } from '$lib/types/tag';
  import { getCategoryLabel } from './categoryLabel';
  import { useGbifSuggest } from './useGbifSuggest.svelte';
  import type { TagFormSubmit } from './types';

  interface Props {
    /** Tag being edited, or `null` for the create form. */
    editingTag: Tag | null;
    /** Tags available as parents (current page of the tags list). */
    existingTags: Tag[];
    /** Project id (for the GBIF lookup). */
    projectId: string;
    /** Whether a create/update mutation is in flight. */
    isMutating: boolean;
    /** Create-mutation error message (if any). */
    createError: string | null;
    /** Update-mutation error message (if any). */
    updateError: string | null;
    onSubmit: (payload: TagFormSubmit) => void;
    onCancel: () => void;
  }

  const {
    editingTag,
    existingTags,
    projectId,
    isMutating,
    createError,
    updateError,
    onSubmit,
    onCancel,
  }: Props = $props();

  let formName = $state('');
  let formCategory = $state<TagCategory>('species');
  let formParentId = $state('');
  let formScientificName = $state('');
  let formCommonName = $state('');
  let formGbifTaxonKey = $state<number | null>(null);
  let formGbifSearch = $state('');

  const gbif = useGbifSuggest(() => projectId);

  // (Re-)initialize the form fields from `editingTag`. Reads only the
  // `editingTag` reference and writes field state, so there is no reactive
  // loop. Mirrors the original `openCreateForm` / `openEditForm` handlers.
  let lastEditingTag: Tag | null | undefined = undefined;
  $effect(() => {
    if (editingTag === lastEditingTag) return;
    lastEditingTag = editingTag;
    if (editingTag) {
      formName = editingTag.name;
      formCategory = editingTag.category;
      formParentId = editingTag.parent_id ?? '';
      formScientificName = editingTag.scientific_name ?? '';
      formCommonName = editingTag.common_name ?? '';
      formGbifTaxonKey = editingTag.gbif_taxon_key ?? null;
      formGbifSearch = '';
    } else {
      formName = '';
      formCategory = 'species';
      formParentId = '';
      formScientificName = '';
      formCommonName = '';
      formGbifTaxonKey = null;
      formGbifSearch = '';
    }
    gbif.clear();
  });

  function handleFormSubmit(e: Event) {
    e.preventDefault();
    if (!formName.trim()) return;

    if (editingTag) {
      onSubmit({
        mode: 'edit',
        tagId: editingTag.id,
        data: {
          name: formName.trim(),
          parent_id: formParentId || null,
          common_name: formCommonName.trim() || undefined,
        },
      });
    } else {
      onSubmit({
        mode: 'create',
        data: {
          name: formName.trim(),
          category: formCategory,
          parent_id: formParentId || undefined,
          gbif_taxon_key: formGbifTaxonKey ?? undefined,
          scientific_name: formScientificName.trim() || undefined,
          common_name: formCommonName.trim() || undefined,
        },
      });
    }
  }

  function handleGBIFSearchInput() {
    gbif.search(formGbifSearch);
  }

  function applyGBIFSuggestion(suggestion: GBIFSuggestion) {
    formGbifTaxonKey = suggestion.key;
    formScientificName = suggestion.scientific_name;
    formCommonName = ''; // common name not available in suggestion shape
    if (!formName) {
      formName = suggestion.canonical_name;
    }
    formGbifSearch = suggestion.canonical_name;
    gbif.clear();
  }
</script>

<div class="form-container">
  <h2>{editingTag ? m.annotation_tag_edit_form_title() : m.annotation_tag_create_form_title()}</h2>

  <form onsubmit={handleFormSubmit} class="tag-form">
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
        {#each existingTags.filter((t) => !editingTag || t.id !== editingTag.id) as tag}
          <option value={tag.id}>{tag.name} ({getCategoryLabel(tag.category)})</option>
        {/each}
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
            oninput={handleGBIFSearchInput}
            placeholder={m.annotation_tag_form_gbif_placeholder()}
            autocomplete="off"
          />
          {#if gbif.isLoading}
            <div class="gbif-results gbif-results--loading">{m.annotation_tag_form_gbif_searching()}</div>
          {:else if gbif.suggestions.length > 0}
            <div class="gbif-results">
              {#each gbif.suggestions as suggestion}
                <button
                  type="button"
                  class="gbif-result-item"
                  onclick={() => applyGBIFSuggestion(suggestion)}
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
      <button type="button" class="btn-secondary" onclick={onCancel} disabled={isMutating}>
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

    {#if createError}
      <div class="form-error">
        {createError}
      </div>
    {/if}
    {#if updateError}
      <div class="form-error">
        {updateError}
      </div>
    {/if}
  </form>
</div>

<style>
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

  /* Buttons */
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
