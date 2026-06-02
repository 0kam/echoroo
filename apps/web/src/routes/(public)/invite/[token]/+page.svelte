<script lang="ts">
  /**
   * Invitation landing page — spec/011 US2 public invite flow (T220).
   *
   * URL shape: ``/invite/{signed_token}`` (lives under ``(public)`` so it is
   * reachable by anonymous visitors with NO auth-guard redirect — the signed
   * token is the credential and must never be bounced through
   * ``/login?redirect=...``).
   *
   * Flow
   * ----
   *   loading
   *     → resolveInvitation(token)                       (GET resolver)
   *         → is_logged_in = false → ``signup``          (new-user branch)
   *         → is_logged_in = true  → ``confirm``         (existing-user branch)
   *     → acceptInvitation(token, payload)               (POST accept)
   *         → new-user: backend set HttpOnly session cookies on the 201;
   *           the body has NO access_token, so hydrate via
   *           authStore.initialize() (refresh → /users/me → setUser).
   *         → strip the token from the URL via history.replaceState BEFORE
   *           any navigation, then land in the project.
   *
   * Security
   * --------
   *   - The token NEVER leaks: the page stays under ``(public)``; there is no
   *     ``goto('/login?redirect=/invite/...')``; ``history.replaceState``
   *     removes the token from the URL/history before navigating post-accept.
   *   - The client-generated TOTP secret is NEVER logged.
   *   - The bound email is rendered read-only (and handled gracefully when
   *     ``null`` for a wrong-account authenticated caller).
   */

  import { browser } from '$app/environment';
  import { goto } from '$app/navigation';
  import { ApiError } from '$lib/api/client';
  import {
    resolveInvitation,
    acceptInvitation,
    type InvitationContextResponse,
    type InvitationAcceptResponse,
  } from '$lib/api/web-auth';
  import { authStore } from '$lib/stores/auth.svelte';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import { generateTotpEnrollment, totpQrDataUrl } from '$lib/utils/totpEnroll';
  import DarkModeToggle from '$lib/components/ui/DarkModeToggle.svelte';
  import LanguageSwitcher from '$lib/components/ui/LanguageSwitcher.svelte';

  /** Page server-load output ({ token, projectId }). */
  let { data } = $props();
  const token = $derived(data.token);

  type Phase = 'loading' | 'signup' | 'confirm' | 'submitting' | 'success' | 'error';

  let phase = $state<Phase>('loading');
  let ctx = $state<InvitationContextResponse | null>(null);
  let result = $state<InvitationAcceptResponse | null>(null);
  let errorKey = $state<string | null>(null);

  // --- new-user signup form state ---
  let password = $state('');
  let totpSecret = $state(''); // client-generated; NEVER logged
  let totpQr = $state('');
  let totpCode = $state('');
  let secretCopied = $state(false);
  let fieldErrors = $state<{ password?: boolean; totpCode?: boolean }>({});

  /** Display label for the role/kind ("Member", "Trusted", ...). */
  const roleLabel = $derived(ctx?.role ?? ctx?.kind ?? '');

  // Resolve the invitation on mount (browser-only — never SSR; the token
  // must not be resolved server-side where it could surface in logs).
  $effect(() => {
    if (!browser) return;
    void load();
  });

  async function load(): Promise<void> {
    phase = 'loading';
    errorKey = null;
    try {
      const resolved = await resolveInvitation(token);
      ctx = resolved;
      if (resolved.is_logged_in) {
        phase = 'confirm';
      } else {
        // New-user signup branch: client-generate a TOTP secret bound to the
        // invitee email and render the QR. bound_email is always present for
        // an anonymous caller.
        const email = resolved.bound_email ?? '';
        const { secret, provisioningUri } = generateTotpEnrollment(email);
        totpSecret = secret;
        totpQr = await totpQrDataUrl(provisioningUri);
        phase = 'signup';
      }
    } catch (err) {
      errorKey = mapError(err);
      phase = 'error';
    }
  }

  // ---- new-user signup submit ----
  async function submitSignup(e: Event): Promise<void> {
    e.preventDefault();
    fieldErrors = {};
    errorKey = null;
    if (password.length < 12) {
      fieldErrors.password = true;
      errorKey = 'invite_signup_password_invalid';
      return;
    }
    const code = totpCode.trim().replace(/\s+/g, '');
    if (code.length !== 6) {
      fieldErrors.totpCode = true;
      errorKey = 'invite_signup_totp_invalid';
      return;
    }
    if (!ctx?.bound_email) {
      errorKey = 'invite_landing_generic_error';
      phase = 'error';
      return;
    }
    phase = 'submitting';
    try {
      const res = await acceptInvitation(token, {
        email: ctx.bound_email,
        password,
        totp_enrollment: { totp_secret_signed: totpSecret, totp_initial_code: code },
      });
      await afterAccept(res, true);
    } catch (err) {
      errorKey = mapError(err);
      // 422 (password/TOTP) returns to the form rather than a terminal error.
      if (err instanceof ApiError && err.status === 422) {
        if (errorKey === 'invite_signup_totp_invalid') fieldErrors.totpCode = true;
        if (errorKey === 'invite_signup_password_invalid') fieldErrors.password = true;
        phase = 'signup';
      } else {
        phase = 'error';
      }
    }
  }

  // ---- existing-user confirm submit ----
  async function submitConfirm(e: Event): Promise<void> {
    e.preventDefault();
    errorKey = null;
    phase = 'submitting';
    try {
      const res = await acceptInvitation(token, { accept: true });
      await afterAccept(res, false);
    } catch (err) {
      errorKey = mapError(err);
      phase = 'error';
    }
  }

  /**
   * Shared post-accept handling.
   *
   * For the new-user branch the backend established the session server-side
   * (HttpOnly cookies on the 201) but returned NO access_token in the body,
   * so we hydrate the in-memory token + user via authStore.initialize().
   * We strip the token from the URL FIRST so it can never leak — even if
   * initialize() were to navigate (it won't for a fresh, valid session).
   */
  async function afterAccept(res: InvitationAcceptResponse, isNewUser: boolean): Promise<void> {
    result = res;
    if (browser && typeof history !== 'undefined') {
      try {
        history.replaceState(history.state, '', localizeHref('/dashboard'));
      } catch {
        // replaceState is best-effort; the success panel + Continue button
        // below still work without it.
      }
    }
    if (isNewUser) {
      try {
        await authStore.initialize({ silent: false });
      } catch {
        // The session cookie is present; if hydration hiccups, the project
        // page's own guard recovers on navigation.
      }
    }
    phase = 'success';
  }

  function continueToProject(): void {
    if (!result) return;
    void goto(localizeHref(`/projects/${result.project_id}`));
  }

  function copySecret(): void {
    if (!totpSecret || typeof navigator === 'undefined') return;
    navigator.clipboard?.writeText(totpSecret).then(() => {
      secretCopied = true;
      setTimeout(() => (secretCopied = false), 2000);
    });
  }

  /** Map a thrown error to an i18n key. */
  function mapError(err: unknown): string {
    if (err instanceof ApiError) {
      const code = err.code;
      if (err.status === 404) return 'invite_landing_invitation_not_found';
      if (err.status === 409 && code === 'ERR_ALREADY_MEMBER') {
        return 'invite_landing_already_member';
      }
      if (err.status === 409) return 'invite_landing_conflict';
      if (err.status === 429) return 'invite_landing_rate_limited';
      if (err.status === 422) {
        return code === 'ERR_TOTP_ENROLLMENT_INVALID'
          ? 'invite_signup_totp_invalid'
          : 'invite_signup_password_invalid';
      }
    }
    return 'invite_landing_generic_error';
  }

  /** Resolve an i18n key to its localised string (no dynamic m[...] lookup). */
  function tr(key: string): string {
    switch (key) {
      case 'invite_landing_invitation_not_found':
        return m.invite_landing_invitation_not_found();
      case 'invite_landing_already_member':
        return m.invite_landing_already_member();
      case 'invite_landing_conflict':
        return m.invite_landing_conflict();
      case 'invite_landing_rate_limited':
        return m.invite_landing_rate_limited();
      case 'invite_signup_totp_invalid':
        return m.invite_signup_totp_invalid();
      case 'invite_signup_password_invalid':
        return m.invite_signup_password_invalid();
      default:
        return m.invite_landing_generic_error();
    }
  }
