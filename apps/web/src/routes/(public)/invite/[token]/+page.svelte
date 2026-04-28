<script lang="ts">
  /**
   * Invitation landing page — Phase 10 / T521 (Round 2 polish).
   *
   * URL shape: ``/invite/{signed_token}?project_id={uuid}``.
   *
   * Rationale for living under ``(public)``
   * ---------------------------------------
   * Before Round 2 this page lived under ``(app)/invite/[token]/`` and the
   * ``(app)`` layout guard redirected unauthenticated visitors to
   * ``/login?redirect=/invite/{token}`` — which leaked the signed token
   * into the login URL, the browser history, the SvelteKit
   * ``redirect`` query string, and (often) reverse-proxy access logs.
   * Round 1 flagged this as a *Critical*. The fix moves the page to
   * ``(public)`` so SvelteKit never has to bounce through ``/login`` with
   * the token in tow; instead, this component renders the appropriate
   * variant for each session state.
   *
   * Behaviour
   * ---------
   * 1. **Signed in** — same accept path as before: ``POST
   *    /web-api/v1/projects/{project_id}/invitations/{token}/accept`` with
   *    a generated ``X-Idempotency-Key`` (FR-053). On 200 we ``replaceState``
   *    the URL bar to the project detail URL so the token disappears from
   *    the user's history.
   * 2. **Signed out** — render the "Sign in to accept" CTA. Clicking the
   *    button stashes ``{token, projectId}`` in ``sessionStorage`` and
   *    navigates to ``/login`` *without* a ``redirect`` query parameter.
   *    After the user authenticates, the auth flow returns them to the
   *    canonical ``/invite-resume`` route which reads back the stash and
   *    ``replaceState``s the user onto the in-place accept URL.
   *
   * Backend errors surface via ``ApiError.code`` and map to the existing
   * ``invite_landing_*`` i18n keys (no new keys required for this fix).
   *
   * Decline flow (FR-107)
   * ---------------------
   * Authenticated recipients may DELETE the invitation themselves
   * (collapse-to-404 for cross-account / mismatch per FR-055). Decline is
   * unavailable to signed-out callers — they must sign in first to make a
   * decision attributable to a user identity (the backend gates DELETE on
   * the bearer principal anyway).
   */

  import { goto } from '$app/navigation';
  import { browser } from '$app/environment';
  import { ApiError } from '$lib/api/client';
  import { projectsApi } from '$lib/api/projects';
  import { authStore } from '$lib/stores/auth.svelte';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import { generateId } from '$lib/utils/id';
  import type { InvitationAcceptResponse } from '$lib/types';

  /** Page server-load output. */
  let { data } = $props();
  const token = $derived(data.token);
  const projectId = $derived(data.projectId);

  type Phase =
    | 'idle'
    | 'login_required'
    | 'accepting'
    | 'success'
    | 'error'
    | 'declining'
    | 'declined';

  /**
   * Component lifecycle:
   *
   *   idle → (login_required | accepting) → success | error
   *
   * The decline path is reachable only from `error` or `idle` while the
   * recipient is signed in.
   */
  let phase = $state<Phase>('idle');
  let result = $state<InvitationAcceptResponse | null>(null);
  let errorKey = $state<string | null>(null);
  let confirmDeclineOpen = $state(false);

  /**
   * Idempotency key — generated once per page load. Per FR-053, reusing
   * the same key with the same token is required for safe retries; using
   * it with a different token returns 409 from the backend.
   */
  const idempotencyKey = generateId();

  /** sessionStorage keys used to round-trip the token across login. */
  const RESUME_TOKEN_KEY = 'echoroo:pendingInviteToken';
  const RESUME_PROJECT_KEY = 'echoroo:pendingInviteProjectId';

  /**
   * Translate `ApiError` into the i18n key surfaced to the user. Returns
   * the generic-error key when the error wasn't an ApiError.
   */
  function mapAcceptError(err: unknown): string {
    if (err instanceof ApiError) {
      switch (err.status) {
        case 403:
          if (err.code === 'ERR_EMAIL_MISMATCH') {
            return 'invite_landing_email_mismatch';
          }
          break;
        case 404:
          return 'invite_landing_invitation_not_found';
        case 410:
          if (err.code === 'ERR_INVITATION_TERMINAL_STATE') {
            return 'invite_landing_already_used';
          }
          return 'invite_landing_expired';
        case 409:
          return 'invite_landing_conflict';
        case 503:
          return 'invite_landing_infra_unavailable';
      }
    }
    return 'invite_landing_generic_error';
  }

  /** Resolve an i18n key to its localised string. */
  function tr(key: string): string {
    switch (key) {
      case 'invite_landing_email_mismatch':
        return m.invite_landing_email_mismatch();
      case 'invite_landing_invitation_not_found':
        return m.invite_landing_invitation_not_found();
      case 'invite_landing_already_used':
        return m.invite_landing_already_used();
      case 'invite_landing_expired':
        return m.invite_landing_expired();
      case 'invite_landing_conflict':
        return m.invite_landing_conflict();
      case 'invite_landing_infra_unavailable':
        return m.invite_landing_infra_unavailable();
      case 'invite_landing_missing_project':
        return m.invite_landing_missing_project();
      default:
        return m.invite_landing_generic_error();
    }
  }

  async function tryAccept(): Promise<void> {
    if (!projectId) {
      phase = 'error';
      errorKey = 'invite_landing_missing_project';
      return;
    }
    if (!token) {
      phase = 'error';
      errorKey = 'invite_landing_invitation_not_found';
      return;
    }
    phase = 'accepting';
    errorKey = null;
    try {
      const res = await projectsApi.acceptInvitation(
        projectId,
        token,
        idempotencyKey,
      );
      result = res;
      phase = 'success';
      // Drop the token from the URL bar (and therefore from the entry in
      // the browser history). We replace with the project detail URL so
      // that `Back` returns the user to wherever they came from rather
      // than to an invite URL with a now-consumed token.
      if (browser && typeof history !== 'undefined') {
        const target = res.project_id
          ? localizeHref(`/projects/${res.project_id}`)
          : projectId
            ? localizeHref(`/projects/${projectId}`)
            : localizeHref('/dashboard');
        try {
          history.replaceState(history.state, '', target);
        } catch {
          // replaceState is best-effort. If it throws (e.g. exotic
          // browsers, sandboxed iframes) we still have the success
          // panel + Continue button below.
        }
      }
    } catch (err) {
      errorKey = mapAcceptError(err);
      phase = 'error';
    }
  }

  /**
   * React to auth-store transitions. While the store is loading we stay
   * idle. Once it resolves we either kick off the accept (signed in) or
   * present the in-place login CTA (signed out).
   */
  $effect(() => {
    if (authStore.isLoading) return;
    if (phase !== 'idle') return;
    if (authStore.isAuthenticated) {
      void tryAccept();
    } else {
      phase = 'login_required';
    }
  });

  function startLoginRedirect(): void {
    if (!browser) return;
    // Stash the invite credentials in sessionStorage so the login flow
    // can resume the accept without ever putting the token into a URL
    // query parameter.
    try {
      if (token) sessionStorage.setItem(RESUME_TOKEN_KEY, token);
      if (projectId) sessionStorage.setItem(RESUME_PROJECT_KEY, projectId);
    } catch {
      // Ignore storage failures; we still send the user to the login
      // page — they will simply lose the auto-resume on this device.
    }
    // Round 3 polish — fix Critical #1: navigate with `replaceState: true`
    // so the current `/invite/{token}` history entry is overwritten rather
    // than pushed onto the back stack. Without this, the signed token
    // would remain reachable via the browser Back button (and visible in
    // session history APIs) for the entire round-trip through
    // `/login` → `/invite-resume`. Replacing the entry guarantees that
    // once we reach the login screen, the token URL is gone from the
    // forward/back history altogether.
    void goto(localizeHref('/login?redirect=/invite-resume'), {
      replaceState: true,
    });
  }

  async function handleDecline(): Promise<void> {
    if (!projectId || !token) {
      confirmDeclineOpen = false;
      return;
    }
    phase = 'declining';
    try {
      await projectsApi.declineInvitation(projectId, token);
      phase = 'declined';
      confirmDeclineOpen = false;
    } catch {
      // Best-effort: the decline endpoint is intentionally generous
      // (404 / 410 / 204), so any unexpected error surfaces as the
      // generic message but we still allow the user to navigate away.
      errorKey = 'invite_landing_generic_error';
      phase = 'error';
      confirmDeclineOpen = false;
    }
  }

  function continueToProject(): void {
    if (result?.project_id) {
      void goto(localizeHref(`/projects/${result.project_id}`));
    } else if (projectId) {
      void goto(localizeHref(`/projects/${projectId}`));
    } else {
      void goto(localizeHref('/dashboard'));
    }
  }

  function backToHome(): void {
    void goto(localizeHref(authStore.isAuthenticated ? '/dashboard' : '/'));
  }
