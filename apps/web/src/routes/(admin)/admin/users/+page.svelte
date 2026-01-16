<script lang="ts">
  /**
   * Admin - User Management Page
   */

  import { adminApi } from '$lib/api/admin';
  import { ApiError } from '$lib/api/client';
  import type { User } from '$lib/types';

  // State
  let users = $state<User[]>([]);
  let total = $state(0);
  let page = $state(1);
  let limit = $state(20);
  let search = $state('');
  let isActiveFilter = $state<boolean | undefined>(undefined);
  let isLoading = $state(true);
  let error = $state<string | null>(null);
  let successMessage = $state<string | null>(null);

  // Debounced search
  let searchTimeout: ReturnType<typeof setTimeout> | null = null;

  /**
   * Load users
   */
  async function loadUsers() {
    isLoading = true;
    error = null;

    try {
      const response = await adminApi.listUsers({
        page,
        limit,
        search: search.trim() || undefined,
        is_active: isActiveFilter,
      });
      users = response.items;
      total = response.total;
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = 'Failed to load users';
      }
    } finally {
      isLoading = false;
    }
  }

  // Load users on mount and when filters change
  $effect(() => {
    loadUsers();
  });

  /**
   * Handle search input
   */
  function handleSearch(event: Event) {
    const target = event.target as HTMLInputElement;
    search = target.value;

    // Reset to first page on search
    page = 1;

    // Debounce search
    if (searchTimeout) {
      clearTimeout(searchTimeout);
    }
    searchTimeout = setTimeout(() => {
      loadUsers();
    }, 300);
  }

  /**
   * Handle filter change
   */
  function handleFilterChange(event: Event) {
    const target = event.target as HTMLSelectElement;
    const value = target.value;

    if (value === 'all') {
      isActiveFilter = undefined;
    } else if (value === 'active') {
      isActiveFilter = true;
    } else if (value === 'inactive') {
      isActiveFilter = false;
    }

    page = 1;
  }

  /**
   * Toggle user active status
   */
  async function toggleUserActive(user: User) {
    try {
      await adminApi.updateUser(user.id, {
        is_active: !user.is_active,
      });

      // Update local state
      user.is_active = !user.is_active;
      successMessage = `User ${user.is_active ? 'activated' : 'deactivated'} successfully`;

      // Clear success message after 3 seconds
      setTimeout(() => {
        successMessage = null;
      }, 3000);
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = 'Failed to update user';
      }
    }
  }

  /**
   * Toggle user superuser status
   */
  async function toggleUserSuperuser(user: User) {
    try {
      await adminApi.updateUser(user.id, {
        is_superuser: !user.is_superuser,
      });

      // Update local state
      user.is_superuser = !user.is_superuser;
      successMessage = `User ${user.is_superuser ? 'promoted to' : 'demoted from'} superuser`;

      // Clear success message after 3 seconds
      setTimeout(() => {
        successMessage = null;
      }, 3000);
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = 'Failed to update user';
      }
    }
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

  /**
   * Format date
   */
  function formatDate(dateString: string): string {
    return new Date(dateString).toLocaleString();
  }
</script>

<svelte:head>
  <title>User Management - Admin - Echoroo</title>
</svelte:head>

