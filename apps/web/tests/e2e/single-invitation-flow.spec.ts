/**
 * E2E spec for spec/011 Step 12b T245 (US2): single-collaborator invitation flow.
 *
 * Scenarios:
 *   A — new-user signup:  issue invite → open link in fresh context → signup with
 *       client-enrolled TOTP → land on project → admin verifies new member.
 *   B — existing-user accept: issue invite to e2e-nonmember → log in as them →
 *       accept via confirm branch → land on project → admin verifies new member.
 *   C — 409 already-member: issue invite to e2e-member (already in project) →
 *       open link as that logged-in user → backend 409 → UI surfaces the error.
 *
 * Project used: "e2e E2E Public Permission Project" (b95e3ae7-946a-4bb1-b6e9-98da6bdf770f)
 * Owner account: e2e-owner@echoroo.app (has manage_members)
 * Shared TOTP secret (seeded accounts): VUO4R45DU5RTBODG63FN7KOE6OOCKCJE
 */

import { test, expect } from '@playwright/test';
import { loginWithSharedTotp } from './helpers/spec011-auth';
import { generateTotpCode, waitForFreshTotpWindow } from './helpers/totp';
import {
  trackConsoleErrors,
  assertNoRealConsoleErrors,
} from './helpers/spec011-infra';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const E2E_PROJECT_ID = 'b95e3ae7-946a-4bb1-b6e9-98da6bdf770f';
const E2E_PASSWORD = 'E2E-Test-Password-123!';
const OWNER_EMAIL = 'e2e-owner@echoroo.app';
const NONMEMBER_EMAIL = 'e2e-nonmember@echoroo.app';
// User ID of e2e-nonmember (from seed_e2e_permissions.py DB output).
const NONMEMBER_USER_ID = '954955ac-d19c-4f0c-aaf5-0ff25f2b9b15';
const MEMBER_EMAIL = 'e2e-member@echoroo.app';

const COLLABORATORS_PATH = `/en/projects/${E2E_PROJECT_ID}/collaborators`;

/**
 * Revoke any pending invitation for an email (idempotent cleanup).
 * Clicks Revoke + confirms in the dialog. No-op if no pending row found.
 * The page must already be at the collaborators route.
 *
 * I-4 fix: re-read row count each iteration, iterate from last row to avoid
 * live-locator misclick/hang, and bound the loop to avoid infinite iteration.
 *
 * @param maxRevocations - Max number of pending rows to revoke. Defaults to 5
 *   to prevent runaway loops when many stale Pending rows exist (e.g., for
 *   e2e-member which accumulates Pending rows from repeated test runs).
 */
async function revokePendingIfExists(
  ownerPage: import('@playwright/test').Page,
  email: string,
  maxRevocations = 5
): Promise<void> {
  for (let iteration = 0; iteration < maxRevocations; iteration++) {
    // Re-read the count on each iteration so we handle list mutations correctly.
    const rows = ownerPage
      .locator('table tbody tr')
      .filter({ hasText: email })
      .filter({ hasText: 'Pending' });

    const count = await rows.count().catch(() => 0);
    if (count === 0) break; // No more pending rows.

    // Click Revoke on the LAST pending row (iterate from end to avoid index shifts).
    const revokeBtn = rows.nth(count - 1).locator('button:has-text("Revoke")');
    if (!(await revokeBtn.isVisible().catch(() => false))) {
      // Button gone between count and click — re-count on next iteration.
      continue;
    }

    await revokeBtn.click();

    // Confirm the revoke dialog.
    const confirmBtn = ownerPage.locator('[role="dialog"]').locator('button:has-text("Revoke")');
    await confirmBtn.waitFor({ state: 'visible', timeout: 5000 });
    await confirmBtn.click();

    // Wait for the dialog to close before continuing.
    await confirmBtn.waitFor({ state: 'hidden', timeout: 5000 }).catch(() => {});
  }
}

/**
 * Remove an existing project membership via the API (idempotent cleanup for re-runs).
 *
 * Calls DELETE /web-api/v1/projects/{projectId}/members/{userId} from inside
 * the browser so session cookies + CSRF are sent automatically.
 * No-op if the user is not a member (404) or if cleanup fails (non-fatal).
 */
