<script lang="ts">
  /**
   * Admin layout with top navigation header, matching the dashboard style.
   *
   * Phase 15 (006-permissions-redesign T955): adds the "Superusers"
   * navigation entry and a break-glass status banner that is visible to
   * every superuser whenever the platform is in break-glass mode (FR-111).
   */

  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { authStore } from '$lib/stores/auth.svelte';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import LanguageSwitcher from '$lib/components/ui/LanguageSwitcher.svelte';
  import DarkModeToggle from '$lib/components/ui/DarkModeToggle.svelte';
  import { superuserApi, type SuperuserBreakGlassStatusResponse } from '$lib/api/superusers';

  interface Props {
    children: import('svelte').Snippet;
  }

  let { children }: Props = $props();

  // Navigation items
  const navItems = $derived([
    { name: m.admin_nav_users(), href: '/admin/users' },
    { name: m.admin_nav_superusers(), href: '/admin/superusers' },
    { name: m.admin_nav_settings(), href: '/admin/settings' },
    { name: m.admin_nav_licenses(), href: '/admin/licenses' },
    { name: m.admin_nav_recorders(), href: '/admin/recorders' },
  ]);

  let breakGlass = $state<SuperuserBreakGlassStatusResponse | null>(null);

  // Redirect non-superusers away from admin (client-side guard)
  $effect(() => {
    if (!authStore.isLoading && authStore.user && !authStore.user.is_superuser) {
      goto(localizeHref('/dashboard'));
    }
  });

  // Fetch break-glass status once we know we are an authenticated
  // superuser.  Errors are swallowed: the banner is purely informational
  // and must not block normal admin pages from rendering when the status
  // endpoint is briefly unavailable.
  $effect(() => {
    if (
      !authStore.isLoading &&
      authStore.user &&
      authStore.user.is_superuser
    ) {
      superuserApi
        .breakGlassStatus()
        .then((status) => {
          breakGlass = status;
        })
        .catch(() => {
          breakGlass = null;
        });
    }
  });

  /**
   * Check if nav item is active
   */
  function isActive(href: string): boolean {
    return $page.url.pathname.startsWith(href);
  }

  /**
   * Logout handler
   */
  async function handleLogout() {
    await authStore.logout();
    goto(localizeHref('/login'));
  }
</script>

<svelte:head>
  <title>{m.admin_page_title()}</title>
</svelte:head>

<div class="flex h-screen flex-col bg-surface-page">
  <!-- Top navigation header -->
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
      <!-- Left: Logo / brand and navigation links -->
      <div class="flex items-center gap-6">
        <a
          href={localizeHref('/admin/users')}
          class="flex items-center gap-1.5 text-sm font-semibold tracking-wide text-primary-500 hover:text-primary-600"
        >
          <img src="/echoroo.png" alt="Echoroo" class="h-6 w-auto" />
          {m.admin_sidebar_title()}
        </a>
        <nav class="flex items-center gap-1">
          {#each navItems as item}
            <a
              href={localizeHref(item.href)}
              class="rounded px-3 py-1 text-sm font-medium transition-colors {isActive(item.href)
                ? 'bg-primary-100 text-primary-700 dark:bg-primary-900/30 dark:text-primary-400'
                : 'text-stone-600 hover:bg-stone-100 hover:text-stone-900 dark:text-stone-400 dark:hover:bg-stone-800 dark:hover:text-stone-100'}"
            >
              {item.name}
            </a>
          {/each}
        </nav>
      </div>

      <!-- Right: user info and actions -->
      <div class="ml-auto flex items-center gap-2">
        {#if authStore.user?.display_name || authStore.user?.email}
          <span class="text-xs text-stone-500 dark:text-stone-400">
            {authStore.user.display_name || authStore.user.email}
          </span>
        {/if}

        <a
          href={localizeHref('/dashboard')}
          class="rounded px-3 py-1 text-xs font-medium text-stone-600 transition-colors hover:bg-stone-100 hover:text-stone-900 dark:text-stone-400 dark:hover:bg-stone-800 dark:hover:text-stone-100"
        >
          {m.admin_sidebar_dashboard()}
        </a>

        <button
          type="button"
          onclick={handleLogout}
          class="rounded px-3 py-1 text-xs font-medium text-stone-600 transition-colors hover:bg-stone-100 hover:text-stone-900 dark:text-stone-400 dark:hover:bg-stone-800 dark:hover:text-stone-100"
        >
          {m.admin_sidebar_logout()}
        </button>

        <DarkModeToggle />
        <LanguageSwitcher />
      </div>
    {/if}
  </header>

  <!-- Break-glass banner (FR-111): shown to all superusers when active -->
  {#if breakGlass?.active}
    <div
      role="alert"
      class="border-b border-danger/40 bg-danger-light px-4 py-2 text-xs font-medium text-danger"
    >
      <span class="font-semibold">
        {m.admin_superusers_break_glass_banner_label()}
      </span>
      <span class="ml-2">
        {m.admin_superusers_break_glass_banner_message()}
      </span>
      {#if breakGlass.expires_at}
        <span class="ml-2 opacity-75">
          {m.admin_superusers_break_glass_banner_expires({
            time: new Date(breakGlass.expires_at).toLocaleString(),
          })}
        </span>
      {/if}
    </div>
  {/if}

  <!-- Page content -->
  <main class="flex-1 overflow-auto p-4 sm:p-6 lg:p-8">
    {@render children()}
  </main>
</div>
