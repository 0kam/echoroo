<script lang="ts">
  /**
   * Language switcher component.
   * Navigates to the same page with a different locale prefix,
   * triggering a full page reload so paraglide picks up the new locale.
   */

  import { page } from '$app/stores';
  import { locales, getLocale, localizeHref, deLocalizeHref } from '$lib/paraglide/runtime';
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
      <a
        href={getLocaleHref(locale)}
        data-sveltekit-reload
        class="rounded px-2 py-1 text-xs font-medium text-stone-500 hover:bg-stone-100 hover:text-stone-800 transition-colors"
      >
        {languageNames[locale] ?? locale}
      </a>
    {/if}
  {/each}
</div>
