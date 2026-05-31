<script lang="ts">
  /**
   * Forced password-change screen (spec/011 US4).
   *
   * Lives in the `(auth)` route group so a user whose `must_change_password`
   * flag is set (after an admin reset) can reach it even though the `(app)`
   * guard bounces them away from every other authenticated route. On success
   * the user is sent to `/dashboard`; the `must_change_password` flag is
   * cleared server-side by the change-password endpoint.
   */

  import { goto } from '$app/navigation';
  import { changePassword } from '$lib/api/auth';
  import { apiClient, ApiError } from '$lib/api/client';
  import { authStore } from '$lib/stores/auth.svelte';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import type { User } from '$lib/types';
  import LanguageSwitcher from '$lib/components/ui/LanguageSwitcher.svelte';
  import DarkModeToggle from '$lib/components/ui/DarkModeToggle.svelte';

  // Form state
  let currentPassword = $state('');
  let newPassword = $state('');
  let confirmPassword = $state('');

  // UI state
  let isSubmitting = $state(false);
  let error = $state<string | null>(null);
  let success = $state<string | null>(null);
  let fieldErrors = $state<Record<string, string>>({});

  /**
   * Validate form fields (mirrors the reset-password rules: 8+ chars,
   * mixed case + number, confirm match).
   */
  function validateForm(): boolean {
    fieldErrors = {};
    error = null;

    if (!currentPassword) {
      fieldErrors.currentPassword = m.error_current_password_required();
    }

    if (!newPassword) {
      fieldErrors.newPassword = m.error_password_required();
    } else if (newPassword.length < 8) {
      fieldErrors.newPassword = m.error_password_too_short_8();
    } else if (!/(?=.*[a-z])(?=.*[A-Z])(?=.*\d)/.test(newPassword)) {
      fieldErrors.newPassword = m.error_password_complexity();
    }

    if (!confirmPassword) {
      fieldErrors.confirmPassword = m.error_confirm_password_required();
    } else if (newPassword !== confirmPassword) {
      fieldErrors.confirmPassword = m.auth_change_password_mismatch();
    }

    return Object.keys(fieldErrors).length === 0;
  }

  /**
   * Pull the backend-provided policy message out of the structured error
   * envelope (`{ detail: { error_code, message } }`).
   */
  function policyMessage(err: ApiError): string | null {
    const body = err.body;
    if (typeof body === 'object' && body !== null && 'detail' in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === 'object' && detail !== null && 'message' in detail) {
        const message = (detail as { message: unknown }).message;
        if (typeof message === 'string' && message.length > 0) return message;
      }
    }
    return null;
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
    success = null;

    try {
      const res = await changePassword(currentPassword, newPassword);

      // The backend rotates the caller's `security_stamp` on success,
      // which invalidates the OLD in-memory access token. It returns a
      // freshly-minted `access_token`; swap it into the apiClient FIRST so
      // the `/users/me` re-hydrate (and every subsequent session-gated
      // call) authenticates with the NEW token rather than the rotated-stale
      // one. Older backends may omit the field — guard accordingly.
      if (res?.access_token) {
        apiClient.setAccessToken(res.access_token);
      }

      // The backend re-issues the caller's session cookies with the new
      // security_stamp, so the current session SURVIVES the change. Re-hydrate
      // the auth store BEFORE navigating so `must_change_password` flips to
      // false in memory; otherwise the (app) layout guard would immediately
      // bounce the user back here (soft-lock loop).
      try {
        const user = await apiClient.get<User>('/web-api/v1/users/me');
        authStore.setUser(user);
      } catch {
        // Re-hydrate failed (e.g. transient): the next route's guard will
        // retry via authStore.initialize(). Fall through to the success
        // notice rather than risking a redirect loop with stale state.
      }

      // Surface the success notice before/at redirect.
      success = m.auth_change_password_success();

      // Loop guard: only navigate into the (app) area once the auth store
      // confirms the flag is cleared. If it somehow still shows
      // must_change_password=true, do NOT redirect — leave the user on the
      // success state so they can proceed manually instead of bouncing.
      if (authStore.user?.must_change_password !== true) {
        await goto(localizeHref('/dashboard'));
      }
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 401 || err.code === 'current_password_invalid') {
          error = m.auth_change_password_current_invalid();
        } else if (err.code === 'password_reused') {
          error = m.auth_change_password_reused();
        } else if (err.code === 'password_policy_violation') {
          error = policyMessage(err) ?? err.detail ?? err.message;
        } else {
          error = err.detail || err.message;
        }
      } else {
        error = m.error_unexpected();
      }
    } finally {
      isSubmitting = false;
    }
  }
