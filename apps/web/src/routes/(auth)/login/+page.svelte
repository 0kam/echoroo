<script lang="ts">
  /**
   * Login page
   */

  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { login } from '$lib/api/auth';
  import { authStore } from '$lib/stores/auth.svelte';
  import { ApiError } from '$lib/api/client';
  import Captcha from '$lib/components/Captcha.svelte';
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
      error = 'Please login to continue';
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
      error = 'Please enter your email and password';
      return;
    }

    // Validate email format
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email)) {
      error = 'Please enter a valid email address';
      return;
    }

    // Validate password length
    if (password.length < 8) {
      error = 'Password must be at least 8 characters';
      return;
    }

    // Require CAPTCHA after 3 failed attempts
    if (showCaptcha && !captchaToken) {
      error = 'Please complete the CAPTCHA verification';
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

      // Update auth store
      authStore.setUser(response.user);

      // Reset failed attempts
      failedAttempts = 0;
      showCaptcha = false;

      // Redirect to dashboard or return URL
      const redirect = $page.url.searchParams.get('redirect');
      await goto(redirect || '/dashboard');
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
        error = 'An unexpected error occurred. Please try again.';
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
    error = 'CAPTCHA verification failed. Please try again.';
  }

  /**
   * Handle CAPTCHA expiry
   */
  function handleCaptchaExpire() {
    captchaToken = null;
  }
</script>

<svelte:head>
  <title>Login - Echoroo</title>
</svelte:head>

<div class="flex min-h-screen items-center justify-center bg-gray-50 px-4 py-12 sm:px-6 lg:px-8">
  <div class="w-full max-w-md space-y-8">
    <!-- Header -->
    <div>
      <h2 class="mt-6 text-center text-3xl font-extrabold text-gray-900">
        Login to Echoroo
      </h2>
      <p class="mt-2 text-center text-sm text-gray-600">
        Welcome back! Please sign in to continue.
      </p>
    </div>

    <!-- Login Form -->
    <form class="mt-8 space-y-6" onsubmit={handleSubmit}>
      <div class="space-y-4 rounded-md shadow-sm">
        <!-- Email Input -->
        <div>
          <label for="email" class="sr-only">Email address</label>
          <input
            id="email"
            name="email"
            type="email"
            autocomplete="email"
            required
            bind:value={email}
            disabled={isSubmitting}
            class="relative block w-full appearance-none rounded-md border border-gray-300 px-3 py-2 text-gray-900 placeholder-gray-500 focus:z-10 focus:border-blue-500 focus:outline-none focus:ring-blue-500 disabled:bg-gray-100 disabled:cursor-not-allowed sm:text-sm"
            placeholder="Email address"
          />
        </div>

        <!-- Password Input -->
        <div>
          <label for="password" class="sr-only">Password</label>
          <input
            id="password"
            name="password"
            type="password"
            autocomplete="current-password"
            required
            bind:value={password}
            disabled={isSubmitting}
            class="relative block w-full appearance-none rounded-md border border-gray-300 px-3 py-2 text-gray-900 placeholder-gray-500 focus:z-10 focus:border-blue-500 focus:outline-none focus:ring-blue-500 disabled:bg-gray-100 disabled:cursor-not-allowed sm:text-sm"
            placeholder="Password"
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
        <div class="rounded-md bg-red-50 p-4" role="alert">
          <div class="flex">
            <div class="flex-shrink-0">
              <svg
                class="h-5 w-5 text-red-400"
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
              <p class="text-sm font-medium text-red-800">{error}</p>
            </div>
          </div>
        </div>
      {/if}

      <!-- Forgot Password Link -->
      <div class="flex items-center justify-end">
        <div class="text-sm">
          <a href="/forgot-password" class="font-medium text-blue-600 hover:text-blue-500">
            Forgot password?
          </a>
        </div>
      </div>

      <!-- Submit Button -->
      <div>
        <button
          type="submit"
          disabled={isSubmitting}
          class="group relative flex w-full justify-center rounded-md border border-transparent bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:bg-gray-400 disabled:cursor-not-allowed"
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
              Signing in...
            </span>
          {:else}
            Log In
          {/if}
        </button>
      </div>

      <!-- Register Link -->
      <div class="text-center text-sm">
        <span class="text-gray-600">Don't have an account?</span>
        <a href="/register" class="ml-1 font-medium text-blue-600 hover:text-blue-500">
          Register
        </a>
      </div>
    </form>
  </div>
</div>
