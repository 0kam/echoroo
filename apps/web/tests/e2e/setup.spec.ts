/**
 * E2E tests for initial setup wizard
 */

import { test, expect } from '@playwright/test';

test.describe('Initial Setup Wizard', () => {
  test('complete setup flow with fresh database', async ({ page }) => {
    // Navigate to root - should redirect to /setup if setup is required
    await page.goto('/');

    // Should be redirected to /setup page
    await expect(page).toHaveURL('/setup');

    // Verify page title and content
    await expect(page.locator('h1')).toContainText('Welcome to Echoroo');
    await expect(page.locator('text=Create your administrator account')).toBeVisible();

    // Fill in the setup form
    const email = 'admin@echoroo.test';
    const password = 'SecurePassword123';
    const displayName = 'Admin User';

    await page.fill('input[type="email"]', email);
    await page.fill('input[id="password"]', password);
    await page.fill('input[id="confirmPassword"]', password);
    await page.fill('input[id="displayName"]', displayName);

    // Submit the form
    await page.click('button[type="submit"]');

    // Should redirect to login page after successful setup
    await expect(page).toHaveURL('/login', { timeout: 10000 });

    // Verify we can login with the created admin account
    await page.fill('input[type="email"]', email);
    await page.fill('input[type="password"]', password);
    await page.click('button[type="submit"]');

    // Should redirect to dashboard after successful login
    await expect(page).toHaveURL('/dashboard', { timeout: 10000 });
  });

  test('validates email format', async ({ page }) => {
    await page.goto('/setup');

    // Enter invalid email
    await page.fill('input[type="email"]', 'invalid-email');
    await page.fill('input[id="password"]', 'SecurePassword123');
    await page.fill('input[id="confirmPassword"]', 'SecurePassword123');

    // Blur the email field to trigger validation
    await page.click('input[id="password"]');

    // Should show email validation error
    await expect(page.locator('text=Invalid email format')).toBeVisible();
  });

  test('validates password length', async ({ page }) => {
    await page.goto('/setup');

    // Enter short password
    await page.fill('input[type="email"]', 'admin@test.com');
    await page.fill('input[id="password"]', 'short');
    await page.fill('input[id="confirmPassword"]', 'short');

    // Blur the password field to trigger validation
    await page.click('input[id="confirmPassword"]');

    // Should show password length error
    await expect(page.locator('text=Password must be at least 8 characters')).toBeVisible();
  });

  test('validates password confirmation', async ({ page }) => {
    await page.goto('/setup');

    const email = 'admin@test.com';
    const password = 'SecurePassword123';

    await page.fill('input[type="email"]', email);
    await page.fill('input[id="password"]', password);
    await page.fill('input[id="confirmPassword"]', 'DifferentPassword123');

    // Blur the confirm password field to trigger validation
    await page.click('input[id="displayName"]');

    // Should show password mismatch error
    await expect(page.locator('text=Passwords do not match')).toBeVisible();
  });

  test('shows loading state during submission', async ({ page }) => {
    await page.goto('/setup');

    await page.fill('input[type="email"]', 'admin@test.com');
    await page.fill('input[id="password"]', 'SecurePassword123');
    await page.fill('input[id="confirmPassword"]', 'SecurePassword123');

    // Click submit button
    await page.click('button[type="submit"]');

    // Should show loading state
    await expect(page.locator('text=Setting up...')).toBeVisible();
  });

  test('redirects to login if setup already completed', async ({ page }) => {
    // First, complete the setup
    await page.goto('/setup');

    await page.fill('input[type="email"]', 'admin@echoroo.test');
    await page.fill('input[id="password"]', 'SecurePassword123');
    await page.fill('input[id="confirmPassword"]', 'SecurePassword123');
    await page.click('button[type="submit"]');

    // Wait for redirect to login
    await expect(page).toHaveURL('/login', { timeout: 10000 });

    // Now try to access /setup again
    await page.goto('/setup');

    // Should be redirected to /login
    await expect(page).toHaveURL('/login');
  });

  test('display name is optional', async ({ page }) => {
    await page.goto('/setup');

    // Fill form without display name
    await page.fill('input[type="email"]', 'admin@test.com');
    await page.fill('input[id="password"]', 'SecurePassword123');
    await page.fill('input[id="confirmPassword"]', 'SecurePassword123');

    // Should be able to submit without display name
    await page.click('button[type="submit"]');

    // Should not show any validation errors
    await expect(page.locator('.text-red-600')).toHaveCount(0);
  });

  test('shows API error messages', async ({ page }) => {
    // Mock API to return an error
    await page.route('**/api/setup/initialize', (route) => {
      route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: 'Email already exists',
        }),
      });
    });

    await page.goto('/setup');

    await page.fill('input[type="email"]', 'existing@test.com');
    await page.fill('input[id="password"]', 'SecurePassword123');
    await page.fill('input[id="confirmPassword"]', 'SecurePassword123');
    await page.click('button[type="submit"]');

    // Should show API error message
    await expect(page.locator('text=Email already exists')).toBeVisible();
  });
});
