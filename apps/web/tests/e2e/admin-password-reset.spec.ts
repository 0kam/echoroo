/**
 * E2E tests for spec/011 US4 — Admin password reset (T362).
 *
 * Flow under test
 * ---------------
 *   1. ACTOR (superuser with TOTP enrolled) opens /admin/users.
 *   2. ACTOR clicks "Reset password" for TARGET user → step-up modal appears.
 *   3. ACTOR fills operator password + TOTP code → submits step-up form.
 *   4. One-time temp password is revealed in the reveal dialog.
 *   5. TARGET logs in with the temp password → auto-routed to /change-password.
 *   6. TARGET submits temp password as current + a strong new password → lands
 *      on /dashboard with an active session.
 *   7. A post-change authenticated navigation confirms the session is alive.
 *
 * TTL-expiry path (24h temp-password)
 * ------------------------------------
 * The 24h TTL-expiry acceptance criterion cannot be exercised in real-time
 * Playwright tests without time-mocking at the backend level. This path is
 * covered instead by the backend integration tests in:
 *   tests/integration/test_admin_password_reset.py
 * A fixme placeholder is included below to document the gap.
 *
 * Environment
 * -----------
 * Designed for the TEST_MODE dev harness:
 *   TEST_MODE=true, TEST_TOTP_SECRET_BASE32=VUO4R45DU5RTBODG63FN7KOE6OOCKCJE
 * Any seeded e2e-* account can be used with the shared TOTP secret.
 * No env-gate flag required — runs in the standard dev suite.
 *
 * Safety / idempotency
 * --------------------
 * TARGET's password is restored to E2E-Test-Password-123! (the suite default)
 * after the forced-change flow, so other specs that depend on this account
 * remain unaffected.
 *
 * How to run
 * ----------
 *   ./scripts/docker.sh dev
 *   ECHOROO_API_URL=http://localhost:8002 npx playwright test tests/e2e/admin-password-reset.spec.ts
 */

import { test, expect } from '@playwright/test';
import { loginWithSharedTotp, SHARED_TOTP_SECRET, E2E_PASSWORD } from './helpers/spec011-auth';
import { generateTotpCode, waitForFreshTotpWindow } from './helpers/totp';

// ---------------------------------------------------------------------------
// Accounts
// ---------------------------------------------------------------------------

// ACTOR: e2e-admin is a platform superuser with TOTP enrolled.
const ACTOR = {
  email: process.env.ADMIN_PWD_RESET_ACTOR_EMAIL ?? 'e2e-admin@echoroo.app',
  password: process.env.ADMIN_PWD_RESET_ACTOR_PASSWORD ?? E2E_PASSWORD,
  totpSecret:
    process.env.ADMIN_PWD_RESET_ACTOR_TOTP_SECRET ?? SHARED_TOTP_SECRET,
};

// TARGET: a non-superuser whose password will be reset by ACTOR.
// Using e2e-viewer to avoid disrupting accounts relied on by other specs.
const TARGET = {
  email: process.env.ADMIN_PWD_RESET_TARGET_EMAIL ?? 'e2e-viewer@echoroo.app',
  totpSecret:
    process.env.ADMIN_PWD_RESET_TARGET_TOTP_SECRET ?? SHARED_TOTP_SECRET,
};

// The new password set during the forced-change flow.
// Set to the suite default so the TARGET account is restored after the test.
const NEW_PASSWORD = process.env.ADMIN_PWD_RESET_NEW_PASSWORD ?? E2E_PASSWORD;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Strip the locale prefix (/en, /ja, …) from a pathname so URL assertions
 * remain locale-agnostic.
 */
function stripLocale(pathname: string): string {
  return pathname.replace(/^\/[a-z]{2}(?=\/|$)/, '');
}

// ---------------------------------------------------------------------------
// Suite
// ---------------------------------------------------------------------------

