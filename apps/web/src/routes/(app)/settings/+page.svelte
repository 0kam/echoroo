<script lang="ts">
  /**
   * Settings page - manage user security settings (password change, API tokens)
   */

  import { onMount } from 'svelte';
  import { changePassword } from '$lib/api/users';
  import { listTokens, revokeToken } from '$lib/api/tokens';
  import TokenDialog from '$lib/components/TokenDialog.svelte';
  import type { APIToken, APITokenCreateResponse } from '$lib/types';

  // Form state
  let currentPassword = $state('');
  let newPassword = $state('');
  let confirmNewPassword = $state('');

  // UI state
  let isSubmitting = $state(false);
  let successMessage = $state('');
  let errorMessage = $state('');

  // API Token state
  let tokens = $state<APIToken[]>([]);
  let tokensLoading = $state(true);
  let tokensError = $state('');
  let isTokenDialogOpen = $state(false);
  let deletingTokenId = $state<string | null>(null);

  // Validation state
  let passwordsMatch = $derived(newPassword === confirmNewPassword);
  let newPasswordValid = $derived(
    newPassword.length >= 8 &&
    /[a-zA-Z]/.test(newPassword) &&
    /\d/.test(newPassword)
  );
  let formValid = $derived(
    currentPassword.length > 0 &&
    newPasswordValid &&
    passwordsMatch
  );

  /**
   * Get password strength indicator
   */
  function getPasswordStrength(password: string): { level: string; color: string; width: string } {
    if (password.length === 0) {
      return { level: '', color: 'bg-gray-200', width: 'w-0' };
    }
    if (password.length < 8) {
      return { level: 'Too short', color: 'bg-red-500', width: 'w-1/4' };
    }

    let score = 0;
    if (/[a-z]/.test(password)) score++;
    if (/[A-Z]/.test(password)) score++;
    if (/\d/.test(password)) score++;
    if (/[^a-zA-Z0-9]/.test(password)) score++;
    if (password.length >= 12) score++;

    if (score <= 2) {
      return { level: 'Weak', color: 'bg-yellow-500', width: 'w-1/2' };
    }
    if (score <= 3) {
      return { level: 'Good', color: 'bg-blue-500', width: 'w-3/4' };
    }
    return { level: 'Strong', color: 'bg-green-500', width: 'w-full' };
  }

  let passwordStrength = $derived(getPasswordStrength(newPassword));

  /**
   * Handle form submission
   */
  async function handleSubmit(event: Event) {
    event.preventDefault();

    if (isSubmitting || !formValid) return;

    isSubmitting = true;
    successMessage = '';
    errorMessage = '';

    try {
      await changePassword({
        current_password: currentPassword,
        new_password: newPassword,
      });

      successMessage = 'Password changed successfully';

      // Clear form
      currentPassword = '';
      newPassword = '';
      confirmNewPassword = '';

      // Clear success message after 5 seconds
      setTimeout(() => {
        successMessage = '';
      }, 5000);
    } catch (error: unknown) {
      if (error instanceof Error) {
        errorMessage = error.message;
      } else {
        errorMessage = 'Failed to change password';
      }
    } finally {
      isSubmitting = false;
    }
  }

  /**
   * Clear all form fields
   */
  function handleReset() {
    currentPassword = '';
    newPassword = '';
    confirmNewPassword = '';
    successMessage = '';
    errorMessage = '';
  }

  // ==========================================================================
  // API Token Management Functions
  // ==========================================================================

  /**
   * Load API tokens
   */
  async function loadTokens() {
    tokensLoading = true;
    tokensError = '';
    try {
      tokens = await listTokens();
    } catch (err) {
      if (err instanceof Error) {
        tokensError = err.message;
      } else {
        tokensError = 'Failed to load tokens';
      }
    } finally {
      tokensLoading = false;
    }
  }

  /**
   * Handle token creation
   */
  function handleTokenCreated(token: APITokenCreateResponse) {
    // Add the new token to the list (without the token value)
    const { token: _, ...tokenWithoutValue } = token;
    tokens = [tokenWithoutValue, ...tokens];
  }

  /**
   * Handle token revocation
   */
  async function handleRevokeToken(tokenId: string) {
    if (!confirm('Are you sure you want to revoke this token? This action cannot be undone.')) {
      return;
    }

    deletingTokenId = tokenId;
    try {
      await revokeToken(tokenId);
      tokens = tokens.filter((t) => t.id !== tokenId);
    } catch (err) {
      if (err instanceof Error) {
        tokensError = err.message;
      } else {
        tokensError = 'Failed to revoke token';
      }
    } finally {
      deletingTokenId = null;
    }
  }

  /**
   * Format date for display
   */
  function formatTokenDate(dateString: string | undefined): string {
    if (!dateString) return 'Never';
    return new Date(dateString).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  // Load tokens on mount
  onMount(() => {
    loadTokens();
  });
</script>

<svelte:head>
  <title>Settings - Echoroo</title>
</svelte:head>

<div class="min-h-screen bg-gray-50">
  <!-- Header -->
  <header class="bg-white shadow">
    <div class="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <div class="flex items-center justify-between">
        <h1 class="text-3xl font-bold text-gray-900">Settings</h1>
        <a
          href="/dashboard"
          class="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
        >
          Back to Dashboard
        </a>
      </div>
    </div>
  </header>

  <!-- Main Content -->
  <main class="mx-auto max-w-3xl px-4 py-8 sm:px-6 lg:px-8">
    <!-- Password Change Section -->
    <div class="overflow-hidden rounded-lg bg-white shadow">
      <div class="px-4 py-5 sm:p-6">
        <h2 class="text-lg font-medium leading-6 text-gray-900">
          Change Password
        </h2>
        <p class="mt-1 text-sm text-gray-600">
          Update your password to keep your account secure.
        </p>

        <!-- Success Message -->
        {#if successMessage}
          <div class="mt-4 rounded-md bg-green-50 p-4">
            <div class="flex">
              <div class="flex-shrink-0">
                <svg class="h-5 w-5 text-green-400" viewBox="0 0 20 20" fill="currentColor">
                  <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" />
                </svg>
              </div>
              <div class="ml-3">
                <p class="text-sm font-medium text-green-800">{successMessage}</p>
              </div>
            </div>
          </div>
        {/if}

        <!-- Error Message -->
        {#if errorMessage}
          <div class="mt-4 rounded-md bg-red-50 p-4">
            <div class="flex">
              <div class="flex-shrink-0">
                <svg class="h-5 w-5 text-red-400" viewBox="0 0 20 20" fill="currentColor">
                  <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd" />
                </svg>
              </div>
              <div class="ml-3">
                <p class="text-sm font-medium text-red-800">{errorMessage}</p>
              </div>
            </div>
          </div>
        {/if}

        <form class="mt-6 space-y-6" onsubmit={handleSubmit}>
          <!-- Current Password -->
          <div>
            <label for="current_password" class="block text-sm font-medium text-gray-700">
              Current password
            </label>
            <div class="mt-1">
              <input
                type="password"
                id="current_password"
                name="current_password"
                bind:value={currentPassword}
                autocomplete="current-password"
                required
                class="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
              />
            </div>
          </div>

          <!-- New Password -->
          <div>
            <label for="new_password" class="block text-sm font-medium text-gray-700">
              New password
            </label>
            <div class="mt-1">
              <input
                type="password"
                id="new_password"
                name="new_password"
                bind:value={newPassword}
                autocomplete="new-password"
                required
                minlength="8"
                class="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
              />
            </div>

            <!-- Password Strength Indicator -->
            {#if newPassword.length > 0}
              <div class="mt-2">
                <div class="flex items-center justify-between">
                  <div class="flex-1">
                    <div class="h-2 w-full rounded-full bg-gray-200">
                      <div
                        class="h-2 rounded-full transition-all duration-300 {passwordStrength.color} {passwordStrength.width}"
                      ></div>
                    </div>
                  </div>
                  <span class="ml-3 text-sm font-medium text-gray-600">
                    {passwordStrength.level}
                  </span>
                </div>
              </div>
            {/if}

            <!-- Password Requirements -->
            <div class="mt-2 text-sm text-gray-500">
              <p>Password requirements:</p>
              <ul class="mt-1 list-inside list-disc space-y-1">
                <li class:text-green-600={newPassword.length >= 8} class:text-gray-500={newPassword.length < 8}>
                  At least 8 characters
                </li>
                <li class:text-green-600={/[a-zA-Z]/.test(newPassword)} class:text-gray-500={!/[a-zA-Z]/.test(newPassword)}>
                  At least one letter
                </li>
                <li class:text-green-600={/\d/.test(newPassword)} class:text-gray-500={!/\d/.test(newPassword)}>
                  At least one number
                </li>
              </ul>
            </div>
          </div>

          <!-- Confirm New Password -->
          <div>
            <label for="confirm_new_password" class="block text-sm font-medium text-gray-700">
              Confirm new password
            </label>
            <div class="mt-1">
              <input
                type="password"
                id="confirm_new_password"
                name="confirm_new_password"
                bind:value={confirmNewPassword}
                autocomplete="new-password"
                required
                class="block w-full rounded-md shadow-sm focus:ring-blue-500 sm:text-sm"
                class:border-gray-300={confirmNewPassword.length === 0 || passwordsMatch}
                class:border-red-500={confirmNewPassword.length > 0 && !passwordsMatch}
                class:focus:border-blue-500={confirmNewPassword.length === 0 || passwordsMatch}
                class:focus:border-red-500={confirmNewPassword.length > 0 && !passwordsMatch}
              />
            </div>
            {#if confirmNewPassword.length > 0 && !passwordsMatch}
              <p class="mt-1 text-sm text-red-600">Passwords do not match</p>
            {/if}
          </div>

          <!-- Form Actions -->
          <div class="flex justify-end space-x-3 border-t border-gray-200 pt-6">
            <button
              type="button"
              onclick={handleReset}
              disabled={isSubmitting}
              class="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Clear
            </button>
            <button
              type="submit"
              disabled={!formValid || isSubmitting}
              class="inline-flex items-center rounded-md border border-transparent bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {#if isSubmitting}
                <svg class="-ml-1 mr-2 h-4 w-4 animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                Changing...
              {:else}
                Change Password
              {/if}
            </button>
          </div>
        </form>

        <!-- Profile Link -->
        <div class="mt-8 border-t border-gray-200 pt-6">
          <a
            href="/profile"
            class="inline-flex items-center text-sm font-medium text-blue-600 hover:text-blue-500"
          >
            <svg class="mr-2 h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
            </svg>
            Profile Settings
          </a>
          <p class="mt-1 text-sm text-gray-500">
            Update your display name and organization.
          </p>
        </div>
      </div>
    </div>

    <!-- API Tokens Section -->
    <div class="mt-8 overflow-hidden rounded-lg bg-white shadow">
      <div class="px-4 py-5 sm:p-6">
        <div class="mb-4 flex items-center justify-between">
          <div>
            <h2 class="text-lg font-medium leading-6 text-gray-900">API Tokens</h2>
            <p class="mt-1 text-sm text-gray-600">
              API tokens allow programmatic access to your account. Keep them secure.
            </p>
          </div>
          <button
            type="button"
            onclick={() => (isTokenDialogOpen = true)}
            class="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
            data-testid="create-token-button"
          >
            Create New Token
          </button>
        </div>

        {#if tokensError}
          <div class="mb-4 rounded-md bg-red-50 p-3 text-sm text-red-700" role="alert">
            {tokensError}
          </div>
        {/if}

        {#if tokensLoading}
          <div class="py-8 text-center text-gray-500">Loading tokens...</div>
        {:else if tokens.length === 0}
          <div class="py-8 text-center text-gray-500" data-testid="no-tokens-message">
            <svg
              class="mx-auto h-12 w-12 text-gray-400"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z"
              />
            </svg>
            <p class="mt-2">No API tokens yet</p>
            <p class="text-sm">Create a token to access the API programmatically</p>
          </div>
        {:else}
          <div class="overflow-hidden rounded-md border border-gray-200">
            <table class="min-w-full divide-y divide-gray-200" data-testid="tokens-table">
              <thead class="bg-gray-50">
                <tr>
                  <th
                    class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500"
                  >
                    Name
                  </th>
                  <th
                    class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500"
                  >
                    Created
                  </th>
                  <th
                    class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500"
                  >
                    Last Used
                  </th>
                  <th
                    class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500"
                  >
                    Expires
                  </th>
                  <th class="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody class="divide-y divide-gray-200 bg-white">
                {#each tokens as token (token.id)}
                  <tr data-testid={`token-row-${token.id}`}>
                    <td class="whitespace-nowrap px-4 py-3 text-sm font-medium text-gray-900">
                      {token.name}
                    </td>
                    <td class="whitespace-nowrap px-4 py-3 text-sm text-gray-500">
                      {formatTokenDate(token.created_at)}
                    </td>
                    <td class="whitespace-nowrap px-4 py-3 text-sm text-gray-500">
                      {formatTokenDate(token.last_used_at)}
                    </td>
                    <td class="whitespace-nowrap px-4 py-3 text-sm text-gray-500">
                      {token.expires_at ? formatTokenDate(token.expires_at) : 'Never'}
                    </td>
                    <td class="whitespace-nowrap px-4 py-3 text-right text-sm">
                      <button
                        type="button"
                        onclick={() => handleRevokeToken(token.id)}
                        disabled={deletingTokenId === token.id}
                        class="text-red-600 hover:text-red-800 disabled:cursor-not-allowed disabled:opacity-50"
                        data-testid={`revoke-token-${token.id}`}
                      >
                        {deletingTokenId === token.id ? 'Revoking...' : 'Revoke'}
                      </button>
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      </div>
    </div>
  </main>
</div>

<!-- Token Creation Dialog -->
<TokenDialog
  bind:open={isTokenDialogOpen}
  onClose={() => (isTokenDialogOpen = false)}
  onTokenCreated={handleTokenCreated}
/>
