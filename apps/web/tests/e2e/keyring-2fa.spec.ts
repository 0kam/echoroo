/**
 * Exercise per-user TOTP enrollment and login against the real local keyring.
 *
 * Enrollment wraps the new TOTP secret's DEK with the keyring; the second
 * login in a fresh browser context unwraps it again. This intentionally does
 * not use the shared TEST_MODE TOTP secret: the code comes from the secret
 * shown on the enrollment page.
 */

import { expect, test, type Page } from '@playwright/test';
import { generateTotpCode, waitForFreshTotpWindow } from './helpers/totp';
import { login } from './permissions/seeded-permissions.helpers';

const PASSWORD = 'Keyring-E2E-Password-123!';
const REGISTER_ATTEMPTS = 5;

async function register(page: Page, email: string): Promise<void> {
  await page.goto('/en/register');
  for (let attempt = 1; attempt <= REGISTER_ATTEMPTS; attempt += 1) {
    await page.fill('input[name="email"]', email);
    await page.fill('input[name="password"]', PASSWORD);
    await page.fill('input[name="confirmPassword"]', PASSWORD);
    const response = page
      .waitForResponse(
        (r) => r.request().method() === 'POST' && r.url().includes('/register'),
        { timeout: 5000 }
      )
      .catch(() => null);
    await page.click('button[type="submit"]');
    const registered = await response;
    if (registered) {
      expect(registered.ok(), `register returned ${registered.status()}`).toBeTruthy();
      await expect(page).toHaveURL(/\/en\/login\?registered=true/);
      return;
    }
    // Clicked before hydration: the browser submitted the form natively.
    await page.goto('/en/register');
  }
  throw new Error('register form never submitted through the app');
}

test('registers, enrolls TOTP, and logs back in with the enrolled secret', async ({
  page,
  browser,
}) => {
  const suffix = `${Date.now()}-${test.info().workerIndex}-${Math.random().toString(36).slice(2, 8)}`;
  const email = `keyring-2fa-${suffix}@echoroo.app`;

  await register(page, email);

  // First login: no 2FA yet, so the app sends the user to TOTP setup.
  await login(page, { role: 'member', email, password: PASSWORD, totpSecret: '' });
  await expect(page).toHaveURL(/\/en\/2fa-setup/);
  const secret = (await page.locator('[data-testid="two-factor-secret"]').textContent())
    ?.replace(/\s+/g, '')
    .trim();
  expect(secret).toBeTruthy();

  await waitForFreshTotpWindow();
  await page.fill('[data-testid="two-factor-setup-code-input"]', generateTotpCode(secret!));
  await page.click('[data-testid="two-factor-confirm"]');

  await expect(page.locator('[data-testid="two-factor-backup-codes"]')).toBeVisible();
  await page.check('[data-testid="backup-codes-saved"]');
  await page.click('[data-testid="backup-codes-continue"]');
  await expect(page).not.toHaveURL(/\/(login|2fa-setup)/);

  // Second login in a fresh context: the stored secret must decrypt.
  const context = await browser.newContext();
  try {
    const second = await context.newPage();
    await login(second, { role: 'member', email, password: PASSWORD, totpSecret: secret! });
    await expect(second).not.toHaveURL(/\/(login|2fa-setup)/);
  } finally {
    await context.close();
  }
});
