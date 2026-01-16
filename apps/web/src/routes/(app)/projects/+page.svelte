<script lang="ts">
  /**
   * Projects list page
   */

  import { goto } from '$app/navigation';
  import { projectsApi } from '$lib/api/projects';
  import { ApiError } from '$lib/api/client';
  import type { Project } from '$lib/types';

  // State
  let projects = $state<Project[]>([]);
  let total = $state(0);
  let page = $state(1);
  let limit = $state(20);
  let isLoading = $state(true);
  let error = $state<string | null>(null);

  /**
   * Load projects
   */
  async function loadProjects() {
    isLoading = true;
    error = null;

    try {
      const response = await projectsApi.list({ page, limit });
      projects = response.items;
      total = response.total;
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = 'Failed to load projects';
      }
    } finally {
      isLoading = false;
    }
  }

  // Load projects on mount
  $effect(() => {
    loadProjects();
  });

  /**
   * Navigate to project detail
   */
  function viewProject(projectId: string) {
    goto(`/projects/${projectId}`);
  }

  /**
   * Navigate to new project page
   */
  function createNewProject() {
    goto('/projects/new');
  }

  /**
   * Change page
   */
  function changePage(newPage: number) {
    page = newPage;
  }

  /**
   * Calculate total pages
   */
  const totalPages = $derived(Math.ceil(total / limit));
</script>

<svelte:head>
  <title>Projects - Echoroo</title>
</svelte:head>

<div class="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
  <!-- Header -->
  <div class="mb-8 flex items-center justify-between">
    <div>
      <h1 class="text-3xl font-bold text-gray-900">Projects</h1>
      <p class="mt-2 text-sm text-gray-600">Manage your bioacoustic analysis projects</p>
    </div>
    <button
      onclick={createNewProject}
      class="inline-flex items-center rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
    >
      <svg
        class="mr-2 h-5 w-5"
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
      >
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
      </svg>
      New Project
    </button>
  </div>

  <!-- Error Message -->
  {#if error}
    <div class="mb-6 rounded-md bg-red-50 p-4" role="alert">
      <div class="flex">
        <div class="flex-shrink-0">
          <svg
            class="h-5 w-5 text-red-400"
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 20 20"
            fill="currentColor"
          >
            <path
              fill-rule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
              clip-rule="evenodd"
            />
          </svg>
        </div>
        <div class="ml-3">
          <p class="text-sm font-medium text-red-800">{error}</p>
        </div>
      </div>
    </div>
  {/if}

  <!-- Loading State -->
  {#if isLoading}
    <div class="flex items-center justify-center py-12">
      <svg
        class="h-8 w-8 animate-spin text-blue-600"
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
      >
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"
        ></circle>
        <path
          class="opacity-75"
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
        ></path>
      </svg>
    </div>
  {:else if projects.length === 0}
    <!-- Empty State -->
    <div class="rounded-lg border-2 border-dashed border-gray-300 p-12 text-center">
      <svg
        class="mx-auto h-12 w-12 text-gray-400"
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
      >
        <path
          stroke-linecap="round"
          stroke-linejoin="round"
          stroke-width="2"
          d="M9 13h6m-3-3v6m-9 1V7a2 2 0 012-2h6l2 2h6a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z"
        />
      </svg>
      <h3 class="mt-2 text-sm font-medium text-gray-900">No projects</h3>
      <p class="mt-1 text-sm text-gray-500">Get started by creating a new project.</p>
      <div class="mt-6">
        <button
          onclick={createNewProject}
          class="inline-flex items-center rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          <svg class="mr-2 h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M12 4v16m8-8H4"
            />
          </svg>
          New Project
        </button>
      </div>
    </div>
  {:else}
    <!-- Projects Grid -->
    <div class="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
      {#each projects as project (project.id)}
        <div
          class="cursor-pointer rounded-lg border border-gray-200 bg-white p-6 shadow-sm transition-shadow hover:shadow-md"
          onclick={() => viewProject(project.id)}
          role="button"
          tabindex="0"
          onkeydown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              viewProject(project.id);
            }
          }}
        >
          <!-- Project Header -->
          <div class="mb-4 flex items-start justify-between">
            <h3 class="text-lg font-semibold text-gray-900">{project.name}</h3>
            <span
              class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium {project.visibility ===
              'public'
                ? 'bg-green-100 text-green-800'
                : 'bg-gray-100 text-gray-800'}"
            >
              {#if project.visibility === 'public'}
                <svg class="mr-1 h-3 w-3" fill="currentColor" viewBox="0 0 20 20">
                  <path
                    fill-rule="evenodd"
                    d="M10 18a8 8 0 100-16 8 8 0 000 16zM4.332 8.027a6.012 6.012 0 011.912-2.706C6.512 5.73 6.974 6 7.5 6A1.5 1.5 0 019 7.5V8a2 2 0 004 0 2 2 0 011.523-1.943A5.977 5.977 0 0116 10c0 .34-.028.675-.083 1H15a2 2 0 00-2 2v2.197A5.973 5.973 0 0110 16v-2a2 2 0 00-2-2 2 2 0 01-2-2 2 2 0 00-1.668-1.973z"
                    clip-rule="evenodd"
                  />
                </svg>
                Public
              {:else}
                <svg class="mr-1 h-3 w-3" fill="currentColor" viewBox="0 0 20 20">
                  <path
                    fill-rule="evenodd"
                    d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z"
                    clip-rule="evenodd"
                  />
                </svg>
                Private
              {/if}
            </span>
          </div>

          <!-- Project Description -->
          {#if project.description}
            <p class="mb-4 line-clamp-2 text-sm text-gray-600">{project.description}</p>
          {:else}
            <p class="mb-4 text-sm italic text-gray-400">No description</p>
          {/if}

          <!-- Project Metadata -->
          <div class="space-y-2 text-xs text-gray-500">
            {#if project.target_taxa}
              <div class="flex items-center">
                <svg class="mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    stroke-width="2"
                    d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z"
                  />
                </svg>
                <span class="truncate">{project.target_taxa}</span>
              </div>
            {/if}
            <div class="flex items-center">
              <svg class="mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"
                />
              </svg>
              <span>{project.owner.display_name || project.owner.email}</span>
            </div>
            <div class="flex items-center">
              <svg class="mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"
                />
              </svg>
              <span>Created {new Date(project.created_at).toLocaleDateString()}</span>
            </div>
          </div>
        </div>
      {/each}
    </div>

    <!-- Pagination -->
    {#if totalPages > 1}
      <div class="mt-8 flex items-center justify-center space-x-2">
        <button
          onclick={() => changePage(page - 1)}
          disabled={page === 1}
          class="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Previous
        </button>

        {#each Array.from({ length: totalPages }, (_, i) => i + 1) as pageNum}
          {#if pageNum === 1 || pageNum === totalPages || (pageNum >= page - 1 && pageNum <= page + 1)}
            <button
              onclick={() => changePage(pageNum)}
              class="rounded-md px-4 py-2 text-sm font-medium {pageNum === page
                ? 'bg-blue-600 text-white'
                : 'border border-gray-300 bg-white text-gray-700 hover:bg-gray-50'}"
            >
              {pageNum}
            </button>
          {:else if pageNum === page - 2 || pageNum === page + 2}
            <span class="px-2 text-gray-500">...</span>
          {/if}
        {/each}

        <button
          onclick={() => changePage(page + 1)}
          disabled={page === totalPages}
          class="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Next
        </button>
      </div>
    {/if}
  {/if}
</div>
