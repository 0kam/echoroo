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

import { expect, type Page } from '@playwright/test';
import { login, type SeededTestUser } from '../permissions/seeded-permissions.helpers';
import { generateTotpCode, waitForFreshTotpWindow } from './totp';

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

/**
 * Redeem an invitation as a brand-new user via the invite signup flow.
 *
 * Extracted from single-invitation-flow.spec.ts Scenario A so both the
 * single-invite and bulk-invite specs can share the same redemption pattern.
 *
 * Preconditions:
 *   - `page` must be a fresh (logged-out) browser context page.
 *   - `inviteTokenOrPath` may be either:
 *       - A signed token envelope like "{raw}.{exp}.{kid}.{mac}"
 *       - A full URL like "http://localhost:5173/en/invite/{token}"
 *       - An already-built path like "/en/invite/{token}"
 *
 * Flow:
 *   1. Navigates to the invite path.
 *   2. Waits for the signup form (data-testid="invite-signup-form").
 *   3. Fills password from opts.password (defaults to E2E_PASSWORD).
 *   4. Scrapes the client-generated TOTP secret from code[data-testid="invite-signup-secret"].
 *   5. Generates a fresh TOTP code and fills the TOTP input.
 *   6. Submits the form.
 *   7. Clicks the continue button if present, then asserts the page is at the project URL.
 *
 * Returns the final URL the page landed on.
 */
export async function redeemInviteAsNewUser(
  page: Page,
  inviteTokenOrPath: string,
  opts?: { password?: string; projectId?: string }
): Promise<string> {
  const password = opts?.password ?? E2E_PASSWORD;

  // Build the invite path from whatever form is provided.
  let invitePath: string;
  if (inviteTokenOrPath.startsWith('http://') || inviteTokenOrPath.startsWith('https://')) {
    const parsed = new URL(inviteTokenOrPath);
    invitePath = parsed.pathname + parsed.search;
  } else if (inviteTokenOrPath.startsWith('/')) {
    invitePath = inviteTokenOrPath;
  } else {
    // Raw signed token envelope.
    invitePath = `/en/invite/${encodeURIComponent(inviteTokenOrPath)}`;
  }

  await page.goto(invitePath);

  // Wait for the signup form to appear.
  await page.waitForSelector('[data-testid="invite-signup-form"]', { timeout: 20000 });

  // Fill password.
  await page.fill('[data-testid="invite-signup-password"]', password);

  // Scrape the client-generated TOTP secret.
  const secretEl = page.locator('code[data-testid="invite-signup-secret"]');
  await expect(secretEl).toBeVisible({ timeout: 10000 });
  const rawSecret = await secretEl.textContent();
  expect(rawSecret).toBeTruthy();
  const scrapedSecret = rawSecret!.replace(/\s+/g, '');

  // Generate a fresh TOTP code from the scraped secret.
  await waitForFreshTotpWindow();
  const totpCode = generateTotpCode(scrapedSecret);
  await page.fill('[data-testid="invite-signup-code"]', totpCode);

  // Submit the signup form.
  await page.click('[data-testid="invite-signup-submit"]');

  // Wait for the continue button or a direct project navigation.
  const projectPathFragment = opts?.projectId ? `/projects/${opts.projectId}` : '/projects/';
  const outcome = await Promise.race([
    page
      .waitForSelector('[data-testid="invite-landing-continue"]', { timeout: 25000 })
      .then(() => 'continue-button'),
    page
      .waitForURL((url) => url.pathname.includes(projectPathFragment), { timeout: 25000 })
      .then(() => 'project-url'),
  ]).catch(() => 'timeout');

  if (outcome === 'continue-button') {
    await page.click('[data-testid="invite-landing-continue"]');
    await page.waitForURL((url) => url.pathname.includes(projectPathFragment), { timeout: 15000 });
  } else if (outcome === 'timeout') {
    // Surface any error element for a meaningful failure message.
    const signupErrorEl = page.locator('[data-testid="invite-signup-error"]');
    if (await signupErrorEl.isVisible().catch(() => false)) {
      const text = await signupErrorEl.textContent().catch(() => '<unreadable>');
      throw new Error(`redeemInviteAsNewUser: signup form error: ${text}`);
    }
    const landingErrorEl = page.locator('[data-testid="invite-landing-error"]');
    if (await landingErrorEl.isVisible().catch(() => false)) {
      const text = await landingErrorEl.textContent().catch(() => '<unreadable>');
      throw new Error(`redeemInviteAsNewUser: landing error: ${text}`);
    }
    throw new Error(
      `redeemInviteAsNewUser: did not reach project page or continue button within timeout`
    );
  }

  return page.url();
}
