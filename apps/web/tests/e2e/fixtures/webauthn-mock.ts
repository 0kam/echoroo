/**
 * WebAuthn browser API mock for Playwright E2E tests.
 *
 * Phase 16 Batch 6g-4 (T970).
 *
 * Injects a stub for ``navigator.credentials.create`` and
 * ``navigator.credentials.get`` into the browser context via
 * ``page.addInitScript``.  The stub immediately resolves with a
 * synthetic credential so tests never block on a physical hardware key.
 *
 * Additionally provides a ``routeWebAuthnVerify`` helper that intercepts
 * ``/web-api/v1/auth/2fa/webauthn/*`` network requests and returns a
 * mock ``step_up_token`` response so the frontend's
 * ``performWebAuthnAndCaptureStepUpToken`` path completes end-to-end
 * without hitting the real backend challenge endpoint.
 *
 * Usage
 * -----
 *   import { injectWebAuthnMock, routeWebAuthnVerify } from './fixtures/webauthn-mock';
 *
 *   test.beforeEach(async ({ page }) => {
 *     await injectWebAuthnMock(page);
 *   });
 *
 *   test('add superuser calls API with X-Step-Up-Token', async ({ page }) => {
 *     await routeWebAuthnVerify(page, { step_up_token: 'mock-jwt-aaa' });
 *     // ... rest of test
 *   });
 */

import type { Page } from '@playwright/test';

// ---------------------------------------------------------------------------
// The script is injected into the browser page context (runs inside the
// browser VM, not in Node).  It must therefore be self-contained — no
// imports, no TypeScript-only constructs that the browser cannot run.
// ---------------------------------------------------------------------------

const WEBAUTHN_MOCK_SCRIPT = `
(function () {
  'use strict';

  // Only stub when the API is missing (headless Chromium in Playwright does
  // not expose the full WebAuthn authenticator subsystem that requires user
  // presence / device PIN).  If we somehow land on a real device browser
  // during a headed run we still override so tests stay deterministic.

  const MOCK_CREDENTIAL_ID = 'bW9jay1jcmVkZW50aWFsLWlk'; // base64url: "mock-credential-id"
  const MOCK_PUBLIC_KEY    = new Uint8Array(65).fill(0x04); // uncompressed EC point placeholder

  // Build a fake AuthenticatorAssertionResponse used by startAuthentication.
  function buildFakeAssertionResponse() {
    const clientDataJSON = new TextEncoder().encode(
      JSON.stringify({
        type: 'webauthn.get',
        challenge: 'AAAA',
        origin: window.location.origin,
      })
    );
    const authenticatorData = new Uint8Array(37); // rpIdHash(32) + flags(1) + signCount(4)
    authenticatorData[32] = 0x05; // UP + UV flags
    const signature = new Uint8Array(64).fill(0xab);

    return {
      id: MOCK_CREDENTIAL_ID,
      rawId: new Uint8Array(22),
      type: 'public-key',
      response: {
        clientDataJSON: clientDataJSON.buffer,
        authenticatorData: authenticatorData.buffer,
        signature: signature.buffer,
        userHandle: null,
        getClientDataJSON() { return clientDataJSON.buffer; },
        getAuthenticatorData() { return authenticatorData.buffer; },
        getSignature() { return signature.buffer; },
        getUserHandle() { return null; },
      },
      getClientExtensionResults() { return {}; },
      authenticatorAttachment: 'cross-platform',
      toJSON() { return { id: MOCK_CREDENTIAL_ID, type: 'public-key' }; },
    };
  }

  // Build a fake AuthenticatorAttestationResponse used by startRegistration.
  function buildFakeAttestationResponse() {
    const clientDataJSON = new TextEncoder().encode(
      JSON.stringify({
        type: 'webauthn.create',
        challenge: 'AAAA',
        origin: window.location.origin,
      })
    );
    return {
      id: MOCK_CREDENTIAL_ID,
      rawId: new Uint8Array(22),
      type: 'public-key',
      response: {
        clientDataJSON: clientDataJSON.buffer,
        attestationObject: new Uint8Array(32).buffer,
        getClientDataJSON() { return clientDataJSON.buffer; },
        getPublicKey() { return MOCK_PUBLIC_KEY.buffer; },
        getPublicKeyAlgorithm() { return -7; }, // ES256
        getAuthenticatorData() { return new Uint8Array(37).buffer; },
        getTransports() { return ['usb']; },
      },
      getClientExtensionResults() { return {}; },
      authenticatorAttachment: 'cross-platform',
      toJSON() { return { id: MOCK_CREDENTIAL_ID, type: 'public-key' }; },
    };
  }

  // Patch navigator.credentials
  if (navigator.credentials) {
    const original = navigator.credentials;

    // get() → used by startAuthentication (@simplewebauthn/browser)
    navigator.credentials.get = function (_options) {
      return Promise.resolve(buildFakeAssertionResponse());
    };

    // create() → used by startRegistration (@simplewebauthn/browser)
    navigator.credentials.create = function (_options) {
      return Promise.resolve(buildFakeAttestationResponse());
    };

    // store() / preventSilentAccess() are rarely called by SWA; keep originals.
    if (!navigator.credentials.store) {
      navigator.credentials.store = original.store ? original.store.bind(original) : () => Promise.resolve();
    }
  } else {
    // Polyfill for browsers without the API (extremely rare in Playwright).
    Object.defineProperty(navigator, 'credentials', {
      value: {
        get: () => Promise.resolve(buildFakeAssertionResponse()),
        create: () => Promise.resolve(buildFakeAttestationResponse()),
        store: () => Promise.resolve(),
        preventSilentAccess: () => Promise.resolve(),
      },
      configurable: true,
      writable: true,
    });
  }

  // Also stub PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable
  // so the isWebAuthnSupported helper in webauthnGating.ts returns true.
  if (typeof window.PublicKeyCredential === 'undefined') {
    window.PublicKeyCredential = function () {};
  }
  if (!window.PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable) {
    window.PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable =
      function () { return Promise.resolve(true); };
  }
})();
`;

