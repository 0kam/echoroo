<script lang="ts">
  /**
   * Initial Setup Wizard Page
   * Create first administrator account
   */

  import { goto } from '$app/navigation';
  import QRCode from 'qrcode';
  import {
    initializeSetup,
    type SetupCompleteResponse,
    type SetupInitializeRequest,
  } from '$lib/api/setup';
  import { ApiError } from '$lib/api/client';
  import { localizeHref } from '$lib/paraglide/runtime';
  import * as m from '$lib/paraglide/messages';

  const MIN_PASSWORD_LENGTH = 16;
  type CopyField = 'totp_secret' | 'totp_uri' | 'bootstrap_token';

  // Form state using Svelte 5 runes
  let email = $state('');
  let password = $state('');
  let confirmPassword = $state('');
  let displayName = $state('');
  let isLoading = $state(false);
  let errorMessage = $state<string | null>(null);
  let setupResult = $state<SetupCompleteResponse | null>(null);
  let qrCodeDataUrl = $state<string | null>(null);
  let copiedField = $state<CopyField | null>(null);
  let copyErrorMessage = $state<string | null>(null);

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
    if (value.length < MIN_PASSWORD_LENGTH) {
      return m.error_password_too_short();
    }
    return null;
  }

  function formatExpiration(value: string): string {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date(value));
  }

  function selectCopyField(event: FocusEvent) {
    const target = event.currentTarget;
    if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) {
      target.select();
    }
  }

  function copyWithExecCommand(value: string): boolean {
    const textarea = document.createElement('textarea');
    textarea.value = value;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.top = '0';
    textarea.style.left = '0';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();

    try {
      return document.execCommand('copy');
    } catch {
      return false;
    } finally {
      document.body.removeChild(textarea);
    }
  }

  async function copyToClipboard(value: string, field: CopyField) {
    copyErrorMessage = null;
    let copied = false;

    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value);
        copied = true;
      }
    } catch {
      copied = false;
    }

    if (!copied) {
      copied = copyWithExecCommand(value);
    }

    if (copied) {
      copiedField = field;
      window.setTimeout(() => {
        if (copiedField === field) {
          copiedField = null;
        }
      }, 2000);
      return;
    }

    copiedField = null;
    copyErrorMessage = m.setup_copy_failed_message();
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
      const result = await initializeSetup(requestData);
      setupResult = result;
      qrCodeDataUrl = await QRCode.toDataURL(result.totp_provisioning_uri, {
        margin: 1,
        width: 192,
      });
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

