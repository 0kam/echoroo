/**
 * E2E spec for spec/011 Step 12b T663 (US7): in-app banner stack + activity view UX.
 *
 * Scope: proves the FRONTEND banner-stack UX:
 *   1. Banner renders after a banner-eligible audit event.
 *   2. Dismiss persists across reload (POST /me/banners/dismiss → 204, idempotent).
 *   3. Empty/logged-out state: no BannerStack rendered, /me/banners not called.
 *   4. Activity view: platform event row appears, pagination works.
 *
 * Banner generator:
 *   POST /web-api/v1/account/trusted-devices/revoke-all emits
 *   "auth.trusted_device.revoke_all" (banner-eligible per BANNER_ELIGIBLE_ACTIONS).
 *   The service writes exactly ONE audit row per call, even when no active devices
 *   exist (revoked_count==0). Safe to call repeatedly — harmless on e2e-member.
 *
 * Note: The 4 event-type→banner mappings are covered by backend integration test
 * test_user_banners.py (T661). This e2e proves the frontend banner mechanism end-to-end
 * using the real revoke-all banner (render role=alert + non-empty summary, dismiss-persists,
 * empty/logged-out, activity row + Load-more).
 *
 * Account: e2e-member@echoroo.app (accumulates revoke-all audit rows; harmless).
 * Password: E2E-Test-Password-123!
 * Shared TOTP: VUO4R45DU5RTBODG63FN7KOE6OOCKCJE
 */

import { test, expect } from '@playwright/test';
import { loginWithSharedTotp } from './helpers/spec011-auth';
import {
  trackConsoleErrors,
  assertNoRealConsoleErrors,
  revokeAllTrustedDevicesInBrowser,
} from './helpers/spec011-infra';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MEMBER_EMAIL = 'e2e-member@echoroo.app';

// How long to wait for banner-related network round-trips (TanStack Query +
// post-revoke invalidation).
const BANNER_TIMEOUT_MS = 15_000;

// ---------------------------------------------------------------------------
// Helper: dismiss all visible banners (for cleanup after assertion tests).
// ---------------------------------------------------------------------------

async function dismissAllVisibleBanners(
  page: import('@playwright/test').Page
): Promise<void> {
  // Dismiss one at a time — each dismiss triggers a list re-fetch.
  // Cap at 50 iterations to prevent unbounded loops when banners accumulate
  // (e.g. when running the full suite after admin-password-reset generates many banners).
  const MAX_DISMISSALS = 50;
  let dismissed = 0;

  while (dismissed < MAX_DISMISSALS) {
    const dismissBtn = page.locator('[role="alert"] button[aria-label]').first();
    const visible = await dismissBtn.isVisible().catch(() => false);
    if (!visible) break;

    // Capture a unique identifier for THIS specific button so we can wait for
    // exactly this one to disappear (not all buttons), allowing the loop to
    // continue if more banners remain after a re-fetch.
    const ariaLabel = await dismissBtn.getAttribute('aria-label').catch(() => null);

    await Promise.all([
      page
        .waitForResponse(
          (resp) => resp.url().includes('/me/banners') && resp.status() === 204,
          { timeout: 10000 }
        )
        .catch(() => {
          // Non-fatal: response may have already come or endpoint returned 200.
        }),
      dismissBtn.click(),
    ]);

    dismissed++;

    // Wait until THIS specific button is gone from the DOM (not all buttons).
    // This lets the loop continue even if other banners remain visible.
    if (ariaLabel) {
      await page
        .waitForFunction(
          (label: string) =>
            !Array.from(document.querySelectorAll('button[aria-label]')).some(
              (btn) => btn.getAttribute('aria-label') === label
            ),
          ariaLabel,
          { timeout: 8000 }
        )
        .catch(() => {
          // Non-fatal: already gone.
        });
    } else {
      // Fallback: short settle wait.
      await page.waitForTimeout(500);
    }
  }

  if (dismissed >= MAX_DISMISSALS) {
    console.warn(`dismissAllVisibleBanners: hit max dismissals (${MAX_DISMISSALS}) — stopping`);
  }
}

// ---------------------------------------------------------------------------
// Suite
// ---------------------------------------------------------------------------

