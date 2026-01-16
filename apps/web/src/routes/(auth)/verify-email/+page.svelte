<script lang="ts">
  /**
   * Email verification page
   */

  import { onMount } from 'svelte';
  import { verifyEmail, resendVerificationEmail } from '$lib/api/auth';
  import { ApiError } from '$lib/api/client';
  import type { PageData } from './$types';

  interface Props {
    data: PageData;
  }

  let { data }: Props = $props();

  // Verification state
  let isVerifying = $state(false);
  let isVerified = $state(false);
  let error = $state<string | null>(null);

  // Resend state
  let isResending = $state(false);
  let resendSuccess = $state(false);
  let resendCooldown = $state(0);

  /**
   * Verify email with token
   */
  async function verify() {
    if (!data.token) return;

    isVerifying = true;
    error = null;

    try {
      await verifyEmail(data.token);
      isVerified = true;
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = 'An unexpected error occurred. Please try again.';
      }
    } finally {
      isVerifying = false;
    }
  }

  /**
   * Resend verification email
   */
  async function handleResend() {
    isResending = true;
    resendSuccess = false;
    error = null;

    try {
      await resendVerificationEmail();
      resendSuccess = true;

      // Start cooldown timer (60 seconds)
      resendCooldown = 60;
      const interval = setInterval(() => {
        resendCooldown--;
        if (resendCooldown <= 0) {
          clearInterval(interval);
        }
      }, 1000);
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = 'Failed to resend verification email. Please try again.';
      }
    } finally {
      isResending = false;
    }
  }

  onMount(() => {
    // If token is provided, automatically verify
    if (data.token) {
      verify();
    }
  });
</script>

<svelte:head>
  <title>Verify Email - Echoroo</title>
</svelte:head>

<div class="flex min-h-screen items-center justify-center bg-gray-50 px-4 py-12 sm:px-6 lg:px-8">
  <div class="w-full max-w-md space-y-8">
    <!-- Header -->
    <div>
      <h2 class="mt-6 text-center text-3xl font-extrabold text-gray-900">
        Email Verification
      </h2>
    </div>

    <div class="mt-8 rounded-lg bg-white p-8 shadow-md">
      {#if isVerifying}
        <!-- Verifying State -->
        <div class="text-center">
          <div class="mb-4 flex justify-center">
            <svg
              class="h-12 w-12 animate-spin text-blue-600"
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
          </div>
          <p class="text-lg font-medium text-gray-900">Verifying your email...</p>
          <p class="mt-2 text-sm text-gray-600">Please wait while we verify your email address.</p>
        </div>
      {:else if isVerified}
        <!-- Success State -->
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
                d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
          </div>
          <h3 class="text-lg font-medium text-gray-900">Email verified successfully!</h3>
          <p class="mt-2 text-sm text-gray-600">
            Your email address has been verified. You can now log in to your account.
          </p>
          <div class="mt-6">
            <a
              href="/login"
              class="inline-flex w-full justify-center rounded-md border border-transparent bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
            >
              Go to Login
            </a>
          </div>
        </div>
      {:else if data.registered}
        <!-- Registration Success - Pending Verification -->
        <div class="text-center">
          <div class="mb-4 flex justify-center">
            <svg
              class="h-12 w-12 text-blue-600"
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
          <h3 class="text-lg font-medium text-gray-900">Check your email!</h3>
          <p class="mt-2 text-sm text-gray-600">
            We've sent a verification link to your email address. Please click the link to verify
            your account.
          </p>

          {#if resendSuccess}
            <div class="mt-4 rounded-md bg-green-50 p-4">
              <p class="text-sm font-medium text-green-800">
                Verification email sent successfully!
              </p>
            </div>
          {/if}

          <div class="mt-6">
            <p class="text-sm text-gray-600">Didn't receive the email?</p>
            <button
              type="button"
              onclick={handleResend}
              disabled={isResending || resendCooldown > 0}
              class="mt-2 inline-flex items-center rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {#if isResending}
                Sending...
              {:else if resendCooldown > 0}
                Resend in {resendCooldown}s
              {:else}
                Resend Verification Email
              {/if}
            </button>
          </div>
        </div>
      {:else if error}
        <!-- Error State -->
        <div class="text-center">
          <div class="mb-4 flex justify-center">
            <svg
              class="h-12 w-12 text-red-600"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
          </div>
          <h3 class="text-lg font-medium text-gray-900">Verification failed</h3>
          <p class="mt-2 text-sm text-red-600">{error}</p>

          <div class="mt-6 space-y-3">
            <button
              type="button"
              onclick={handleResend}
              disabled={isResending || resendCooldown > 0}
              class="inline-flex w-full justify-center rounded-md border border-transparent bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {#if isResending}
                Sending...
              {:else if resendCooldown > 0}
                Resend in {resendCooldown}s
              {:else}
                Resend Verification Email
              {/if}
            </button>

            <a
              href="/login"
              class="inline-flex w-full justify-center rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
            >
              Back to Login
            </a>
          </div>
        </div>
      {:else}
        <!-- No Token Provided -->
        <div class="text-center">
          <p class="text-sm text-gray-600">No verification token provided.</p>
          <div class="mt-4">
            <a
              href="/login"
              class="inline-flex justify-center rounded-md border border-transparent bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
            >
              Go to Login
            </a>
          </div>
        </div>
      {/if}
    </div>
  </div>
</div>
