<script lang="ts">
  /**
   * Project settings page (admin only)
   */

  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { projectsApi } from '$lib/api/projects';
  import { authStore } from '$lib/stores/auth.svelte';
  import { ApiError } from '$lib/api/client';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import type { Project, ProjectMember } from '$lib/types';

  // Predefined taxa options
  const TARGET_TAXA_OPTIONS = [
    { value: 'Birds', label: 'Birds' },
    { value: 'Anurans', label: 'Anurans' },
    { value: 'Insects', label: 'Insects' },
    { value: 'Bats', label: 'Bats' },
    { value: 'Land mammals', label: 'Land mammals' },
    { value: 'Fishes', label: 'Fishes' },
    { value: 'Cetaceans', label: 'Cetaceans' },
  ];

  // Get project ID from URL
  const projectId = $derived($page.params.id!);

  // State
  let project = $state<Project | null>(null);
  let members = $state<ProjectMember[]>([]);
  let name = $state('');
  let description = $state('');
  let selectedTaxa = $state<string[]>([]);
  let visibility = $state<'private' | 'public'>('private');

  // Derived comma-separated string for API
  const targetTaxa = $derived(selectedTaxa.join(', '));

  /**
   * Toggle a taxon selection
   */
  function toggleTaxon(value: string) {
    if (selectedTaxa.includes(value)) {
      selectedTaxa = selectedTaxa.filter((t) => t !== value);
    } else {
      selectedTaxa = [...selectedTaxa, value];
    }
  }

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
      // Parse comma-separated taxa string into array of selected values
      const rawTaxa = projectData.target_taxa || '';
      selectedTaxa = rawTaxa
        ? rawTaxa
            .split(',')
            .map((t) => t.trim())
            .filter((t) => TARGET_TAXA_OPTIONS.some((opt) => opt.value === t))
        : [];
      visibility = projectData.visibility;
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
        if (err.status === 404) {
          error = m.project_settings_error_not_found();
        } else if (err.status === 403) {
          error = m.project_settings_error_forbidden();
        }
      } else {
        error = m.project_settings_error_load();
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
      error = m.project_settings_name_required();
      return false;
    }

    if (name.length > 200) {
      error = m.project_settings_name_too_long();
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
      error = m.project_settings_error_permission();
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
        target_taxa: targetTaxa || undefined,
        visibility,
      });

      project = updated;
      successMessage = m.project_settings_save_success();

      // Clear success message after 3 seconds
      setTimeout(() => {
        successMessage = null;
      }, 3000);
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = m.project_settings_error_save();
      }
    } finally {
      isSaving = false;
    }
  }

  /**
   * Cancel and go back
   */
  function handleCancel() {
    goto(localizeHref(`/projects/${projectId}`));
  }
</script>

<svelte:head>
  <title>{m.project_settings_page_title()}</title>
</svelte:head>

