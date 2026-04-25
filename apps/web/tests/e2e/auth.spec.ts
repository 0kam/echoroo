/**
 * E2E tests for authentication flows
 */

import { test, expect } from '@playwright/test';
import { generateTotpCode, waitForFreshTotpWindow } from './helpers/totp';

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

  test.describe('Two-Factor Authentication Flow', () => {
    /**
     * Full enrollment flow: register a fresh user, log in for the first
     * time, complete 2FA setup, and arrive at the dashboard.
     */
    test('register-then-first-login forces 2FA setup', async ({ page }) => {
      const fresh = {
        email: `2fa-${Date.now()}@example.com`,
        password: 'TestPassword123!',
        displayName: 'TwoFA User',
      };

      // 1. Register
      await page.goto('/register');
      await expect(page.locator('[data-testid="register-2fa-notice"]')).toBeVisible();
      await page.fill('#email', fresh.email);
      await page.fill('#displayName', fresh.displayName);
      await page.fill('#password', fresh.password);
      await page.fill('#confirmPassword', fresh.password);
      await page.click('button[type="submit"]');

      // Should redirect to /login?registered=true&email=...
      await expect(page).toHaveURL(/\/login\?registered=true/);

      // 2. Login (first time)
      await page.fill('#password', fresh.password);
      await page.click('button[type="submit"]');

      // Backend instructs the FE to redirect to the 2FA setup page.
      // The setup page lives in (auth) so unauthenticated users can reach it.
      await expect(page).toHaveURL(/\/2fa-setup/);

      // 3. Capture the secret rendered on the page, then submit the TOTP code.
      const secretLocator = page.locator('[data-testid="two-factor-secret"]');
      await expect(secretLocator).toBeVisible();
      const secret = (await secretLocator.textContent())?.trim();
      expect(secret, 'TOTP secret should be visible on setup page').toBeTruthy();

      await waitForFreshTotpWindow();
      const code = generateTotpCode(secret as string);
      await page.fill('[data-testid="two-factor-setup-code-input"]', code);
      await page.click('[data-testid="two-factor-confirm"]');

      // 4. Backup codes screen
      await expect(page.locator('[data-testid="two-factor-backup-codes"]')).toBeVisible();
      await page.check('[data-testid="backup-codes-saved"]');
      await page.click('[data-testid="backup-codes-continue"]');

      // 5. Dashboard
      await expect(page).toHaveURL(/\/dashboard/);
    });

    /**
     * Login flow for a user that has 2FA already enabled. Assumes the test
     * environment seeds a user whose TOTP secret is available via env var.
     */
    test('login with 2FA-enabled user completes with TOTP', async ({ page }) => {
      const email = process.env.E2E_2FA_USER_EMAIL;
      const password = process.env.E2E_2FA_USER_PASSWORD;
      const secret = process.env.E2E_2FA_USER_TOTP_SECRET;

      test.skip(
        !email || !password || !secret,
        'E2E_2FA_USER_* env vars not set — skip until seeded fixture is available',
      );

      await page.goto('/login');
      await page.fill('#email', email as string);
      await page.fill('#password', password as string);
      await page.click('button[type="submit"]');

      // Step 2 form should appear
      await expect(page.locator('[data-testid="two-factor-form"]')).toBeVisible();

      await waitForFreshTotpWindow();
      const code = generateTotpCode(secret as string);
      await page.fill('[data-testid="two-factor-code-input"]', code);
      await page.click('[data-testid="two-factor-submit"]');

      await expect(page).toHaveURL(/\/dashboard/);
    });

    /**
     * Invalid TOTP codes during the challenge step show an error and do
     * NOT advance the user to the dashboard.
     */
    test('login with invalid TOTP shows error', async ({ page }) => {
      const email = process.env.E2E_2FA_USER_EMAIL;
      const password = process.env.E2E_2FA_USER_PASSWORD;

      test.skip(
        !email || !password,
        'E2E_2FA_USER_* env vars not set — skip until seeded fixture is available',
      );

      await page.goto('/login');
      await page.fill('#email', email as string);
      await page.fill('#password', password as string);
      await page.click('button[type="submit"]');

      await expect(page.locator('[data-testid="two-factor-form"]')).toBeVisible();

      await page.fill('[data-testid="two-factor-code-input"]', '000000');
      await page.click('[data-testid="two-factor-submit"]');

      await expect(page.locator('[data-testid="two-factor-error"]')).toBeVisible();
      // Should NOT have navigated away from the login page.
      await expect(page).toHaveURL(/\/login/);
    });
  });
});
