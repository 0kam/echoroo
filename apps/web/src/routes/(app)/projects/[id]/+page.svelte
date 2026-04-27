<script lang="ts">
  /**
   * Project detail page
   */

  import { goto } from '$app/navigation';
  import { createQuery } from '@tanstack/svelte-query';
  import { projectsApi } from '$lib/api/projects';
  import { authStore } from '$lib/stores/auth.svelte';
  import { ApiError } from '$lib/api/client';
  import { localizeHref, getLocale } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import type { Project, ProjectMember } from '$lib/types';
  import ProjectSitesMap from '$lib/components/project/ProjectSitesMap.svelte';
  import RecordingCalendar from '$lib/components/project/RecordingCalendar.svelte';
  import RestrictedToggles from '$lib/components/project/RestrictedToggles.svelte';

  // Props
  let { data } = $props();
  const projectId = $derived(data.projectId);

  // State
  let project = $state<Project | null>(null);
  let members = $state<ProjectMember[]>([]);
  // `membersAvailable` reflects whether the GET /projects/{id}/members
  // call returned successfully. The endpoint is admin-only, so a 403
  // is the expected response for Members / Viewers and must NOT block
  // the project detail render. When false, the membership-gated UI
  // (members sidebar list, "Manage members" link) is hidden but the
  // page itself stays interactive.
  let membersAvailable = $state(false);
  let isLoading = $state(true);
  let error = $state<string | null>(null);
  let showDeleteDialog = $state(false);
  let isDeleting = $state(false);

  // Current user
  const currentUser = $derived(authStore.user);

  // Check if current user is owner. Derives directly from the loaded
  // project so we never rely on the admin-only members list — Members
  // / Viewers must still see the project header.
  const isOwner = $derived(
    !!(currentUser && project && project.owner.id === currentUser.id),
  );

  // Check if current user is admin. We can only confirm admin role from
  // the members list, which Members / Viewers cannot read. When the
  // members fetch was rejected (`membersAvailable === false`) we fall
  // back to Owner-only admin detection — that matches the backend
  // contract: Owner is always Admin, and the only callers who can edit
  // RestrictedToggles via PATCH are Owner / Admin (FR-014).
  const isAdmin = $derived(
    (() => {
      if (!currentUser || !project) return false;
      if (isOwner) return true;
      if (!membersAvailable) return false;

      const member = members.find((m) => m.user.id === currentUser.id);
      return member?.role === 'admin';
    })(),
  );

  // canEdit is the surface used by RestrictedToggles. Only Owners and
  // Admins satisfy the EDIT_PROJECT permission for the
  // restricted-config PATCH endpoint, so we route the same predicate
  // through Boolean() to avoid a `null | boolean` reaching the
  // component prop.
  const canEdit = $derived(Boolean(isAdmin));

  /**
   * Load project and members.
   *
   * The two requests are deliberately decoupled because
   * `GET /projects/{id}/members` is admin-only — a Member or Viewer
   * who can fetch the project itself will get a 403 from
   * `/members`. We therefore await the project first and then attempt
   * the members fetch with a try/catch so the page renders for the
   * non-admin case. Other (non-403) members-fetch failures are
   * swallowed silently — the sidebar simply hides itself, but the
   * project detail still loads.
   */
  async function loadProject() {
    isLoading = true;
    error = null;

    try {
      // 1) Project itself — required. If this fails we surface the
      //    error and abort.
      project = await projectsApi.get(projectId);
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
        if (err.status === 404) {
          error = m.project_detail_error_not_found();
        } else if (err.status === 403) {
          error = m.project_detail_error_forbidden();
        }
      } else {
        error = m.project_detail_error_load();
      }
      isLoading = false;
      return;
    }

    // 2) Members — best-effort. 403 is expected for Members / Viewers
    //    so we tolerate it and leave the sidebar empty.
    try {
      members = await projectsApi.listMembers(projectId);
      membersAvailable = true;
    } catch (err) {
      members = [];
      membersAvailable = false;
      // Only surface non-403 unexpected errors via console — never
      // break the page. 401 / 403 are silent because they are the
      // documented responses for non-admin callers.
      if (err instanceof ApiError && err.status !== 401 && err.status !== 403) {
        console.warn('Failed to load project members', err);
      }
    } finally {
      isLoading = false;
    }
  }

  // Load project on mount
  $effect(() => {
    loadProject();
  });

  // Overview query (TanStack Query)
  const overviewQuery = $derived(
    createQuery({
      queryKey: ['project-overview', projectId],
      queryFn: () => projectsApi.getOverview(projectId),
      enabled: !!projectId,
      retry: false,
    })
  );

  const overview = $derived($overviewQuery.data ?? null);

  // Format total duration as hours + minutes
  const totalHours = $derived(overview ? Math.floor(overview.total_duration / 3600) : 0);
  const totalMinutes = $derived(overview ? Math.floor((overview.total_duration % 3600) / 60) : 0);

  /**
   * Navigate to settings
   */
  function goToSettings() {
    goto(localizeHref(`/projects/${projectId}/settings`));
  }

  /**
   * Navigate to members
   */
  function goToMembers() {
    goto(localizeHref(`/projects/${projectId}/members`));
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
      await goto(localizeHref('/projects'));
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = m.project_detail_error_delete();
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
  {:else if error}
    <!-- Error State -->
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
          <p class="text-sm font-medium text-danger">{error}</p>
        </div>
      </div>
      <div class="mt-4">
        <a href={localizeHref('/projects')} class="text-sm font-medium text-primary-600 hover:text-primary-500">
          {m.project_detail_back_to_projects()}
        </a>
      </div>
    </div>
  {:else if project}
    <!-- Project Header -->
    <div class="mb-8">
      <div class="flex items-start justify-between">
        <div>
          <div class="flex items-center space-x-3">
            <h1 class="text-3xl font-bold text-stone-900">{project.name}</h1>
            <!--
              Three-way visibility badge. The Permissions Redesign
              introduced `restricted` (FR-014). Legacy `private` projects
              still exist in the type union for backwards compatibility,
              but new projects only ship `public` / `restricted`.
            -->
            <span
              class="inline-flex items-center rounded-full px-3 py-1 text-sm font-medium {project.visibility ===
              'public'
                ? 'bg-success-light text-success'
                : project.visibility === 'restricted'
                  ? 'bg-warning-light text-warning'
                  : 'bg-stone-100 text-stone-800 dark:bg-stone-700 dark:text-stone-300'}"
            >
              {#if project.visibility === 'public'}
                <svg class="mr-1.5 h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
                  <path
                    fill-rule="evenodd"
                    d="M10 18a8 8 0 100-16 8 8 0 000 16zM4.332 8.027a6.012 6.012 0 011.912-2.706C6.512 5.73 6.974 6 7.5 6A1.5 1.5 0 019 7.5V8a2 2 0 004 0 2 2 0 011.523-1.943A5.977 5.977 0 0116 10c0 .34-.028.675-.083 1H15a2 2 0 00-2 2v2.197A5.973 5.973 0 0110 16v-2a2 2 0 00-2-2 2 2 0 01-2-2 2 2 0 00-1.668-1.973z"
                    clip-rule="evenodd"
                  />
                </svg>
                {m.project_detail_visibility_public()}
              {:else if project.visibility === 'restricted'}
                <!--
                  Restricted = key icon, signalling per-capability
                  gating. Distinct from the closed-padlock used for
                  legacy private projects so users can tell the two
                  apart at a glance.
                -->
                <svg class="mr-1.5 h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
                  <path
                    fill-rule="evenodd"
                    d="M18 8a6 6 0 01-7.743 5.743L10 14l-1 1-1 1H6v2H2v-4l4.257-4.257A6 6 0 1118 8zm-6-4a1 1 0 100 2 2 2 0 012 2 1 1 0 102 0 4 4 0 00-4-4z"
                    clip-rule="evenodd"
                  />
                </svg>
                {m.project_detail_visibility_restricted()}
              {:else}
                <svg class="mr-1.5 h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
                  <path
                    fill-rule="evenodd"
                    d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z"
                    clip-rule="evenodd"
                  />
                </svg>
                {m.project_detail_visibility_private()}
              {/if}
            </span>
          </div>
          <p class="mt-2 text-sm text-stone-600">
            {m.project_detail_created_by({ date: new Date(project.created_at).toLocaleDateString(getLocale()), owner: project.owner.display_name || project.owner.email })}
          </p>
        </div>

        <!-- Actions -->
        <div class="flex space-x-3">
          {#if isAdmin}
            <button
              onclick={goToSettings}
              class="inline-flex items-center rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50"
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
              {m.project_detail_settings_button()}
            </button>
          {/if}

          {#if isOwner}
            <button
              onclick={showDeleteConfirmation}
              class="inline-flex items-center rounded-md border border-danger/30 bg-surface-card px-4 py-2 text-sm font-medium text-danger hover:bg-danger-light"
            >
              <svg class="mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                />
              </svg>
              {m.project_detail_delete_button()}
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
        <div class="mb-6 rounded-lg bg-surface-card p-6 shadow">
          <h2 class="mb-4 text-lg font-semibold text-stone-900">{m.project_detail_description_heading()}</h2>
          {#if project.description}
            <p class="whitespace-pre-wrap text-sm text-stone-700">{project.description}</p>
          {:else}
            <p class="text-sm italic text-stone-400">{m.project_detail_no_description()}</p>
          {/if}
        </div>

        <!-- Target Taxa -->
        {#if project.target_taxa}
          <div class="mb-6 rounded-lg bg-surface-card p-6 shadow">
            <h2 class="mb-4 text-lg font-semibold text-stone-900">{m.project_detail_target_taxa_heading()}</h2>
            <p class="text-sm text-stone-700">{project.target_taxa}</p>
          </div>
        {/if}

        <!-- Quick Navigation -->
        <div class="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <a
            href={localizeHref(`/projects/${projectId}/data`)}
            class="flex items-start rounded-lg bg-surface-card p-4 shadow transition hover:shadow-md"
          >
            <svg class="mr-3 mt-0.5 h-5 w-5 flex-shrink-0 text-primary-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
            </svg>
            <div>
              <h3 class="text-sm font-semibold text-stone-900">{m.project_detail_nav_sites_data_title()}</h3>
              <p class="mt-1 text-xs text-stone-500">{m.project_detail_nav_sites_data_desc()}</p>
            </div>
          </a>
          <a
            href={localizeHref(`/projects/${projectId}/detections`)}
            class="flex items-start rounded-lg bg-surface-card p-4 shadow transition hover:shadow-md"
          >
            <svg class="mr-3 mt-0.5 h-5 w-5 flex-shrink-0 text-primary-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
            </svg>
            <div>
              <h3 class="text-sm font-semibold text-stone-900">{m.project_detail_nav_detections_title()}</h3>
              <p class="mt-1 text-xs text-stone-500">{m.project_detail_nav_detections_desc()}</p>
            </div>
          </a>
          <a
            href={localizeHref(`/projects/${projectId}/reports`)}
            class="flex items-start rounded-lg bg-surface-card p-4 shadow transition hover:shadow-md"
          >
            <svg class="mr-3 mt-0.5 h-5 w-5 flex-shrink-0 text-primary-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <div>
              <h3 class="text-sm font-semibold text-stone-900">{m.project_detail_nav_reports_title()}</h3>
              <p class="mt-1 text-xs text-stone-500">{m.project_detail_nav_reports_desc()}</p>
            </div>
          </a>
          <a
            href={localizeHref(`/projects/${projectId}/settings`)}
            class="flex items-start rounded-lg bg-surface-card p-4 shadow transition hover:shadow-md"
          >
            <svg class="mr-3 mt-0.5 h-5 w-5 flex-shrink-0 text-primary-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            <div>
              <h3 class="text-sm font-semibold text-stone-900">{m.project_detail_nav_settings_title()}</h3>
              <p class="mt-1 text-xs text-stone-500">{m.project_detail_nav_settings_desc()}</p>
            </div>
          </a>
        </div>

        <!-- Overview section: shows data if recordings exist, otherwise placeholder -->
        {#if $overviewQuery.isLoading}
          <!-- Loading skeleton -->
          <div class="rounded-lg bg-surface-card p-6 shadow">
            <div class="mb-4 h-5 w-32 animate-pulse rounded bg-stone-200"></div>
            <div class="h-[300px] animate-pulse rounded-lg bg-stone-100"></div>
          </div>
        {:else if overview && overview.total_recordings > 0}
          <!-- Summary stats -->
          <div class="mb-4 flex flex-wrap gap-4">
            <div class="rounded-lg bg-surface-card px-4 py-3 shadow">
              <p class="text-xs text-stone-500">{m.project_overview_total_recordings({ count: overview.total_recordings })}</p>
            </div>
            <div class="rounded-lg bg-surface-card px-4 py-3 shadow">
              <p class="text-xs text-stone-500">{m.project_overview_total_sites({ count: overview.total_sites })}</p>
            </div>
            {#if overview.total_duration > 0}
              <div class="rounded-lg bg-surface-card px-4 py-3 shadow">
                <p class="text-xs text-stone-500">{m.project_overview_total_duration({ hours: totalHours, minutes: totalMinutes })}</p>
              </div>
            {/if}
          </div>

          <!-- Sites Map -->
          {#if overview.sites.length > 0}
            <div class="mb-6 rounded-lg bg-surface-card p-6 shadow">
              <h2 class="mb-4 text-lg font-semibold text-stone-900">{m.project_overview_sites_map_title()}</h2>
              <ProjectSitesMap sites={overview.sites} {projectId} />
            </div>
          {/if}

          <!-- Recording Calendar -->
          {#if overview.recording_calendar.length > 0}
            <div class="rounded-lg bg-surface-card p-6 shadow">
              <h2 class="mb-4 text-lg font-semibold text-stone-900">{m.project_overview_recording_calendar_title()}</h2>
              <RecordingCalendar calendar={overview.recording_calendar} />
            </div>
          {/if}
        {:else}
          <!-- No recordings placeholder -->
          <div class="rounded-lg border-2 border-dashed border-stone-300 p-12 text-center">
            <svg
              class="mx-auto h-12 w-12 text-stone-400"
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
            <h3 class="mt-2 text-sm font-medium text-stone-900">{m.project_overview_no_data()}</h3>
            <p class="mt-1 text-sm text-stone-500">{m.project_overview_no_data_desc()}</p>
          </div>
        {/if}

        <!--
          Phase 8 / T402 — Restricted-mode capability toggles (FR-014).
          The component itself short-circuits to a "public-only" notice
          for visibility=public projects, so it is safe to mount
          unconditionally. We keep it in the main column (below the
          overview) so Owners / Admins find it on the same page that
          already surfaces project metadata, instead of buried in a
          separate Settings sub-page.
        -->
        <div class="mt-6">
          <RestrictedToggles {project} {canEdit} />
        </div>
      </div>

      <!-- Sidebar -->
      <div class="space-y-6">
        <!--
          Project Members sidebar — only rendered when the
          admin-only members fetch succeeded. Members / Viewers (whose
          /members request returns 403) simply don't see this card,
          which matches the backend's information-hiding posture.
        -->
        {#if membersAvailable}
        <div class="rounded-lg bg-surface-card p-6 shadow">
          <div class="mb-4 flex items-center justify-between">
            <h2 class="text-lg font-semibold text-stone-900">{m.project_detail_members_heading()}</h2>
            {#if isAdmin}
              <button
                onclick={goToMembers}
                class="text-sm font-medium text-primary-600 hover:text-primary-500"
              >
                {m.project_detail_members_manage()}
              </button>
            {/if}
          </div>

          <div class="space-y-3">
            {#each members.slice(0, 5) as member (member.id)}
              <div class="flex items-center justify-between">
                <div class="flex items-center space-x-3">
                  <div class="flex h-8 w-8 items-center justify-center rounded-full bg-stone-200">
                    <span class="text-xs font-medium text-stone-600">
                      {(member.user?.display_name || member.user?.email || 'U').charAt(0).toUpperCase()}
                    </span>
                  </div>
                  <div class="min-w-0 flex-1">
                    <p class="truncate text-sm font-medium text-stone-900">
                      {member.user.display_name || member.user.email}
                    </p>
                    <p class="truncate text-xs text-stone-500">{member.role}</p>
                  </div>
                </div>
              </div>
            {/each}

            {#if members.length > 5}
              <button
                onclick={goToMembers}
                class="w-full pt-2 text-center text-sm text-stone-600 hover:text-stone-900"
              >
                {m.project_detail_members_view_all({ count: members.length })}
              </button>
            {/if}
          </div>
        </div>
        {/if}
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
        class="fixed inset-0 bg-stone-500 bg-opacity-75 transition-opacity"
        onclick={cancelDelete}
        onkeydown={(e) => e.key === 'Escape' && cancelDelete()}
      ></div>

      <!-- Modal panel -->
      <div
        class="inline-block transform overflow-hidden rounded-lg bg-surface-card text-left align-bottom shadow-xl transition-all sm:my-8 sm:w-full sm:max-w-lg sm:align-middle"
      >
        <div class="bg-surface-card px-4 pb-4 pt-5 sm:p-6 sm:pb-4">
          <div class="sm:flex sm:items-start">
            <div
              class="mx-auto flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-full bg-danger-light sm:mx-0 sm:h-10 sm:w-10"
            >
              <svg class="h-6 w-6 text-danger" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
                />
              </svg>
            </div>
            <div class="mt-3 text-center sm:ml-4 sm:mt-0 sm:text-left">
              <h3 class="text-lg font-medium leading-6 text-stone-900" id="modal-title">
                {m.project_detail_delete_title()}
              </h3>
              <div class="mt-2">
                <p class="text-sm text-stone-500">
                  {m.project_detail_delete_body({ name: project?.name ?? '' })}
                </p>
              </div>
            </div>
          </div>
        </div>
        <div class="bg-stone-50 px-4 py-3 sm:flex sm:flex-row-reverse sm:px-6">
          <button
            type="button"
            onclick={deleteProject}
            disabled={isDeleting}
            class="inline-flex w-full justify-center rounded-md bg-danger px-4 py-2 text-base font-medium text-white shadow-sm hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-danger/50 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 sm:ml-3 sm:w-auto sm:text-sm"
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
              {m.project_detail_deleting()}
            {:else}
              {m.project_detail_delete_button()}
            {/if}
          </button>
          <button
            type="button"
            onclick={cancelDelete}
            disabled={isDeleting}
            class="mt-3 inline-flex w-full justify-center rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-base font-medium text-stone-700 shadow-sm hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 sm:ml-3 sm:mt-0 sm:w-auto sm:text-sm"
          >
            {m.common_cancel()}
          </button>
        </div>
      </div>
    </div>
  </div>
{/if}
