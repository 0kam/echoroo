<script lang="ts">
  /**
   * Login page (web-auth, Phase 4 redesign).
   *
   * Two-step flow:
   *   1. Submit email + password → `/web-api/v1/auth/login`.
   *      Backend returns `{login_state, interim_token}` — NO session cookie.
   *   2a. `login_state == "2fa_setup_required"` → redirect to /2fa-setup.
   *   2b. `login_state == "2fa_required"` → render TOTP / backup-code form.
   *       Submitting calls `/2fa/challenge`, which sets the session cookies
   *       and returns the access token.
   */

  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import {
    challengeTwoFactor,
    loginUser,
    WebAuthError,
    type TwoFactorMethod,
  } from '$lib/api/web-auth';
  import { authStore } from '$lib/stores/auth.svelte';
  import { ApiError, apiClient } from '$lib/api/client';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import LanguageSwitcher from '$lib/components/ui/LanguageSwitcher.svelte';
  import DarkModeToggle from '$lib/components/ui/DarkModeToggle.svelte';
  import { onMount } from 'svelte';
  import type { User } from '$lib/types';

  // Step tracking
  type Step = 'credentials' | 'two_factor';
  let step = $state<Step>('credentials');

  // Step 1 state
  let email = $state('');
  let password = $state('');

  // Step 2 state
  let interimToken = $state<string | null>(null);
  let twoFactorMethod = $state<TwoFactorMethod>('totp');
  let twoFactorCode = $state('');
  let trustDevice = $state(false);

  // UI state
  let isSubmitting = $state(false);
  let error = $state<string | null>(null);
  let successNotice = $state<string | null>(null);

  async function completeLogin(accessToken: string) {
    apiClient.setAccessToken(accessToken);

    // Fetch the current user (cookie + access token already set by server).
    // Use the BFF mirror at ``/web-api/v1/users/me`` so the session
    // cookie alone authenticates the request — the legacy Bearer
    // path 401-ed here and bounced the user back to /login right
    // after a successful 2FA verify.
    try {
      const user = await apiClient.get<User>('/web-api/v1/users/me');
      authStore.setUser(user);
    } catch (err) {
      // spec/011 US4 forced-change routing fix: when an admin has reset a
      // user's password the forced-change middleware locks `/users/me` with
      // ``423 ERR_PASSWORD_CHANGE_REQUIRED``. The login itself succeeded and
      // the in-memory access token IS valid (only `/users/me` is locked), so
      // we must NOT fall through to `/dashboard` — the (app) forced-change
      // guard relies on `authStore.user.must_change_password`, but
      // `authStore.user` is null here, so the guard never fires and the user
      // is stranded on a blank dashboard shell. Route directly to
      // `/change-password`, keeping the access token intact so that screen can
      // call the authenticated change-password endpoint.
      if (
        err instanceof ApiError &&
        (err.status === 423 || err.code === 'ERR_PASSWORD_CHANGE_REQUIRED')
      ) {
        await goto(localizeHref('/change-password'));
        return;
      }
      // Any other failure: the new web-auth backend may expose user data via a
      // different endpoint. We still consider login successful; the dashboard
      // will retry via authStore.initialize().
    }

    const redirect = $page.url.searchParams.get('redirect');
    await goto(redirect ? localizeHref(redirect) : localizeHref('/dashboard'));
  }

  onMount(() => {
    const redirect = $page.url.searchParams.get('redirect');
    if (redirect) {
      error = m.auth_login_redirect_message();
    }

    if ($page.url.searchParams.get('registered') === 'true') {
      successNotice = m.auth_register_success_redirect();
      const fromQuery = $page.url.searchParams.get('email');
      if (fromQuery) email = fromQuery;
    }
  });

  // ---------- Step 1: credentials ----------

  function validateCredentials(): boolean {
    error = null;
    if (!email || !password) {
      error = m.error_required_email_password();
      return false;
    }
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email)) {
      error = m.error_invalid_email();
      return false;
    }
    if (password.length < 8) {
      error = m.error_password_too_short();
      return false;
    }
    return true;
  }

  async function handleCredentialsSubmit(e: Event) {
    e.preventDefault();
    if (!validateCredentials()) return;

    isSubmitting = true;
    successNotice = null;

    try {
      const result = await loginUser({ email, password });

      if (result.login_state === 'complete') {
        await completeLogin(result.access_token);
        return;
      }

      if (result.login_state === '2fa_setup_required') {
        // Hand the interim_token to the setup page via session storage so it
        // is not exposed in the URL bar / browser history. The setup page
        // lives under (auth) (NOT (app)) so unauthenticated users can reach
        // it — at this point the user has not yet established a session.
        if (typeof window !== 'undefined' && result.interim_token) {
          window.sessionStorage.setItem('echoroo.interim_token', result.interim_token);
        }
        await goto(localizeHref('/2fa-setup'));
        return;
      }

      // 2fa_required: switch UI to the second step
      interimToken = result.interim_token;
      twoFactorMethod = 'totp';
      twoFactorCode = '';
      trustDevice = false;
      step = 'two_factor';
      error = null;
    } catch (err) {
      handleError(err);
    } finally {
      isSubmitting = false;
    }
  }

  // ---------- Step 2: 2FA challenge ----------

  function validateTwoFactor(): boolean {
    error = null;
    if (!twoFactorCode.trim()) {
      error = m.auth_two_factor_invalid_code();
      return false;
    }
    return true;
  }

  async function handleTwoFactorSubmit(e: Event) {
    e.preventDefault();
    if (!validateTwoFactor()) return;
    if (!interimToken) {
      // Should not normally happen — recover by sending user back to step 1.
      error = m.auth_two_factor_missing_interim_token();
      step = 'credentials';
      return;
    }

    isSubmitting = true;

    try {
      const result = await challengeTwoFactor(
        interimToken,
        twoFactorMethod,
        twoFactorCode.trim(),
        { trustDevice },
      );

      await completeLogin(result.access_token);
    } catch (err) {
      handleError(err);
      twoFactorCode = '';
    } finally {
      isSubmitting = false;
    }
  }

  function switchToBackupCode() {
    twoFactorMethod = 'backup_code';
    twoFactorCode = '';
    error = null;
  }

  function switchToTotp() {
    twoFactorMethod = 'totp';
    twoFactorCode = '';
    error = null;
  }

  function handleError(err: unknown) {
    if (err instanceof WebAuthError) {
      if (err.status === 429) {
        const seconds = err.retryAfterSeconds() ?? 60;
        error = m.auth_two_factor_rate_limited({ seconds: String(seconds) });
      } else if (err.status === 423) {
        const seconds = err.retryAfterSeconds() ?? 900;
        error = m.auth_two_factor_locked({ seconds: String(seconds) });
      } else if (err.status === 401) {
        error =
          step === 'two_factor'
            ? m.auth_two_factor_invalid_code()
            : err.detail || err.message;
      } else {
        error = err.detail || err.message;
      }
    } else if (err instanceof ApiError) {
      error = err.detail || err.message;
    } else {
      error = m.error_unexpected();
    }
  }
