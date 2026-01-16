/**
 * E2E tests for API token management
 */

import { test, expect } from '@playwright/test';

test.describe('API Token Management', () => {
  // Login before each test
  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.fill('#email', 'admin@example.com');
    await page.fill('#password', 'admin123');
    await page.click('button[type="submit"]');
    await expect(page).toHaveURL('/dashboard');

    // Navigate to settings
    await page.goto('/settings');
    await expect(page.locator('text=API Tokens')).toBeVisible();
  });

  test('should show empty state when no tokens exist', async ({ page }) => {
    // Should show the no tokens message or the tokens table
    const noTokensMessage = page.getByTestId('no-tokens-message');
    const tokensTable = page.getByTestId('tokens-table');

    // Either no tokens message or tokens table should be visible
    await expect(noTokensMessage.or(tokensTable)).toBeVisible();
  });

  test('should create token and display it', async ({ page }) => {
    // Click create new token button
    await page.getByTestId('create-token-button').click();

    // Fill in token name
    await page.fill('#token-name', 'Test Token');

    // Submit form
    await page.click('button:has-text("Create Token")');

    // Should show the token value
    await expect(page.getByText('Token Created')).toBeVisible();
    await expect(page.getByText('This token will only be shown once')).toBeVisible();

    // Token should be displayed
    const tokenInput = page.getByTestId('token-value');
    await expect(tokenInput).toBeVisible();
    const tokenValue = await tokenInput.inputValue();
    expect(tokenValue).toMatch(/^ecr_/);
  });

  test('should copy token to clipboard', async ({ page, context }) => {
    // Grant clipboard permissions
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);

    // Create a token first
    await page.getByTestId('create-token-button').click();
    await page.fill('#token-name', 'Copy Test Token');
    await page.click('button:has-text("Create Token")');

    // Wait for token to be displayed
    await expect(page.getByTestId('token-value')).toBeVisible();

    // Click copy button
    await page.getByTestId('copy-token-button').click();

    // Should show "Copied!" feedback
    await expect(page.getByText('Copied!')).toBeVisible();
  });

  test('should list created tokens', async ({ page }) => {
    // Create a token first
    await page.getByTestId('create-token-button').click();
    await page.fill('#token-name', 'List Test Token');
    await page.click('button:has-text("Create Token")');

    // Close dialog
    await page.click('button:has-text("Done")');

    // Token should appear in the list
    await expect(page.getByTestId('tokens-table')).toBeVisible();
    await expect(page.locator('td:has-text("List Test Token")')).toBeVisible();
  });

  test('should revoke token', async ({ page }) => {
    // Create a token first
    await page.getByTestId('create-token-button').click();
    await page.fill('#token-name', 'Revoke Test Token');
    await page.click('button:has-text("Create Token")');
    await page.click('button:has-text("Done")');

    // Find the token row
    await expect(page.locator('td:has-text("Revoke Test Token")')).toBeVisible();

    // Accept the confirmation dialog
    page.on('dialog', dialog => dialog.accept());

    // Click revoke button
    await page.locator('button:has-text("Revoke")').first().click();

    // Token should be removed from the list
    await expect(page.locator('td:has-text("Revoke Test Token")')).not.toBeVisible();
  });

  test('should create token with expiration date', async ({ page }) => {
    // Click create new token button
    await page.getByTestId('create-token-button').click();

    // Fill in token name
    await page.fill('#token-name', 'Expiring Token');

    // Set expiration date (30 days from now)
    const futureDate = new Date();
    futureDate.setDate(futureDate.getDate() + 30);
    const dateString = futureDate.toISOString().slice(0, 16);
    await page.fill('#token-expires', dateString);

    // Submit form
    await page.click('button:has-text("Create Token")');

    // Should show the token
    await expect(page.getByTestId('token-value')).toBeVisible();

    // Close dialog
    await page.click('button:has-text("Done")');

    // Token should be in the list with expiration info
    await expect(page.locator('td:has-text("Expiring Token")')).toBeVisible();
  });

  test('token shown only once - not visible after dialog close', async ({ page }) => {
    // Create a token
    await page.getByTestId('create-token-button').click();
    await page.fill('#token-name', 'One Time Token');
    await page.click('button:has-text("Create Token")');

    // Get the token value
    const tokenInput = page.getByTestId('token-value');
    await expect(tokenInput).toBeVisible();
    const tokenValue = await tokenInput.inputValue();

    // Close the dialog
    await page.click('button:has-text("Done")');

    // Token should be in the table but value not shown
    await expect(page.locator('td:has-text("One Time Token")')).toBeVisible();

    // The actual token value should not be visible anywhere on the page
    await expect(page.locator(`text=${tokenValue}`)).not.toBeVisible();
  });
});
