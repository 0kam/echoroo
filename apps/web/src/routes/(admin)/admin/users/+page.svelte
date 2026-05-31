<script lang="ts">
  /**
   * Admin - User Management Page.
   *
   * spec/006 + spec/011 cleanup: the backend ``AdminUserListItem`` schema
   * no longer exposes ``is_active`` / ``is_verified`` / ``organization``,
   * and the legacy Activate / Deactivate / Promote / Demote controls were
   * dead UI (the corresponding PATCH fields are silently dropped server
   * side). Superuser promotion is handled exclusively through the
   * ``/admin/superusers`` M-of-N workflow; this page is now a read-only
   * roster with email + display name + SU role + timestamps.
   */

  import { adminApi } from '$lib/api/admin';
  import { ApiError } from '$lib/api/client';
  import { stepUpBegin, stepUpComplete } from '$lib/api/auth';
  import { clearStepUpToken } from '$lib/utils/webauthnGating';
  import { focusTrap } from '$lib/actions/focusTrap';
  import { getLocale } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import type { AdminUserListItem } from '$lib/types';

  // State
  let users = $state<AdminUserListItem[]>([]);
  let total = $state(0);
  let page = $state(1);
  let limit = $state(20);
  let search = $state('');
  let isLoading = $state(true);
  let error = $state<string | null>(null);

  // Debounced search
  let searchTimeout: ReturnType<typeof setTimeout> | null = null;

  // ---- spec/011 US4: admin password reset (step-up gated) ----

  // Step-up ceremony modal state
  let showStepUpModal = $state(false);
  let targetUserId = $state<string | null>(null);
  let targetUserEmail = $state('');
  let stepUpPassword = $state('');
  let stepUpTotpCode = $state('');
  let stepUpError = $state<string | null>(null);
  let isResetting = $state(false);

  // Temporary-password reveal dialog state
  let showRevealDialog = $state(false);
  let temporaryPassword = $state('');
  let temporaryPasswordExpiresAt = $state('');
  let copied = $state(false);
  let revealTimeout: ReturnType<typeof setTimeout> | null = null;
  // Brief notice shown on the roster when the reveal dialog auto-wipes the
  // temporary password (60s timeout). Cleared on the next reveal.
  let clearedNotice = $state<string | null>(null);

  const STEP_UP_SCOPE = 'admin_recovery' as const;

  /**
   * Open the step-up ceremony for a given roster row.
   */
  function openStepUpModal(user: AdminUserListItem) {
    targetUserId = user.id;
    targetUserEmail = user.email;
    stepUpPassword = '';
    stepUpTotpCode = '';
    stepUpError = null;
    showStepUpModal = true;
  }

  /**
   * Dismiss the step-up modal and wipe the entered factors.
   */
  function closeStepUpModal() {
    showStepUpModal = false;
    stepUpPassword = '';
    stepUpTotpCode = '';
    stepUpError = null;
  }

  /**
   * Run the full ceremony: begin → complete → reset.
   *
   * A 401 `step_up_factor_invalid` can mean any wrong factor OR a stale
   * challenge, so every attempt re-runs `stepUpBegin` to obtain a fresh
   * challenge before completing.
   */
  async function handleStepUpSubmit(e: Event) {
    e.preventDefault();
    if (isResetting || !targetUserId) return;

    isResetting = true;
    stepUpError = null;

    try {
      const begin = await stepUpBegin(STEP_UP_SCOPE);
      const complete = await stepUpComplete(begin.challenge_id, {
        password: stepUpPassword,
        totpCode: stepUpTotpCode.trim(),
      });

      // Security: the high-privilege admin_recovery JWT is consumed inline
      // here and never re-read from storage for this flow, so it MUST NOT be
      // persisted. Pass it straight through to the reset call.
      const result = await adminApi.resetUserPassword(
        targetUserId,
        complete.step_up_token
      );

      temporaryPassword = result.temporary_password;
      temporaryPasswordExpiresAt = result.expires_at;
      showStepUpModal = false;
      stepUpPassword = '';
      stepUpTotpCode = '';
      openRevealDialog();
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === 'step_up_2fa_not_enrolled') {
          // Operator has no TOTP factor enrolled — enrol then retry.
          stepUpError = m.admin_password_reset_not_enrolled();
        } else if (err.code === 'step_up_factor_set_changed') {
          // The operator's factor set changed mid-ceremony; the next submit
          // re-runs stepUpBegin, so a plain retry recovers.
          stepUpError = m.admin_password_reset_factor_changed_retry();
        } else if (err.status === 409) {
          // Other 409s: fall back to the not-enrolled remediation (the only
          // other documented 409 cause for this flow).
          stepUpError = m.admin_password_reset_not_enrolled();
        } else if (err.code === 'must_change_password') {
          // The OPERATOR is themselves in forced-change — waiting never
          // helps; they must change their own password first.
          stepUpError = m.admin_password_reset_self_forced_change();
        } else if (err.code === 'two_factor_locked' || err.status === 429) {
          // 2FA lockout cooldown / rate limit — waiting is the remedy.
          stepUpError = m.admin_password_reset_cooldown();
        } else if (err.status === 423) {
          // Other 423s without a recognised code — generic cooldown.
          stepUpError = m.admin_password_reset_cooldown();
        } else if (
          err.code === 'step_up_factor_invalid' ||
          err.status === 401
        ) {
          stepUpError = m.admin_password_reset_factor_invalid();
        } else {
          stepUpError = err.detail || err.message;
        }
      } else {
        stepUpError = m.admin_password_reset_factor_invalid();
      }
    } finally {
      isResetting = false;
    }
  }

  /**
   * Open the one-time reveal dialog and arm a 60s auto-wipe.
   */
  function openRevealDialog() {
    showRevealDialog = true;
    copied = false;
    clearedNotice = null;
    if (revealTimeout) clearTimeout(revealTimeout);
    revealTimeout = setTimeout(() => {
      // Auto-wipe surfaces a brief notice so the operator knows the secret
      // was hidden on a timer (not lost to a bug).
      wipeTemporaryPassword({ notify: true });
    }, 60_000);
  }

  /**
   * Wipe the revealed password, close the dialog, and best-effort clear
   * the clipboard so the secret does not linger.
   *
   * When `notify` is set (the 60s auto-wipe path) a brief roster notice
   * tells the operator the temporary password was hidden on a timer.
   */
  function wipeTemporaryPassword(options: { notify?: boolean } = {}) {
    temporaryPassword = '';
    temporaryPasswordExpiresAt = '';
    copied = false;
    showRevealDialog = false;
    if (revealTimeout) {
      clearTimeout(revealTimeout);
      revealTimeout = null;
    }
    if (typeof navigator !== 'undefined' && navigator.clipboard) {
      navigator.clipboard.writeText('').catch(() => {
        /* best effort */
      });
    }
    // One-shot recovery flow: do not leave the step-up JWT in storage.
    clearStepUpToken(STEP_UP_SCOPE);
    targetUserId = null;
    targetUserEmail = '';
    clearedNotice = options.notify ? m.admin_password_reset_cleared() : null;
  }

  /**
   * Manual close of the reveal dialog (same teardown as the timeout, but
   * without the auto-wipe notice — the operator chose to close it).
   */
  function closeRevealDialog() {
    wipeTemporaryPassword();
  }

  /**
   * Copy the temporary password to the clipboard with a 2s "Copied" flip.
   */
  async function copyTemporaryPassword() {
    if (!temporaryPassword) return;
    try {
      await navigator.clipboard.writeText(temporaryPassword);
      copied = true;
      setTimeout(() => {
        copied = false;
      }, 2000);
    } catch {
      /* clipboard unavailable — ignore */
    }
  }

  // Clean up the auto-wipe timer if the component unmounts mid-reveal.
  $effect(() => {
    return () => {
      if (revealTimeout) {
        clearTimeout(revealTimeout);
        revealTimeout = null;
      }
    };
  });

  /**
   * Load users
   */
  async function loadUsers() {
    isLoading = true;
    error = null;

    try {
      const response = await adminApi.listUsers({
        page,
        limit,
        search: search.trim() || undefined,
      });
      users = response.items;
      total = response.total;
    } catch (err) {
      if (err instanceof ApiError) {
        error = err.detail || err.message;
      } else {
        error = m.admin_users_error_load();
      }
    } finally {
      isLoading = false;
    }
  }

  // Load users on mount and when filters change
  $effect(() => {
    loadUsers();
  });

  /**
   * Handle search input
   */
  function handleSearch(event: Event) {
    const target = event.target as HTMLInputElement;
    search = target.value;

    // Reset to first page on search
    page = 1;

    // Debounce search
    if (searchTimeout) {
      clearTimeout(searchTimeout);
    }
    searchTimeout = setTimeout(() => {
      loadUsers();
    }, 300);
  }

  /**
   * Change page
   */
  function changePage(newPage: number) {
    page = newPage;
  }

  /**
   * Calculate total pages
   */
  const totalPages = $derived(Math.ceil(total / limit));

  /**
   * Format date
   */
  function formatDate(dateString: string): string {
    return new Date(dateString).toLocaleString(getLocale());
  }

  /**
   * Format optional date (last_login_at may be null)
   */
  function formatOptionalDate(dateString: string | null): string {
    return dateString ? formatDate(dateString) : '-';
  }
