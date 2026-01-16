<script lang="ts">
  /**
   * Project members management page (admin only)
   */

  import { page } from '$app/stores';
  import { projectsApi } from '$lib/api/projects';
  import { authStore } from '$lib/stores/auth.svelte';
  import { ApiError } from '$lib/api/client';
  import type { Project, ProjectMember } from '$lib/types';
  import type { ProjectRole } from '$lib/stores/permissions';
  import { getRoleDescription, getRoleDisplayName } from '$lib/stores/permissions';

  // Get project ID from URL
  const projectId = $derived($page.params.id!);

  // State
  let project = $state<Project | null>(null);
  let members = $state<ProjectMember[]>([]);
  let isLoading = $state(true);
  let error = $state<string | null>(null);

  // Add member form
  let showAddMemberForm = $state(false);
  let newMemberEmail = $state('');
  let newMemberRole = $state<'admin' | 'member' | 'viewer'>('member');
  let isAdding = $state(false);
  let addError = $state<string | null>(null);

  // Remove member state
  let memberToRemove = $state<ProjectMember | null>(null);
  let isRemoving = $state(false);

  // Role change confirmation state
  let roleChangeConfirmation = $state<{
    member: ProjectMember;
    newRole: ProjectRole;
  } | null>(null);
  let isChangingRole = $state(false);

  // Tooltip state
  let showRoleTooltip = $state<string | null>(null);

  // Current user
  const currentUser = $derived(authStore.user);

  // Check if current user is admin
  const isAdmin = $derived(
    (() => {
      if (!currentUser || !project) return false;
      if (project.owner.id === currentUser.id) return true;

      const member = members.find((m) => m.user.id === currentUser.id);
      return member?.role === 'admin';
    })()
  );

  /**
   * Load project and members
   */
  async function loadData() {
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
          error = 'You do not have permission to access this project';
        }
      } else {
        error = 'Failed to load project';
      }
    } finally {
      isLoading = false;
    }
  }

  // Load data on mount
  $effect(() => {
    loadData();
  });

  /**
   * Toggle add member form
   */
  function toggleAddMemberForm() {
    showAddMemberForm = !showAddMemberForm;
    if (!showAddMemberForm) {
      newMemberEmail = '';
      newMemberRole = 'member';
      addError = null;
    }
  }

  /**
   * Add member
   */
  async function handleAddMember(e: Event) {
    e.preventDefault();
    addError = null;

    // Validate email
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(newMemberEmail)) {
      addError = 'Please enter a valid email address';
      return;
    }

    isAdding = true;

    try {
      const newMember = await projectsApi.addMember(projectId, {
        email: newMemberEmail,
        role: newMemberRole,
      });

      members = [...members, newMember];
      toggleAddMemberForm();
    } catch (err) {
      if (err instanceof ApiError) {
        addError = err.detail || err.message;
      } else {
        addError = 'Failed to add member';
      }
    } finally {
      isAdding = false;
    }
  }

  /**
   * Show role change confirmation
   */
  function showRoleChangeConfirmation(member: ProjectMember, newRole: string) {
    roleChangeConfirmation = {
      member,
      newRole: newRole as ProjectRole,
    };
  }

  /**
   * Cancel role change
   */
  function cancelRoleChange() {
    roleChangeConfirmation = null;
  }

  /**
   * Confirm and update member role
   */
  async function confirmRoleChange() {
    if (!roleChangeConfirmation) return;

    isChangingRole = true;
    const { member, newRole } = roleChangeConfirmation;

    try {
      const updated = await projectsApi.updateMemberRole(projectId, member.user.id, {
        role: newRole,
      });

      members = members.map((m) => (m.id === member.id ? updated : m));
      roleChangeConfirmation = null;
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = 'Failed to update member role';
      }
    } finally {
      isChangingRole = false;
    }
  }

  /**
   * Show remove confirmation
   */
  function showRemoveConfirmation(member: ProjectMember) {
    memberToRemove = member;
  }

  /**
   * Cancel remove
   */
  function cancelRemove() {
    memberToRemove = null;
  }

  /**
   * Remove member
   */
  async function confirmRemove() {
    if (!memberToRemove) return;

    isRemoving = true;
    const memberIdToRemove = memberToRemove.id;
    const userIdToRemove = memberToRemove.user.id;

    try {
      await projectsApi.removeMember(projectId, userIdToRemove);
      members = members.filter((m) => m.id !== memberIdToRemove);
      memberToRemove = null;
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = 'Failed to remove member';
      }
    } finally {
      isRemoving = false;
    }
  }

  /**
   * Check if member is owner
   */
  function isMemberOwner(member: ProjectMember): boolean {
    return project?.owner.id === member.user.id;
  }
