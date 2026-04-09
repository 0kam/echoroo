<script lang="ts">
  /**
   * Forgot password page
   */

  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import { requestPasswordReset } from '$lib/api/auth';
  import LanguageSwitcher from '$lib/components/ui/LanguageSwitcher.svelte';
  import DarkModeToggle from '$lib/components/ui/DarkModeToggle.svelte';

  // Form state
  let email = $state('');

  // UI state
  let isSubmitting = $state(false);
  let isSubmitted = $state(false);
  let error = $state<string | null>(null);

  /**
   * Handle form submission
   */
  async function handleSubmit(e: Event) {
    e.preventDefault();
    error = null;

    // Validate email
    if (!email) {
      error = m.error_email_required_field();
      return;
    }

    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email)) {
      error = m.error_invalid_email();
      return;
    }

    isSubmitting = true;

    try {
      await requestPasswordReset(email);
      isSubmitted = true;
    } catch {
      // Always show success message for security reasons
      // Don't reveal whether the email exists in the system
      isSubmitted = true;
    } finally {
      isSubmitting = false;
    }
  }
</script>

<svelte:head>
  <title>{m.auth_forgot_password_page_title()}</title>
</svelte:head>

<div class="flex min-h-screen items-center justify-center bg-stone-50 px-4 py-12 sm:px-6 lg:px-8">
  <div class="w-full max-w-md space-y-8">
    <!-- Language switcher and dark mode toggle -->
    <div class="flex justify-end gap-1">
      <DarkModeToggle />
      <LanguageSwitcher />
    </div>

    <!-- Header -->
    <div>
      <h2 class="mt-6 text-center text-3xl font-extrabold text-stone-900">
        {m.auth_forgot_password_title()}
      </h2>
      <p class="mt-2 text-center text-sm text-stone-600">
        {m.auth_forgot_password_subtitle()}
      </p>
    </div>

    {#if isSubmitted}
      <!-- Success Message -->
      <div class="rounded-lg bg-surface-card p-8 shadow-md">
        <div class="text-center">
          <div class="mb-4 flex justify-center">
            <svg
              class="h-12 w-12 text-green-600"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
              />
            </svg>
          </div>
          <h3 class="text-lg font-medium text-stone-900">{m.auth_forgot_password_success_title()}</h3>
          <p class="mt-2 text-sm text-stone-600">
            {m.auth_forgot_password_success_body({ email })}
          </p>
          <p class="mt-4 text-xs text-stone-500">
            {m.auth_forgot_password_no_email_hint()}
          </p>

          <div class="mt-6">
            <a
              href={localizeHref('/login')}
              class="inline-flex w-full justify-center rounded-md border border-transparent bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2"
            >
              {m.auth_forgot_password_back_to_login()}
            </a>
          </div>
        </div>
      </div>
    {:else}
      <!-- Forgot Password Form -->
      <form class="mt-8 space-y-6" onsubmit={handleSubmit}>
        <div class="rounded-md shadow-sm">
          <div>
            <label for="email" class="sr-only">{m.auth_forgot_password_email_placeholder()}</label>
            <input
              id="email"
              name="email"
              type="email"
              autocomplete="email"
              required
              bind:value={email}
              disabled={isSubmitting}
              class="relative block w-full appearance-none rounded-md border border-stone-300 px-3 py-2 text-stone-900 placeholder-stone-500 focus:z-10 focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:bg-stone-100 disabled:cursor-not-allowed sm:text-sm"
              placeholder={m.auth_forgot_password_email_placeholder()}
            />
          </div>
        </div>

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

        <!-- Submit Button -->
        <div>
          <button
            type="submit"
            disabled={isSubmitting}
            class="group relative flex w-full justify-center rounded-md border border-transparent bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:bg-stone-400 disabled:cursor-not-allowed"
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
                {m.auth_forgot_password_submitting()}
              </span>
            {:else}
              {m.auth_forgot_password_submit()}
            {/if}
          </button>
        </div>

        <!-- Back to Login Link -->
        <div class="text-center text-sm">
          <a href={localizeHref('/login')} class="font-medium text-primary-600 hover:text-primary-500">
            {m.auth_forgot_password_back_to_login()}
          </a>
        </div>
      </form>
    {/if}
  </div>
</div>
