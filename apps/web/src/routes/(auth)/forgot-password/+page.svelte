<script lang="ts">
  /**
   * Forgot password page
   */

  import { requestPasswordReset } from '$lib/api/auth';

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
      error = 'Please enter your email address';
      return;
    }

    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email)) {
      error = 'Please enter a valid email address';
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
  <title>Forgot Password - Echoroo</title>
</svelte:head>

<div class="flex min-h-screen items-center justify-center bg-gray-50 px-4 py-12 sm:px-6 lg:px-8">
  <div class="w-full max-w-md space-y-8">
    <!-- Header -->
    <div>
      <h2 class="mt-6 text-center text-3xl font-extrabold text-gray-900">
        Forgot your password?
      </h2>
      <p class="mt-2 text-center text-sm text-gray-600">
        Enter your email address and we'll send you a link to reset your password.
      </p>
    </div>

    {#if isSubmitted}
      <!-- Success Message -->
      <div class="rounded-lg bg-white p-8 shadow-md">
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
          <h3 class="text-lg font-medium text-gray-900">Check your email</h3>
          <p class="mt-2 text-sm text-gray-600">
            If an account exists for <strong>{email}</strong>, you will receive a password reset
            link shortly.
          </p>
          <p class="mt-4 text-xs text-gray-500">
            Didn't receive an email? Check your spam folder or try again with a different email
            address.
          </p>

          <div class="mt-6">
            <a
              href="/login"
              class="inline-flex w-full justify-center rounded-md border border-transparent bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
            >
              Back to Login
            </a>
          </div>
        </div>
      </div>
    {:else}
      <!-- Forgot Password Form -->
      <form class="mt-8 space-y-6" onsubmit={handleSubmit}>
        <div class="rounded-md shadow-sm">
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
                Sending...
              </span>
            {:else}
              Send Reset Link
            {/if}
          </button>
        </div>

        <!-- Back to Login Link -->
        <div class="text-center text-sm">
          <a href="/login" class="font-medium text-blue-600 hover:text-blue-500">
            Back to Login
          </a>
        </div>
      </form>
    {/if}
  </div>
</div>
