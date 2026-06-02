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
 * Safety / idempotency (C-4)
 * --------------------------
 * TARGET's password is ALWAYS restored to E2E-Test-Password-123! (the suite default)
 * after the forced-change flow — even if the happy-path steps fail. The afterAll
 * hook performs a best-effort recovery: if TARGET cannot log in with the suite
 * default password, it triggers another admin reset + forced-change to restore it,
 * or logs a CLEAR FAILURE so the account is never silently left on an unknown password.
 *
 * How to run
 * ----------
 *   ./scripts/docker.sh dev
 *   ECHOROO_API_URL=http://localhost:8002 npx playwright test tests/e2e/admin-password-reset.spec.ts
 */

import { test, expect, type Browser } from '@playwright/test';
import { loginWithSharedTotp, SHARED_TOTP_SECRET, E2E_PASSWORD } from './helpers/spec011-auth';
import { generateTotpCode, waitForFreshTotpWindow } from './helpers/totp';

// ---------------------------------------------------------------------------
// Accounts
// ---------------------------------------------------------------------------

// ACTOR: e2e-admin is a platform superuser with TOTP enrolled.
const ACTOR = {
  email: process.env.ADMIN_PWD_RESET_ACTOR_EMAIL ?? 'e2e-admin@echoroo.app',
  password: process.env.ADMIN_PWD_RESET_ACTOR_PASSWORD ?? E2E_PASSWORD,
  totpSecret: process.env.ADMIN_PWD_RESET_ACTOR_TOTP_SECRET ?? SHARED_TOTP_SECRET,
};

// TARGET: a non-superuser whose password will be reset by ACTOR.
// Using e2e-viewer to avoid disrupting accounts relied on by other specs.
const TARGET = {
  email: process.env.ADMIN_PWD_RESET_TARGET_EMAIL ?? 'e2e-viewer@echoroo.app',
  totpSecret: process.env.ADMIN_PWD_RESET_TARGET_TOTP_SECRET ?? SHARED_TOTP_SECRET,
};

// The new password set during the forced-change flow.
// Set to the suite default so the TARGET account is restored after the test.
const NEW_PASSWORD = process.env.ADMIN_PWD_RESET_NEW_PASSWORD ?? E2E_PASSWORD;

// ---------------------------------------------------------------------------
// C-4: Module-scope recovery state shared between Scenario 3 and afterAll.
// ---------------------------------------------------------------------------

/** Tracks the temp password issued in Scenario 3 so afterAll can recover if needed. */
let _tempPasswordIssuedInScenario3: string | null = null;
/** Set to true once Scenario 3 successfully restores TARGET to NEW_PASSWORD. */
let _targetPasswordRestored = false;

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
 * C-4: Best-effort recovery — perform an admin reset of TARGET + forced-change
 * to restore the account to `NEW_PASSWORD` (suite default).
 *
 * This is called by afterAll when Scenario 3 left TARGET in an unknown state.
 * Logs a CLEAR FAILURE warning if it cannot restore — so the account is never
 * silently left broken.
 */
async function restoreTargetPassword(browser: Browser): Promise<void> {
  console.log('[C-4 recovery] Attempting to restore TARGET password…');

  try {
    // Step 1: ACTOR logs in and issues a new admin reset.
    const actorCtx = await browser.newContext();
    const actorPage = await actorCtx.newPage();

    try {
      await loginWithSharedTotp(actorPage, { email: ACTOR.email, password: ACTOR.password });
      await actorPage.goto('/en/admin/users');
      await actorPage.waitForLoadState('networkidle');

      // Search for TARGET.
      const searchInput = actorPage.locator('input[type="search"]');
      await expect(searchInput).toBeVisible({ timeout: 5000 });
      await searchInput.fill(TARGET.email);
      await actorPage.waitForTimeout(600);

      const targetRow = actorPage.locator('tbody tr', { hasText: TARGET.email });
      const rowCount = await targetRow.count();
      if (rowCount === 0) {
        console.error(
          `[C-4 recovery] FAILURE: TARGET ${TARGET.email} not found on /admin/users — ` +
            `account may be left with an unknown password. Manual intervention required.`
        );
        return;
      }

      const resetButton = targetRow.locator('[data-testid^="admin-reset-password-"]');
      await expect(resetButton).toBeVisible({ timeout: 5000 });
      await resetButton.click();

      const stepUpModal = actorPage.locator('[data-testid="step-up-modal"]');
      await expect(stepUpModal).toBeVisible({ timeout: 5000 });

      await actorPage.fill('[data-testid="step-up-password-input"]', ACTOR.password);
      await waitForFreshTotpWindow();
      const actorTotp = generateTotpCode(ACTOR.totpSecret);
      await actorPage.fill('[data-testid="step-up-totp-input"]', actorTotp);
      await actorPage.click('[data-testid="step-up-submit"]');

      const revealInput = actorPage.locator('[data-testid="temp-password-reveal"]');
      await expect(revealInput).toBeVisible({ timeout: 15000 });
      const recoveryTempPassword = await revealInput.inputValue();

      if (!recoveryTempPassword) {
        console.error('[C-4 recovery] FAILURE: Could not read recovery temp password.');
        return;
      }

      console.log('[C-4 recovery] Got recovery temp password. Logging in as TARGET…');

      // Step 2: TARGET logs in with recovery temp password + forced-change to NEW_PASSWORD.
      const targetCtx = await browser.newContext();
      const targetPage = await targetCtx.newPage();

      try {
        await loginWithSharedTotp(targetPage, {
          email: TARGET.email,
          password: recoveryTempPassword,
        });

        await expect(targetPage).toHaveURL(
          (url) => stripLocale(url.pathname) === '/change-password',
          { timeout: 15000 }
        );

        await targetPage.fill('[data-testid="change-password-current-input"]', recoveryTempPassword);
        await targetPage.fill('[data-testid="change-password-new-input"]', NEW_PASSWORD);
        await targetPage.fill('[data-testid="change-password-confirm-input"]', NEW_PASSWORD);
        await targetPage.click('[data-testid="change-password-submit"]');

        await expect(targetPage).toHaveURL(
          (url) => stripLocale(url.pathname).startsWith('/dashboard'),
          { timeout: 15000 }
        );

        _targetPasswordRestored = true;
        console.log('[C-4 recovery] SUCCESS: TARGET password restored to suite default.');
      } finally {
        await targetCtx.close();
      }
    } finally {
      await actorCtx.close();
    }
  } catch (err) {
    console.error(
      `[C-4 recovery] FAILURE: could not restore TARGET ${TARGET.email} password: ${err}. ` +
        `Manual intervention required.`
    );
  }
}