<div class="px-8 py-6">
  <!-- Header -->
  <div class="mb-6">
    <h1 class="text-3xl font-bold text-gray-900">User Management</h1>
    <p class="mt-2 text-sm text-gray-600">Manage user accounts and permissions</p>
  </div>

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

  <!-- Filters -->
  <div class="mb-6 flex flex-col gap-4 sm:flex-row">
    <!-- Search -->
    <div class="flex-1">
      <label for="search" class="sr-only">Search users</label>
      <div class="relative">
        <div class="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
          <svg class="h-5 w-5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
            />
          </svg>
        </div>
        <input
          type="search"
          id="search"
          value={search}
          oninput={handleSearch}
          placeholder="Search by email or name..."
          class="block w-full rounded-lg border border-gray-300 bg-white py-2 pl-10 pr-3 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
      </div>
    </div>

    <!-- Status Filter -->
    <div class="sm:w-48">
      <label for="status-filter" class="sr-only">Filter by status</label>
      <select
        id="status-filter"
        onchange={handleFilterChange}
        class="block w-full rounded-lg border border-gray-300 bg-white py-2 pl-3 pr-10 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
      >
        <option value="all">All Users</option>
        <option value="active">Active Only</option>
        <option value="inactive">Inactive Only</option>
      </select>
    </div>
  </div>

  <!-- Users Table -->
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
  {:else if users.length === 0}
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
          d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"
        />
      </svg>
      <h3 class="mt-2 text-sm font-medium text-gray-900">No users found</h3>
      <p class="mt-1 text-sm text-gray-500">Try adjusting your search or filters.</p>
    </div>
  {:else}
    <div class="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
      <div class="overflow-x-auto">
        <table class="min-w-full divide-y divide-gray-200">
          <thead class="bg-gray-50">
            <tr>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500"
              >
                Email
              </th>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500"
              >
                Display Name
              </th>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500"
              >
                Status
              </th>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500"
              >
                Role
              </th>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500"
              >
                Created
              </th>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500"
              >
                Actions
              </th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-200 bg-white">
            {#each users as user (user.id)}
              <tr class="hover:bg-gray-50">
                <!-- Email -->
                <td class="whitespace-nowrap px-6 py-4">
                  <div class="flex items-center">
                    <div>
                      <div class="text-sm font-medium text-gray-900">{user.email}</div>
                      {#if user.organization}
                        <div class="text-xs text-gray-500">{user.organization}</div>
                      {/if}
                    </div>
                  </div>
                </td>

                <!-- Display Name -->
                <td class="whitespace-nowrap px-6 py-4 text-sm text-gray-900">
                  {user.display_name || '-'}
                </td>

                <!-- Status -->
                <td class="whitespace-nowrap px-6 py-4">
                  <div class="flex flex-col gap-1">
                    <span
                      class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium {user.is_active
                        ? 'bg-green-100 text-green-800'
                        : 'bg-red-100 text-red-800'}"
                    >
                      {user.is_active ? 'Active' : 'Inactive'}
                    </span>
                    {#if user.is_verified}
                      <span
                        class="inline-flex items-center rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-medium text-blue-800"
                      >
                        Verified
                      </span>
                    {/if}
                  </div>
                </td>

                <!-- Role -->
                <td class="whitespace-nowrap px-6 py-4">
                  <span
                    class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium {user.is_superuser
                      ? 'bg-purple-100 text-purple-800'
                      : 'bg-gray-100 text-gray-800'}"
                  >
                    {user.is_superuser ? 'Superuser' : 'User'}
                  </span>
                </td>

                <!-- Created -->
                <td class="whitespace-nowrap px-6 py-4 text-sm text-gray-500">
                  {formatDate(user.created_at)}
                </td>

                <!-- Actions -->
                <td class="whitespace-nowrap px-6 py-4 text-sm">
                  <div class="flex gap-2">
                    <button
                      onclick={() => toggleUserActive(user)}
                      class="rounded px-3 py-1 text-xs font-medium transition-colors {user.is_active
                        ? 'bg-red-100 text-red-700 hover:bg-red-200'
                        : 'bg-green-100 text-green-700 hover:bg-green-200'}"
                    >
                      {user.is_active ? 'Deactivate' : 'Activate'}
                    </button>
                    <button
                      onclick={() => toggleUserSuperuser(user)}
                      class="rounded bg-purple-100 px-3 py-1 text-xs font-medium text-purple-700 transition-colors hover:bg-purple-200"
                    >
                      {user.is_superuser ? 'Demote' : 'Promote'}
                    </button>
                  </div>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Pagination -->
    {#if totalPages > 1}
      <div class="mt-6 flex items-center justify-between">
        <div class="text-sm text-gray-700">
          Showing <span class="font-medium">{(page - 1) * limit + 1}</span>
          to
          <span class="font-medium">{Math.min(page * limit, total)}</span>
          of
          <span class="font-medium">{total}</span>
          users
        </div>

        <div class="flex space-x-2">
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
      </div>
    {/if}
  {/if}
</div>
