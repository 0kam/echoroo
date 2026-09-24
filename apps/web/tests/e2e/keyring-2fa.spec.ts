/**
 * Exercise per-user TOTP enrollment and login against the real local keyring.
 *
 * This intentionally does not use the shared TEST_MODE TOTP secret: the
 * secret is read from the enrollment page and used again after logout.
 */

import { expect, test } from '@playwright/test';
import { generateTotpCode, waitForFreshTotpWindow } from './helpers/totp';

const PASSWORD = 'Keyring-E2E-Password-123!';

test('registers, enrolls TOTP, logs out, and logs back in', async ({ page }) => {
  const suffix = `${Date.now()}-${test.info().workerIndex}-${Math.random().toString(36).slice(2, 8)}`;
  const email = `keyring-2fa-${suffix}@echoroo.test`;

  await page.goto('/en/register');
  await page.fill('input[name="email"]', email);
  await page.fill('input[name="password"]', PASSWORD);
  await page.fill('input[name="confirmPassword"]', PASSWORD);
  await page.click('button[type="submit"]');

  await expect(page).toHaveURL(/\/en\/login/);
  await page.fill('input[name="email"]', email);
  await page.fill('input[name="password"]', PASSWORD);
  await page.click('button[type="submit"]');

  await expect(page).toHaveURL(/\/en\/2fa-setup/);
  const secret = (await page.locator('[data-testid="two-factor-secret"]').textContent())?.trim();
  expect(secret).toBeTruthy();

  await waitForFreshTotpWindow();
  await page.fill('[data-testid="two-factor-setup-code-input"]', generateTotpCode(secret!));
  await page.click('[data-testid="two-factor-confirm"]');

  await expect(page.locator('[data-testid="two-factor-backup-codes"]')).toBeVisible();
  await page.check('[data-testid="backup-codes-saved"]');
  await page.click('[data-testid="backup-codes-continue"]');
  await expect(page).toHaveURL(/\/en\/dashboard/);

  await page.getByRole('button', { name: /log\s*out/i }).click();
  await expect(page).toHaveURL(/\/en\/login/);

  await page.fill('input[name="email"]', email);
  await page.fill('input[name="password"]', PASSWORD);
  await page.click('button[type="submit"]');
  await expect(page.locator('[data-testid="two-factor-form"]')).toBeVisible();

  await waitForFreshTotpWindow();
  await page.fill('[data-testid="two-factor-code-input"]', generateTotpCode(secret!));
  await page.click('[data-testid="two-factor-submit"]');

  await expect(page).toHaveURL(/\/en\/dashboard/);
  await expect(page.getByRole('button', { name: /log\s*out/i })).toBeVisible();
});
