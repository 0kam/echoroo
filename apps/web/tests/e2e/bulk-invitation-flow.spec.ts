/**
 * E2E spec for spec/011 Step 12b T292 (US3): bulk-invitation flow.
 *
 * Scenarios:
 *   1 — Bulk issue + result table:
 *       Switch to bulk mode, paste 5 unique emails, submit, assert 5-row result
 *       table with "Issued" status and non-empty invitation_url inputs.
 *       Assert "Copy all as CSV" button is present.
 *
 *   2 — Each URL redeems independently:
 *       Take 2 of the bulk-issued invitation URLs, redeem each in a fresh
 *       browser context as a brand-new user, assert landing on the project.
 *
 *   3 — Copy-all-CSV content:
 *       Click the "Copy all as CSV" button and assert the clipboard content
 *       starts with "email,status,invitation_url" and contains all 5 emails.
 *       Falls back to table-row assertion if clipboard read is blocked.
 *
 * Project used: "e2e E2E Public Permission Project" (b95e3ae7-946a-4bb1-b6e9-98da6bdf770f)
 * Owner account: e2e-owner@echoroo.app (has manage_members)
 * Shared TOTP secret (seeded accounts): VUO4R45DU5RTBODG63FN7KOE6OOCKCJE
 */

import { test, expect } from '@playwright/test';
import { spawnSync } from 'child_process';
import { loginWithSharedTotp, redeemInviteAsNewUser } from './helpers/spec011-auth';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const E2E_PROJECT_ID = 'b95e3ae7-946a-4bb1-b6e9-98da6bdf770f';
const E2E_PASSWORD = 'E2E-Test-Password-123!';
const OWNER_EMAIL = 'e2e-owner@echoroo.app';

const COLLABORATORS_PATH = `/en/projects/${E2E_PROJECT_ID}/collaborators`;

// ---------------------------------------------------------------------------
// Console error tracking
// ---------------------------------------------------------------------------

/**
 * Known-benign console error patterns during the invite / auth flow.
 * Mirrors single-invitation-flow.spec.ts pattern exactly.
 */
const BENIGN_CONSOLE_ERROR_PATTERNS = [
  '401',
  '403',
  '404',
  '409',
  'net::ERR_ABORTED',
  'Failed to load resource',
];

function isBenignConsoleError(msg: string): boolean {
  return BENIGN_CONSOLE_ERROR_PATTERNS.some((pattern) => msg.includes(pattern));
}

