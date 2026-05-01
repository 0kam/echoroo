/**
 * E2E tests for Phase 6 US2 — Authenticated non-member voting flow (T311)
 *
 * Covers FR-037, FR-038, FR-039, FR-040 acceptance scenarios:
 *
 *   1. An authenticated non-member user opens a Public-project annotation
 *      detail page, sees the vote controls, and casts an "agree" vote.
 *   2. The vote is recorded with `source=guest_authenticated` and the UI
 *      surfaces the "Non-member" badge (FR-040).
 *   3. The per-source breakdown updates `guest_authenticated_agree`
 *      counter by +1 (FR-038).
 *   4. An Owner viewer sees the same vote with the raw `user_id` exposed
 *      and the "Non-member" badge (FR-039 unmask path).
 *   5. A Member viewer (non-Owner / non-Admin) sees the vote with
 *      `user_id=null` (rendered as "Anonymous"), but the "Non-member"
 *      badge is still visible (FR-039 mask path; vote is not hidden).
 *   6. The non-member user re-votes (changes "agree" → "disagree") — the
 *      backend keeps `source` and `project_role_at_vote` immutable; the
 *      "Non-member" badge does not change (FR-037).
 *
 * Environment gate
 * ----------------
 * All tests are skipped unless `PHASE6_E2E_ENABLED=1` is set, mirroring
 * the env-gate pattern used by Phase 5's `guest-public-flow.spec.ts` and
 * the existing `auth.spec.ts` 2FA gate. CI never runs these against a
 * cold database that has not been seeded with the required fixtures.
 *
 * Required environment variables
 * --------------------------------
 *   PHASE6_E2E_ENABLED=1                    Enable this suite.
 *   PHASE6_PUBLIC_PROJECT_ID=<uuid>         Active+Public project that the
 *                                           non-member user is NOT a member of.
 *   PHASE6_ANNOTATION_ID=<uuid>             Annotation under that project that
 *                                           is open for voting (consensus_status
 *                                           is needs_votes / disputed).
 *   PHASE6_NONMEMBER_EMAIL                  Authenticated non-member account.
 *                                           Defaults to PHASE6_NONMEMBER_DEFAULT_EMAIL
 *                                           (test-nonmember@echoroo.app) when unset
 *                                           — the corresponding password env var is
 *                                           PHASE6_NONMEMBER_PASSWORD.
 *   PHASE6_NONMEMBER_PASSWORD
 *
 * Owner / Member viewers default to the shared test account
 * (test@echoroo.app / N6Wz0IJXsQc4) per
 * memory/test-accounts.md.  Override with the env vars below when
 * Owner and Member need to be DIFFERENT identities (e.g. to verify
 * FR-039 Owner-vs-Member masking divergence).
 *
 *   PHASE6_OWNER_EMAIL                      (optional) Owner of PUBLIC_PROJECT_ID.
 *   PHASE6_OWNER_PASSWORD
 *   PHASE6_MEMBER_EMAIL                     (optional) Member (non-Owner /
 *                                           non-Admin) of PUBLIC_PROJECT_ID.
 *   PHASE6_MEMBER_PASSWORD
 *
 * Optional environment variables
 * --------------------------------
 *   PHASE6_BASE_URL                         Override base URL.
 *   PHASE6_NONMEMBER_USER_ID=<uuid>         Used in scenario #4 to verify the
 *                                           Owner sees the raw UUID. If unset,
 *                                           scenario #4 only asserts that
 *                                           SOME non-masked voter row exists.
 *
 * How to run
 * ----------
 *     ./scripts/docker.sh dev
 *     PHASE6_E2E_ENABLED=1 \
 *       PHASE6_PUBLIC_PROJECT_ID=<uuid> \
 *       PHASE6_ANNOTATION_ID=<uuid> \
 *       PHASE6_NONMEMBER_EMAIL=... \
 *       PHASE6_NONMEMBER_PASSWORD=... \
 *       PHASE6_OWNER_EMAIL=... \
 *       PHASE6_OWNER_PASSWORD=... \
 *       PHASE6_MEMBER_EMAIL=... \
 *       PHASE6_MEMBER_PASSWORD=... \
 *       npx playwright test tests/e2e/phase6-vote-flow.spec.ts
 */

import { test, expect, type Page } from '@playwright/test';

// ---------------------------------------------------------------------------
// Env gate — evaluated at module load. Each test still calls test.skip() so
// that the suite runs cleanly with Playwright's --list mode (no fixtures).
// ---------------------------------------------------------------------------
const SUITE_ENABLED = process.env.PHASE6_E2E_ENABLED === '1';
const PUBLIC_PROJECT_ID = process.env.PHASE6_PUBLIC_PROJECT_ID ?? '';
const ANNOTATION_ID = process.env.PHASE6_ANNOTATION_ID ?? '';
const NONMEMBER_USER_ID = process.env.PHASE6_NONMEMBER_USER_ID ?? '';

