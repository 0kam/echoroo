<script lang="ts">
  /**
   * WebAuthn assertion (verify) prompt component.
   *
   * Drives the `POST /web-api/v1/auth/2fa/webauthn/challenge` begin/complete
   * dance.  Used during the 2FA login challenge step for superusers.
   *
   * Per FR-111 superuser sessions MUST be backed by a hardware key.  This
   * component is a reusable replacement for the TOTP input on superuser
   * accounts.  Callers in the (auth) login flow pass the
   * `2fa_challenge`-scoped interim_token and receive the resulting
   * `access_token` on success.
   */

  import {
    verifyWebAuthnCredential,
    isWebAuthnSupported,
  } from '$lib/api/webauthn';
  import { ApiError } from '$lib/api/client';
  import * as m from '$lib/paraglide/messages';

  interface Props {
    /** Fresh `2fa_challenge`-scoped interim token. */
    interimToken: string;
    /** Disable the verify button while parent flow is in flight. */
    disabled?: boolean;
    /** Called with the issued access token on success. */
    onSuccess?: (result: { access_token: string; expires_in: number }) => void;
    /** Called with an error message on failure. */
    onError?: (message: string) => void;
  }

  let { interimToken, disabled = false, onSuccess, onError }: Props = $props();

  let isProcessing = $state(false);
  let localError = $state<string | null>(null);

  const supported = $derived(isWebAuthnSupported());

  async function handleVerify() {
    if (!interimToken) {
      localError = m.admin_superusers_webauthn_missing_interim_token();
      return;
    }
    isProcessing = true;
    localError = null;
    try {
      const result = await verifyWebAuthnCredential(interimToken);
      onSuccess?.(result);
    } catch (err) {
      let message: string = m.admin_superusers_webauthn_verify_failed();
      if (err instanceof ApiError) {
        message = err.detail || err.message || message;
      } else if (err instanceof Error) {
        message = err.message;
      }
      localError = message;
      onError?.(message);
    } finally {
      isProcessing = false;
    }
  }
</script>

<div class="rounded-md border border-card bg-surface-card p-4">
  <h3 class="m-0 mb-2 text-sm font-semibold text-stone-900 dark:text-stone-100">
    {m.admin_superusers_webauthn_verify_heading()}
  </h3>
  <p class="m-0 mb-3 text-xs text-stone-600 dark:text-stone-400">
    {m.admin_superusers_webauthn_verify_description()}
  </p>

  {#if !supported}
    <div
      role="alert"
      class="rounded-md border border-warning/30 bg-warning-light p-3 text-xs text-warning"
    >
      {m.admin_superusers_webauthn_unsupported()}
    </div>
  {:else}
    <button
      type="button"
      onclick={handleVerify}
      disabled={disabled || isProcessing || !supported}
      class="rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {isProcessing
        ? m.admin_superusers_webauthn_verify_in_progress()
        : m.admin_superusers_webauthn_verify_button()}
    </button>
    {#if localError}
      <div
        role="alert"
        class="mt-2 rounded-md border border-danger/30 bg-danger-light p-2 text-xs text-danger"
      >
        {localError}
      </div>
    {/if}
  {/if}
</div>
