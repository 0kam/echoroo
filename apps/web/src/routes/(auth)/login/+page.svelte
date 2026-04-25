<script lang="ts">
  /**
   * Login page (web-auth, Phase 4 redesign).
   *
   * Two-step flow:
   *   1. Submit email + password → `/web-api/v1/auth/login`.
   *      Backend returns `{login_state, interim_token}` — NO session cookie.
   *   2a. `login_state == "2fa_setup_required"` → redirect to /account/2fa.
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
    type LoginState,
    type TwoFactorMethod,
  } from '$lib/api/web-auth';
  import { authStore } from '$lib/stores/auth.svelte';
  import { ApiError, apiClient } from '$lib/api/client';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import Captcha from '$lib/components/Captcha.svelte';
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
  let captchaToken = $state<string | null>(null);
  let showCaptcha = $state(false);
  let failedAttempts = $state(0);

  // Step 2 state
  let interimToken = $state<string | null>(null);
  let twoFactorMethod = $state<TwoFactorMethod>('totp');
  let twoFactorCode = $state('');

  // UI state
  let isSubmitting = $state(false);
  let error = $state<string | null>(null);
  let successNotice = $state<string | null>(null);

  // Captcha reference
  let captchaComponent: { reset: () => void } | undefined = $state(undefined);
  let turnstileSiteKey = $state('');

  onMount(() => {
    turnstileSiteKey = import.meta.env.PUBLIC_TURNSTILE_SITE_KEY || '1x00000000000000000000AA';

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
    if (showCaptcha && !captchaToken) {
      error = m.error_captcha_required();
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
      const state: LoginState = result.login_state;

      if (state === '2fa_setup_required') {
        // Hand the interim_token to the setup page via session storage so it
        // is not exposed in the URL bar / browser history.
        if (typeof window !== 'undefined' && result.interim_token) {
          window.sessionStorage.setItem('echoroo.interim_token', result.interim_token);
        }
        await goto(localizeHref('/account/2fa?mode=setup'));
        return;
      }

      // 2fa_required: switch UI to the second step
      interimToken = result.interim_token;
      twoFactorMethod = 'totp';
      twoFactorCode = '';
      step = 'two_factor';
      error = null;
      failedAttempts = 0;
      showCaptcha = false;
    } catch (err) {
      handleError(err);

      failedAttempts++;
      if (failedAttempts >= 3) {
        showCaptcha = true;
      }
      if (showCaptcha && captchaComponent) {
        captchaComponent.reset();
        captchaToken = null;
      }
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
      );

      apiClient.setAccessToken(result.access_token);

      // Fetch the current user (cookie + access token already set by server)
      try {
        const user = await apiClient.get<User>('/api/v1/users/me');
        authStore.setUser(user);
      } catch {
        // The new web-auth backend may expose user data via a different
        // endpoint. If /users/me fails we still consider login successful;
        // the dashboard will retry via authStore.initialize().
      }

      const redirect = $page.url.searchParams.get('redirect');
      await goto(redirect ? localizeHref(redirect) : localizeHref('/dashboard'));
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

  function handleCaptchaVerify(token: string) {
    captchaToken = token;
  }

  function handleCaptchaError() {
    captchaToken = null;
    error = m.error_captcha_failed();
  }

  function handleCaptchaExpire() {
    captchaToken = null;
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

        {#if showCaptcha}
          <div class="mt-4">
            <Captcha
              bind:this={captchaComponent}
              siteKey={turnstileSiteKey}
              onVerify={handleCaptchaVerify}
              onError={handleCaptchaError}
              onExpire={handleCaptchaExpire}
            />
          </div>
        {/if}

        {#if error}
          <div class="rounded-md bg-danger-light p-4" role="alert">
            <p class="text-sm font-medium text-danger">{error}</p>
          </div>
        {/if}

        <div class="flex items-center justify-end">
          <div class="text-sm">
            <a href={localizeHref('/forgot-password')} class="font-medium text-primary-600 hover:text-primary-500">
              {m.auth_login_forgot_password()}
            </a>
          </div>
        </div>

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
