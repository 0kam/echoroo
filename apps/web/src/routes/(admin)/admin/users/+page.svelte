<script lang="ts">
  /**
   * Admin - User Management Page
   */

  import { adminApi } from '$lib/api/admin';
  import { ApiError } from '$lib/api/client';
  import { getLocale } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
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
        error = m.admin_users_error_load();
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
      successMessage = user.is_active
        ? m.admin_users_success_activated()
        : m.admin_users_success_deactivated();

      // Clear success message after 3 seconds
      setTimeout(() => {
        successMessage = null;
      }, 3000);
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = m.admin_users_error_update();
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
      successMessage = user.is_superuser
        ? m.admin_users_success_promoted()
        : m.admin_users_success_demoted();

      // Clear success message after 3 seconds
      setTimeout(() => {
        successMessage = null;
      }, 3000);
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = m.admin_users_error_update();
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
    return new Date(dateString).toLocaleString(getLocale());
  }
</script>

<svelte:head>
  <title>{m.admin_users_heading()} - Admin - Echoroo</title>
</svelte:head>

<div class="px-8 py-6">
  <!-- Header -->
  <div class="mb-6">
    <h1 class="text-3xl font-bold text-stone-900">{m.admin_users_heading()}</h1>
    <p class="mt-2 text-sm text-stone-600">{m.admin_users_description()}</p>
  </div>

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

  <!-- Filters -->
  <div class="mb-6 flex flex-col gap-4 sm:flex-row">
    <!-- Search -->
    <div class="flex-1">
      <label for="search" class="sr-only">{m.admin_users_search_placeholder()}</label>
      <div class="relative">
        <div class="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
          <svg class="h-5 w-5 text-stone-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
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
          placeholder={m.admin_users_search_placeholder()}
          class="block w-full rounded-lg border border-stone-300 bg-surface-card py-2 pl-10 pr-3 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
        />
      </div>
    </div>

    <!-- Status Filter -->
    <div class="sm:w-48">
      <label for="status-filter" class="sr-only">{m.admin_users_table_status()}</label>
      <select
        id="status-filter"
        onchange={handleFilterChange}
        class="block w-full rounded-lg border border-stone-300 bg-surface-card py-2 pl-3 pr-10 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
      >
        <option value="all">{m.admin_users_filter_all()}</option>
        <option value="active">{m.admin_users_filter_active()}</option>
        <option value="inactive">{m.admin_users_filter_inactive()}</option>
      </select>
    </div>
  </div>

  <!-- Users Table -->
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
  {:else if users.length === 0}
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
          d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"
        />
      </svg>
      <h3 class="mt-2 text-sm font-medium text-stone-900">{m.admin_users_empty_title()}</h3>
      <p class="mt-1 text-sm text-stone-500">{m.admin_users_empty_description()}</p>
    </div>
  {:else}
    <div class="overflow-hidden rounded-lg border border-card bg-surface-card shadow-sm">
      <div class="overflow-x-auto">
        <table class="min-w-full divide-y divide-stone-200">
          <thead class="bg-stone-50">
            <tr>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-stone-500"
              >
                {m.admin_users_table_email()}
              </th>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-stone-500"
              >
                {m.admin_users_table_display_name()}
              </th>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-stone-500"
              >
                {m.admin_users_table_status()}
              </th>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-stone-500"
              >
                {m.admin_users_table_role()}
              </th>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-stone-500"
              >
                {m.admin_users_table_created()}
              </th>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-stone-500"
              >
                {m.admin_users_table_actions()}
              </th>
            </tr>
          </thead>
          <tbody class="divide-y divide-stone-200 bg-surface-card">
            {#each users as user (user.id)}
              <tr class="hover:bg-stone-50">
                <!-- Email -->
                <td class="whitespace-nowrap px-6 py-4">
                  <div class="flex items-center">
                    <div>
                      <div class="text-sm font-medium text-stone-900">{user.email}</div>
                      {#if user.organization}
                        <div class="text-xs text-stone-500">{user.organization}</div>
                      {/if}
                    </div>
                  </div>
                </td>

                <!-- Display Name -->
                <td class="whitespace-nowrap px-6 py-4 text-sm text-stone-900">
                  {user.display_name || '-'}
                </td>

                <!-- Status -->
                <td class="whitespace-nowrap px-6 py-4">
                  <div class="flex flex-col gap-1">
                    <span
                      class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium {user.is_active
                        ? 'bg-success-light text-success'
                        : 'bg-danger-light text-danger'}"
                    >
                      {user.is_active ? m.admin_users_status_active() : m.admin_users_status_inactive()}
                    </span>
                    {#if user.is_verified}
                      <span
                        class="inline-flex items-center rounded-full bg-primary-100 px-2.5 py-0.5 text-xs font-medium text-primary-800 dark:bg-primary-900/30 dark:text-primary-400"
                      >
                        {m.admin_users_badge_verified()}
                      </span>
                    {/if}
                  </div>
                </td>

                <!-- Role -->
                <td class="whitespace-nowrap px-6 py-4">
                  <span
                    class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium {user.is_superuser
                      ? 'bg-primary-100 text-primary-800 dark:bg-primary-900/30 dark:text-primary-400'
                      : 'bg-stone-100 text-stone-800 dark:bg-stone-700 dark:text-stone-300'}"
                  >
                    {user.is_superuser ? m.admin_users_role_superuser() : m.admin_users_role_user()}
                  </span>
                </td>

                <!-- Created -->
                <td class="whitespace-nowrap px-6 py-4 text-sm text-stone-500">
                  {formatDate(user.created_at)}
                </td>

                <!-- Actions -->
                <td class="whitespace-nowrap px-6 py-4 text-sm">
                  <div class="flex gap-2">
                    <button
                      onclick={() => toggleUserActive(user)}
                      class="rounded px-3 py-1 text-xs font-medium transition-colors {user.is_active
                        ? 'bg-danger-light text-danger hover:bg-danger/20'
                        : 'bg-success-light text-success hover:bg-success/20'}"
                    >
                      {user.is_active ? m.admin_users_button_deactivate() : m.admin_users_button_activate()}
                    </button>
                    <button
                      onclick={() => toggleUserSuperuser(user)}
                      class="rounded bg-primary-100 px-3 py-1 text-xs font-medium text-primary-700 transition-colors hover:bg-primary-200 dark:bg-primary-900/30 dark:text-primary-400 dark:hover:bg-primary-900/50"
                    >
                      {user.is_superuser ? m.admin_users_button_demote() : m.admin_users_button_promote()}
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
        <div class="text-sm text-stone-700">
          {m.admin_users_pagination_showing({
            from: (page - 1) * limit + 1,
            to: Math.min(page * limit, total),
            total,
          })}
        </div>

        <div class="flex space-x-2">
          <button
            onclick={() => changePage(page - 1)}
            disabled={page === 1}
            class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {m.admin_users_pagination_previous()}
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
            {m.admin_users_pagination_next()}
          </button>
        </div>
      </div>
    {/if}
  {/if}
</div>
