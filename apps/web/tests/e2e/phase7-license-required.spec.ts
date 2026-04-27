/**
 * E2E tests for Phase 7 US10 — License-required project creation (T324).
 *
 * Covers FR-085 acceptance scenarios:
 *
 *   1. With only `name` + `visibility` filled in, the submit button is
 *      DISABLED (FR-085 client-side guard).
 *   2. After picking a license (CC-BY) the submit button becomes ENABLED.
 *   3. Submitting a complete form (name + visibility + license) succeeds:
 *      the user is redirected to the new project's detail page and the
 *      project is reachable from the projects index.
 *   4. The license field label is locale-aware: `/en/*` shows "License *"
 *      and `/ja/*` shows "ライセンス *".
 *   5. (defensive) If the client guard is bypassed, a 422 from the API is
 *      caught and surfaced as an inline "License is required" error.
 *
 * Environment gate
 * ----------------
 * All tests are skipped unless `PHASE7_E2E_ENABLED=1` is set, mirroring the
 * env-gate pattern used by Phase 5's `guest-public-flow.spec.ts` and
 * Phase 6's `phase6-vote-flow.spec.ts`.  CI never runs this suite against
 * a cold database that has not been seeded with the test account.
 *
 * Required environment variables
 * --------------------------------
 *   PHASE7_E2E_ENABLED=1                Enable this suite.
 *
 * Optional environment variables
 * --------------------------------
 *   PHASE7_TEST_EMAIL                   Override the test login email.
 *                                       Defaults to `test@echoroo.app`
 *                                       (memory/test-accounts.md).
 *   PHASE7_TEST_PASSWORD                Override the test login password.
 *                                       Defaults to `N6Wz0IJXsQc4`.
 *
 *   The Playwright base URL is sourced from `playwright.config.ts`
 *   (`use.baseURL` / Playwright's standard `PLAYWRIGHT_TEST_BASE_URL` env
 *   var). This suite intentionally does NOT define its own
 *   `PHASE7_BASE_URL` override; rely on the shared config instead.
 *
 * How to run
 * ----------
 *     ./scripts/docker.sh dev
 *     PHASE7_E2E_ENABLED=1 \
 *       npx playwright test tests/e2e/phase7-license-required.spec.ts
 *
 * Notes
 * -----
 * - Each test logs in fresh via the `/login` form because the suite does
 *   not rely on a shared storageState fixture.  This matches the Phase 6
 *   pattern (login per test) and avoids leaking auth state between tests.
 * - The created project's name is timestamped so re-runs do not collide
 *   on the unique-name CHECK constraint.
 */

import { test, expect, type Page } from '@playwright/test';

// ---------------------------------------------------------------------------
// Env gate
// ---------------------------------------------------------------------------
const SUITE_ENABLED = process.env.PHASE7_E2E_ENABLED === '1';

// Shared test account fallback (memory/test-accounts.md). Phase 6 uses the
// same constants — keep them in sync with that suite to avoid drift.
const SHARED_TEST_EMAIL = 'test@echoroo.app';
const SHARED_TEST_PASSWORD = 'N6Wz0IJXsQc4';

