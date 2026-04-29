import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * Tests for the ``requireWebAuthn`` / ``ensureHardwareKeyPresence``
 * helpers.
 *
 * The underlying ceremony delegates to ``@simplewebauthn/browser``;
 * we mock it (and ``isWebAuthnSupported``) so the suite never touches
 * a real authenticator.
 */

const startAuthenticationMock = vi.fn();
const isWebAuthnSupportedMock = vi.fn();

vi.mock('@simplewebauthn/browser', () => ({
  startAuthentication: (...args: unknown[]) => startAuthenticationMock(...args),
}));

vi.mock('$lib/api/webauthn', () => ({
  isWebAuthnSupported: () => isWebAuthnSupportedMock(),
}));

describe('webauthnGating', () => {
  beforeEach(() => {
    startAuthenticationMock.mockReset();
    isWebAuthnSupportedMock.mockReset();
    isWebAuthnSupportedMock.mockReturnValue(true);
    // Provide a stable crypto.getRandomValues for jsdom.
    if (typeof globalThis.crypto === 'undefined' || !globalThis.crypto.getRandomValues) {
      Object.defineProperty(globalThis, 'crypto', {
        configurable: true,
        value: {
          getRandomValues: (arr: Uint8Array) => {
            for (let i = 0; i < arr.length; i += 1) arr[i] = i;
            return arr;
          },
        },
      });
    }
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('runs the action when the WebAuthn ceremony succeeds', async () => {
    startAuthenticationMock.mockResolvedValueOnce({ id: 'cred-1' });
    const { requireWebAuthn } = await import('./webauthnGating');
    const action = vi.fn().mockResolvedValue(undefined);

    const ok = await requireWebAuthn(action);

    expect(ok).toBe(true);
    expect(action).toHaveBeenCalledTimes(1);
    expect(startAuthenticationMock).toHaveBeenCalledTimes(1);
  });

  it('returns false and skips the action when the user cancels', async () => {
    startAuthenticationMock.mockRejectedValueOnce(
      new DOMException('cancelled', 'NotAllowedError'),
    );
    const { requireWebAuthn } = await import('./webauthnGating');
    const action = vi.fn();

    const ok = await requireWebAuthn(action);

    expect(ok).toBe(false);
    expect(action).not.toHaveBeenCalled();
  });

  it('throws WebAuthnGateError when the ceremony fails for non-cancellation reasons', async () => {
    startAuthenticationMock.mockRejectedValueOnce(new Error('boom'));
    const { requireWebAuthn, WebAuthnGateError } = await import('./webauthnGating');
    const action = vi.fn();

    await expect(requireWebAuthn(action)).rejects.toBeInstanceOf(
      WebAuthnGateError,
    );
    expect(action).not.toHaveBeenCalled();
  });

  it('throws WebAuthnGateError when WebAuthn is unsupported', async () => {
    isWebAuthnSupportedMock.mockReturnValue(false);
    const { ensureHardwareKeyPresence, WebAuthnGateError } = await import(
      './webauthnGating'
    );

    await expect(ensureHardwareKeyPresence()).rejects.toBeInstanceOf(
      WebAuthnGateError,
    );
    expect(startAuthenticationMock).not.toHaveBeenCalled();
  });

  it('propagates errors thrown by the action after the ceremony succeeds', async () => {
    startAuthenticationMock.mockResolvedValueOnce({ id: 'cred-2' });
    const { requireWebAuthn } = await import('./webauthnGating');
    const action = vi.fn().mockRejectedValue(new Error('action failed'));

    await expect(requireWebAuthn(action)).rejects.toThrow('action failed');
    expect(action).toHaveBeenCalledTimes(1);
  });
});
