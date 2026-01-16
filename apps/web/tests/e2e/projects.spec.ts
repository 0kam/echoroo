/**
 * E2E tests for project management
 */

import { test, expect } from '@playwright/test';

// Test data
const testUser = {
  email: 'test@example.com',
  password: 'TestPassword123!',
  displayName: 'Test User',
};

const testProject = {
  name: 'Test Project',
  description: 'This is a test project for bioacoustic analysis',
  targetTaxa: 'Passeriformes',
};

const testMember = {
  email: 'member@example.com',
  role: 'member',
};

test.describe('Project Management', () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to login page
    await page.goto('/login');

    // Login with test user
    await page.fill('input[name="email"]', testUser.email);
    await page.fill('input[name="password"]', testUser.password);
    await page.click('button[type="submit"]');

    // Wait for navigation to dashboard
    await page.waitForURL('/dashboard');
  });

  test('should create a new project', async ({ page }) => {
    // Navigate to projects page
    await page.goto('/projects');

    // Click "New Project" button
    await page.click('button:has-text("New Project")');

    // Wait for navigation to new project page
    await page.waitForURL('/projects/new');

    // Fill in project details
    await page.fill('input[name="name"]', testProject.name);
    await page.fill('textarea[name="description"]', testProject.description);
    await page.fill('input[name="targetTaxa"]', testProject.targetTaxa);

    // Select visibility (default is private)
    await page.check('input[name="visibility"][value="private"]');

    // Submit form
    await page.click('button[type="submit"]:has-text("Create Project")');

    // Wait for navigation to project detail page
    await page.waitForURL(/\/projects\/[a-f0-9-]+$/);

    // Verify project was created
    await expect(page.locator('h1')).toContainText(testProject.name);
    await expect(page.locator('text=' + testProject.description)).toBeVisible();
  });

  test('should edit project settings', async ({ page }) => {
    // Assume we have a project created in beforeEach or setup
    // For this test, we'll navigate to projects and select the first one
    await page.goto('/projects');

    // Click on first project
    await page.click('.cursor-pointer:first-child');

    // Wait for project detail page
    await page.waitForURL(/\/projects\/[a-f0-9-]+$/);

    // Click Settings button (only visible to admins)
    await page.click('button:has-text("Settings")');

    // Wait for settings page
    await page.waitForURL(/\/projects\/[a-f0-9-]+\/settings$/);

    // Update project name
    const updatedName = 'Updated ' + testProject.name;
    await page.fill('input[name="name"]', updatedName);

    // Change visibility to public
    await page.check('input[name="visibility"][value="public"]');

    // Save changes
    await page.click('button[type="submit"]:has-text("Save Changes")');

    // Wait for success message
    await expect(page.locator('text=Project settings saved successfully')).toBeVisible();

    // Navigate back to project detail
    await page.click('button:has-text("Cancel")');

    // Verify changes
    await expect(page.locator('h1')).toContainText(updatedName);
    await expect(page.locator('text=Public')).toBeVisible();
  });

  test('should add a member to project', async ({ page }) => {
    // Navigate to projects
    await page.goto('/projects');

    // Click on first project
    await page.click('.cursor-pointer:first-child');

    // Navigate to members page
    await page.click('button:has-text("Manage")');

    // Wait for members page
    await page.waitForURL(/\/projects\/[a-f0-9-]+\/members$/);

    // Click "Add Member" button
    await page.click('button:has-text("Add Member")');

    // Fill in member email
    await page.fill('input[type="email"]', testMember.email);

    // Select role
    await page.selectOption('select[id="role"]', testMember.role);

    // Submit
    await page.click('button[type="submit"]:has-text("Add")');

    // Wait for member to appear in list
    await expect(page.locator(`text=${testMember.email}`)).toBeVisible();
  });

  test('should change member role', async ({ page }) => {
    // Navigate to projects
    await page.goto('/projects');

    // Click on first project
    await page.click('.cursor-pointer:first-child');

    // Navigate to members page
    await page.click('button:has-text("Manage")');

    // Wait for members page
    await page.waitForURL(/\/projects\/[a-f0-9-]+\/members$/);

    // Find member and change role
    // Assuming the member exists from previous test
    const memberRow = page.locator(`text=${testMember.email}`).locator('..');

    // Change role to admin
    await memberRow.locator('select').selectOption('admin');

    // Wait for update to complete
    await page.waitForTimeout(1000);

    // Verify role was updated
    const roleSelect = memberRow.locator('select');
    await expect(roleSelect).toHaveValue('admin');
  });

  test('should remove a member from project', async ({ page }) => {
    // Navigate to projects
    await page.goto('/projects');

    // Click on first project
    await page.click('.cursor-pointer:first-child');

    // Navigate to members page
    await page.click('button:has-text("Manage")');

    // Wait for members page
    await page.waitForURL(/\/projects\/[a-f0-9-]+\/members$/);

    // Find member and click remove
    const memberRow = page.locator(`text=${testMember.email}`).locator('..');
    await memberRow.locator('button:has-text("Remove")').click();

    // Confirm removal in dialog
    await page.click('button:has-text("Remove")').last();

    // Wait for member to be removed
    await expect(page.locator(`text=${testMember.email}`)).not.toBeVisible();
  });

  test('should delete a project', async ({ page }) => {
    // Navigate to projects
    await page.goto('/projects');

    // Get initial project count
    const initialCount = await page.locator('.cursor-pointer').count();

    // Click on first project
    await page.click('.cursor-pointer:first-child');

    // Click Delete button (only visible to owner)
    await page.click('button:has-text("Delete")');

    // Confirm deletion in dialog
    await page.click('button:has-text("Delete")').last();

    // Wait for navigation back to projects list
    await page.waitForURL('/projects');

    // Verify project was deleted
    const newCount = await page.locator('.cursor-pointer').count();
    expect(newCount).toBe(initialCount - 1);
  });

  test('should show empty state when no projects', async ({ page }) => {
    // This test assumes user has no projects
    // In a real scenario, you might need to delete all projects first
    await page.goto('/projects');

    // Wait for empty state
    await expect(page.locator('text=No projects')).toBeVisible();
    await expect(page.locator('text=Get started by creating a new project')).toBeVisible();
  });

  test('should navigate between project pages', async ({ page }) => {
    // Navigate to projects
    await page.goto('/projects');

    // Click on a project
    await page.click('.cursor-pointer:first-child');

    // Verify we're on project detail page
    await expect(page).toHaveURL(/\/projects\/[a-f0-9-]+$/);

    // Navigate to settings
    await page.click('button:has-text("Settings")');
    await expect(page).toHaveURL(/\/projects\/[a-f0-9-]+\/settings$/);

    // Navigate back to project
    await page.click('button:has-text("Cancel")');
    await expect(page).toHaveURL(/\/projects\/[a-f0-9-]+$/);

    // Navigate to members
    await page.click('button:has-text("Manage")');
    await expect(page).toHaveURL(/\/projects\/[a-f0-9-]+\/members$/);

    // Navigate back to project list
    await page.click('a:has-text("Back to Project")');
    await expect(page).toHaveURL(/\/projects\/[a-f0-9-]+$/);
  });

  test('should enforce admin permissions', async ({ page }) => {
    // This test would require a non-admin user account
    // Skip for now or implement with proper test setup

    // Navigate to projects
    await page.goto('/projects');

    // Find a project where current user is not admin
    // This would require test data setup

    // Try to access settings
    // Should see "Access Denied" or settings button not visible

    test.skip();
  });

  test('should validate project form', async ({ page }) => {
    // Navigate to new project page
    await page.goto('/projects/new');

    // Try to submit without name
    await page.click('button[type="submit"]');

    // Should show validation error
    // HTML5 validation should prevent submission

    // Fill in name that's too long
    await page.fill('input[name="name"]', 'a'.repeat(201));
    await page.click('button[type="submit"]');

    // Should show error message
    await expect(page.locator('text=must be less than 200 characters')).toBeVisible();
  });

  test('should handle pagination in project list', async ({ page }) => {
    // This test assumes there are enough projects to paginate
    await page.goto('/projects');

    // Check if pagination is visible
    const paginationVisible = await page.locator('button:has-text("Next")').isVisible();

    if (paginationVisible) {
      // Click next page
      await page.click('button:has-text("Next")');

      // Verify page parameter in URL
      await expect(page).toHaveURL(/page=2/);

      // Click previous
      await page.click('button:has-text("Previous")');

      // Should be back to page 1
      await expect(page).toHaveURL(/projects/);
    } else {
      // Not enough projects to test pagination
      test.skip();
    }
  });
});
