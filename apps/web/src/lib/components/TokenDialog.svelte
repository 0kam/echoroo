<script lang="ts">
  /**
   * Token creation dialog component
   * Handles creating new API tokens and displaying them once
   */

  import type { APITokenCreateResponse } from '$lib/types';
  import { createToken } from '$lib/api/tokens';
  import * as m from '$lib/paraglide/messages';

  interface Props {
    open: boolean;
    onClose: () => void;
    onTokenCreated: (token: APITokenCreateResponse) => void;
  }

  let { open = $bindable(), onClose, onTokenCreated }: Props = $props();

  let name = $state('');
  let expiresAt = $state('');
  let error = $state('');
  let isLoading = $state(false);
  let createdToken = $state<string | null>(null);
  let copied = $state(false);

  /**
   * Reset dialog state
   */
  function resetDialog() {
    name = '';
    expiresAt = '';
    error = '';
    isLoading = false;
    createdToken = null;
    copied = false;
  }

  /**
   * Handle dialog close
   */
  function handleClose() {
    resetDialog();
    onClose();
  }

  /**
   * Handle form submission
   */
  async function handleSubmit(e: Event) {
    e.preventDefault();
    error = '';
    isLoading = true;

    try {
      const request = {
        name: name.trim(),
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : undefined,
      };

      const response = await createToken(request);
      createdToken = response.token;
      onTokenCreated(response);
    } catch (err) {
      if (err instanceof Error) {
        error = err.message;
      } else {
        error = 'Failed to create token';
      }
    } finally {
      isLoading = false;
    }
  }

  /**
   * Copy token to clipboard
   */
  async function copyToClipboard() {
    if (!createdToken) return;

    try {
      await navigator.clipboard.writeText(createdToken);
      copied = true;
      setTimeout(() => {
        copied = false;
      }, 2000);
    } catch (err) {
      console.error('Failed to copy token:', err);
    }
  }
</script>

{#if open}
  <!-- Backdrop -->
  <div
    class="fixed inset-0 z-50 bg-black/50"
    onclick={handleClose}
    onkeydown={(e) => e.key === 'Escape' && handleClose()}
    role="button"
    tabindex="-1"
  ></div>

  <!-- Dialog -->
  <div
    class="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-lg bg-surface-card p-6 shadow-xl"
    role="dialog"
    aria-modal="true"
    aria-labelledby="dialog-title"
  >
    {#if !createdToken}
      <!-- Create Token Form -->
      <h2 id="dialog-title" class="mb-4 text-xl font-semibold text-stone-900">
        {m.token_dialog_create_title()}
      </h2>

      <form onsubmit={handleSubmit}>
        <!-- Name field -->
        <div class="mb-4">
          <label for="token-name" class="mb-1 block text-sm font-medium text-stone-700">
            {m.token_dialog_token_name_label()}
          </label>
          <input
            id="token-name"
            type="text"
            bind:value={name}
            required
            maxlength="100"
            placeholder="e.g., CI/CD Pipeline"
            class="w-full rounded-md border border-stone-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
          />
          <p class="mt-1 text-xs text-stone-500">
            {m.token_dialog_token_name_hint()}
          </p>
        </div>

        <!-- Expiration field -->
        <div class="mb-4">
          <label for="token-expires" class="mb-1 block text-sm font-medium text-stone-700">
            {m.token_dialog_expiration_label()}
          </label>
          <input
            id="token-expires"
            type="datetime-local"
            bind:value={expiresAt}
            min={new Date().toISOString().slice(0, 16)}
            class="w-full rounded-md border border-stone-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
          />
          <p class="mt-1 text-xs text-stone-500">
            {m.token_dialog_expiration_hint()}
          </p>
        </div>

        {#if error}
          <div class="mb-4 rounded-md bg-danger-light p-3 text-sm text-danger" role="alert">
            {error}
          </div>
        {/if}

        <!-- Buttons -->
        <div class="flex justify-end gap-3">
          <button
            type="button"
            onclick={handleClose}
            class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2"
          >
            {m.token_dialog_cancel()}
          </button>
          <button
            type="submit"
            disabled={isLoading || !name.trim()}
            class="rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
          >
            {isLoading ? m.token_dialog_creating() : m.token_dialog_create_button()}
          </button>
        </div>
      </form>
    {:else}
      <!-- Token Created View -->
      <h2 id="dialog-title" class="mb-4 text-xl font-semibold text-stone-900">
        {m.token_dialog_created_title()}
      </h2>

      <!-- Warning -->
      <div class="mb-4 rounded-md bg-warning-light p-4">
        <div class="flex">
          <svg
            class="h-5 w-5 text-warning"
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 20 20"
            fill="currentColor"
          >
            <path
              fill-rule="evenodd"
              d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z"
              clip-rule="evenodd"
            />
          </svg>
          <div class="ml-3">
            <h3 class="text-sm font-medium text-warning">{m.token_dialog_important()}</h3>
            <p class="mt-1 text-sm text-warning">
              {m.token_dialog_important_body()}
            </p>
          </div>
        </div>
      </div>

      <!-- Token display -->
      <div class="mb-4">
        <label for="api-token-value" class="mb-1 block text-sm font-medium text-stone-700">{m.token_dialog_your_api_token()}</label>
        <div class="flex items-center gap-2">
          <input
            id="api-token-value"
            type="text"
            value={createdToken}
            readonly
            class="w-full rounded-md border border-stone-300 bg-stone-50 px-3 py-2 font-mono text-sm"
            data-testid="token-value"
          />
          <button
            type="button"
            onclick={copyToClipboard}
            class="flex-shrink-0 rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2"
            data-testid="copy-token-button"
          >
            {copied ? m.token_dialog_copied() : m.token_dialog_copy()}
          </button>
        </div>
      </div>

      <!-- Close button -->
      <div class="flex justify-end">
        <button
          type="button"
          onclick={handleClose}
          class="rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
        >
          {m.token_dialog_done()}
        </button>
      </div>
    {/if}
  </div>
{/if}
