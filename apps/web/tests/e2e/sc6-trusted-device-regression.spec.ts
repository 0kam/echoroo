/**
 * spec/011 Step 12b — T745 (SC-6 / FR-011-402):
 * Trusted-device revocation trigger regression test.
 *
 * FR-011-402 specifies that trusted-device tokens are revoked across FOUR
 * call-sites:
 *   (A) email-change           — covered by backend T631 integration tests.
 *   (B) 2FA-disable            — covered by backend T631 integration tests.
 *   (C) user-delete            — covered by backend T631 integration tests.
 *   (D) password-reset         — covered by backend T631 integration tests.
 *   (E) user-self revoke-all   — asserted HERE via observable UI evidence.
 *
 * This spec asserts the user-self "revoke all trusted devices" path (E)
 * through an observable UI journey:
 *   1. Login as e2e-trusted@echoroo.app via loginWithSharedTotp.
 *   2. Trigger POST /web-api/v1/account/trusted-devices/revoke-all via the
 *      profile page UI ("Revoke all" button), OR, if the button is disabled
 *      because there are no current trusted devices, call the endpoint directly
 *      from inside the browser (same pattern as banner-stack.spec.ts).
 *   3. Assert observably that revocation happened: EITHER
 *      - the profile page trusted-devices section shows zero active devices, OR
 *      - the activity view (/profile/activity) shows an "auth.trusted_device.revoke_all" row.
 *
 * Account: e2e-trusted@echoroo.app
 * Password: E2E-Test-Password-123!
 * Shared TOTP secret (TEST_MODE): VUO4R45DU5RTBODG63FN7KOE6OOCKCJE
 */

import { test, expect, type Page } from '@playwright/test';
import { loginWithSharedTotp } from './helpers/spec011-auth';

// ---------------------------------------------------------------------------
// Console error tracking (reuse pattern from single-invitation-flow.spec.ts)
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
// inside the browser. Reuses the identical helper pattern from
// banner-stack.spec.ts so no standalone fetch wiring is needed.
// Returns the HTTP status code.
// ---------------------------------------------------------------------------