</script>

<svelte:head>
  <title>{m.invite_landing_title()} - Echoroo</title>
</svelte:head>

<div class="flex min-h-screen items-center justify-center bg-stone-50 px-4 py-12 sm:px-6 lg:px-8">
  <div class="w-full max-w-md space-y-8" data-testid="invite-landing-page">
    <div class="flex justify-end gap-1">
      <DarkModeToggle />
      <LanguageSwitcher />
    </div>

    <div class="flex flex-col items-center">
      <img src="/echoroo.png" alt="Echoroo" class="mb-4 h-16 w-auto" />
      <h2 class="text-center text-3xl font-extrabold text-stone-900">
        {m.invite_landing_title()}
      </h2>
    </div>

    {#if phase === 'loading'}
      <div class="flex items-center justify-center gap-3 py-6" data-testid="invite-landing-loading">
        <svg
          class="h-5 w-5 animate-spin text-primary-600"
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
        <p class="text-sm text-stone-700">{m.invite_landing_loading()}</p>
      </div>
    {:else if phase === 'signup'}
      <!-- New-user signup branch: read-only email + password + TOTP enroll -->
      <p class="text-sm text-stone-600" data-testid="invite-signup-intro">
        {m.invite_signup_intro({ project: ctx?.project_name ?? '', role: roleLabel })}
      </p>

      <form class="space-y-6" onsubmit={submitSignup} data-testid="invite-signup-form">
        <div class="space-y-4">
          <div>
            <label for="invite-email" class="block text-sm font-medium text-stone-700">
              {m.invite_signup_email_label()}
            </label>
            <input
              id="invite-email"
              type="email"
              value={ctx?.bound_email ?? ''}
              readonly
              data-testid="invite-signup-email"
              class="mt-1 block w-full appearance-none rounded-md border border-stone-300 bg-stone-100 px-3 py-2 text-stone-900 sm:text-sm"
            />
          </div>

          <div>
            <label for="invite-password" class="block text-sm font-medium text-stone-700">
              {m.invite_signup_password_label()}
            </label>
            <input
              id="invite-password"
              type="password"
              autocomplete="new-password"
              required
              bind:value={password}
              data-testid="invite-signup-password"
              class="mt-1 block w-full appearance-none rounded-md border px-3 py-2 text-stone-900 placeholder-stone-500 focus:z-10 focus:border-primary-500 focus:outline-none focus:ring-primary-500 sm:text-sm"
              class:border-danger={fieldErrors.password}
              class:border-stone-300={!fieldErrors.password}
            />
            <p class="mt-1 text-xs text-stone-500">{m.invite_signup_password_hint()}</p>
          </div>
        </div>

        <!-- TOTP enrollment (QR + manual secret + 6-digit code) -->
        <div class="rounded-md border border-card bg-surface-card p-4">
          <p class="text-sm text-stone-700">{m.invite_signup_totp_intro()}</p>

          <div class="mt-4 flex flex-col items-center gap-4 sm:flex-row sm:items-start">
            {#if totpQr}
              <img
                src={totpQr}
                alt="2FA QR code"
                data-testid="invite-signup-qr"
                class="h-60 w-60 rounded border border-stone-200 bg-white p-2"
              />
            {/if}

            <div class="flex-1">
              <p class="text-xs font-medium text-stone-600">
                {m.invite_signup_totp_secret_label()}
              </p>
              <code
                class="mt-2 block break-all rounded bg-stone-100 p-2 font-mono text-sm text-stone-800"
                data-testid="invite-signup-secret"
              >
                {totpSecret}
              </code>
              <button
                type="button"
                onclick={copySecret}
                class="mt-2 rounded px-2 py-1 text-xs font-medium text-primary-600 ring-1 ring-primary-200 hover:bg-primary-50"
              >
                {secretCopied
                  ? m.auth_two_factor_secret_copied()
                  : m.auth_two_factor_secret_copy()}
              </button>
            </div>
          </div>

          <div class="mt-4">
            <label for="invite-totp-code" class="block text-sm font-medium text-stone-700">
              {m.invite_signup_totp_code_label()}
            </label>
            <input
              id="invite-totp-code"
              type="text"
              inputmode="numeric"
              autocomplete="one-time-code"
              maxlength="6"
              required
              bind:value={totpCode}
              data-testid="invite-signup-code"
              class="mt-1 block w-full appearance-none rounded-md border px-3 py-2 text-center font-mono text-lg tracking-widest text-stone-900 placeholder-stone-400 focus:border-primary-500 focus:outline-none focus:ring-primary-500 sm:text-sm"
              class:border-danger={fieldErrors.totpCode}
              class:border-stone-300={!fieldErrors.totpCode}
            />
          </div>
        </div>

        {#if errorKey}
          <div class="rounded-md bg-danger-light p-4" role="alert" data-testid="invite-signup-error">
            <p class="text-sm font-medium text-danger">{tr(errorKey)}</p>
          </div>
        {/if}

        <button
          type="submit"
          data-testid="invite-signup-submit"
          class="group relative flex w-full justify-center rounded-md border border-transparent bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:bg-stone-400 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
        >
          {m.invite_signup_submit()}
        </button>
      </form>
    {:else if phase === 'confirm'}
      <!-- Existing-user confirm branch -->
      <p class="text-sm text-stone-600" data-testid="invite-confirm-intro">
        {m.invite_confirm_intro({ project: ctx?.project_name ?? '', role: roleLabel })}
      </p>

      {#if ctx && ctx.is_logged_in && !ctx.authenticated_email_matches_bound}
        <div class="rounded-md bg-warning/10 p-3" role="alert" data-testid="invite-confirm-mismatch">
          <p class="text-sm text-stone-800">{m.invite_confirm_email_mismatch()}</p>
        </div>
      {/if}

      <form class="space-y-6" onsubmit={submitConfirm}>
        <button
          type="submit"
          data-testid="invite-confirm-submit"
          class="group relative flex w-full justify-center rounded-md border border-transparent bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:bg-stone-400 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
        >
          {m.invite_confirm_accept()}
        </button>
      </form>
    {:else if phase === 'submitting'}
      <div class="flex items-center justify-center gap-3 py-6" data-testid="invite-submitting">
        <svg
          class="h-5 w-5 animate-spin text-primary-600"
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
        <p class="text-sm text-stone-700">{m.invite_landing_loading()}</p>
      </div>
    {:else if phase === 'success' && result}
      <div class="rounded-md bg-success-light p-6" role="status" data-testid="invite-landing-success">
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
    {:else if phase === 'error' && errorKey}
      <div
        class="rounded-md bg-danger-light p-4"
        role="alert"
        data-testid="invite-landing-error"
        data-error-key={errorKey}
      >
        <p class="text-sm font-medium text-danger">{tr(errorKey)}</p>
      </div>
    {/if}
  </div>
</div>
