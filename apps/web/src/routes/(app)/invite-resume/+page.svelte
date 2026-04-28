<script lang="ts">
  /**
   * Invite resume route — Phase 10 / T521 (Round 2 polish).
   *
   * The token-bearing ``/invite/{token}?project_id=...`` URL is now under
   * the ``(public)`` group so it never leaks the token through SvelteKit's
   * ``/login?redirect=...`` machinery. When a Guest opens an invite link we
   * stash ``{token, projectId}`` in ``sessionStorage`` and send them to
   * ``/login?redirect=/invite-resume`` — i.e. this page.
   *
   * On mount (we are inside ``(app)`` so the auth guard guarantees a
   * session) we read the stash, clear it, and ``replaceState`` onto the
   * canonical accept URL. The accept page then performs the actual
   * ``POST .../accept`` call against ``apiClient`` which now has a fresh
   * Bearer.
   *
   * If the stash is missing — e.g. the user navigated here manually, or
   * ``sessionStorage`` was cleared — we silently route them to
   * ``/dashboard`` instead of leaving them on a blank page.
   */

  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { browser } from '$app/environment';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';

  const RESUME_TOKEN_KEY = 'echoroo:pendingInviteToken';
  const RESUME_PROJECT_KEY = 'echoroo:pendingInviteProjectId';

  onMount(() => {
    if (!browser) return;
    let token: string | null = null;
    let projectId: string | null = null;
    try {
      token = sessionStorage.getItem(RESUME_TOKEN_KEY);
      projectId = sessionStorage.getItem(RESUME_PROJECT_KEY);
      // One-shot: clear immediately so a refresh of this page after a
      // successful accept doesn't bounce the user into another accept
      // attempt with a now-consumed token.
      sessionStorage.removeItem(RESUME_TOKEN_KEY);
      sessionStorage.removeItem(RESUME_PROJECT_KEY);
    } catch {
      // ignore — fall through to the fallback navigation below.
    }
    if (!token) {
      void goto(localizeHref('/dashboard'));
      return;
    }
    const target = projectId
      ? `/invite/${encodeURIComponent(token)}?project_id=${encodeURIComponent(projectId)}`
      : `/invite/${encodeURIComponent(token)}`;
    void goto(localizeHref(target), { replaceState: true });
  });
</script>

<svelte:head>
  <title>{m.invite_landing_title()} - Echoroo</title>
</svelte:head>

<div class="mx-auto max-w-xl px-4 py-12" data-testid="invite-resume-page">
  <p class="text-sm text-stone-700">{m.invite_landing_loading()}</p>
</div>
