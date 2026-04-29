<script lang="ts">
  /**
   * WebAuthnGatePrompt — modal-style step-up prompt for destructive
   * superuser actions.
   *
   * Phase 15 Batch 5b R2 (Codex Major 1 fix, FR-111).
   *
   * Unlike ``WebAuthnPrompt`` (which drives the 2FA login challenge and
   * needs an ``interim_token``) this component triggers a frontend-only
   * UX gate: a fresh WebAuthn assertion ceremony that demands physical
   * presence on the hardware key before the wrapped admin action runs.
   *
   * Usage:
   *
   *   let gateOpen = $state(false);
   *   let pendingAction = $state<(() => Promise<void>) | null>(null);
   *
   *   function attemptRevoke(target) {
   *     pendingAction = async () => { await superuserApi.revoke(target.id); };
   *     gateOpen = true;
   *   }
   *
   *   <WebAuthnGatePrompt
   *     bind:isOpen={gateOpen}
   *     action={pendingAction}
   *     onSuccess={...}
   *     onCancel={...}
   *     onError={...}
   *   />
   */

  import {
    requireWebAuthn,
    WebAuthnGateError,
  } from '$lib/utils/webauthnGating';
  import { isWebAuthnSupported } from '$lib/api/webauthn';
  import { focusTrap } from '$lib/actions/focusTrap';
  import * as m from '$lib/paraglide/messages';

  interface Props {
    /** Controls visibility — caller toggles to show / hide the modal. */
    isOpen: boolean;
    /**
     * The destructive operation to run after the WebAuthn ceremony
     * succeeds.  ``null`` while the gate is dormant.
     */
    action: (() => Promise<void>) | null;
    /** Fired after the action completes successfully. */
    onSuccess?: () => void;
    /** Fired when the user cancels the WebAuthn prompt. */
    onCancel?: () => void;
    /** Fired when WebAuthn or the action throws.  Receives the error message. */
    onError?: (message: string) => void;
  }

  let { isOpen = $bindable(), action, onSuccess, onCancel, onError }: Props =
    $props();

  let isProcessing = $state(false);
  let localError = $state<string | null>(null);

  const supported = $derived(isWebAuthnSupported());

  async function handleContinue() {
    if (!action || isProcessing) return;
    isProcessing = true;
    localError = null;
    try {
      const ran = await requireWebAuthn(action);
      if (!ran) {
        localError = m.admin_superusers_webauthn_gate_cancelled();
        onCancel?.();
        return;
      }
      isOpen = false;
      onSuccess?.();
    } catch (err) {
      let reason = 'unknown';
      if (err instanceof WebAuthnGateError) {
        reason = err.message;
      } else if (err instanceof Error) {
        reason = err.message;
      }
      const message = m.admin_superusers_webauthn_gate_failed({ reason });
      localError = message;
      onError?.(message);
    } finally {
      isProcessing = false;
    }
  }

  function handleCancel() {
    if (isProcessing) return;
    localError = null;
    isOpen = false;
    onCancel?.();
  }
</script>

{#if isOpen}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    role="dialog"
    aria-modal="true"
    aria-labelledby="webauthn-gate-title"
    tabindex="-1"
    onclick={(event) => {
      if (event.target === event.currentTarget) handleCancel();
    }}
  >
    <div
      use:focusTrap={{ onClose: handleCancel }}
      class="w-full max-w-md rounded-lg bg-surface-card shadow-xl"
    >
      <div class="border-b border-stone-200 px-6 py-4 dark:border-stone-700">
        <h2
          id="webauthn-gate-title"
          class="m-0 text-lg font-semibold text-stone-900 dark:text-stone-100"
        >
          {m.admin_superusers_webauthn_gate_title()}
        </h2>
      </div>

      <div class="space-y-3 p-6 text-sm text-stone-700 dark:text-stone-300">
        <p class="m-0 leading-relaxed">
          {m.admin_superusers_webauthn_gate_description()}
        </p>

        {#if !supported}
          <div
            role="alert"
            class="rounded-md border border-warning/30 bg-warning-light p-3 text-xs text-warning"
          >
            {m.admin_superusers_webauthn_unsupported()}
          </div>
        {/if}

        {#if localError}
          <div
            role="alert"
            class="rounded-md border border-danger/30 bg-danger-light p-3 text-xs text-danger"
          >
            {localError}
          </div>
        {/if}
      </div>

      <div class="flex justify-end gap-3 border-t border-stone-200 px-6 py-4 dark:border-stone-700">
        <button
          type="button"
          onclick={handleCancel}
          disabled={isProcessing}
          class="rounded-md border border-stone-300 bg-surface-card px-4 py-2 text-sm font-medium text-stone-700 transition-colors hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {m.common_cancel()}
        </button>
        <button
          type="button"
          onclick={handleContinue}
          disabled={isProcessing || !supported || !action}
          class="rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isProcessing
            ? m.admin_superusers_webauthn_gate_in_progress()
            : m.admin_superusers_webauthn_gate_continue()}
        </button>
      </div>
    </div>
  </div>
{/if}
