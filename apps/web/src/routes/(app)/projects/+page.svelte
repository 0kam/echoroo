<script lang="ts">
  /**
   * Projects list page
   */

  import { goto } from '$app/navigation';
  import { projectsApi } from '$lib/api/projects';
  import { ApiError } from '$lib/api/client';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import type { ProjectSummary } from '$lib/types';

  // State.
  //
  // Phase 9 / FR-018, FR-019: the list endpoint returns `ProjectSummary`
  // rows — a deliberately narrow projection over `Project` that strips
  // `restricted_config`, the full `owner` sub-object, and timestamps so
  // Guest enumeration of Restricted projects cannot leak any field
  // beyond the documented summary slot. The list view is therefore
  // limited to `name / description / visibility / status / license /
  // owner_display_name / dataset_count / species_preview`.
  let projects = $state<ProjectSummary[]>([]);
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
        error = m.project_load_error();
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
    goto(localizeHref(`/projects/${projectId}`));
  }

  /**
   * Navigate to new project page
   */
  function createNewProject() {
    goto(localizeHref('/projects/new'));
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
  <title>{m.project_page_title()}</title>
</svelte:head>

<div class="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
  <!-- Header -->
  <div class="mb-8 flex items-center justify-between">
    <div>
      <h1 class="text-3xl font-bold text-stone-900">{m.project_heading()}</h1>
      <p class="mt-2 text-sm text-stone-600">{m.project_description()}</p>
    </div>
    <button
      onclick={createNewProject}
      class="inline-flex items-center rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
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
      {m.project_new_button()}
    </button>
  </div>

  <!-- Error Message -->
  {#if error}
    <div class="mb-6 rounded-md bg-danger-light p-4" role="alert">
      <div class="flex">
        <div class="flex-shrink-0">
          <svg
            class="h-5 w-5 text-danger"
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
          <p class="text-sm font-medium text-danger">{error}</p>
        </div>
      </div>
    </div>
  {/if}

  <!-- Loading State -->
  {#if isLoading}
    <div class="flex items-center justify-center py-12">
      <svg
        class="h-8 w-8 animate-spin text-primary-600"
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
    <div class="rounded-lg border-2 border-dashed border-stone-300 p-12 text-center">
      <svg
        class="mx-auto h-12 w-12 text-stone-400"
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
      <h3 class="mt-2 text-sm font-medium text-stone-900">{m.project_no_projects_title()}</h3>
      <p class="mt-1 text-sm text-stone-500">{m.project_no_projects_body()}</p>
      <div class="mt-6">
        <button
          onclick={createNewProject}
          class="inline-flex items-center rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
        >
          <svg class="mr-2 h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M12 4v16m8-8H4"
            />
          </svg>
          {m.project_new_button()}
        </button>
      </div>
    </div>
  {:else}
    <!-- Projects Grid -->
    <div class="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
      {#each projects as project (project.id)}
        <div
          class="cursor-pointer rounded-lg border border-card bg-surface-card p-6 shadow-sm transition-shadow hover:shadow-md"
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
            <h3 class="text-lg font-semibold text-stone-900">{project.name}</h3>
            <!-- Visibility badge: public or restricted. -->
            <span
              class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium {project.visibility ===
              'public'
                ? 'bg-success-light text-success'
                : 'bg-warning-light text-warning'}"
            >
              {#if project.visibility === 'public'}
                <svg class="mr-1 h-3 w-3" fill="currentColor" viewBox="0 0 20 20">
                  <path
                    fill-rule="evenodd"
                    d="M10 18a8 8 0 100-16 8 8 0 000 16zM4.332 8.027a6.012 6.012 0 011.912-2.706C6.512 5.73 6.974 6 7.5 6A1.5 1.5 0 019 7.5V8a2 2 0 004 0 2 2 0 011.523-1.943A5.977 5.977 0 0116 10c0 .34-.028.675-.083 1H15a2 2 0 00-2 2v2.197A5.973 5.973 0 0110 16v-2a2 2 0 00-2-2 2 2 0 01-2-2 2 2 0 00-1.668-1.973z"
                    clip-rule="evenodd"
                  />
                </svg>
                {m.project_visibility_public()}
              {:else}
                <svg class="mr-1 h-3 w-3" fill="currentColor" viewBox="0 0 20 20">
                  <path
                    fill-rule="evenodd"
                    d="M18 8a6 6 0 01-7.743 5.743L10 14l-1 1-1 1H6v2H2v-4l4.257-4.257A6 6 0 1118 8zm-6-4a1 1 0 100 2 2 2 0 012 2 1 1 0 102 0 4 4 0 00-4-4z"
                    clip-rule="evenodd"
                  />
                </svg>
                {m.project_visibility_restricted()}
              {/if}
            </span>
          </div>

          <!-- Project Description -->
          {#if project.description}
            <p class="mb-4 line-clamp-2 text-sm text-stone-600">{project.description}</p>
          {:else}
            <p class="mb-4 text-sm italic text-stone-400">{m.project_no_description()}</p>
          {/if}

          <!--
            Project Metadata.

            Phase 9 / FR-019: the summary slot only carries
            `owner_display_name`, `dataset_count`, and a small
            `species_preview` list. Older fields (`target_taxa`,
            `created_at`, full `owner.email`) live on `ProjectResponse`
            and are visible only on the detail page.
          -->
          <div class="space-y-2 text-xs text-stone-500">
            <div class="flex items-center">
              <svg class="mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"
                />
              </svg>
              <span class="truncate">{project.owner_display_name}</span>
            </div>
            <div class="flex items-center">
              <svg class="mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4"
                />
              </svg>
              <span>{project.dataset_count === 1
                ? m.project_summary_dataset_count_one()
                : m.project_summary_dataset_count_other({ count: project.dataset_count })}</span>
            </div>
            {#if project.species_preview.length > 0}
              <div class="flex items-start">
                <svg class="mr-2 mt-0.5 h-4 w-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    stroke-width="2"
                    d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z"
                  />
                </svg>
                <span class="line-clamp-1">{project.species_preview.join(', ')}</span>
              </div>
            {/if}
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
          class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {m.project_previous()}
        </button>

        {#each Array.from({ length: totalPages }, (_, i) => i + 1) as pageNum}
          {#if pageNum === 1 || pageNum === totalPages || (pageNum >= page - 1 && pageNum <= page + 1)}
            <button
              onclick={() => changePage(pageNum)}
              class="rounded-md px-4 py-2 text-sm font-medium {pageNum === page
                ? 'bg-primary-600 text-white dark:bg-primary-500 dark:text-stone-50'
                : 'border border-stone-300 bg-surface-card text-stone-700 hover:bg-stone-50'}"
            >
              {pageNum}
            </button>
          {:else if pageNum === page - 2 || pageNum === page + 2}
            <span class="px-2 text-stone-500">...</span>
          {/if}
        {/each}

        <button
          onclick={() => changePage(page + 1)}
          disabled={page === totalPages}
          class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {m.project_next()}
        </button>
      </div>
    {/if}
  {/if}
</div>