async function removeMembershipIfExists(
  ownerPage: import('@playwright/test').Page,
  userId: string
): Promise<void> {
  try {
    const statusCode = await ownerPage.evaluate(
      async ([projectId, uid]) => {
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
          // Skip if refresh fails.
        }

        const headers: Record<string, string> = {
          'Content-Type': 'application/json',
        };
        if (accessToken) headers['Authorization'] = `Bearer ${accessToken}`;
        if (csrfToken) headers['X-CSRF-Token'] = csrfToken;

        const resp = await fetch(`/web-api/v1/projects/${projectId}/members/${uid}`, {
          method: 'DELETE',
          credentials: 'include',
          headers,
        });
        return resp.status;
      },
      [E2E_PROJECT_ID, userId] as [string, string]
    );

    if (statusCode === 204 || statusCode === 200) {
      console.log(`Cleanup: membership for user ${userId} removed`);
    } else if (statusCode === 404) {
      // Not a member — nothing to do.
    } else {
      console.warn(`Cleanup: DELETE /members/${userId} returned ${statusCode}`);
    }
  } catch (err) {
    console.warn(`Cleanup: removeMembershipIfExists failed (non-fatal): ${err}`);
  }
}

/**
 * Count how many Accepted rows exist for `email` in the collaborators table.
 * Used for C-3 run-specific assertion hardening.
 */
async function countAcceptedRows(
  ownerPage: import('@playwright/test').Page,
  email: string
): Promise<number> {
  return ownerPage
    .locator('table tbody tr')
    .filter({ hasText: email })
    .filter({ hasText: 'Accepted' })
    .count()
    .catch(() => 0);
}

/**
 * Issue a single invitation as owner and return the invitation path to navigate to.
 *
 * The backend returns `invitation_url` as a 4-part signed token envelope.
 * The public invite route is /en/invite/{token}.
 *
 * If there is already a pending invitation for the email (from a previous test run),
 * we revoke it first so re-issuance succeeds.
 *
 * The owner page must already be at the collaborators route.
 */
async function issueInvitation(
  ownerPage: import('@playwright/test').Page,
  email: string,
  role: 'viewer' | 'member' | 'admin' = 'member'
): Promise<string> {
  // Wait for the page to load.
  await ownerPage.waitForSelector('#invite-email', { timeout: 15000 });

  // Clean up any pre-existing pending invitation (prior test run residue).
  await revokePendingIfExists(ownerPage, email);

  await ownerPage.fill('#invite-email', email);
  await ownerPage.selectOption('#invite-role', role);

  await ownerPage.click('form button[type="submit"]:has-text("Issue invitation")');

  // Wait for the one-shot dialog to appear.
  await ownerPage.waitForSelector('[data-testid="invitation-url-dialog"]', { timeout: 15000 });

  const urlInput = ownerPage.locator('[data-testid="invitation-url-value"]');
  await expect(urlInput).toBeVisible();
  const tokenOrUrl = await urlInput.inputValue();
  expect(tokenOrUrl).toBeTruthy();

  // Close the dialog.
  await ownerPage.click('[data-testid="invitation-url-close-button"]');

  // M-2: do NOT log the full token — only log a prefix.
  console.log(`issueInvitation: token prefix: ${tokenOrUrl.substring(0, 8)}...`);

  if (tokenOrUrl.startsWith('http://') || tokenOrUrl.startsWith('https://')) {
    const parsed = new URL(tokenOrUrl);
    return parsed.pathname + parsed.search;
  }
  return `/en/invite/${encodeURIComponent(tokenOrUrl)}`;
}

// ---------------------------------------------------------------------------
// Test suite
// ---------------------------------------------------------------------------

