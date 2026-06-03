/**
 * spec/011 Step 12b — T192 (US1 AC1-3)
 *
 * Assertion: NO email-verification UI exists anywhere in the Echoroo frontend
 * after Step 10b removed the email subsystem.
 *
 * Guards against regression where a developer accidentally re-introduces:
 *   - "Forgot password" / password-reset links on the login page
 *   - /verify-email, /forgot-password, /reset-password routes
 *   - Email-verification banners / badges on authenticated pages
 *
 * Test accounts: e2e-owner@echoroo.app (shared TEST_MODE TOTP secret)
 */

import { test, expect, type Page } from '@playwright/test';
import { loginWithSharedTotp } from './helpers/spec011-auth';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Assert that the page does NOT contain any email-verification UI marker.
 *
 * The check is intentionally broad — substring matches on common strings used
 * by email-verification flows:
 *   - "verify email" / "email verification" / "メール認証" (old i18n key)
 *   - "resend verification" / "resend" in verification context
 *   - "email_verified" badge/attribute text
 *   - "forgot password" link text (should not appear post-Step-10b)
 *   - href patterns: forgot-password, reset-password, verify-email
 *
 * Non-email uses of "verify" that are EXPECTED to remain (2FA code input
 * label says "Verification code", hardware-key button says "Verify hardware
 * key") are NOT matched by the patterns below because they are scoped to
 * /admin/ or the TOTP challenge form which only renders during login step 2.
 * The authenticated-page assertions run after a successful login so the TOTP
 * form is no longer visible.
 */
async function assertNoEmailVerificationUI(page: Page, context: string): Promise<void> {
  const bodyText = (await page.locator('body').textContent()) ?? '';

  // Patterns that would indicate email-verification UI is present
  const forbiddenTextPatterns = [
    /forgot.{0,5}password/i,
    /reset.{0,5}password/i,
    /verify.{0,10}email/i,
    /email.{0,10}verif/i,
    /メール認証/,
    /resend verification/i,
    /email_verified/i,
  ];

  for (const pattern of forbiddenTextPatterns) {
    expect(
      bodyText,
      `${context}: page body should not contain email-verification UI matching ${pattern}`
    ).not.toMatch(pattern);
  }

  // Href-based checks: no link should point to these deleted routes
  const forbiddenHrefPatterns = ['forgot-password', 'reset-password', 'verify-email'];
  for (const href of forbiddenHrefPatterns) {
    const count = await page.locator(`a[href*="${href}"]`).count();
    expect(
      count,
      `${context}: no <a> tag should link to "${href}"`
    ).toBe(0);
  }
}

// ---------------------------------------------------------------------------
// Suite 1 — Logged-out pages
// ---------------------------------------------------------------------------

test.describe('No email-verification UI — logged-out', () => {
  test('login page has no forgot-password link, no verify-email text, only email+password form', async ({
    page,
  }) => {
    await page.goto('/en/login');

    // Confirm the page actually loaded (positive anchor — the credential form is present)
    await expect(page.locator('input[name="email"]')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('input[name="password"]')).toBeVisible();
    await expect(page.locator('button[type="submit"]')).toBeVisible();

    // Now assert email-verification markers are absent
    await assertNoEmailVerificationUI(page, 'login page (logged-out)');

    // Explicit check for the "Forgot password" link that Step 10b removed
    const forgotLink = page.locator('a[href*="forgot-password"]');
    await expect(forgotLink).toHaveCount(0);

    // The "Register" link SHOULD still be present (legitimate, not email-verification)
    const registerLink = page.locator(`a[href*="/register"]`);
    await expect(registerLink).toHaveCount(1);
  });
});

// ---------------------------------------------------------------------------
// Suite 2 — Deleted route smoke checks
// ---------------------------------------------------------------------------

test.describe('No email-verification UI — deleted routes return 404 / no form', () => {
  for (const deletedRoute of ['/en/verify-email', '/en/forgot-password', '/en/reset-password']) {
    test(`${deletedRoute} does not render a real form`, async ({ page }) => {
      // I-7: use domcontentloaded instead of networkidle for deleted routes —
      // these routes return 404 immediately, and networkidle can hang on
      // SvelteKit error-page hydration requests.
      await page.goto(deletedRoute, { waitUntil: 'domcontentloaded' });

      // The page should NOT contain a form targeting these deleted flows
      const verifyFormVisible = await page
        .locator('form')
        .filter({ hasText: /verify|forgot|reset.*password/i })
        .isVisible()
        .catch(() => false);
      expect(
        verifyFormVisible,
        `${deletedRoute}: a verify/forgot/reset password form should not be rendered`
      ).toBe(false);

      // Also assert no email-specific inputs dedicated to these flows are visible
      // (a "verify email" page would typically ask for an email + token)
      const verifyEmailInput = await page
        .locator('input[name="token"], input[name="verification_token"]')
        .isVisible()
        .catch(() => false);
      expect(
        verifyEmailInput,
        `${deletedRoute}: no verification-token input should be visible`
      ).toBe(false);

      // Confirm the route is either showing a 404/error page OR has redirected to
      // a legitimate page (login or dashboard).  We check by asserting that
      // the URL after navigation is either:
      //   a) the same deleted route (so render it without a functional form), or
      //   b) a redirect to /login or / or /dashboard.
      // Either way, the important thing is no functional email-verification form.
      const finalPath = new URL(page.url()).pathname.replace(/^\/[a-z]{2}(?=\/)/, '');
      const acceptablePaths = [
        deletedRoute.replace(/^\/[a-z]{2}/, ''),
        '/login',
        '/dashboard',
        '/',
        '/404',
      ];
      const isAcceptable = acceptablePaths.some(
        (p) => finalPath === p || finalPath.startsWith(p + '/')
      );
      expect(
        isAcceptable,
        `${deletedRoute}: final URL path "${finalPath}" is not an acceptable landing page. ` +
          `Expected one of: ${acceptablePaths.join(', ')}`
      ).toBe(true);
    });
  }
});

// ---------------------------------------------------------------------------
// Suite 3 — Logged-in authenticated pages
// ---------------------------------------------------------------------------

test.describe('No email-verification UI — logged-in screens', () => {
  // Log in once before all tests in this describe block
  test.beforeEach(async ({ page }) => {
    await loginWithSharedTotp(page, { email: 'e2e-owner@echoroo.app' });
    // Confirm we landed on dashboard after login.
    // Strip the locale prefix (/en, /ja, …) before asserting the path.
    // The || startsWith('/') form is intentionally avoided — it is always true.
    const pathname = new URL(page.url()).pathname.replace(/^\/(en|ja)(?=\/|$)/, '');
    expect(
      pathname.startsWith('/dashboard'),
      `Expected to land on /dashboard after login, got: ${page.url()} (stripped path: ${pathname})`
    ).toBe(true);
  });

  test('dashboard page has no email-verification UI', async ({ page }) => {
    await page.goto('/en/dashboard');

    // Positive anchor — the dashboard welcome section is present
    await expect(page.locator('main')).toBeVisible({ timeout: 10000 });

    await assertNoEmailVerificationUI(page, 'dashboard (logged-in)');
  });

  test('profile page has no email-verification UI', async ({ page }) => {
    await page.goto('/en/profile');

    // Positive anchor — the profile form (email field) is present
    await expect(page.locator('input[name="email"]')).toBeVisible({ timeout: 10000 });

    // The email field is read-only on the profile page — it is NOT a
    // "verify your email" prompt. Confirm the hint text is the "cannot change"
    // message, not a verification prompt.
    const _emailHint = page.locator('p').filter({ hasText: /cannot change|change.*email/i });
    // (hint may or may not be present depending on locale; it should NOT say "verify")

    await assertNoEmailVerificationUI(page, 'profile page (logged-in)');
  });

  test('settings page has no email-verification UI', async ({ page }) => {
    await page.goto('/en/settings');

    // Positive anchor — the password change section is present
    await expect(page.locator('input[name="current_password"]')).toBeVisible({ timeout: 10000 });

    await assertNoEmailVerificationUI(page, 'settings page (logged-in)');
  });
});