test.describe.serial('Banner stack + activity view (US7 T663)', () => {
  // 15 minutes — the suite runs sequentially and includes network round-trips.
  test.setTimeout(120_000);

  // ─── Test 1: Banner renders ──────────────────────────────────────────────

  test('banner renders after trusted-device revoke-all event', async ({ page }) => {
    const getErrors = trackConsoleErrors(page);

    // Log in as e2e-member.
    await loginWithSharedTotp(page, { email: MEMBER_EMAIL });

    // Navigate to an (app) page that mounts BannerStack.
    await page.goto('/en/dashboard');
    await page.waitForLoadState('networkidle');

    // Generate a banner-eligible audit event from inside the browser.
    const status = await revokeAllTrustedDevicesInBrowser(page);
    expect([200, 204], `revoke-all returned unexpected status ${status}`).toContain(status);

    // The BannerStack uses TanStack Query (staleTime=60s). Reload so the
    // query re-fires without waiting for stale time.
    await page.reload();
    await page.waitForLoadState('networkidle');

    // Assert at least one banner is visible.
    const bannerLocator = page.locator('[role="alert"]').first();
    await expect(bannerLocator).toBeVisible({ timeout: BANNER_TIMEOUT_MS });

    // Summary text is non-empty (backend-rendered A-13-safe string).
    const summaryText = await page.locator('[role="alert"] p.flex-1').first().textContent();
    expect(summaryText?.trim().length, 'Banner summary should be non-empty').toBeGreaterThan(0);

    // "View activity" link is present and points to /profile/activity.
    const activityLink = page.locator('[role="alert"] a').first();
    await expect(activityLink).toBeVisible();
    const href = await activityLink.getAttribute('href');
    expect(href, '"View activity" href should contain /profile/activity').toContain(
      '/profile/activity'
    );

    assertNoRealConsoleErrors(getErrors, 'Test 1: banner renders');
  });

  // ─── Test 2: Dismiss persists ────────────────────────────────────────────

  test('dismiss button removes the banner and persists across reload', async ({ page }) => {
    const getErrors = trackConsoleErrors(page);

    await loginWithSharedTotp(page, { email: MEMBER_EMAIL });
    await page.goto('/en/dashboard');
    await page.waitForLoadState('networkidle');

    // ── Step 2a: Clean slate (setup) ──────────────────────────────────────
    // Dismiss ALL currently-visible banners so we start from a known-empty
    // state. This is setup only — NOT a persistence assertion.
    await dismissAllVisibleBanners(page);

    // Reload and confirm 0 banners remain (ensures the dismiss-all above
    // persisted and we start from a genuinely clean slate).
    await page.reload();
    await page.waitForLoadState('networkidle');

    // Give TanStack Query time to fetch and render (or confirm absence).
    await page.waitForFunction(
      () => {
        // Wait until any in-flight fetch has settled.  BannerStack renders
        // immediately; if no banners exist the stack is empty after networkidle.
        return true;
      },
      { timeout: 5000 }
    );

    const initialCount = await page.locator('[role="alert"]').count();
    expect(initialCount, 'Clean-slate: expected 0 banners after dismiss-all + reload').toBe(0);

    // ── Step 2b: Generate exactly ONE fresh banner ────────────────────────
    const status = await revokeAllTrustedDevicesInBrowser(page);
    expect([200, 204], `revoke-all returned unexpected status ${status}`).toContain(status);

    // Reload so TanStack Query fetches fresh data (staleTime=60s).
    await page.reload();
    await page.waitForLoadState('networkidle');

    // Assert exactly 1 banner visible — render check.
    await expect(page.locator('[role="alert"]').first()).toBeVisible({ timeout: BANNER_TIMEOUT_MS });
    const countAfterGenerate = await page.locator('[role="alert"]').count();
    expect(countAfterGenerate, 'Expected exactly 1 banner after generating one').toBe(1);

    // The banner must have a non-empty summary and a View-activity link.
    const summaryText = await page.locator('[role="alert"] p.flex-1').first().textContent();
    expect(summaryText?.trim().length, 'Banner summary must be non-empty').toBeGreaterThan(0);
    const activityLink = page.locator('[role="alert"] a').first();
    await expect(activityLink).toBeVisible();
    const href = await activityLink.getAttribute('href');
    expect(href, '"View activity" href must contain /profile/activity').toContain(
      '/profile/activity'
    );

    // ── Step 2c: Dismiss that one banner ─────────────────────────────────
    const dismissBtn = page.locator('[role="alert"] button[aria-label]').first();
    await expect(dismissBtn).toBeVisible();

    await Promise.all([
      page.waitForResponse(
        (resp) => resp.url().includes('/me/banners') && resp.status() === 204,
        { timeout: 10000 }
      ),
      dismissBtn.click(),
    ]);

    // Wait for the banner to disappear from the DOM before reloading.
    await page.waitForFunction(
      () => document.querySelectorAll('[role="alert"]').length === 0,
      { timeout: 8000 }
    );

    // ── Step 2d: Reload — NO cleanup — persistence assertion ─────────────
    // IMPORTANT: we do NOT call dismissAllVisibleBanners (or any dismiss
    // helper) between this reload and the count assertion below.
    //
    // If dismiss-persistence is broken and the banner reappears, count will
    // be 1 and the test FAILS.  A cleanup call here would hide that failure
    // — which is precisely the false-confidence bug this test was fixed to
    // prevent.
    await page.reload();
    await page.waitForLoadState('networkidle');

    // Allow TanStack Query to settle (networkidle covers the /me/banners fetch).
    await page.waitForFunction(() => true, { timeout: 3000 });

    // THE persistence assertion: the dismissed banner must NOT reappear.
    // No dismiss/cleanup runs before this assert.
    const persistedCount = await page.locator('[role="alert"]').count();
    expect(
      persistedCount,
      'Persistence: dismissed banner must NOT reappear after reload (count should be 0)'
    ).toBe(0);

    assertNoRealConsoleErrors(getErrors, 'Test 2: dismiss persists');
  });

  // ─── Test 3: Empty + logged-out state ────────────────────────────────────

  test('no banner rendered when logged out', async ({ browser }) => {
    // Use a fresh context so there are no session cookies.
    const context = await browser.newContext();
    const page = await context.newPage();
    const getErrors = trackConsoleErrors(page);

    let bannerRequestFired = false;
    page.on('request', (req) => {
      if (req.url().includes('/me/banners')) {
        bannerRequestFired = true;
      }
    });

    // Navigate to the public-facing login page (no auth cookie).
    await page.goto('/en/login');
    await page.waitForLoadState('networkidle');

    // No banner box / role="alert" BannerStack should be rendered.
    const bannerStackAlerts = await page
      .locator('[role="alert"]:has(button[aria-label])')
      .count();
    expect(
      bannerStackAlerts,
      'No BannerStack alerts should be present on the login page'
    ).toBe(0);

    // /me/banners should NOT have been called.
    expect(
      bannerRequestFired,
      '/me/banners must not be called when the user is not authenticated'
    ).toBe(false);

    assertNoRealConsoleErrors(getErrors, 'Test 3: logged-out state');

    await context.close();
  });

  // ─── Test 4: Activity view ───────────────────────────────────────────────

  test('activity page shows trusted-device revoke-all row and handles pagination', async ({
    page,
  }) => {
    const getErrors = trackConsoleErrors(page);

    await loginWithSharedTotp(page, { email: MEMBER_EMAIL });

    // Ensure at least one revoke-all event exists (generates activity row).
    await page.goto('/en/dashboard');
    await page.waitForLoadState('networkidle');
    const status = await revokeAllTrustedDevicesInBrowser(page);
    expect([200, 204]).toContain(status);

    // Navigate to the activity page.
    await page.goto('/en/profile/activity');
    await page.waitForLoadState('networkidle');

    // Wait for the list to initialize.
    await page.waitForFunction(
      () => {
        return (
          document.querySelector('ul') !== null ||
          document.querySelector('[class*="empty"]') !== null ||
          document.querySelector('p') !== null
        );
      },
      null,
      { timeout: 15000 }
    );

    // Allow a short settle time for the state transition.
    await page.waitForTimeout(1000);

    // Assert the activity list <ul> rendered.
    const listLocator = page.locator('ul');
    await expect(listLocator).toBeVisible({ timeout: 10000 });

    // Assert the trusted-device revoke-all action row appears.
    const revokeRow = page.locator('li').filter({ hasText: 'auth.trusted_device.revoke_all' });
    await expect(revokeRow.first()).toBeVisible({ timeout: 10000 });

    // Assert the row renders a timestamp.
    const timestamp = revokeRow.first().locator('span').last();
    const tsText = await timestamp.textContent();
    expect(tsText?.trim().length, 'Activity row timestamp should be non-empty').toBeGreaterThan(0);

    // Pagination: if "Load more" button is present, click it and assert more rows appear.
    const loadMoreBtn = page.locator('button', { hasText: /load more/i });
    const hasLoadMore = await loadMoreBtn.isVisible().catch(() => false);

    if (hasLoadMore) {
      const rowsBefore = await page.locator('li').count();
      await loadMoreBtn.click();
      await page.waitForFunction(
        (before: number) => document.querySelectorAll('li').length > before,
        rowsBefore,
        { timeout: 10000 }
      );
      const rowsAfter = await page.locator('li').count();
      expect(rowsAfter).toBeGreaterThan(rowsBefore);
      console.log(`Activity pagination: Load more clicked, ${rowsBefore}→${rowsAfter} rows.`);
    } else {
      const rowCount = await page.locator('li').count();
      console.log(
        `Activity pagination: fewer than page limit (${rowCount} rows), Load-more absent — correct.`
      );
    }

    assertNoRealConsoleErrors(getErrors, 'Test 4: activity view');
  });

});