</script>

<svelte:head>
  <title>{m.admin_users_heading()} - Admin - Echoroo</title>
</svelte:head>

<div class="px-8 py-6">
  <!-- Header -->
  <div class="mb-6">
    <h1 class="text-3xl font-bold text-stone-900">{m.admin_users_heading()}</h1>
    <p class="mt-2 text-sm text-stone-600">{m.admin_users_description()}</p>
  </div>

  <!-- Error Message -->
  {#if error}
    <div class="mb-6 rounded-md bg-danger-light p-4" role="alert">
      <div class="flex">
        <div class="flex-shrink-0">
          <svg
            class="h-5 w-5 text-danger"
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
          <p class="text-sm font-medium text-danger">{error}</p>
        </div>
      </div>
    </div>
  {/if}

  <!-- Auto-wipe notice (temporary password hidden after the 60s timer) -->
  {#if clearedNotice}
    <div
      class="mb-6 rounded-md bg-info-light p-4"
      role="status"
      data-testid="admin-password-cleared-notice"
    >
      <p class="text-sm font-medium text-info">{clearedNotice}</p>
    </div>
  {/if}

  <!-- Manage Superusers hint -->
  <div class="mb-6 rounded-md border border-card bg-surface-card p-4 text-sm text-stone-600">
    {m.admin_users_manage_su_hint()}
    <a
      href="/admin/superusers"
      class="ml-1 font-medium text-primary-700 underline-offset-2 hover:underline dark:text-primary-400"
    >
      {m.admin_users_manage_su_link()}
    </a>
  </div>

  <!-- Filters -->
  <div class="mb-6 flex flex-col gap-4 sm:flex-row">
    <!-- Search -->
    <div class="flex-1">
      <label for="search" class="sr-only">{m.admin_users_search_placeholder()}</label>
      <div class="relative">
        <div class="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
          <svg class="h-5 w-5 text-stone-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
            />
          </svg>
        </div>
        <input
          type="search"
          id="search"
          value={search}
          oninput={handleSearch}
          placeholder={m.admin_users_search_placeholder()}
          class="block w-full rounded-lg border border-stone-300 bg-surface-card py-2 pl-10 pr-3 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
        />
      </div>
    </div>
  </div>

  <!-- Users Table -->
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
  {:else if users.length === 0}
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
          d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"
        />
      </svg>
      <h3 class="mt-2 text-sm font-medium text-stone-900">{m.admin_users_empty_title()}</h3>
      <p class="mt-1 text-sm text-stone-500">{m.admin_users_empty_description()}</p>
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
                {m.admin_users_table_email()}
              </th>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-stone-500"
              >
                {m.admin_users_table_display_name()}
              </th>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-stone-500"
              >
                {m.admin_users_table_role()}
              </th>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-stone-500"
              >
                {m.admin_users_table_created()}
              </th>
              <th
                scope="col"
                class="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-stone-500"
              >
                {m.admin_users_table_last_login()}
              </th>
              <th
                scope="col"
                class="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-stone-500"
              >
                {m.admin_password_reset_actions_column()}
              </th>
            </tr>
          </thead>
          <tbody class="divide-y divide-stone-200 bg-surface-card">
            {#each users as user (user.id)}
              <tr class="hover:bg-stone-50">
                <!-- Email -->
                <td class="whitespace-nowrap px-6 py-4">
                  <div class="text-sm font-medium text-stone-900">{user.email}</div>
                </td>

                <!-- Display Name -->
                <td class="whitespace-nowrap px-6 py-4 text-sm text-stone-900">
                  {user.display_name || '-'}
                </td>

                <!-- Role -->
                <td class="whitespace-nowrap px-6 py-4">
                  {#if user.is_superuser}
                    <span
                      class="inline-flex items-center rounded-full bg-primary-100 px-2.5 py-0.5 text-xs font-medium text-primary-800 dark:bg-primary-900/30 dark:text-primary-400"
                    >
                      {m.admin_users_role_superuser()}
                    </span>
                  {:else}
                    <span
                      class="inline-flex items-center rounded-full bg-stone-100 px-2.5 py-0.5 text-xs font-medium text-stone-800 dark:bg-stone-700 dark:text-stone-300"
                    >
                      {m.admin_users_role_user()}
                    </span>
                  {/if}
                </td>

                <!-- Created -->
                <td class="whitespace-nowrap px-6 py-4 text-sm text-stone-500">
                  {formatDate(user.created_at)}
                </td>

                <!-- Last login -->
                <td class="whitespace-nowrap px-6 py-4 text-sm text-stone-500">
                  {formatOptionalDate(user.last_login_at)}
                </td>

                <!-- Actions -->
                <td class="whitespace-nowrap px-6 py-4 text-right">
                  <button
                    type="button"
                    onclick={() => openStepUpModal(user)}
                    data-testid={`admin-reset-password-${user.id}`}
                    class="rounded-md border border-stone-300 bg-surface-card px-3 py-1.5 text-sm font-medium text-stone-700 hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2"
                  >
                    {m.admin_password_reset_button()}
                  </button>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Pagination -->
    {#if totalPages > 1}
      <div class="mt-6 flex items-center justify-between">
        <div class="text-sm text-stone-700">
          {m.admin_users_pagination_showing({
            from: (page - 1) * limit + 1,
            to: Math.min(page * limit, total),
            total,
          })}
        </div>

        <div class="flex space-x-2">
          <button
            onclick={() => changePage(page - 1)}
            disabled={page === 1}
            class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {m.admin_users_pagination_previous()}
          </button>

          {#each Array.from({ length: totalPages }, (_, i) => i + 1) as pageNum}
            {#if pageNum === 1 || pageNum === totalPages || (pageNum >= page - 1 && pageNum <= page + 1)}
              <button
                onclick={() => changePage(pageNum)}
                class="rounded-md px-4 py-2 text-sm font-medium {pageNum === page
                  ? 'bg-primary-600 text-white dark:bg-primary-500 dark:text-stone-50'
                  : 'border border-stone-300 bg-surface-card text-stone-700 hover:bg-stone-50'}"
              >
                {pageNum}
              </button>
            {:else if pageNum === page - 2 || pageNum === page + 2}
              <span class="px-2 text-stone-500">...</span>
            {/if}
          {/each}

          <button
            onclick={() => changePage(page + 1)}
            disabled={page === totalPages}
            class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {m.admin_users_pagination_next()}
          </button>
        </div>
      </div>
    {/if}
  {/if}
</div>

<!-- spec/011 US4: step-up ceremony modal (password + TOTP, no WebAuthn) -->
{#if showStepUpModal}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    role="dialog"
    aria-modal="true"
    aria-labelledby="step-up-modal-title"
    tabindex="-1"
    onclick={(event) => {
      if (event.target === event.currentTarget && !isResetting) closeStepUpModal();
    }}
  >
    <div
      use:focusTrap={{ onClose: closeStepUpModal }}
      class="w-full max-w-md rounded-lg bg-surface-card shadow-xl"
      data-testid="step-up-modal"
    >
      <div class="border-b border-stone-200 px-6 py-4 dark:border-stone-700">
        <h2
          id="step-up-modal-title"
          class="m-0 text-lg font-semibold text-stone-900 dark:text-stone-100"
        >
          {m.admin_password_reset_modal_title()}
        </h2>
        <p class="mt-1 text-sm text-stone-600 dark:text-stone-400">
          {m.admin_password_reset_modal_subtitle({ email: targetUserEmail })}
        </p>
      </div>

      <form onsubmit={handleStepUpSubmit}>
        <div class="space-y-4 p-6">
          <!-- Operator password -->
          <div>
            <label
              for="step-up-password"
              class="block text-sm font-medium text-stone-700 dark:text-stone-300"
            >
              {m.admin_password_reset_password_label()}
            </label>
            <input
              id="step-up-password"
              type="password"
              autocomplete="current-password"
              required
              bind:value={stepUpPassword}
              disabled={isResetting}
              data-testid="step-up-password-input"
              class="mt-1 block w-full appearance-none rounded-md border border-stone-300 px-3 py-2 text-stone-900 placeholder-stone-500 focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:bg-stone-100 disabled:cursor-not-allowed sm:text-sm"
            />
          </div>

          <!-- TOTP code (6-digit, TOTP-only) -->
          <div>
            <label
              for="step-up-totp"
              class="block text-sm font-medium text-stone-700 dark:text-stone-300"
            >
              {m.admin_password_reset_totp_label()}
            </label>
            <input
              id="step-up-totp"
              type="text"
              inputmode="numeric"
              autocomplete="one-time-code"
              required
              bind:value={stepUpTotpCode}
              disabled={isResetting}
              data-testid="step-up-totp-input"
              class="mt-1 block w-full appearance-none rounded-md border border-stone-300 px-3 py-2 text-center font-mono text-lg tracking-widest text-stone-900 placeholder-stone-400 focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:bg-stone-100 disabled:cursor-not-allowed sm:text-sm"
              placeholder="000000"
            />
          </div>

          {#if stepUpError}
            <div
              role="alert"
              class="rounded-md border border-danger/30 bg-danger-light p-3 text-sm text-danger"
              data-testid="step-up-error"
            >
              {stepUpError}
            </div>
          {/if}
        </div>

        <div
          class="flex justify-end gap-3 border-t border-stone-200 px-6 py-4 dark:border-stone-700"
        >
          <button
            type="button"
            onclick={closeStepUpModal}
            disabled={isResetting}
            class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {m.common_cancel()}
          </button>
          <button
            type="submit"
            disabled={isResetting || !stepUpPassword || !stepUpTotpCode.trim()}
            data-testid="step-up-submit"
            class="rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
          >
            {m.admin_password_reset_submit()}
          </button>
        </div>
      </form>
    </div>
  </div>
{/if}

<!-- spec/011 US4: one-time temporary-password reveal dialog -->
{#if showRevealDialog}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    role="dialog"
    aria-modal="true"
    aria-labelledby="reveal-dialog-title"
    tabindex="-1"
    onclick={(event) => {
      if (event.target === event.currentTarget) closeRevealDialog();
    }}
  >
    <div
      use:focusTrap={{ onClose: closeRevealDialog }}
      class="w-full max-w-md rounded-lg bg-surface-card p-6 shadow-xl"
    >
      <h2
        id="reveal-dialog-title"
        class="mb-4 text-lg font-semibold text-stone-900 dark:text-stone-100"
      >
        {m.admin_password_reset_revealed_title()}
      </h2>

      <!-- Warning -->
      <div class="mb-4 rounded-md bg-warning-light p-4">
        <div class="flex">
          <svg
            class="h-5 w-5 flex-shrink-0 text-warning"
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 20 20"
            fill="currentColor"
            aria-hidden="true"
          >
            <path
              fill-rule="evenodd"
              d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z"
              clip-rule="evenodd"
            />
          </svg>
          <p class="ml-3 text-sm text-warning">
            {m.admin_password_reset_revealed_warning()}
          </p>
        </div>
      </div>

      <!-- Temporary password display -->
      <div class="mb-2">
        <div class="flex items-center gap-2">
          <input
            type="text"
            value={temporaryPassword}
            readonly
            data-testid="temp-password-reveal"
            class="w-full rounded-md border border-stone-300 bg-stone-50 px-3 py-2 font-mono text-sm text-stone-900"
          />
          <button
            type="button"
            onclick={copyTemporaryPassword}
            data-testid="temp-password-copy"
            class="flex-shrink-0 rounded-md border border-stone-300 bg-surface-card px-3 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2"
          >
            {copied ? m.admin_password_reset_copied() : m.admin_password_reset_copy_button()}
          </button>
        </div>
        {#if temporaryPasswordExpiresAt}
          <p class="mt-2 text-xs text-stone-500">
            {m.admin_password_reset_expires_hint({
              expiresAt: formatDate(temporaryPasswordExpiresAt),
            })}
          </p>
        {/if}
      </div>

      <!-- Close button -->
      <div class="mt-4 flex justify-end">
        <button
          type="button"
          onclick={closeRevealDialog}
          class="rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
        >
          {m.token_dialog_done()}
        </button>
      </div>
    </div>
  </div>
{/if}
