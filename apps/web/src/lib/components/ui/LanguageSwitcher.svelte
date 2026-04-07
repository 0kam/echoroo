<script lang="ts">
  /**
   * Language switcher component.
   * Sets the locale cookie via setLocale() then performs a hard navigation so
   * that Paraglide picks up the new locale on both server and client.
   */

  import { page } from '$app/stores';
  import { locales, getLocale, setLocale, localizeHref, deLocalizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';

  // Language display names keyed by locale code
  const languageNames: Record<string, string> = {
    en: 'English',
    ja: '日本語',
  };

  // Current locale resolved from the URL
  let currentLocale = $derived(getLocale());

  /**
   * Build the href for a given locale by first de-localizing the current path,
   * then re-localizing it for the target locale.
   */
  function getLocaleHref(targetLocale: string): string {
    const currentPath = $page.url.pathname + $page.url.search;
    const basePath = deLocalizeHref(currentPath);
    return localizeHref(basePath, { locale: targetLocale as 'en' | 'ja' });
  }

  /**
   * Switch locale: persist via cookie then hard-navigate to the localized URL.
   * We use setLocale() with reload:false to write the cookie without triggering
   * Paraglide's own reload, then manually navigate so SvelteKit's server hook
   * reads the correct locale on the next request.
   */
  function switchLocale(targetLocale: string) {
    setLocale(targetLocale as 'en' | 'ja', { reload: false });
    window.location.href = getLocaleHref(targetLocale);
  }
</script>

<div class="flex items-center gap-1" aria-label={m.language_switcher_label()}>
  {#each locales as locale}
    {#if locale === currentLocale}
      <span
        class="rounded px-2 py-1 text-xs font-semibold text-stone-900 bg-stone-100"
        aria-current="true"
      >
        {languageNames[locale] ?? locale}
      </span>
    {:else}
      <button
        type="button"
        onclick={() => switchLocale(locale)}
        class="rounded px-2 py-1 text-xs font-medium text-stone-500 hover:bg-stone-100 hover:text-stone-800 transition-colors"
      >
        {languageNames[locale] ?? locale}
      </button>
    {/if}
  {/each}
</div>
