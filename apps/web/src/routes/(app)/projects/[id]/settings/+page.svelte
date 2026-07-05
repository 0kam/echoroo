<script lang="ts">
  /**
   * Project settings page (admin only)
   *
   * Orchestration shell: loads the project + derives permissions, then
   * delegates the edit form and the ownership-transfer flow to dedicated
   * components under `$lib/components/project-settings/`.
   */

  import { page } from '$app/stores';
  import { projectsApi } from '$lib/api/projects';
  import { ApiError } from '$lib/api/client';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import type { Project } from '$lib/types';
  import { authStore } from '$lib/stores/auth.svelte';
  import { buildProjectContext, can } from '$lib/utils/permissions';
  import ProjectSettingsForm from '$lib/components/project-settings/ProjectSettingsForm.svelte';
  import OwnershipTransferDialog from '$lib/components/project-settings/OwnershipTransferDialog.svelte';

  // Get project ID from URL
  const projectId = $derived($page.params.id!);

  // State
  let project = $state<Project | null>(null);
  let isLoading = $state(true);
  let error = $state<string | null>(null);

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

  // Owner-only gate for the transfer section. The project's `owner.id`
  // (public-safe sub-object) is compared against the authenticated user's
  // id. `current_user_role === 'owner'` is a secondary signal, but the id
  // comparison is the canonical owner check used elsewhere (members page).
  const isOwner = $derived(
    project !== null &&
      authStore.user !== null &&
      project.owner.id === authStore.user.id
  );

  /**
   * Load project
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

  function handleSaved(updated: Project) {
    project = updated;
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
  {:else if project}
    <section class="mb-6 rounded-lg border border-stone-200 bg-surface-card p-6 shadow">
      <div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 class="text-lg font-semibold text-stone-900">
            {m.project_settings_tag_management_heading()}
          </h2>
          <p class="mt-1 text-sm text-stone-600">
            {m.project_settings_tag_management_description()}
          </p>
        </div>
        <a
          href={localizeHref(`/projects/${projectId}/settings/tags`)}
          class="inline-flex items-center justify-center rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 shadow-sm hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2"
        >
          {m.project_settings_tag_management_link()}
        </a>
      </div>
    </section>

    <ProjectSettingsForm
      {projectId}
      {project}
      {hasAdminAccess}
      onSaved={handleSaved}
    />

    <OwnershipTransferDialog {projectId} {isOwner} onTransferred={loadProject} />
  {/if}
</div>