<div class="min-h-screen bg-gradient-to-br from-primary-50 to-primary-100 flex items-center justify-center px-4 sm:px-6 lg:px-8">
  <div class={setupResult ? 'max-w-2xl w-full' : 'max-w-md w-full'}>
    <!-- Card Container -->
    <div class="bg-surface-card shadow-xl rounded-lg p-8">
      {#if setupResult}
        <!-- Bootstrap Artifacts -->
        <div class="text-center mb-8">
          <h1 class="text-3xl font-bold text-stone-900 mb-2">{m.setup_success_title()}</h1>
          <p class="text-stone-600">{m.setup_success_subtitle()}</p>
        </div>

        {#if copyErrorMessage}
          <div class="mb-6 rounded-md border border-danger/20 bg-danger-light px-4 py-3 text-danger" role="alert">
            <p class="text-sm">{copyErrorMessage}</p>
          </div>
        {/if}

        <div class="grid gap-6 md:grid-cols-[auto_1fr] md:items-start">
          <div class="flex justify-center">
            {#if qrCodeDataUrl}
              <img
                src={qrCodeDataUrl}
                alt={m.setup_totp_qr_alt()}
                class="h-48 w-48 rounded-md border border-stone-200 bg-white p-2"
              />
            {/if}
          </div>

          <div class="space-y-4">
            <div>
              <div class="flex items-center justify-between gap-3">
                <p class="text-sm font-medium text-stone-700">{m.setup_totp_secret_label()}</p>
                <button
                  type="button"
                  onclick={() => copyToClipboard(setupResult!.totp_secret_base32, 'totp_secret')}
                  class="rounded-md border border-stone-300 px-2 py-1 text-xs font-medium text-stone-700 hover:bg-stone-50"
                >
                  {copiedField === 'totp_secret' ? m.setup_copied() : m.setup_copy()}
                </button>
              </div>
              <input
                value={setupResult.totp_secret_base32}
                readonly
                onfocus={selectCopyField}
                class="mt-1 w-full rounded-md border border-stone-200 bg-stone-50 px-3 py-2 font-mono text-sm text-stone-900"
              />
            </div>

            <div>
              <div class="flex items-center justify-between gap-3">
                <p class="text-sm font-medium text-stone-700">{m.setup_totp_uri_label()}</p>
                <button
                  type="button"
                  onclick={() => copyToClipboard(setupResult!.totp_provisioning_uri, 'totp_uri')}
                  class="rounded-md border border-stone-300 px-2 py-1 text-xs font-medium text-stone-700 hover:bg-stone-50"
                >
                  {copiedField === 'totp_uri' ? m.setup_copied() : m.setup_copy()}
                </button>
              </div>
              <textarea
                value={setupResult.totp_provisioning_uri}
                readonly
                rows="3"
                onfocus={selectCopyField}
                class="mt-1 w-full resize-y rounded-md border border-stone-200 bg-stone-50 px-3 py-2 font-mono text-xs text-stone-900"
              ></textarea>
            </div>
          </div>
        </div>

        <div class="mt-6 space-y-4">
          <div>
            <div class="flex items-center justify-between gap-3">
              <p class="text-sm font-medium text-stone-700">{m.setup_bootstrap_token_label()}</p>
              <button
                type="button"
                onclick={() => copyToClipboard(setupResult!.bootstrap_token, 'bootstrap_token')}
                class="rounded-md border border-stone-300 px-2 py-1 text-xs font-medium text-stone-700 hover:bg-stone-50"
              >
                {copiedField === 'bootstrap_token' ? m.setup_copied() : m.setup_copy()}
              </button>
            </div>
            <input
              value={setupResult.bootstrap_token}
              readonly
              onfocus={selectCopyField}
              class="mt-1 w-full rounded-md border border-stone-200 bg-stone-50 px-3 py-2 font-mono text-sm text-stone-900"
            />
            <p class="mt-1 text-xs text-stone-500">
              {m.setup_bootstrap_expires({
                expires: formatExpiration(setupResult.bootstrap_token_expires_at),
              })}
            </p>
          </div>

          <div>
            <p class="text-sm font-medium text-stone-700">{m.setup_webauthn_url_label()}</p>
            <a
              href={localizeHref(setupResult.webauthn_registration_url)}
              class="mt-1 block break-all rounded-md border border-stone-200 bg-stone-50 px-3 py-2 text-sm text-primary-700 hover:text-primary-800"
            >
              {setupResult.webauthn_registration_url}
            </a>
          </div>
        </div>

        <button
          type="button"
          onclick={() => goto(localizeHref('/login'))}
          class="mt-8 w-full py-3 px-4 bg-primary-600 hover:bg-primary-700 text-white font-medium rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 transition-colors dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
        >
          {m.setup_continue_to_login()}
        </button>
      {:else}
        <!-- Header -->
        <div class="text-center mb-8">
          <h1 class="text-3xl font-bold text-stone-900 mb-2">{m.setup_page_title()}</h1>
          <p class="text-stone-600">{m.setup_create_admin()}</p>
        </div>

        <!-- Error Message -->
        {#if errorMessage}
          <div class="mb-6 bg-danger-light border border-danger/20 text-danger px-4 py-3 rounded-md" role="alert">
            <p class="text-sm">{errorMessage}</p>
          </div>
        {/if}

        <!-- Setup Form -->
        <form onsubmit={handleSubmit} class="space-y-6">
          <!-- Email Field -->
          <div>
            <label for="email" class="block text-sm font-medium text-stone-700 mb-1">
              {m.setup_email_label()}
            </label>
            <input
              id="email"
              type="email"
              bind:value={email}
              onblur={handleEmailBlur}
              disabled={isLoading}
              class="w-full px-3 py-2 border border-stone-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 disabled:bg-stone-100 disabled:cursor-not-allowed"
              placeholder={m.setup_email_placeholder()}
              autocomplete="email"
            />
            {#if emailError}
              <p class="mt-1 text-sm text-danger">{emailError}</p>
            {/if}
          </div>

          <!-- Password Field -->
          <div>
            <label for="password" class="block text-sm font-medium text-stone-700 mb-1">
              {m.setup_password_label()}
            </label>
            <input
              id="password"
              type="password"
              bind:value={password}
              onblur={handlePasswordBlur}
              disabled={isLoading}
              class="w-full px-3 py-2 border border-stone-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 disabled:bg-stone-100 disabled:cursor-not-allowed"
              placeholder={m.setup_password_placeholder()}
              autocomplete="new-password"
            />
            {#if passwordError}
              <p class="mt-1 text-sm text-danger">{passwordError}</p>
            {:else}
              <p class="mt-1 text-xs text-stone-500">{m.setup_password_hint()}</p>
            {/if}
          </div>

          <!-- Confirm Password Field -->
          <div>
            <label for="confirmPassword" class="block text-sm font-medium text-stone-700 mb-1">
              {m.setup_confirm_password_label()}
            </label>
            <input
              id="confirmPassword"
              type="password"
              bind:value={confirmPassword}
              onblur={handleConfirmPasswordBlur}
              disabled={isLoading}
              class="w-full px-3 py-2 border border-stone-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 disabled:bg-stone-100 disabled:cursor-not-allowed"
              placeholder={m.setup_confirm_password_placeholder()}
              autocomplete="new-password"
            />
            {#if confirmPasswordError}
              <p class="mt-1 text-sm text-danger">{confirmPasswordError}</p>
            {/if}
          </div>

          <!-- Display Name Field (Optional) -->
          <div>
            <label for="displayName" class="block text-sm font-medium text-stone-700 mb-1">
              {m.setup_display_name_label()} <span class="text-stone-400 text-xs">{m.setup_display_name_optional()}</span>
            </label>
            <input
              id="displayName"
              type="text"
              bind:value={displayName}
              disabled={isLoading}
              class="w-full px-3 py-2 border border-stone-300 rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 disabled:bg-stone-100 disabled:cursor-not-allowed"
              placeholder={m.setup_display_name_placeholder()}
              autocomplete="name"
            />
          </div>

          <!-- Submit Button -->
          <button
            type="submit"
            disabled={isLoading}
            class="w-full py-3 px-4 bg-primary-600 hover:bg-primary-700 text-white font-medium rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 disabled:bg-stone-400 disabled:cursor-not-allowed transition-colors dark:bg-primary-500 dark:text-stone-50 dark:hover:bg-primary-400"
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
      {/if}
    </div>

    <!-- Footer Info -->
    {#if !setupResult}
      <div class="mt-6 text-center">
        <p class="text-sm text-stone-600">
          {m.setup_footer()}
        </p>
      </div>
    {/if}
  </div>
</div>