test.describe('US2 single-collaborator invitation flow', () => {
  const stamp = Date.now();

  // ---------------------------------------------------------------------------
  // Scenario A — new-user signup
  // ---------------------------------------------------------------------------
  test('Scenario A: new-user signup via invite link', async ({ browser }) => {
    const ownerCtx = await browser.newContext();
    const ownerPage = await ownerCtx.newPage();
    const getOwnerErrors = trackConsoleErrors(ownerPage);

    // 1. Log in as owner and go to collaborators page.
    await loginWithSharedTotp(ownerPage, { email: OWNER_EMAIL, password: E2E_PASSWORD });
    await ownerPage.goto(COLLABORATORS_PATH);

    const newUserEmail = `newuser-${stamp}@example.com`;
    const invitePath = await issueInvitation(ownerPage, newUserEmail, 'member');

    // 2. Open invite URL in a fresh (logged-out) context.
    const inviteeCtx = await browser.newContext();
    const inviteePage = await inviteeCtx.newPage();
    const getInviteeErrors = trackConsoleErrors(inviteePage);

    await inviteePage.goto(invitePath);

    // Wait for the signup form to appear.
    await inviteePage.waitForSelector('[data-testid="invite-signup-form"]', { timeout: 20000 });

    // Assert read-only email is the invited email.
    const emailField = inviteePage.locator('[data-testid="invite-signup-email"]');
    await expect(emailField).toBeVisible();
    const boundEmail = await emailField.inputValue();
    expect(boundEmail).toBe(newUserEmail);

    // Fill password.
    await inviteePage.fill('[data-testid="invite-signup-password"]', E2E_PASSWORD);

    // Read the client-generated TOTP secret from the <code> element.
    const secretEl = inviteePage.locator('code[data-testid="invite-signup-secret"]');
    await expect(secretEl).toBeVisible({ timeout: 10000 });
    const rawSecret = await secretEl.textContent();
    expect(rawSecret).toBeTruthy();
    const scrapedSecret = rawSecret!.replace(/\s+/g, '');

    // Generate a fresh TOTP code from the scraped secret and fill it in.
    await waitForFreshTotpWindow();
    const totpCode = generateTotpCode(scrapedSecret);
    await inviteePage.fill('[data-testid="invite-signup-code"]', totpCode);

    // Submit the signup form.
    await inviteePage.click('[data-testid="invite-signup-submit"]');

    const successOrProject = await Promise.race([
      inviteePage
        .waitForSelector('[data-testid="invite-landing-continue"]', { timeout: 25000 })
        .then(() => 'continue-button'),
      inviteePage
        .waitForURL((url) => url.pathname.includes(`/projects/${E2E_PROJECT_ID}`), {
          timeout: 25000,
        })
        .then(() => 'project-url'),
    ]).catch(() => 'timeout');

    if (successOrProject === 'continue-button') {
      await inviteePage.click('[data-testid="invite-landing-continue"]');
      await inviteePage.waitForURL(
        (url) => url.pathname.includes(`/projects/${E2E_PROJECT_ID}`),
        { timeout: 15000 }
      );
    } else if (successOrProject === 'timeout') {
      const errorEl = inviteePage.locator('[data-testid="invite-signup-error"]');
      const errorVisible = await errorEl.isVisible().catch(() => false);
      if (errorVisible) {
        const errorText = await errorEl.textContent().catch(() => '<unreadable>');
        throw new Error(`Signup failed with error: ${errorText}`);
      }
      const landingError = inviteePage.locator('[data-testid="invite-landing-error"]');
      const landingVisible = await landingError.isVisible().catch(() => false);
      if (landingVisible) {
        const landingText = await landingError.textContent().catch(() => '<unreadable>');
        throw new Error(`Invite landing error: ${landingText}`);
      }
      throw new Error(`Signup did not proceed to project page or continue button within timeout`);
    }

    expect(inviteePage.url()).toContain(`/projects/${E2E_PROJECT_ID}`);
    console.log(`Scenario A: new user ${newUserEmail} landed on project page`);

    // 3. Admin verifies new member appears in the collaborators listing (Accepted status).
    await ownerPage.goto(COLLABORATORS_PATH);
    await ownerPage.waitForSelector('table, [class*="text-stone-500"]', { timeout: 15000 });

    const memberRow = ownerPage
      .locator('table tbody tr')
      .filter({ hasText: newUserEmail })
      .filter({ hasText: 'Accepted' })
      .first();
    await expect(memberRow).toBeVisible({ timeout: 10000 });
    console.log(`Scenario A: admin verified ${newUserEmail} in collaborators listing`);

    assertNoRealConsoleErrors(getInviteeErrors, 'Scenario A: invitee page');
    assertNoRealConsoleErrors(getOwnerErrors, 'Scenario A: owner page');

    await inviteeCtx.close();
    await ownerCtx.close();
  });

  // ---------------------------------------------------------------------------
  // Scenario B — existing-user accept
  //
  // C-3 fix: before issuing, capture the count of Accepted rows for
  // NONMEMBER_EMAIL; after accept, assert the count INCREASED by 1 so we
  // never pass on a stale row from a prior run.
  // ---------------------------------------------------------------------------
  test('Scenario B: existing-user accept via invite link', async ({ browser }) => {
    const ownerCtx = await browser.newContext();
    const ownerPage = await ownerCtx.newPage();
    const getOwnerErrors = trackConsoleErrors(ownerPage);

    // 1. Log in as owner and go to collaborators page.
    await loginWithSharedTotp(ownerPage, { email: OWNER_EMAIL, password: E2E_PASSWORD });
    await ownerPage.goto(COLLABORATORS_PATH);

    // Pre-run idempotency: remove any existing membership so the accept flow
    // starts from a clean state.
    await removeMembershipIfExists(ownerPage, NONMEMBER_USER_ID);

    // Navigate fresh to the collaborators page to ensure the table reflects
    // the post-cleanup state (avoids stale DOM from the removeMembership evaluate call).
    await ownerPage.goto(COLLABORATORS_PATH);
    await ownerPage.waitForLoadState('networkidle');
    await ownerPage.waitForSelector('table, [class*="text-stone-500"]', { timeout: 15000 });

    // C-3: capture the baseline count of Accepted rows BEFORE issuing this run's invite.
    // Also revoke any pending rows now so the baseline is stable.
    await revokePendingIfExists(ownerPage, NONMEMBER_EMAIL);
    // Reload once more after revoke to get a stable baseline — networkidle ensures
    // TanStack Query has settled and the table is fully populated.
    await ownerPage.goto(COLLABORATORS_PATH);
    await ownerPage.waitForLoadState('networkidle');
    await ownerPage.waitForSelector('table, [class*="text-stone-500"]', { timeout: 15000 });
    // Wait for any lazy-loaded rows to appear.
    await ownerPage.waitForTimeout(1000);

    const acceptedCountBefore = await countAcceptedRows(ownerPage, NONMEMBER_EMAIL);
    console.log(
      `Scenario B: accepted rows for ${NONMEMBER_EMAIL} before invite: ${acceptedCountBefore}`
    );

    const invitePath = await issueInvitation(ownerPage, NONMEMBER_EMAIL, 'member');

    // 2. Fresh context: log in as e2e-nonmember, then open the invite URL.
    const inviteeCtx = await browser.newContext();
    const inviteePage = await inviteeCtx.newPage();
    const getInviteeErrors = trackConsoleErrors(inviteePage);

    await loginWithSharedTotp(inviteePage, { email: NONMEMBER_EMAIL, password: E2E_PASSWORD });

    await inviteePage.goto(invitePath);

    // Existing-user branch: confirm form should appear (not signup).
    await inviteePage.waitForSelector('[data-testid="invite-confirm-submit"]', { timeout: 20000 });
    await expect(inviteePage.locator('[data-testid="invite-signup-form"]')).not.toBeVisible();

    // Ensure no email-mismatch warning.
    const mismatch = inviteePage.locator('[data-testid="invite-confirm-mismatch"]');
    expect(await mismatch.isVisible().catch(() => false)).toBe(false);

    // Accept the invitation.
    await inviteePage.click('[data-testid="invite-confirm-submit"]');

    const outcome = await Promise.race([
      inviteePage
        .waitForSelector('[data-testid="invite-landing-continue"]', { timeout: 20000 })
        .then(() => 'continue-button'),
      inviteePage
        .waitForURL((url) => url.pathname.includes(`/projects/${E2E_PROJECT_ID}`), {
          timeout: 20000,
        })
        .then(() => 'project-url'),
    ]).catch(() => 'timeout');

    if (outcome === 'continue-button') {
      await inviteePage.click('[data-testid="invite-landing-continue"]');
      await inviteePage.waitForURL(
        (url) => url.pathname.includes(`/projects/${E2E_PROJECT_ID}`),
        { timeout: 15000 }
      );
    } else if (outcome === 'timeout') {
      const errorEl = inviteePage.locator('[data-testid="invite-landing-error"]');
      const errorVisible = await errorEl.isVisible().catch(() => false);
      if (errorVisible) {
        const errorText = await errorEl.textContent().catch(() => '<unreadable>');
        throw new Error(`Accept failed with error: ${errorText}`);
      }
      throw new Error(`Accept did not proceed to project page within timeout`);
    }

    expect(inviteePage.url()).toContain(`/projects/${E2E_PROJECT_ID}`);
    console.log(`Scenario B: ${NONMEMBER_EMAIL} landed on project page`);

    // 3. Admin verifies nonmember now appears as member.
    // C-3: reload page and assert count INCREASED by exactly 1 relative to the
    // baseline captured above — never passes on a stale row from a prior run.
    await ownerPage.goto(COLLABORATORS_PATH);
    await ownerPage.waitForLoadState('networkidle');
    await ownerPage.waitForSelector('table, [class*="text-stone-500"]', { timeout: 15000 });
    await ownerPage.waitForTimeout(1000);

    const acceptedCountAfter = await countAcceptedRows(ownerPage, NONMEMBER_EMAIL);
    console.log(
      `Scenario B: accepted rows for ${NONMEMBER_EMAIL} after accept: ${acceptedCountAfter}`
    );
    expect(
      acceptedCountAfter,
      `Scenario B: accepted row count for ${NONMEMBER_EMAIL} must have increased by 1 ` +
        `(was ${acceptedCountBefore}, now ${acceptedCountAfter})`
    ).toBe(acceptedCountBefore + 1);

    console.log(`Scenario B: admin verified ${NONMEMBER_EMAIL} in collaborators listing`);

    // 4. Cleanup: remove nonmember's membership so re-runs start from a clean state.
    await removeMembershipIfExists(ownerPage, NONMEMBER_USER_ID);

    assertNoRealConsoleErrors(getInviteeErrors, 'Scenario B: invitee page');
    assertNoRealConsoleErrors(getOwnerErrors, 'Scenario B: owner page');

    await inviteeCtx.close();
    await ownerCtx.close();
  });

  // ---------------------------------------------------------------------------
  // Scenario C — 409 already-member
  // ---------------------------------------------------------------------------
  test('Scenario C: already-member invite yields error on accept', async ({ browser }) => {
    const ownerCtx = await browser.newContext();
    const ownerPage = await ownerCtx.newPage();

    // 1. Issue an invitation to e2e-member (already in the project at member role).
    await loginWithSharedTotp(ownerPage, { email: OWNER_EMAIL, password: E2E_PASSWORD });
    await ownerPage.goto(COLLABORATORS_PATH);

    const invitePath = await issueInvitation(ownerPage, MEMBER_EMAIL, 'member');

    // 2. Log in as e2e-member and attempt to accept.
    const memberCtx = await browser.newContext();
    const memberPage = await memberCtx.newPage();
    const getMemberErrors = trackConsoleErrors(memberPage);

    await loginWithSharedTotp(memberPage, { email: MEMBER_EMAIL, password: E2E_PASSWORD });

    await memberPage.goto(invitePath);

    // The confirm form will appear (existing user).
    await memberPage.waitForSelector('[data-testid="invite-confirm-submit"]', { timeout: 20000 });
    await memberPage.click('[data-testid="invite-confirm-submit"]');

    // Wait for error state (409 already-member).
    await memberPage.waitForSelector('[data-testid="invite-landing-error"]', { timeout: 20000 });
    const errorEl = memberPage.locator('[data-testid="invite-landing-error"]');
    await expect(errorEl).toBeVisible();

    const errorKey = await errorEl.getAttribute('data-error-key');
    expect(errorKey).toBe('invite_landing_already_member');

    const errorText = await errorEl.textContent();
    console.log(`Scenario C: 409 rendered as "${errorText?.trim()}"`);
    expect(errorText?.trim()).toBeTruthy();

    // Assert NO success panel appeared and no project navigation happened.
    expect(await memberPage.locator('[data-testid="invite-landing-success"]').isVisible()).toBe(
      false
    );
    expect(memberPage.url()).not.toContain(`/projects/${E2E_PROJECT_ID}`);

    assertNoRealConsoleErrors(getMemberErrors, 'Scenario C: member page');

    await memberCtx.close();
    await ownerCtx.close();
  });
});
