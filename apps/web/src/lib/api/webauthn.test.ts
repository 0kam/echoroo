import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * Phase 15 Batch 5b R3 (Codex Minor 3 fix): ``postJson`` inside
 * ``webauthn.ts`` must accept both legacy string ``detail`` payloads
 * and Phase 8 polish round 2 structured ``{ error_code, message }``
 * dict detail payloads.
 *
 * We exercise the public surface (``registerWebAuthnCredential``) because
 * ``postJson`` is module-private; the begin call drives the failure
 * branch we care about, so the mocked fetch only needs to fire once.
 */

const startRegistrationMock = vi.fn();
const startAuthenticationMock = vi.fn();

vi.mock('@simplewebauthn/browser', () => ({
  startRegistration: (...args: unknown[]) => startRegistrationMock(...args),
  startAuthentication: (...args: unknown[]) => startAuthenticationMock(...args),
}));

describe('webauthn.ts postJson error handling', () => {
  beforeEach(() => {
    startRegistrationMock.mockReset();
    startAuthenticationMock.mockReset();
    global.fetch = vi.fn();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('parses a legacy string detail into ApiError.message', async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: false,
      status: 400,
      json: async () => ({ detail: 'Interim token expired' }),
    });

    const { registerWebAuthnCredential } = await import('./webauthn');
    const { ApiError } = await import('./client');

    let captured: InstanceType<typeof ApiError> | null = null;
    try {
      await registerWebAuthnCredential('stale-token');
    } catch (err) {
      captured = err as InstanceType<typeof ApiError>;
    }
    expect(captured).not.toBeNull();
    expect(captured!).toBeInstanceOf(ApiError);
    expect(captured!.message).toBe('Interim token expired');
    expect(captured!.status).toBe(400);
  });

  it('parses a structured object detail (`{error_code, message}`) into a `code: message` form', async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: async () => ({
        detail: {
          error_code: 'ERR_WEBAUTHN_INTERIM_INVALID',
          message: 'The interim token has expired or been revoked.',
        },
      }),
    });

    const { registerWebAuthnCredential } = await import('./webauthn');
    const { ApiError } = await import('./client');

    let captured: InstanceType<typeof ApiError> | null = null;
    try {
      await registerWebAuthnCredential('stale-token');
    } catch (err) {
      captured = err as InstanceType<typeof ApiError>;
    }
    expect(captured).not.toBeNull();
    expect(captured!).toBeInstanceOf(ApiError);
    expect(captured!.message).toBe(
      'ERR_WEBAUTHN_INTERIM_INVALID: The interim token has expired or been revoked.',
    );
    expect(captured!.code).toBe('ERR_WEBAUTHN_INTERIM_INVALID');
    expect(captured!.status).toBe(401);
  });

  it('falls back to top-level envelope (`{error, message}`) when detail is missing', async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: false,
      status: 403,
      json: async () => ({
        error: 'ERR_2FA_REQUIRED',
        message: 'Two-factor authentication is required.',
      }),
    });

    const { registerWebAuthnCredential } = await import('./webauthn');
    const { ApiError } = await import('./client');

    let captured: InstanceType<typeof ApiError> | null = null;
    try {
      await registerWebAuthnCredential('stale-token');
    } catch (err) {
      captured = err as InstanceType<typeof ApiError>;
    }
    expect(captured).not.toBeNull();
    expect(captured!).toBeInstanceOf(ApiError);
    expect(captured!.message).toBe('Two-factor authentication is required.');
    expect(captured!.code).toBe('ERR_2FA_REQUIRED');
  });

  it('falls back to the generic message when no useful detail is present', async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({}),
    });

    const { registerWebAuthnCredential } = await import('./webauthn');
    const { ApiError } = await import('./client');

    let captured: InstanceType<typeof ApiError> | null = null;
    try {
      await registerWebAuthnCredential('stale-token');
    } catch (err) {
      captured = err as InstanceType<typeof ApiError>;
    }
    expect(captured!).toBeInstanceOf(ApiError);
    expect(captured).not.toBeNull();
    expect(captured!.message).toBe('WebAuthn request failed');
    expect(captured!.code).toBeNull();
  });
});
