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
 * Environment gate
 * ----------------
 * All tests skip unless `ADMIN_PWD_RESET_E2E_ENABLED=1` is set.
 * Even with the suite enabled, tests skip if required env vars are absent.
 * This keeps CI collection cheap and credential-free by default.
 *
 * Required environment variables
 * --------------------------------
 *   ADMIN_PWD_RESET_E2E_ENABLED=1   Enable this suite.
 *
 * Optional environment variables (all have dev-sensible defaults)
 * ---------------------------------------------------------------
 *   ADMIN_PWD_RESET_ACTOR_EMAIL          Superuser email.
 *                                        Default: e2e-admin@echoroo.app
 *   ADMIN_PWD_RESET_ACTOR_PASSWORD       Superuser password.
 *                                        Default: E2E-Test-Password-123!
 *   ADMIN_PWD_RESET_ACTOR_TOTP_SECRET    Superuser TOTP secret (base32).
 *                                        Default: shared TEST_MODE secret
 *                                        JBSWY3DPEHPK3PXP (preview env).
 *   ADMIN_PWD_RESET_TARGET_EMAIL         Non-superuser to reset.
 *                                        Default: e2e-viewer@echoroo.app
 *   ADMIN_PWD_RESET_TARGET_PASSWORD      Current (pre-test) password for
 *                                        TARGET. Not used to log in — only
 *                                        consumed when the test needs to
 *                                        restore the account after the run.
 *                                        Default: E2E-Test-Password-123!
 *   ADMIN_PWD_RESET_TARGET_TOTP_SECRET   TARGET TOTP secret (base32).
 *                                        Default: shared TEST_MODE secret
 *                                        JBSWY3DPEHPK3PXP.
 *
 * Idempotency note
 * ----------------
 * The test resets the TARGET's password and then changes it again as part
 * of the happy-path scenario. After the test, TARGET's password is the
 * random `NEW_PASSWORD` value generated at runtime, NOT the original
 * `ADMIN_PWD_RESET_TARGET_PASSWORD`. Re-running the test against a dev DB
 * that retains state is therefore safe as long as the e2e-viewer account
 * can reach the change-password screen after each reset.
 *
 * How to run
 * ----------
 *   ./scripts/docker.sh dev
 *   ADMIN_PWD_RESET_E2E_ENABLED=1 npx playwright test tests/e2e/admin-password-reset.spec.ts
 *
 *   # Headed (for debugging):
 *   ADMIN_PWD_RESET_E2E_ENABLED=1 npx playwright test tests/e2e/admin-password-reset.spec.ts --headed
 */

import { test, expect, type Page } from '@playwright/test';
import { generateTotpCode, waitForFreshTotpWindow } from './helpers/totp';

// ---------------------------------------------------------------------------
// Environment gate
// ---------------------------------------------------------------------------

const SUITE_ENABLED = process.env.ADMIN_PWD_RESET_E2E_ENABLED === '1';

// ACTOR: a superuser account with TOTP enrolled.
const ACTOR = {
  email: process.env.ADMIN_PWD_RESET_ACTOR_EMAIL ?? 'e2e-admin@echoroo.app',
  password: process.env.ADMIN_PWD_RESET_ACTOR_PASSWORD ?? 'E2E-Test-Password-123!',
  // Shared TEST_MODE TOTP secret (works in preview and any dev DB seeded
  // with seed_e2e_permissions.py + TEST_MODE=true).
  totpSecret:
    process.env.ADMIN_PWD_RESET_ACTOR_TOTP_SECRET ?? 'JBSWY3DPEHPK3PXP',
};

// TARGET: a non-superuser whose password will be reset by ACTOR.
const TARGET = {
  email: process.env.ADMIN_PWD_RESET_TARGET_EMAIL ?? 'e2e-viewer@echoroo.app',
  // TARGET's TOTP for the subsequent login after reset.
  totpSecret:
    process.env.ADMIN_PWD_RESET_TARGET_TOTP_SECRET ?? 'JBSWY3DPEHPK3PXP',
};

// A unique strong password for the forced-change step — random enough to
// avoid HIBP hits and policy collisions between runs.
const NEW_PASSWORD = `E2E-Chg-${Date.now()}-Aa1!`;

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

/**
 * Log in via the UI, completing the TOTP 2FA challenge if presented.
 * Mirrors the pattern from admin-superusers.spec.ts.
 */
async function login(
  page: Page,
  email: string,
  password: string,
  totpSecret: string,
): Promise<void> {
  await page.goto('/en/login');
  await page.fill('input[name="email"]', email);
  await page.fill('input[name="password"]', password);
  await page.click('button[type="submit"]');

  const twoFactorForm = page.locator('[data-testid="two-factor-form"]');
  const offLoginRedirect = page.waitForURL(
    (url) => !url.pathname.replace(/^\/[a-z]{2}(?=\/)/, '').startsWith('/login'),
    { timeout: 15000 },
  );

  await Promise.race([
    twoFactorForm.waitFor({ state: 'visible', timeout: 15000 }),
    offLoginRedirect.catch(() => undefined),
  ]);

  if (await twoFactorForm.isVisible().catch(() => false)) {
    if (!totpSecret) {
      test.skip(true, '2FA challenge appeared but TOTP secret is not configured.');
      return;
    }
    await waitForFreshTotpWindow();
    const code = generateTotpCode(totpSecret);
    await page.fill('[data-testid="two-factor-code-input"]', code);
    await Promise.all([
      page.waitForURL(
        (url) =>
          !url.pathname.replace(/^\/[a-z]{2}(?=\/)/, '').startsWith('/login'),
        { timeout: 15000 },
      ),
      page.click('[data-testid="two-factor-submit"]'),
    ]);
  }
}

