<script lang="ts">
  /**
   * Registration page (web-auth, Phase 4 redesign).
   *
   * Posts to `/web-api/v1/auth/register`. Does NOT log the user in — the
   * backend always requires a separate login + 2FA setup on first sign-in.
   */

  import { goto } from '$app/navigation';
  import { registerUser, WebAuthError } from '$lib/api/web-auth';
  import { ApiError } from '$lib/api/client';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import LanguageSwitcher from '$lib/components/ui/LanguageSwitcher.svelte';
  import DarkModeToggle from '$lib/components/ui/DarkModeToggle.svelte';
  import { onMount } from 'svelte';

  // Form state
  let email = $state('');
  let password = $state('');
  let confirmPassword = $state('');
  let displayName = $state('');
  let timezone = $state('UTC');

  // UI state
  let isSubmitting = $state(false);
  let error = $state<string | null>(null);
  let fieldErrors = $state<Record<string, string>>({});

  onMount(() => {
    // Auto-detect timezone from the browser. Fall back to UTC if unavailable.
    try {
      const detected = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (detected) timezone = detected;
    } catch {
      timezone = 'UTC';
    }
  });

  /**
   * Validate form fields client-side. The backend re-validates everything,
   * but client-side checks reduce round-trips for obvious mistakes.
   */
  function validateForm(): boolean {
    fieldErrors = {};
    error = null;

    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!email) {
      fieldErrors.email = m.error_email_required();
    } else if (!emailRegex.test(email)) {
      fieldErrors.email = m.error_invalid_email();
    }

    if (!password) {
      fieldErrors.password = m.error_password_required();
    } else if (password.length < 8) {
      fieldErrors.password = m.error_password_too_short();
    } else if (!/(?=.*[a-z])(?=.*[A-Z])(?=.*\d)/.test(password)) {
      fieldErrors.password = m.error_password_complexity();
    }

    if (!confirmPassword) {
      fieldErrors.confirmPassword = m.error_confirm_password_required();
    } else if (password !== confirmPassword) {
      fieldErrors.confirmPassword = m.error_passwords_do_not_match();
    }

    if (displayName && displayName.length > 100) {
      fieldErrors.displayName = m.error_display_name_too_long();
    }

    return Object.keys(fieldErrors).length === 0;
  }

  async function handleSubmit(e: Event) {
    e.preventDefault();
    if (!validateForm()) return;

    isSubmitting = true;
    error = null;

    try {
      await registerUser({
        email,
        password,
        display_name: displayName || undefined,
        timezone,
      });

      // Backend does NOT log the user in. Direct them to login with a hint
      // that they must set up 2FA on first sign-in.
      await goto(
        localizeHref(`/login?registered=true&email=${encodeURIComponent(email)}`),
      );
    } catch (err) {
      if (err instanceof WebAuthError) {
        if (err.status === 422) {
          // Password policy / validation error — surface the specific reason.
          error = err.detail || err.message;
        } else if (err.status === 409) {
          // Generic message to avoid email-enumeration.
          error = m.error_unexpected();
        } else {
          error = err.detail || err.message;
        }
      } else if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = m.error_unexpected();
      }
    } finally {
      isSubmitting = false;
    }
  }
</script>

<svelte:head>
  <title>{m.auth_register_page_title()}</title>
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
        {m.auth_register_title()}
      </h2>
      <p class="mt-2 text-center text-sm text-stone-600">
        {m.auth_register_subtitle()}
      </p>
    </div>

    <!-- 2FA enrollment notice (FR-069) -->
    <div
      class="rounded-md border border-info/30 bg-info/10 p-3 text-sm text-stone-700"
      role="note"
      data-testid="register-2fa-notice"
    >
      {m.auth_register_two_factor_required_notice()}
    </div>

    <form class="mt-8 space-y-6" onsubmit={handleSubmit}>
      <div class="space-y-4 rounded-md shadow-sm">
        <div>
          <label for="email" class="block text-sm font-medium text-stone-700">
            {m.auth_register_email_label()} <span class="text-danger">*</span>
          </label>
          <input
            id="email"
            name="email"
            type="email"
            autocomplete="email"
            required
            bind:value={email}
            disabled={isSubmitting}
            class="mt-1 block w-full appearance-none rounded-md border border-stone-300 px-3 py-2 text-stone-900 placeholder-stone-500 focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:bg-stone-100 disabled:cursor-not-allowed sm:text-sm"
            class:border-danger={fieldErrors.email}
            placeholder="you@example.com"
          />
          {#if fieldErrors.email}
            <p class="mt-1 text-sm text-danger">{fieldErrors.email}</p>
          {/if}
        </div>

        <div>
          <label for="displayName" class="block text-sm font-medium text-stone-700">
            {m.auth_register_display_name_label()}
          </label>
          <input
            id="displayName"
            name="displayName"
            type="text"
            autocomplete="name"
            bind:value={displayName}
            disabled={isSubmitting}
            class="mt-1 block w-full appearance-none rounded-md border border-stone-300 px-3 py-2 text-stone-900 placeholder-stone-500 focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:bg-stone-100 disabled:cursor-not-allowed sm:text-sm"
            class:border-danger={fieldErrors.displayName}
            placeholder={m.auth_register_display_name_placeholder()}
          />
          {#if fieldErrors.displayName}
            <p class="mt-1 text-sm text-danger">{fieldErrors.displayName}</p>
          {/if}
        </div>

        <div>
          <label for="password" class="block text-sm font-medium text-stone-700">
            {m.auth_register_password_label()} <span class="text-danger">*</span>
          </label>
          <input
            id="password"
            name="password"
            type="password"
            autocomplete="new-password"
            required
            bind:value={password}
            disabled={isSubmitting}
            class="mt-1 block w-full appearance-none rounded-md border border-stone-300 px-3 py-2 text-stone-900 placeholder-stone-500 focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:bg-stone-100 disabled:cursor-not-allowed sm:text-sm"
            class:border-danger={fieldErrors.password}
            placeholder={m.auth_register_password_placeholder()}
          />
          {#if fieldErrors.password}
            <p class="mt-1 text-sm text-danger">{fieldErrors.password}</p>
          {:else}
            <p class="mt-1 text-xs text-stone-500">
              {m.auth_register_password_hint()}
            </p>
          {/if}
        </div>

        <div>
          <label for="confirmPassword" class="block text-sm font-medium text-stone-700">
            {m.auth_register_confirm_password_label()} <span class="text-danger">*</span>
          </label>
          <input
            id="confirmPassword"
            name="confirmPassword"
            type="password"
            autocomplete="new-password"
            required
            bind:value={confirmPassword}
            disabled={isSubmitting}
            class="mt-1 block w-full appearance-none rounded-md border border-stone-300 px-3 py-2 text-stone-900 placeholder-stone-500 focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:bg-stone-100 disabled:cursor-not-allowed sm:text-sm"
            class:border-danger={fieldErrors.confirmPassword}
            placeholder={m.auth_register_confirm_password_placeholder()}
          />
          {#if fieldErrors.confirmPassword}
            <p class="mt-1 text-sm text-danger">{fieldErrors.confirmPassword}</p>
          {/if}
        </div>
      </div>

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
              {m.auth_register_submitting()}
            </span>
          {:else}
            {m.auth_register_submit()}
          {/if}
        </button>
      </div>

      <div class="text-center text-sm">
        <span class="text-stone-600">{m.auth_register_already_have_account()}</span>
        <a href={localizeHref('/login')} class="ml-1 font-medium text-primary-600 hover:text-primary-500">
          {m.auth_register_login_link()}
        </a>
      </div>
    </form>
  </div>
</div>