</script>

<svelte:head>
  <title>{m.auth_page_title()}</title>
</svelte:head>

<div class="flex min-h-screen items-center justify-center bg-stone-50 px-4 py-12 sm:px-6 lg:px-8">
  <div class="w-full max-w-md space-y-8">
    <div class="flex justify-end gap-1">
      <DarkModeToggle />
      <LanguageSwitcher />
    </div>

    <div class="flex flex-col items-center">
      <img src="/echoroo.png" alt="Echoroo" class="h-16 w-auto mb-4" />
      <h2 class="text-center text-3xl font-extrabold text-stone-900">
        {step === 'credentials' ? m.auth_login_title() : m.auth_two_factor_challenge_title()}
      </h2>
      <p class="mt-2 text-center text-sm text-stone-600">
        {#if step === 'credentials'}
          {m.auth_login_subtitle()}
        {:else if twoFactorMethod === 'totp'}
          {m.auth_two_factor_challenge_subtitle()}
        {:else}
          {m.auth_two_factor_challenge_subtitle_backup()}
        {/if}
      </p>
    </div>

    {#if successNotice}
      <div class="rounded-md bg-success-light p-3 text-sm text-success" role="status">
        {successNotice}
      </div>
    {/if}

    {#if step === 'credentials'}
      <!-- Step 1: email + password -->
      <form class="mt-8 space-y-6" onsubmit={handleCredentialsSubmit}>
        <div class="space-y-4 rounded-md shadow-sm">
          <div>
            <label for="email" class="sr-only">{m.auth_login_email_placeholder()}</label>
            <input
              id="email"
              name="email"
              type="email"
              autocomplete="email"
              required
              bind:value={email}
              disabled={isSubmitting}
              class="relative block w-full appearance-none rounded-md border border-stone-300 px-3 py-2 text-stone-900 placeholder-stone-500 focus:z-10 focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:bg-stone-100 disabled:cursor-not-allowed sm:text-sm"
              placeholder={m.auth_login_email_placeholder()}
            />
          </div>

          <div>
            <label for="password" class="sr-only">{m.auth_login_password_placeholder()}</label>
            <input
              id="password"
              name="password"
              type="password"
              autocomplete="current-password"
              required
              bind:value={password}
              disabled={isSubmitting}
              class="relative block w-full appearance-none rounded-md border border-stone-300 px-3 py-2 text-stone-900 placeholder-stone-500 focus:z-10 focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:bg-stone-100 disabled:cursor-not-allowed sm:text-sm"
              placeholder={m.auth_login_password_placeholder()}
            />
          </div>
        </div>

        {#if error}
          <div class="rounded-md bg-danger-light p-4" role="alert">
            <p class="text-sm font-medium text-danger">{error}</p>
          </div>
        {/if}

        <div>
          <button
            type="submit"
            disabled={isSubmitting}
            class="group relative flex w-full justify-center rounded-md border border-transparent bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:bg-stone-400 disabled:cursor-not-allowed dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
          >
            {#if isSubmitting}
              {m.auth_login_submitting()}
            {:else}
              {m.auth_login_submit()}
            {/if}
          </button>
        </div>

        <div class="text-center text-sm">
          <span class="text-stone-600">{m.auth_login_no_account()}</span>
          <a href={localizeHref('/register')} class="ml-1 font-medium text-primary-600 hover:text-primary-500">
            {m.auth_login_register_link()}
          </a>
        </div>
      </form>
    {:else}
      <!-- Step 2: TOTP / backup-code -->
      <form class="mt-8 space-y-6" onsubmit={handleTwoFactorSubmit} data-testid="two-factor-form">
        <div>
          <label for="twoFactorCode" class="block text-sm font-medium text-stone-700">
            {m.auth_two_factor_enter_code_label()}
          </label>
          <input
            id="twoFactorCode"
            name="twoFactorCode"
            type="text"
            inputmode={twoFactorMethod === 'totp' ? 'numeric' : 'text'}
            autocomplete="one-time-code"
            required
            bind:value={twoFactorCode}
            disabled={isSubmitting}
            data-testid="two-factor-code-input"
            class="mt-1 block w-full appearance-none rounded-md border border-stone-300 px-3 py-2 text-center font-mono text-lg tracking-widest text-stone-900 placeholder-stone-400 focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:bg-stone-100 disabled:cursor-not-allowed sm:text-sm"
            placeholder={m.auth_two_factor_enter_code_placeholder()}
          />
        </div>

        <label class="flex items-start gap-2 text-sm text-stone-700">
          <input
            type="checkbox"
            bind:checked={trustDevice}
            disabled={isSubmitting}
            data-testid="trust-device-checkbox"
            class="mt-1 h-4 w-4 rounded border-stone-300 text-primary-600 focus:ring-primary-500 disabled:cursor-not-allowed disabled:opacity-60"
          />
          <span>
            Trust this device for 30 days
          </span>
        </label>

        {#if error}
          <div class="rounded-md bg-danger-light p-4" role="alert" data-testid="two-factor-error">
            <p class="text-sm font-medium text-danger">{error}</p>
          </div>
        {/if}

        <div>
          <button
            type="submit"
            disabled={isSubmitting}
            data-testid="two-factor-submit"
            class="group relative flex w-full justify-center rounded-md border border-transparent bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:bg-stone-400 disabled:cursor-not-allowed dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
          >
            {isSubmitting
              ? m.auth_two_factor_challenge_submitting()
              : m.auth_two_factor_challenge_submit()}
          </button>
        </div>

        <div class="text-center text-sm">
          {#if twoFactorMethod === 'totp'}
            <button
              type="button"
              onclick={switchToBackupCode}
              class="font-medium text-primary-600 hover:text-primary-500"
              data-testid="use-backup-code"
            >
              {m.auth_two_factor_challenge_use_backup_code_link()}
            </button>
          {:else}
            <button
              type="button"
              onclick={switchToTotp}
              class="font-medium text-primary-600 hover:text-primary-500"
              data-testid="use-totp"
            >
              {m.auth_two_factor_challenge_use_totp_link()}
            </button>
          {/if}
        </div>
      </form>
    {/if}
  </div>
</div>