const TEST_USER = {
  email: process.env.PHASE7_TEST_EMAIL ?? SHARED_TEST_EMAIL,
  password: process.env.PHASE7_TEST_PASSWORD ?? SHARED_TEST_PASSWORD,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function login(page: Page, creds: { email: string; password: string }): Promise<void> {
  await page.goto('/login');
  await page.fill('input[name="email"]', creds.email);
  await page.fill('input[name="password"]', creds.password);
  await Promise.all([
    page.waitForURL((url) => !url.pathname.startsWith('/login')),
    page.click('button[type="submit"]'),
  ]);
}

/**
 * Generate a unique-but-readable project name so concurrent or repeated
 * runs do not collide on a unique-name constraint.
 */
function uniqueProjectName(prefix: string): string {
  const ts = new Date().toISOString().replace(/[:.]/g, '-');
  return `${prefix} ${ts}`;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe('Phase 7 US10 — License-required project create (T324, FR-085)', () => {
  test.beforeEach(async () => {
    test.skip(!SUITE_ENABLED, 'PHASE7_E2E_ENABLED is not set');
  });

  // -------------------------------------------------------------------------
  // Scenario 1: submit button is disabled while license is unselected
  // -------------------------------------------------------------------------
  test('submit button is DISABLED when license is not selected', async ({ page }) => {
    await login(page, TEST_USER);
    await page.goto('/en/projects/new');

    // Fill in the required, license-independent fields.
    await page.fill('input[name="name"]', uniqueProjectName('Phase7 Disabled'));
    // visibility defaults to "private" via the radio group, no action needed.

    const submitBtn = page.locator('[data-testid="project-create-submit"]');
    await expect(submitBtn).toBeVisible();
    // The button must remain disabled because license has not been picked yet.
    await expect(submitBtn).toBeDisabled();
  });

  // -------------------------------------------------------------------------
  // Scenario 2: submit button becomes enabled once a license is chosen
  // -------------------------------------------------------------------------
  test('submit button becomes ENABLED after selecting a license', async ({ page }) => {
    await login(page, TEST_USER);
    await page.goto('/en/projects/new');

    await page.fill('input[name="name"]', uniqueProjectName('Phase7 Enabled'));

    const submitBtn = page.locator('[data-testid="project-create-submit"]');
    await expect(submitBtn).toBeDisabled();

    // Pick CC-BY in the license dropdown.
    await page.locator('[data-testid="license-select"]').selectOption('CC-BY');

    await expect(submitBtn).toBeEnabled();
  });

  // -------------------------------------------------------------------------
  // Scenario 3: full happy-path create succeeds and the project is reachable
  // -------------------------------------------------------------------------
  test('a full form (name + visibility + CC-BY) submits successfully', async ({ page }) => {
    await login(page, TEST_USER);
    await page.goto('/en/projects/new');

    const projectName = uniqueProjectName('Phase7 Created');
    await page.fill('input[name="name"]', projectName);
    await page.locator('[data-testid="license-select"]').selectOption('CC-BY');

    const submitBtn = page.locator('[data-testid="project-create-submit"]');
    await expect(submitBtn).toBeEnabled();

    // Submit. The page redirects to /projects/<uuid> on success.
    await Promise.all([
      page.waitForURL(/\/projects\/[0-9a-fA-F-]{36}/, { timeout: 15000 }),
      submitBtn.click(),
    ]);

    // The detail page should render the project's name in the heading.
    const heading = page.locator('h1').first();
    await expect(heading).toBeVisible({ timeout: 10000 });
    const headingText = (await heading.textContent()) ?? '';
    expect(
      headingText.includes(projectName.split(' ')[0]),
      'detail heading should contain the project name prefix',
    ).toBe(true);

    // Sanity: the projects index lists the new project as well.
    await page.goto('/en/projects');
    await expect(page.getByText(projectName, { exact: false }).first()).toBeVisible({
      timeout: 10000,
    });
  });

  // -------------------------------------------------------------------------
  // Scenario 4: i18n — /en shows "License *", /ja shows "ライセンス *"
  // -------------------------------------------------------------------------
  test('license field label is locale-aware (/en vs /ja)', async ({ page }) => {
    await login(page, TEST_USER);

    // English locale.
    await page.goto('/en/projects/new');
    await expect(
      page.locator('label[for="license"]', { hasText: /License/i }),
    ).toBeVisible({ timeout: 10000 });

    // Japanese locale.
    await page.goto('/ja/projects/new');
    await expect(
      page.locator('label[for="license"]', { hasText: 'ライセンス' }),
    ).toBeVisible({ timeout: 10000 });
  });

  // -------------------------------------------------------------------------
  // Scenario 5: API 422 (ERR_LICENSE_REQUIRED) surfaces the inline error
  //
  // The submit button is disabled while license==='' so a normal user can
  // never reach the API without a license.  This scenario verifies the
  // server-error envelope path by stripping the `license` field from the
  // POST body via a network route, simulating either a JS-disabled bypass
  // or a stale client.  The backend must respond with 422 and the UI must
  // surface "License is required" inline (and not silently swallow it).
  // -------------------------------------------------------------------------
  test('API 422 ERR_LICENSE_REQUIRED is caught and shown inline', async ({ page }) => {
    await login(page, TEST_USER);
    await page.goto('/en/projects/new');

    // Intercept the POST and strip the license field so the backend's
    // FR-085 422 path is exercised end-to-end.
    await page.route('**/api/v1/projects', async (route, request) => {
      if (request.method() !== 'POST') {
        await route.continue();
        return;
      }
      const original = request.postDataJSON() as Record<string, unknown> | null;
      const stripped = { ...(original ?? {}) };
      delete stripped['license'];
      await route.continue({
        postData: JSON.stringify(stripped),
        headers: {
          ...request.headers(),
          'content-type': 'application/json',
        },
      });
    });

    await page.fill('input[name="name"]', uniqueProjectName('Phase7 422'));
    await page.locator('[data-testid="license-select"]').selectOption('CC-BY');

    const submitBtn = page.locator('[data-testid="project-create-submit"]');
    await expect(submitBtn).toBeEnabled();
    await submitBtn.click();

    // The field-level error MUST surface inline next to the license dropdown.
    // It is the only legitimate announcement for ERR_LICENSE_REQUIRED — the
    // form-level alert is intentionally suppressed (see applyApiError() in
    // +page.svelte) so screen readers do not read the same copy twice.
    const fieldError = page.locator('p#license-error');
    await expect(fieldError).toBeVisible({ timeout: 10000 });
    await expect(fieldError).toHaveText(/License is required/i);
    // Both the field-level <p> and the form-level <div> share role="alert"
    // when rendered, so we lock in that the field-level error is the one
    // exposed to assistive tech. This catches a regression where a future
    // change reintroduces the form-level alert for license-required errors.
    await expect(fieldError).toHaveAttribute('role', 'alert');

    // Form-level alert MUST be absent (Codex Round 2 minor 1 regression
    // guard). The form-level <div> is conditionally rendered ({#if error}),
    // so asserting count=0 catches the case where it is mounted at all —
    // a hidden-but-present node would still indicate the suppression broke.
    const formAlert = page.locator('[data-testid="project-form-error"]');
    await expect(formAlert).toHaveCount(0);
  });
});
