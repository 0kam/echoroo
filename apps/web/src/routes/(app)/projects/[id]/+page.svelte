<script lang="ts">
  /**
   * Project detail page
   */

  import { goto } from '$app/navigation';
  import { projectsApi } from '$lib/api/projects';
  import { authStore } from '$lib/stores/auth.svelte';
  import { ApiError } from '$lib/api/client';
  import type { Project, ProjectMember } from '$lib/types';

  // Props
  let { data } = $props();
  const projectId = $derived(data.projectId);

  // State
  let project = $state<Project | null>(null);
  let members = $state<ProjectMember[]>([]);
  let isLoading = $state(true);
  let error = $state<string | null>(null);
  let showDeleteDialog = $state(false);
  let isDeleting = $state(false);

  // Current user
  const currentUser = $derived(authStore.user);

  // Check if current user is owner
  const isOwner = $derived(
    currentUser && project && project.owner.id === currentUser.id
  );

  // Check if current user is admin
  const isAdmin = $derived(
    (() => {
      if (!currentUser || !project) return false;
      if (isOwner) return true;

      const member = members.find((m) => m.user.id === currentUser.id);
      return member?.role === 'admin';
    })()
  );

  /**
   * Load project and members
   */
  async function loadProject() {
    isLoading = true;
    error = null;

    try {
      const [projectData, membersData] = await Promise.all([
        projectsApi.get(projectId),
        projectsApi.listMembers(projectId),
      ]);

      project = projectData;
      members = membersData;
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
        if (err.status === 404) {
          error = 'Project not found';
        } else if (err.status === 403) {
          error = 'You do not have permission to view this project';
        }
      } else {
        error = 'Failed to load project';
      }
    } finally {
      isLoading = false;
    }
  }

  // Load project on mount
  $effect(() => {
    loadProject();
  });

  /**
   * Navigate to settings
   */
  function goToSettings() {
    goto(`/projects/${projectId}/settings`);
  }

  /**
   * Navigate to members
   */
  function goToMembers() {
    goto(`/projects/${projectId}/members`);
  }

  /**
   * Show delete confirmation dialog
   */
  function showDeleteConfirmation() {
    showDeleteDialog = true;
  }

  /**
   * Cancel delete
   */
  function cancelDelete() {
    showDeleteDialog = false;
  }

  /**
   * Delete project
   */
  async function deleteProject() {
    isDeleting = true;

    try {
      await projectsApi.delete(projectId);
      // Redirect to projects list
      await goto('/projects');
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = 'Failed to delete project';
      }
      showDeleteDialog = false;
    } finally {
      isDeleting = false;
    }
  }
</script>

<svelte:head>
  <title>{project ? project.name : 'Project'} - Echoroo</title>
</svelte:head>