</script>

<svelte:head>
  <title>Project Members - Echoroo</title>
</svelte:head>

<div class="mx-auto max-w-4xl px-4 py-8 sm:px-6 lg:px-8">
  <!-- Header -->
  <div class="mb-8">
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-3xl font-bold text-gray-900">Project Members</h1>
        {#if project}
          <p class="mt-2 text-sm text-gray-600">
            Manage members and permissions for "{project.name}"
          </p>
        {/if}
      </div>
      <a
        href="/projects/{projectId}"
        class="text-sm font-medium text-blue-600 hover:text-blue-500"
      >
        Back to Project
      </a>
    </div>
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
  {:else if !isAdmin}
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
            You do not have permission to manage project members
          </p>
        </div>
      </div>
    </div>
  {:else}
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

    <!-- Add Member Section -->
    <div class="mb-6 rounded-lg bg-white shadow">
      <div class="p-6">
        {#if !showAddMemberForm}
          <button
            onclick={toggleAddMemberForm}
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
            Add Member
          </button>
        {:else}
          <form onsubmit={handleAddMember} class="space-y-4">
            <div class="flex items-end space-x-4">
              <div class="flex-1">
                <label for="email" class="block text-sm font-medium text-gray-700">
                  Email Address
                </label>
                <input
                  id="email"
                  type="email"
                  required
                  bind:value={newMemberEmail}
                  disabled={isAdding}
                  class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-blue-500 disabled:bg-gray-100"
                  placeholder="member@example.com"
                />
              </div>

              <div class="w-48">
                <label for="role" class="block text-sm font-medium text-gray-700">
                  Role
                  <button
                    type="button"
                    aria-label="Show role descriptions"
                    class="ml-1 inline-flex items-center text-gray-400 hover:text-gray-500"
                    onmouseenter={() => (showRoleTooltip = 'add-role')}
                    onmouseleave={() => (showRoleTooltip = null)}
                  >
                    <svg class="h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
                      <path
                        fill-rule="evenodd"
                        d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z"
                        clip-rule="evenodd"
                      />
                    </svg>
                  </button>
                </label>
                <div class="relative">
                  <select
                    id="role"
                    bind:value={newMemberRole}
                    disabled={isAdding}
                    class="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-blue-500 disabled:bg-gray-100"
                  >
                    <option value="viewer">Viewer</option>
                    <option value="member">Member</option>
                    <option value="admin">Admin</option>
                  </select>
                  {#if showRoleTooltip === 'add-role'}
                    <div
                      class="absolute z-10 mt-2 w-64 rounded-md bg-gray-900 p-3 text-xs text-white shadow-lg"
                    >
                      <div class="space-y-2">
                        <div>
                          <strong>Admin:</strong> {getRoleDescription('admin')}
                        </div>
                        <div>
                          <strong>Member:</strong> {getRoleDescription('member')}
                        </div>
                        <div>
                          <strong>Viewer:</strong> {getRoleDescription('viewer')}
                        </div>
                      </div>
                    </div>
                  {/if}
                </div>
              </div>

              <button
                type="submit"
                disabled={isAdding}
                class="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {isAdding ? 'Adding...' : 'Add'}
              </button>

              <button
                type="button"
                onclick={toggleAddMemberForm}
                disabled={isAdding}
                class="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
            </div>

            {#if addError}
              <p class="text-sm text-red-600">{addError}</p>
            {/if}
          </form>
        {/if}
      </div>
    </div>

    <!-- Members List -->
    <div class="rounded-lg bg-white shadow">
      <div class="p-6">
        <h2 class="mb-4 text-lg font-semibold text-gray-900">
          Members ({members.length})
        </h2>

        <div class="divide-y divide-gray-200">
          {#each members as member (member.id)}
            <div class="flex items-center justify-between py-4">
              <div class="flex items-center space-x-4">
                <!-- Avatar -->
                <div class="flex h-10 w-10 items-center justify-center rounded-full bg-gray-200">
                  <span class="text-sm font-medium text-gray-600">
                    {(member.user?.display_name || member.user?.email || 'U').charAt(0).toUpperCase()}
                  </span>
                </div>

                <!-- User Info -->
                <div>
                  <p class="text-sm font-medium text-gray-900">
                    {member.user.display_name || member.user.email}
                    {#if isMemberOwner(member)}
                      <span class="ml-2 text-xs text-gray-500">(Owner)</span>
                    {/if}
                  </p>
                  <p class="text-xs text-gray-500">{member.user.email}</p>
                  <p class="text-xs text-gray-500">
                    Joined {new Date(member.joined_at).toLocaleDateString()}
                  </p>
                </div>
              </div>

              <!-- Actions -->
              <div class="flex items-center space-x-3">
                {#if !isMemberOwner(member)}
                  <!-- Role Selector with Tooltip -->
                  <div class="relative">
                    <div class="flex items-center space-x-1">
                      <select
                        value={member.role}
                        onchange={(e) => showRoleChangeConfirmation(member, e.currentTarget.value)}
                        class="rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none focus:ring-blue-500"
                      >
                        <option value="viewer">Viewer</option>
                        <option value="member">Member</option>
                        <option value="admin">Admin</option>
                      </select>
                      <button
                        type="button"
                        aria-label="Show role descriptions"
                        class="text-gray-400 hover:text-gray-500"
                        onmouseenter={() => (showRoleTooltip = member.id)}
                        onmouseleave={() => (showRoleTooltip = null)}
                      >
                        <svg class="h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
                          <path
                            fill-rule="evenodd"
                            d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z"
                            clip-rule="evenodd"
                          />
                        </svg>
                      </button>
                    </div>
                    {#if showRoleTooltip === member.id}
                      <div
                        class="absolute right-0 z-10 mt-2 w-64 rounded-md bg-gray-900 p-3 text-xs text-white shadow-lg"
                      >
                        <div class="space-y-2">
                          <div>
                            <strong>Admin:</strong> {getRoleDescription('admin')}
                          </div>
                          <div>
                            <strong>Member:</strong> {getRoleDescription('member')}
                          </div>
                          <div>
                            <strong>Viewer:</strong> {getRoleDescription('viewer')}
                          </div>
                        </div>
                      </div>
                    {/if}
                  </div>

                  <!-- Remove Button -->
                  <button
                    onclick={() => showRemoveConfirmation(member)}
                    class="rounded-md border border-red-300 bg-white px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50"
                  >
                    Remove
                  </button>
                {:else}
                  <span class="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-500">
                    Owner
                  </span>
                {/if}
              </div>
            </div>
          {/each}
        </div>
      </div>
    </div>
  {/if}
</div>

<!-- Role Change Confirmation Dialog -->
{#if roleChangeConfirmation}
  <div class="fixed inset-0 z-50 overflow-y-auto" role="dialog">
    <div class="flex min-h-screen items-end justify-center px-4 pb-20 pt-4 text-center sm:block sm:p-0">
      <!-- Background overlay -->
      <div
        role="button"
        tabindex="0"
        aria-label="Close dialog"
        class="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
        onclick={cancelRoleChange}
        onkeydown={(e) => e.key === 'Escape' && cancelRoleChange()}
      ></div>

      <!-- Modal panel -->
      <div
        class="inline-block transform overflow-hidden rounded-lg bg-white text-left align-bottom shadow-xl transition-all sm:my-8 sm:w-full sm:max-w-lg sm:align-middle"
      >
        <div class="bg-white px-4 pb-4 pt-5 sm:p-6 sm:pb-4">
          <div class="sm:flex sm:items-start">
            <div
              class="mx-auto flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-full bg-blue-100 sm:mx-0 sm:h-10 sm:w-10"
            >
              <svg class="h-6 w-6 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M8 9l4-4 4 4m0 6l-4 4-4-4"
                />
              </svg>
            </div>
            <div class="mt-3 text-center sm:ml-4 sm:mt-0 sm:text-left">
              <h3 class="text-lg font-medium leading-6 text-gray-900">Change Member Role</h3>
              <div class="mt-2">
                <p class="text-sm text-gray-500">
                  Are you sure you want to change {roleChangeConfirmation.member.user.display_name ||
                    roleChangeConfirmation.member.user.email}'s role from <strong
                    >{getRoleDisplayName(roleChangeConfirmation.member.role)}</strong
                  > to <strong>{getRoleDisplayName(roleChangeConfirmation.newRole)}</strong>?
                </p>
                <p class="mt-2 text-sm text-gray-500">
                  {getRoleDescription(roleChangeConfirmation.newRole)}
                </p>
              </div>
            </div>
          </div>
        </div>
        <div class="bg-gray-50 px-4 py-3 sm:flex sm:flex-row-reverse sm:px-6">
          <button
            type="button"
            onclick={confirmRoleChange}
            disabled={isChangingRole}
            class="inline-flex w-full justify-center rounded-md bg-blue-600 px-4 py-2 text-base font-medium text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50 sm:ml-3 sm:w-auto sm:text-sm"
          >
            {isChangingRole ? 'Changing...' : 'Change Role'}
          </button>
          <button
            type="button"
            onclick={cancelRoleChange}
            disabled={isChangingRole}
            class="mt-3 inline-flex w-full justify-center rounded-md border border-gray-300 bg-white px-4 py-2 text-base font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 sm:ml-3 sm:mt-0 sm:w-auto sm:text-sm"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  </div>
{/if}

<!-- Remove Member Confirmation Dialog -->
{#if memberToRemove}
  <div class="fixed inset-0 z-50 overflow-y-auto" role="dialog">
    <div class="flex min-h-screen items-end justify-center px-4 pb-20 pt-4 text-center sm:block sm:p-0">
      <!-- Background overlay -->
      <div
        role="button"
        tabindex="0"
        aria-label="Close dialog"
        class="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity"
        onclick={cancelRemove}
        onkeydown={(e) => e.key === 'Escape' && cancelRemove()}
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
              <h3 class="text-lg font-medium leading-6 text-gray-900">Remove Member</h3>
              <div class="mt-2">
                <p class="text-sm text-gray-500">
                  Are you sure you want to remove {memberToRemove.user.display_name ||
                    memberToRemove.user.email} from this project? They will lose access to all project
                  data.
                </p>
              </div>
            </div>
          </div>
        </div>
        <div class="bg-gray-50 px-4 py-3 sm:flex sm:flex-row-reverse sm:px-6">
          <button
            type="button"
            onclick={confirmRemove}
            disabled={isRemoving}
            class="inline-flex w-full justify-center rounded-md bg-red-600 px-4 py-2 text-base font-medium text-white shadow-sm hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 disabled:opacity-50 sm:ml-3 sm:w-auto sm:text-sm"
          >
            {isRemoving ? 'Removing...' : 'Remove'}
          </button>
          <button
            type="button"
            onclick={cancelRemove}
            disabled={isRemoving}
            class="mt-3 inline-flex w-full justify-center rounded-md border border-gray-300 bg-white px-4 py-2 text-base font-medium text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 sm:ml-3 sm:mt-0 sm:w-auto sm:text-sm"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  </div>
{/if}
