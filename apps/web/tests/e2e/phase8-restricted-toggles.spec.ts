/**
 * E2E tests for Phase 8 US3 — Restricted owner toggles (T404).
 *
 * Covers spec.md acceptance scenarios L488-499 (PR-003 / SC-003) and
 * the eight key transitions required by FR-014, FR-020-022:
 *
 *   1. The Restricted-toggles section is visible on a Restricted project.
 *   2. `allow_voting_and_comments=OFF` → an Authenticated non-member is
 *      blocked (403) when attempting to vote on a detection.
 *   3. `allow_detection_view=OFF` → non-members do not see detection
 *      rows in the cross-project search / detection list.
 *   4. `public_location_precision_h3_res=5` → non-member map view
 *      surfaces an H3 hex at resolution 5 (~30 km).
 *   5. `mask_species_in_detection=true` → species names render as
 *      "(masked)" for non-members.
 *   6. `allow_precise_location_to_viewer=true` (Restricted only) →
 *      Viewer sees member-grade coordinates on the map.
 *   7. Public projects do NOT show the section — instead the
 *      "public-only" notice is rendered.
 *   8. Members / Viewers see the toggles in read-only mode (the Save
 *      button is absent and inputs are disabled).
 *
 * Environment gate
 * ----------------
 * All tests in this file are skipped unless `PHASE8_E2E_ENABLED=1` is
 * set, mirroring the env-gate pattern used by Phase 5's
 * `guest-public-flow.spec.ts`, Phase 6's `phase6-vote-flow.spec.ts`,
 * and Phase 7's `phase7-license-required.spec.ts`. CI never runs
 * these against a cold database.
 *
 * Required environment variables
 * --------------------------------
 *   PHASE8_E2E_ENABLED=1                Enable this suite.
 *   PHASE8_RESTRICTED_PROJECT_ID=<uuid> Restricted-visibility project
 *                                       owned by the OWNER credentials below.
 *   PHASE8_PUBLIC_PROJECT_ID=<uuid>     Public-visibility project owned
 *                                       by the OWNER (used for scenario 7).
 *
 * Optional environment variables
 * --------------------------------
 *   PHASE8_DETECTION_ID=<uuid>          Detection under the Restricted
 *                                       project (used for scenarios 2/3/5).
 *   PHASE8_OWNER_EMAIL                  Owner credentials (defaults to
 *                                       memory/test-accounts.md).
 *   PHASE8_OWNER_PASSWORD
 *   PHASE8_NONMEMBER_EMAIL              Authenticated non-member used by
 *                                       scenarios 2-5. When unset, those
 *                                       scenarios are skipped.
 *   PHASE8_NONMEMBER_PASSWORD
 *   PHASE8_MEMBER_EMAIL                 Member of the restricted project
 *                                       (Member role, NOT admin/owner) —
 *                                       used by scenario 8.
 *   PHASE8_MEMBER_PASSWORD
 *   PHASE8_VIEWER_EMAIL                 Viewer of the restricted project,
 *                                       used by scenario 6.
 *   PHASE8_VIEWER_PASSWORD
 *   PHASE8_TOTP_SECRET                  Shared TOTP secret used to derive
 *                                       2FA challenge codes when an account-
 *                                       specific secret is not provided.
 *   PHASE8_OWNER_TOTP_SECRET            Per-account TOTP secrets that
 *   PHASE8_NONMEMBER_TOTP_SECRET        override ``PHASE8_TOTP_SECRET``. If
 *   PHASE8_MEMBER_TOTP_SECRET           the relevant account is gated by
 *   PHASE8_VIEWER_TOTP_SECRET           2FA and no secret is available, the
 *                                       affected scenario is skipped with a
 *                                       diagnostic message (Phase 4 enforces
 *                                       2FA for all accounts).
 *
 * How to run
 * ----------
 *     ./scripts/docker.sh dev
 *     PHASE8_E2E_ENABLED=1 \
 *       PHASE8_RESTRICTED_PROJECT_ID=<uuid> \
 *       PHASE8_PUBLIC_PROJECT_ID=<uuid> \
 *       npx playwright test tests/e2e/phase8-restricted-toggles.spec.ts
 *
 * Notes
 * -----
 * - The toggle section is mounted on the project detail page, so the
 *   first scenarios only require the Owner login to assert visibility
 *   and edit-mode controls. Scenarios that probe the resulting
 *   non-member behaviour additionally need PHASE8_NONMEMBER_*.
 * - Mix of UI-driven and API-driven scenarios for FR-024 verification:
 *   the Owner-side toggle changes are exercised through the rendered
 *   form (so we cover the binding + dirty + Save lifecycle), while
 *   the resulting non-member behaviour is asserted via
 *   `page.request` against the public API. Using `request.fetch()`
 *   here keeps the scenarios independent of frontend route shapes
 *   that may not yet be wired for non-member browse.
 * - The non-member API probes target `/api/v1/...` endpoints, which
 *   are gated by ``CurrentUser`` (Bearer-only — see
 *   ``apps/api/echoroo/middleware/auth.py``). UI login only plants the
 *   ``refresh_token`` HttpOnly cookie, so we must obtain a fresh access
 *   token via ``POST /web-api/v1/auth/refresh`` (cookie principal) and
 *   then inject it as ``Authorization: Bearer ...`` on the subsequent
 *   calls. ``getBearerTokenAfterLogin`` encapsulates that handshake.
 *   The ``echoroo_refresh`` cookie is set with
 *   ``Path=/web-api/v1/auth/refresh`` (see
 *   ``apps/api/echoroo/api/web_v1/auth.py:_set_session_cookies``), so
 *   the refresh request MUST target the ``/web-api/v1`` path — the
 *   legacy ``/api/v1/auth/refresh`` path receives no cookie and 401s.
 *   The ``/web-api/v1`` surface only exposes auth / projects / audit,
 *   so ``/api/v1/projects/{id}/sites``, ``/api/v1/h3/validate``,
 *   ``/api/v1/projects/{id}/detections[/{id}]`` and
 *   ``/api/v1/projects/{id}/overview`` are reachable only via Bearer.
 *
 * - 2FA is mandatory for all accounts since Phase 4
 *   (``apps/api/echoroo/api/web_v1/auth.py``), so ``login()`` detects
 *   the TOTP challenge step. To complete it the suite needs a TOTP
 *   secret per account via ``PHASE8_*_TOTP_SECRET`` env vars (or a
 *   shared ``PHASE8_TOTP_SECRET``). When the secret is unavailable the
 *   per-test ``login()`` call invokes ``test.skip`` with a clear
 *   diagnostic, mirroring the deferral pattern used by the other env-
 *   gated phase suites. End-to-end 2FA bypass for tests is tracked as
 *   a separate test-infrastructure follow-up (see ``tasks.md`` notes
 *   under "Phase 8 Round 5").
 */

