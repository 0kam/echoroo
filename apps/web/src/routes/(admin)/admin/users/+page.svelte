<script lang="ts">
  /**
   * Admin - User Management Page.
   *
   * spec/006 + spec/011 cleanup: the backend ``AdminUserListItem`` schema
   * no longer exposes ``is_active`` / ``is_verified`` / ``organization``,
   * and the legacy Activate / Deactivate / Promote / Demote controls were
   * dead UI (the corresponding PATCH fields are silently dropped server
   * side). Superuser promotion is handled exclusively through the
   * ``/admin/superusers`` M-of-N workflow; this page is now a read-only
   * roster with email + display name + SU role + timestamps.
   */

  import { adminApi } from '$lib/api/admin';
  import { ApiError } from '$lib/api/client';
  import { getLocale } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import type { AdminUserListItem } from '$lib/types';

  // State
  let users = $state<AdminUserListItem[]>([]);
  let total = $state(0);
  let page = $state(1);
  let limit = $state(20);
  let search = $state('');
  let isLoading = $state(true);
  let error = $state<string | null>(null);

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

  /**
   * Format optional date (last_login_at may be null)
   */
  function formatOptionalDate(dateString: string | null): string {
    return dateString ? formatDate(dateString) : '-';
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

  <!-- Manage Superusers hint -->
  <div class="mb-6 rounded-md border border-card bg-surface-card p-4 text-sm text-stone-600">
    {m.admin_users_manage_su_hint()}
    <a
      href="/admin/superusers"
      class="ml-1 font-medium text-primary-700 underline-offset-2 hover:underline dark:text-primary-400"
    >
      {m.admin_users_manage_su_link()}
    </a>
  </div>

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
                {m.admin_users_table_last_login()}
              </th>
            </tr>
          </thead>
          <tbody class="divide-y divide-stone-200 bg-surface-card">
            {#each users as user (user.id)}
              <tr class="hover:bg-stone-50">
                <!-- Email -->
                <td class="whitespace-nowrap px-6 py-4">
                  <div class="text-sm font-medium text-stone-900">{user.email}</div>
                </td>

                <!-- Display Name -->
                <td class="whitespace-nowrap px-6 py-4 text-sm text-stone-900">
                  {user.display_name || '-'}
                </td>

                <!-- Role -->
                <td class="whitespace-nowrap px-6 py-4">
                  {#if user.is_superuser}
                    <span
                      class="inline-flex items-center rounded-full bg-primary-100 px-2.5 py-0.5 text-xs font-medium text-primary-800 dark:bg-primary-900/30 dark:text-primary-400"
                    >
                      {m.admin_users_role_superuser()}
                    </span>
                  {:else}
                    <span
                      class="inline-flex items-center rounded-full bg-stone-100 px-2.5 py-0.5 text-xs font-medium text-stone-800 dark:bg-stone-700 dark:text-stone-300"
                    >
                      {m.admin_users_role_user()}
                    </span>
                  {/if}
                </td>

                <!-- Created -->
                <td class="whitespace-nowrap px-6 py-4 text-sm text-stone-500">
                  {formatDate(user.created_at)}
                </td>

                <!-- Last login -->
                <td class="whitespace-nowrap px-6 py-4 text-sm text-stone-500">
                  {formatOptionalDate(user.last_login_at)}
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
