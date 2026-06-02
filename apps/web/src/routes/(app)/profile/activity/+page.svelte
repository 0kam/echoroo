<script lang="ts">
  /**
   * spec/011 US7 (T642) — authenticated user audit-activity history.
   *
   * Sibling route mirroring `/profile/api-tokens` (profile has no tab
   * system). Keyset/cursor pagination: pages accumulate in local `$state`
   * via a "Load more" button which hides once `next_cursor === null`.
   *
   * Each row renders ONLY the raw `action` string + a localized timestamp.
   * `details` and the (always-null) `actor_user_id` are NOT A-13-redacted
   * and are deliberately never rendered.
   */
  import { meApi } from '$lib/api/me';
  import { getLocale } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import type { ActivityItem } from '$lib/types/me';

  const ACTIVITY_LIMIT = 50; // matches backend DEFAULT_ACTIVITY_LIMIT

  let items = $state<ActivityItem[]>([]);
  let nextCursor = $state<string | null>(null);
  let loading = $state(false);
  let loadError = $state(false);
  let initialized = $state(false);

  async function loadPage(cursor: string | null): Promise<void> {
    if (loading) return;
    loading = true;
    loadError = false;
    try {
      const page = await meApi.listActivity({ cursor, limit: ACTIVITY_LIMIT });
      items = cursor ? [...items, ...page.items] : page.items;
      nextCursor = page.next_cursor;
    } catch {
      loadError = true;
    } finally {
      loading = false;
      initialized = true;
    }
  }

  // Initial load (the (app) layout guarantees the user is authenticated).
  $effect(() => {
    if (!initialized) void loadPage(null);
  });

  function fmt(ts: string): string {
    return new Date(ts).toLocaleString(getLocale());
  }
</script>

<svelte:head><title>{m.activity_title()}</title></svelte:head>

<div class="mx-auto w-full max-w-3xl px-4 py-6">
  <h1 class="mb-4 text-xl font-semibold text-stone-900">{m.activity_title()}</h1>

  {#if loadError && items.length === 0}
    <p
      class="rounded-md border border-danger/30 bg-danger-light px-4 py-3 text-sm text-danger"
    >
      {m.activity_load_error()}
    </p>
  {:else if !initialized && loading}
    <div class="flex justify-center py-16">
      <svg
        class="h-8 w-8 animate-spin text-stone-400"
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
        aria-hidden="true"
      >
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path
          class="opacity-75"
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
        ></path>
      </svg>
      <span class="sr-only">{m.activity_loading()}</span>
    </div>
  {:else if initialized && items.length === 0}
    <div class="flex flex-col items-center gap-2 py-16 text-center">
      <svg
        class="h-10 w-10 text-stone-400"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.5"
        aria-hidden="true"
      >
        <path
          stroke-linecap="round"
          stroke-linejoin="round"
          d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
        />
      </svg>
      <p class="font-medium text-stone-700">{m.activity_empty_title()}</p>
      <p class="text-sm text-stone-500">{m.activity_empty_description()}</p>
    </div>
  {:else}
    <ul class="divide-y divide-stone-200 rounded-lg border border-stone-200">
      {#each items as item (item.audit_table + ':' + item.audit_log_id)}
        <li class="flex flex-col gap-1 px-4 py-3">
          <span class="text-sm text-stone-900">{item.action}</span>
          <span class="text-xs text-stone-500">{fmt(item.occurred_at)}</span>
        </li>
      {/each}
    </ul>

    {#if nextCursor}
      <div class="mt-4 flex justify-center">
        <button
          type="button"
          onclick={() => loadPage(nextCursor)}
          disabled={loading}
          class="rounded-md border border-stone-300 px-4 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-100 disabled:opacity-50"
        >
          {loading ? m.activity_loading() : m.activity_load_more()}
        </button>
      </div>
    {/if}

    {#if loadError && items.length > 0}
      <p class="mt-2 text-center text-sm text-danger">{m.activity_load_error()}</p>
    {/if}
  {/if}
</div>
