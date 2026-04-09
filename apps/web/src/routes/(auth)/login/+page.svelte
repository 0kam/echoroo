<script lang="ts">
  /**
   * Login page
   */

  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { login } from '$lib/api/auth';
  import { authStore } from '$lib/stores/auth.svelte';
  import { ApiError } from '$lib/api/client';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import Captcha from '$lib/components/Captcha.svelte';
  import LanguageSwitcher from '$lib/components/ui/LanguageSwitcher.svelte';
  import DarkModeToggle from '$lib/components/ui/DarkModeToggle.svelte';
  import { onMount } from 'svelte';

  // Form state
  let email = $state('');
  let password = $state('');
  let captchaToken = $state<string | null>(null);
  let showCaptcha = $state(false);
  let failedAttempts = $state(0);

  // UI state
  let isSubmitting = $state(false);
  let error = $state<string | null>(null);

  // Captcha reference
  let captchaComponent: { reset: () => void } | undefined = $state(undefined);

  // Environment variables
  let turnstileSiteKey = $state('');

  onMount(() => {
    // Get Turnstile site key from environment
    // In production, this should be set via PUBLIC_TURNSTILE_SITE_KEY
    turnstileSiteKey = import.meta.env.PUBLIC_TURNSTILE_SITE_KEY || '1x00000000000000000000AA';

    // Check if user came from protected route
    const redirect = $page.url.searchParams.get('redirect');
    if (redirect) {
      error = m.auth_login_redirect_message();
    }
  });

  /**
   * Handle form submission
   */
  async function handleSubmit(e: Event) {
    e.preventDefault();
    error = null;

    // Validate form
    if (!email || !password) {
      error = m.error_required_email_password();
      return;
    }

    // Validate email format
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email)) {
      error = m.error_invalid_email();
      return;
    }

    // Validate password length
    if (password.length < 8) {
      error = m.error_password_too_short();
      return;
    }

    // Require CAPTCHA after 3 failed attempts
    if (showCaptcha && !captchaToken) {
      error = m.error_captcha_required();
      return;
    }

    isSubmitting = true;

    try {
      // Call login API
      const response = await login({
        email,
        password,
        captcha_token: captchaToken || undefined,
      });

      // Set access token and user data from login response
      const { apiClient } = await import('$lib/api/client');
      apiClient.setAccessToken(response.access_token);

      // Use user from login response if available, otherwise fetch
      if (response.user) {
        authStore.setUser(response.user);
      } else {
        const { getCurrentUser } = await import('$lib/api/auth');
        const user = await getCurrentUser();
        authStore.setUser(user);
      }

      // Reset failed attempts
      failedAttempts = 0;
      showCaptcha = false;

      // Redirect to dashboard or return URL
      const redirect = $page.url.searchParams.get('redirect');
      await goto(redirect ? localizeHref(redirect) : localizeHref('/dashboard'));
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;

        // Increment failed attempts
        failedAttempts++;

        // Show CAPTCHA after 3 failed attempts
        if (failedAttempts >= 3) {
          showCaptcha = true;
        }

        // Reset CAPTCHA if shown
        if (showCaptcha && captchaComponent) {
          captchaComponent.reset();
          captchaToken = null;
        }
      } else {
        error = m.error_unexpected();
      }
    } finally {
      isSubmitting = false;
    }
  }

  /**
   * Handle CAPTCHA verification
   */
  function handleCaptchaVerify(token: string) {
    captchaToken = token;
  }

  /**
   * Handle CAPTCHA error
   */
  function handleCaptchaError() {
    captchaToken = null;
    error = m.error_captcha_failed();
  }

  /**
   * Handle CAPTCHA expiry
   */
  function handleCaptchaExpire() {
    captchaToken = null;
  }
</script>

<svelte:head>
  <title>{m.auth_page_title()}</title>
</svelte:head>

<div class="flex min-h-screen items-center justify-center bg-stone-50 px-4 py-12 sm:px-6 lg:px-8">
  <div class="w-full max-w-md space-y-8">
    <!-- Language switcher and dark mode toggle -->
    <div class="flex justify-end gap-1">
      <DarkModeToggle />
      <LanguageSwitcher />
    </div>

    <!-- Header -->
    <div class="flex flex-col items-center">
      <img src="/echoroo.png" alt="Echoroo" class="h-16 w-auto mb-4" />
      <h2 class="text-center text-3xl font-extrabold text-stone-900">
        {m.auth_login_title()}
      </h2>
      <p class="mt-2 text-center text-sm text-stone-600">
        {m.auth_login_subtitle()}
      </p>
    </div>

    <!-- Login Form -->
    <form class="mt-8 space-y-6" onsubmit={handleSubmit}>
      <div class="space-y-4 rounded-md shadow-sm">
        <!-- Email Input -->
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

        <!-- Password Input -->
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

      <!-- CAPTCHA (shown after 3 failed attempts) -->
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

      <!-- Error Message -->
      {#if error}
        <div class="rounded-md bg-danger-light p-4" role="alert">
          <div class="flex">
            <div class="flex-shrink-0">
              <svg
                class="h-5 w-5 text-danger"
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 20 20"
                fill="currentColor"
                aria-hidden="true"
              >
                <path
                  fill-rule="evenodd"
                  d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
                  clip-rule="evenodd"
                />
              </svg>
            </div>
            <div class="ml-3">
              <p class="text-sm font-medium text-danger">{error}</p>
            </div>
          </div>
        </div>
      {/if}

      <!-- Forgot Password Link -->
      <div class="flex items-center justify-end">
        <div class="text-sm">
          <a href={localizeHref('/forgot-password')} class="font-medium text-primary-600 hover:text-primary-500">
            {m.auth_login_forgot_password()}
          </a>
        </div>
      </div>

      <!-- Submit Button -->
      <div>
        <button
          type="submit"
          disabled={isSubmitting}
          class="group relative flex w-full justify-center rounded-md border border-transparent bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:bg-stone-400 disabled:cursor-not-allowed dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
        >
          {#if isSubmitting}
            <span class="flex items-center">
              <svg
                class="mr-2 h-4 w-4 animate-spin"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
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
              {m.auth_login_submitting()}
            </span>
          {:else}
            {m.auth_login_submit()}
          {/if}
        </button>
      </div>

      <!-- Register Link -->
      <div class="text-center text-sm">
        <span class="text-stone-600">{m.auth_login_no_account()}</span>
        <a href={localizeHref('/register')} class="ml-1 font-medium text-primary-600 hover:text-primary-500">
          {m.auth_login_register_link()}
        </a>
      </div>
    </form>
  </div>
</div>
