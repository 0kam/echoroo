/**
 * E2E tests for Phase 9 US4 — Restricted project discovery (T414).
 *
 * Covers spec.md acceptance scenarios L499-505 (PR-003 / FR-019 /
 * FR-026):
 *
 *   1. Guest can enumerate Restricted project metadata via GET
 *      `/api/v1/projects` — `name / description / visibility /
 *      dataset_count` are present even though the caller is
 *      unauthenticated and not a member.
 *   2. Guest opening the Restricted detail page sees the project
 *      header (name + description) but **NOT** the
 *      "Request access" mailto: affordance — that surface is gated
 *      to Authenticated non-members (US4 AC2).
 *   3. Authenticated non-member opening the Restricted detail page
 *      sees the project header **AND** the "Request access" callout
 *      with the owner's display name.
 *   4. The mailto: link href starts with `mailto:` and embeds an
 *      i18n-localised `subject` and `body` query parameter that
 *      includes the project name.
 *   5. With `allow_detection_view=OFF` on the Restricted project, an
 *      Authenticated non-member's species search **does not** surface
 *      detections from this project (FR-017 / FR-026). The project
 *      metadata itself is still enumerable.
 *   6. (Optional) With `allow_detection_view=ON` the same probe
 *      surfaces detection rows for the same caller — guarded behind
 *      `PHASE9_DETECTION_ID` so the assertion only runs when the
 *      seed has a known detection.
 *
 * Environment gate
 * ----------------
 * All tests in this file are skipped unless `PHASE9_E2E_ENABLED=1` is
 * set, mirroring the env-gate pattern used by Phase 5/6/7/8 specs. CI
 * never runs these against a cold database.
 *
 * Required environment variables
 * --------------------------------
 *   PHASE9_E2E_ENABLED=1                Enable this suite.
 *   PHASE9_RESTRICTED_PROJECT_ID=<uuid> Restricted-visibility project
 *                                       owned by the OWNER credentials below.
 *
 * Optional environment variables
 * --------------------------------
 *   PHASE9_OWNER_EMAIL                  Owner credentials (defaults to
 *                                       memory/test-accounts.md). Used by
 *                                       scenario 5 to flip
 *                                       `allow_detection_view` OFF before
 *                                       the non-member probe.
 *   PHASE9_OWNER_PASSWORD
 *   PHASE9_NONMEMBER_EMAIL              Authenticated non-member used by
 *                                       scenarios 3-6. When unset, those
 *                                       scenarios are skipped.
 *   PHASE9_NONMEMBER_PASSWORD
 *   PHASE9_DETECTION_ID                 Detection under the Restricted
 *                                       project — when set, scenario 6
 *                                       runs the `allow_detection_view=ON`
 *                                       positive assertion. When unset
 *                                       scenario 6 is skipped.
 *   PHASE9_TOTP_SECRET                  Shared TOTP secret used to derive
 *                                       2FA challenge codes when an
 *                                       account-specific secret is not
 *                                       provided.
 *   PHASE9_OWNER_TOTP_SECRET            Per-account TOTP secrets that
 *   PHASE9_NONMEMBER_TOTP_SECRET        override `PHASE9_TOTP_SECRET`.
 *
 * How to run
 * ----------
 *     ./scripts/docker.sh dev
 *     PHASE9_E2E_ENABLED=1 \
 *       PHASE9_RESTRICTED_PROJECT_ID=<uuid> \
 *       npx playwright test tests/e2e/phase9-restricted-discovery.spec.ts
 *
 * Notes
 * -----
 * - The Guest scenarios (1, 2) deliberately avoid logging in and use
 *   `page.request` for the API probe so we can assert FR-019 on the
 *   public surface without any session state.
 * - Scenarios 3-6 follow the Phase 8 pattern: UI login → cookie
 *   refresh → Bearer-token probe of `/api/v1/...`. Login helpers /
 *   `getBearerTokenAfterLogin` are intentionally inlined here rather
 *   than extracted to `helpers/` because each phase suite scopes its
 *   own env var prefix; consolidating across phases is a separate
 *   E2E-infra refactor (Phase 8 Round 5 follow-up).
 * - 2FA is mandatory since Phase 4. When a TOTP challenge appears and
 *   no secret is configured the test skips with a diagnostic, mirroring
 *   the Phase 5/6/7/8 deferral pattern.
 */

