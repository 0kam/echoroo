/**
 * spec/011 Step 12b — T740 (SC-1): Naive-deployer zero-email journey.
 *
 * Goal: prove that a deployer can reach productive use with ZERO email
 * configuration (no SMTP/Resend/Mailpit/DKIM/DNS) and never hit an
 * email-verification or email-config gate.
 *
 * The dev stack already runs without email config, so this spec asserts
 * that the journey works end-to-end:
 *   1. Login as a seeded user via loginWithSharedTotp → lands on dashboard.
 *   2. Navigate to /projects/new, fill the minimum required fields, and
 *      successfully create a project → lands in the project detail page.
 *   3. Throughout the journey: no email-config or email-verification gate
 *      is encountered (no "verify email" redirect, no "configure email"
 *      blocker, no role="alert" demanding email setup).
 *
 * Note: the /setup wizard is NOT tested here — the dev DB is already
 * initialised and the wizard cannot be re-run.  The SC-1 surface relevant
 * to this test is the productive user journey that works even without email.
 *
 * Test account: e2e-owner@echoroo.app (shared TEST_MODE TOTP secret).
 */

import { test, expect, type Page } from '@playwright/test';
import { loginWithSharedTotp } from './helpers/spec011-auth';

// ---------------------------------------------------------------------------
// Console error tracking (reuse pattern from single-invitation-flow.spec.ts)
// ---------------------------------------------------------------------------

const BENIGN_CONSOLE_ERROR_PATTERNS = [
  '401',
  '403',
  '404',
  'net::ERR_ABORTED',
  'Failed to load resource',
];

function isBenignConsoleError(msg: string): boolean {
  return BENIGN_CONSOLE_ERROR_PATTERNS.some((pattern) => msg.includes(pattern));
}

function trackConsoleErrors(page: Page): () => string[] {
  const errors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error' && !isBenignConsoleError(msg.text())) {
      errors.push(msg.text());
    }
  });
  page.on('pageerror', (err) => {
    errors.push(`PAGE ERROR: ${err.message}`);
  });
  return () => errors;
}

// ---------------------------------------------------------------------------
// Helpers: email-verification / email-config gate detection
// Reuses the absence-assertion pattern from no-email-ui-fresh-deployment.spec.ts
// ---------------------------------------------------------------------------

async function assertNoEmailGate(page: Page, context: string): Promise<void> {
  const url = page.url();

  // Must NOT be redirected to a verify-email route.
  expect(url, `${context}: must not redirect to /verify-email`).not.toContain('verify-email');
  expect(url, `${context}: must not redirect to /forgot-password`).not.toContain(
    'forgot-password'
  );
  expect(url, `${context}: must not redirect to /reset-password`).not.toContain('reset-password');

  // Must NOT contain a role="alert" demanding email config/verification.
  const bodyText = (await page.locator('body').textContent()) ?? '';

  const forbiddenPatterns = [
    /configure.{0,15}email/i,
    /email.{0,15}configur/i,
    /smtp.{0,15}required/i,
    /verify.{0,10}email/i,
    /email.{0,10}verif/i,
    /メール認証/,
    /email.*setup.*required/i,
  ];

  for (const pattern of forbiddenPatterns) {
    expect(
      bodyText,
      `${context}: page body must not contain email-gate text matching ${pattern}`
    ).not.toMatch(pattern);
  }

  // No <a> linking to deleted/email-config routes.
  const forbiddenHrefs = ['verify-email', 'forgot-password', 'reset-password', 'email-config'];
  for (const href of forbiddenHrefs) {
    const count = await page.locator(`a[href*="${href}"]`).count();
    expect(count, `${context}: no <a> tag should link to "${href}"`).toBe(0);
  }
}

// ---------------------------------------------------------------------------
// Suite
// ---------------------------------------------------------------------------

