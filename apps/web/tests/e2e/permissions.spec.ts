/**
 * E2E tests for project member permissions
 */

import { test, expect } from '@playwright/test';

// Test data
const adminUser = {
  email: 'admin@example.com',
  password: 'AdminPassword123!',
  displayName: 'Admin User',
};

const memberUser = {
  email: 'member@example.com',
  password: 'MemberPassword123!',
  displayName: 'Member User',
};

const viewerUser = {
  email: 'viewer@example.com',
  password: 'ViewerPassword123!',
  displayName: 'Viewer User',
};

const ownerUser = {
  email: 'owner@example.com',
  password: 'OwnerPassword123!',
  displayName: 'Owner User',
};

test.describe('Project Member Permissions', () => {
  // Helper function to login
  async function login(page: any, user: typeof adminUser) {
    await page.goto('/login');
    await page.fill('input[name="email"]', user.email);
    await page.fill('input[name="password"]', user.password);
    await page.click('button[type="submit"]');
    await page.waitForURL('/dashboard');
  }

  // Helper function to get a project ID
  async function getFirstProjectId(page: any): Promise<string> {
    await page.goto('/projects');
    await page.waitForSelector('.cursor-pointer');
    await page.click('.cursor-pointer:first-child');
    await page.waitForURL(/\/projects\/([a-f0-9-]+)$/);
    const url = page.url();
    const match = url.match(/\/projects\/([a-f0-9-]+)$/);
    return match ? match[1] : '';
  }

  test('admin can change member role', async ({ page }) => {
    // Login as admin
    await login(page, adminUser);

    // Get project ID
    const projectId = await getFirstProjectId(page);

    // Navigate to members page
    await page.goto(`/projects/${projectId}/members`);

    // Wait for members to load
    await page.waitForSelector('text=Members');

    // Find a member row (not the owner)
    const memberRows = page.locator('div:has(select)');
    const memberRow = memberRows.first();

    // Get current role
    const roleSelect = memberRow.locator('select');
    const currentRole = await roleSelect.inputValue();

    // Change role to different value
    const newRole = currentRole === 'member' ? 'viewer' : 'member';
    await roleSelect.selectOption(newRole);

    // Wait for confirmation dialog
    await expect(page.locator('text=Change Member Role')).toBeVisible();

    // Verify dialog shows old and new roles
    await expect(page.locator(`text=${currentRole.charAt(0).toUpperCase() + currentRole.slice(1)}`)).toBeVisible();
    await expect(page.locator(`text=${newRole.charAt(0).toUpperCase() + newRole.slice(1)}`)).toBeVisible();

    // Confirm role change
    await page.click('button:has-text("Change Role")');

    // Wait for dialog to close
    await expect(page.locator('text=Change Member Role')).not.toBeVisible();

    // Verify role was updated
    await expect(roleSelect).toHaveValue(newRole);
  });

  test('member cannot access settings page', async ({ page }) => {
    // Login as member
    await login(page, memberUser);

    // Get project ID
    const projectId = await getFirstProjectId(page);

    // Navigate to project detail
    await page.goto(`/projects/${projectId}`);

    // Settings button should not be visible for non-admin members
    const settingsButton = page.locator('button:has-text("Settings")');

    // If button exists, check if it's visible
    const buttonCount = await settingsButton.count();
    if (buttonCount > 0) {
      // Button might exist but be hidden or disabled
      await expect(settingsButton).not.toBeVisible();
    }

    // Try to access settings page directly
    await page.goto(`/projects/${projectId}/settings`);

    // Should see access denied message
    await expect(
      page.locator('text=You do not have permission to edit this project')
    ).toBeVisible();
  });

  test('viewer cannot edit project', async ({ page }) => {
    // Login as viewer
    await login(page, viewerUser);

    // Get project ID
    const projectId = await getFirstProjectId(page);

    // Navigate to project detail
    await page.goto(`/projects/${projectId}`);

    // Settings button should not be visible
    const settingsButton = page.locator('button:has-text("Settings")');
    const settingsButtonCount = await settingsButton.count();

    if (settingsButtonCount > 0) {
      await expect(settingsButton).not.toBeVisible();
    }

    // Try to access settings page directly
    await page.goto(`/projects/${projectId}/settings`);

    // Should see access denied message
    await expect(
      page.locator('text=You do not have permission to edit this project')
    ).toBeVisible();

    // Try to access members page directly
    await page.goto(`/projects/${projectId}/members`);

    // Should see access denied message
    await expect(
      page.locator('text=You do not have permission to manage project members')
    ).toBeVisible();
  });

  test('owner can delete project', async ({ page }) => {
    // Login as owner
    await login(page, ownerUser);

    // Navigate to projects
    await page.goto('/projects');

    // Get initial project count
    const initialCount = await page.locator('.cursor-pointer').count();

    // Click on a project that the user owns
    await page.click('.cursor-pointer:first-child');

    // Wait for project detail page
    await page.waitForURL(/\/projects\/[a-f0-9-]+$/);

    // Delete button should be visible for owner
    const deleteButton = page.locator('button:has-text("Delete")');
    await expect(deleteButton).toBeVisible();

    // Click delete
    await deleteButton.click();

    // Wait for confirmation dialog
    await expect(page.locator('text=Delete Project')).toBeVisible();

    // Confirm deletion
    await page.click('button:has-text("Delete")').last();

    // Wait for navigation back to projects list
    await page.waitForURL('/projects');

    // Verify project was deleted
    const newCount = await page.locator('.cursor-pointer').count();
    expect(newCount).toBe(initialCount - 1);
  });

  test('admin cannot delete project', async ({ page }) => {
    // Login as admin (not owner)
    await login(page, adminUser);

    // Get project ID
    const projectId = await getFirstProjectId(page);

    // Navigate to project detail
    await page.goto(`/projects/${projectId}`);

    // Delete button should not be visible for non-owner admin
    const deleteButton = page.locator('button:has-text("Delete")');
    const deleteButtonCount = await deleteButton.count();

    if (deleteButtonCount > 0) {
      await expect(deleteButton).not.toBeVisible();
    }
  });

  test('role tooltips show correct descriptions', async ({ page }) => {
    // Login as admin
    await login(page, adminUser);

    // Get project ID
    const projectId = await getFirstProjectId(page);

    // Navigate to members page
    await page.goto(`/projects/${projectId}/members`);

    // Wait for page to load
    await page.waitForSelector('text=Members');

    // Click add member button
    await page.click('button:has-text("Add Member")');

    // Hover over role info icon
    const infoIcon = page.locator('button svg').first();
    await infoIcon.hover();

    // Wait for tooltip to appear
    await page.waitForTimeout(300);

    // Verify tooltip contains role descriptions
    await expect(page.locator('text=Can manage members and edit project settings')).toBeVisible();
    await expect(page.locator('text=Can view and edit project data')).toBeVisible();
    await expect(page.locator('text=Can only view project data')).toBeVisible();
  });

  test('owner role cannot be changed', async ({ page }) => {
    // Login as admin or owner
    await login(page, ownerUser);

    // Get project ID
    const projectId = await getFirstProjectId(page);

    // Navigate to members page
    await page.goto(`/projects/${projectId}/members`);

    // Wait for members to load
    await page.waitForSelector('text=Members');

    // Find owner row (should have "(Owner)" label)
    const ownerRow = page.locator('text=(Owner)').locator('..');

    // Owner should have a disabled role indicator, not a select
    const roleSelect = ownerRow.locator('select');
    const roleSelectCount = await roleSelect.count();

    // Role selector should not exist for owner
    expect(roleSelectCount).toBe(0);

    // Should show "Owner" label instead
    await expect(page.locator('span:has-text("Owner")')).toBeVisible();
  });

  test('role change confirmation shows permission details', async ({ page }) => {
    // Login as admin
    await login(page, adminUser);

    // Get project ID
    const projectId = await getFirstProjectId(page);

    // Navigate to members page
    await page.goto(`/projects/${projectId}/members`);

    // Wait for members to load
    await page.waitForSelector('text=Members');

    // Find a member row (not the owner)
    const memberRows = page.locator('div:has(select)');
    const memberRow = memberRows.first();

    // Get current role
    const roleSelect = memberRow.locator('select');

    // Change role to admin
    await roleSelect.selectOption('admin');

    // Wait for confirmation dialog
    await expect(page.locator('text=Change Member Role')).toBeVisible();

    // Verify dialog shows new role description
    await expect(
      page.locator('text=Can manage members and edit project settings')
    ).toBeVisible();
  });

  test('member cannot add or remove members', async ({ page }) => {
    // Login as member
    await login(page, memberUser);

    // Get project ID
    const projectId = await getFirstProjectId(page);

    // Try to access members page directly
    await page.goto(`/projects/${projectId}/members`);

    // Should see access denied message
    await expect(
      page.locator('text=You do not have permission to manage project members')
    ).toBeVisible();

    // Add Member button should not be visible
    const addMemberButton = page.locator('button:has-text("Add Member")');
    const addMemberButtonCount = await addMemberButton.count();

    if (addMemberButtonCount > 0) {
      await expect(addMemberButton).not.toBeVisible();
    }
  });

  test('viewer cannot see manage members link on project detail', async ({ page }) => {
    // Login as viewer
    await login(page, viewerUser);

    // Get project ID
    const projectId = await getFirstProjectId(page);

    // Navigate to project detail
    await page.goto(`/projects/${projectId}`);

    // Wait for page to load
    await page.waitForSelector('h1');

    // Manage button should not be visible in members sidebar
    const manageButton = page.locator('button:has-text("Manage")');
    const manageButtonCount = await manageButton.count();

    if (manageButtonCount > 0) {
      await expect(manageButton).not.toBeVisible();
    }
  });
});