import { test, expect, type Page } from '@playwright/test';
import { generateTotpCode, waitForFreshTotpWindow } from './helpers/totp';

// ---------------------------------------------------------------------------
// Env gate
// ---------------------------------------------------------------------------
const SUITE_ENABLED = process.env.PHASE8_E2E_ENABLED === '1';
const RESTRICTED_PROJECT_ID = process.env.PHASE8_RESTRICTED_PROJECT_ID ?? '';
const PUBLIC_PROJECT_ID = process.env.PHASE8_PUBLIC_PROJECT_ID ?? '';
const DETECTION_ID = process.env.PHASE8_DETECTION_ID ?? '';

const SHARED_TEST_EMAIL = 'test@echoroo.app';
const SHARED_TEST_PASSWORD = 'N6Wz0IJXsQc4';

/**
 * Shared TOTP secret. Used as a fallback when a per-account secret is
 * unavailable. Empty string means "no shared secret".
 */
const SHARED_TOTP_SECRET = process.env.PHASE8_TOTP_SECRET ?? '';

interface TestCreds {
  email: string;
  password: string;
  totpSecret: string;
}

const OWNER: TestCreds = {
  email: process.env.PHASE8_OWNER_EMAIL ?? SHARED_TEST_EMAIL,
  password: process.env.PHASE8_OWNER_PASSWORD ?? SHARED_TEST_PASSWORD,
  totpSecret: process.env.PHASE8_OWNER_TOTP_SECRET ?? SHARED_TOTP_SECRET,
};
const NONMEMBER: TestCreds = {
  email: process.env.PHASE8_NONMEMBER_EMAIL ?? '',
  password: process.env.PHASE8_NONMEMBER_PASSWORD ?? '',
  totpSecret: process.env.PHASE8_NONMEMBER_TOTP_SECRET ?? SHARED_TOTP_SECRET,
};
const MEMBER: TestCreds = {
  email: process.env.PHASE8_MEMBER_EMAIL ?? '',
  password: process.env.PHASE8_MEMBER_PASSWORD ?? '',
  totpSecret: process.env.PHASE8_MEMBER_TOTP_SECRET ?? SHARED_TOTP_SECRET,
};
const VIEWER: TestCreds = {
  email: process.env.PHASE8_VIEWER_EMAIL ?? '',
  password: process.env.PHASE8_VIEWER_PASSWORD ?? '',
  totpSecret: process.env.PHASE8_VIEWER_TOTP_SECRET ?? SHARED_TOTP_SECRET,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isOffLoginPath(pathname: string): boolean {
  return !pathname.replace(/^\/[a-z]{2}(?=\/)/, '').startsWith('/login');
}

async function waitForLoginDecision(page: Page): Promise<'off-login' | 'two-factor' | 'error'> {
  await page.waitForFunction(() => {
    const normalizedPath = window.location.pathname.replace(/^\/[a-z]{2}(?=\/)/, '');
    return (
      !normalizedPath.startsWith('/login') ||
      document.querySelector('[data-testid="two-factor-form"]') !== null ||
      document.querySelector('[role="alert"]') !== null
    );
  }, null, { timeout: 15000 });

  if (isOffLoginPath(new URL(page.url()).pathname)) {
    return 'off-login';
  }
  if (await page.locator('[data-testid="two-factor-form"]').isVisible().catch(() => false)) {
    return 'two-factor';
  }
  return 'error';
}

async function loginErrorText(page: Page): Promise<string> {
  const text = await page.locator('[role="alert"]').first().textContent().catch(() => null);
  return text?.trim() ?? '<no visible error text>';
}

/**
 * Sign in via the UI, transparently completing the 2FA TOTP challenge
 * if the backend asks for one.
 *
 * Phase 4 makes 2FA mandatory for every account (see
 * ``apps/api/echoroo/api/web_v1/auth.py`` and ``memory/`` Phase 4
 * notes), so a successful login almost always passes through the
 * ``two-factor-form`` step before the dashboard URL is reached. To
 * complete that step the helper needs ``creds.totpSecret``; if the
 * TOTP form appears and no secret is configured, the calling test is
 * skipped with a diagnostic — this matches the deferral pattern used
 * by Phase 5/6/7 specs and keeps Phase 8 component / API GO unblocked
 * by E2E test-infrastructure work.
 *
 * The helper waits until the URL leaves ``/login`` (or any localised
 * variant such as ``/en/login``) before returning, so callers can
 * follow up with ``page.goto`` immediately.
 */
async function login(page: Page, creds: TestCreds): Promise<void> {
  await page.goto('/login');
  await page.fill('input[name="email"]', creds.email);
  await page.fill('input[name="password"]', creds.password);
  await page.click('button[type="submit"]');

  const firstDecision = await waitForLoginDecision(page);
  if (firstDecision === 'off-login') {
    return;
  }
  if (firstDecision === 'error') {
    throw new Error(`Login failed for ${creds.email}: ${await loginErrorText(page)}`);
  }

  if (!creds.totpSecret) {
    test.skip(
      true,
      `2FA challenge appeared for ${creds.email} but no TOTP secret was provided ` +
        `(set PHASE8_*_TOTP_SECRET or PHASE8_TOTP_SECRET). 2FA automation for E2E ` +
        `is tracked as a follow-up; Phase 4 enforces 2FA for all accounts.`,
    );
    return;
  }

  await waitForFreshTotpWindow();
  const code = generateTotpCode(creds.totpSecret);
  await page.fill('[data-testid="two-factor-code-input"]', code);
  await page.click('[data-testid="two-factor-submit"]');

  const secondDecision = await waitForLoginDecision(page);
  if (secondDecision !== 'off-login') {
    throw new Error(`2FA login failed for ${creds.email}: ${await loginErrorText(page)}`);
  }
}

/**
 * Obtain a Bearer access token after a UI login.
 *
 * Why this is needed
 * ------------------
 * The ``/api/v1/...`` surface is gated by FastAPI's ``CurrentUser``
 * dependency, which only accepts ``Authorization: Bearer ...`` headers
 * (see ``apps/api/echoroo/middleware/auth.py``). The cookie-principal
 * ``AuthRouter`` is **explicitly disabled** for ``/api/v1/*`` in
 * ``apps/api/echoroo/main.py``. UI login (``/login`` page) only plants
 * an HttpOnly ``refresh_token`` cookie and a session — the access token
 * is held in the SPA's in-memory ``apiClient`` singleton, which
 * Playwright's ``page.request.*`` does not share.
 *
 * Cookie path scoping
 * -------------------
 * The ``echoroo_refresh`` cookie is set with
 * ``Path=/web-api/v1/auth/refresh`` (see
 * ``apps/api/echoroo/api/web_v1/auth.py:_set_session_cookies`` ~ L722
 * and ``apps/api/echoroo/core/settings.py:web_refresh_cookie_*``). The
 * legacy ``/api/v1/auth/refresh`` path therefore receives no cookie
 * and 401s — we MUST hit ``/web-api/v1/auth/refresh`` to swap the
 * cookie for an access token.
 *
 * Strategy
 * --------
 * After UI login, the browser context owns a valid ``refresh_token``
 * cookie scoped to ``/web-api/v1/auth/refresh``. Calling
 * ``POST /web-api/v1/auth/refresh`` (which reads the cookie — see
 * ``apps/api/echoroo/api/web_v1/auth.py`` ``refresh``) returns
 * ``{access_token, expires_in}``. We then attach the token as
 * ``Authorization: Bearer ...`` on the subsequent ``/api/v1/...``
 * probes the test needs to make.
 *
 * Returns the token string. Throws if the refresh failed (which would
 * indicate the test seed is broken — surfacing it as a failure is the
 * desired behaviour).
 */
async function getBearerTokenAfterLogin(page: Page): Promise<string> {
  const response = await page.request.post('/web-api/v1/auth/refresh', {
    failOnStatusCode: false,
  });
  if (response.status() !== 200) {
    const body = await response.text().catch(() => '<no body>');
    throw new Error(
      `web-api/v1/auth/refresh returned ${response.status()} after UI login (expected 200). ` +
        `Cookie principal may not have been planted. Body: ${body}`,
    );
  }
  const data = (await response.json()) as { access_token?: string };
  if (!data.access_token) {
    throw new Error('web-api/v1/auth/refresh succeeded but did not return access_token');
  }
  return data.access_token;
}

/**
 * Ensure a single boolean toggle ends up at ``value`` on the server.
 *
 * Behaviour
 * ---------
 * - When the rendered checkbox already matches ``value`` (and is
 *   therefore in sync with ``serverConfig``), this is a **no-op** —
 *   the form is non-dirty so there is nothing to commit. The caller
 *   must NOT invoke ``clickSave`` afterwards, because the Save button
 *   stays disabled and ``toBeEnabled()`` would fail.
 * - When the rendered value differs from ``value``, this clicks the
 *   toggle once (flipping it to ``value``), waits for the visible
 *   state to settle, then issues a Save. The function only resolves
 *   after the success banner appears, so subsequent assertions can
 *   safely observe the post-save server state.
 *
 * Why this shape? Earlier revisions tried a "force dirty" two-click
 * pattern even when seed already matched the desired value. That made
 * the form dirty during the click sequence, but the final state was
 * still equal to ``serverConfig``, so the Svelte ``dirty`` derivation
 * collapsed back to ``false`` and the Save button remained disabled.
 * Splitting "ensure value" from "click save" lets each scenario
 * remain correct regardless of seed state.
 */
async function ensureToggleAtValue(
  page: Page,
  testid: string,
  value: boolean,
): Promise<void> {
  const toggle = page.locator(`[data-testid="${testid}"]`);
  await expect(toggle).toBeVisible();
  const current = await toggle.isChecked();
  if (current === value) {
    // Already in the desired state — the form is non-dirty and the
    // server already holds ``value``. Nothing to do.
    return;
  }
  await toggle.click();
  await expect(toggle).toBeChecked({ checked: value });
  await clickSave(page);
}

/**
 * Ensure the H3-resolution range input is set to ``value`` on the server.
 *
 * Mirrors :func:`ensureToggleAtValue` for the only non-boolean control
 * in the toggle section: when the range already shows ``value`` we
 * skip the Save (the form is non-dirty), otherwise we set ``value`` and
 * Save once.
 */
async function ensureRangeAtValue(
  page: Page,
  testid: string,
  value: string,
): Promise<void> {
  const range = page.locator(`[data-testid="${testid}"]`);
  await expect(range).toBeVisible();
  const current = await range.inputValue();
  if (current === value) {
    return;
  }
  await range.evaluate((input, nextValue) => {
    if (!(input instanceof HTMLInputElement)) return;
    input.value = nextValue;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }, value);
  await expect(range).toHaveValue(value);
  await clickSave(page);
}

/**
 * Click the Save button and wait for the success banner. The button
 * is expected to be enabled (i.e. the caller has just made the form
 * dirty). Callers that may end up with a non-dirty form should use
 * :func:`ensureToggleAtValue` / :func:`ensureRangeAtValue` instead,
 * which skip the Save when nothing changed.
 */
async function clickSave(page: Page): Promise<void> {
  const saveBtn = page.locator('[data-testid="restricted-toggles-save-button"]');
  await expect(saveBtn).toBeEnabled();
  await saveBtn.click();
  await expect(
    page.locator('[data-testid="restricted-toggles-save-success"]'),
  ).toBeVisible({ timeout: 10000 });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe('Phase 8 US3 — Restricted owner toggles (T404, FR-014/020-022)', () => {
  test.beforeEach(() => {
    test.skip(!SUITE_ENABLED, 'PHASE8_E2E_ENABLED is not set');
  });

  // -------------------------------------------------------------------------
  // Scenario 1: Restricted-toggles section is visible on a Restricted project
  // -------------------------------------------------------------------------
  test('Owner sees the Restricted-toggles section on a Restricted project', async ({
    page,
  }) => {
    test.skip(!RESTRICTED_PROJECT_ID, 'PHASE8_RESTRICTED_PROJECT_ID is not set');
    await login(page, OWNER);
    await page.goto(`/en/projects/${RESTRICTED_PROJECT_ID}`);

    const section = page.locator('[data-testid="restricted-toggles-section"]');
    await expect(section).toBeVisible({ timeout: 10000 });

    // Each of the eight inputs must render.
    for (const id of [
      'toggle-allow_media_playback',
      'toggle-allow_detection_view',
      'toggle-mask_species_in_detection',
      'toggle-allow_download',
      'toggle-allow_export',
      'toggle-allow_voting_and_comments',
      'toggle-public_location_precision_h3_res',
      'toggle-allow_precise_location_to_viewer',
    ]) {
      await expect(page.locator(`[data-testid="${id}"]`)).toBeVisible();
    }

    // The Save button is rendered (Owner can edit). It is disabled until
    // a toggle changes.
    const saveBtn = page.locator('[data-testid="restricted-toggles-save-button"]');
    await expect(saveBtn).toBeVisible();
    await expect(saveBtn).toBeDisabled();
  });

  // -------------------------------------------------------------------------
  // Scenario 2: allow_voting_and_comments=OFF blocks non-member voting
  // -------------------------------------------------------------------------
  test('allow_voting_and_comments=OFF returns 403 for non-member voting', async ({
    page,
    browser,
  }) => {
    test.skip(!RESTRICTED_PROJECT_ID, 'PHASE8_RESTRICTED_PROJECT_ID is not set');
    test.skip(!DETECTION_ID, 'PHASE8_DETECTION_ID is not set');
    test.skip(!NONMEMBER.email, 'PHASE8_NONMEMBER_EMAIL is not set');

    // Owner toggles the flag OFF.
    await login(page, OWNER);
    await page.goto(`/en/projects/${RESTRICTED_PROJECT_ID}`);
    await expect(
      page.locator('[data-testid="restricted-toggles-section"]'),
    ).toBeVisible({ timeout: 10000 });
    await ensureToggleAtValue(page, 'toggle-allow_voting_and_comments', false);

    // Non-member opens a fresh context, signs in, and tries to vote via
    // the public vote API. The frontend non-member detection-detail
    // page is the user-facing surface, but for the purposes of T404 we
    // assert the API gating directly so the test does not depend on
    // a fully-seeded UI for the non-member path.
    const ctx = await browser.newContext();
    const page2 = await ctx.newPage();
    await login(page2, NONMEMBER);
    const bearer = await getBearerTokenAfterLogin(page2);
    const apiResponse = await page2.request.post(
      `/api/v1/projects/${RESTRICTED_PROJECT_ID}/detections/${DETECTION_ID}/vote`,
      {
        data: { vote: 'agree' },
        headers: { Authorization: `Bearer ${bearer}` },
        failOnStatusCode: false,
      },
    );
    expect(
      [401, 403],
      'non-member vote attempt must be denied with 401 or 403',
    ).toContain(apiResponse.status());
    await ctx.close();
  });

  // -------------------------------------------------------------------------
  // Scenario 3: allow_detection_view=OFF hides detections from non-members
  // -------------------------------------------------------------------------
  test('allow_detection_view=OFF removes detections from non-member listing', async ({
    page,
    browser,
  }) => {
    test.skip(!RESTRICTED_PROJECT_ID, 'PHASE8_RESTRICTED_PROJECT_ID is not set');
    test.skip(!NONMEMBER.email, 'PHASE8_NONMEMBER_EMAIL is not set');

    await login(page, OWNER);
    await page.goto(`/en/projects/${RESTRICTED_PROJECT_ID}`);
    await expect(
      page.locator('[data-testid="restricted-toggles-section"]'),
    ).toBeVisible({ timeout: 10000 });
    await ensureToggleAtValue(page, 'toggle-allow_detection_view', false);

    const ctx = await browser.newContext();
    const page2 = await ctx.newPage();
    await login(page2, NONMEMBER);
    const bearer = await getBearerTokenAfterLogin(page2);
    // The non-member detection list endpoint must respond with either
    // 403 (gate denial) or 200 + zero detections (filtered listing).
    const apiResponse = await page2.request.get(
      `/api/v1/projects/${RESTRICTED_PROJECT_ID}/detections`,
      {
        headers: { Authorization: `Bearer ${bearer}` },
        failOnStatusCode: false,
      },
    );
    if (apiResponse.status() === 200) {
      const body = (await apiResponse.json()) as {
        items?: Array<unknown>;
        total?: number;
      };
      const items = body.items ?? [];
      expect(
        items.length,
        'non-member should see zero detections when allow_detection_view=OFF',
      ).toBe(0);
    } else {
      expect([401, 403]).toContain(apiResponse.status());
    }
    await ctx.close();
  });

  // -------------------------------------------------------------------------
  // Scenario 4: public_location_precision_h3_res=5 changes non-member resolution
  // -------------------------------------------------------------------------
  test('public_location_precision_h3_res=5 surfaces resolution 5 cells to non-members', async ({
    page,
    browser,
  }) => {
    test.skip(!RESTRICTED_PROJECT_ID, 'PHASE8_RESTRICTED_PROJECT_ID is not set');

    await login(page, OWNER);
    await page.goto(`/en/projects/${RESTRICTED_PROJECT_ID}`);
    await expect(
      page.locator('[data-testid="restricted-toggles-section"]'),
    ).toBeVisible({ timeout: 10000 });

    // Persist resolution 5 on the server. The helper skips the Save
    // when the range already shows '5' (form non-dirty), and Saves
    // once otherwise.
    await ensureRangeAtValue(page, 'toggle-public_location_precision_h3_res', '5');

    // After ensureRangeAtValue() the persisted value must be 5 (the
    // form re-mounts from the GET /projects/{id} response).
    await expect(
      page.locator('[data-testid="toggle-public_location_precision_h3_res"]'),
    ).toHaveValue('5');

    // FR-021 strict assertion: a non-member must observe a coarsened
    // H3 cell at resolution 5 from the public site listing.
    test.skip(!NONMEMBER.email, 'PHASE8_NONMEMBER_EMAIL is not set');

    const ctx = await browser.newContext();
    const page2 = await ctx.newPage();
    try {
      await login(page2, NONMEMBER);
      const bearer = await getBearerTokenAfterLogin(page2);
      // Non-members fetch sites via the public sites listing. This
      // endpoint applies Stage-2 response filtering, so ``h3_index_member``
      // (Phase 13 P4 / T807 canonical Site H3 wire field) is already
      // coarsened to the project's ``public_location_precision_h3_res``
      // for non-members of a Restricted project.
      const sitesResponse = await page2.request.get(
        `/api/v1/projects/${RESTRICTED_PROJECT_ID}/sites?page=1&page_size=100`,
        {
          headers: { Authorization: `Bearer ${bearer}` },
          failOnStatusCode: false,
        },
      );
      expect(
        sitesResponse.status(),
        'non-member sites listing must return 200 for a Restricted project (gated by metadata-read)',
      ).toBe(200);
      const sitesBody = (await sitesResponse.json()) as {
        items?: Array<{ h3_index_member?: string }>;
      };
      const items = sitesBody.items ?? [];
      expect(
        items.length,
        'Restricted project must expose at least one site for the H3 resolution check',
      ).toBeGreaterThan(0);
      // Pick the first site's coarsened h3_index_member and ask the backend
      // for its decoded resolution. The /h3/validate endpoint requires
      // authentication only, so the non-member can call it.
      const sampleIndex = items[0]?.h3_index_member;
      expect(
        typeof sampleIndex === 'string' && sampleIndex.length > 0,
        'sites[].h3_index_member must be a non-empty string',
      ).toBe(true);
      const h3Resp = await page2.request.post('/api/v1/h3/validate', {
        data: { h3_index: sampleIndex },
        headers: { Authorization: `Bearer ${bearer}` },
        failOnStatusCode: false,
      });
      expect(h3Resp.status(), '/h3/validate must accept the site h3_index_member').toBe(200);
      const h3Body = (await h3Resp.json()) as { valid?: boolean; resolution?: number };
      expect(h3Body.valid, 'site h3_index_member must validate as a real H3 cell').toBe(true);
      expect(
        h3Body.resolution,
        'non-member sites[].h3_index_member must be coarsened to resolution 5 (FR-021)',
      ).toBe(5);
    } finally {
      await ctx.close();
    }
  });

  // -------------------------------------------------------------------------
  // Scenario 5: mask_species_in_detection=true → species shown as "(masked)"
  // -------------------------------------------------------------------------
  test('mask_species_in_detection=true masks species for non-members', async ({
    page,
    browser,
  }) => {
    test.skip(!RESTRICTED_PROJECT_ID, 'PHASE8_RESTRICTED_PROJECT_ID is not set');
    test.skip(!NONMEMBER.email, 'PHASE8_NONMEMBER_EMAIL is not set');
    test.skip(!DETECTION_ID, 'PHASE8_DETECTION_ID is not set');

    await login(page, OWNER);
    await page.goto(`/en/projects/${RESTRICTED_PROJECT_ID}`);
    await expect(
      page.locator('[data-testid="restricted-toggles-section"]'),
    ).toBeVisible({ timeout: 10000 });
    // We need allow_detection_view=ON and mask_species_in_detection=ON
    // simultaneously so the non-member receives a row but with the
    // species masked. Each helper call is independent: when one toggle
    // already holds the desired value it is a no-op, otherwise it
    // flips and Saves.
    await ensureToggleAtValue(page, 'toggle-allow_detection_view', true);
    await ensureToggleAtValue(page, 'toggle-mask_species_in_detection', true);

    const ctx = await browser.newContext();
    const page2 = await ctx.newPage();
    try {
      await login(page2, NONMEMBER);
      const bearer = await getBearerTokenAfterLogin(page2);
      const apiResponse = await page2.request.get(
        `/api/v1/projects/${RESTRICTED_PROJECT_ID}/detections/${DETECTION_ID}`,
        {
          headers: { Authorization: `Bearer ${bearer}` },
          failOnStatusCode: false,
        },
      );
      // FR-022 spec requirement: with allow_detection_view=true AND
      // mask_species_in_detection=true the detection must be
      // accessible (200) but with species names replaced by the
      // "(masked)" sentinel. We require 200 here — a 401/403 would
      // mean the seed for this test does not actually grant the
      // detection-view capability we just toggled on, which is a
      // regression and must surface as a test failure.
      expect(
        apiResponse.status(),
        'allow_detection_view=true should let a non-member fetch the detection (200 expected)',
      ).toBe(200);
      const body = (await apiResponse.json()) as Record<string, unknown>;
      const json = JSON.stringify(body);
      expect(
        json,
        'masked-species detection must contain the (masked) sentinel anywhere in the payload',
      ).toContain('(masked)');
    } finally {
      await ctx.close();
    }
  });

  // -------------------------------------------------------------------------
  // Scenario 6: allow_precise_location_to_viewer=true → Viewer sees precise lat/lng
  // -------------------------------------------------------------------------
  test('allow_precise_location_to_viewer=true grants Viewer member-grade location', async ({
    page,
    browser,
  }) => {
    test.skip(!RESTRICTED_PROJECT_ID, 'PHASE8_RESTRICTED_PROJECT_ID is not set');
    test.skip(!VIEWER.email, 'PHASE8_VIEWER_EMAIL is not set');

    await login(page, OWNER);
    await page.goto(`/en/projects/${RESTRICTED_PROJECT_ID}`);
    await expect(
      page.locator('[data-testid="restricted-toggles-section"]'),
    ).toBeVisible({ timeout: 10000 });
    await ensureToggleAtValue(page, 'toggle-allow_precise_location_to_viewer', true);

    const ctx = await browser.newContext();
    const page2 = await ctx.newPage();
    await login(page2, VIEWER);
    const bearer = await getBearerTokenAfterLogin(page2);
    // The Viewer detail page must surface a project-overview / sites
    // payload with member-grade coordinates. We probe the same
    // endpoint the project-detail map uses and assert the response
    // contains explicit lat/lng pairs (not coarsened to null).
    const apiResponse = await page2.request.get(
      `/api/v1/projects/${RESTRICTED_PROJECT_ID}/overview`,
      {
        headers: { Authorization: `Bearer ${bearer}` },
        failOnStatusCode: false,
      },
    );
    // Strict assertion: the Viewer must be able to fetch the project
    // overview after we toggled allow_precise_location_to_viewer=true.
    // Silently skipping non-200s would let 401/403/500 regressions
    // pass — this scenario is about FR-022's positive contract.
    expect(
      apiResponse.status(),
      'Viewer with allow_precise_location_to_viewer=true must receive 200 from /overview',
    ).toBe(200);
    const body = (await apiResponse.json()) as {
      sites?: Array<{ latitude?: number | null; longitude?: number | null }>;
    };
    const sites = body.sites ?? [];
    // At least one site should expose a non-null latitude/longitude
    // when precise location is granted to the Viewer.
    const hasPrecise = sites.some(
      (s) => typeof s.latitude === 'number' && typeof s.longitude === 'number',
    );
    // We accept either a populated array (precise) or an empty array
    // (no sites in the project) — but if sites exist they MUST have
    // coordinates.
    if (sites.length > 0) {
      expect(
        hasPrecise,
        'Viewer with allow_precise_location_to_viewer=true must see lat/lng',
      ).toBe(true);
    }
    await ctx.close();
  });

  // -------------------------------------------------------------------------
  // Scenario 7: Public projects render the public-only notice (section hidden)
  // -------------------------------------------------------------------------
  test('Public project shows the public-only notice instead of the toggle list', async ({
    page,
  }) => {
    test.skip(!PUBLIC_PROJECT_ID, 'PHASE8_PUBLIC_PROJECT_ID is not set');
    await login(page, OWNER);
    await page.goto(`/en/projects/${PUBLIC_PROJECT_ID}`);

    // The section header is still rendered (so the layout stays
    // stable) but it should contain the public-only notice and NOT
    // any of the toggle inputs.
    const section = page.locator('[data-testid="restricted-toggles-section"]');
    await expect(section).toBeVisible({ timeout: 10000 });
    await expect(
      page.locator('[data-testid="restricted-toggles-public-notice"]'),
    ).toBeVisible();

    // None of the actual toggle controls should be in the DOM.
    await expect(
      page.locator('[data-testid="toggle-allow_media_playback"]'),
    ).toHaveCount(0);
    await expect(
      page.locator('[data-testid="restricted-toggles-save-button"]'),
    ).toHaveCount(0);
  });

  // -------------------------------------------------------------------------
  // Scenario 8: Members see read-only toggles (no save button, inputs disabled)
  // -------------------------------------------------------------------------
  test('Member sees Restricted toggles in read-only mode (no save, inputs disabled)', async ({
    page,
  }) => {
    test.skip(!RESTRICTED_PROJECT_ID, 'PHASE8_RESTRICTED_PROJECT_ID is not set');
    test.skip(!MEMBER.email, 'PHASE8_MEMBER_EMAIL is not set');

    await login(page, MEMBER);
    await page.goto(`/en/projects/${RESTRICTED_PROJECT_ID}`);

    const section = page.locator('[data-testid="restricted-toggles-section"]');
    await expect(section).toBeVisible({ timeout: 10000 });

    // The "no permission" notice should be rendered.
    await expect(
      page.locator('[data-testid="restricted-toggles-no-permission-notice"]'),
    ).toBeVisible();

    // The Save button must be absent.
    await expect(
      page.locator('[data-testid="restricted-toggles-save-button"]'),
    ).toHaveCount(0);

    // Each toggle is disabled.
    for (const id of [
      'toggle-allow_media_playback',
      'toggle-allow_detection_view',
      'toggle-mask_species_in_detection',
      'toggle-allow_download',
      'toggle-allow_export',
      'toggle-allow_voting_and_comments',
      'toggle-public_location_precision_h3_res',
      'toggle-allow_precise_location_to_viewer',
    ]) {
      await expect(page.locator(`[data-testid="${id}"]`)).toBeDisabled();
    }
  });
});
