/**
 * Smoke test to verify basic functionality
 */

import { test, expect } from '@playwright/test';

test.describe('Basic functionality', () => {
  test('home page loads successfully', async ({ page }) => {
    await page.goto('/');

    // Should see the page title or main content
    await expect(page).toHaveTitle(/Echoroo/i);
  });

  test('api client is initialized', async ({ page }) => {
    await page.goto('/');

    // Check that the page renders without errors
    const errors: string[] = [];
    page.on('pageerror', (error) => {
      errors.push(error.message);
    });

    // Wait a bit for any potential errors
    await page.waitForTimeout(1000);

    expect(errors).toHaveLength(0);
  });
});
