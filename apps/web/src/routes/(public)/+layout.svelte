<script lang="ts">
  /**
   * (public) layout — Phase 5 US1 (T211).
   *
   * Renders a minimal top bar suitable for unauthenticated Guests browsing
   * Public + Active projects. Authenticated callers see a "Back to dashboard"
   * link instead of the sign-in / register CTA so the same shell can be used
   * regardless of session state (FR-009 / FR-016).
   *
   * Intentionally lightweight: no project sidebar, no member tools — those
   * live in the `(app)` layout, which is auth-guarded.
   */

  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import LanguageSwitcher from '$lib/components/ui/LanguageSwitcher.svelte';
  import DarkModeToggle from '$lib/components/ui/DarkModeToggle.svelte';
  import type { Snippet } from 'svelte';

  interface Props {
    children: Snippet;
    data: { isAuthenticated: boolean; locale?: string };
  }

  let { children, data }: Props = $props();
</script>

<div class="flex min-h-screen flex-col bg-surface-page">
  <!-- Top bar: brand, language switcher, dark-mode toggle, sign-in CTA -->
  <header
    class="flex h-12 flex-shrink-0 items-center border-b border-card bg-surface-card px-4"
  >
    <div class="flex items-center gap-6">
      <a
        href={localizeHref('/explore/projects')}
        class="flex items-center gap-1.5 text-sm font-semibold tracking-wide text-primary-500 hover:text-primary-600"
      >
        <img src="/echoroo.png" alt="Echoroo" class="h-6 w-auto" />
        {m.nav_brand()}
      </a>
    </div>

    <div class="ml-auto flex items-center gap-2">
      {#if data.isAuthenticated}
        <a
          href={localizeHref('/dashboard')}
          class="rounded px-3 py-1 text-xs font-medium text-stone-600 transition-colors hover:bg-stone-100 hover:text-stone-900"
        >
          {m.public_layout_dashboard_link()}
        </a>
      {:else}
        <a
          href={localizeHref('/login')}
          class="rounded px-3 py-1 text-xs font-medium text-stone-600 transition-colors hover:bg-stone-100 hover:text-stone-900"
        >
          {m.auth_login_submit()}
        </a>
        <a
          href={localizeHref('/register')}
          class="rounded px-3 py-1 text-xs font-medium text-primary-700 ring-1 ring-primary-200 transition-colors hover:bg-primary-50"
        >
          {m.auth_login_register_link()}
        </a>
      {/if}

      <DarkModeToggle />
      <LanguageSwitcher />
    </div>
  </header>

  <!-- Page body -->
  <main class="flex-1">
    {@render children()}
  </main>
</div>