<div class="mx-auto max-w-3xl px-4 py-8 sm:px-6 lg:px-8">
  <!-- Header -->
  <div class="mb-8">
    <h1 class="text-3xl font-bold text-stone-900">{m.project_settings_heading()}</h1>
    <p class="mt-2 text-sm text-stone-600">
      {m.project_settings_description()}
    </p>
  </div>

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
            {m.project_settings_access_denied()}
          </p>
        </div>
      </div>
      <div class="mt-4">
        <a
          href={localizeHref(`/projects/${projectId}`)}
          class="text-sm font-medium text-primary-600 hover:text-primary-500"
        >
          {m.project_settings_back_to_project()}
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
      <div class="rounded-lg bg-surface-card shadow">
        <div class="space-y-6 p-6">
          <!-- Project Name -->
          <div>
            <label for="name" class="block text-sm font-medium text-stone-700">
              {m.project_settings_name_label()} <span class="text-red-500">*</span>
            </label>
            <input
              id="name"
              name="name"
              type="text"
              required
              bind:value={name}
              disabled={isSaving}
              class="mt-1 block w-full rounded-md border border-stone-300 px-3 py-2 text-stone-900 placeholder-stone-400 focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:bg-stone-100 disabled:cursor-not-allowed sm:text-sm"
              placeholder={m.project_settings_name_placeholder()}
            />
          </div>

          <!-- Description -->
          <div>
            <label for="description" class="block text-sm font-medium text-stone-700">
              {m.project_settings_description_label()}
            </label>
            <textarea
              id="description"
              name="description"
              rows="4"
              bind:value={description}
              disabled={isSaving}
              class="mt-1 block w-full rounded-md border border-stone-300 px-3 py-2 text-stone-900 placeholder-stone-400 focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:bg-stone-100 disabled:cursor-not-allowed sm:text-sm"
              placeholder={m.project_settings_description_placeholder()}
            ></textarea>
          </div>

          <!-- Target Taxa -->
          <div>
            <span class="block text-sm font-medium text-stone-700" id="target-taxa-label">
              {m.project_settings_target_taxa_label()}
            </span>
            <div
              class="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3"
              role="group"
              aria-labelledby="target-taxa-label"
            >
              {#each TARGET_TAXA_OPTIONS as option (option.value)}
                <label
                  class="flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors
                    {selectedTaxa.includes(option.value)
                    ? 'border-primary-500 bg-primary-50 text-primary-700'
                    : 'border-stone-200 bg-surface-card text-stone-700 hover:bg-stone-50'}
                    {isSaving ? 'cursor-not-allowed opacity-50' : ''}"
                >
                  <input
                    type="checkbox"
                    value={option.value}
                    checked={selectedTaxa.includes(option.value)}
                    disabled={isSaving}
                    onchange={() => toggleTaxon(option.value)}
                    class="h-4 w-4 rounded border-stone-300 text-primary-600 focus:ring-primary-500"
                  />
                  {option.label}
                </label>
              {/each}
            </div>
            <p class="mt-1 text-xs text-stone-500">
              {m.project_settings_target_taxa_hint()}
            </p>
          </div>

          <!-- Visibility -->
          <div>
            <span class="block text-sm font-medium text-stone-700" id="visibility-label">{m.project_settings_visibility_label()}</span>
            <div class="mt-2 space-y-2" role="radiogroup" aria-labelledby="visibility-label">
              <label class="flex items-start">
                <input
                  type="radio"
                  name="visibility"
                  value="private"
                  bind:group={visibility}
                  disabled={isSaving}
                  class="mt-0.5 h-4 w-4 border-stone-300 text-primary-600 focus:ring-primary-500"
                />
                <div class="ml-3">
                  <div class="flex items-center">
                    <svg class="mr-1.5 h-4 w-4 text-stone-500" fill="currentColor" viewBox="0 0 20 20">
                      <path
                        fill-rule="evenodd"
                        d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z"
                        clip-rule="evenodd"
                      />
                    </svg>
                    <span class="text-sm font-medium text-stone-700">{m.project_settings_visibility_private_label()}</span>
                  </div>
                  <p class="text-xs text-stone-500">{m.project_settings_visibility_private_hint()}</p>
                </div>
              </label>

              <label class="flex items-start">
                <input
                  type="radio"
                  name="visibility"
                  value="public"
                  bind:group={visibility}
                  disabled={isSaving}
                  class="mt-0.5 h-4 w-4 border-stone-300 text-primary-600 focus:ring-primary-500"
                />
                <div class="ml-3">
                  <div class="flex items-center">
                    <svg class="mr-1.5 h-4 w-4 text-stone-500" fill="currentColor" viewBox="0 0 20 20">
                      <path
                        fill-rule="evenodd"
                        d="M10 18a8 8 0 100-16 8 8 0 000 16zM4.332 8.027a6.012 6.012 0 011.912-2.706C6.512 5.73 6.974 6 7.5 6A1.5 1.5 0 019 7.5V8a2 2 0 004 0 2 2 0 011.523-1.943A5.977 5.977 0 0116 10c0 .34-.028.675-.083 1H15a2 2 0 00-2 2v2.197A5.973 5.973 0 0110 16v-2a2 2 0 00-2-2 2 2 0 01-2-2 2 2 0 00-1.668-1.973z"
                        clip-rule="evenodd"
                      />
                    </svg>
                    <span class="text-sm font-medium text-stone-700">{m.project_settings_visibility_public_label()}</span>
                  </div>
                  <p class="text-xs text-stone-500">{m.project_settings_visibility_public_hint()}</p>
                </div>
              </label>
            </div>
          </div>
        </div>

        <!-- Form Actions -->
        <div class="flex justify-end space-x-3 border-t border-stone-200 bg-stone-50 px-6 py-4">
          <button
            type="button"
            onclick={handleCancel}
            disabled={isSaving}
            class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {m.project_settings_cancel()}
          </button>
          <button
            type="submit"
            disabled={isSaving}
            class="inline-flex items-center rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
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
              {m.project_settings_saving()}
            {:else}
              {m.project_settings_save()}
            {/if}
          </button>
        </div>
      </div>
    </form>
  {/if}
</div>
