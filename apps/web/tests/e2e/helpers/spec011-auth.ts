/**
 * Shared login helper for spec/011 Step 12b E2E tests.
 *
 * Uses the TEST_MODE shared TOTP secret so any seeded e2e-* account
 * (created by seed_e2e_permissions.py with TEST_MODE=true on the backend)
 * can be logged in without knowing their per-user TOTP secret.
 *
 * Backend requirement: TEST_MODE=true, TEST_TOTP_SECRET_BASE32=VUO4R45DU5RTBODG63FN7KOE6OOCKCJE
 *
 * Implementation delegates to the battle-tested `login()` helper from
 * seeded-permissions.helpers.ts to guarantee identical interaction patterns.
 */

import { type Page } from '@playwright/test';
import { login, type SeededTestUser } from '../permissions/seeded-permissions.helpers';

export const SHARED_TOTP_SECRET =
  process.env.E2E_SHARED_TOTP_SECRET ?? 'VUO4R45DU5RTBODG63FN7KOE6OOCKCJE';

export const E2E_PASSWORD = process.env.E2E_PASSWORD ?? 'E2E-Test-Password-123!';

export const DEFAULT_E2E_EMAIL = 'e2e-owner@echoroo.app';

/**
 * Log in via the UI using the shared TEST_MODE TOTP secret.
 *
 * Delegates to the battle-tested `login()` function in seeded-permissions.helpers.ts.
 *
 * 1. Navigates to /en/login.
 * 2. Fills email + password and submits.
 * 3. Waits for the 2FA form, generates a fresh TOTP code, fills and submits.
 * 4. Waits until the page navigates off /login (typically to /dashboard).
 */
export async function loginWithSharedTotp(
  page: Page,
  opts?: { email?: string; password?: string }
): Promise<void> {
  const user: SeededTestUser = {
    role: 'owner',
    email: opts?.email ?? DEFAULT_E2E_EMAIL,
    password: opts?.password ?? E2E_PASSWORD,
    totpSecret: SHARED_TOTP_SECRET,
  };

  await login(page, user);
}
