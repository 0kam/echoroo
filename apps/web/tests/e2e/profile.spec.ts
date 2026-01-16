/**
 * E2E tests for user profile management (T105)
 */

import { test, expect } from '@playwright/test';

// Test data
const testUserCredentials = {
  email: 'admin@example.com',
  password: 'admin123',
};

test.describe('Profile Management', () => {
  // Login before each test
  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.fill('#email', testUserCredentials.email);
    await page.fill('#password', testUserCredentials.password);
    await page.click('button[type="submit"]');
    await expect(page).toHaveURL('/dashboard');
  });

  test.describe('Profile Page', () => {
    test('should display current user profile information', async ({ page }) => {
      await page.goto('/profile');

      // Should show profile page header
      await expect(page.locator('h1:has-text("Profile")')).toBeVisible();

      // Should show email (read-only)
      const emailInput = page.locator('#email');
      await expect(emailInput).toBeVisible();
      await expect(emailInput).toBeDisabled();

      // Should show display name and organization fields
      await expect(page.locator('#display_name')).toBeVisible();
      await expect(page.locator('#organization')).toBeVisible();
    });

    test('should update display name', async ({ page }) => {
      await page.goto('/profile');

      // Clear existing value and enter new display name
      const newDisplayName = `Updated User ${Date.now()}`;
      await page.locator('#display_name').clear();
      await page.fill('#display_name', newDisplayName);

      // Submit form
      await page.click('button[type="submit"]');

      // Should show success message
      await expect(page.locator('text=Profile updated successfully')).toBeVisible();

      // Reload page and verify persistence
      await page.reload();
      await expect(page.locator('#display_name')).toHaveValue(newDisplayName);
    });

    test('should update organization', async ({ page }) => {
      await page.goto('/profile');

      // Clear existing value and enter new organization
      const newOrganization = `New Org ${Date.now()}`;
      await page.locator('#organization').clear();
      await page.fill('#organization', newOrganization);

      // Submit form
      await page.click('button[type="submit"]');

      // Should show success message
      await expect(page.locator('text=Profile updated successfully')).toBeVisible();

      // Reload page and verify persistence
      await page.reload();
      await expect(page.locator('#organization')).toHaveValue(newOrganization);
    });

    test('should disable save button when no changes', async ({ page }) => {
      await page.goto('/profile');

      // Save button should be disabled initially (no changes)
      const saveButton = page.locator('button[type="submit"]');
      await expect(saveButton).toBeDisabled();

      // Make a change
      await page.fill('#display_name', 'Changed Name');

      // Save button should be enabled
      await expect(saveButton).toBeEnabled();
    });

    test('should reset form to original values', async ({ page }) => {
      await page.goto('/profile');

      // Get original value
      const originalDisplayName = await page.locator('#display_name').inputValue();

      // Make changes
      await page.locator('#display_name').clear();
      await page.fill('#display_name', 'Temporary Name');

      // Click reset button
      await page.click('button:has-text("Reset")');

      // Should revert to original value
      await expect(page.locator('#display_name')).toHaveValue(originalDisplayName);
    });

    test('should validate display name max length', async ({ page }) => {
      await page.goto('/profile');

      // Enter a name that's too long (> 100 characters)
      const tooLongName = 'A'.repeat(101);
      await page.locator('#display_name').clear();

      // HTML maxlength attribute should prevent entering more than 100 chars
      await page.fill('#display_name', tooLongName);
      const actualValue = await page.locator('#display_name').inputValue();
      expect(actualValue.length).toBeLessThanOrEqual(100);
    });

    test('should navigate to security settings', async ({ page }) => {
      await page.goto('/profile');

      // Click on security settings link
      await page.click('a:has-text("Security Settings")');

      // Should navigate to settings page
      await expect(page).toHaveURL('/settings');
    });
  });

  test.describe('Settings Page - Password Change', () => {
    test('should display password change form', async ({ page }) => {
      await page.goto('/settings');

      // Should show settings page header
      await expect(page.locator('h1:has-text("Settings")')).toBeVisible();

      // Should show password change form fields
      await expect(page.locator('#current_password')).toBeVisible();
      await expect(page.locator('#new_password')).toBeVisible();
      await expect(page.locator('#confirm_new_password')).toBeVisible();
    });

    test('should change password successfully', async ({ page }) => {
      await page.goto('/settings');

      const newPassword = 'NewSecurePass456';

      // Fill in password change form
      await page.fill('#current_password', testUserCredentials.password);
      await page.fill('#new_password', newPassword);
      await page.fill('#confirm_new_password', newPassword);

      // Submit form
      await page.click('button[type="submit"]');

      // Should show success message
      await expect(page.locator('text=Password changed successfully')).toBeVisible();

      // Logout
      await page.goto('/dashboard');
      await page.click('button:has-text("Logout")');

      // Login with new password
      await page.goto('/login');
      await page.fill('#email', testUserCredentials.email);
      await page.fill('#password', newPassword);
      await page.click('button[type="submit"]');
      await expect(page).toHaveURL('/dashboard');

      // Reset password back to original for other tests
      await page.goto('/settings');
      await page.fill('#current_password', newPassword);
      await page.fill('#new_password', testUserCredentials.password);
      await page.fill('#confirm_new_password', testUserCredentials.password);
      await page.click('button[type="submit"]');
      await expect(page.locator('text=Password changed successfully')).toBeVisible();
    });

    test('should show error for wrong current password', async ({ page }) => {
      await page.goto('/settings');

      // Fill in password change form with wrong current password
      await page.fill('#current_password', 'WrongPassword123');
      await page.fill('#new_password', 'NewPassword456');
      await page.fill('#confirm_new_password', 'NewPassword456');

      // Submit form
      await page.click('button[type="submit"]');

      // Should show error message
      await expect(page.locator('text=Invalid current password')).toBeVisible();
    });

    test('should show error when passwords do not match', async ({ page }) => {
      await page.goto('/settings');

      // Fill in form with mismatched passwords
      await page.fill('#current_password', testUserCredentials.password);
      await page.fill('#new_password', 'NewPassword123');
      await page.fill('#confirm_new_password', 'DifferentPassword456');

      // Should show mismatch error
      await expect(page.locator('text=Passwords do not match')).toBeVisible();

      // Submit button should be disabled
      const submitButton = page.locator('button[type="submit"]');
      await expect(submitButton).toBeDisabled();
    });

    test('should show password strength indicator', async ({ page }) => {
      await page.goto('/settings');

      // Enter a weak password
      await page.fill('#new_password', 'weak1234');

      // Should show strength indicator
      await expect(page.locator('text=Weak')).toBeVisible();

      // Enter a stronger password
      await page.locator('#new_password').clear();
      await page.fill('#new_password', 'StrongPass123!@#');

      // Should show better strength
      await expect(page.locator('text=Strong').or(page.locator('text=Good'))).toBeVisible();
    });

    test('should validate password requirements', async ({ page }) => {
      await page.goto('/settings');

      // Enter password with no letters
      await page.fill('#new_password', '12345678');

      // Should show requirement not met
      const letterReq = page.locator('text=At least one letter');
      await expect(letterReq).toHaveClass(/text-gray-500/);

      // Enter password with no numbers
      await page.locator('#new_password').clear();
      await page.fill('#new_password', 'abcdefgh');

      // Should show requirement not met
      const numberReq = page.locator('text=At least one number');
      await expect(numberReq).toHaveClass(/text-gray-500/);

      // Enter valid password
      await page.locator('#new_password').clear();
      await page.fill('#new_password', 'ValidPass123');

      // All requirements should be met (green)
      await expect(page.locator('li.text-green-600')).toHaveCount(3);
    });

    test('should clear form after clicking clear button', async ({ page }) => {
      await page.goto('/settings');

      // Fill in form
      await page.fill('#current_password', 'somepassword');
      await page.fill('#new_password', 'newpassword123');
      await page.fill('#confirm_new_password', 'newpassword123');

      // Click clear button
      await page.click('button:has-text("Clear")');

      // All fields should be empty
      await expect(page.locator('#current_password')).toHaveValue('');
      await expect(page.locator('#new_password')).toHaveValue('');
      await expect(page.locator('#confirm_new_password')).toHaveValue('');
    });

    test('should navigate to profile settings', async ({ page }) => {
      await page.goto('/settings');

      // Click on profile settings link
      await page.click('a:has-text("Profile Settings")');

      // Should navigate to profile page
      await expect(page).toHaveURL('/profile');
    });
  });

  test.describe('Unauthenticated Access', () => {
    test('should redirect to login when accessing profile without auth', async ({ page, context }) => {
      // Clear cookies to simulate logged out state
      await context.clearCookies();

      // Try to access profile page
      await page.goto('/profile');

      // Should redirect to login
      await expect(page).toHaveURL(/\/login/);
    });

    test('should redirect to login when accessing settings without auth', async ({ page, context }) => {
      // Clear cookies to simulate logged out state
      await context.clearCookies();

      // Try to access settings page
      await page.goto('/settings');

      // Should redirect to login
      await expect(page).toHaveURL(/\/login/);
    });
  });
});
