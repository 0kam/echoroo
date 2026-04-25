/**
 * TOTP helpers for E2E tests.
 *
 * Used by Playwright specs that exercise the 2FA setup / challenge flow.
 * These helpers are NOT shipped to the browser bundle — they only run from
 * Node during test execution.
 */

import { generateSync } from 'otplib';

/**
 * Generate a TOTP code for the given base32 secret. Uses the otplib v13
 * functional API; defaults match the backend (RFC 6238: 30s window, 6 digits,
 * SHA1).
 */
export function generateTotpCode(secret: string): string {
  return generateSync({ secret, strategy: 'totp' });
}

/**
 * Wait until the next 30-second TOTP window if the current code is about to
 * expire. Prevents flaky tests where the code becomes invalid between the
 * helper call and the form submission.
 */
export async function waitForFreshTotpWindow(): Promise<void> {
  const seconds = 30 - (Math.floor(Date.now() / 1000) % 30);
  if (seconds < 5) {
    await new Promise((resolve) => setTimeout(resolve, (seconds + 1) * 1000));
  }
}
