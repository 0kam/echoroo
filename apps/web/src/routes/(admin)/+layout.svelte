<script lang="ts">
  /**
   * Admin layout with navigation sidebar
   */

  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { authStore } from '$lib/stores/auth.svelte';

  interface Props {
    children: import('svelte').Snippet;
  }

  let { children }: Props = $props();

  // Navigation items
  const navItems = [
    {
      name: 'Users',
      href: '/admin/users',
      icon: 'M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z',
    },
    {
      name: 'Settings',
      href: '/admin/settings',
      icon: 'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z',
    },
    {
      name: 'Licenses',
      href: '/admin/licenses',
      icon: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z',
    },
    {
      name: 'Recorders',
      href: '/admin/recorders',
      icon: 'M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z',
    },
  ];

  // Redirect non-superusers away from admin (client-side guard)
  $effect(() => {
    if (!authStore.isLoading && authStore.user && !authStore.user.is_superuser) {
      goto('/dashboard');
    }
  });

  /**
   * Check if nav item is active
   */
  function isActive(href: string): boolean {
    return $page.url.pathname.startsWith(href);
  }

  /**
   * Navigate to item
   */
  function navigateTo(href: string) {
    goto(href);
  }

  /**
   * Logout handler
   */
  async function handleLogout() {
    await authStore.logout();
    goto('/login');
  }
</script>

<svelte:head>
  <title>Admin - Echoroo</title>
</svelte:head>

<div class="flex h-screen bg-gray-50">
  <!-- Sidebar -->
  <aside class="w-64 border-r border-gray-200 bg-white">
    <!-- Sidebar Header -->
    <div class="flex h-16 items-center border-b border-gray-200 px-6">
      <h1 class="text-xl font-bold text-gray-900">Echoroo Admin</h1>
    </div>

    <!-- Navigation -->
    <nav class="flex-1 space-y-1 p-4">
      {#each navItems as item}
        <button
          onclick={() => navigateTo(item.href)}
          class="flex w-full items-center rounded-lg px-4 py-3 text-sm font-medium transition-colors {isActive(
            item.href
          )
            ? 'bg-blue-50 text-blue-700'
            : 'text-gray-700 hover:bg-gray-50'}"
        >
          <svg class="mr-3 h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d={item.icon} />
          </svg>
          {item.name}
        </button>
      {/each}
    </nav>

    <!-- Sidebar Footer -->
    <div class="border-t border-gray-200 p-4">
      <div class="mb-3 rounded-lg bg-blue-50 p-3">
        <p class="text-xs font-medium text-blue-900">Logged in as</p>
        <p class="mt-1 truncate text-sm text-blue-700">
          {authStore.user?.display_name || authStore.user?.email || 'Admin'}
        </p>
      </div>
      <div class="space-y-2">
        <a
          href="/dashboard"
          class="flex w-full items-center justify-center rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50"
        >
          <svg class="mr-2 h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"
            />
          </svg>
          Dashboard
        </a>
        <button
          onclick={handleLogout}
          class="flex w-full items-center justify-center rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50"
        >
          <svg class="mr-2 h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"
            />
          </svg>
          Logout
        </button>
      </div>
    </div>
  </aside>

  <!-- Main Content -->
  <main class="flex-1 overflow-auto">
    {@render children()}
  </main>
</div>
