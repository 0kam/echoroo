<script lang="ts">
  /**
   * Tag management page.
   *
   * Orchestration shell: owns the TanStack queries + mutations and the
   * filter / pagination / form / delete state, then delegates the form, list,
   * filters, and statistics to dedicated components under
   * `$lib/components/tags/`.
   */
  import { page } from '$app/stores';
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import {
    fetchTags,
    createTag,
    updateTag,
    deleteTag,
    fetchTagStatistics,
  } from '$lib/api/tags';
  import type { Tag, TagCategory, TagCreate, TagUpdate } from '$lib/types/tag';
  import ConfirmDialog from '$lib/components/ui/ConfirmDialog.svelte';
  import TagForm from '$lib/components/tags/TagForm.svelte';
  import TagFilters from '$lib/components/tags/TagFilters.svelte';
  import TagList from '$lib/components/tags/TagList.svelte';
  import TagStatistics from '$lib/components/tags/TagStatistics.svelte';
  import type { TagFormSubmit } from '$lib/components/tags/types';

  const queryClient = useQueryClient();

  $: projectId = $page.params.id as string;

  // Filter / pagination state
  let currentPage = 1;
  let search = '';
  let categoryFilter: TagCategory | '' = '';

  // Form state
  let showForm = false;
  let editingTag: Tag | null = null;

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
    showForm = true;
  }

  function openEditForm(tag: Tag) {
    editingTag = tag;
    showForm = true;
  }

  function closeForm() {
    showForm = false;
    editingTag = null;
  }

  async function handleFormSubmit(payload: TagFormSubmit) {
    if (payload.mode === 'edit') {
      await $updateMutationStore.mutateAsync({ tagId: payload.tagId, data: payload.data });
    } else {
      await $createMutationStore.mutateAsync(payload.data);
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

  function handlePageChange(next: number) {
    currentPage = next;
  }

  $: isMutating =
    $createMutationStore.isPending || $updateMutationStore.isPending;
  $: createError = $createMutationStore.isError
    ? $createMutationStore.error?.message || m.annotation_tag_form_error_create()
    : null;
  $: updateError = $updateMutationStore.isError
    ? $updateMutationStore.error?.message || m.annotation_tag_form_error_update()
    : null;
</script>

<svelte:head>
  <title>{m.annotation_tag_page_title()}</title>
</svelte:head>

<div class="tags-page">
  <!-- Page header -->
  <header class="page-header">
    <div class="page-header__left">
      <a href={localizeHref(`/projects/${projectId}/settings`)} class="back-link">
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
    <TagForm
      {editingTag}
      existingTags={$tagsQuery.data?.items ?? []}
      {projectId}
      {isMutating}
      {createError}
      {updateError}
      onSubmit={handleFormSubmit}
      onCancel={closeForm}
    />
  {/if}

  <!-- Filters -->
  <TagFilters
    {categoryFilter}
    bind:search
    onCategoryChange={handleCategoryFilterChange}
    onSearchInput={handleSearchInput}
  />

  <!-- Tag list -->
  <TagList
    data={$tagsQuery.data}
    isLoading={$tagsQuery.isLoading}
    isError={$tagsQuery.isError}
    errorMessage={$tagsQuery.error?.message ?? ''}
    {search}
    {categoryFilter}
    {currentPage}
    onEdit={openEditForm}
    onDelete={handleDeleteClick}
    onPageChange={handlePageChange}
  />

  <!-- Statistics section -->
  <TagStatistics stats={$statisticsQuery.data ?? []} />

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
</style>