<div class="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
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
  {:else if error}
    <!-- Error State -->
    <div class="rounded-md bg-red-50 p-4" role="alert">
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
      <div class="mt-4">
        <a href="/projects" class="text-sm font-medium text-blue-600 hover:text-blue-500">
          Back to Projects
        </a>
      </div>
    </div>
  {:else if project}
    <!-- Project Header -->
    <div class="mb-8">
      <div class="flex items-start justify-between">
        <div>
          <div class="flex items-center space-x-3">
            <h1 class="text-3xl font-bold text-gray-900">{project.name}</h1>
            <span
              class="inline-flex items-center rounded-full px-3 py-1 text-sm font-medium {project.visibility ===
              'public'
                ? 'bg-green-100 text-green-800'
                : 'bg-gray-100 text-gray-800'}"
            >
              {#if project.visibility === 'public'}
                <svg class="mr-1.5 h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
                  <path
                    fill-rule="evenodd"
                    d="M10 18a8 8 0 100-16 8 8 0 000 16zM4.332 8.027a6.012 6.012 0 011.912-2.706C6.512 5.73 6.974 6 7.5 6A1.5 1.5 0 019 7.5V8a2 2 0 004 0 2 2 0 011.523-1.943A5.977 5.977 0 0116 10c0 .34-.028.675-.083 1H15a2 2 0 00-2 2v2.197A5.973 5.973 0 0110 16v-2a2 2 0 00-2-2 2 2 0 01-2-2 2 2 0 00-1.668-1.973z"
                    clip-rule="evenodd"
                  />
                </svg>
                Public
              {:else}
                <svg class="mr-1.5 h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
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
          <p class="mt-2 text-sm text-gray-600">
            Created {new Date(project.created_at).toLocaleDateString()} by {project.owner
              .display_name || project.owner.email}
          </p>
        </div>

        <!-- Actions -->
        <div class="flex space-x-3">
          {#if isAdmin}
            <button
              onclick={goToSettings}
              class="inline-flex items-center rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              <svg class="mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
                />
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                />
              </svg>
              Settings
            </button>
          {/if}

          {#if isOwner}
            <button
              onclick={showDeleteConfirmation}
              class="inline-flex items-center rounded-md border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-50"
            >
              <svg class="mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                />
              </svg>
              Delete
            </button>
          {/if}
        </div>
      </div>
    </div>

    <!-- Project Content -->
    <div class="grid gap-6 lg:grid-cols-3">
      <!-- Main Content -->
      <div class="lg:col-span-2">
        <!-- Description -->
        <div class="mb-6 rounded-lg bg-white p-6 shadow">
          <h2 class="mb-4 text-lg font-semibold text-gray-900">Description</h2>
          {#if project.description}
            <p class="whitespace-pre-wrap text-sm text-gray-700">{project.description}</p>
          {:else}
            <p class="text-sm italic text-gray-400">No description provided</p>
          {/if}
        </div>

        <!-- Target Taxa -->
        {#if project.target_taxa}
          <div class="mb-6 rounded-lg bg-white p-6 shadow">
            <h2 class="mb-4 text-lg font-semibold text-gray-900">Target Taxa</h2>
            <p class="text-sm text-gray-700">{project.target_taxa}</p>
          </div>
        {/if}

        <!-- Placeholder for future content -->
        <div class="rounded-lg border-2 border-dashed border-gray-300 p-12 text-center">
          <svg
            class="mx-auto h-12 w-12 text-gray-400"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3"
            />
          </svg>
          <h3 class="mt-2 text-sm font-medium text-gray-900">No recordings yet</h3>
          <p class="mt-1 text-sm text-gray-500">Upload recordings to start analyzing.</p>
        </div>
      </div>

      <!-- Sidebar -->
      <div class="space-y-6">
        <!-- Project Members -->
        <div class="rounded-lg bg-white p-6 shadow">
          <div class="mb-4 flex items-center justify-between">
            <h2 class="text-lg font-semibold text-gray-900">Members</h2>
            {#if isAdmin}
              <button
                onclick={goToMembers}
                class="text-sm font-medium text-blue-600 hover:text-blue-500"
              >
                Manage
              </button>
            {/if}
          </div>

          <div class="space-y-3">
            {#each members.slice(0, 5) as member (member.id)}
              <div class="flex items-center justify-between">
                <div class="flex items-center space-x-3">
                  <div class="flex h-8 w-8 items-center justify-center rounded-full bg-gray-200">
                    <span class="text-xs font-medium text-gray-600">
                      {(member.user?.display_name || member.user?.email || 'U').charAt(0).toUpperCase()}
                    </span>
                  </div>
                  <div class="min-w-0 flex-1">
                    <p class="truncate text-sm font-medium text-gray-900">
                      {member.user.display_name || member.user.email}
                    </p>
                    <p class="truncate text-xs text-gray-500">{member.role}</p>
                  </div>
                </div>
              </div>
            {/each}

            {#if members.length > 5}
              <button
                onclick={goToMembers}
                class="w-full pt-2 text-center text-sm text-gray-600 hover:text-gray-900"
              >
                View all {members.length} members
              </button>
            {/if}
          </div>
        </div>
      </div>
    </div>
  {/if}
</div>

<!-- Delete Confirmation Dialog -->
{#if showDeleteDialog}
  <div class="fixed inset-0 z-50 overflow-y-auto" aria-labelledby="modal-title" role="dialog">
    <div class="flex min-h-screen items-end justify-center px-4 pb-20 pt-4 text-center sm:block sm:p-0">
      <!-- Background overlay -->
      <div
        role="button"
        tabindex="0"
        aria-label="Close dialog"
        class="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
        onclick={cancelDelete}
        onkeydown={(e) => e.key === 'Escape' && cancelDelete()}
      ></div>

      <!-- Modal panel -->
      <div
        class="inline-block transform overflow-hidden rounded-lg bg-white text-left align-bottom shadow-xl transition-all sm:my-8 sm:w-full sm:max-w-lg sm:align-middle"
      >
        <div class="bg-white px-4 pb-4 pt-5 sm:p-6 sm:pb-4">
          <div class="sm:flex sm:items-start">
            <div
              class="mx-auto flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-full bg-red-100 sm:mx-0 sm:h-10 sm:w-10"
            >
              <svg class="h-6 w-6 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
                />
              </svg>
            </div>
            <div class="mt-3 text-center sm:ml-4 sm:mt-0 sm:text-left">
              <h3 class="text-lg font-medium leading-6 text-gray-900" id="modal-title">
                Delete Project
              </h3>
              <div class="mt-2">
                <p class="text-sm text-gray-500">
                  Are you sure you want to delete "{project?.name}"? This action cannot be undone and
                  will permanently delete all recordings, annotations, and data associated with this
                  project.
                </p>
              </div>
            </div>
          </div>
        </div>
        <div class="bg-gray-50 px-4 py-3 sm:flex sm:flex-row-reverse sm:px-6">
          <button
            type="button"
            onclick={deleteProject}
            disabled={isDeleting}
            class="inline-flex w-full justify-center rounded-md bg-red-600 px-4 py-2 text-base font-medium text-white shadow-sm hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 sm:ml-3 sm:w-auto sm:text-sm"
          >
            {#if isDeleting}
              <svg
                class="mr-2 h-4 w-4 animate-spin"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
              >
                <circle
                  class="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  stroke-width="4"
                ></circle>
                <path
                  class="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                ></path>
              </svg>
              Deleting...
            {:else}
              Delete
            {/if}
          </button>
          <button
            type="button"
            onclick={cancelDelete}
            disabled={isDeleting}
            class="mt-3 inline-flex w-full justify-center rounded-md border border-gray-300 bg-white px-4 py-2 text-base font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 sm:ml-3 sm:mt-0 sm:w-auto sm:text-sm"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  </div>
{/if}
