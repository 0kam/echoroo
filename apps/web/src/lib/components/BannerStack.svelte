<script lang="ts">
  /**
   * spec/011 US7 (T640) — non-modal in-app banner stack.
   *
   * Renders undismissed, A-13-safe banners for the authenticated user just
   * below the global header. Each row shows the backend-rendered `summary`
   * verbatim (NOT translated), a "View activity" deep-link, and a dismiss
   * button. Renders nothing when there are no banners (no empty box).
   *
   * Transport: TanStack Query (list) + mutation (dismiss). The dismiss
   * mutation invalidates the list on BOTH success and error so the UI
   * reconciles to server truth — including the anti-enumeration 404, which
   * is treated as "already gone", never surfaced as a distinct error.
   */
  import {
    createQuery,
    createMutation,
    useQueryClient,
  } from '@tanstack/svelte-query';
  import { fly } from 'svelte/transition';
  import { meApi } from '$lib/api/me';
  import { authStore } from '$lib/stores/auth.svelte';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import type { BannerItem } from '$lib/types/me';

  const queryClient = useQueryClient();

  // Only fetch once auth is resolved AND the user is authenticated — never
  // fire /me/banners pre-auth (it would 401).
  const enabled = $derived(authStore.isAuthenticated && !authStore.isLoading);

  const bannersQuery = $derived(
    createQuery({
      queryKey: ['me-banners'],
      queryFn: () => meApi.listBanners(),
      enabled,
      staleTime: 60_000,
    })
  );

  const dismissMutation = createMutation({
    mutationFn: (b: Pick<BannerItem, 'audit_table' | 'audit_log_id'>) =>
      meApi.dismissBanner({
        audit_table: b.audit_table,
        audit_log_id: b.audit_log_id,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['me-banners'] });
    },
    onError: () => {
      // 404 anti-enumeration / network: invalidate so the UI converges to
      // server truth (the row may already be gone). Do NOT surface the 404
      // distinctly — the backend collapses three failure modes into one.
      queryClient.invalidateQueries({ queryKey: ['me-banners'] });
    },
  });

  const items = $derived($bannersQuery.data?.items ?? []);

  function dismiss(b: BannerItem): void {
    $dismissMutation.mutate({
      audit_table: b.audit_table,
      audit_log_id: b.audit_log_id,
    });
  }
</script>

{#if enabled && items.length > 0}
  <div class="flex flex-shrink-0 flex-col">
    {#each items as banner (banner.audit_table + ':' + banner.audit_log_id)}
      <div
        transition:fly={{ y: -10, duration: 150 }}
        role="alert"
        class="flex items-center gap-3 border-b border-info/40 bg-info-light px-4 py-2 text-info"
      >
        <svg
          class="h-5 w-5 flex-shrink-0"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          aria-hidden="true"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"
          />
        </svg>

        <!-- Backend-rendered, A-13-safe summary — DO NOT translate. -->
        <p class="flex-1 text-sm">{banner.summary}</p>

        <!-- `link` is always null in phase 1 → always deep-link to activity. -->
        <a
          href={localizeHref('/profile/activity')}
          class="text-sm font-medium underline underline-offset-2 hover:opacity-80"
        >
          {m.banner_view_activity()}
        </a>

        <button
          type="button"
          onclick={() => dismiss(banner)}
          disabled={$dismissMutation.isPending}
          class="flex h-6 w-6 flex-shrink-0 items-center justify-center text-info opacity-60 transition-opacity hover:opacity-100 disabled:opacity-30"
          aria-label={m.banner_dismiss_aria()}
        >
          ✕
        </button>
      </div>
    {/each}
  </div>
{/if}
