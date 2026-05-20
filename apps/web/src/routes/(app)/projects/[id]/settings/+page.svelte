<script lang="ts">
  /**
   * Project settings page (admin only)
   */

  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { projectsApi } from '$lib/api/projects';
  import { ApiError } from '$lib/api/client';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import type { Project } from '$lib/types';
  import { authStore } from '$lib/stores/auth.svelte';
  import { buildProjectContext, can } from '$lib/utils/permissions';

  // Get project ID from URL
  const projectId = $derived($page.params.id!);

  // State
  let project = $state<Project | null>(null);
  let name = $state('');
  let description = $state('');
  // Visibility radio supports public / restricted / private (Phase 8 /
  // FR-014). All three options are surfaced in the form below; the
  // selected value is round-tripped via projectData.visibility on save.
  let visibility = $state<'private' | 'public' | 'restricted'>('private');

  let isLoading = $state(true);
  let isSaving = $state(false);
  let error = $state<string | null>(null);
  let successMessage = $state<string | null>(null);

  // Phase 2B.3 (spec/007): permission gating goes through `can()` so
  // the page no longer encodes the role -> permission mapping
  // locally. `edit_project` is the canonical permission for the
  // "edit settings" UI (owner + admin in the canonical matrix).
  // The context is built directly from `authStore` + the loaded
  // project; this page does NOT use TanStack Query for the project
  // load, so we bypass `usePermissionContext` (which wraps a query
  // store) and call `buildProjectContext` against the plain `project`
  // state below.
  const permissionContext = $derived(
    buildProjectContext({
      authStore: {
        isAuthenticated: authStore.isAuthenticated,
        user: authStore.user,
      },
      project: project ?? undefined,
      projectQueryState: { isLoading, isError: error !== null },
      pendingInvitationToken: null,
    })
  );
  const hasAdminAccess = $derived(can('edit_project', permissionContext));

  /**
   * Load project and members
   */
  async function loadProject() {
    isLoading = true;
    error = null;

    try {
      // Phase 1 (spec/007): only fetch the project; `current_user_role`
      // is returned as part of the project payload, so the separate
      // `listMembers` call previously used solely for role derivation
      // is no longer needed on this page.
      const projectData = await projectsApi.get(projectId);

      project = projectData;

      // Initialize form fields
      name = projectData.name;
      description = projectData.description || '';
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
    <div class="rounded-md bg-danger-light p-4" role="alert">
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
          <p class="text-sm font-medium text-danger">
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
      <div class="mb-6 rounded-md bg-success-light p-4" role="alert">
        <div class="flex">
          <div class="flex-shrink-0">
            <svg
              class="h-5 w-5 text-success"
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
            <p class="text-sm font-medium text-success">{successMessage}</p>
          </div>
        </div>
      </div>
    {/if}

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

    <!-- Settings Form -->
    <form onsubmit={handleSave} class="space-y-6">
      <div class="rounded-lg bg-surface-card shadow">
        <div class="space-y-6 p-6">
          <!-- Project Name -->
          <div>
            <label for="name" class="block text-sm font-medium text-stone-700">
              {m.project_settings_name_label()} <span class="text-danger">*</span>
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

          <!-- Visibility -->
          <div>
            <span class="block text-sm font-medium text-stone-700" id="visibility-label">{m.project_settings_visibility_label()}</span>
            <!--
              Three-way radio group. `restricted` is the current
              recommended visibility introduced by the Permissions
              Redesign (FR-014). `private` is shown only as a legacy
              option so existing private projects can be reopened
              without the radio appearing unselected.
            -->
            <div class="mt-2 space-y-2" role="radiogroup" aria-labelledby="visibility-label">
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

              <label class="flex items-start">
                <input
                  type="radio"
                  name="visibility"
                  value="restricted"
                  bind:group={visibility}
                  disabled={isSaving}
                  class="mt-0.5 h-4 w-4 border-stone-300 text-primary-600 focus:ring-primary-500"
                />
                <div class="ml-3">
                  <div class="flex items-center">
                    <svg class="mr-1.5 h-4 w-4 text-stone-500" fill="currentColor" viewBox="0 0 20 20">
                      <path
                        fill-rule="evenodd"
                        d="M18 8a6 6 0 01-7.743 5.743L10 14l-1 1-1 1H6v2H2v-4l4.257-4.257A6 6 0 1118 8zm-6-4a1 1 0 100 2 2 2 0 012 2 1 1 0 102 0 4 4 0 00-4-4z"
                        clip-rule="evenodd"
                      />
                    </svg>
                    <span class="text-sm font-medium text-stone-700">{m.project_settings_visibility_restricted_label()}</span>
                  </div>
                  <p class="text-xs text-stone-500">{m.project_settings_visibility_restricted_hint()}</p>
                </div>
              </label>

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
            class="inline-flex items-center rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
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
