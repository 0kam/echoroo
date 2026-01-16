import { test, expect } from '@playwright/test';

test('home page displays welcome message', async ({ page }) => {
  await page.goto('/');

  await expect(page.locator('h1')).toContainText('Welcome to Echoroo');
  await expect(page.locator('p')).toContainText('Bioacoustic Analysis Platform');
});