test.describe('spec/011 US4 admin password reset @e2e-admin', () => {
  // -------------------------------------------------------------------------
  // Scenario 1: ACTOR opens /admin/users — page renders with the user roster
  // -------------------------------------------------------------------------
  test('admin/users page loads and displays at least one user row', async ({ page }) => {
    await loginWithSharedTotp(page, { email: ACTOR.email, password: ACTOR.password });
    await page.goto('/en/admin/users');

    // Wait for the page heading.
    await expect(page.locator('h1')).toBeVisible({ timeout: 15000 });

    // The user table must be present (at least ACTOR themselves).
    await expect(page.locator('table')).toBeVisible({ timeout: 10000 });
    const rows = page.locator('tbody tr');
    await expect(rows.first()).toBeVisible({ timeout: 10000 });
  });

  // -------------------------------------------------------------------------
  // Scenario 2: Step-up modal appears when ACTOR clicks "Reset password"
  // -------------------------------------------------------------------------
  test('clicking Reset password for a user opens the step-up modal', async ({ page }) => {
    await loginWithSharedTotp(page, { email: ACTOR.email, password: ACTOR.password });
    await page.goto('/en/admin/users');

    // Wait for the table to populate.
    await expect(page.locator('tbody tr').first()).toBeVisible({ timeout: 15000 });

    // Find a Reset password button (any row is acceptable for this assertion).
    const resetBtn = page.locator('[data-testid^="admin-reset-password-"]').first();
    await expect(resetBtn).toBeVisible({ timeout: 10000 });
    await resetBtn.click();

    // The step-up modal must appear.
    await expect(page.locator('[data-testid="step-up-modal"]')).toBeVisible({
      timeout: 5000,
    });

    // Both credential inputs must be present — no WebAuthn branch.
    await expect(page.locator('[data-testid="step-up-password-input"]')).toBeVisible();
    await expect(page.locator('[data-testid="step-up-totp-input"]')).toBeVisible();
    await expect(page.locator('[data-testid="step-up-submit"]')).toBeVisible();
  });

  // -------------------------------------------------------------------------
  // Scenario 3: Full happy-path
  //   ACTOR resets TARGET → reveal dialog shows temp password →
  //   TARGET logs in → auto-routed to /change-password →
  //   TARGET changes password to suite default → lands on /dashboard (session alive)
  // -------------------------------------------------------------------------
  test('full admin-reset flow: reset → forced-change → dashboard', async ({ page, browser }) => {
    // This scenario exercises: login → admin reset → step-up → reveal → new context login →
    // forced-change → dashboard. Each step has its own sub-timeout; we raise the overall
    // test timeout to accommodate all of them.
    test.setTimeout(90000);
    // ---- Step A: ACTOR logs in and navigates to /admin/users ----
    await loginWithSharedTotp(page, { email: ACTOR.email, password: ACTOR.password });
    await page.goto('/en/admin/users');

    // Wait for the table to load.
    await expect(page.locator('table')).toBeVisible({ timeout: 15000 });

    // ---- Step B: Search for TARGET by email to ensure it appears regardless of pagination ----
    // The admin users list is ordered newest-first; seeded accounts may be on page 2+.
    // Using the search input guarantees the row appears on the first page.
    const searchInput = page.locator('input[type="search"]');
    await expect(searchInput).toBeVisible({ timeout: 5000 });
    await searchInput.fill(TARGET.email);
    // Allow the debounced search to fire (300ms) and the table to re-render.
    await page.waitForTimeout(600);

    const targetRow = page.locator('tbody tr', {
      hasText: TARGET.email,
    });

    const targetRowCount = await targetRow.count();
    if (targetRowCount === 0) {
      // TARGET is not visible even after search — skip gracefully.
      test.skip(
        true,
        `Target user ${TARGET.email} not found on /admin/users even after search. Ensure the e2e seed has been run.`,
      );
      return;
    }

    const resetButton = targetRow.locator('[data-testid^="admin-reset-password-"]');
    await expect(resetButton).toBeVisible({ timeout: 5000 });
    await resetButton.click();

    // ---- Step C: Step-up modal appears ----
    const stepUpModal = page.locator('[data-testid="step-up-modal"]');
    await expect(stepUpModal).toBeVisible({ timeout: 5000 });

    // ---- Step D: Fill operator credentials and submit ----
    await page.fill('[data-testid="step-up-password-input"]', ACTOR.password);

    // Generate a fresh TOTP code close to the window boundary.
    await waitForFreshTotpWindow();
    const actorTotp = generateTotpCode(ACTOR.totpSecret);
    await page.fill('[data-testid="step-up-totp-input"]', actorTotp);

    await page.click('[data-testid="step-up-submit"]');

    // ---- Step E: Reveal dialog appears with the temporary password ----
    const revealInput = page.locator('[data-testid="temp-password-reveal"]');
    await expect(revealInput).toBeVisible({ timeout: 15000 });

    const tempPassword = await revealInput.inputValue();
    expect(tempPassword, 'Temp password must be non-empty').toBeTruthy();
    expect(tempPassword.length, 'Temp password should be at least 12 chars').toBeGreaterThanOrEqual(12);

    // Copy button must also be present.
    await expect(page.locator('[data-testid="temp-password-copy"]')).toBeVisible();

    // ---- Step F: TARGET logs in with the temp password in a fresh context ----
    // Use an isolated browser context so the ACTOR's session does not
    // interfere with TARGET's session.
    const targetContext = await browser.newContext();
    const targetPage = await targetContext.newPage();

    try {
      // Log in as TARGET using the temp password.
      // TARGET has 2FA; use the shared TEST_MODE TOTP secret via loginWithSharedTotp
      // which uses the battle-tested seeded-permissions.helpers.ts login() under the hood.
      // The temp password is passed as the password override.
      await loginWithSharedTotp(targetPage, { email: TARGET.email, password: tempPassword });

      // ---- Step G: TARGET is auto-routed to /change-password ----
      // After login with a temp password the backend returns 423 and the
      // login page routes directly to /change-password.
      await expect(targetPage).toHaveURL(
        (url) => stripLocale(url.pathname) === '/change-password',
        { timeout: 15000 },
      );

      // The change-password form must be visible.
      await expect(
        targetPage.locator('[data-testid="change-password-form"]'),
      ).toBeVisible({ timeout: 10000 });

      // ---- Step H: TARGET completes the forced-change ----
      // Use NEW_PASSWORD (= E2E_PASSWORD = E2E-Test-Password-123!) to restore
      // the account to the suite default so other specs are unaffected.
      await targetPage.fill('[data-testid="change-password-current-input"]', tempPassword);
      await targetPage.fill('[data-testid="change-password-new-input"]', NEW_PASSWORD);
      await targetPage.fill('[data-testid="change-password-confirm-input"]', NEW_PASSWORD);
      await targetPage.click('[data-testid="change-password-submit"]');

      // ---- Step I: TARGET lands on /dashboard ----
      await expect(targetPage).toHaveURL(
        (url) => stripLocale(url.pathname).startsWith('/dashboard'),
        { timeout: 15000 },
      );

      // No error banner must be visible after redirect.
      const errorBanner = targetPage.locator('[data-testid="change-password-error"]');
      await expect(errorBanner).not.toBeVisible();

      // ---- Step J: Session is alive — a protected page loads ----
      // Navigate to /dashboard directly to confirm the session is not bounced.
      await targetPage.goto('/en/dashboard');
      await expect(targetPage).toHaveURL(
        (url) => stripLocale(url.pathname).startsWith('/dashboard'),
        { timeout: 10000 },
      );
      // Ensure we are not bounced back to /login.
      await expect(targetPage).not.toHaveURL((url) =>
        stripLocale(url.pathname).startsWith('/login'),
      );
    } finally {
      await targetContext.close();
    }
  });

  // -------------------------------------------------------------------------
  // Scenario 4: Step-up modal — invalid credentials surface an error
  // -------------------------------------------------------------------------
  test('step-up modal shows error when wrong password or TOTP is supplied', async ({ page }) => {
    await loginWithSharedTotp(page, { email: ACTOR.email, password: ACTOR.password });
    await page.goto('/en/admin/users');
    await expect(page.locator('tbody tr').first()).toBeVisible({ timeout: 15000 });

    // Click any reset button.
    const resetBtn = page.locator('[data-testid^="admin-reset-password-"]').first();
    await expect(resetBtn).toBeVisible({ timeout: 10000 });
    await resetBtn.click();

    const stepUpModal = page.locator('[data-testid="step-up-modal"]');
    await expect(stepUpModal).toBeVisible({ timeout: 5000 });

    // Supply deliberately wrong credentials.
    await page.fill('[data-testid="step-up-password-input"]', 'DefinitelyWrong!');
    await page.fill('[data-testid="step-up-totp-input"]', '000000');
    await page.click('[data-testid="step-up-submit"]');

    // An error message must appear inside the modal.
    await expect(page.locator('[data-testid="step-up-error"]')).toBeVisible({
      timeout: 10000,
    });

    // The reveal dialog must NOT have appeared (no temp password was issued).
    await expect(page.locator('[data-testid="temp-password-reveal"]')).not.toBeVisible();
  });

  // -------------------------------------------------------------------------
  // Scenario 5 (fixme): 24h TTL-expiry of the temporary password
  // -------------------------------------------------------------------------
  // The spec/011 US4 acceptance criterion requires that a temp password
  // expire after 24 hours and be rejected on login. This cannot be exercised
  // in real-time Playwright tests without backend time-mocking.
  //
  // Coverage location: apps/api/tests/integration/test_admin_password_reset.py
  test.fixme(
    'temp password is rejected after its 24h TTL expires (backend integration test coverage)',
    async () => {
      // This scenario is intentionally not implemented here.
      // See: apps/api/tests/integration/test_admin_password_reset.py
    },
  );
});
