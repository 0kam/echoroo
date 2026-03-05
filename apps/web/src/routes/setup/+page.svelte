<script lang="ts">
  /**
   * Initial Setup Wizard Page
   * Create first administrator account
   */

  import { goto } from '$app/navigation';
  import { initializeSetup, type SetupInitializeRequest } from '$lib/api/setup';
  import { ApiError } from '$lib/api/client';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';

  // Form state using Svelte 5 runes
  let email = $state('');
  let password = $state('');
  let confirmPassword = $state('');
  let displayName = $state('');
  let isLoading = $state(false);
  let errorMessage = $state<string | null>(null);

  // Validation errors
  let emailError = $state<string | null>(null);
  let passwordError = $state<string | null>(null);
  let confirmPasswordError = $state<string | null>(null);

  /**
   * Validate email format
   */
  function validateEmail(value: string): string | null {
    if (!value) {
      return m.error_email_required();
    }
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(value)) {
      return m.error_invalid_email();
    }
    return null;
  }

  /**
   * Validate password strength
   */
  function validatePassword(value: string): string | null {
    if (!value) {
      return m.error_password_required();
    }
    if (value.length < 8) {
      return m.error_password_too_short();
    }
    return null;
  }

  /**
   * Validate password confirmation
   */
  function validateConfirmPassword(value: string, passwordValue: string): string | null {
    if (!value) {
      return m.error_confirm_password_required();
    }
    if (value !== passwordValue) {
      return m.error_passwords_do_not_match();
    }
    return null;
  }

  /**
   * Handle form submission
   */
  async function handleSubmit(event: Event) {
    event.preventDefault();

    // Reset errors
    errorMessage = null;
    emailError = null;
    passwordError = null;
    confirmPasswordError = null;

    // Validate all fields
    emailError = validateEmail(email);
    passwordError = validatePassword(password);
    confirmPasswordError = validateConfirmPassword(confirmPassword, password);

    // If any validation errors, stop submission
    if (emailError || passwordError || confirmPasswordError) {
      return;
    }

    // Prepare request data
    const requestData: SetupInitializeRequest = {
      email: email.trim(),
      password,
    };

    if (displayName.trim()) {
      requestData.display_name = displayName.trim();
    }

    isLoading = true;

    try {
      // Call setup initialization API
      await initializeSetup(requestData);

      // Success - redirect to login page
      goto(localizeHref('/login'));
    } catch (error) {
      // Handle API errors
      if (error instanceof ApiError) {
        errorMessage = error.detail || error.message;
      } else if (error instanceof Error) {
        errorMessage = error.message;
      } else {
        errorMessage = m.common_error_unexpected();
      }
    } finally {
      isLoading = false;
    }
  }

  /**
   * Real-time validation on blur
   */
  function handleEmailBlur() {
    if (email) {
      emailError = validateEmail(email);
    }
  }

  function handlePasswordBlur() {
    if (password) {
      passwordError = validatePassword(password);
    }
  }

  function handleConfirmPasswordBlur() {
    if (confirmPassword) {
      confirmPasswordError = validateConfirmPassword(confirmPassword, password);
    }
  }
</script>

<div class="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 flex items-center justify-center px-4 sm:px-6 lg:px-8">
  <div class="max-w-md w-full">
    <!-- Card Container -->
    <div class="bg-white shadow-xl rounded-lg p-8">
      <!-- Header -->
      <div class="text-center mb-8">
        <h1 class="text-3xl font-bold text-gray-900 mb-2">{m.setup_page_title()}</h1>
        <p class="text-gray-600">{m.setup_create_admin()}</p>
      </div>

      <!-- Error Message -->
      {#if errorMessage}
        <div class="mb-6 bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-md" role="alert">
          <p class="text-sm">{errorMessage}</p>
        </div>
      {/if}

      <!-- Setup Form -->
      <form onsubmit={handleSubmit} class="space-y-6">
        <!-- Email Field -->
        <div>
          <label for="email" class="block text-sm font-medium text-gray-700 mb-1">
            {m.setup_email_label()}
          </label>
          <input
            id="email"
            type="email"
            bind:value={email}
            onblur={handleEmailBlur}
            disabled={isLoading}
            class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 disabled:bg-gray-100 disabled:cursor-not-allowed"
            placeholder={m.setup_email_placeholder()}
            autocomplete="email"
          />
          {#if emailError}
            <p class="mt-1 text-sm text-red-600">{emailError}</p>
          {/if}
        </div>

        <!-- Password Field -->
        <div>
          <label for="password" class="block text-sm font-medium text-gray-700 mb-1">
            {m.setup_password_label()}
          </label>
          <input
            id="password"
            type="password"
            bind:value={password}
            onblur={handlePasswordBlur}
            disabled={isLoading}
            class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 disabled:bg-gray-100 disabled:cursor-not-allowed"
            placeholder={m.setup_password_placeholder()}
            autocomplete="new-password"
          />
          {#if passwordError}
            <p class="mt-1 text-sm text-red-600">{passwordError}</p>
          {:else}
            <p class="mt-1 text-xs text-gray-500">{m.setup_password_hint()}</p>
          {/if}
        </div>

        <!-- Confirm Password Field -->
        <div>
          <label for="confirmPassword" class="block text-sm font-medium text-gray-700 mb-1">
            {m.setup_confirm_password_label()}
          </label>
          <input
            id="confirmPassword"
            type="password"
            bind:value={confirmPassword}
            onblur={handleConfirmPasswordBlur}
            disabled={isLoading}
            class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 disabled:bg-gray-100 disabled:cursor-not-allowed"
            placeholder={m.setup_confirm_password_placeholder()}
            autocomplete="new-password"
          />
          {#if confirmPasswordError}
            <p class="mt-1 text-sm text-red-600">{confirmPasswordError}</p>
          {/if}
        </div>

        <!-- Display Name Field (Optional) -->
        <div>
          <label for="displayName" class="block text-sm font-medium text-gray-700 mb-1">
            {m.setup_display_name_label()} <span class="text-gray-400 text-xs">{m.setup_display_name_optional()}</span>
          </label>
          <input
            id="displayName"
            type="text"
            bind:value={displayName}
            disabled={isLoading}
            class="w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 disabled:bg-gray-100 disabled:cursor-not-allowed"
            placeholder={m.setup_display_name_placeholder()}
            autocomplete="name"
          />
        </div>

        <!-- Submit Button -->
        <button
          type="submit"
          disabled={isLoading}
          class="w-full py-3 px-4 bg-indigo-600 hover:bg-indigo-700 text-white font-medium rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors"
        >
          {#if isLoading}
            <span class="flex items-center justify-center">
              <svg class="animate-spin -ml-1 mr-3 h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              {m.setup_submitting()}
            </span>
          {:else}
            {m.setup_submit()}
          {/if}
        </button>
      </form>
    </div>

    <!-- Footer Info -->
    <div class="mt-6 text-center">
      <p class="text-sm text-gray-600">
        {m.setup_footer()}
      </p>
    </div>
  </div>
</div>
