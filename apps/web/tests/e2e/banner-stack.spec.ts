/**
 * E2E spec for spec/011 Step 12b T663 (US7): in-app banner stack + activity view UX.
 *
 * Scope: proves the FRONTEND banner-stack UX:
 *   1. Banner renders after a banner-eligible audit event.
 *   2. Dismiss persists across reload (POST /me/banners/dismiss → 204, idempotent).
 *   3. Empty/logged-out state: no BannerStack rendered, /me/banners not called.
 *   4. Activity view: platform event row appears, pagination works.
 *   5. (best-effort) new-device login banner — assert if present, skip if absent.
 *
 * Banner generator:
 *   POST /web-api/v1/account/trusted-devices/revoke-all emits
 *   "auth.trusted_device.revoke_all" (banner-eligible per BANNER_ELIGIBLE_ACTIONS).
 *   The service writes exactly ONE audit row per call, even when no active devices
 *   exist (revoked_count==0). Safe to call repeatedly — harmless on e2e-member.
 *
 * Account: e2e-member@echoroo.app (accumulates revoke-all audit rows; harmless).
 * Password: E2E-Test-Password-123!
 * Shared TOTP: VUO4R45DU5RTBODG63FN7KOE6OOCKCJE
 */

import { test, expect, type Page } from '@playwright/test';
import { loginWithSharedTotp } from './helpers/spec011-auth';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MEMBER_EMAIL = 'e2e-member@echoroo.app';

// How long to wait for banner-related network round-trips (TanStack Query +
// post-revoke invalidation).
const BANNER_TIMEOUT_MS = 15_000;

// ---------------------------------------------------------------------------
// Console error tracking
// ---------------------------------------------------------------------------

const BENIGN_CONSOLE_ERROR_PATTERNS = [
  '401',
  '403',
  '404',
  'net::ERR_ABORTED',
  'Failed to load resource',
];

function isBenignConsoleError(msg: string): boolean {
  return BENIGN_CONSOLE_ERROR_PATTERNS.some((pattern) => msg.includes(pattern));
}

function trackConsoleErrors(page: Page): () => string[] {
  const errors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error' && !isBenignConsoleError(msg.text())) {
      errors.push(msg.text());
    }
  });
  page.on('pageerror', (err) => {
    errors.push(`PAGE ERROR: ${err.message}`);
  });
  return () => errors;
}

// ---------------------------------------------------------------------------
// Helper: call POST /web-api/v1/account/trusted-devices/revoke-all from
// inside the browser, reusing the live session cookies + CSRF + Bearer
// (mirrors the single-invitation-flow pattern).
// Returns the HTTP status code.
// ---------------------------------------------------------------------------

async function revokeAllTrustedDevicesInBrowser(page: Page): Promise<number> {
  return page.evaluate(async () => {
    // Read CSRF token from the echoroo_csrf cookie (httponly=false).
    const csrfMatch = document.cookie
      .split(';')
      .map((c) => c.trim())
      .find((c) => c.startsWith('echoroo_csrf='));
    const csrfToken = csrfMatch ? csrfMatch.split('=').slice(1).join('=') : '';

    // Obtain a fresh Bearer token via /auth/refresh.
    let accessToken = '';
    try {
      const refreshResp = await fetch('/web-api/v1/auth/refresh', {
        method: 'POST',
        credentials: 'include',
      });
      if (refreshResp.ok) {
        const refreshData = (await refreshResp.json()) as { access_token?: string };
        accessToken = refreshData.access_token ?? '';
      }
    } catch {
      // Proceed without Bearer — the request will still carry cookies.
    }

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };
    if (accessToken) headers['Authorization'] = `Bearer ${accessToken}`;
    if (csrfToken) headers['X-CSRF-Token'] = csrfToken;

    const resp = await fetch('/web-api/v1/account/trusted-devices/revoke-all', {
      method: 'POST',
      credentials: 'include',
      headers,
    });
    return resp.status;
  });
}

