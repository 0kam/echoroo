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
 *      (I-6: if the activity row is not on the first page, page through Load-more before
 *      concluding absent.)
 *
 * Account: e2e-trusted@echoroo.app
 * Password: E2E-Test-Password-123!
 * Shared TOTP secret (TEST_MODE): VUO4R45DU5RTBODG63FN7KOE6OOCKCJE
 */

import { test, expect } from '@playwright/test';
import { loginWithSharedTotp } from './helpers/spec011-auth';
import {
  trackConsoleErrors,
  assertNoRealConsoleErrors,
  revokeAllTrustedDevicesInBrowser,
} from './helpers/spec011-infra';

// ---------------------------------------------------------------------------
// Suite
// ---------------------------------------------------------------------------

test.describe.serial('SC-6: trusted-device revocation regression (T745 / FR-011-402)', () => {
  test.setTimeout(120_000);

  test('self revoke-all is observable: zero trusted devices or activity row', async ({ page }) => {
    // Note: the other 3 revoke call-sites (email-change, 2FA-disable, user-delete,
    // password-reset) are covered by backend tests (T631 + integration test suite).

    const getErrors = trackConsoleErrors(page);

    // ── Step 1: Login ──────────────────────────────────────────────────────
    await loginWithSharedTotp(page, { email: 'e2e-trusted@echoroo.app' });

    const postLoginPath = new URL(page.url()).pathname.replace(/^\/[a-z]{2}(?=\/)/, '');
    expect(
      !postLoginPath.startsWith('/login'),
      `Expected to land off /login after successful auth, got: ${page.url()}`
    ).toBe(true);

    console.log(`SC-6 Step 1: login OK, landed at ${page.url()}`);

    // ── Step 2: Navigate to profile page and attempt "Revoke all" ─────────
    await page.goto('/en/profile');
    await page.waitForLoadState('networkidle');

    await page.waitForSelector('section[aria-labelledby="trusted-devices-heading"]', {
      timeout: 15000,
    });

    await page.waitForFunction(
      () => {
        const loadingText = document.querySelector('p')?.textContent ?? '';
        return !loadingText.includes('Loading trusted devices');
      },
      null,
      { timeout: 10000 }
    );

    // I-6: check whether the "Revoke all" button is present AND enabled.
    // Do not treat a missing button as "disabled" — distinguish the two cases.
    const revokeAllBtn = page.locator('button:has-text("Revoke all")');
    const revokeAllBtnVisible = await revokeAllBtn.isVisible().catch(() => false);

    let revokeStatus: number;
    if (revokeAllBtnVisible) {
      // Button is present — check if it is enabled (devices exist) or disabled.
      const isEnabled = await revokeAllBtn.isEnabled().catch(() => false);

      if (isEnabled) {
        await revokeAllBtn.click();
        const successMsg = page.locator('[role="status"]:has-text("revoked")');
        await expect(successMsg).toBeVisible({ timeout: 10000 });
        console.log('SC-6 Step 2: "Revoke all" UI button clicked, success message visible.');
        revokeStatus = 204;
      } else {
        // Button present but disabled — no active devices. Call directly.
        console.log(
          'SC-6 Step 2: "Revoke all" button is disabled (no active devices). ' +
            'Calling revoke-all endpoint directly.'
        );
        revokeStatus = await revokeAllTrustedDevicesInBrowser(page);
        expect([200, 204], `revoke-all returned unexpected status ${revokeStatus}`).toContain(
          revokeStatus
        );
      }
    } else {
      // Button not found at all — call the endpoint directly.
      console.log(
        'SC-6 Step 2: "Revoke all" button not found in profile section. ' +
          'Calling revoke-all endpoint directly to exercise code path.'
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

    const noDevicesText = await page
      .locator('p:has-text("No trusted devices")')
      .isVisible()
      .catch(() => false);

    // I-6: only assert "disabled" if the button is actually present.
    const revokeAllBtnAfter = page.locator('button:has-text("Revoke all")');
    const revokeAllBtnAfterVisible = await revokeAllBtnAfter.isVisible().catch(() => false);
    const revokeAllDisabled = revokeAllBtnAfterVisible
      ? !(await revokeAllBtnAfter.isEnabled().catch(() => true))
      : false; // button absent — don't claim it's disabled

    const assertionAPassed = noDevicesText || revokeAllDisabled;

    // Assertion B: activity view shows the revoke_all audit row.
    // I-6: page through Load-more if the row is not on the first page.
    await page.goto('/en/profile/activity');
    await page.waitForLoadState('networkidle');

    await page.waitForFunction(
      () =>
        document.querySelector('ul') !== null || document.querySelectorAll('p').length > 1,
      null,
      { timeout: 15000 }
    );
    await page.waitForTimeout(1000);

    let assertionBPassed = false;
    let pageCount = 0;
    const MAX_PAGES = 10; // Safety cap to avoid infinite Load-more loop.

    while (pageCount < MAX_PAGES) {
      pageCount++;

      const revokeRow = page.locator('li').filter({ hasText: 'auth.trusted_device.revoke_all' });
      const rowVisible = await revokeRow.first().isVisible().catch(() => false);

      if (rowVisible) {
        // Verify the row has a non-empty timestamp.
        const timestamp = revokeRow.first().locator('span').last();
        const tsText = await timestamp.textContent().catch(() => '');
        expect(
          tsText?.trim().length,
          'Activity row timestamp should be non-empty'
        ).toBeGreaterThan(0);
        console.log(
          `SC-6 Step 3: activity row "auth.trusted_device.revoke_all" visible (page ${pageCount}).`
        );
        assertionBPassed = true;
        break;
      }

      // Row not found on this page — try Load-more if available.
      const loadMoreBtn = page.locator('button', { hasText: /load more/i });
      const hasLoadMore = await loadMoreBtn.isVisible().catch(() => false);
      if (!hasLoadMore) {
        console.log(
          `SC-6 Step 3: activity row not found after ${pageCount} page(s), no Load-more button.`
        );
        break;
      }

      const rowsBefore = await page.locator('li').count();
      await loadMoreBtn.click();
      await page
        .waitForFunction(
          (before: number) => document.querySelectorAll('li').length > before,
          rowsBefore,
          { timeout: 10000 }
        )
        .catch(() => {
          // Load-more completed with no new rows — stop paging.
        });

      const rowsAfter = await page.locator('li').count();
      if (rowsAfter <= rowsBefore) {
        console.log(`SC-6 Step 3: Load-more yielded no new rows — stopping pagination.`);
        break;
      }

      console.log(
        `SC-6 Step 3: Load-more clicked (page ${pageCount}): ${rowsBefore}→${rowsAfter} rows.`
      );
    }

    // assertionB (activity row) is REQUIRED — the backend emits
    // "auth.trusted_device.revoke_all" even when revoked_count==0 (T630).
    // The activity row MUST appear to prove FR-011-402 is genuinely enforced.
    expect(
      assertionBPassed,
      `SC-6: auth.trusted_device.revoke_all row MUST appear in the activity view ` +
        `(FR-011-402). Row not found after ${pageCount} page(s). ` +
        `This proves the backend emitted the audit event even with zero active devices.`
    ).toBe(true);

    // assertionA (zero trusted devices in UI) is an ADDITIONAL check — not an alternative.
    // It validates the profile page state after revoke-all.
    expect(
      assertionAPassed,
      'SC-6: After revoke-all, the profile page must show zero active trusted devices ' +
        '(either "No trusted devices" text or a disabled "Revoke all" button). ' +
        `assertionA (zero-devices): ${assertionAPassed}`
    ).toBe(true);

    assertNoRealConsoleErrors(getErrors, 'SC-6: trusted-device revocation');
  });
});