</script>

<svelte:head>
  <title>{m.auth_change_password_title()} - Echoroo</title>
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
        {m.auth_change_password_title()}
      </h2>
      <p class="mt-2 text-center text-sm text-stone-600">
        {m.auth_change_password_subtitle()}
      </p>
    </div>

    <!-- Change Password Form -->
    <form class="mt-8 space-y-6" onsubmit={handleSubmit} data-testid="change-password-form">
      <div class="space-y-4 rounded-md shadow-sm">
        <!-- Current Password -->
        <div>
          <label for="currentPassword" class="block text-sm font-medium text-stone-700">
            {m.auth_change_password_current_label()} <span class="text-danger">*</span>
          </label>
          <input
            id="currentPassword"
            name="currentPassword"
            type="password"
            autocomplete="current-password"
            required
            bind:value={currentPassword}
            disabled={isSubmitting}
            data-testid="change-password-current-input"
            class="mt-1 block w-full appearance-none rounded-md border border-stone-300 px-3 py-2 text-stone-900 placeholder-stone-500 focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:bg-stone-100 disabled:cursor-not-allowed sm:text-sm"
            class:border-danger={fieldErrors.currentPassword}
          />
          {#if fieldErrors.currentPassword}
            <p class="mt-1 text-sm text-danger">{fieldErrors.currentPassword}</p>
          {/if}
        </div>

        <!-- New Password -->
        <div>
          <label for="newPassword" class="block text-sm font-medium text-stone-700">
            {m.auth_change_password_new_label()} <span class="text-danger">*</span>
          </label>
          <input
            id="newPassword"
            name="newPassword"
            type="password"
            autocomplete="new-password"
            required
            bind:value={newPassword}
            disabled={isSubmitting}
            data-testid="change-password-new-input"
            class="mt-1 block w-full appearance-none rounded-md border border-stone-300 px-3 py-2 text-stone-900 placeholder-stone-500 focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:bg-stone-100 disabled:cursor-not-allowed sm:text-sm"
            class:border-danger={fieldErrors.newPassword}
            placeholder={m.auth_register_password_placeholder()}
          />
          {#if fieldErrors.newPassword}
            <p class="mt-1 text-sm text-danger">{fieldErrors.newPassword}</p>
          {:else}
            <p class="mt-1 text-xs text-stone-500">
              {m.auth_register_password_hint()}
            </p>
          {/if}
        </div>

        <!-- Confirm New Password -->
        <div>
          <label for="confirmPassword" class="block text-sm font-medium text-stone-700">
            {m.auth_change_password_confirm_label()} <span class="text-danger">*</span>
          </label>
          <input
            id="confirmPassword"
            name="confirmPassword"
            type="password"
            autocomplete="new-password"
            required
            bind:value={confirmPassword}
            disabled={isSubmitting}
            data-testid="change-password-confirm-input"
            class="mt-1 block w-full appearance-none rounded-md border border-stone-300 px-3 py-2 text-stone-900 placeholder-stone-500 focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:bg-stone-100 disabled:cursor-not-allowed sm:text-sm"
            class:border-danger={fieldErrors.confirmPassword}
          />
          {#if fieldErrors.confirmPassword}
            <p class="mt-1 text-sm text-danger">{fieldErrors.confirmPassword}</p>
          {/if}
        </div>
      </div>

      <!-- Success Message -->
      {#if success}
        <div
          class="rounded-md bg-success-light p-4"
          role="status"
          data-testid="change-password-success"
        >
          <p class="text-sm font-medium text-success">{success}</p>
        </div>
      {/if}

      <!-- Error Message -->
      {#if error}
        <div class="rounded-md bg-danger-light p-4" role="alert" data-testid="change-password-error">
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
          data-testid="change-password-submit"
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
              {m.auth_change_password_submit()}
            </span>
          {:else}
            {m.auth_change_password_submit()}
          {/if}
        </button>
      </div>
    </form>
  </div>
</div>
