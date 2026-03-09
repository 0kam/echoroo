<script lang="ts">
  /**
   * App layout with global top navigation header and auth guard.
   * This wraps all (app) routes and sits above the project sidebar layout.
   */

  import { goto } from '$app/navigation';
  import { authStore } from '$lib/stores/auth.svelte';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import LanguageSwitcher from '$lib/components/ui/LanguageSwitcher.svelte';
  import DarkModeToggle from '$lib/components/ui/DarkModeToggle.svelte';

  interface Props {
    children: import('svelte').Snippet;
  }

  let { children }: Props = $props();

  /**
   * Auth guard: redirect to login if not authenticated after loading completes.
   */
  $effect(() => {
    if (!authStore.isLoading && !authStore.isAuthenticated) {
      goto(localizeHref('/login'));
    }
  });

  /**
   * Logout handler
   */
  async function handleLogout() {
    await authStore.logout();
    goto(localizeHref('/login'));
  }
</script>

<div class="flex h-screen flex-col bg-surface-page">
  <!-- Global top navigation header -->
  <header class="flex h-12 flex-shrink-0 items-center border-b border-card bg-surface-card px-4">
    {#if authStore.isLoading}
      <!-- Loading spinner while auth state resolves -->
      <div class="flex w-full items-center justify-center">
        <svg
          class="h-5 w-5 animate-spin text-stone-400"
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
        >
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path
            class="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
          ></path>
        </svg>
      </div>
    {:else}
      <!-- Left: Logo / brand link -->
      <div class="flex items-center gap-6">
        <a
          href={localizeHref('/dashboard')}
          class="flex items-center gap-1.5 text-sm font-semibold tracking-wide text-primary-500 hover:text-primary-600"
        >
          <img src="/echoroo.png" alt="Echoroo" class="h-6 w-auto" />
          {m.nav_brand()}
        </a>
        <nav class="flex items-center gap-1">
          <a
            href={localizeHref('/projects')}
            class="rounded px-3 py-1 text-sm font-medium text-stone-600 transition-colors hover:bg-stone-100 hover:text-stone-900"
          >
            {m.nav_projects()}
          </a>
        </nav>
      </div>

      <!-- Right: user info and actions -->
      <div class="ml-auto flex items-center gap-2">
        {#if authStore.user?.display_name || authStore.user?.email}
          <span class="text-xs text-stone-500">
            {authStore.user.display_name || authStore.user.email}
          </span>
        {/if}

        {#if authStore.user?.is_superuser}
          <a
            href={localizeHref('/admin/users')}
            class="rounded px-3 py-1 text-xs font-medium text-primary-700 ring-1 ring-primary-200 transition-colors hover:bg-primary-50"
          >
            {m.nav_admin()}
          </a>
        {/if}

        <a
          href={localizeHref('/profile')}
          class="rounded px-3 py-1 text-xs font-medium text-stone-600 transition-colors hover:bg-stone-100 hover:text-stone-900"
        >
          {m.nav_profile()}
        </a>

        <button
          type="button"
          onclick={handleLogout}
          class="rounded px-3 py-1 text-xs font-medium text-stone-600 transition-colors hover:bg-stone-100 hover:text-stone-900"
        >
          {m.nav_logout()}
        </button>

        <DarkModeToggle />
        <LanguageSwitcher />
      </div>
    {/if}
  </header>

  <!-- Page content (flex-1 so it fills remaining height) -->
  <div class="flex flex-1 overflow-hidden">
    {@render children()}
  </div>
</div>