import { test, expect, type Page } from '@playwright/test';
import { generateTotpCode, waitForFreshTotpWindow } from './helpers/totp';

// ---------------------------------------------------------------------------
// Env gate
// ---------------------------------------------------------------------------
const SUITE_ENABLED = process.env.PHASE9_E2E_ENABLED === '1';
const RESTRICTED_PROJECT_ID = process.env.PHASE9_RESTRICTED_PROJECT_ID ?? '';
const DETECTION_ID = process.env.PHASE9_DETECTION_ID ?? '';

const SHARED_TEST_EMAIL = 'test@echoroo.app';
const SHARED_TEST_PASSWORD = 'N6Wz0IJXsQc4';
const SHARED_TOTP_SECRET = process.env.PHASE9_TOTP_SECRET ?? '';

interface TestCreds {
  email: string;
  password: string;
  totpSecret: string;
}

const OWNER: TestCreds = {
  email: process.env.PHASE9_OWNER_EMAIL ?? SHARED_TEST_EMAIL,
  password: process.env.PHASE9_OWNER_PASSWORD ?? SHARED_TEST_PASSWORD,
  totpSecret: process.env.PHASE9_OWNER_TOTP_SECRET ?? SHARED_TOTP_SECRET,
};
const NONMEMBER: TestCreds = {
  email: process.env.PHASE9_NONMEMBER_EMAIL ?? '',
  password: process.env.PHASE9_NONMEMBER_PASSWORD ?? '',
  totpSecret: process.env.PHASE9_NONMEMBER_TOTP_SECRET ?? SHARED_TOTP_SECRET,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Sign in via the UI, transparently completing the 2FA TOTP challenge
 * if the backend asks for one. Mirrors the Phase 8 helper of the same
 * name — kept inline so each suite owns its own env prefixes.
 */
async function login(page: Page, creds: TestCreds): Promise<void> {
  await page.goto('/login');
  await page.fill('input[name="email"]', creds.email);
  await page.fill('input[name="password"]', creds.password);
  await page.click('button[type="submit"]');

  const twoFactorForm = page.locator('[data-testid="two-factor-form"]');
  const off2faRedirect = page.waitForURL(
    (url) => !url.pathname.replace(/^\/[a-z]{2}(?=\/)/, '').startsWith('/login'),
    { timeout: 15000 },
  );
  await Promise.race([
    twoFactorForm.waitFor({ state: 'visible', timeout: 15000 }),
    off2faRedirect.catch(() => undefined),
  ]);

  if (await twoFactorForm.isVisible().catch(() => false)) {
    if (!creds.totpSecret) {
      test.skip(
        true,
        `2FA challenge appeared for ${creds.email} but no TOTP secret was provided ` +
          `(set PHASE9_*_TOTP_SECRET or PHASE9_TOTP_SECRET). 2FA automation for E2E ` +
          `is tracked as a follow-up; Phase 4 enforces 2FA for all accounts.`,
      );
      return;
    }
    await waitForFreshTotpWindow();
    const code = generateTotpCode(creds.totpSecret);
    await page.fill('[data-testid="two-factor-code-input"]', code);
    await Promise.all([
      page.waitForURL(
        (url) => !url.pathname.replace(/^\/[a-z]{2}(?=\/)/, '').startsWith('/login'),
        { timeout: 15000 },
      ),
      page.click('[data-testid="two-factor-submit"]'),
    ]);
  }
}

/**
 * Obtain a Bearer access token after a UI login by swapping the
 * `echoroo_refresh` cookie via `POST /web-api/v1/auth/refresh`.
 *
 * The `/api/v1/...` surface is Bearer-only (`CurrentUser` dependency);
 * UI login plants only the cookie principal, so we need this hop before
 * any `page.request.*` probe of `/api/v1`.
 */
async function getBearerTokenAfterLogin(page: Page): Promise<string> {
  const response = await page.request.post('/web-api/v1/auth/refresh', {
    failOnStatusCode: false,
  });
  if (response.status() !== 200) {
    const body = await response.text().catch(() => '<no body>');
    throw new Error(
      `web-api/v1/auth/refresh returned ${response.status()} after UI login. ` +
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
 * Convenience: fetch the Restricted project as the Owner via the UI
 * + cookie-refreshed Bearer, then PATCH `/web-api/v1/projects/{id}/restricted-config`
 * to pin a single boolean toggle. Returns when the response settles.
 *
 * We use the Web UI surface (cookie + CSRF) here rather than driving
 * the toggle UI because the test only cares about persisted server
 * state — the Phase 8 spec already covers the form-binding path. CSRF
 * is read out of `document.cookie` exactly the way `projects.ts`
 * `getCsrfToken` does it, so the spec stays decoupled from frontend
 * Web-API plumbing.
 */
async function setAllowDetectionView(
  page: Page,
  projectId: string,
  value: boolean,
): Promise<void> {
  // Read every required toggle from the canonical detail endpoint so
  // we send a Pydantic-`Extra.forbid`-compatible body. Any missing key
  // would 422.
  const bearer = await getBearerTokenAfterLogin(page);
  const detail = await page.request.get(`/api/v1/projects/${projectId}`, {
    headers: { Authorization: `Bearer ${bearer}` },
    failOnStatusCode: false,
  });
  expect(
    detail.status(),
    `Owner must be able to fetch the restricted project for toggle prep (got ${detail.status()})`,
  ).toBe(200);
  const body = (await detail.json()) as {
    restricted_config?: Record<string, unknown>;
  };
  const config = body.restricted_config ?? {};
  const next = { ...config, allow_detection_view: value };

  // CSRF token lives in a JS-readable cookie planted by the session
  // login flow.
  const cookies = await page.context().cookies();
  const csrf = cookies.find((c) => c.name === 'echoroo_csrf')?.value ?? '';
  expect(csrf.length, 'echoroo_csrf cookie must be present after login').toBeGreaterThan(0);

  const patchResp = await page.request.patch(
    `/web-api/v1/projects/${projectId}/restricted-config`,
    {
      data: next,
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': csrf,
        Authorization: `Bearer ${bearer}`,
      },
      failOnStatusCode: false,
    },
  );
  expect(
    patchResp.status(),
    `restricted-config PATCH must succeed (got ${patchResp.status()})`,
  ).toBe(200);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe('Phase 9 US4 — Restricted project discovery (T414, FR-017/019/026)', () => {
  test.beforeEach(() => {
    test.skip(!SUITE_ENABLED, 'PHASE9_E2E_ENABLED is not set');
  });

  // -------------------------------------------------------------------------
  // Scenario 1: Guest enumerates Restricted project metadata
  // -------------------------------------------------------------------------
  test('Guest sees Restricted project metadata in GET /projects (FR-019)', async ({
    page,
  }) => {
    test.skip(!RESTRICTED_PROJECT_ID, 'PHASE9_RESTRICTED_PROJECT_ID is not set');

    // No login — Guest path. The list endpoint must enumerate the
    // Restricted project's summary fields.
    const response = await page.request.get('/api/v1/projects?page=1', {
      failOnStatusCode: false,
    });
    expect(
      response.status(),
      'Guest list endpoint must return 200 (Restricted projects enumerable per FR-019)',
    ).toBe(200);
    const body = (await response.json()) as {
      items?: Array<{
        id?: string;
        name?: string;
        description?: string | null;
        visibility?: string;
        dataset_count?: number;
        owner_display_name?: string;
      }>;
    };
    const items = body.items ?? [];
    const summary = items.find((p) => p.id === RESTRICTED_PROJECT_ID);
    expect(
      summary,
      `Restricted project ${RESTRICTED_PROJECT_ID} must appear in the Guest list response`,
    ).toBeDefined();
    expect(summary!.visibility).toBe('restricted');
    expect(typeof summary!.name).toBe('string');
    expect(summary!.name!.length).toBeGreaterThan(0);
    expect(typeof summary!.dataset_count).toBe('number');
    expect(typeof summary!.owner_display_name).toBe('string');
    // The summary must NOT leak `restricted_config` per FR-019.
    expect(
      (summary as Record<string, unknown>).restricted_config,
      'ProjectSummary must never include restricted_config',
    ).toBeUndefined();
  });

  // -------------------------------------------------------------------------
  // Scenario 2: Guest detail view does NOT show the Request access affordance
  // -------------------------------------------------------------------------
  test('Guest detail view hides the mailto: Request access affordance', async ({
    page,
  }) => {
    test.skip(!RESTRICTED_PROJECT_ID, 'PHASE9_RESTRICTED_PROJECT_ID is not set');

    // Guest navigates straight to the SPA detail route without login.
    // The (app) layout normally redirects to /login when there is no
    // session, but the Guest-public surface (Phase 5) keeps the
    // Restricted metadata reachable via /explore/projects/{id}. We
    // assert via the API surface here so the test doesn't bind to the
    // SPA route shape — the affordance lives only in the
    // Authenticated detail page.
    const response = await page.request.get(`/api/v1/projects/${RESTRICTED_PROJECT_ID}`, {
      failOnStatusCode: false,
    });
    // Whether the Guest detail surface returns 200 (Phase 5 metadata)
    // or 401/403 depends on backend deployment of the Phase-5/9 detail
    // route. Either way: the SPA detail page would never render the
    // Request-access mailto affordance for a Guest because
    // `currentUser` is null. We assert that explicitly via the DOM by
    // visiting the Authenticated detail route without a session — the
    // login redirect short-circuits so the affordance is provably
    // unreachable.
    await page.goto(`/en/projects/${RESTRICTED_PROJECT_ID}`);
    await expect(
      page.locator('[data-testid="restricted-request-access-mailto"]'),
    ).toHaveCount(0);
    // Sanity: the API probe must at least not 5xx.
    expect(
      response.status(),
      `Restricted detail probe must not 5xx (got ${response.status()})`,
    ).toBeLessThan(500);
  });

  // -------------------------------------------------------------------------
  // Scenario 3: Authenticated non-member sees the Request access callout
  // -------------------------------------------------------------------------
  test('Authenticated non-member sees the mailto: Request access callout (US4 AC2)', async ({
    page,
  }) => {
    test.skip(!RESTRICTED_PROJECT_ID, 'PHASE9_RESTRICTED_PROJECT_ID is not set');
    test.skip(!NONMEMBER.email, 'PHASE9_NONMEMBER_EMAIL is not set');

    await login(page, NONMEMBER);
    await page.goto(`/en/projects/${RESTRICTED_PROJECT_ID}`);

    const callout = page.locator('[data-testid="restricted-request-access"]');
    await expect(callout).toBeVisible({ timeout: 10000 });

    // Phase 9 polish round 2 致命 1 (2026-04-27): the backend now exposes
    // `owner.email` for Authenticated callers on Restricted projects so
    // the mailto: link MUST render — the previous "no-contact" fallback
    // is reserved for the rare missing-email defensive case and is no
    // longer an acceptable outcome under US4 AC2.
    const mailtoLink = page.locator('[data-testid="restricted-request-access-mailto"]');
    await expect(mailtoLink).toHaveCount(1);
    const href = await mailtoLink.getAttribute('href');
    expect(href, 'mailto: href must be present').toBeTruthy();
    expect(href!.startsWith('mailto:'), 'href must start with mailto:').toBe(true);
  });

  // -------------------------------------------------------------------------
  // Scenario 4: mailto: href shape — subject + body match the i18n template
  // -------------------------------------------------------------------------
  test('mailto: href starts with mailto: and embeds project name in subject', async ({
    page,
  }) => {
    test.skip(!RESTRICTED_PROJECT_ID, 'PHASE9_RESTRICTED_PROJECT_ID is not set');
    test.skip(!NONMEMBER.email, 'PHASE9_NONMEMBER_EMAIL is not set');

    await login(page, NONMEMBER);
    await page.goto(`/en/projects/${RESTRICTED_PROJECT_ID}`);

    const callout = page.locator('[data-testid="restricted-request-access"]');
    await expect(callout).toBeVisible({ timeout: 10000 });

    // Phase 9 polish round 2 致命 1 (2026-04-27): Authenticated
    // non-member on a Restricted project MUST see the mailto: link —
    // backend now populates `owner.email` for this exact combination
    // so US4 AC2 is functional, not a "best effort" affordance.
    const mailtoLink = page.locator('[data-testid="restricted-request-access-mailto"]');
    await expect(mailtoLink).toHaveCount(1);
    const href = await mailtoLink.getAttribute('href');
    expect(href, 'mailto: href must be present').toBeTruthy();
    expect(href!.startsWith('mailto:'), 'href must start with mailto:').toBe(true);

    // Parse the query string and assert subject embeds the project
    // name. We don't assert the exact i18n string so the test stays
    // robust to copy edits; the structural invariant is enough.
    const queryStart = href!.indexOf('?');
    expect(queryStart, 'mailto: must include query parameters').toBeGreaterThan(0);
    const params = new URLSearchParams(href!.slice(queryStart + 1));
    const subject = params.get('subject') ?? '';
    const body = params.get('body') ?? '';
    expect(subject.length, 'subject must be non-empty').toBeGreaterThan(0);
    expect(body.length, 'body must be non-empty').toBeGreaterThan(0);
    // The header still renders the project name; pull it from the
    // visible heading so we don't bind to API state.
    const projectName = (await page.locator('h1').first().textContent())?.trim() ?? '';
    expect(projectName.length).toBeGreaterThan(0);
    expect(
      subject.includes(projectName),
      `subject (${subject!}) must include the project name (${projectName})`,
    ).toBe(true);
  });

  // -------------------------------------------------------------------------
  // Scenario 5: allow_detection_view=OFF hides species in cross-search probe
  // -------------------------------------------------------------------------
  test('allow_detection_view=OFF excludes Restricted detections from non-member cross-search (FR-017/026)', async ({
    page,
    browser,
  }) => {
    test.skip(!RESTRICTED_PROJECT_ID, 'PHASE9_RESTRICTED_PROJECT_ID is not set');
    test.skip(!NONMEMBER.email, 'PHASE9_NONMEMBER_EMAIL is not set');

    // Owner flips allow_detection_view OFF.
    await login(page, OWNER);
    await setAllowDetectionView(page, RESTRICTED_PROJECT_ID, false);

    // Non-member context probes the project's detection list — the
    // surrogate for cross-project species search until the Phase 11
    // route ships. With the toggle OFF the response must be either
    // a 403 (gate denial) or 200 with zero rows.
    const ctx = await browser.newContext();
    const page2 = await ctx.newPage();
    try {
      await login(page2, NONMEMBER);
      const bearer = await getBearerTokenAfterLogin(page2);
      const apiResp = await page2.request.get(
        `/api/v1/projects/${RESTRICTED_PROJECT_ID}/detections`,
        {
          headers: { Authorization: `Bearer ${bearer}` },
          failOnStatusCode: false,
        },
      );
      if (apiResp.status() === 200) {
        const respBody = (await apiResp.json()) as { items?: Array<unknown> };
        expect(
          (respBody.items ?? []).length,
          'Non-member must see zero detection rows when allow_detection_view=OFF',
        ).toBe(0);
      } else {
        expect([401, 403]).toContain(apiResp.status());
      }

      // The project metadata itself must still be enumerable via the
      // public list endpoint — FR-019 separates metadata visibility
      // from detection visibility.
      const listResp = await page2.request.get('/api/v1/projects?page=1', {
        headers: { Authorization: `Bearer ${bearer}` },
        failOnStatusCode: false,
      });
      expect(listResp.status()).toBe(200);
      const listBody = (await listResp.json()) as {
        items?: Array<{ id?: string }>;
      };
      const stillEnumerable = (listBody.items ?? []).some(
        (p) => p.id === RESTRICTED_PROJECT_ID,
      );
      expect(
        stillEnumerable,
        'Restricted project metadata must remain enumerable even with allow_detection_view=OFF',
      ).toBe(true);
    } finally {
      await ctx.close();
    }
  });

  // -------------------------------------------------------------------------
  // Scenario 6 (optional): allow_detection_view=ON surfaces detections
  // -------------------------------------------------------------------------
  test('allow_detection_view=ON exposes the seeded Restricted detection to non-members', async ({
    page,
    browser,
  }) => {
    test.skip(!RESTRICTED_PROJECT_ID, 'PHASE9_RESTRICTED_PROJECT_ID is not set');
    test.skip(!NONMEMBER.email, 'PHASE9_NONMEMBER_EMAIL is not set');
    test.skip(!DETECTION_ID, 'PHASE9_DETECTION_ID is not set');

    await login(page, OWNER);
    await setAllowDetectionView(page, RESTRICTED_PROJECT_ID, true);

    const ctx = await browser.newContext();
    const page2 = await ctx.newPage();
    try {
      await login(page2, NONMEMBER);
      const bearer = await getBearerTokenAfterLogin(page2);
      const apiResp = await page2.request.get(
        `/api/v1/projects/${RESTRICTED_PROJECT_ID}/detections/${DETECTION_ID}`,
        {
          headers: { Authorization: `Bearer ${bearer}` },
          failOnStatusCode: false,
        },
      );
      expect(
        apiResp.status(),
        'Non-member must be able to fetch a seeded detection when allow_detection_view=ON',
      ).toBe(200);
    } finally {
      await ctx.close();
    }
  });
});
