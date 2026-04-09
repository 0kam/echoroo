<script lang="ts">
  /**
   * API Tokens Management Page
   * Allows users to create, view, and revoke API tokens
   */

  import { listTokens, createToken, revokeToken } from '$lib/api/tokens';
  import { ApiError } from '$lib/api/client';
  import { localizeHref, getLocale } from '$lib/paraglide/runtime';
  import type { APIToken, APITokenCreateRequest } from '$lib/types';
  import * as m from '$lib/paraglide/messages';

  // State
  let tokens = $state<APIToken[]>([]);
  let isLoading = $state(true);
  let error = $state<string | null>(null);
  let successMessage = $state<string | null>(null);

  // Create token modal state
  let showCreateModal = $state(false);
  let tokenName = $state('');
  let expiresAt = $state('');
  let isCreating = $state(false);

  // Token display modal state
  let showTokenModal = $state(false);
  let newTokenValue = $state('');
  let newTokenName = $state('');
  let isCopied = $state(false);

  /**
   * Load tokens
   */
  async function loadTokens() {
    isLoading = true;
    error = null;

    try {
      tokens = await listTokens();
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = m.api_tokens_failed_load();
      }
    } finally {
      isLoading = false;
    }
  }

  // Load tokens on mount
  $effect(() => {
    loadTokens();
  });

  /**
   * Open create token modal
   */
  function openCreateModal() {
    tokenName = '';
    expiresAt = '';
    showCreateModal = true;
  }

  /**
   * Close create token modal
   */
  function closeCreateModal() {
    showCreateModal = false;
    tokenName = '';
    expiresAt = '';
  }

  /**
   * Handle create token
   */
  async function handleCreateToken(event: Event) {
    event.preventDefault();

    if (!tokenName.trim()) {
      error = 'Token name is required';
      return;
    }

    isCreating = true;
    error = null;

    try {
      const request: APITokenCreateRequest = {
        name: tokenName.trim(),
      };

      if (expiresAt) {
        request.expires_at = new Date(expiresAt).toISOString();
      }

      const response = await createToken(request);

      // Store token value and name for display
      newTokenValue = response.token;
      newTokenName = response.name;

      // Close create modal and show token modal
      closeCreateModal();
      showTokenModal = true;

      // Reload tokens list
      await loadTokens();
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = m.api_tokens_failed_create();
      }
    } finally {
      isCreating = false;
    }
  }

  /**
   * Close token display modal
   */
  function closeTokenModal() {
    showTokenModal = false;
    newTokenValue = '';
    newTokenName = '';
    isCopied = false;
  }

  /**
   * Copy token to clipboard
   */
  async function copyToClipboard() {
    try {
      await navigator.clipboard.writeText(newTokenValue);
      isCopied = true;
      successMessage = m.api_tokens_copied_success();

      // Clear success message after 3 seconds
      setTimeout(() => {
        successMessage = null;
      }, 3000);
    } catch {
      error = 'Failed to copy to clipboard';
    }
  }

  /**
   * Handle revoke token
   */
  async function handleRevokeToken(token: APIToken) {
    if (!confirm(m.api_tokens_revoke_confirm({ name: token.name }))) {
      return;
    }

    try {
      await revokeToken(token.id);
      successMessage = m.api_tokens_revoked_success();

      // Clear success message after 3 seconds
      setTimeout(() => {
        successMessage = null;
      }, 3000);

      // Reload tokens list
      await loadTokens();
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = m.api_tokens_failed_revoke();
      }
    }
  }

  /**
   * Format date
   */
  function formatDate(dateString: string | undefined | null): string {
    if (!dateString) return m.api_tokens_never();
    return new Date(dateString).toLocaleString(getLocale());
  }

  /**
   * Format date for datetime-local input
   */
  function getMinDateTime(): string {
    const now = new Date();
    now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
    return now.toISOString().slice(0, 16);
  }
</script>

<svelte:head>
  <title>{m.api_tokens_page_title()}</title>
</svelte:head>