/**
 * Inject the WebAuthn browser API mock into the given Playwright page.
 *
 * Must be called before any navigation that loads the SvelteKit app so
 * the script runs before ``@simplewebauthn/browser`` initialises.
 */
export async function injectWebAuthnMock(page: Page): Promise<void> {
  await page.addInitScript(WEBAUTHN_MOCK_SCRIPT);
}

/**
 * Route WebAuthn challenge/verify API calls to return a mock step-up token.
 *
 * Intercepts ``POST /web-api/v1/auth/2fa/webauthn/**`` and returns
 * ``{ step_up_token, expires_at }`` so the frontend's token-persistence
 * path (``rememberStepUpToken``) stores a valid-looking JWT in
 * ``sessionStorage``.  Subsequent destructive admin calls will then
 * attach ``X-Step-Up-Token: <mockToken>`` automatically.
 *
 * @param page        Playwright page object.
 * @param overrides   Optional overrides; defaults produce a token that
 *                    expires 5 minutes from now.
 */
export async function routeWebAuthnVerify(
  page: Page,
  overrides: {
    step_up_token?: string;
    expires_at?: string;
    scope?: string;
    status?: number;
  } = {},
): Promise<void> {
  const token = overrides.step_up_token ?? 'mock-step-up-jwt-for-e2e-testing';
  const expiresAt =
    overrides.expires_at ??
    new Date(Date.now() + 5 * 60 * 1000).toISOString();
  const scope = overrides.scope ?? 'admin_destructive';
  const status = overrides.status ?? 200;

  await page.route('**/web-api/v1/auth/2fa/webauthn/**', (route) => {
    if (status !== 200) {
      route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'mock webauthn error', error: 'mock_error' }),
      });
      return;
    }
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        step_up_token: token,
        expires_at: expiresAt,
        scope,
      }),
    });
  });
}

/**
 * Inject a pre-baked step-up token directly into the page's
 * ``sessionStorage`` so tests that do not want to exercise the full
 * WebAuthn ceremony can start with a valid cached token.
 *
 * Call this after ``page.goto()`` (sessionStorage is origin-scoped).
 */
export async function seedStepUpToken(
  page: Page,
  token = 'mock-step-up-jwt-seeded',
  ttlMs = 5 * 60 * 1000,
): Promise<void> {
  await page.evaluate(
    ({ token, expiresAt }) => {
      sessionStorage.setItem(
        'echoroo.stepUpToken',
        JSON.stringify({ token, expiresAt, scope: 'admin_destructive' }),
      );
    },
    { token, expiresAt: Date.now() + ttlMs },
  );
}