// ---------------------------------------------------------------------------
// Suite
// ---------------------------------------------------------------------------

test.describe('spec/011 US4 admin password reset @e2e-admin', () => {
  // C-4: afterAll recovery — if Scenario 3 left TARGET in an unknown state, restore it.
  test.afterAll(async ({ browser }) => {
    if (_targetPasswordRestored) {
      // Scenario 3 already restored — nothing to do.
      return;
    }

    if (_tempPasswordIssuedInScenario3 !== null) {
      // Scenario 3 clicked reset (marker set) but did NOT complete the
      // forced-change (test failed mid-way). We need to recover.
      // Note: marker may be 'pending' (reset clicked, reveal not yet seen) or
      // the actual temp password string.
      console.warn(
        '[C-4 afterAll] Scenario 3 did not complete password restore. Triggering recovery…' +
          ` (marker: ${_tempPasswordIssuedInScenario3 === 'pending' ? 'pending (pre-reveal)' : 'temp-password-known'})`
      );
      await restoreTargetPassword(browser);
    }
    // If _tempPasswordIssuedInScenario3 is null, Scenario 3 never reached the
    // reset button click — TARGET's password was not changed and no recovery is needed.
  });

  // -------------------------------------------------------------------------
  // Scenario 1: ACTOR opens /admin/users — page renders with the user roster
  // -------------------------------------------------------------------------
  test('admin/users page loads and displays at least one user row', async ({ page }) => {
    await loginWithSharedTotp(page, { email: ACTOR.email, password: ACTOR.password });
    await page.goto('/en/admin/users');

    await expect(page.locator('h1')).toBeVisible({ timeout: 15000 });
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

    await expect(page.locator('tbody tr').first()).toBeVisible({ timeout: 15000 });

    const resetBtn = page.locator('[data-testid^="admin-reset-password-"]').first();
    await expect(resetBtn).toBeVisible({ timeout: 10000 });
    await resetBtn.click();

    await expect(page.locator('[data-testid="step-up-modal"]')).toBeVisible({
      timeout: 5000,
    });
    await expect(page.locator('[data-testid="step-up-password-input"]')).toBeVisible();
    await expect(page.locator('[data-testid="step-up-totp-input"]')).toBeVisible();
    await expect(page.locator('[data-testid="step-up-submit"]')).toBeVisible();
  });

  // -------------------------------------------------------------------------
  // Scenario 3: Full happy-path
  //   ACTOR resets TARGET → reveal dialog shows temp password →
  //   TARGET logs in → auto-routed to /change-password →
  //   TARGET changes password to suite default → lands on /dashboard (session alive)
  //
  // C-4: module-scope state is updated so afterAll can recover if this test fails.
  // -------------------------------------------------------------------------
  test('full admin-reset flow: reset → forced-change → dashboard', async ({ page, browser }) => {
    test.setTimeout(90000);

    // ---- Step A: ACTOR logs in and navigates to /admin/users ----
    await loginWithSharedTotp(page, { email: ACTOR.email, password: ACTOR.password });
    await page.goto('/en/admin/users');
    await expect(page.locator('table')).toBeVisible({ timeout: 15000 });

    // ---- Step B: Search for TARGET ----
    const searchInput = page.locator('input[type="search"]');
    await expect(searchInput).toBeVisible({ timeout: 5000 });
    await searchInput.fill(TARGET.email);
    await page.waitForTimeout(600);

    const targetRow = page.locator('tbody tr', { hasText: TARGET.email });
    const targetRowCount = await targetRow.count();
    // Seeded e2e accounts are a required precondition — a missing account means
    // the test harness is broken, not a condition to skip gracefully.
    expect(
      targetRowCount,
      `Seeded target user ${TARGET.email} must exist on /admin/users. ` +
        `A missing seeded account indicates a broken harness — re-run the e2e seed script.`
    ).toBeGreaterThan(0);

    const resetButton = targetRow.locator('[data-testid^="admin-reset-password-"]');
    await expect(resetButton).toBeVisible({ timeout: 5000 });

    // C-4: Set the marker BEFORE clicking reset — this ensures afterAll will
    // trigger the recovery path even if a later assertion throws. The marker
    // is the sentinel value "pending" (not the actual temp password yet).
    // It will be overwritten with the real temp password once revealed.
    _tempPasswordIssuedInScenario3 = 'pending';

    await resetButton.click();

    // ---- Step C: Step-up modal ----
    const stepUpModal = page.locator('[data-testid="step-up-modal"]');
    await expect(stepUpModal).toBeVisible({ timeout: 5000 });

    // ---- Step D: Fill operator credentials ----
    await page.fill('[data-testid="step-up-password-input"]', ACTOR.password);
    await waitForFreshTotpWindow();
    const actorTotp = generateTotpCode(ACTOR.totpSecret);
    await page.fill('[data-testid="step-up-totp-input"]', actorTotp);
    await page.click('[data-testid="step-up-submit"]');

    // ---- Step E: Reveal dialog ----
    const revealInput = page.locator('[data-testid="temp-password-reveal"]');
    await expect(revealInput).toBeVisible({ timeout: 15000 });

    const tempPassword = await revealInput.inputValue();
    expect(tempPassword, 'Temp password must be non-empty').toBeTruthy();
    expect(tempPassword.length, 'Temp password should be at least 12 chars').toBeGreaterThanOrEqual(12);

    // C-4: update with the actual temp password now that we have it.
    // afterAll uses this to log in as TARGET and complete forced-change.
    _tempPasswordIssuedInScenario3 = tempPassword;

    await expect(page.locator('[data-testid="temp-password-copy"]')).toBeVisible();

    // ---- Step F: TARGET logs in with the temp password ----
    const targetContext = await browser.newContext();
    const targetPage = await targetContext.newPage();

    try {
      await loginWithSharedTotp(targetPage, { email: TARGET.email, password: tempPassword });

      // ---- Step G: TARGET is auto-routed to /change-password ----
      await expect(targetPage).toHaveURL(
        (url) => stripLocale(url.pathname) === '/change-password',
        { timeout: 15000 }
      );

      await expect(
        targetPage.locator('[data-testid="change-password-form"]')
      ).toBeVisible({ timeout: 10000 });

      // ---- Step H: TARGET completes the forced-change ----
      await targetPage.fill('[data-testid="change-password-current-input"]', tempPassword);
      await targetPage.fill('[data-testid="change-password-new-input"]', NEW_PASSWORD);
      await targetPage.fill('[data-testid="change-password-confirm-input"]', NEW_PASSWORD);
      await targetPage.click('[data-testid="change-password-submit"]');

      // ---- Step I: TARGET lands on /dashboard ----
      await expect(targetPage).toHaveURL(
        (url) => stripLocale(url.pathname).startsWith('/dashboard'),
        { timeout: 15000 }
      );

      const errorBanner = targetPage.locator('[data-testid="change-password-error"]');
      await expect(errorBanner).not.toBeVisible();

      // ---- Step J: Session is alive ----
      await targetPage.goto('/en/dashboard');
      await expect(targetPage).toHaveURL(
        (url) => stripLocale(url.pathname).startsWith('/dashboard'),
        { timeout: 10000 }
      );
      await expect(targetPage).not.toHaveURL((url) =>
        stripLocale(url.pathname).startsWith('/login')
      );

      // C-4: mark as restored so afterAll knows no recovery is needed.
      _targetPasswordRestored = true;
      _tempPasswordIssuedInScenario3 = null;
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

    const resetBtn = page.locator('[data-testid^="admin-reset-password-"]').first();
    await expect(resetBtn).toBeVisible({ timeout: 10000 });
    await resetBtn.click();

    const stepUpModal = page.locator('[data-testid="step-up-modal"]');
    await expect(stepUpModal).toBeVisible({ timeout: 5000 });

    await page.fill('[data-testid="step-up-password-input"]', 'DefinitelyWrong!');
    await page.fill('[data-testid="step-up-totp-input"]', '000000');
    await page.click('[data-testid="step-up-submit"]');

    await expect(page.locator('[data-testid="step-up-error"]')).toBeVisible({
      timeout: 10000,
    });

    await expect(page.locator('[data-testid="temp-password-reveal"]')).not.toBeVisible();
  });

  // -------------------------------------------------------------------------
  // Scenario 5 (fixme): 24h TTL-expiry of the temporary password
  // -------------------------------------------------------------------------
  test.fixme(
    'temp password is rejected after its 24h TTL expires (backend integration test coverage)',
    async () => {
      // This scenario is intentionally not implemented here.
      // See: apps/api/tests/integration/test_admin_password_reset.py
    }
  );
});
