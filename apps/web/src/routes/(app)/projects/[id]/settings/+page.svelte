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
  import type { Project, ProjectMember } from '$lib/types';
  import { authStore } from '$lib/stores/auth.svelte';
  import { buildProjectContext, can } from '$lib/utils/permissions';

  // Get project ID from URL
  const projectId = $derived($page.params.id!);

  const TARGET_TAXA_OPTIONS = [
    { value: 'Birds', label: m.project_target_taxa_option_birds },
    { value: 'Anurans', label: m.project_target_taxa_option_anurans },
    { value: 'Insects', label: m.project_target_taxa_option_insects },
    { value: 'Bats', label: m.project_target_taxa_option_bats },
    { value: 'Land mammals', label: m.project_target_taxa_option_land_mammals },
    { value: 'Fishes', label: m.project_target_taxa_option_fishes },
    { value: 'Cetaceans', label: m.project_target_taxa_option_cetaceans },
  ];

  // State
  let project = $state<Project | null>(null);
  let name = $state('');
  let description = $state('');
  let selectedTaxa = $state<string[]>([]);
  const targetTaxa = $derived(selectedTaxa.join(', '));
  // Visibility radio supports public / restricted (Phase 8 / FR-014). The
  // selected value is round-tripped via projectData.visibility on save.
  let visibility = $state<'public' | 'restricted'>('restricted');

  let isLoading = $state(true);
  let isSaving = $state(false);
  let error = $state<string | null>(null);
  let successMessage = $state<string | null>(null);

  // --- Transfer ownership (preview feedback #2 / SU-bootstrap redesign) ---
  // The transfer section is owner-only. Eligible targets are active project
  // Admins (the backend rejects any other target with
  // `ERR_INVALID_TRANSFER_TARGET`). Members are loaded lazily once we know
  // the caller is the owner.
  let members = $state<ProjectMember[]>([]);
  let membersLoading = $state(false);
  let membersError = $state<string | null>(null);
  // "Loaded" latch for the lazy auto-load effect. The OWNER is not stored as a
  // `project_members` row, so a freshly-created project legitimately returns an
  // empty list — we cannot infer "done" from `members.length`, or the effect
  // would re-fire forever. This latch is set once `loadMembers()` settles
  // (even on an empty result) and gates only the auto-load effect, never the
  // direct error-recovery refetches in `confirmTransfer`.
  let membersLoaded = $state(false);
  let selectedNewOwnerId = $state('');
  // Confirmation dialog target (the chosen Admin member) — drives the
  // danger-styled confirm modal. `null` = dialog closed.
  let transferTarget = $state<ProjectMember | null>(null);
  let isTransferring = $state(false);
  // Error surfaced inside the transfer section / dialog (never console-only).
  let transferError = $state<string | null>(null);
  let transferSuccess = $state<string | null>(null);

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

  // Eligible transfer targets: active project Admins. The backend only
  // permits transferring ownership to an active Admin, so we filter the
  // member list to `role === 'admin'` and never offer Members/Viewers or
  // the owner themselves.
  const eligibleAdmins = $derived(members.filter((mem) => mem.role === 'admin'));

  // Currently-selected target member resolved from the picker value.
  const selectedNewOwner = $derived<ProjectMember | null>(
    selectedNewOwnerId === ''
      ? null
      : (eligibleAdmins.find((mem) => mem.user.id === selectedNewOwnerId) ?? null)
  );

  /**
   * Display label for a member in the picker: `display_name (email)`,
   * falling back to just the email when no display name is set.
   */
  function memberLabel(mem: ProjectMember): string {
    const name = mem.user.display_name?.trim();
    return name ? `${name} (${mem.user.email})` : mem.user.email;
  }

  /**
   * Load the project's members for the transfer picker. Called lazily once
   * the caller is confirmed to be the owner (the listing endpoint is
   * admin-gated, so a non-owner Admin could still load it, but we only ever
   * surface the picker to the owner).
   */
  async function loadMembers() {
    membersLoading = true;
    membersError = null;
    try {
      members = await projectsApi.listMembers(projectId);
    } catch (err) {
      if (err instanceof ApiError) {
        membersError = err.detail || err.message;
      } else {
        membersError = m.project_transfer_members_load_error();
      }
    } finally {
      membersLoading = false;
      // Latch as loaded even when the result is an empty array (owner-only
      // project), so the auto-load effect below settles instead of looping.
      membersLoaded = true;
    }
  }

  // Load members once we know the caller is the owner. `$effect` re-runs when
  // `isOwner` flips true after the project finishes loading. Gated on the
  // `membersLoaded` latch (not `members.length`) so an empty member list — the
  // expected case for a freshly-created project whose only role is the owner —
  // is a terminal state, not an infinite re-fetch.
  $effect(() => {
    if (isOwner && !membersLoaded && !membersLoading && membersError === null) {
      loadMembers();
    }
  });

  /**
   * Open the confirmation dialog for the currently-selected Admin target.
   */
  function openTransferConfirm() {
    transferError = null;
    if (selectedNewOwner) {
      transferTarget = selectedNewOwner;
    }
  }

  /**
   * Close / cancel the transfer confirmation dialog.
   */
  function cancelTransfer() {
    if (isTransferring) return;
    transferTarget = null;
  }

  /**
   * Confirm and perform the ownership transfer.
   *
   * Generates a fresh UUID v4 idempotency key per attempt so a double-click
   * inside the dialog cannot transfer twice. On success the project +
   * members are reloaded; once the caller is demoted to Admin, `isOwner`
   * flips false and the whole transfer section disappears.
   */
  async function confirmTransfer() {
    if (!transferTarget) return;

    isTransferring = true;
    transferError = null;
    const target = transferTarget;

    try {
      const idempotencyKey = crypto.randomUUID();
      await projectsApi.transferOwnership(projectId, target.user.id, idempotencyKey);

      // Reflect the new ownership: reload the project (so `owner.id` +
      // `current_user_role` update and `isOwner` flips false) and the
      // member list. The transfer UI disappears since the caller is now an
      // Admin, not the Owner.
      transferTarget = null;
      selectedNewOwnerId = '';
      transferSuccess = m.project_transfer_success({ name: memberLabel(target) });
      await Promise.all([loadProject(), loadMembers()]);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 400 || err.code === 'ERR_INVALID_TRANSFER_TARGET') {
          // Target is no longer an active Admin — refresh the picker so the
          // stale option drops out, and ask the owner to pick another.
          transferError = m.project_transfer_error_invalid_target();
          await loadMembers();
        } else if (err.status === 409) {
          // Idempotency / concurrent-transfer conflict. The transfer most
          // likely already applied (or another tab raced it); reload to
          // reflect the authoritative state and let the owner retry if not.
          transferError = m.project_transfer_error_conflict();
          await Promise.all([loadProject(), loadMembers()]);
        } else {
          transferError = err.detail || err.message || m.project_transfer_error_generic();
        }
      } else {
        transferError = m.project_transfer_error_generic();
      }
    } finally {
      isTransferring = false;
    }
  }

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

  function toggleTaxon(value: string) {
    selectedTaxa = selectedTaxa.includes(value)
      ? selectedTaxa.filter((taxon) => taxon !== value)
      : [...selectedTaxa, value];
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

          <!-- Target Taxa -->
          <div>
            <span id="target-taxa-label" class="block text-sm font-medium text-stone-700">
              {m.project_settings_target_taxa_label()}
            </span>
            <div
              role="group"
              class="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3"
              aria-labelledby="target-taxa-label"
            >
              {#each TARGET_TAXA_OPTIONS as option (option.value)}
                {@const selected = selectedTaxa.includes(option.value)}
                <label
                  class={`flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors ${
                    isSaving ? 'cursor-not-allowed opacity-50' : ''
                  } ${
                    selected
                      ? 'border-primary-500 bg-primary-50 text-primary-700'
                      : 'border-stone-200 bg-surface-card text-stone-700 hover:bg-stone-50'
                  }`}
                >
                  <input
                    type="checkbox"
                    value={option.value}
                    checked={selectedTaxa.includes(option.value)}
                    disabled={isSaving}
                    onchange={() => toggleTaxon(option.value)}
                    class="h-4 w-4 rounded border-stone-300 text-primary-600 focus:ring-primary-500"
                  />
                  {option.label()}
                </label>
              {/each}
            </div>
            <p class="mt-1 text-xs text-stone-500">{m.project_settings_target_taxa_hint()}</p>
          </div>

          <!-- Visibility -->
          <div>
            <span class="block text-sm font-medium text-stone-700" id="visibility-label">{m.project_settings_visibility_label()}</span>
            <!-- Visibility radio group: public or restricted. -->
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

    <!-- Transfer ownership (preview feedback #2 / SU-bootstrap redesign).
         Owner-only, danger-styled. Eligible targets are active project
         Admins; the section disappears once the caller is no longer the
         owner (after a successful transfer they become an Admin). -->
    {#if isOwner}
      <div class="mt-8 rounded-lg border border-danger/30 bg-surface-card shadow">
        <div class="space-y-4 p-6">
          <div>
            <h2 class="text-lg font-semibold text-danger">
              {m.project_transfer_heading()}
            </h2>
            <p class="mt-1 text-sm text-stone-600">
              {m.project_transfer_description()}
            </p>
          </div>

          <!-- Transfer success -->
          {#if transferSuccess}
            <div class="rounded-md bg-success-light p-3" role="status">
              <p class="text-sm font-medium text-success">{transferSuccess}</p>
            </div>
          {/if}

          <!-- Transfer error (section-level; dialog also surfaces it) -->
          {#if transferError}
            <div class="rounded-md bg-danger-light p-3" role="alert">
              <p class="text-sm font-medium text-danger">{transferError}</p>
            </div>
          {/if}

          {#if membersLoading}
            <p class="text-sm text-stone-500">{m.project_transfer_members_loading()}</p>
          {:else if membersError}
            <p class="text-sm text-danger" role="alert">{membersError}</p>
          {:else if eligibleAdmins.length === 0}
            <!-- No eligible Admins: hint to invite one first. -->
            <div class="rounded-md bg-warning-light p-3">
              <p class="text-sm text-stone-700">{m.project_transfer_no_admins_hint()}</p>
              <a
                href={localizeHref(`/projects/${projectId}/collaborators`)}
                class="mt-1 inline-block text-sm font-medium text-primary-600 hover:text-primary-500"
              >
                {m.project_transfer_go_to_collaborators()}
              </a>
            </div>
          {:else}
            <div class="flex flex-col gap-3 sm:flex-row sm:items-end">
              <div class="flex-1">
                <label for="transfer-target" class="block text-sm font-medium text-stone-700">
                  {m.project_transfer_select_label()}
                </label>
                <select
                  id="transfer-target"
                  bind:value={selectedNewOwnerId}
                  disabled={isTransferring}
                  data-testid="transfer-owner-select"
                  class="mt-1 block w-full rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-sm text-stone-900 focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:bg-stone-100 disabled:cursor-not-allowed"
                >
                  <option value="" disabled>{m.project_transfer_select_placeholder()}</option>
                  {#each eligibleAdmins as admin (admin.user.id)}
                    <option value={admin.user.id}>{memberLabel(admin)}</option>
                  {/each}
                </select>
              </div>
              <button
                type="button"
                onclick={openTransferConfirm}
                disabled={isTransferring || selectedNewOwnerId === ''}
                data-testid="transfer-owner-button"
                class="inline-flex items-center justify-center rounded-md bg-danger px-4 py-2 text-sm font-medium text-white shadow-sm hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-danger/50 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {m.project_transfer_button()}
              </button>
            </div>
          {/if}
        </div>
      </div>
    {/if}
  {/if}
</div>

<!-- Transfer ownership confirmation dialog (danger-styled). -->
{#if transferTarget}
  <div class="fixed inset-0 z-50 overflow-y-auto" role="dialog" aria-modal="true">
    <div class="flex min-h-screen items-end justify-center px-4 pb-20 pt-4 text-center sm:block sm:p-0">
      <!-- Background overlay -->
      <div
        role="button"
        tabindex="0"
        aria-label={m.project_transfer_cancel()}
        class="fixed inset-0 bg-stone-500 bg-opacity-75 transition-opacity"
        onclick={cancelTransfer}
        onkeydown={(e) => e.key === 'Escape' && cancelTransfer()}
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
              <h3 class="text-lg font-medium leading-6 text-stone-900">
                {m.project_transfer_confirm_title()}
              </h3>
              <div class="mt-2">
                <p class="text-sm text-stone-500">
                  {m.project_transfer_confirm_body({ name: memberLabel(transferTarget) })}
                </p>
              </div>
              {#if transferError}
                <p class="mt-3 text-sm text-danger" role="alert">{transferError}</p>
              {/if}
            </div>
          </div>
        </div>
        <div class="bg-stone-50 px-4 py-3 sm:flex sm:flex-row-reverse sm:px-6">
          <button
            type="button"
            onclick={confirmTransfer}
            disabled={isTransferring}
            data-testid="transfer-owner-confirm"
            class="inline-flex w-full justify-center rounded-md bg-danger px-4 py-2 text-base font-medium text-white shadow-sm hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-danger/50 focus:ring-offset-2 disabled:opacity-50 sm:ml-3 sm:w-auto sm:text-sm"
          >
            {isTransferring
              ? m.project_transfer_confirming()
              : m.project_transfer_confirm_submit()}
          </button>
          <button
            type="button"
            onclick={cancelTransfer}
            disabled={isTransferring}
            class="mt-3 inline-flex w-full justify-center rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-base font-medium text-stone-700 shadow-sm hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:opacity-50 sm:ml-3 sm:mt-0 sm:w-auto sm:text-sm"
          >
            {m.project_transfer_cancel()}
          </button>
        </div>
      </div>
    </div>
  </div>
{/if}
