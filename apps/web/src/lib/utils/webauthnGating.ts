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

// ---------------------------------------------------------------------------
// Phase 16 Batch 6g-3: step-up token storage
// ---------------------------------------------------------------------------
//
// After the user completes a WebAuthn ceremony the backend
// (``POST /web-api/v1/auth/2fa/webauthn/challenge``) issues a 5-minute
// step-up JWT bound to ``scope='admin_destructive'``. Every subsequent
// destructive admin call MUST attach the token via ``X-Step-Up-Token``
// or the backend gate (``require_step_up_token``) returns 401/403.
//
// We persist the latest token in ``sessionStorage`` so:
//   * Tab refreshes inside the 5-minute window do not force a redundant
//     ceremony.
//   * The token is wiped on tab close — matching the spec's "one
//     hardware-touch per workflow" expectation.

const STEP_UP_STORAGE_KEY = 'echoroo.stepUpToken';

interface StoredStepUpToken {
  token: string;
  expiresAt: number; // ms epoch
  scope: string;
}

function loadStoredStepUpToken(): StoredStepUpToken | null {
  if (typeof sessionStorage === 'undefined') return null;
  try {
    const raw = sessionStorage.getItem(STEP_UP_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredStepUpToken;
    if (
      typeof parsed.token !== 'string' ||
      typeof parsed.expiresAt !== 'number' ||
      typeof parsed.scope !== 'string'
    ) {
      return null;
    }
    if (parsed.expiresAt <= Date.now()) return null;
    return parsed;
  } catch {
    return null;
  }
}

function persistStepUpToken(stored: StoredStepUpToken): void {
  if (typeof sessionStorage === 'undefined') return;
  sessionStorage.setItem(STEP_UP_STORAGE_KEY, JSON.stringify(stored));
}

/**
 * Clear the cached step-up token.
 *
 * The optional ``scope`` argument lets callers express intent (e.g.
 * ``clearStepUpToken('admin_recovery')`` after a one-shot recovery
 * flow). Storage is a single slot, so when a scope is supplied we only
 * clear it if the stored token matches that scope — otherwise an
 * unrelated active token (different scope) is left intact.
 */
export function clearStepUpToken(scope?: string): void {
  if (typeof sessionStorage === 'undefined') return;
  if (scope) {
    const stored = loadStoredStepUpToken();
    if (stored && stored.scope !== scope) return;
  }
  sessionStorage.removeItem(STEP_UP_STORAGE_KEY);
}

/**
 * Read the currently-cached step-up token, returning ``null`` when
 * absent or expired. Callers (e.g. ``superusers.ts`` request wrapper)
 * use this to attach the ``X-Step-Up-Token`` header. When the token
 * has expired or is missing the caller should re-prompt the user via
 * :func:`requireWebAuthn`.
 */
export function getActiveStepUpToken(
  scope: string = 'admin_destructive',
): string | null {
  const stored = loadStoredStepUpToken();
  if (!stored) return null;
  if (stored.scope !== scope) return null;
  return stored.token;
}

/**
 * Run the WebAuthn ceremony, then exchange the assertion at the
 * backend ``/web-api/v1/auth/2fa/webauthn/challenge`` endpoint to
 * obtain a fresh step-up token.
 *
 * Phase 16 Batch 6g-3 placeholder: end-to-end ceremony wiring with
 * the backend ``interim_token`` flow lives in a follow-up batch.
 * Today we still run the local presence ceremony for the UX gate;
 * the token retrieval is invoked here so tests can mock it. When the
 * full flow lands the body of this function will POST to the
 * challenge endpoint and capture the response's ``step_up_token``
 * field via the same path.
 */
export async function performWebAuthnAndCaptureStepUpToken(): Promise<{
  ran: boolean;
  token: string | null;
}> {
  const ok = await ensureHardwareKeyPresence();
  if (!ok) return { ran: false, token: null };
  // The legacy endpoint chain returns the step-up token alongside the
  // session refresh; in Phase 16 we surface it from the
  // ``/2fa/webauthn/challenge`` complete branch. The detailed wiring
  // (interim-token + assertion exchange) is the responsibility of the
  // 2FA login flow; this helper documents the contract for downstream
  // consumers and exposes ``getActiveStepUpToken`` for header
  // attachment.
  const cached = getActiveStepUpToken();
  return { ran: true, token: cached };
}

/**
 * Persist a step-up token captured from
 * ``WebAuthnChallengeCompleteResponse.step_up_token``. Call this from
 * the WebAuthn login completion path so destructive admin calls can
 * pick up the latest token automatically.
 */
export function rememberStepUpToken(payload: {
  token: string;
  expiresAt: string | number;
  scope: string;
}): void {
  const expiresMs =
    typeof payload.expiresAt === 'number'
      ? payload.expiresAt
      : Date.parse(payload.expiresAt);
  if (!Number.isFinite(expiresMs)) {
    throw new WebAuthnGateError(
      'step_up_expires_at could not be parsed as a date',
    );
  }
  persistStepUpToken({
    token: payload.token,
    expiresAt: expiresMs,
    scope: payload.scope,
  });
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
