/**
 * WebAuthn API client (Phase 8 endpoints, used by Phase 15 admin UI).
 *
 * The backend exposes two endpoints — both accept an `interim_token` plus
 * an optional `credential` payload:
 *   - `POST /web-api/v1/auth/2fa/webauthn/register` (begin / complete)
 *   - `POST /web-api/v1/auth/2fa/webauthn/challenge` (begin / complete)
 *
 * The "begin" call returns PublicKeyCredentialCreationOptions /
 * PublicKeyCredentialRequestOptions plus a fresh `next_interim_token` that
 * must be passed back to the matching "complete" call.
 *
 * This module wraps `@simplewebauthn/browser` so callers only deal with
 * the high-level register / verify functions.
 */

import {
  startRegistration,
  startAuthentication,
} from '@simplewebauthn/browser';
import { ApiError } from './client';

const BASE = '/web-api/v1/auth';

function resolveBaseUrl(): string {
  if (typeof window !== 'undefined') return '';
  return import.meta.env.PUBLIC_API_URL || 'http://localhost:8002';
}

interface BeginResponse {
  options: Record<string, unknown>;
  next_interim_token: string;
}

interface RegisterCompleteResponse {
  credential_id: string;
  name: string;
  registered_at: string;
}

interface ChallengeCompleteResponse {
  access_token: string;
  expires_in: number;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const url = `${resolveBaseUrl()}${BASE}${path}`;
  const response = await fetch(url, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    const message =
      (errorData && typeof errorData === 'object' && 'detail' in errorData
        ? typeof (errorData as { detail: unknown }).detail === 'string'
          ? ((errorData as { detail: string }).detail)
          : null
        : null) ?? 'WebAuthn request failed';
    throw new ApiError(message, response.status, message);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/**
 * Run the full WebAuthn registration ceremony.
 *
 * Caller passes the original `interim_token` (e.g. one with scope
 * `webauthn_register` issued during 2FA setup).  Returns the persisted
 * credential metadata.
 */
export async function registerWebAuthnCredential(
  interimToken: string,
  name?: string,
): Promise<RegisterCompleteResponse> {
  const begin = await postJson<BeginResponse>('/2fa/webauthn/register', {
    interim_token: interimToken,
  });

  // The browser API expects the options object exactly as returned by the
  // server.  `@simplewebauthn/browser` v13 expects the new
  // `optionsJSON` named argument.
  const credential = await startRegistration({
    optionsJSON: begin.options as never,
  });

  const complete = await postJson<RegisterCompleteResponse>(
    '/2fa/webauthn/register',
    {
      interim_token: begin.next_interim_token,
      credential,
      ...(name ? { name } : {}),
    },
  );
  return complete;
}

/**
 * Run the full WebAuthn authentication ceremony.
 *
 * Used during the 2FA login challenge step (interim_token scope
 * `2fa_challenge`).  Returns the access token + TTL on success.
 */
export async function verifyWebAuthnCredential(
  interimToken: string,
): Promise<ChallengeCompleteResponse> {
  const begin = await postJson<BeginResponse>('/2fa/webauthn/challenge', {
    interim_token: interimToken,
  });

  const credential = await startAuthentication({
    optionsJSON: begin.options as never,
  });

  const complete = await postJson<ChallengeCompleteResponse>(
    '/2fa/webauthn/challenge',
    {
      interim_token: begin.next_interim_token,
      credential,
    },
  );
  return complete;
}

/**
 * Best-effort feature detection for environments where WebAuthn is
 * unavailable (older browsers, http origins, missing platform support).
 */
export function isWebAuthnSupported(): boolean {
  if (typeof window === 'undefined') return false;
  return (
    typeof window.PublicKeyCredential === 'function' &&
    typeof navigator !== 'undefined' &&
    typeof navigator.credentials !== 'undefined'
  );
}
