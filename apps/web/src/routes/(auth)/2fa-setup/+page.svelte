<script lang="ts">
  /**
   * Two-factor authentication enrollment page (Phase 4 redesign).
   *
   * This page lives in the (auth) route group so first-login users — who
   * have authenticated their password but have NOT yet established a
   * session — can reach it. The (app) layout's auth guard would otherwise
   * redirect them back to /login before they could read the interim_token
   * from sessionStorage.
   *
   * Flow:
   *   1. Read `interim_token` from sessionStorage (set by login page).
   *   2. POST /web-api/v1/auth/2fa/setup/totp -> secret + provisioning_uri.
   *   3. Render QR code + secret. User enters their TOTP code.
   *   4. POST /2fa/setup/totp/confirm -> backup codes + session cookies.
   *   5. Show backup codes ONCE, gated by an "I've saved them" checkbox.
   */

  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import QRCode from 'qrcode';
  import {
    setupTotp,
    confirmTotpSetup,
    WebAuthError,
    type TotpSetupResponse,
  } from '$lib/api/web-auth';
  import { ApiError, apiClient } from '$lib/api/client';
  import { authStore } from '$lib/stores/auth.svelte';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';
  import type { User } from '$lib/types';

  type Phase = 'loading' | 'enroll_form' | 'enroll_show_codes';

  let phase = $state<Phase>('loading');
  let setupData = $state<TotpSetupResponse | null>(null);
  let qrDataUrl = $state<string | null>(null);
  let totpCode = $state('');
  let backupCodes = $state<string[]>([]);
  let savedConfirmed = $state(false);
  let error = $state<string | null>(null);
  let isSubmitting = $state(false);
  let secretCopied = $state(false);

  onMount(async () => {
    const interimToken =
      typeof window !== 'undefined'
        ? window.sessionStorage.getItem('echoroo.interim_token')
        : null;

    if (!interimToken) {
      error = m.auth_two_factor_missing_interim_token();
      phase = 'enroll_form';
      return;
    }

    try {
      const result = await setupTotp(interimToken);
      setupData = result;
      qrDataUrl = await QRCode.toDataURL(result.provisioning_uri, {
        width: 240,
        margin: 1,
        errorCorrectionLevel: 'M',
      });
      phase = 'enroll_form';
    } catch (err) {
      handleError(err);
      phase = 'enroll_form';
    }
  });

  async function handleConfirm(e: Event) {
    e.preventDefault();
    if (!setupData) {
      error = m.auth_two_factor_setup_failed();
      return;
    }
    if (!totpCode.trim()) {
      error = m.auth_two_factor_invalid_code();
      return;
    }

    isSubmitting = true;
    error = null;

    try {
      const result = await confirmTotpSetup(
        setupData.next_interim_token,
        setupData.secret,
        totpCode.trim(),
      );
      backupCodes = result.backup_codes;
      apiClient.setAccessToken(result.access_token);
      // Best-effort fetch of the current user — failures are non-fatal here
      // because the dashboard guard will retry via authStore.initialize().
      // Targets the BFF mirror (``/web-api/v1/users/me``) so the
      // freshly-issued session cookie alone authenticates the call.
      try {
        const user = await apiClient.get<User>('/web-api/v1/users/me');
        authStore.setUser(user);
      } catch {
        // ignore
      }
      // Clear the interim_token from sessionStorage now that 2FA is enabled.
      if (typeof window !== 'undefined') {
        window.sessionStorage.removeItem('echoroo.interim_token');
      }
      phase = 'enroll_show_codes';
    } catch (err) {
      handleError(err);
    } finally {
      isSubmitting = false;
    }
  }

  function copySecret() {
    if (!setupData || typeof navigator === 'undefined') return;
    navigator.clipboard?.writeText(setupData.secret).then(() => {
      secretCopied = true;
      setTimeout(() => (secretCopied = false), 2000);
    });
  }

  function downloadBackupCodes() {
    if (typeof window === 'undefined') return;
    const content = `Echoroo two-factor backup codes\n\n${backupCodes.join('\n')}\n\nKeep these codes safe. Each can be used once if you lose access to your authenticator app.\n`;
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'echoroo-backup-codes.txt';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  async function handleContinue() {
    await goto(localizeHref('/dashboard'));
  }

  function handleError(err: unknown) {
    if (err instanceof WebAuthError) {
      if (err.status === 429) {
        const seconds = err.retryAfterSeconds() ?? 60;
        error = m.auth_two_factor_rate_limited({ seconds: String(seconds) });
      } else if (err.status === 423) {
        const seconds = err.retryAfterSeconds() ?? 900;
        error = m.auth_two_factor_locked({ seconds: String(seconds) });
      } else if (err.status === 401) {
        error = m.auth_two_factor_invalid_code();
      } else {
        error = err.detail || err.message;
      }
    } else if (err instanceof ApiError) {
      error = err.detail || err.message;
    } else {
      error = m.auth_two_factor_setup_failed();
    }
  }
</script>

<svelte:head>
  <title>{m.auth_two_factor_page_title()}</title>
</svelte:head>

<div class="mx-auto w-full max-w-2xl px-4 py-10">
  {#if phase === 'loading'}
    <div class="flex items-center justify-center py-16">
      <svg
        class="h-8 w-8 animate-spin text-stone-400"
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
      >
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path
          class="opacity-75"
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
        ></path>
      </svg>
    </div>
  {:else if phase === 'enroll_form'}
    <h1 class="text-2xl font-extrabold text-stone-900">
      {m.auth_two_factor_setup_title()}
    </h1>
    <p class="mt-2 text-sm text-stone-600">
      {m.auth_two_factor_setup_subtitle()}
    </p>

    {#if setupData}
      <div class="mt-6 rounded-md border border-card bg-surface-card p-6">
        <p class="whitespace-pre-line text-sm text-stone-700">
          {m.auth_two_factor_qr_instructions()}
        </p>

        <div class="mt-4 flex flex-col items-center gap-4 sm:flex-row sm:items-start">
          {#if qrDataUrl}
            <img
              src={qrDataUrl}
              alt="2FA QR code"
              data-testid="two-factor-qr"
              class="h-60 w-60 rounded border border-stone-200 bg-white p-2"
            />
          {/if}

          <div class="flex-1">
            <p class="text-xs font-medium text-stone-600">
              {m.auth_two_factor_scan_qr_or_enter_secret()}
            </p>
            <code
              class="mt-2 block break-all rounded bg-stone-100 p-2 font-mono text-sm text-stone-800"
              data-testid="two-factor-secret"
            >
              {setupData.secret}
            </code>
            <button
              type="button"
              onclick={copySecret}
              class="mt-2 rounded px-2 py-1 text-xs font-medium text-primary-600 ring-1 ring-primary-200 hover:bg-primary-50"
            >
              {secretCopied
                ? m.auth_two_factor_secret_copied()
                : m.auth_two_factor_secret_copy()}
            </button>
          </div>
        </div>

        <form class="mt-6 space-y-4" onsubmit={handleConfirm}>
          <div>
            <label for="totpCode" class="block text-sm font-medium text-stone-700">
              {m.auth_two_factor_enter_code_label()}
            </label>
            <input
              id="totpCode"
              name="totpCode"
              type="text"
              inputmode="numeric"
              autocomplete="one-time-code"
              required
              maxlength="6"
              bind:value={totpCode}
              disabled={isSubmitting}
              data-testid="two-factor-setup-code-input"
              class="mt-1 block w-full appearance-none rounded-md border border-stone-300 px-3 py-2 text-center font-mono text-lg tracking-widest text-stone-900 placeholder-stone-400 focus:border-primary-500 focus:outline-none focus:ring-primary-500 disabled:bg-stone-100 disabled:cursor-not-allowed sm:text-sm"
              placeholder={m.auth_two_factor_enter_code_placeholder()}
            />
          </div>

          {#if error}
            <div class="rounded-md bg-danger-light p-3" role="alert" data-testid="two-factor-setup-error">
              <p class="text-sm font-medium text-danger">{error}</p>
            </div>
          {/if}

          <button
            type="submit"
            disabled={isSubmitting}
            data-testid="two-factor-confirm"
            class="w-full rounded-md border border-transparent bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:bg-stone-400 disabled:cursor-not-allowed dark:bg-primary-500 dark:hover:bg-primary-400"
          >
            {isSubmitting
              ? m.auth_two_factor_confirm_button_submitting()
              : m.auth_two_factor_confirm_button()}
          </button>
        </form>
      </div>
    {:else if error}
      <div class="mt-6 rounded-md bg-danger-light p-4" role="alert">
        <p class="text-sm font-medium text-danger">{error}</p>
        <a
          href={localizeHref('/login')}
          class="mt-2 inline-block text-sm font-medium text-primary-600 hover:text-primary-500"
        >
          {m.auth_two_factor_back_to_login()}
        </a>
      </div>
    {/if}
  {:else if phase === 'enroll_show_codes'}
    <h1 class="text-2xl font-extrabold text-stone-900">
      {m.auth_two_factor_backup_codes_title()}
    </h1>
    <div class="mt-4 rounded-md border border-warning/40 bg-warning/10 p-4">
      <p class="text-sm text-stone-800">
        {m.auth_two_factor_backup_codes_warning()}
      </p>
    </div>

    <ul
      class="mt-6 grid grid-cols-2 gap-2 rounded-md border border-stone-200 bg-stone-50 p-4 font-mono text-sm"
      data-testid="two-factor-backup-codes"
    >
      {#each backupCodes as code}
        <li class="rounded bg-white px-3 py-2 text-stone-800 ring-1 ring-stone-200">{code}</li>
      {/each}
    </ul>

    <div class="mt-4 flex flex-wrap gap-2">
      <button
        type="button"
        onclick={downloadBackupCodes}
        class="rounded-md border border-stone-300 bg-white px-3 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50"
      >
        {m.auth_two_factor_backup_codes_download()}
      </button>
    </div>

    <label class="mt-6 flex items-start gap-2 text-sm text-stone-700">
      <input
        type="checkbox"
        bind:checked={savedConfirmed}
        data-testid="backup-codes-saved"
        class="mt-1 h-4 w-4 rounded border-stone-300 text-primary-600 focus:ring-primary-500"
      />
      <span>{m.auth_two_factor_backup_codes_saved_confirm()}</span>
    </label>

    <button
      type="button"
      onclick={handleContinue}
      disabled={!savedConfirmed}
      data-testid="backup-codes-continue"
      class="mt-4 w-full rounded-md border border-transparent bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 disabled:bg-stone-400 disabled:cursor-not-allowed dark:bg-primary-500 dark:hover:bg-primary-400"
    >
      {m.auth_two_factor_backup_codes_continue()}
    </button>
  {/if}
</div>
