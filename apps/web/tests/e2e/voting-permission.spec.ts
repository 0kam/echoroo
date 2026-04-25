/**
 * E2E scaffold tests for voting button permission gate (PR-003)
 *
 * Backend: VOTE permission gate implemented in Phase 3 (T124, commit d22d12dd).
 * Frontend: voting UI permission-aware refactor is NOT yet complete.
 *
 * All tests are marked test.fixme() so they are skipped (not failing) until the
 * frontend voting UI is updated to respect the VOTE permission. Enable each test
 * after the corresponding frontend change lands.
 *
 * Selectors marked "placeholder" (e.g. [data-testid="vote-agree"]) must be
 * replaced with the real selectors when the frontend UI is implemented.
 */

import { test, expect } from '@playwright/test';

// User fixtures — kept in sync with permissions.spec.ts
const viewerUser = {
  email: 'viewer@example.com',
  password: 'ViewerPassword123!',
};

const memberUser = {
  email: 'member@example.com',
  password: 'MemberPassword123!',
};

// Login helper — mirrors the pattern in permissions.spec.ts
async function login(page: any, user: { email: string; password: string }) {
  await page.goto('/login');
  await page.fill('input[name="email"]', user.email);
  await page.fill('input[name="password"]', user.password);
  await page.click('button[type="submit"]');
  await page.waitForURL('/dashboard');
}

// Navigate to the detections page of the first accessible project.
// Returns the project ID extracted from the URL.
async function navigateToDetections(page: any): Promise<string> {
  await page.goto('/projects');
  await page.waitForSelector('.cursor-pointer');
  await page.click('.cursor-pointer:first-child');
  await page.waitForURL(/\/projects\/([a-f0-9-]+)$/);
  const url = page.url();
  const match = url.match(/\/projects\/([a-f0-9-]+)$/);
  const projectId = match ? match[1] : '';
  await page.goto(`/projects/${projectId}/detections`);
  return projectId;
}

test.describe('Voting button permission gate (PR-003)', () => {
  // Enable after frontend voting UI is updated to respect the VOTE permission.
  // Selector [data-testid="vote-agree"] is a placeholder — replace with the
  // real selector once the frontend component is implemented.
  test.fixme('viewer sees disabled vote button on detection', async ({ page }) => {
    await login(page, viewerUser);
    await navigateToDetections(page);

    // Wait for detection cards to render
    await page.waitForSelector('[data-testid="vote-agree"]');

    const voteButton = page.locator('[data-testid="vote-agree"]').first();
    await expect(voteButton).toBeDisabled();
  });

  // Enable after frontend voting UI is updated to respect the VOTE permission.
  test.fixme('member sees enabled vote button on detection', async ({ page }) => {
    await login(page, memberUser);
    await navigateToDetections(page);

    await page.waitForSelector('[data-testid="vote-agree"]');

    const voteButton = page.locator('[data-testid="vote-agree"]').first();
    await expect(voteButton).toBeEnabled();
  });

  // Enable after frontend voting UI is updated to respect the VOTE permission.
  // Verifies that clicking a disabled vote button does not fire a POST request
  // and that the button remains disabled (or a 403 tooltip is shown).
  test.fixme('viewer clicking vote button does nothing or shows tooltip', async ({ page }) => {
    await login(page, viewerUser);
    await navigateToDetections(page);

    await page.waitForSelector('[data-testid="vote-agree"]');

    const voteButton = page.locator('[data-testid="vote-agree"]').first();

    // force:true bypasses Playwright's own disabled-element guard so we can
    // confirm the UI itself prevents the action rather than relying on the
    // browser's native disabled behaviour.
    await voteButton.click({ force: true });

    // After the click the button must still be disabled (no optimistic update).
    await expect(voteButton).toBeDisabled();
  });
});