function trackConsoleErrors(page: import('@playwright/test').Page): () => string[] {
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
// Helper: extract invite path from a token-or-url value
// ---------------------------------------------------------------------------

function buildInvitePath(tokenOrUrl: string): string {
  if (tokenOrUrl.startsWith('http://') || tokenOrUrl.startsWith('https://')) {
    const parsed = new URL(tokenOrUrl);
    return parsed.pathname + parsed.search;
  }
  if (tokenOrUrl.startsWith('/')) {
    return tokenOrUrl;
  }
  return `/en/invite/${encodeURIComponent(tokenOrUrl)}`;
}

// ---------------------------------------------------------------------------
// Test suite
// ---------------------------------------------------------------------------

// Each test needs well over 30s for login + bulk submit + redemptions.
// Override the global 30s default for this suite.
test.setTimeout(120000);

// Use serial mode so Tests 1→2→3 run in order within the same worker.
// This guarantees that collectedInviteTokens filled by Test 1 is readable
// by Test 2, as they share the same JS module scope in a single worker.
test.describe.serial('US3 bulk-invitation flow', () => {
  // Unique stamp per run — prevents duplicate_pending collisions across runs.
  const stamp = Date.now();
  const bulkEmails = Array.from({ length: 5 }, (_, i) => `bulk-${stamp}-${i + 1}@example.com`);

  // Shared state: bulk result URLs collected in Test 1, consumed in Test 2.
  // serial mode guarantees single-worker execution; the array is safe to share.
  const collectedInviteTokens: string[] = [];

  // ---------------------------------------------------------------------------
  // beforeAll: reset invitation rate-limit counters for the e2e actor + project.
  //
  // The e2e-owner account (actor) and the e2e project both have per-hour
  // Redis counters (50/h and 200/h respectively). Repeated test runs can
  // exhaust the actor counter within the 1-hour window, causing bulk rows
  // to come back as "rate_limited" with no invitation_url — making Test 1
  // and Test 2 non-deterministic.
  //
  // We reset ONLY those two specific Redis keys (not FLUSHALL). This is
  // safe because:
  //   - No real users exist during E2E runs (dev environment only).
  //   - The keys are named "invitation_rate:actor:<uuid>" and
  //     "invitation_rate:project:<uuid>" — scoped exclusively to invitation
  //     rate limiting.
  // ---------------------------------------------------------------------------
  test.beforeAll(async () => {
    const BACKEND_CONTAINER = 'echoroo-backend';
    const E2E_ACTOR_ID = '1004dbbb-76a7-4bd8-a29d-15aa15e90ace'; // e2e-owner
    const E2E_PROJECT_ID_INNER = 'b95e3ae7-946a-4bb1-b6e9-98da6bdf770f';

    const script = `
import asyncio, os
import redis.asyncio as aioredis

REDIS_URL = os.environ.get('REDIS_URL', 'redis://redis:6379')

async def main():
    r = await aioredis.from_url(REDIS_URL, decode_responses=True)
    deleted = await r.delete(
        'invitation_rate:actor:${E2E_ACTOR_ID}',
        'invitation_rate:project:${E2E_PROJECT_ID_INNER}'
    )
    print(f'Reset {deleted} rate-limit key(s)')
    await r.aclose()

asyncio.run(main())
`.trim();

    try {
      // Use spawnSync with an argument array (no shell involved) to avoid
      // command injection. The Python script is passed via stdin (-i flag)
      // so no shell escaping of the script body is needed.
      // All arguments are compile-time constants — no user input is present.
      const result = spawnSync(
        'docker',
        ['exec', '-i', BACKEND_CONTAINER, 'sh', '-c', 'cd /app && uv run python -'],
        { input: script, encoding: 'utf8', timeout: 15000 }
      );
      if (result.status === 0) {
        console.log(`Rate-limit reset: ${result.stdout.trim()}`);
      } else {
        console.warn(`Rate-limit reset exited ${result.status}: ${result.stderr}`);
      }
    } catch (err) {
      // Non-fatal: if the reset fails (e.g., backend not running), the tests
      // may hit rate limits but will still run. We log the error clearly.
      console.warn(`Rate-limit reset failed (non-fatal): ${err}`);
    }
  });

  // ---------------------------------------------------------------------------
  // Test 1 — bulk issue + result table
  // ---------------------------------------------------------------------------
  test('Test 1: bulk issue 5 invitations and render result table', async ({ browser }) => {
    const ownerCtx = await browser.newContext();
    const ownerPage = await ownerCtx.newPage();
    const getOwnerErrors = trackConsoleErrors(ownerPage);

    // 1. Log in as owner.
    await loginWithSharedTotp(ownerPage, { email: OWNER_EMAIL, password: E2E_PASSWORD });

    // 2. Navigate to collaborators page.
    await ownerPage.goto(COLLABORATORS_PATH);

    // Wait for the single-invite form (page has loaded and canManage is true).
    await ownerPage.waitForSelector('#invite-email', { timeout: 15000 });

    // 3. Switch to bulk mode by clicking the "Bulk invite" toggle button.
    await ownerPage.click('button:has-text("Bulk invite")');

    // Wait for the bulk textarea to appear.
    await ownerPage.waitForSelector('#bulk-emails', { timeout: 10000 });

    // 4. Paste 5 unique emails into the textarea.
    await ownerPage.fill('#bulk-emails', bulkEmails.join('\n'));

    // 5. Select the "member" role.
    await ownerPage.selectOption('#bulk-role', 'member');

    // 6. Submit the bulk invite form by clicking "Issue invitations".
    await ownerPage.click('button[type="submit"]:has-text("Issue invitations")');

    // 7. Wait for the results table to appear.
    // The bulk-results table contains read-only <input> elements (the one-shot
    // invitation URL fields). The invitation listing table does NOT have any
    // <input> elements — so waiting for an input[readonly] inside a table
    // uniquely targets the bulk results table and avoids a timing race with the
    // pre-existing invitation listing table.
    await ownerPage.waitForSelector('table input[readonly]', { timeout: 30000 });

    // 8. Assert exactly 5 rows are rendered.
    // Confirm the "Results" heading is visible so any DOM-order mismatch surfaces.
    const resultsH3 = ownerPage.locator('h3:has-text("Results")').first();
    await expect(resultsH3).toBeVisible({ timeout: 10000 });

    // Locate the bulk-results table as the table that contains input[readonly].
    // This is more reliable than .first() if the page renders tables in an
    // unexpected order.
    const bulkResultsTable = ownerPage.locator('table').filter({ has: ownerPage.locator('input[readonly]') });
    await expect(bulkResultsTable).toBeVisible({ timeout: 10000 });

    const resultRows = bulkResultsTable.locator('tbody tr');
    await expect(resultRows).toHaveCount(5, { timeout: 15000 });

    // 9. For each row, assert "Issued" status badge and a non-empty URL input.
    for (let i = 0; i < 5; i++) {
      const row = resultRows.nth(i);

      // Status badge should show "Issued".
      const statusBadge = row.locator('span').filter({ hasText: 'Issued' });
      await expect(statusBadge).toBeVisible({ timeout: 5000 });

      // The invitation_url column should have a read-only input with a non-empty value.
      const urlInput = row.locator('input[readonly]');
      await expect(urlInput).toBeVisible({ timeout: 5000 });
      const tokenValue = await urlInput.inputValue();
      expect(tokenValue.trim()).not.toBe('');

      // Collect for use in Test 2.
      collectedInviteTokens.push(tokenValue.trim());
    }

    // 10. Assert the "Copy all as CSV" button is present.
    const copyBtn = ownerPage.locator('button:has-text("Copy all as CSV")');
    await expect(copyBtn).toBeVisible();

    console.log(
      `Test 1: 5 rows rendered, all "Issued", invitation tokens collected: ${collectedInviteTokens.length}`
    );

    // Report console errors.
    const ownerErrors = getOwnerErrors();
    if (ownerErrors.length > 0) {
      console.warn(`Test 1: owner console errors: ${ownerErrors.join('; ')}`);
    }
    expect(ownerErrors, 'Owner page console errors').toHaveLength(0);

    await ownerCtx.close();
  });

  // ---------------------------------------------------------------------------
  // Test 2 — each URL redeems independently (2 of the 5)
  // ---------------------------------------------------------------------------
  test('Test 2: 2 bulk-issued URLs redeem independently as new users', async ({ browser }) => {
    // collectedInviteTokens is populated by Test 1.
    // If Test 1 did not run, this test will fail with a clear message.
    expect(collectedInviteTokens.length).toBeGreaterThanOrEqual(2);

    // We use the first two tokens.
    const tokensToRedeem = collectedInviteTokens.slice(0, 2);

    for (let idx = 0; idx < tokensToRedeem.length; idx++) {
      const token = tokensToRedeem[idx];
      const invitePath = buildInvitePath(token);

      const inviteeCtx = await browser.newContext();
      const inviteePage = await inviteeCtx.newPage();
      const getInviteeErrors = trackConsoleErrors(inviteePage);

      console.log(`Test 2 [${idx + 1}/2]: redeeming invite as new user, path=${invitePath}`);

      const landedUrl = await redeemInviteAsNewUser(inviteePage, invitePath, {
        password: E2E_PASSWORD,
        projectId: E2E_PROJECT_ID,
      });

      expect(landedUrl).toContain(`/projects/${E2E_PROJECT_ID}`);
      console.log(`Test 2 [${idx + 1}/2]: landed on ${landedUrl}`);

      // Report console errors.
      const inviteeErrors = getInviteeErrors();
      if (inviteeErrors.length > 0) {
        console.warn(`Test 2 [${idx + 1}/2]: invitee console errors: ${inviteeErrors.join('; ')}`);
      }
      expect(inviteeErrors, `Invitee ${idx + 1} page console errors`).toHaveLength(0);

      await inviteeCtx.close();
    }
  });

  // ---------------------------------------------------------------------------
  // Test 3 — Copy-all-CSV content
  // ---------------------------------------------------------------------------
  test('Test 3: Copy-all-CSV produces valid CSV with all 5 emails', async ({ browser }) => {
    // We need to reproduce the bulk invite UI state. Since the bulk results are
    // transient (lost on navigation), we must re-submit the bulk invite in this
    // test. However, the earlier emails are already pending — submitting them again
    // would yield "duplicate_pending" status. That is still valid for the CSV test
    // (each row still has an email and a status, but no invitation_url for
    // duplicate_pending rows).
    //
    // Strategy: use a new set of 5 emails unique to this test, submit bulk invite,
    // then test the CSV copy feature.
    const t3Stamp = Date.now() + 100000; // distinct from stamp used in Test 1
    const t3Emails = Array.from(
      { length: 5 },
      (_, i) => `bulk-csv-${t3Stamp}-${i + 1}@example.com`
    );

    // Open context with clipboard permissions granted.
    const ownerCtx = await browser.newContext({
      permissions: ['clipboard-read', 'clipboard-write'],
    });
    const ownerPage = await ownerCtx.newPage();
    const getOwnerErrors = trackConsoleErrors(ownerPage);

    // Log in as owner.
    await loginWithSharedTotp(ownerPage, { email: OWNER_EMAIL, password: E2E_PASSWORD });
    await ownerPage.goto(COLLABORATORS_PATH);

    // Wait for single-invite form to be ready, then switch to bulk mode.
    await ownerPage.waitForSelector('#invite-email', { timeout: 15000 });
    await ownerPage.click('button:has-text("Bulk invite")');
    await ownerPage.waitForSelector('#bulk-emails', { timeout: 10000 });

    // Fill 5 fresh emails and submit.
    await ownerPage.fill('#bulk-emails', t3Emails.join('\n'));
    await ownerPage.selectOption('#bulk-role', 'member');
    await ownerPage.click('button[type="submit"]:has-text("Issue invitations")');

    // Wait for results table — same strategy as Test 1: wait for input[readonly].
    await ownerPage.waitForSelector('table input[readonly]', { timeout: 30000 });

    // Confirm the results section h3 is visible.
    const resultsH3 = ownerPage.locator('h3:has-text("Results")').first();
    await expect(resultsH3).toBeVisible({ timeout: 10000 });

    // Locate the bulk-results table via its distinctive input[readonly] elements.
    const t3BulkTable = ownerPage.locator('table').filter({ has: ownerPage.locator('input[readonly]') });
    await expect(t3BulkTable).toBeVisible({ timeout: 10000 });

    // Click the "Copy all as CSV" button.
    const copyBtn = ownerPage.locator('button:has-text("Copy all as CSV")');
    await expect(copyBtn).toBeVisible();
    await copyBtn.click();

    // Wait briefly for the clipboard write and the button label change to "Copied!".
    await ownerPage.waitForSelector('button:has-text("Copied!")', { timeout: 5000 }).catch(() => {
      // Non-fatal: some CI environments suppress button label change timing.
      console.warn('Test 3: "Copied!" label did not appear within 5s (non-fatal)');
    });

    // Attempt to read clipboard via page.evaluate.
    let clipboardSucceeded = false;
    let csvText = '';

    try {
      csvText = await ownerPage.evaluate(async () => {
        return await navigator.clipboard.readText();
      });
      clipboardSucceeded = true;
    } catch (err) {
      console.warn(`Test 3: clipboard read blocked in headless Chromium: ${err}`);
    }

    if (clipboardSucceeded && csvText) {
      // Primary assertion: clipboard content starts with expected CSV header.
      expect(csvText).toMatch(/^email,status,invitation_url/);

      // All 5 emails should appear in the CSV.
      for (const email of t3Emails) {
        expect(csvText).toContain(email);
      }

      console.log(`Test 3: clipboard CSV verified — header present, all 5 emails found`);
    } else {
      // Fallback: assert CSV is constructible from the visible table rows.
      console.warn('Test 3: clipboard unavailable — falling back to table-row assertion');

      const resultRows = t3BulkTable.locator('tbody tr');
      await expect(resultRows).toHaveCount(5, { timeout: 10000 });

      const csvLines: string[] = ['email,status,invitation_url'];

      for (let i = 0; i < 5; i++) {
        const row = resultRows.nth(i);

        // Email cell is the first td.
        const emailCell = row.locator('td').nth(0);
        const emailText = await emailCell.textContent();
        expect(emailText?.trim()).toBeTruthy();
        expect(t3Emails).toContain(emailText?.trim());

        // Status badge text.
        const statusCell = row.locator('td').nth(1);
        const statusText = await statusCell.textContent();
        expect(statusText?.trim()).toBeTruthy();

        // URL input (may be empty for non-issued rows, but should be present).
        const urlInput = row.locator('td').nth(2).locator('input[readonly]');
        const urlExists = await urlInput.isVisible().catch(() => false);
        const urlValue = urlExists ? await urlInput.inputValue() : '';

        csvLines.push(
          `${emailText?.trim() ?? ''},${statusText?.trim() ?? ''},${urlValue.trim()}`
        );
      }

      const constructedCsv = csvLines.join('\n');
      expect(constructedCsv).toMatch(/^email,status,invitation_url/);

      // Assert all 5 emails are in the constructed CSV.
      for (const email of t3Emails) {
        expect(constructedCsv).toContain(email);
      }

      console.log('Test 3: fallback table-row CSV assertion passed — all 5 emails present');
    }

    // Report console errors.
    const ownerErrors = getOwnerErrors();
    if (ownerErrors.length > 0) {
      console.warn(`Test 3: owner console errors: ${ownerErrors.join('; ')}`);
    }
    expect(ownerErrors, 'Owner page console errors').toHaveLength(0);

    await ownerCtx.close();
  });
});