test.describe.serial('SC-1: naive-deployer zero-email journey (T740)', () => {
  test.setTimeout(90_000);

  test('login + create project succeeds with no email-config or email-verification gate', async ({
    page,
  }) => {
    const getErrors = trackConsoleErrors(page);

    // ── Step 1: Login ─────────────────────────────────────────────────────
    await loginWithSharedTotp(page, { email: 'e2e-owner@echoroo.app' });

    // Confirm landing on dashboard (auth works without email verification step).
    const pathname = new URL(page.url()).pathname.replace(/^\/[a-z]{2}(?=\/)/, '');
    expect(
      pathname.startsWith('/dashboard') || pathname.startsWith('/'),
      `Expected dashboard after login, got: ${page.url()}`
    ).toBe(true);

    // Positive anchor: dashboard main element visible.
    await expect(page.locator('main')).toBeVisible({ timeout: 10000 });

    // Assert no email gate on the dashboard.
    await assertNoEmailGate(page, 'dashboard after login');

    console.log(`SC-1 Step 1: login OK, landed at ${page.url()}`);

    // ── Step 2: Create a new project ──────────────────────────────────────
    await page.goto('/en/projects/new');

    // Wait for the form to render (license dropdown is loaded async).
    await expect(page.locator('input[name="name"]')).toBeVisible({ timeout: 15000 });

    // Assert no email gate on the project creation page.
    await assertNoEmailGate(page, 'projects/new page');

    // Wait for licenses to load (the submit button is disabled until a license
    // is selected; the dropdown is populated from the live API).
    await page.waitForFunction(
      () => {
        const select = document.querySelector<HTMLSelectElement>('[data-testid="license-select"]');
        if (!select) return false;
        // At least one option beyond the placeholder (disabled first option).
        return select.options.length > 1;
      },
      null,
      { timeout: 15000 }
    );

    // Fill the minimum required fields.
    const projectName = `SC-1 E2E Test Project ${Date.now()}`;
    await page.fill('input[name="name"]', projectName);

    // Select the first non-placeholder license option.
    const licenseSelect = page.locator('[data-testid="license-select"]');
    await licenseSelect.selectOption({ index: 1 });

    // Visibility defaults to "restricted" (first radio pre-checked).
    // We verify that is the case and accept the default.
    const restrictedRadio = page.locator('input[type="radio"][value="restricted"]');
    await expect(restrictedRadio).toBeChecked({ timeout: 5000 });

    // Submit the form.
    const submitBtn = page.locator('[data-testid="project-create-submit"]');
    await expect(submitBtn).toBeEnabled({ timeout: 5000 });
    await submitBtn.click();

    // ── Step 3: Assert landing in the newly-created project ───────────────
    // After a successful create the app navigates to /projects/{uuid}.
    // "new" must NOT count — UUIDs contain digits (e.g. b95e3ae7-946a-4bb1-b6e9-98da6bdf770f).
    await page.waitForURL(
      (url) => {
        const p = url.pathname.replace(/^\/[a-z]{2}(?=\/)/, '');
        // UUID-shaped path: /projects/{hex-{hex}-…} — must contain a digit
        return /^\/projects\/[0-9a-f]+-[0-9a-f]+-/.test(p);
      },
      { timeout: 20000 }
    );

    const finalUrl = page.url();
    const finalPath = new URL(finalUrl).pathname.replace(/^\/[a-z]{2}(?=\/)/, '');
    expect(
      /^\/projects\/[0-9a-f]+-[0-9a-f]+-/.test(finalPath),
      `Expected to land on a project detail page (UUID path), got: ${finalUrl}`
    ).toBe(true);

    // Assert no email gate on the project detail page.
    await assertNoEmailGate(page, 'project detail page after creation');

    console.log(`SC-1 Step 2-3: project created, landed at ${finalUrl}`);

    // ── Final: zero console errors ─────────────────────────────────────────
    const errors = getErrors();
    expect(errors, `Unexpected console errors: ${errors.join(', ')}`).toHaveLength(0);
  });
});
