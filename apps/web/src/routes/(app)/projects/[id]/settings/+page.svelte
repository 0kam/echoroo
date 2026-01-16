<script lang="ts">
  /**
   * Project settings page (admin only)
   */

  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { projectsApi } from '$lib/api/projects';
  import { authStore } from '$lib/stores/auth.svelte';
  import { ApiError } from '$lib/api/client';
  import type { Project, ProjectMember } from '$lib/types';

  // Get project ID from URL
  const projectId = $derived($page.params.id!);

  // State
  let project = $state<Project | null>(null);
  let members = $state<ProjectMember[]>([]);
  let name = $state('');
  let description = $state('');
  let targetTaxa = $state('');
  let visibility = $state<'private' | 'public'>('private');

  let isLoading = $state(true);
  let isSaving = $state(false);
  let error = $state<string | null>(null);
  let successMessage = $state<string | null>(null);

  // Current user
  const currentUser = $derived(authStore.user);

  // Check if current user is owner
  const isOwner = $derived(
    currentUser && project && project.owner.id === currentUser.id
  );

  // Check if current user has admin access (owner or admin role)
  const hasAdminAccess = $derived(
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

      // Initialize form fields
      name = projectData.name;
      description = projectData.description || '';
      targetTaxa = projectData.target_taxa || '';
      visibility = projectData.visibility;
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
        if (err.status === 404) {
          error = 'Project not found';
        } else if (err.status === 403) {
          error = 'You do not have permission to access this project';
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
   * Validate form
   */
  function validateForm(): boolean {
    if (!name.trim()) {
      error = 'Project name is required';
      return false;
    }

    if (name.length > 200) {
      error = 'Project name must be less than 200 characters';
      return false;
    }

    if (targetTaxa && targetTaxa.length > 500) {
      error = 'Target taxa must be less than 500 characters';
      return false;
    }

    return true;
  }

  /**
   * Save changes
   */
  async function handleSave(e: Event) {
    e.preventDefault();
    error = null;
    successMessage = null;

    if (!hasAdminAccess) {
      error = 'You do not have permission to edit this project';
      return;
    }

    if (!validateForm()) {
      return;
    }

    isSaving = true;

    try {
      const updated = await projectsApi.update(projectId, {
        name: name.trim(),
        description: description.trim() || undefined,
        target_taxa: targetTaxa.trim() || undefined,
        visibility,
      });

      project = updated;
      successMessage = 'Project settings saved successfully';

      // Clear success message after 3 seconds
      setTimeout(() => {
        successMessage = null;
      }, 3000);
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = 'Failed to save changes. Please try again.';
      }
    } finally {
      isSaving = false;
    }
  }

  /**
   * Cancel and go back
   */
  function handleCancel() {
    goto(`/projects/${projectId}`);
  }
</script>

<svelte:head>
  <title>Project Settings - Echoroo</title>
</svelte:head>

<div class="mx-auto max-w-3xl px-4 py-8 sm:px-6 lg:px-8">
  <!-- Header -->
  <div class="mb-8">
    <h1 class="text-3xl font-bold text-gray-900">Project Settings</h1>
    <p class="mt-2 text-sm text-gray-600">
      Manage your project settings and visibility. Only project admins can edit these settings.
    </p>
  </div>

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
  {:else if !hasAdminAccess}
    <!-- Access Denied -->
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
          <p class="text-sm font-medium text-red-800">
            You do not have permission to edit this project
          </p>
        </div>
      </div>
      <div class="mt-4">
        <a
          href="/projects/{projectId}"
          class="text-sm font-medium text-blue-600 hover:text-blue-500"
        >
          Back to Project
        </a>
      </div>
    </div>
  {:else}
    <!-- Success Message -->
    {#if successMessage}
      <div class="mb-6 rounded-md bg-green-50 p-4" role="alert">
        <div class="flex">
          <div class="flex-shrink-0">
            <svg
              class="h-5 w-5 text-green-400"
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 20 20"
              fill="currentColor"
            >
              <path
                fill-rule="evenodd"
                d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
                clip-rule="evenodd"
              />
            </svg>
          </div>
          <div class="ml-3">
            <p class="text-sm font-medium text-green-800">{successMessage}</p>
          </div>
        </div>
      </div>
    {/if}

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

    <!-- Settings Form -->
    <form onsubmit={handleSave} class="space-y-6">
      <div class="rounded-lg bg-white shadow">
        <div class="space-y-6 p-6">
          <!-- Project Name -->
          <div>
            <label for="name" class="block text-sm font-medium text-gray-700">
              Project Name <span class="text-red-500">*</span>
            </label>
            <input
              id="name"
              name="name"
              type="text"
              required
              bind:value={name}
              disabled={isSaving}
              class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-blue-500 disabled:bg-gray-100 disabled:cursor-not-allowed sm:text-sm"
              placeholder="e.g., Bird Survey 2026"
            />
          </div>

          <!-- Description -->
          <div>
            <label for="description" class="block text-sm font-medium text-gray-700">
              Description
            </label>
            <textarea
              id="description"
              name="description"
              rows="4"
              bind:value={description}
              disabled={isSaving}
              class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-blue-500 disabled:bg-gray-100 disabled:cursor-not-allowed sm:text-sm"
              placeholder="What is this project about?"
            ></textarea>
          </div>

          <!-- Target Taxa -->
          <div>
            <label for="targetTaxa" class="block text-sm font-medium text-gray-700">
              Target Taxa
            </label>
            <input
              id="targetTaxa"
              name="targetTaxa"
              type="text"
              bind:value={targetTaxa}
              disabled={isSaving}
              class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-blue-500 disabled:bg-gray-100 disabled:cursor-not-allowed sm:text-sm"
              placeholder="e.g., Passeriformes, Aves"
            />
          </div>

          <!-- Visibility -->
          <div>
            <span class="block text-sm font-medium text-gray-700" id="visibility-label">Visibility</span>
            <div class="mt-2 space-y-2" role="radiogroup" aria-labelledby="visibility-label">
              <label class="flex items-start">
                <input
                  type="radio"
                  name="visibility"
                  value="private"
                  bind:group={visibility}
                  disabled={isSaving}
                  class="mt-0.5 h-4 w-4 border-gray-300 text-blue-600 focus:ring-blue-500"
                />
                <div class="ml-3">
                  <div class="flex items-center">
                    <svg class="mr-1.5 h-4 w-4 text-gray-500" fill="currentColor" viewBox="0 0 20 20">
                      <path
                        fill-rule="evenodd"
                        d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z"
                        clip-rule="evenodd"
                      />
                    </svg>
                    <span class="text-sm font-medium text-gray-700">Private</span>
                  </div>
                  <p class="text-xs text-gray-500">Only you and invited members can access</p>
                </div>
              </label>

              <label class="flex items-start">
                <input
                  type="radio"
                  name="visibility"
                  value="public"
                  bind:group={visibility}
                  disabled={isSaving}
                  class="mt-0.5 h-4 w-4 border-gray-300 text-blue-600 focus:ring-blue-500"
                />
                <div class="ml-3">
                  <div class="flex items-center">
                    <svg class="mr-1.5 h-4 w-4 text-gray-500" fill="currentColor" viewBox="0 0 20 20">
                      <path
                        fill-rule="evenodd"
                        d="M10 18a8 8 0 100-16 8 8 0 000 16zM4.332 8.027a6.012 6.012 0 011.912-2.706C6.512 5.73 6.974 6 7.5 6A1.5 1.5 0 019 7.5V8a2 2 0 004 0 2 2 0 011.523-1.943A5.977 5.977 0 0116 10c0 .34-.028.675-.083 1H15a2 2 0 00-2 2v2.197A5.973 5.973 0 0110 16v-2a2 2 0 00-2-2 2 2 0 01-2-2 2 2 0 00-1.668-1.973z"
                        clip-rule="evenodd"
                      />
                    </svg>
                    <span class="text-sm font-medium text-gray-700">Public</span>
                  </div>
                  <p class="text-xs text-gray-500">Anyone can view this project</p>
                </div>
              </label>
            </div>
          </div>
        </div>

        <!-- Form Actions -->
        <div class="flex justify-end space-x-3 border-t border-gray-200 bg-gray-50 px-6 py-4">
          <button
            type="button"
            onclick={handleCancel}
            disabled={isSaving}
            class="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={isSaving}
            class="inline-flex items-center rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {#if isSaving}
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
              Saving...
            {:else}
              Save Changes
            {/if}
          </button>
        </div>
      </div>
    </form>
  {/if}
</div>