<div class="px-8 py-6">
  <!-- Header -->
  <div class="mb-6 flex items-center justify-between">
    <div>
      <h1 class="text-3xl font-bold text-stone-900">{m.api_tokens_heading()}</h1>
      <p class="mt-2 text-sm text-stone-600">
        {m.api_tokens_description()}
      </p>
    </div>
    <div class="flex space-x-3">
      <a
        href={localizeHref('/profile')}
        class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2"
      >
        {m.api_tokens_back_to_profile()}
      </a>
      <button
        onclick={openCreateModal}
        class="rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2"
      >
        {m.api_tokens_create_button()}
      </button>
    </div>
  </div>

  <!-- Success Message -->
  {#if successMessage}
    <div class="mb-6 rounded-md bg-green-50 p-4 dark:bg-green-900/20" role="alert">
      <div class="flex">
        <div class="flex-shrink-0">
          <svg
            class="h-5 w-5 text-green-400"
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 20 20"
            fill="currentColor"
          >
            <path
              fill-rule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
              clip-rule="evenodd"
            />
          </svg>
        </div>
        <div class="ml-3">
          <p class="text-sm font-medium text-green-800 dark:text-green-400">{successMessage}</p>
        </div>
      </div>
    </div>
  {/if}

  <!-- Error Message -->
  {#if error}
    <div class="mb-6 rounded-md bg-red-50 p-4 dark:bg-red-900/20" role="alert">
      <div class="flex">
        <div class="flex-shrink-0">
          <svg
            class="h-5 w-5 text-red-400"
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 20 20"
            fill="currentColor"
          >
            <path
              fill-rule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
              clip-rule="evenodd"
            />
          </svg>
        </div>
        <div class="ml-3">
          <p class="text-sm font-medium text-red-800 dark:text-red-400">{error}</p>
        </div>
      </div>
    </div>
  {/if}

  <!-- Tokens Table -->
  {#if isLoading}
    <div class="flex items-center justify-center py-12">
      <svg
        class="h-8 w-8 animate-spin text-primary-600"
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
      >
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"
        ></circle>
        <path
          class="opacity-75"
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
        ></path>
      </svg>
    </div>
  {:else if tokens.length === 0}
    <div class="rounded-lg border-2 border-dashed border-stone-300 p-12 text-center">
      <svg
        class="mx-auto h-12 w-12 text-stone-400"
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
      <h3 class="mt-2 text-sm font-medium text-stone-900">{m.api_tokens_no_tokens_heading()}</h3>
      <p class="mt-1 text-sm text-stone-500">{m.api_tokens_no_tokens_hint()}</p>
      <div class="mt-6">
        <button
          onclick={openCreateModal}
          class="inline-flex items-center rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2"
        >
          {m.api_tokens_create_button()}
        </button>
      </div>
    </div>
  {:else}
    <div class="overflow-hidden rounded-lg border border-card bg-surface-card shadow-sm">
      <div class="overflow-x-auto">
        <table class="min-w-full divide-y divide-stone-200">
          <thead class="bg-stone-50">
            <tr>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-stone-500"
              >
                {m.api_tokens_col_name()}
              </th>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-stone-500"
              >
                {m.api_tokens_col_created()}
              </th>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-stone-500"
              >
                {m.api_tokens_col_last_used()}
              </th>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-stone-500"
              >
                {m.api_tokens_col_expires()}
              </th>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-stone-500"
              >
                {m.api_tokens_col_status()}
              </th>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-stone-500"
              >
                {m.api_tokens_col_actions()}
              </th>
            </tr>
          </thead>
          <tbody class="divide-y divide-stone-200 bg-surface-card">
            {#each tokens as token (token.id)}
              <tr class="hover:bg-stone-50">
                <!-- Name -->
                <td class="whitespace-nowrap px-6 py-4">
                  <div class="text-sm font-medium text-stone-900">{token.name}</div>
                </td>

                <!-- Created -->
                <td class="whitespace-nowrap px-6 py-4 text-sm text-stone-500">
                  {formatDate(token.created_at)}
                </td>

                <!-- Last Used -->
                <td class="whitespace-nowrap px-6 py-4 text-sm text-stone-500">
                  {formatDate(token.last_used_at)}
                </td>

                <!-- Expires -->
                <td class="whitespace-nowrap px-6 py-4 text-sm text-stone-500">
                  {formatDate(token.expires_at)}
                </td>

                <!-- Status -->
                <td class="whitespace-nowrap px-6 py-4">
                  <span
                    class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium {token.is_active
                      ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
                      : 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400'}"
                  >
                    {token.is_active ? m.api_tokens_status_active() : m.api_tokens_status_inactive()}
                  </span>
                </td>

                <!-- Actions -->
                <td class="whitespace-nowrap px-6 py-4 text-sm">
                  <button
                    onclick={() => handleRevokeToken(token)}
                    class="rounded bg-red-100 px-3 py-1 text-xs font-medium text-red-700 transition-colors hover:bg-red-200"
                  >
                    {m.api_tokens_revoke_button()}
                  </button>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>
  {/if}
</div>

<!-- Create Token Modal -->
{#if showCreateModal}
  <div class="fixed inset-0 z-10 overflow-y-auto" aria-labelledby="modal-title" role="dialog" aria-modal="true">
    <div class="flex min-h-screen items-end justify-center px-4 pb-20 pt-4 text-center sm:block sm:p-0">
      <!-- Background overlay -->
      <div
        class="fixed inset-0 bg-stone-500 bg-opacity-75 transition-opacity"
        onclick={closeCreateModal}
        onkeydown={(e) => e.key === 'Escape' && closeCreateModal()}
        role="button"
        tabindex="-1"
        aria-label="Close modal"
      ></div>

      <!-- Center modal -->
      <span class="hidden sm:inline-block sm:h-screen sm:align-middle" aria-hidden="true">&#8203;</span>

      <div class="inline-block transform overflow-hidden rounded-lg bg-surface-card text-left align-bottom shadow-xl transition-all sm:my-8 sm:w-full sm:max-w-lg sm:align-middle">
        <form onsubmit={handleCreateToken}>
          <div class="bg-surface-card px-4 pb-4 pt-5 sm:p-6 sm:pb-4">
            <div class="sm:flex sm:items-start">
              <div class="mt-3 w-full text-center sm:ml-4 sm:mt-0 sm:text-left">
                <h3 class="text-lg font-medium leading-6 text-stone-900" id="modal-title">
                  {m.api_tokens_create_modal_title()}
                </h3>
                <div class="mt-4 space-y-4">
                  <!-- Token Name -->
                  <div>
                    <label for="token-name" class="block text-sm font-medium text-stone-700">
                      {m.api_tokens_token_name_label()}
                    </label>
                    <input
                      type="text"
                      id="token-name"
                      bind:value={tokenName}
                      required
                      placeholder="e.g., Production API Token"
                      class="mt-1 block w-full rounded-md border-stone-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
                    />
                    <p class="mt-1 text-sm text-stone-500">
                      {m.api_tokens_token_name_hint()}
                    </p>
                  </div>

                  <!-- Expiration Date -->
                  <div>
                    <label for="expires-at" class="block text-sm font-medium text-stone-700">
                      {m.api_tokens_expiration_label()}
                    </label>
                    <input
                      type="datetime-local"
                      id="expires-at"
                      bind:value={expiresAt}
                      min={getMinDateTime()}
                      class="mt-1 block w-full rounded-md border-stone-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
                    />
                    <p class="mt-1 text-sm text-stone-500">
                      {m.api_tokens_expiration_hint()}
                    </p>
                  </div>

                  <!-- Warning -->
                  <div class="rounded-md bg-yellow-50 p-4 dark:bg-yellow-900/20">
                    <div class="flex">
                      <div class="flex-shrink-0">
                        <svg class="h-5 w-5 text-yellow-400 dark:text-yellow-500" viewBox="0 0 20 20" fill="currentColor">
                          <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd" />
                        </svg>
                      </div>
                      <div class="ml-3">
                        <h3 class="text-sm font-medium text-yellow-800 dark:text-yellow-400">
                          {m.api_tokens_important_warning()}
                        </h3>
                        <div class="mt-2 text-sm text-yellow-700 dark:text-yellow-500">
                          <p>
                            {m.api_tokens_important_warning_body()}
                          </p>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div class="bg-stone-50 px-4 py-3 sm:flex sm:flex-row-reverse sm:px-6">
            <button
              type="submit"
              disabled={isCreating}
              class="inline-flex w-full justify-center rounded-md bg-primary-600 px-4 py-2 text-base font-medium text-white hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 sm:ml-3 sm:w-auto sm:text-sm"
            >
              {#if isCreating}
                {m.api_tokens_creating()}
              {:else}
                {m.api_tokens_create_button()}
              {/if}
            </button>
            <button
              type="button"
              onclick={closeCreateModal}
              disabled={isCreating}
              class="mt-3 inline-flex w-full justify-center rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-base font-medium text-stone-700 hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 sm:mt-0 sm:w-auto sm:text-sm"
            >
              {m.api_tokens_cancel()}
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
{/if}

<!-- Token Display Modal -->
{#if showTokenModal}
  <div class="fixed inset-0 z-10 overflow-y-auto" aria-labelledby="token-modal-title" role="dialog" aria-modal="true">
    <div class="flex min-h-screen items-end justify-center px-4 pb-20 pt-4 text-center sm:block sm:p-0">
      <!-- Background overlay -->
      <div class="fixed inset-0 bg-stone-500 bg-opacity-75 transition-opacity"></div>

      <!-- Center modal -->
      <span class="hidden sm:inline-block sm:h-screen sm:align-middle" aria-hidden="true">&#8203;</span>

      <div class="inline-block transform overflow-hidden rounded-lg bg-surface-card text-left align-bottom shadow-xl transition-all sm:my-8 sm:w-full sm:max-w-2xl sm:align-middle">
        <div class="bg-surface-card px-4 pb-4 pt-5 sm:p-6 sm:pb-4">
          <div class="sm:flex sm:items-start">
            <div class="mx-auto flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-full bg-green-100 sm:mx-0 sm:h-10 sm:w-10">
              <svg class="h-6 w-6 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <div class="mt-3 w-full text-center sm:ml-4 sm:mt-0 sm:text-left">
              <h3 class="text-lg font-medium leading-6 text-stone-900" id="token-modal-title">
                {m.api_tokens_created_title()}
              </h3>
              <div class="mt-4 space-y-4">
                <!-- Token Name -->
                <div>
                  <div class="block text-sm font-medium text-stone-700">
                    {m.api_tokens_token_name_display()}
                  </div>
                  <p class="mt-1 text-sm text-stone-900">{newTokenName}</p>
                </div>

                <!-- Token Value -->
                <div>
                  <div class="block text-sm font-medium text-stone-700">
                    {m.api_tokens_token_value_label()}
                  </div>
                  <div class="mt-1 flex space-x-2">
                    <input
                      type="text"
                      readonly
                      value={newTokenValue}
                      class="block w-full rounded-md border-stone-300 bg-stone-50 font-mono text-sm shadow-sm"
                    />
                    <button
                      onclick={copyToClipboard}
                      class="inline-flex items-center rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2"
                    >
                      {#if isCopied}
                        {m.api_tokens_copied_button()}
                      {:else}
                        {m.api_tokens_copy_button()}
                      {/if}
                    </button>
                  </div>
                </div>

                <!-- Warning -->
                <div class="rounded-md bg-red-50 p-4 dark:bg-red-900/20">
                  <div class="flex">
                    <div class="flex-shrink-0">
                      <svg class="h-5 w-5 text-red-400 dark:text-red-500" viewBox="0 0 20 20" fill="currentColor">
                        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd" />
                      </svg>
                    </div>
                    <div class="ml-3">
                      <h3 class="text-sm font-medium text-red-800 dark:text-red-400">
                        {m.api_tokens_security_warning()}
                      </h3>
                      <div class="mt-2 text-sm text-red-700 dark:text-red-500">
                        <p>
                          {m.api_tokens_security_warning_body()}
                        </p>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="bg-stone-50 px-4 py-3 sm:flex sm:flex-row-reverse sm:px-6">
          <button
            type="button"
            onclick={closeTokenModal}
            class="inline-flex w-full justify-center rounded-md bg-primary-600 px-4 py-2 text-base font-medium text-white hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 sm:ml-3 sm:w-auto sm:text-sm"
          >
            {m.api_tokens_close_button()}
          </button>
        </div>
      </div>
    </div>
  </div>
{/if}
