<script lang="ts">
  /**
   * WebAuthn hardware key registration component (superuser-only).
   *
   * Drives the `POST /web-api/v1/auth/2fa/webauthn/register` begin/complete
   * dance via `@simplewebauthn/browser`.
   *
   * The backend requires an `interim_token` issued during a recent
   * authenticated flow (e.g. during 2FA setup, scope `webauthn_register`,
   * or the explicit `next_interim_token` returned from the begin call).
   * The caller must hand a fresh token in via the `interimToken` prop.
   */

  import {
    registerWebAuthnCredential,
    isWebAuthnSupported,
  } from '$lib/api/webauthn';
  import { ApiError } from '$lib/api/client';
  import * as m from '$lib/paraglide/messages';

  interface Props {
    /** Fresh `webauthn_register`-scoped interim token. */
    interimToken: string;
    /** Optional human-readable name for the credential. */
    name?: string;
    /** Disable the register button (e.g. while a parent flow is in flight). */
    disabled?: boolean;
    /** Called with the persisted credential metadata on success. */
    onSuccess?: (result: { credential_id: string; name: string }) => void;
    /** Called with an error message on failure. */
    onError?: (message: string) => void;
  }

  let {
    interimToken,
    name = '',
    disabled = false,
    onSuccess,
    onError,
  }: Props = $props();

  let isProcessing = $state(false);
  let localError = $state<string | null>(null);
  let success = $state<{ credential_id: string; name: string } | null>(null);

  const supported = $derived(isWebAuthnSupported());

  async function handleRegister() {
    if (!interimToken) {
      localError = m.admin_superusers_webauthn_missing_interim_token();
      return;
    }
    isProcessing = true;
    localError = null;
    try {
      const result = await registerWebAuthnCredential(
        interimToken,
        name?.trim() || undefined,
      );
      success = { credential_id: result.credential_id, name: result.name };
      onSuccess?.(success);
    } catch (err) {
      let message: string = m.admin_superusers_webauthn_register_failed();
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
    {m.admin_superusers_webauthn_register_heading()}
  </h3>
  <p class="m-0 mb-3 text-xs text-stone-600 dark:text-stone-400">
    {m.admin_superusers_webauthn_register_description()}
  </p>

  {#if !supported}
    <div
      role="alert"
      class="rounded-md border border-warning/30 bg-warning-light p-3 text-xs text-warning"
    >
      {m.admin_superusers_webauthn_unsupported()}
    </div>
  {:else if success}
    <div
      role="status"
      class="rounded-md border border-success/30 bg-success-light p-3 text-xs text-success"
    >
      {m.admin_superusers_webauthn_register_success({ name: success.name })}
    </div>
  {:else}
    <button
      type="button"
      onclick={handleRegister}
      disabled={disabled || isProcessing || !supported}
      class="rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {isProcessing
        ? m.admin_superusers_webauthn_register_in_progress()
        : m.admin_superusers_webauthn_register_button()}
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
