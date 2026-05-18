/**
 * E2E tests for US4 trusted-device login behavior (T070).
 *
 * Environment gate
 * ----------------
 * The whole suite is skipped unless `AUTH_TRUSTED_DEVICE_E2E_ENABLED` is set.
 * This keeps normal CI collection cheap while documenting the browser-level
 * coverage expected for a seeded 2FA account.
 *
 * Required environment variables when enabled:
 *   AUTH_TRUSTED_DEVICE_EMAIL
 *   AUTH_TRUSTED_DEVICE_PASSWORD
 *   AUTH_TRUSTED_DEVICE_TOTP_SECRET
 */

import { test, expect, type BrowserContext, type Page } from '@playwright/test';
import { generateTotpCode, waitForFreshTotpWindow } from './helpers/totp';

const SUITE_ENABLED = Boolean(process.env.AUTH_TRUSTED_DEVICE_E2E_ENABLED);

const TRUSTED_DEVICE_USER = {
  email: process.env.AUTH_TRUSTED_DEVICE_EMAIL ?? '',
  password: process.env.AUTH_TRUSTED_DEVICE_PASSWORD ?? '',
  totpSecret: process.env.AUTH_TRUSTED_DEVICE_TOTP_SECRET ?? '',
};

function stripLocale(pathname: string): string {
  return pathname.replace(/^\/[a-z]{2}(?=\/|$)/, '');
}

async function submitCredentials(page: Page): Promise<void> {
  await page.goto('/login');
  await page.fill('input[name="email"]', TRUSTED_DEVICE_USER.email);
  await page.fill('input[name="password"]', TRUSTED_DEVICE_USER.password);
  await page.click('button[type="submit"]');
}

async function expectTwoFactorChallenge(page: Page): Promise<void> {
  await expect(page.locator('[data-testid="two-factor-form"]')).toBeVisible({
    timeout: 15000,
  });
}

async function completeTwoFactorChallenge(page: Page, options: { trustDevice: boolean }) {
  await expectTwoFactorChallenge(page);
  await waitForFreshTotpWindow();
  const code = generateTotpCode(TRUSTED_DEVICE_USER.totpSecret);
  await page.fill('[data-testid="two-factor-code-input"]', code);
  await page.locator('[data-testid="trust-device-checkbox"]').setChecked(options.trustDevice);
  await Promise.all([
    page.waitForURL((url) => !stripLocale(url.pathname).startsWith('/login'), {
      timeout: 15000,
    }),
    page.click('[data-testid="two-factor-submit"]'),
  ]);
}

async function loginAndTrustCurrentBrowser(page: Page): Promise<void> {
  await submitCredentials(page);
  await completeTwoFactorChallenge(page, { trustDevice: true });
  await expect(page).toHaveURL((url) => stripLocale(url.pathname).startsWith('/dashboard'));
}

async function clearSessionButKeepTrustedDeviceCookie(context: BrowserContext) {
  const cookies = await context.cookies();
  const trustedDeviceCookies = cookies.filter((cookie) =>
    cookie.name.toLowerCase().includes('trusted')
  );
  await context.clearCookies();
  if (trustedDeviceCookies.length > 0) {
    await context.addCookies(trustedDeviceCookies);
  }
}

test.describe('US4 trusted-device login (T070)', () => {
  test.beforeEach(() => {
    test.skip(!SUITE_ENABLED, 'AUTH_TRUSTED_DEVICE_E2E_ENABLED is not set');
    test.skip(!TRUSTED_DEVICE_USER.email, 'AUTH_TRUSTED_DEVICE_EMAIL is not set');
    test.skip(!TRUSTED_DEVICE_USER.password, 'AUTH_TRUSTED_DEVICE_PASSWORD is not set');
    test.skip(
      !TRUSTED_DEVICE_USER.totpSecret,
      'AUTH_TRUSTED_DEVICE_TOTP_SECRET is not set'
    );
  });

  test('same browser skips 2FA after the device is trusted', async ({ page, context }) => {
    await loginAndTrustCurrentBrowser(page);
    await clearSessionButKeepTrustedDeviceCookie(context);

    await submitCredentials(page);

    await expect(page.locator('[data-testid="two-factor-form"]')).toBeHidden({
      timeout: 15000,
    });
    await expect(page).toHaveURL((url) => stripLocale(url.pathname).startsWith('/dashboard'));
  });

  test('new browser still requires 2FA for the same account', async ({ page, browser }) => {
    await loginAndTrustCurrentBrowser(page);

    const isolatedContext = await browser.newContext();
    const newBrowserPage = await isolatedContext.newPage();
    try {
      await submitCredentials(newBrowserPage);
      await expectTwoFactorChallenge(newBrowserPage);
      await expect(newBrowserPage).toHaveURL((url) =>
        stripLocale(url.pathname).startsWith('/login')
      );
    } finally {
      await isolatedContext.close();
    }
  });
});
