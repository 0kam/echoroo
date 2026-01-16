<script lang="ts">
  /**
   * Registration page
   */

  import { goto } from '$app/navigation';
  import { register } from '$lib/api/auth';
  import { ApiError } from '$lib/api/client';
  import Captcha from '$lib/components/Captcha.svelte';
  import { onMount } from 'svelte';

  // Form state
  let email = $state('');
  let password = $state('');
  let confirmPassword = $state('');
  let displayName = $state('');
  let captchaToken = $state<string | null>(null);

  // UI state
  let isSubmitting = $state(false);
  let error = $state<string | null>(null);
  let fieldErrors = $state<Record<string, string>>({});

  // Captcha reference
  let captchaComponent: { reset: () => void } | undefined = $state(undefined);

  // Environment variables
  let turnstileSiteKey = $state('');

  onMount(() => {
    // Get Turnstile site key from environment
    turnstileSiteKey = import.meta.env.PUBLIC_TURNSTILE_SITE_KEY || '1x00000000000000000000AA';
  });

  /**
   * Validate form fields
   */
  function validateForm(): boolean {
    fieldErrors = {};
    error = null;

    // Email validation
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!email) {
      fieldErrors.email = 'Email is required';
    } else if (!emailRegex.test(email)) {
      fieldErrors.email = 'Please enter a valid email address';
    }

    // Password validation
    if (!password) {
      fieldErrors.password = 'Password is required';
    } else if (password.length < 8) {
      fieldErrors.password = 'Password must be at least 8 characters';
    } else if (!/(?=.*[a-z])(?=.*[A-Z])(?=.*\d)/.test(password)) {
      fieldErrors.password = 'Password must contain uppercase, lowercase, and number';
    }

    // Confirm password validation
    if (!confirmPassword) {
      fieldErrors.confirmPassword = 'Please confirm your password';
    } else if (password !== confirmPassword) {
      fieldErrors.confirmPassword = 'Passwords do not match';
    }

    // Display name validation (optional)
    if (displayName && displayName.length > 100) {
      fieldErrors.displayName = 'Display name must be less than 100 characters';
    }

    // CAPTCHA validation
    if (!captchaToken) {
      error = 'Please complete the CAPTCHA verification';
      return false;
    }

    return Object.keys(fieldErrors).length === 0;
  }

  /**
   * Handle form submission
   */
  async function handleSubmit(e: Event) {
    e.preventDefault();

    if (!validateForm()) {
      return;
    }

    isSubmitting = true;
    error = null;

    try {
      // Call register API
      await register({
        email,
        password,
        display_name: displayName || undefined,
        captcha_token: captchaToken || undefined,
      });

      // Redirect to email verification page
      await goto('/verify-email?registered=true');
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;

        // Reset CAPTCHA
        if (captchaComponent) {
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
  <title>Register - Echoroo</title>
</svelte:head>

<div class="flex min-h-screen items-center justify-center bg-gray-50 px-4 py-12 sm:px-6 lg:px-8">
  <div class="w-full max-w-md space-y-8">
    <!-- Header -->
    <div>
      <h2 class="mt-6 text-center text-3xl font-extrabold text-gray-900">
        Create your account
      </h2>
      <p class="mt-2 text-center text-sm text-gray-600">
        Join Echoroo to start analyzing your audio recordings
      </p>
    </div>

    <!-- Registration Form -->
    <form class="mt-8 space-y-6" onsubmit={handleSubmit}>
      <div class="space-y-4 rounded-md shadow-sm">
        <!-- Email Input -->
        <div>
          <label for="email" class="block text-sm font-medium text-gray-700">
            Email address <span class="text-red-600">*</span>
          </label>
          <input
            id="email"
            name="email"
            type="email"
            autocomplete="email"
            required
            bind:value={email}
            disabled={isSubmitting}
            class="mt-1 block w-full appearance-none rounded-md border border-gray-300 px-3 py-2 text-gray-900 placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-blue-500 disabled:bg-gray-100 disabled:cursor-not-allowed sm:text-sm"
            class:border-red-500={fieldErrors.email}
            placeholder="you@example.com"
          />
          {#if fieldErrors.email}
            <p class="mt-1 text-sm text-red-600">{fieldErrors.email}</p>
          {/if}
        </div>

        <!-- Display Name Input (Optional) -->
        <div>
          <label for="displayName" class="block text-sm font-medium text-gray-700">
            Display name (optional)
          </label>
          <input
            id="displayName"
            name="displayName"
            type="text"
            autocomplete="name"
            bind:value={displayName}
            disabled={isSubmitting}
            class="mt-1 block w-full appearance-none rounded-md border border-gray-300 px-3 py-2 text-gray-900 placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-blue-500 disabled:bg-gray-100 disabled:cursor-not-allowed sm:text-sm"
            class:border-red-500={fieldErrors.displayName}
            placeholder="John Doe"
          />
          {#if fieldErrors.displayName}
            <p class="mt-1 text-sm text-red-600">{fieldErrors.displayName}</p>
          {/if}
        </div>

        <!-- Password Input -->
        <div>
          <label for="password" class="block text-sm font-medium text-gray-700">
            Password <span class="text-red-600">*</span>
          </label>
          <input
            id="password"
            name="password"
            type="password"
            autocomplete="new-password"
            required
            bind:value={password}
            disabled={isSubmitting}
            class="mt-1 block w-full appearance-none rounded-md border border-gray-300 px-3 py-2 text-gray-900 placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-blue-500 disabled:bg-gray-100 disabled:cursor-not-allowed sm:text-sm"
            class:border-red-500={fieldErrors.password}
            placeholder="At least 8 characters"
          />
          {#if fieldErrors.password}
            <p class="mt-1 text-sm text-red-600">{fieldErrors.password}</p>
          {:else}
            <p class="mt-1 text-xs text-gray-500">
              Must be at least 8 characters with uppercase, lowercase, and number
            </p>
          {/if}
        </div>

        <!-- Confirm Password Input -->
        <div>
          <label for="confirmPassword" class="block text-sm font-medium text-gray-700">
            Confirm password <span class="text-red-600">*</span>
          </label>
          <input
            id="confirmPassword"
            name="confirmPassword"
            type="password"
            autocomplete="new-password"
            required
            bind:value={confirmPassword}
            disabled={isSubmitting}
            class="mt-1 block w-full appearance-none rounded-md border border-gray-300 px-3 py-2 text-gray-900 placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-blue-500 disabled:bg-gray-100 disabled:cursor-not-allowed sm:text-sm"
            class:border-red-500={fieldErrors.confirmPassword}
            placeholder="Confirm your password"
          />
          {#if fieldErrors.confirmPassword}
            <p class="mt-1 text-sm text-red-600">{fieldErrors.confirmPassword}</p>
          {/if}
        </div>
      </div>

      <!-- CAPTCHA -->
      <div class="mt-4">
        <Captcha
          bind:this={captchaComponent}
          siteKey={turnstileSiteKey}
          onVerify={handleCaptchaVerify}
          onError={handleCaptchaError}
          onExpire={handleCaptchaExpire}
        />
      </div>

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
              Creating account...
            </span>
          {:else}
            Create Account
          {/if}
        </button>
      </div>

      <!-- Login Link -->
      <div class="text-center text-sm">
        <span class="text-gray-600">Already have an account?</span>
        <a href="/login" class="ml-1 font-medium text-blue-600 hover:text-blue-500">
          Login
        </a>
      </div>
    </form>
  </div>
</div>