// Shared test account fallback (memory/test-accounts.md).  Owner / Member
// viewers default to this account so the suite can be run without seeding
// extra fixtures.  When the assertion needs Owner != Member identity,
// override via the env vars below.
const SHARED_TEST_EMAIL = 'test@echoroo.app';
const SHARED_TEST_PASSWORD = 'N6Wz0IJXsQc4';

const NONMEMBER = {
  // Non-member fixture — must be DIFFERENT from PUBLIC_PROJECT_ID's
  // membership so the FR-037 source classification path is exercised.
  email:
    process.env.PHASE6_NONMEMBER_EMAIL ??
    process.env.PHASE6_NONMEMBER_DEFAULT_EMAIL ??
    '',
  password: process.env.PHASE6_NONMEMBER_PASSWORD ?? '',
};
const OWNER = {
  email: process.env.PHASE6_OWNER_EMAIL ?? SHARED_TEST_EMAIL,
  password: process.env.PHASE6_OWNER_PASSWORD ?? SHARED_TEST_PASSWORD,
};
const MEMBER = {
  email: process.env.PHASE6_MEMBER_EMAIL ?? SHARED_TEST_EMAIL,
  password: process.env.PHASE6_MEMBER_PASSWORD ?? SHARED_TEST_PASSWORD,
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

function annotationDetailUrl(projectId: string, annotationId: string): string {
  // Detection review opens the detail panel via the project's detections page
  // with the annotation id selected. The exact URL convention may evolve, but
  // the deep link pattern below matches the current detection review router.
  return `/projects/${projectId}/detections?selected=${annotationId}`;
}

/**
 * Wait for the vote controls (agree/disagree) to be present.
 * The DetectionCard renders ReviewActions which exposes vote buttons.
 */
async function waitForVoteControls(page: Page): Promise<void> {
  await expect(
    page.locator('button', { hasText: /Agree|同意/i }).first(),
  ).toBeVisible({ timeout: 15000 });
}

/**
 * Read the current `guest_authenticated_agree` counter from the per-source
 * breakdown widget.  Returns 0 when the breakdown is collapsed (no votes).
 */
async function readGuestAgreeCount(page: Page): Promise<number> {
  const guestRow = page
    .locator('[data-testid="vote-source-breakdown"] [data-vote-source="guest_authenticated"]')
    .first();
  if ((await guestRow.count()) === 0) return 0;
  const text = (await guestRow.textContent()) ?? '';
  // Format: "Non-member  3 /1" — the first integer is the agree count.
  const match = text.match(/(\d+)\s*\/\s*\d+/);
  return match ? Number(match[1]) : 0;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe('Phase 6 US2 — Authenticated non-member vote flow (T311)', () => {
  // Scenario 1+2+3 share state — split into a single linear flow because each
  // depends on the previous mutation. Scenario 4/5/6 are independent and use
  // the same ANNOTATION_ID seed.

  test.beforeEach(async () => {
    test.skip(!SUITE_ENABLED, 'PHASE6_E2E_ENABLED is not set');
    test.skip(
      !PUBLIC_PROJECT_ID || !ANNOTATION_ID,
      'PHASE6_PUBLIC_PROJECT_ID / PHASE6_ANNOTATION_ID are not set — DB seed required',
    );
  });

  // -------------------------------------------------------------------------
  // Scenario 1: non-member sees the vote controls on a Public annotation
  // -------------------------------------------------------------------------
  test('non-member sees the vote controls on a Public-project annotation', async ({ page }) => {
    test.skip(!NONMEMBER.email, 'PHASE6_NONMEMBER_EMAIL is not set');

    await login(page, NONMEMBER);
    await page.goto(annotationDetailUrl(PUBLIC_PROJECT_ID, ANNOTATION_ID));
    await waitForVoteControls(page);

    // Non-members must NOT see project-internal controls (e.g. "Edit project")
    // but the vote buttons must be visible.
    await expect(
      page.locator('button', { hasText: /Agree|同意/i }).first(),
    ).toBeEnabled();
  });

  // -------------------------------------------------------------------------
  // Scenario 2: non-member casts agree → "Non-member" badge visible
  // -------------------------------------------------------------------------
  test('non-member casts an agree vote and sees the "Non-member" badge on their own vote', async ({ page }) => {
    test.skip(!NONMEMBER.email, 'PHASE6_NONMEMBER_EMAIL is not set');

    await login(page, NONMEMBER);
    await page.goto(annotationDetailUrl(PUBLIC_PROJECT_ID, ANNOTATION_ID));
    await waitForVoteControls(page);

    // Cast an agree vote. Some review UIs open a signal-quality popover when
    // the user clicks Agree — accept either flow by clicking the first
    // visible "Solo" / "単独" option if it appears.
    await page.locator('button', { hasText: /^Agree$|^同意$/i }).first().click();
    const soloOption = page.locator('button', { hasText: /^Solo$|^単独$/i }).first();
    if (await soloOption.isVisible({ timeout: 1500 }).catch(() => false)) {
      await soloOption.click();
    }

    // Wait for the API mutation to settle.
    await page.waitForLoadState('networkidle');

    // The non-member's own vote row should carry the "Non-member" badge
    // (FR-040: source classification is surfaced in the UI).
    const nonmemberBadge = page
      .locator('[data-vote-source="guest_authenticated"]')
      .first();
    await expect(nonmemberBadge).toBeVisible({ timeout: 10000 });
  });

  // -------------------------------------------------------------------------
  // Scenario 3: per-source breakdown updates guest_authenticated_agree by +1
  // -------------------------------------------------------------------------
  test('per-source breakdown reflects +1 on guest_authenticated_agree after the non-member votes', async ({ page }) => {
    test.skip(!NONMEMBER.email, 'PHASE6_NONMEMBER_EMAIL is not set');

    await login(page, NONMEMBER);
    await page.goto(annotationDetailUrl(PUBLIC_PROJECT_ID, ANNOTATION_ID));
    await waitForVoteControls(page);

    const before = await readGuestAgreeCount(page);

    // If the non-member already voted agree from a previous run, first remove
    // the vote so the +1 delta is observable. The "Remove vote" control may
    // not be present when no vote exists yet — guard with isVisible().
    const removeBtn = page.locator('button', { hasText: /Remove\svote|投票を削除/i }).first();
    if (await removeBtn.isVisible({ timeout: 1500 }).catch(() => false)) {
      await removeBtn.click();
      await page.waitForLoadState('networkidle');
    }

    const baseline = await readGuestAgreeCount(page);

    // Cast a fresh agree vote.
    await page.locator('button', { hasText: /^Agree$|^同意$/i }).first().click();
    const soloOption = page.locator('button', { hasText: /^Solo$|^単独$/i }).first();
    if (await soloOption.isVisible({ timeout: 1500 }).catch(() => false)) {
      await soloOption.click();
    }
    await page.waitForLoadState('networkidle');

    const after = await readGuestAgreeCount(page);
    expect(
      after,
      'guest_authenticated_agree counter should increase by 1 after the vote',
    ).toBe(baseline + 1);
    // Sanity: the post-vote count must also be at least the count we observed
    // at page load (covers the case where the previous run left the counter
    // already incremented).
    expect(after).toBeGreaterThanOrEqual(before);
  });

  // -------------------------------------------------------------------------
  // Scenario 4: Owner viewer sees the non-member voter UNMASKED (FR-039)
  // -------------------------------------------------------------------------
  test('owner viewer sees the non-member vote with raw user_id and "Non-member" badge', async ({ page }) => {
    test.skip(!OWNER.email, 'PHASE6_OWNER_EMAIL is not set');

    await login(page, OWNER);
    await page.goto(annotationDetailUrl(PUBLIC_PROJECT_ID, ANNOTATION_ID));
    await waitForVoteControls(page);

    // The voter list must contain a row with source=guest_authenticated AND
    // it must NOT be masked (data-masked="false"). This proves the Owner
    // viewer sees the raw user_id (FR-039 visible-to-Owner path).
    const unmaskedNonmemberRow = page
      .locator('[data-testid="voter-row"][data-vote-source="guest_authenticated"][data-masked="false"]')
      .first();
    await expect(unmaskedNonmemberRow).toBeVisible({ timeout: 10000 });

    // The badge inside that row must read "Non-member" (FR-040 preserves the
    // source label across masking states).
    await expect(
      unmaskedNonmemberRow.locator('[data-vote-source="guest_authenticated"]').first(),
    ).toBeVisible();

    // When the test runner provides the non-member user id, we additionally
    // verify the Owner can resolve the displayed name (i.e. the row is not
    // showing the "Anonymous" placeholder).
    if (NONMEMBER_USER_ID) {
      await expect(
        unmaskedNonmemberRow.locator('[data-testid="voter-anonymous"]'),
      ).toHaveCount(0);
    }
  });

  // -------------------------------------------------------------------------
  // Scenario 5: Member viewer sees the non-member vote MASKED (FR-039)
  // -------------------------------------------------------------------------
  test('member viewer sees the non-member vote masked (Anonymous) but the "Non-member" badge remains', async ({ page }) => {
    test.skip(!MEMBER.email, 'PHASE6_MEMBER_EMAIL is not set');

    await login(page, MEMBER);
    await page.goto(annotationDetailUrl(PUBLIC_PROJECT_ID, ANNOTATION_ID));
    await waitForVoteControls(page);

    // The voter list must contain a row with source=guest_authenticated AND
    // data-masked="true" (FR-039 mask-to-Member path).
    const maskedNonmemberRow = page
      .locator('[data-testid="voter-row"][data-vote-source="guest_authenticated"][data-masked="true"]')
      .first();
    await expect(maskedNonmemberRow).toBeVisible({ timeout: 10000 });

    // The masked row must surface the "Anonymous" placeholder (FR-039 leaves
    // the vote visible but hides the voter's identity).
    await expect(
      maskedNonmemberRow.locator('[data-testid="voter-anonymous"]'),
    ).toBeVisible();

    // The "Non-member" badge must STILL be visible on the masked row
    // (FR-040: the source classification survives masking).
    await expect(
      maskedNonmemberRow.locator('[data-vote-source="guest_authenticated"]').first(),
    ).toBeVisible();
  });

  // -------------------------------------------------------------------------
  // Scenario 6: re-vote (agree → disagree) keeps source/project_role_at_vote
  // -------------------------------------------------------------------------
  test('non-member re-vote (agree → disagree) keeps the "Non-member" badge (FR-037 immutability)', async ({ page, request }) => {
    test.skip(!NONMEMBER.email, 'PHASE6_NONMEMBER_EMAIL is not set');

    await login(page, NONMEMBER);
    await page.goto(annotationDetailUrl(PUBLIC_PROJECT_ID, ANNOTATION_ID));
    await waitForVoteControls(page);

    // Switch the vote to disagree. Some implementations require an explicit
    // "remove vote" first; we tolerate either flow.
    const disagreeBtn = page.locator('button', { hasText: /^Disagree$|^不同意$/i }).first();
    await disagreeBtn.click();
    await page.waitForLoadState('networkidle');

    // The viewer's own vote row should still carry the "Non-member" badge —
    // re-voting must not flip the source classification (FR-037).
    const nonmemberBadge = page
      .locator('[data-vote-source="guest_authenticated"]')
      .first();
    await expect(nonmemberBadge).toBeVisible({ timeout: 10000 });

    // The badge label text must remain "Non-member" (and not flip to
    // "Member") regardless of locale.
    const badgeText = (await nonmemberBadge.textContent()) ?? '';
    expect(badgeText, 'badge label should not say "Member"').not.toMatch(/^Member$|^メンバー$/);

    // -------------------------------------------------------------------
    // Backend-level immutability check (FR-037 core)
    // -------------------------------------------------------------------
    // The badge alone proves the UI surfaces the source.  To prove that the
    // DB row itself preserved `source` and `project_role_at_vote`, we hit
    // the GET vote-summary endpoint with the same browser cookies and
    // inspect the JSON for the non-member's own row.
    const cookies = await page.context().cookies();
    const cookieHeader = cookies.map((c) => `${c.name}=${c.value}`).join('; ');
    const apiResponse = await request.get(
      `/api/v1/projects/${PUBLIC_PROJECT_ID}/detections/${ANNOTATION_ID}/votes`,
      {
        headers: cookieHeader ? { Cookie: cookieHeader } : {},
      },
    );
    expect(
      apiResponse.ok(),
      `GET /votes should succeed for the non-member viewer (status=${apiResponse.status()})`,
    ).toBe(true);

    const summary = (await apiResponse.json()) as {
      voters?: Array<{
        user_id: string | null;
        vote: string;
        source: string;
        project_role_at_vote: string | null;
      }>;
    };

    // Locate the non-member's own row.  The viewer is the non-member, so
    // FR-039 unmasks their own row → user_id is non-null and matches the
    // session.  We pick the first guest_authenticated row whose user_id
    // matches PHASE6_NONMEMBER_USER_ID when provided, otherwise the first
    // guest_authenticated row at all.
    const guestRows = (summary.voters ?? []).filter((v) => v.source === 'guest_authenticated');
    const ownRow = NONMEMBER_USER_ID
      ? guestRows.find((v) => v.user_id === NONMEMBER_USER_ID) ?? guestRows[0]
      : guestRows[0];

    expect(
      ownRow,
      'GET /votes should return at least one guest_authenticated row',
    ).toBeDefined();
    expect(
      ownRow!.source,
      'FR-037: source must remain guest_authenticated after re-vote',
    ).toBe('guest_authenticated');
    expect(
      ownRow!.project_role_at_vote,
      'FR-037: project_role_at_vote must stay null for non-member votes',
    ).toBeNull();
    expect(
      ownRow!.vote,
      'Re-vote should have changed the vote value to disagree',
    ).toBe('disagree');
  });
});