</script>

<svelte:head>
  <title>{m.invite_landing_title()} - Echoroo</title>
</svelte:head>

<div
  class="mx-auto max-w-xl px-4 py-12"
  data-testid="invite-landing-page"
>
  <h1 class="mb-2 text-2xl font-bold text-stone-900">
    {m.invite_landing_title()}
  </h1>

  {#if phase === 'idle' || phase === 'accepting'}
    <div
      data-testid="invite-landing-loading"
      class="rounded-lg bg-surface-card p-6 shadow"
    >
      <div class="flex items-center gap-3">
        <svg
          class="h-5 w-5 animate-spin text-primary-600"
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <circle
            class="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            stroke-width="4"
          ></circle>
          <path
            class="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
          ></path>
        </svg>
        <p class="text-sm text-stone-700">{m.invite_landing_loading()}</p>
      </div>
    </div>
  {:else if phase === 'login_required'}
    <div
      data-testid="invite-landing-login-required"
      class="rounded-lg bg-surface-card p-6 shadow"
      role="status"
    >
      <p class="text-sm text-stone-700">{m.invite_landing_login_required()}</p>
      <div class="mt-4">
        <button
          type="button"
          data-testid="invite-landing-login-button"
          onclick={startLoginRedirect}
          class="inline-flex items-center rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2"
        >
          {m.invite_landing_login_button()}
        </button>
      </div>
    </div>
  {:else if phase === 'success' && result}
    <div
      data-testid="invite-landing-success"
      class="rounded-lg bg-success-light p-6"
      role="status"
    >
      <p class="text-sm font-medium text-success">
        {result.kind === 'trusted'
          ? m.invite_landing_accept_success_trusted()
          : m.invite_landing_accept_success_member()}
      </p>
      <div class="mt-4">
        <button
          type="button"
          data-testid="invite-landing-continue"
          onclick={continueToProject}
          class="inline-flex items-center rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2"
        >
          {m.invite_landing_continue_to_project()}
        </button>
      </div>
    </div>
  {:else if phase === 'declined'}
    <div
      data-testid="invite-landing-declined"
      class="rounded-lg bg-stone-100 p-6"
      role="status"
    >
      <p class="text-sm text-stone-700">{m.invite_declined_message()}</p>
      <div class="mt-4">
        <button
          type="button"
          onclick={backToHome}
          class="inline-flex items-center rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50"
        >
          {m.invite_decline_back_to_home()}
        </button>
      </div>
    </div>
  {:else if phase === 'error' && errorKey}
    <div
      data-testid="invite-landing-error"
      data-error-key={errorKey}
      class="rounded-lg bg-danger-light p-6"
      role="alert"
    >
      <p class="text-sm font-medium text-danger">{tr(errorKey)}</p>

      <div class="mt-4 flex flex-wrap gap-2">
        {#if errorKey !== 'invite_landing_email_mismatch' && errorKey !== 'invite_landing_already_used' && errorKey !== 'invite_landing_expired' && errorKey !== 'invite_landing_invitation_not_found' && errorKey !== 'invite_landing_missing_project'}
          <!--
            For transient errors (503 infra unavailable, generic
            failures, idempotency conflict) offer a Retry button so the
            recipient can try again without a full page reload. We
            deliberately do NOT offer Retry on terminal errors (mismatch,
            not found, expired) because those will never recover.
          -->
          <button
            type="button"
            data-testid="invite-landing-retry"
            onclick={tryAccept}
            class="inline-flex items-center rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-primary-700"
          >
            {m.common_retry()}
          </button>
        {/if}
        {#if authStore.isAuthenticated}
          <button
            type="button"
            data-testid="invite-landing-decline-open"
            onclick={() => (confirmDeclineOpen = true)}
            class="inline-flex items-center rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50"
          >
            {m.invite_decline_button()}
          </button>
        {/if}
        <button
          type="button"
          onclick={backToHome}
          class="inline-flex items-center rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50"
        >
          {m.invite_decline_back_to_home()}
        </button>
      </div>
    </div>
  {/if}
</div>

{#if confirmDeclineOpen}
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    role="dialog"
    aria-modal="true"
    aria-labelledby="invite-decline-modal-title"
    data-testid="invite-decline-modal"
  >
    <div class="w-full max-w-md overflow-y-auto rounded-lg bg-surface-card shadow-xl">
      <div class="border-b border-stone-200 px-6 py-4">
        <h2
          id="invite-decline-modal-title"
          class="m-0 text-lg font-semibold text-stone-900"
        >
          {m.invite_decline_confirm_title()}
        </h2>
      </div>
      <div class="p-6">
        <p class="m-0 text-sm leading-relaxed text-stone-700">
          {m.invite_decline_confirm_message()}
        </p>
      </div>
      <div class="flex justify-end gap-3 border-t border-stone-200 px-6 py-4">
        <button
          type="button"
          onclick={() => (confirmDeclineOpen = false)}
          disabled={phase === 'declining'}
          class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {m.common_cancel()}
        </button>
        <button
          type="button"
          data-testid="invite-decline-confirm"
          onclick={handleDecline}
          disabled={phase === 'declining'}
          class="rounded-md bg-danger px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {m.invite_decline_confirm_button()}
        </button>
      </div>
    </div>
  </div>
{/if}