// ---------------------------------------------------------------------------
// Suite
// ---------------------------------------------------------------------------

test.describe('spec/011 US4 admin password reset @e2e-admin', () => {
  // Skip the entire suite when the env gate is not set.
  test.beforeEach(() => {
    test.skip(!SUITE_ENABLED, 'ADMIN_PWD_RESET_E2E_ENABLED is not set');
    test.skip(!ACTOR.email, 'ADMIN_PWD_RESET_ACTOR_EMAIL is not configured');
    test.skip(!ACTOR.password, 'ADMIN_PWD_RESET_ACTOR_PASSWORD is not configured');
    test.skip(!ACTOR.totpSecret, 'ADMIN_PWD_RESET_ACTOR_TOTP_SECRET is not configured');
    test.skip(!TARGET.email, 'ADMIN_PWD_RESET_TARGET_EMAIL is not configured');
    test.skip(!TARGET.totpSecret, 'ADMIN_PWD_RESET_TARGET_TOTP_SECRET is not configured');
  });

  // -------------------------------------------------------------------------
  // Scenario 1: ACTOR opens /admin/users — page renders with the user roster
  // -------------------------------------------------------------------------
  test('admin/users page loads and displays at least one user row', async ({ page }) => {
    await login(page, ACTOR.email, ACTOR.password, ACTOR.totpSecret);
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
    await login(page, ACTOR.email, ACTOR.password, ACTOR.totpSecret);
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
  //   TARGET changes password → lands on /dashboard (session alive)
  // -------------------------------------------------------------------------
  test('full admin-reset flow: reset → forced-change → dashboard', async ({ page, browser }) => {
    // ---- Step A: ACTOR logs in and navigates to /admin/users ----
    await login(page, ACTOR.email, ACTOR.password, ACTOR.totpSecret);
    await page.goto('/en/admin/users');
    await expect(page.locator('tbody tr').first()).toBeVisible({ timeout: 15000 });

    // ---- Step B: Find the TARGET user row by email ----
    // Look for the reset button in a row that also contains TARGET's email.
    // Strategy: iterate visible reset buttons and find the nearest email cell.
    // We search the entire table text for TARGET's email, then locate the
    // reset button in that same row.
    const targetRow = page.locator('tbody tr', {
      hasText: TARGET.email,
    });

    const targetRowCount = await targetRow.count();
    if (targetRowCount === 0) {
      // TARGET is not visible on the current page — the test cannot continue
      // without the seeded TARGET account. Skip gracefully.
      test.skip(
        true,
        `Target user ${TARGET.email} not found on /admin/users. Ensure the e2e seed has been run.`,
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
      await targetPage.goto('/en/login');
      await targetPage.fill('input[name="email"]', TARGET.email);
      await targetPage.fill('input[name="password"]', tempPassword);
      await targetPage.click('button[type="submit"]');

      // TARGET may be presented with a 2FA challenge (seeded accounts have 2FA).
      const targetTwoFactor = targetPage.locator('[data-testid="two-factor-form"]');
      const targetOffLogin = targetPage.waitForURL(
        (url) =>
          !url.pathname.replace(/^\/[a-z]{2}(?=\/)/, '').startsWith('/login'),
        { timeout: 15000 },
      );

      await Promise.race([
        targetTwoFactor.waitFor({ state: 'visible', timeout: 15000 }),
        targetOffLogin.catch(() => undefined),
      ]);

      if (await targetTwoFactor.isVisible().catch(() => false)) {
        await waitForFreshTotpWindow();
        const targetTotp = generateTotpCode(TARGET.totpSecret);
        await targetPage.fill('[data-testid="two-factor-code-input"]', targetTotp);
        await Promise.all([
          targetPage.waitForURL(
            (url) =>
              !url.pathname.replace(/^\/[a-z]{2}(?=\/)/, '').startsWith('/login'),
            { timeout: 15000 },
          ),
          targetPage.click('[data-testid="two-factor-submit"]'),
        ]);
      }

      // ---- Step G: TARGET is auto-routed to /change-password ----
      await expect(targetPage).toHaveURL(
        (url) => stripLocale(url.pathname) === '/change-password',
        { timeout: 15000 },
      );

      // The change-password form must be visible.
      await expect(
        targetPage.locator('[data-testid="change-password-form"]'),
      ).toBeVisible({ timeout: 10000 });

      // ---- Step H: TARGET completes the forced-change ----
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
    await login(page, ACTOR.email, ACTOR.password, ACTOR.totpSecret);
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
  //   — the backend integration suite fast-forwards the clock to 24h+1s and
  //     asserts a 401 "credentials_expired" response.
  test.fixme(
    'temp password is rejected after its 24h TTL expires (backend integration test coverage)',
    async () => {
      // This scenario is intentionally not implemented here.
      // See: apps/api/tests/integration/test_admin_password_reset.py
    },
  );
});
