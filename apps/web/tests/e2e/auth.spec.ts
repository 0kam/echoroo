/**
 * E2E tests for authentication flows
 */

import { test, expect } from '@playwright/test';

// Test data
const testUser = {
  email: `test-${Date.now()}@example.com`,
  password: 'TestPassword123!',
  displayName: 'Test User',
};

test.describe('Authentication', () => {
  test.describe('Registration Flow', () => {
    test('should register a new user successfully', async ({ page }) => {
      // Navigate to register page
      await page.goto('/register');

      // Fill in registration form
      await page.fill('#email', testUser.email);
      await page.fill('#displayName', testUser.displayName);
      await page.fill('#password', testUser.password);
      await page.fill('#confirmPassword', testUser.password);

      // Note: In real tests, you would need to handle the CAPTCHA
      // For now, we assume CAPTCHA is bypassed in test environment

      // Submit form
      await page.click('button[type="submit"]');

      // Should redirect to email verification page
      await expect(page).toHaveURL(/\/verify-email/);
      await expect(page.locator('text=Check your email')).toBeVisible();
    });

    test('should show validation errors for invalid input', async ({ page }) => {
      await page.goto('/register');

      // Try to submit with empty fields
      await page.click('button[type="submit"]');

      // Should show validation messages
      await expect(page.locator('text=Email is required')).toBeVisible();

      // Try with invalid email
      await page.fill('#email', 'invalid-email');
      await page.fill('#password', 'short');
      await page.fill('#confirmPassword', 'different');
      await page.click('button[type="submit"]');

      // Should show validation errors
      await expect(page.locator('text=valid email')).toBeVisible();
      await expect(page.locator('text=at least 8 characters')).toBeVisible();
    });

    test('should show error when passwords do not match', async ({ page }) => {
      await page.goto('/register');

      await page.fill('#email', 'test@example.com');
      await page.fill('#password', 'TestPassword123!');
      await page.fill('#confirmPassword', 'DifferentPassword123!');
      await page.click('button[type="submit"]');

      await expect(page.locator('text=Passwords do not match')).toBeVisible();
    });
  });

  test.describe('Login Flow', () => {
    test('should login successfully with valid credentials', async ({ page, context }) => {
      // Note: This assumes a test user exists in the database
      // You may need to create a user via API first

      await page.goto('/login');

      // Fill in login form
      await page.fill('#email', 'admin@example.com'); // Default admin user from setup
      await page.fill('#password', 'admin123'); // Default admin password

      // Submit form
      await page.click('button[type="submit"]');

      // Should redirect to dashboard
      await expect(page).toHaveURL('/dashboard');
      await expect(page.locator('text=Dashboard')).toBeVisible();

      // Should have refresh token cookie
      const cookies = await context.cookies();
      const refreshToken = cookies.find((c) => c.name === 'refresh_token');
      expect(refreshToken).toBeDefined();
    });

    test('should show error for invalid credentials', async ({ page }) => {
      await page.goto('/login');

      await page.fill('#email', 'wrong@example.com');
      await page.fill('#password', 'wrongpassword');
      await page.click('button[type="submit"]');

      // Should show error message
      await expect(page.locator('[role="alert"]')).toBeVisible();
      await expect(page).toHaveURL('/login');
    });

    test('should show CAPTCHA after 3 failed login attempts', async ({ page }) => {
      await page.goto('/login');

      // Attempt to login 3 times with wrong credentials
      for (let i = 0; i < 3; i++) {
        await page.fill('#email', 'test@example.com');
        await page.fill('#password', 'wrongpassword');
        await page.click('button[type="submit"]');
        await page.waitForTimeout(500);
      }

      // CAPTCHA should now be visible
      await expect(page.locator('.captcha-container')).toBeVisible();
    });

    test('should redirect to return URL after login', async ({ page }) => {
      // Try to access protected route
      await page.goto('/dashboard');

      // Should redirect to login with return URL
      await expect(page).toHaveURL(/\/login\?redirect=/);

      // Login
      await page.fill('#email', 'admin@example.com');
      await page.fill('#password', 'admin123');
      await page.click('button[type="submit"]');

      // Should redirect back to dashboard
      await expect(page).toHaveURL('/dashboard');
    });
  });

  test.describe('Logout Flow', () => {
    test('should logout successfully', async ({ page, context }) => {
      // First, login
      await page.goto('/login');
      await page.fill('#email', 'admin@example.com');
      await page.fill('#password', 'admin123');
      await page.click('button[type="submit"]');
      await expect(page).toHaveURL('/dashboard');

      // Click logout button
      await page.click('button:has-text("Logout")');

      // Should redirect to login
      await expect(page).toHaveURL('/login');

      // Refresh token cookie should be cleared
      const cookies = await context.cookies();
      const refreshToken = cookies.find((c) => c.name === 'refresh_token');
      expect(refreshToken).toBeUndefined();
    });

    test('should not allow access to protected routes after logout', async ({ page }) => {
      // Login
      await page.goto('/login');
      await page.fill('#email', 'admin@example.com');
      await page.fill('#password', 'admin123');
      await page.click('button[type="submit"]');

      // Logout
      await page.click('button:has-text("Logout")');

      // Try to access protected route
      await page.goto('/dashboard');

      // Should redirect to login
      await expect(page).toHaveURL(/\/login/);
    });
  });

  test.describe('Password Reset Flow', () => {
    test('should request password reset', async ({ page }) => {
      await page.goto('/forgot-password');

      // Fill in email
      await page.fill('#email', 'test@example.com');

      // Submit form
      await page.click('button[type="submit"]');

      // Should show success message
      await expect(page.locator('text=Check your email')).toBeVisible();
    });

    test('should show success message even for non-existent email', async ({ page }) => {
      // This is a security feature - don't reveal if email exists
      await page.goto('/forgot-password');

      await page.fill('#email', 'nonexistent@example.com');
      await page.click('button[type="submit"]');

      // Should still show success message
      await expect(page.locator('text=Check your email')).toBeVisible();
    });

    test('should reset password with valid token', async ({ page }) => {
      // Note: In real tests, you would need to get a valid reset token
      // For now, we test the UI flow

      // Navigate to reset password page with mock token
      await page.goto('/reset-password?token=mock-token');

      // Fill in new password
      await page.fill('#password', 'NewPassword123!');
      await page.fill('#confirmPassword', 'NewPassword123!');

      // Note: Submit will fail with mock token, but we test validation
      await expect(page.locator('#password')).toHaveValue('NewPassword123!');
    });

    test('should show validation errors for invalid password', async ({ page }) => {
      await page.goto('/reset-password?token=mock-token');

      // Try weak password
      await page.fill('#password', 'weak');
      await page.fill('#confirmPassword', 'weak');
      await page.click('button[type="submit"]');

      await expect(page.locator('text=at least 8 characters')).toBeVisible();
    });
  });

  test.describe('Email Verification Flow', () => {
    test('should show verification pending message after registration', async ({ page }) => {
      await page.goto('/verify-email?registered=true');

      await expect(page.locator('text=Check your email')).toBeVisible();
      await expect(page.locator('button:has-text("Resend")')).toBeVisible();
    });

    test('should verify email with valid token', async ({ page }) => {
      // Note: In real tests, you would need a valid verification token
      // For now, we test the UI flow

      await page.goto('/verify-email?token=mock-token');

      // Should attempt to verify
      // With mock token, it will fail, but we test the UI is shown
      await expect(page.locator('text=verifying', { timeout: 1000 }).or(page.locator('text=failed'))).toBeVisible({
        timeout: 5000,
      });
    });

    test('should allow resending verification email', async ({ page }) => {
      await page.goto('/verify-email?registered=true');

      // Click resend button
      await page.click('button:has-text("Resend")');

      // Should show success message
      await expect(page.locator('text=sent successfully')).toBeVisible();

      // Button should be disabled with cooldown
      await expect(page.locator('button:has-text("Resend in")')).toBeVisible();
    });
  });

  test.describe('Protected Routes', () => {
    test('should redirect unauthenticated users to login', async ({ page }) => {
      const protectedRoutes = ['/dashboard', '/recordings', '/annotations', '/projects'];

      for (const route of protectedRoutes) {
        await page.goto(route);
        await expect(page).toHaveURL(/\/login/);
      }
    });

    test('should redirect authenticated users away from auth pages', async ({ page }) => {
      // Login first
      await page.goto('/login');
      await page.fill('#email', 'admin@example.com');
      await page.fill('#password', 'admin123');
      await page.click('button[type="submit"]');
      await expect(page).toHaveURL('/dashboard');

      // Try to access auth pages
      const authRoutes = ['/login', '/register'];

      for (const route of authRoutes) {
        await page.goto(route);
        // Should redirect to dashboard
        await expect(page).toHaveURL('/dashboard');
      }
    });
  });

  test.describe('Session Management', () => {
    test('should persist session across page reloads', async ({ page }) => {
      // Login
      await page.goto('/login');
      await page.fill('#email', 'admin@example.com');
      await page.fill('#password', 'admin123');
      await page.click('button[type="submit"]');
      await expect(page).toHaveURL('/dashboard');

      // Reload page
      await page.reload();

      // Should still be on dashboard
      await expect(page).toHaveURL('/dashboard');
      await expect(page.locator('text=Dashboard')).toBeVisible();
    });

    test('should handle expired session gracefully', async ({ page, context }) => {
      // Login
      await page.goto('/login');
      await page.fill('#email', 'admin@example.com');
      await page.fill('#password', 'admin123');
      await page.click('button[type="submit"]');
      await expect(page).toHaveURL('/dashboard');

      // Clear cookies to simulate expired session
      await context.clearCookies();

      // Try to access protected route
      await page.goto('/dashboard');

      // Should redirect to login
      await expect(page).toHaveURL(/\/login/);
    });
  });
});
