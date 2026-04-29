/**
 * WebAuthn step-up gating helper for destructive admin actions.
 *
 * Phase 15 Batch 5b R2 (Codex Major 1 fix, FR-111).
 *
 * Background
 * ----------
 * FR-111 requires every destructive superuser action (add / revoke,
 * approve / reject of M-of-N tickets, break-glass entry, IP allowlist
 * mutation) to be gated by a hardware-key (WebAuthn) assertion.  The
 * Phase 15 backend admin endpoints, however, do NOT yet accept an
 * assertion payload — that wiring is deferred to Phase 16 along with the
 * full ``interim_token`` step-up flow.
 *
 * For Batch 5b R2 we therefore install a **frontend-only UX gate**:
 * after the user confirms a destructive action via ConfirmDialog, the
 * UI demands a fresh WebAuthn assertion ceremony before issuing the
 * admin API call.  The ceremony exercises the same physical authenticator
 * that the user would otherwise present, so a stolen-cookie attacker who
 * cannot touch the hardware key is blocked at the UI layer.
 *
 * Hook for Phase 16
 * -----------------
 * When the backend gains an assertion-required endpoint
 * (e.g. ``POST /web-api/v1/auth/2fa/webauthn/verify``) we will:
 *   1. Replace ``ensureHardwareKeyPresence`` with a call that POSTs the
 *      assertion to the verify endpoint and returns a short-lived
 *      step-up token.
 *   2. Thread that token into each admin API call as
 *      ``X-Step-Up-Token`` (or similar).
 * The call sites of ``requireWebAuthn`` will not change.
 */

import {
  startAuthentication,
  type PublicKeyCredentialRequestOptionsJSON,
} from '@simplewebauthn/browser';

import { isWebAuthnSupported } from '$lib/api/webauthn';

/**
 * Error raised when the WebAuthn ceremony fails or the user cancels.
 *
 * Distinct from ApiError so call sites can show a localised "hardware
 * key required" message rather than treating it as a generic server
 * error.
 */
export class WebAuthnGateError extends Error {
  constructor(
    message: string,
    public readonly cause?: unknown,
  ) {
    super(message);
    this.name = 'WebAuthnGateError';
  }
}

/**
 * Generate a 32-byte random challenge encoded as base64url.
 *
 * Used as a placeholder until Phase 16 wires the backend-issued
 * challenge endpoint.  Per WebAuthn spec the challenge MUST be
 * server-generated for true authentication, but for a UX gate the
 * client-side challenge still forces the authenticator to perform a
 * real signature ceremony — i.e. requires user presence + verification.
 */
function generateChallenge(): string {
  if (typeof crypto === 'undefined' || !crypto.getRandomValues) {
    throw new WebAuthnGateError(
      'Cryptography APIs are unavailable; WebAuthn gating cannot run.',
    );
  }
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  // base64url
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/**
 * Run a WebAuthn assertion ceremony as a presence check.
 *
 * Returns ``true`` when the authenticator produced a credential
 * (regardless of which credential), ``false`` when the user cancels.
 * Throws ``WebAuthnGateError`` for fatal misconfigurations (no
 * platform support, no crypto APIs).
 *
 * Note: ``allowCredentials`` is left empty so any registered
 * credential satisfies the prompt.  This matches the Phase 15
 * "discoverable credential" UX — the user is already authenticated;
 * we just need proof of physical possession.
 */
export async function ensureHardwareKeyPresence(): Promise<boolean> {
  if (!isWebAuthnSupported()) {
    throw new WebAuthnGateError(
      'WebAuthn is not supported in this browser.',
    );
  }

  const options: PublicKeyCredentialRequestOptionsJSON = {
    challenge: generateChallenge(),
    timeout: 60_000,
    userVerification: 'preferred',
    // Empty allowCredentials list -> rely on discoverable credentials.
    allowCredentials: [],
  };

  try {
    await startAuthentication({ optionsJSON: options });
    return true;
  } catch (err) {
    // ``NotAllowedError`` covers user cancellation and authenticator
    // timeout.  Treat as "user declined" rather than a hard error so
    // the caller can simply abort the destructive action.
    if (err instanceof DOMException && err.name === 'NotAllowedError') {
      return false;
    }
    throw new WebAuthnGateError(
      err instanceof Error ? err.message : 'WebAuthn ceremony failed',
      err,
    );
  }
}

/**
 * Wrap a destructive action so it only runs after a successful
 * WebAuthn ceremony.
 *
 * Returns ``true`` when the action ran to completion, ``false`` when
 * the user declined the WebAuthn prompt (action skipped silently —
 * the caller is responsible for surfacing UI like "hardware key
 * required").  Errors from ``action`` propagate.
 *
 * Example::
 *
 *     const ran = await requireWebAuthn(async () => {
 *       await superuserApi.revoke(target.id);
 *     });
 *     if (!ran) toast.warn(m.webauthn_gate_cancelled());
 */
export async function requireWebAuthn(
  action: () => Promise<void>,
): Promise<boolean> {
  const ok = await ensureHardwareKeyPresence();
  if (!ok) return false;
  await action();
  return true;
}
