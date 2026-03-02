<script lang="ts">
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import {
    fetchAnnotationProjects,
    createAnnotationProject,
    deleteAnnotationProject,
  } from '$lib/api/annotation-projects';
  import type {
    AnnotationProjectDetail,
    AnnotationProjectCreate,
    AnnotationProjectUpdate,
  } from '$lib/types/annotation';
  import AnnotationProjectList from '$lib/components/annotation/AnnotationProjectList.svelte';
  import AnnotationProjectForm from '$lib/components/annotation/AnnotationProjectForm.svelte';
  import ConfirmDialog from '$lib/components/ui/ConfirmDialog.svelte';

  const queryClient = useQueryClient();

  $: projectId = $page.params.id as string;

  let showCreateForm = false;
  let projectToDelete: AnnotationProjectDetail | null = null;
  let showDeleteDialog = false;

  // Pagination state
  let currentPage = 1;

  // Query for annotation projects
  $: annotationProjectsQuery = createQuery({
    queryKey: ['annotation-projects', projectId, currentPage],
    queryFn: () =>
      fetchAnnotationProjects(projectId, {
        page: currentPage,
        page_size: 20,
      }),
  });

  // Mutation for creating an annotation project
  const annotationProjectCreateMutation = createMutation({
    mutationFn: (data: AnnotationProjectCreate) => createAnnotationProject(projectId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['annotation-projects', projectId] });
      showCreateForm = false;
    },
  });

  // Mutation for deleting an annotation project
  const deleteMutation = createMutation({
    mutationFn: (annotationProjectId: string) =>
      deleteAnnotationProject(projectId, annotationProjectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['annotation-projects', projectId] });
      projectToDelete = null;
    },
  });

  function handleProjectSelect(project: AnnotationProjectDetail) {
    goto(`/projects/${projectId}/annotations/${project.id}`);
  }

  function handleDeleteClick(project: AnnotationProjectDetail) {
    projectToDelete = project;
    showDeleteDialog = true;
  }

  async function confirmDelete() {
    if (projectToDelete) {
      await $deleteMutation.mutateAsync(projectToDelete.id);
      showDeleteDialog = false;
      projectToDelete = null;
    }
  }

  function cancelDelete() {
    showDeleteDialog = false;
    projectToDelete = null;
  }

  async function handleCreateSubmit(data: AnnotationProjectCreate | AnnotationProjectUpdate) {
    await $annotationProjectCreateMutation.mutateAsync(data as AnnotationProjectCreate);
  }
</script>

<svelte:head>
  <title>Annotation Projects | Project</title>
</svelte:head>

<div class="annotations-page">
  <header class="page-header">
    <div>
      <h1>Annotation Projects</h1>
      <p>Manage annotation workflows for audio clips</p>
    </div>
    {#if !showCreateForm}
      <button class="btn-primary" on:click={() => (showCreateForm = true)}>
        + New Annotation Project
      </button>
    {/if}
  </header>

  {#if showCreateForm}
    <div class="create-form-container">
      <h2>Create New Annotation Project</h2>
      <AnnotationProjectForm
        {projectId}
        project={null}
        onSubmit={handleCreateSubmit}
        onCancel={() => (showCreateForm = false)}
      />
      {#if $annotationProjectCreateMutation.isError}
        <div class="form-error">
          {$annotationProjectCreateMutation.error?.message ||
            'Failed to create annotation project'}
        </div>
      {/if}
    </div>
  {:else if $annotationProjectsQuery.isLoading}
    <div class="loading">Loading annotation projects...</div>
  {:else if $annotationProjectsQuery.isError}
    <div class="error">
      Error loading annotation projects: {$annotationProjectsQuery.error?.message}
    </div>
  {:else if $annotationProjectsQuery.data}
    <AnnotationProjectList
      projects={$annotationProjectsQuery.data.items}
      onSelect={handleProjectSelect}
      onDelete={handleDeleteClick}
    />

    <!-- Pagination -->
    {#if $annotationProjectsQuery.data.pages > 1}
      <div class="pagination">
        <button
          class="page-btn"
          on:click={() => (currentPage = Math.max(1, currentPage - 1))}
          disabled={currentPage === 1}
        >
          Previous
        </button>

        <span class="page-info">
          Page {currentPage} of {$annotationProjectsQuery.data.pages}
        </span>

        <button
          class="page-btn"
          on:click={() =>
            (currentPage = Math.min($annotationProjectsQuery.data.pages, currentPage + 1))}
          disabled={currentPage === $annotationProjectsQuery.data.pages}
        >
          Next
        </button>
      </div>
    {/if}

    {#if $annotationProjectsQuery.data.total > 0}
      <div class="pagination-info">
        Showing {$annotationProjectsQuery.data.items.length} of {$annotationProjectsQuery.data
          .total} annotation projects
      </div>
    {/if}
  {/if}

  <!-- Delete Confirmation Dialog -->
  <ConfirmDialog
    isOpen={showDeleteDialog}
    title="Delete Annotation Project"
    message={projectToDelete
      ? `Are you sure you want to delete "${projectToDelete.name}"? This action cannot be undone.`
      : ''}
    confirmText="Delete Annotation Project"
    cancelText="Cancel"
    isDanger={true}
    onConfirm={confirmDelete}
    onCancel={cancelDelete}
    warningItems={['All associated annotation tasks', 'All clip annotations and sound events']}
  />
</div>

<style>
  .annotations-page {
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

  .page-header h1 {
    margin: 0 0 0.25rem 0;
    font-size: 1.5rem;
    font-weight: 600;
  }

  .page-header p {
    margin: 0;
    color: #6b7280;
  }

  .create-form-container {
    background: white;
    padding: 1.5rem;
    border-radius: 0.5rem;
    border: 1px solid #e5e7eb;
    margin-bottom: 2rem;
  }

  .create-form-container h2 {
    margin: 0 0 1.5rem 0;
    font-size: 1.125rem;
    font-weight: 600;
  }

  .form-error {
    margin-top: 1rem;
    padding: 0.75rem;
    background: #fef2f2;
    border: 1px solid #fecaca;
    border-radius: 0.375rem;
    color: #dc2626;
    font-size: 0.875rem;
  }

  .loading,
  .error {
    padding: 2rem;
    text-align: center;
    border-radius: 0.5rem;
  }

  .loading {
    background: #f3f4f6;
    color: #6b7280;
  }

  .error {
    background: #fef2f2;
    color: #dc2626;
  }

  .pagination {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 1rem;
    margin-top: 1.5rem;
  }

  .page-btn {
    padding: 0.5rem 1rem;
    background: white;
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

  .btn-primary {
    padding: 0.625rem 1rem;
    background: #3b82f6;
    color: white;
    border: none;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    font-weight: 500;
    cursor: pointer;
  }

  .btn-primary:hover {
    background: #2563eb;
  }
</style>
