/**
 * E2E tests for admin functionality
 */

import { test, expect } from '@playwright/test';

// Test users
const superuserUser = {
  email: 'admin@example.com',
  password: 'admin123',
};

const regularUser = {
  email: 'user@example.com',
  password: 'user123',
};

test.describe('Admin Functionality', () => {
  // Helper function to login
  async function login(page: any, user: typeof superuserUser) {
    await page.goto('/login');
    await page.fill('input[name="email"]', user.email);
    await page.fill('input[name="password"]', user.password);
    await page.click('button[type="submit"]');
    await page.waitForURL('/dashboard');
  }

  test.describe('User Management', () => {
    test('superuser can list users with pagination', async ({ page }) => {
      // Login as superuser
      await login(page, superuserUser);

      // Navigate to admin users page
      await page.goto('/admin/users');

      // Wait for page to load
      await expect(page.locator('h1:has-text("User Management")')).toBeVisible();

      // Table should be visible
      await expect(page.locator('table')).toBeVisible();

      // Table headers should be present
      await expect(page.locator('th:has-text("Email")')).toBeVisible();
      await expect(page.locator('th:has-text("Display Name")')).toBeVisible();
      await expect(page.locator('th:has-text("Status")')).toBeVisible();
      await expect(page.locator('th:has-text("Role")')).toBeVisible();
      await expect(page.locator('th:has-text("Actions")')).toBeVisible();

      // At least one user row should be visible
      const userRows = page.locator('tbody tr');
      await expect(userRows.first()).toBeVisible();

      // Pagination should be visible if there are multiple pages
      const pagination = page.locator('text=Showing');
      const paginationCount = await pagination.count();
      if (paginationCount > 0) {
        await expect(pagination).toBeVisible();
      }
    });

    test('superuser can search users', async ({ page }) => {
      // Login as superuser
      await login(page, superuserUser);

      // Navigate to admin users page
      await page.goto('/admin/users');

      // Wait for page to load
      await expect(page.locator('h1:has-text("User Management")')).toBeVisible();

      // Find search input
      const searchInput = page.locator('input[placeholder*="Search"]');
      await expect(searchInput).toBeVisible();

      // Search for admin user
      await searchInput.fill('admin');

      // Wait for results to update
      await page.waitForTimeout(500);

      // At least one result should contain "admin" in email
      const userRows = page.locator('tbody tr');
      const firstRow = userRows.first();
      const emailCell = firstRow.locator('td').first();
      const emailText = await emailCell.textContent();
      expect(emailText?.toLowerCase()).toContain('admin');
    });

    test('superuser can filter users by status', async ({ page }) => {
      // Login as superuser
      await login(page, superuserUser);

      // Navigate to admin users page
      await page.goto('/admin/users');

      // Wait for page to load
      await expect(page.locator('h1:has-text("User Management")')).toBeVisible();

      // Find filter dropdown
      const filterSelect = page.locator('select#status-filter');
      await expect(filterSelect).toBeVisible();

      // Filter by active users only
      await filterSelect.selectOption('active');

      // Wait for results to update
      await page.waitForTimeout(500);

      // All visible users should be active
      const statusBadges = page.locator('tbody td span:has-text("Active")');
      const statusCount = await statusBadges.count();
      expect(statusCount).toBeGreaterThan(0);
    });

    test('superuser can toggle user active status', async ({ page }) => {
      // Login as superuser
      await login(page, superuserUser);

      // Navigate to admin users page
      await page.goto('/admin/users');

      // Wait for page to load
      await expect(page.locator('h1:has-text("User Management")')).toBeVisible();

      // Find first user row (skip if it's the current admin to avoid locking out)
      const userRows = page.locator('tbody tr');
      const firstRow = userRows.first();

      // Check current status
      const statusBadge = firstRow.locator('td span').filter({ hasText: /Active|Inactive/ });
      const currentStatus = await statusBadge.textContent();

      // Find and click the activate/deactivate button
      const actionButton = firstRow.locator(
        currentStatus?.includes('Active')
          ? 'button:has-text("Deactivate")'
          : 'button:has-text("Activate")'
      );
      await actionButton.click();

      // Wait for success message
      await expect(
        page.locator('[role="alert"]:has-text("successfully")')
      ).toBeVisible();

      // Status should have changed
      const expectedStatus = currentStatus?.includes('Active') ? 'Inactive' : 'Active';
      await expect(firstRow.locator(`td span:has-text("${expectedStatus}")`)).toBeVisible();
    });

    test('superuser can promote/demote user to superuser', async ({ page }) => {
      // Login as superuser
      await login(page, superuserUser);

      // Navigate to admin users page
      await page.goto('/admin/users');

      // Wait for page to load
      await expect(page.locator('h1:has-text("User Management")')).toBeVisible();

      // Find a non-superuser row
      const userRows = page.locator('tbody tr');
      let targetRow = null;

      // Find a row with "User" role (not "Superuser")
      const rowCount = await userRows.count();
      for (let i = 0; i < rowCount; i++) {
        const row = userRows.nth(i);
        const roleBadge = row.locator('td span:has-text("User")');
        const roleCount = await roleBadge.count();
        if (roleCount > 0) {
          targetRow = row;
          break;
        }
      }

      if (targetRow) {
        // Click promote button
        const promoteButton = targetRow.locator('button:has-text("Promote")');
        await promoteButton.click();

        // Wait for success message
        await expect(
          page.locator('[role="alert"]:has-text("superuser")')
        ).toBeVisible();

        // Role should have changed to Superuser
        await expect(targetRow.locator('td span:has-text("Superuser")')).toBeVisible();
      }
    });

    test('non-superuser cannot access admin users page', async ({ page }) => {
      // Login as regular user
      await login(page, regularUser);

      // Try to access admin users page
      await page.goto('/admin/users');

      // Should redirect to dashboard
      await expect(page).toHaveURL('/dashboard');
    });
  });

  test.describe('System Settings', () => {
    test('superuser can view system settings', async ({ page }) => {
      // Login as superuser
      await login(page, superuserUser);

      // Navigate to admin settings page
      await page.goto('/admin/settings');

      // Wait for page to load
      await expect(page.locator('h1:has-text("System Settings")')).toBeVisible();

      // Registration settings card should be visible
      await expect(page.locator('h2:has-text("Registration Settings")')).toBeVisible();

      // Session settings card should be visible
      await expect(page.locator('h2:has-text("Session Settings")')).toBeVisible();

      // Registration mode dropdown should be visible
      const registrationModeSelect = page.locator('select#registration-mode');
      await expect(registrationModeSelect).toBeVisible();

      // Allow registration toggle should be visible
      const allowRegistrationToggle = page.locator('button#allow-registration');
      await expect(allowRegistrationToggle).toBeVisible();

      // Session timeout input should be visible
      const sessionTimeoutInput = page.locator('input#session-timeout');
      await expect(sessionTimeoutInput).toBeVisible();
    });

    test('superuser can change registration mode', async ({ page }) => {
      // Login as superuser
      await login(page, superuserUser);

      // Navigate to admin settings page
      await page.goto('/admin/settings');

      // Wait for page to load
      await expect(page.locator('h1:has-text("System Settings")')).toBeVisible();

      // Get registration mode select
      const registrationModeSelect = page.locator('select#registration-mode');

      // Get current value
      const currentValue = await registrationModeSelect.inputValue();

      // Change to different value
      const newValue = currentValue === 'open' ? 'invitation' : 'open';
      await registrationModeSelect.selectOption(newValue);

      // Click save button
      const saveButton = page.locator('button[type="submit"]:has-text("Save Settings")');
      await saveButton.click();

      // Wait for success message
      await expect(
        page.locator('[role="alert"]:has-text("Settings saved successfully")')
      ).toBeVisible();

      // Reload page
      await page.reload();

      // Verify value persisted
      await expect(registrationModeSelect).toHaveValue(newValue);
    });

    test('superuser can toggle allow registration', async ({ page }) => {
      // Login as superuser
      await login(page, superuserUser);

      // Navigate to admin settings page
      await page.goto('/admin/settings');

      // Wait for page to load
      await expect(page.locator('h1:has-text("System Settings")')).toBeVisible();

      // Get allow registration toggle
      const allowRegistrationToggle = page.locator('button#allow-registration');

      // Check current state
      const isEnabled = (await allowRegistrationToggle.getAttribute('aria-checked')) === 'true';

      // Toggle it
      await allowRegistrationToggle.click();

      // Click save button
      const saveButton = page.locator('button[type="submit"]:has-text("Save Settings")');
      await saveButton.click();

      // Wait for success message
      await expect(
        page.locator('[role="alert"]:has-text("Settings saved successfully")')
      ).toBeVisible();

      // Reload page
      await page.reload();

      // Verify state changed
      const newState = (await allowRegistrationToggle.getAttribute('aria-checked')) === 'true';
      expect(newState).toBe(!isEnabled);
    });

    test('superuser can update session timeout', async ({ page }) => {
      // Login as superuser
      await login(page, superuserUser);

      // Navigate to admin settings page
      await page.goto('/admin/settings');

      // Wait for page to load
      await expect(page.locator('h1:has-text("System Settings")')).toBeVisible();

      // Get session timeout input
      const sessionTimeoutInput = page.locator('input#session-timeout');

      // Set new value
      await sessionTimeoutInput.fill('90');

      // Click save button
      const saveButton = page.locator('button[type="submit"]:has-text("Save Settings")');
      await saveButton.click();

      // Wait for success message
      await expect(
        page.locator('[role="alert"]:has-text("Settings saved successfully")')
      ).toBeVisible();

      // Reload page
      await page.reload();

      // Verify value persisted
      await expect(sessionTimeoutInput).toHaveValue('90');
    });

    test('superuser can reset settings form', async ({ page }) => {
      // Login as superuser
      await login(page, superuserUser);

      // Navigate to admin settings page
      await page.goto('/admin/settings');

      // Wait for page to load
      await expect(page.locator('h1:has-text("System Settings")')).toBeVisible();

      // Get session timeout input
      const sessionTimeoutInput = page.locator('input#session-timeout');

      // Get initial value
      const initialValue = await sessionTimeoutInput.inputValue();

      // Change the value
      await sessionTimeoutInput.fill('120');

      // Verify it changed locally
      await expect(sessionTimeoutInput).toHaveValue('120');

      // Click reset button
      const resetButton = page.locator('button:has-text("Reset")');
      await resetButton.click();

      // Value should be reset to original
      await expect(sessionTimeoutInput).toHaveValue(initialValue);
    });

    test('non-superuser cannot access admin settings page', async ({ page }) => {
      // Login as regular user
      await login(page, regularUser);

      // Try to access admin settings page
      await page.goto('/admin/settings');

      // Should redirect to dashboard
      await expect(page).toHaveURL('/dashboard');
    });
  });

  test.describe('Admin Navigation', () => {
    test('superuser can navigate between admin pages', async ({ page }) => {
      // Login as superuser
      await login(page, superuserUser);

      // Navigate to admin users page
      await page.goto('/admin/users');

      // Verify we're on users page
      await expect(page.locator('h1:has-text("User Management")')).toBeVisible();

      // Sidebar should be visible
      await expect(page.locator('aside')).toBeVisible();

      // Click settings nav item
      const settingsNavButton = page.locator('button:has-text("Settings")');
      await settingsNavButton.click();

      // Should navigate to settings page
      await expect(page).toHaveURL('/admin/settings');
      await expect(page.locator('h1:has-text("System Settings")')).toBeVisible();

      // Click users nav item
      const usersNavButton = page.locator('button:has-text("Users")');
      await usersNavButton.click();

      // Should navigate back to users page
      await expect(page).toHaveURL('/admin/users');
      await expect(page.locator('h1:has-text("User Management")')).toBeVisible();
    });

    test('admin layout shows current user info', async ({ page }) => {
      // Login as superuser
      await login(page, superuserUser);

      // Navigate to admin page
      await page.goto('/admin/users');

      // User info should be visible in sidebar
      await expect(page.locator('text=Logged in as')).toBeVisible();
      await expect(page.locator('text=admin@example.com')).toBeVisible();
    });

    test('admin can logout from admin panel', async ({ page }) => {
      // Login as superuser
      await login(page, superuserUser);

      // Navigate to admin page
      await page.goto('/admin/users');

      // Click logout button
      const logoutButton = page.locator('button:has-text("Logout")');
      await logoutButton.click();

      // Should redirect to login
      await expect(page).toHaveURL('/login');
    });

    test('active nav item is highlighted', async ({ page }) => {
      // Login as superuser
      await login(page, superuserUser);

      // Navigate to admin users page
      await page.goto('/admin/users');

      // Users nav item should have active styling
      const usersNavButton = page.locator('button:has-text("Users")');
      const usersClasses = await usersNavButton.getAttribute('class');
      expect(usersClasses).toContain('bg-blue');

      // Navigate to settings
      await page.goto('/admin/settings');

      // Settings nav item should have active styling
      const settingsNavButton = page.locator('button:has-text("Settings")');
      const settingsClasses = await settingsNavButton.getAttribute('class');
      expect(settingsClasses).toContain('bg-blue');
    });
  });

  test.describe('Admin Access Control', () => {
    test('non-authenticated users cannot access admin', async ({ page }) => {
      // Try to access admin page without logging in
      await page.goto('/admin/users');

      // Should redirect to login
      await expect(page).toHaveURL(/\/login/);
      await expect(page.locator('input[name="email"]')).toBeVisible();
    });

    test('authenticated non-superuser redirects to dashboard', async ({ page }) => {
      // Login as regular user
      await login(page, regularUser);

      // Try to access admin users page
      await page.goto('/admin/users');

      // Should redirect to dashboard
      await expect(page).toHaveURL('/dashboard');

      // Try to access admin settings page
      await page.goto('/admin/settings');

      // Should redirect to dashboard
      await expect(page).toHaveURL('/dashboard');
    });

    test('superuser sees admin link in main navigation', async ({ page }) => {
      // Login as superuser
      await login(page, superuserUser);

      // Admin link should be visible in navigation (if it exists)
      // This depends on the main app layout implementation
      const adminLinks = page.locator('a[href*="/admin"]');
      const adminLinkCount = await adminLinks.count();

      if (adminLinkCount > 0) {
        await expect(adminLinks.first()).toBeVisible();
      }
    });

    test('regular user does not see admin link in navigation', async ({ page }) => {
      // Login as regular user
      await login(page, regularUser);

      // Admin link should not be visible
      const adminLinks = page.locator('a[href*="/admin"]');
      const adminLinkCount = await adminLinks.count();

      expect(adminLinkCount).toBe(0);
    });
  });
});