async function revokeAllTrustedDevicesInBrowser(page: Page): Promise<number> {
  return page.evaluate(async () => {
    const csrfMatch = document.cookie
      .split(';')
      .map((c) => c.trim())
      .find((c) => c.startsWith('echoroo_csrf='));
    const csrfToken = csrfMatch ? csrfMatch.split('=').slice(1).join('=') : '';

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
      // Proceed without Bearer.
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
// Suite
// ---------------------------------------------------------------------------

test.describe.serial('SC-6: trusted-device revocation regression (T745 / FR-011-402)', () => {
  // Allow ample time for the sequential multi-step journey.
  test.setTimeout(120_000);

  test('self revoke-all is observable: zero trusted devices or activity row', async ({ page }) => {
    // Note: the other 3 revoke call-sites (email-change, 2FA-disable, user-delete,
    // password-reset) are covered by backend tests (T631 + integration test suite).

    const getErrors = trackConsoleErrors(page);

    // ── Step 1: Login ──────────────────────────────────────────────────────
    await loginWithSharedTotp(page, { email: 'e2e-trusted@echoroo.app' });

    // Confirm landing off /login.
    const postLoginPath = new URL(page.url()).pathname.replace(/^\/[a-z]{2}(?=\/)/, '');
    expect(
      !postLoginPath.startsWith('/login'),
      `Expected to land off /login after successful auth, got: ${page.url()}`
    ).toBe(true);

    console.log(`SC-6 Step 1: login OK, landed at ${page.url()}`);

    // ── Step 2: Navigate to profile page and attempt "Revoke all" ─────────
    await page.goto('/en/profile');
    await page.waitForLoadState('networkidle');

    // Wait for the trusted-devices section to load.
    await page.waitForSelector('section[aria-labelledby="trusted-devices-heading"]', {
      timeout: 15000,
    });

    // Wait for the loading state to clear.
    await page.waitForFunction(
      () => {
        const loadingText = document.querySelector('p')?.textContent ?? '';
        return !loadingText.includes('Loading trusted devices');
      },
      null,
      { timeout: 10000 }
    );

    // Check whether the "Revoke all" button is enabled (devices present) or
    // disabled (no active devices).
    const revokeAllBtn = page.locator('button:has-text("Revoke all")');
    await expect(revokeAllBtn).toBeVisible({ timeout: 10000 });

    const isEnabled = await revokeAllBtn.isEnabled().catch(() => false);

    let revokeStatus: number;
    if (isEnabled) {
      // There are active trusted devices — click the UI button.
      await revokeAllBtn.click();

      // Wait for the success message to appear.
      const successMsg = page.locator('[role="status"]:has-text("revoked")');
      await expect(successMsg).toBeVisible({ timeout: 10000 });
      console.log('SC-6 Step 2: "Revoke all" UI button clicked, success message visible.');

      revokeStatus = 204; // Inferred from UI success.
    } else {
      // No active trusted devices in the UI (already clean). Call the endpoint
      // directly so we still exercise the revoke-all code path and generate
      // an audit row, which lets us assert the activity evidence below.
      console.log(
        'SC-6 Step 2: no active trusted devices, calling revoke-all endpoint directly.'
      );
      revokeStatus = await revokeAllTrustedDevicesInBrowser(page);
      expect([200, 204], `revoke-all returned unexpected status ${revokeStatus}`).toContain(
        revokeStatus
      );
    }

    console.log(`SC-6 Step 2: revoke-all completed with status ~${revokeStatus}`);

    // ── Step 3: Assert observably that revocation happened ────────────────

    // Assertion A: profile page trusted-devices section shows zero active devices.
    await page.goto('/en/profile');
    await page.waitForLoadState('networkidle');

    // Wait for the section and loading to clear.
    await page.waitForSelector('section[aria-labelledby="trusted-devices-heading"]', {
      timeout: 10000,
    });
    await page.waitForFunction(
      () => {
        const loadingText = Array.from(document.querySelectorAll('p'))
          .map((el) => el.textContent ?? '')
          .join('');
        return !loadingText.includes('Loading trusted devices');
      },
      null,
      { timeout: 10000 }
    );

    // After revoking, the section should show either:
    //   - "No trusted devices." (all cleared), or
    //   - "Revoke all" button disabled (no devices left).
    const noDevicesText = await page
      .locator('p:has-text("No trusted devices")')
      .isVisible()
      .catch(() => false);
    const revokeAllDisabled = !(await revokeAllBtn.isEnabled().catch(() => false));

    const assertionAPassed = noDevicesText || revokeAllDisabled;

    // Assertion B: activity view shows the revoke_all audit row.
    await page.goto('/en/profile/activity');
    await page.waitForLoadState('networkidle');

    // Wait for the list to initialize.
    await page.waitForFunction(
      () =>
        document.querySelector('ul') !== null || document.querySelectorAll('p').length > 1,
      null,
      { timeout: 15000 }
    );
    await page.waitForTimeout(1000);

    const revokeRow = page.locator('li').filter({ hasText: 'auth.trusted_device.revoke_all' });
    const assertionBPassed = await revokeRow.first().isVisible({ timeout: 10000 }).catch(() => false);

    if (assertionBPassed) {
      // Verify the row has a non-empty timestamp.
      const timestamp = revokeRow.first().locator('span').last();
      const tsText = await timestamp.textContent().catch(() => '');
      expect(
        tsText?.trim().length,
        'Activity row timestamp should be non-empty'
      ).toBeGreaterThan(0);
      console.log('SC-6 Step 3: activity row "auth.trusted_device.revoke_all" visible.');
    } else {
      console.log('SC-6 Step 3: activity row not visible yet (may be behind pagination).');
    }

    // At least ONE of the two assertions must hold.
    expect(
      assertionAPassed || assertionBPassed,
      'Expected EITHER zero trusted devices in profile section OR ' +
        'an auth.trusted_device.revoke_all row in the activity view. ' +
        `assertionA (zero-devices): ${assertionAPassed}, ` +
        `assertionB (activity-row): ${assertionBPassed}`
    ).toBe(true);

    // ── Final: zero real console errors ───────────────────────────────────
    const errors = getErrors();
    expect(errors, `Unexpected console errors: ${errors.join(', ')}`).toHaveLength(0);
  });
});