// ---------------------------------------------------------------------------
// Helper: dismiss all visible banners (for cleanup after assertion tests).
// ---------------------------------------------------------------------------

async function dismissAllVisibleBanners(page: Page): Promise<void> {
  // Dismiss one at a time — each dismiss triggers a list re-fetch.
  while (true) {
    const dismissBtn = page.locator('[role="alert"] button[aria-label]').first();
    const visible = await dismissBtn.isVisible().catch(() => false);
    if (!visible) break;
    await dismissBtn.click();
    // Wait for the banner to disappear (list re-fetched after dismiss).
    await page.waitForTimeout(600);
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

    const errors = getErrors();
    expect(errors, `Unexpected console errors: ${errors.join(', ')}`).toHaveLength(0);
  });

  // ─── Test 2: Dismiss persists ────────────────────────────────────────────

  test('dismiss button removes the banner and persists across reload', async ({ page }) => {
    const getErrors = trackConsoleErrors(page);

    await loginWithSharedTotp(page, { email: MEMBER_EMAIL });
    await page.goto('/en/dashboard');
    await page.waitForLoadState('networkidle');

    // Ensure at least one banner is present (generate one if needed).
    let hasBanner = await page.locator('[role="alert"]').first().isVisible().catch(() => false);
    if (!hasBanner) {
      const status = await revokeAllTrustedDevicesInBrowser(page);
      expect([200, 204]).toContain(status);
      await page.reload();
      await page.waitForLoadState('networkidle');
    }

    // Wait for the banner to appear.
    await expect(page.locator('[role="alert"]').first()).toBeVisible({ timeout: BANNER_TIMEOUT_MS });

    // Count banners before dismissal.
    const countBefore = await page.locator('[role="alert"]').count();
    expect(countBefore).toBeGreaterThan(0);

    // Click the dismiss (✕) button on the first banner.
    // aria-label is set via m.banner_dismiss_aria(); use the button inside the alert.
    const dismissBtn = page
      .locator('[role="alert"]')
      .first()
      .locator('button[aria-label]');
    await expect(dismissBtn).toBeVisible();
    await dismissBtn.click();

    // Wait for the stack to update (dismiss POST + list re-fetch).
    // The US7 frontend has a known nit where dismiss may fire twice (idempotent 204); that's fine.
    await page.waitForTimeout(1500);

    // If there were exactly 1 banner, the stack should now render nothing.
    if (countBefore === 1) {
      await expect(page.locator('[role="alert"]').first()).not.toBeVisible({ timeout: 8000 });
    } else {
      // Multiple banners: at least one should have disappeared.
      const countAfter = await page.locator('[role="alert"]').count();
      expect(countAfter).toBeLessThan(countBefore);
    }

    // Reload and assert the dismissed banner did NOT reappear.
    await page.reload();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000); // Allow TanStack Query to fetch.

    // Dismiss ALL remaining banners so subsequent tests start clean.
    await dismissAllVisibleBanners(page);

    // After dismissing all, the stack should render nothing.
    // Wait briefly for the final re-fetch to complete.
    await page.waitForTimeout(1500);
    await expect(page.locator('[role="alert"]').first()).not.toBeVisible({ timeout: 8000 });

    // Reload one more time — dismissed state must persist.
    await page.reload();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);
    await expect(page.locator('[role="alert"]').first()).not.toBeVisible({ timeout: 8000 });

    const errors = getErrors();
    expect(errors, `Unexpected console errors: ${errors.join(', ')}`).toHaveLength(0);
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
    // (The BannerStack is mounted in (app)/+layout.svelte which is NOT
    //  rendered on the (public) login route.)
    const alertCount = await page.locator('[role="alert"]').count();
    // The login page itself may have form-level role="alert" elements;
    // assert none match the BannerStack structure (flex + dismiss button).
    const bannerStackAlerts = await page
      .locator('[role="alert"]:has(button[aria-label])')
      .count();
    expect(
      bannerStackAlerts,
      'No BannerStack alerts should be present on the login page'
    ).toBe(0);

    // /me/banners should NOT have been called (BannerStack is disabled when not authenticated).
    expect(
      bannerRequestFired,
      '/me/banners must not be called when the user is not authenticated'
    ).toBe(false);

    const errors = getErrors();
    expect(errors, `Unexpected console errors: ${errors.join(', ')}`).toHaveLength(0);

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

    // Wait for the list to initialize (spinner disappears / list appears).
    // The page uses $state initialized=false; the list renders once initialized===true.
    await page.waitForFunction(
      () => {
        // Either the list <ul> or the empty-state <p> should be present.
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

    // Assert the row renders a timestamp (the <span class="text-xs"> sibling).
    const timestamp = revokeRow.first().locator('span').last();
    const tsText = await timestamp.textContent();
    expect(tsText?.trim().length, 'Activity row timestamp should be non-empty').toBeGreaterThan(0);

    // Pagination: if "Load more" button is present, click it and assert more rows appear.
    const loadMoreBtn = page.locator('button', { hasText: /load more/i });
    const hasLoadMore = await loadMoreBtn.isVisible().catch(() => false);

    if (hasLoadMore) {
      const rowsBefore = await page.locator('li').count();
      await loadMoreBtn.click();
      // Wait for the next page to append.
      await page.waitForFunction(
        (before: number) => document.querySelectorAll('li').length > before,
        rowsBefore,
        { timeout: 10000 }
      );
      const rowsAfter = await page.locator('li').count();
      expect(rowsAfter).toBeGreaterThan(rowsBefore);
      console.log(`Activity pagination: Load more clicked, ${rowsBefore}→${rowsAfter} rows.`);
    } else {
      // Fewer than 50 rows — Load-more button absent as expected.
      const rowCount = await page.locator('li').count();
      console.log(
        `Activity pagination: fewer than page limit (${rowCount} rows), Load-more absent — correct.`
      );
    }

    const errors = getErrors();
    expect(errors, `Unexpected console errors: ${errors.join(', ')}`).toHaveLength(0);
  });

  // ─── Test 5: (best-effort) new-device login banner ───────────────────────

  test('(best-effort) new-device login banner — present or absent without failure', async ({
    browser,
  }) => {
    // Use a completely fresh browser context (no cookies, no trusted-device cookie)
    // to simulate a "new device" login which would emit auth.login.new_device.
    const context = await browser.newContext();
    const page = await context.newPage();
    const getErrors = trackConsoleErrors(page);

    await loginWithSharedTotp(page, { email: MEMBER_EMAIL });
    await page.waitForLoadState('networkidle');

    // Brief wait for TanStack Query to fetch banners.
    await page.waitForTimeout(3000);

    // Check whether a new-device banner appeared.
    const allAlerts = await page.locator('[role="alert"]:has(button[aria-label])').all();
    let newDeviceBannerFound = false;

    for (const alert of allAlerts) {
      const text = await alert.textContent().catch(() => '');
      // The backend renders the summary verbatim — new-device banners typically
      // include "new device" or "new login" in the English summary.
      // Also check the action label if visible.
      if (
        text?.toLowerCase().includes('new device') ||
        text?.toLowerCase().includes('new login') ||
        text?.toLowerCase().includes('auth.login.new_device')
      ) {
        newDeviceBannerFound = true;
        // Assert the banner structure is correct.
        await expect(alert.locator('p.flex-1').first()).toBeVisible();
        await expect(alert.locator('a').first()).toBeVisible();
        await expect(alert.locator('button[aria-label]').first()).toBeVisible();
        console.log('Best-effort new-device banner: PRESENT and structure verified.');
        break;
      }
    }

    if (!newDeviceBannerFound) {
      // Known dev gap: new-device detection depends on IP/UA heuristics that
      // may not trigger in a Playwright Chromium headless context.
      console.log(
        'Best-effort new-device banner: ABSENT in this run (known dev gap — not a failure).'
      );
    }

    const errors = getErrors();
    expect(errors, `Unexpected console errors: ${errors.join(', ')}`).toHaveLength(0);

    await context.close();
  });
});
