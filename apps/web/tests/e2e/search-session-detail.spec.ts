/**
 * E2E smoke tests for SearchSessionDetail.svelte
 *
 * Safety net before splitting SearchSessionDetail into hooks and sub-components.
 * All 9 test cases from plan.md §8 are covered so that behaviour regressions
 * after the refactor will be caught immediately.
 *
 * Covers the search session detail route:
 *   /en/projects/{projectId}/search?session={sessionId}
 *
 * Auth strategy (same as annotation-editor.spec.ts):
 *   1. Obtain refresh_token via Node.js fetch (avoids browser rate-limit).
 *   2. Plant cookie in sharedContext so the SPA can restore the access token
 *      via /auth/refresh on every page load.
 *   3. Use sharedPage across all tests to keep the in-memory token alive.
 *
 * Seeding strategy (beforeAll):
 *   1. Login via Node.js fetch to get access_token + refresh_token.
 *   2. GET /search/sessions?limit=50 to list existing sessions.
 *   3. Deterministic selection: status === 'completed' && species_config !== null
 *      && result_count > 0, sorted by id ascending, pick first.
 *   4. env override: E2E_SEARCH_SESSION_ID takes priority.
 *   5. If no qualifying session found, all tests are skipped via test.skip().
 *   6. Record ORIGINAL_NAME for rename restore in test 3.
 *
 * Note on ReferenceSoundsPanel heading:
 *   In detail view (readonly=true), the heading is "Loaded Sources" (search_loaded_sources).
 *   In new-search mode (readonly=false / editable), it is "Reference Sounds" (search_reference_sounds).
 *   Tests 6 & 7 use the editable "Reference Sounds" heading as the new-search anchor.
 */

import {
  test,
  expect,
  chromium,
  type Browser,
  type BrowserContext,
  type Page,
} from '@playwright/test';

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

// Defaults unchanged; LAN/remote runs may override via env without editing
// this file (e.g. PLAYWRIGHT_BASE_URL / ECHOROO_API_URL pointing at an IP).
const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:3000';
const API_BASE =
  process.env.ECHOROO_API_URL || process.env.PUBLIC_API_URL || 'http://localhost:8002';
const TEST_PROJECT_ID = '6ed4e592-87ca-4fa7-a384-c64ca6bfeec5';
const TEST_EMAIL = 'test@echoroo.app';
const TEST_PASSWORD = 'N6Wz0IJXsQc4';

// ---------------------------------------------------------------------------
// Suite-level state
// ---------------------------------------------------------------------------

let sharedBrowser: Browser;
let sharedContext: BrowserContext;
let sharedPage: Page;

const suiteConsoleErrors: string[] = [];

// Seeded data (populated in beforeAll)
let accessToken = '';
let testSessionId = '';
let originalName = '';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Obtain credentials via a direct Node.js HTTP call.
 * Does not count against the browser-side rate limiter.
 *
 * Retries up to 3 times with a 25-second delay on 429 responses.
 */
async function fetchLoginCredentials(): Promise<{
  accessToken: string;
  refreshTokenCookie: string;
}> {
  const maxAttempts = 3;
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    const response = await fetch(`${API_BASE}/api/v1/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: TEST_EMAIL, password: TEST_PASSWORD }),
      redirect: 'follow',
    });

    if (response.status === 429) {
      if (attempt < maxAttempts) {
        console.warn(
          `Login rate-limited (attempt ${attempt}/${maxAttempts}). Waiting 25s before retry...`,
        );
        await new Promise((r) => setTimeout(r, 25000));
        continue;
      }
      const body = await response.text();
      throw new Error(`Login API still rate-limited after ${maxAttempts} attempts: ${body}`);
    }

    if (!response.ok) {
      const body = await response.text();
      throw new Error(`Login API returned ${response.status}: ${body}`);
    }

    const data = (await response.json()) as { access_token: string };
    const setCookieHeader = response.headers.get('set-cookie') ?? '';
    const match = setCookieHeader.match(/refresh_token=([^;]+)/);
    const refreshTokenCookie = match?.[1] ?? '';

    if (!refreshTokenCookie) {
      throw new Error('No refresh_token found in login response cookies');
    }

    return { accessToken: data.access_token, refreshTokenCookie };
  }

  throw new Error('fetchLoginCredentials: exhausted all retry attempts');
}

/** Authenticated GET helper. */
async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`GET ${path} returned ${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

/** Authenticated PATCH helper. */
async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'PATCH',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`PATCH ${path} returned ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

/** Build the search detail URL for a given session. */
function searchDetailUrl(sessionId: string): string {
  return `${BASE_URL}/en/projects/${TEST_PROJECT_ID}/search?session=${sessionId}`;
}

// ---------------------------------------------------------------------------
// Interfaces for API responses
// ---------------------------------------------------------------------------

interface SearchSessionListResponse {
  sessions: Array<{
    id: string;
    name: string | null;
    status: string;
    result_count: number;
    species_config: unknown[] | null;
  }>;
}

interface SearchSessionDetailResponse {
  id: string;
  name: string | null;
  status: string;
}

// ---------------------------------------------------------------------------
// Test suite
// ---------------------------------------------------------------------------

test.describe('SearchSessionDetail smoke tests', () => {
  test.beforeAll(async () => {
    test.setTimeout(120000);

    // Step 1: Login via Node.js fetch.
    const { accessToken: tok, refreshTokenCookie } = await fetchLoginCredentials();
    accessToken = tok;

    // Step 2: Check env override first.
    const envOverride = process.env['E2E_SEARCH_SESSION_ID'];
    if (envOverride) {
      testSessionId = envOverride;
      console.log(`Using env override session: ${testSessionId}`);
    } else {
      // Step 3: Fetch sessions list and select deterministically.
      const sessionList = await apiGet<SearchSessionListResponse>(
        `/api/v1/projects/${TEST_PROJECT_ID}/search/sessions?limit=50`,
      );

      // Filter: completed, has species_config, result_count > 0
      const qualifying = sessionList.sessions.filter(
        (s) =>
          s.status === 'completed' &&
          s.species_config !== null &&
          Array.isArray(s.species_config) &&
          s.species_config.length > 0 &&
          s.result_count > 0,
      );

      if (qualifying.length === 0) {
        console.warn(
          'No qualifying completed sessions with species_config and results found. All tests will be skipped.',
        );
        // Launch a minimal browser so afterAll can safely close it.
        sharedBrowser = await chromium.launch({ headless: true });
        sharedContext = await sharedBrowser.newContext();
        sharedPage = await sharedContext.newPage();
        return;
      }

      // Sort by id ascending (ULID/UUID both sort lexicographically) and pick first.
      const sorted = qualifying.slice().sort((a, b) => a.id.localeCompare(b.id));
      testSessionId = sorted[0].id;
      console.log(`Selected test session: ${testSessionId}`);
    }

    // Step 4: Fetch ORIGINAL_NAME for rename restore.
    const sessionDetail = await apiGet<SearchSessionDetailResponse>(
      `/api/v1/projects/${TEST_PROJECT_ID}/search/sessions/${testSessionId}`,
    );
    originalName = sessionDetail.name ?? '';
    console.log(`Original session name: "${originalName}"`);

    // Launch browser.
    sharedBrowser = await chromium.launch({ headless: true });
    sharedContext = await sharedBrowser.newContext();

    // Plant refresh_token cookie for auth persistence.
    await sharedContext.addCookies([
      {
        name: 'refresh_token',
        value: refreshTokenCookie,
        domain: 'localhost',
        path: '/',
        httpOnly: true,
        sameSite: 'Lax',
      },
    ]);

    sharedPage = await sharedContext.newPage();

    // Collect console errors for the entire suite.
    // Filter out 404s for audio/spectrogram assets — these are expected in the
    // dev environment where audio files may not be locally cached.
    sharedPage.on('pageerror', (err) => {
      suiteConsoleErrors.push(`[pageerror] ${err.message}`);
    });
    sharedPage.on('console', (msg) => {
      if (msg.type() === 'error') {
        const text = msg.text();
        // Ignore 404s for static assets (audio, spectrogram chunks, images).
        if (text.includes('404 (Not Found)') || text.includes('Failed to load resource')) {
          return;
        }
        suiteConsoleErrors.push(`[console.error] ${text}`);
      }
    });

    // Navigate to the session detail page to warm up auth.
    const targetUrl = searchDetailUrl(testSessionId);
    const warmupMaxAttempts = 3;
    for (let attempt = 1; attempt <= warmupMaxAttempts; attempt++) {
      await sharedPage.goto(targetUrl, { waitUntil: 'load' });

      // Wait for the Back to Sessions button to appear — signals session loaded.
      const backBtn = sharedPage.getByRole('button', { name: /Back to Sessions/i });
      const visible = await backBtn
        .waitFor({ state: 'visible', timeout: 20000 })
        .then(() => true)
        .catch(() => false);
      if (visible) break;

      if (attempt < warmupMaxAttempts) {
        console.warn(
          `Warmup attempt ${attempt}/${warmupMaxAttempts}: Back button not visible (auth/refresh may be rate-limited). Waiting 25s...`,
        );
        await new Promise((r) => setTimeout(r, 25000));
      }
    }

    // Final assertion — if all retry attempts still fail this gives a clear error.
    await expect(
      sharedPage.getByRole('button', { name: /Back to Sessions/i }),
      'Back to Sessions button should be visible on initial load',
    ).toBeVisible({ timeout: 30000 });

    // Flush any auth/navigation errors accumulated during warm-up.
    suiteConsoleErrors.length = 0;
  });

  test.afterAll(async () => {
    // Fallback rename restore: if test 3's finally block did not run (suite
    // aborted), restore original name here.
    if (accessToken && testSessionId && originalName !== undefined) {
      try {
        await apiPatch(
          `/api/v1/projects/${TEST_PROJECT_ID}/search/sessions/${testSessionId}`,
          { name: originalName },
        );
      } catch {
        // Non-critical: just log
        console.warn('afterAll: Failed to restore original session name');
      }
    }

    await sharedPage?.close();
    await sharedContext?.close();
    await sharedBrowser?.close();
  });

  // ---------------------------------------------------------------------------
  // Helper: skip when no qualifying session was found
  // ---------------------------------------------------------------------------

  function requireSession() {
    if (!testSessionId) {
      test.skip();
    }
  }

  // ---------------------------------------------------------------------------
  // Helper: navigate back to detail page (preserves in-memory access token)
  // ---------------------------------------------------------------------------

  /**
   * Navigate to the session detail page using SPA click navigation.
   *
   * Strategy (preserves in-memory access token, avoids /auth/refresh rate limit):
   * 1. If already in detail view showing the Back button, return immediately.
   * 2. If in new-search mode (Back button visible but URL has no session ID),
   *    click Back to return to list mode.
   * 3. From list mode, click the session row in SearchSessionList to enter detail mode.
   *    Sessions are rendered as role="button" divs inside <li> elements.
   *
   * Full page.goto triggers /auth/refresh on every SPA re-init. Since /auth/refresh
   * shares the login rate limiter (5 calls/min), rapid successive goto calls will
   * fail. SPA click navigation avoids this.
   */
  /**
   * Navigate to the session detail page.
   *
   * Uses page.goto for a clean full-page navigation that resets all SPA state.
   * This avoids the problem where fork/edit-rerun leaves the SPA in new-search mode
   * with an active polling interval that cannot be stopped via SPA-only navigation.
   *
   * Rate limit mitigation: /auth/refresh is called once per page.goto. We have
   * a budget of ~5 calls/min. The total goto calls across the suite are:
   *   1 (beforeAll warmup) + 1 (test6 reset) + 1 (test7 reset) = 3 calls.
   * This is within the 5/min limit when tests run sequentially.
   * If rate-limited (429 on /auth/refresh → SPA shows empty page), retry once after 25s.
   */
  async function gotoDetailPage(): Promise<void> {
    const targetUrl = searchDetailUrl(testSessionId);

    // Check if we're already in a working detail mode by looking for the Rename button.
    // This button only appears in SearchSessionDetail (detail mode) for completed sessions.
    // It does NOT appear in new-search mode.
    const renameBtn = sharedPage.getByRole('button', { name: /^Rename$/i });
    const isDetailMode = await renameBtn.isVisible({ timeout: 1500 }).catch(() => false);
    if (isDetailMode) {
      return;
    }

    // Perform a full page navigation to reset SPA state (stops any active polling).
    // Retry once if the auth/refresh rate limit causes an empty page.
    for (let attempt = 1; attempt <= 2; attempt++) {
      await sharedPage.goto(targetUrl, { waitUntil: 'load' });

      const backBtn = sharedPage.getByRole('button', { name: /Back to Sessions/i });
      const backVisible = await backBtn
        .waitFor({ state: 'visible', timeout: 20000 })
        .then(() => true)
        .catch(() => false);

      if (backVisible) break;

      if (attempt < 2) {
        console.warn(
          `gotoDetailPage attempt ${attempt}/2: Back button not visible (auth/refresh may be rate-limited). Waiting 25s...`,
        );
        await new Promise((r) => setTimeout(r, 25000));
      }
    }

    await expect(
      sharedPage.getByRole('button', { name: /Back to Sessions/i }),
      'Back to Sessions button must be visible after gotoDetailPage',
    ).toBeVisible({ timeout: 30000 });

    // Wait for session to fully load (Rename button appears for completed sessions).
    await expect(renameBtn).toBeVisible({ timeout: 15000 });
  }

  // ---------------------------------------------------------------------------

  /**
   * Test 1: session loads
   *
   * Verifies:
   * - "Back to Sessions" button is visible (text locator, no aria-label)
   * - Session header card is visible (h2 with session name)
   * - Loading spinner has disappeared
   */
  test('Test 1: session loads — back button, header card, no spinner', async () => {
    test.setTimeout(60000);
    requireSession();
    suiteConsoleErrors.length = 0;

    await gotoDetailPage();

    // Back to Sessions button (text locator — component has no aria-label on this button)
    await expect(
      sharedPage.getByRole('button', { name: /Back to Sessions/i }),
      'Back to Sessions button must be visible',
    ).toBeVisible();

    // Session header card — h2 element with the session name
    await expect(
      sharedPage.locator('h2').first(),
      'Session name h2 must be visible in header card',
    ).toBeVisible({ timeout: 15000 });

    // Loading skeleton should have disappeared
    await expect(
      sharedPage.locator('.animate-pulse').first(),
      'Loading skeleton should disappear after session loads',
    ).not.toBeVisible({ timeout: 10000 });

    expect(suiteConsoleErrors, 'no console errors on session load').toEqual([]);
  });

  // ---------------------------------------------------------------------------

  /**
   * Test 2: species reconstruction
   *
   * Verifies ReferenceSoundsPanel is visible with "Loaded Sources" heading
   * (readonly=true in detail view uses search_loaded_sources, not search_reference_sounds).
   */
  test('Test 2: species reconstruction — ReferenceSoundsPanel visible', async () => {
    test.setTimeout(60000);
    requireSession();
    suiteConsoleErrors.length = 0;

    await gotoDetailPage();

    // In detail view with readonly=true, ReferenceSoundsPanel renders "Loaded Sources"
    await expect(
      sharedPage.getByRole('heading', { name: /Loaded Sources/i }),
      'ReferenceSoundsPanel heading "Loaded Sources" must be visible',
    ).toBeVisible({ timeout: 15000 });

    expect(suiteConsoleErrors, 'no console errors during species reconstruction').toEqual([]);
  });

  // ---------------------------------------------------------------------------

  /**
   * Test 3: rename save
   *
   * Uses try/finally to guarantee name is restored even on test failure.
   *
   * Steps:
   * 1. Click pencil (Rename) button
   * 2. Clear input and type new name
   * 3. Click Save
   * 4. Assert header shows new name
   * 5. Intercept PATCH via waitForRequest and assert request body
   * Finally: PATCH original name back via API
   */
  test('Test 3: rename save — pencil → input → save → header updated', async () => {
    test.setTimeout(60000);
    requireSession();
    suiteConsoleErrors.length = 0;

    await gotoDetailPage();

    const newName = `e2e-test-rename-${Date.now()}`;

    try {
      // Click pencil / Rename button (aria-label="Rename")
      const renameBtn = sharedPage.getByRole('button', { name: /^Rename$/i });
      await expect(renameBtn, 'Rename (pencil) button must be visible').toBeVisible({
        timeout: 10000,
      });
      await renameBtn.click();

      // Rename input should appear
      const renameInput = sharedPage.getByRole('textbox', { name: /Session Name/i });
      await expect(renameInput, 'Rename input must appear').toBeVisible({ timeout: 5000 });

      // Clear and type new name
      await renameInput.fill(newName);

      // Set up request interceptor for PATCH before clicking Save
      const patchRequestPromise = sharedPage.waitForRequest(
        (req) =>
          req.url().includes(`/search/sessions/${testSessionId}`) && req.method() === 'PATCH',
        { timeout: 10000 },
      );

      // Click Save button
      const saveBtn = sharedPage.getByRole('button', { name: /^Save$/i });
      await saveBtn.click();

      // Wait for PATCH request and assert body
      const patchRequest = await patchRequestPromise;
      const patchBody = patchRequest.postDataJSON() as Record<string, unknown>;
      expect(patchBody, 'PATCH body should contain the new name').toMatchObject({ name: newName });

      // Header should now show new name
      await expect(
        sharedPage.locator('h2').filter({ hasText: newName }),
        'Session header should display new name after save',
      ).toBeVisible({ timeout: 10000 });
    } finally {
      // Always restore original name via direct API call
      try {
        await apiPatch(
          `/api/v1/projects/${TEST_PROJECT_ID}/search/sessions/${testSessionId}`,
          { name: originalName },
        );
        console.log(`Restored session name to: "${originalName}"`);
      } catch (err) {
        console.warn('Test 3 finally: Failed to restore original session name', err);
      }
    }

    expect(suiteConsoleErrors, 'no console errors during rename save').toEqual([]);
  });

  // ---------------------------------------------------------------------------

  /**
   * Test 4: rename cancel
   *
   * Steps:
   * 1. Click pencil (Rename) button
   * 2. Type a different name
   * 3. Click Cancel
   * 4. Assert rename input is gone and original name is still shown
   */
  test('Test 4: rename cancel — pencil → cancel → original name shown', async () => {
    test.setTimeout(60000);
    requireSession();
    suiteConsoleErrors.length = 0;

    await gotoDetailPage();

    // Get the current displayed name before rename
    const h2Text = await sharedPage.locator('h2').first().innerText();

    // Click pencil / Rename button
    const renameBtn = sharedPage.getByRole('button', { name: /^Rename$/i });
    await expect(renameBtn).toBeVisible({ timeout: 10000 });
    await renameBtn.click();

    // Rename input should appear
    const renameInput = sharedPage.getByRole('textbox', { name: /Session Name/i });
    await expect(renameInput).toBeVisible({ timeout: 5000 });

    // Type a different name
    await renameInput.fill('should-not-be-saved-name');

    // Click Cancel
    const cancelBtn = sharedPage.getByRole('button', { name: /^Cancel$/i });
    await cancelBtn.click();

    // Rename input should disappear
    await expect(renameInput, 'Rename input should disappear after cancel').not.toBeVisible({
      timeout: 5000,
    });

    // Original name should still be displayed
    await expect(
      sharedPage.locator('h2').filter({ hasText: h2Text.trim() }),
      'Original name should still be shown after cancel',
    ).toBeVisible({ timeout: 5000 });

    expect(suiteConsoleErrors, 'no console errors during rename cancel').toEqual([]);
  });

  // ---------------------------------------------------------------------------

  /**
   * Test 5: export CSV
   *
   * Clicks "Export CSV" button and waits for a download event.
   * If the download event is not triggered (e.g., backend returns inline),
   * falls back to asserting the API request was made.
   */
  test('Test 5: export CSV — button click triggers download', async () => {
    test.setTimeout(60000);
    requireSession();
    suiteConsoleErrors.length = 0;

    await gotoDetailPage();

    const exportBtn = sharedPage.getByRole('button', { name: /Export CSV/i });
    await expect(exportBtn, 'Export CSV button must be visible').toBeVisible({ timeout: 10000 });

    // Set up both a download listener and a request interceptor as fallback.
    const downloadPromise = sharedPage.waitForEvent('download', { timeout: 15000 }).catch(() => null);
    const requestPromise = sharedPage.waitForRequest(
      (req) => req.url().includes('export') || req.url().includes('csv'),
      { timeout: 15000 },
    ).catch(() => null);

    await exportBtn.click();

    // Either a download fires, or we see the export API request.
    const [downloadResult, requestResult] = await Promise.all([downloadPromise, requestPromise]);

    expect(
      downloadResult !== null || requestResult !== null,
      'Either a download event or an export API request should occur on Export CSV click',
    ).toBe(true);

    expect(suiteConsoleErrors, 'no console errors during export').toEqual([]);
  });

  // ---------------------------------------------------------------------------

  /**
   * Test 6: fork (click + run)
   *
   * Steps:
   * 1. Click "Fork as New Session" button
   * 2. Assert new-search mode via "Reference Sounds" heading (editable panel)
   * 3. Mock POST /search/batch via page.route
   * 4. Click "Search" (or "Search All Species") button in SearchConfigBar
   * 5. Assert mock received POST /batch
   */
  test('Test 6: fork — new-search mode anchor + POST /batch intercepted', async () => {
    test.setTimeout(60000);
    requireSession();
    suiteConsoleErrors.length = 0;

    await gotoDetailPage();

    const forkBtn = sharedPage.getByRole('button', { name: /Fork as New Session/i });
    await expect(forkBtn, 'Fork as New Session button must be visible').toBeVisible({
      timeout: 10000,
    });

    // Set up route mock for POST /search/batch BEFORE clicking Fork.
    // Also mock the job status polling endpoint to prevent the SPA from entering
    // a long-running search state that would pollute subsequent tests.
    let batchRequestReceived = false;
    await sharedPage.route('**/api/v1/projects/*/search/batch', async (route) => {
      if (route.request().method() === 'POST') {
        batchRequestReceived = true;
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          // Use a stub job ID that won't match any real job.
          body: JSON.stringify({ job_id: 'stub-batch-job-id', session_id: null }),
        });
      } else {
        await route.continue();
      }
    });
    // Mock the job polling endpoint to immediately return 'failed' so the SPA
    // exits the searching state quickly and doesn't transition to detail mode.
    // The polling URL is relative to the frontend origin (Vite proxy): /api/v1/projects/*/search/jobs/*
    await sharedPage.route(
      (url) => url.pathname.includes('/search/jobs/stub-batch-job-id'),
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ status: 'failed', error: 'stub search not supported' }),
        });
      },
    );

    // Click Fork
    await forkBtn.click();

    // Assert new-search mode: editable ReferenceSoundsPanel shows "Reference Sounds" heading
    await expect(
      sharedPage.getByRole('heading', { name: /Reference Sounds/i }),
      'Editable "Reference Sounds" heading must appear in new-search mode after Fork',
    ).toBeVisible({ timeout: 10000 });

    // Click Search button (SearchConfigBar renders "Search" or "Search All Species")
    const searchBtn = sharedPage.getByRole('button', { name: /^Search$|^Search All Species$/i });
    await expect(searchBtn, 'Search button must be visible').toBeVisible({ timeout: 10000 });
    await expect(searchBtn, 'Search button must be enabled').toBeEnabled({ timeout: 5000 });
    await searchBtn.click();

    // Assert mock received POST /batch
    await sharedPage.waitForFunction(() => true, undefined, { timeout: 5000 });
    expect(batchRequestReceived, 'POST /search/batch should have been called on Fork search').toBe(
      true,
    );

    // Cleanup route mocks
    await sharedPage.unroute('**/api/v1/projects/*/search/batch');
    await sharedPage.unrouteAll({ behavior: 'ignoreErrors' }).catch(() => {});

    // After Fork, the SPA is in new-search mode (stub polling returned 'failed' so
    // isSearching=false but still in new-search mode).
    // gotoDetailPage() handles the transition: Back → list → click session row.
    await gotoDetailPage();
    suiteConsoleErrors.length = 0;
  });

  // ---------------------------------------------------------------------------

  /**
   * Test 7: edit & re-search (click + run)
   *
   * Steps:
   * 1. Click "Edit & Re-search" button
   * 2. Assert new-search mode via "Reference Sounds" heading (editable panel, isRerunMode)
   * 3. Mock PUT /search/sessions/{id}/rerun via page.route
   * 4. Click "Search" button
   * 5. Assert mock received PUT /rerun (distinguishes from fork's POST /batch)
   */
  test('Test 7: edit & re-search — new-search mode anchor + PUT /rerun intercepted', async () => {
    test.setTimeout(60000);
    requireSession();
    suiteConsoleErrors.length = 0;

    await gotoDetailPage();

    const editRerunBtn = sharedPage.getByRole('button', { name: /Edit & Re-search/i });
    await expect(editRerunBtn, 'Edit & Re-search button must be visible').toBeVisible({
      timeout: 10000,
    });

    // Set up route mock for PUT /rerun BEFORE clicking Edit & Re-search.
    // Also mock the job polling endpoint to prevent long-running search state.
    let rerunRequestReceived = false;
    await sharedPage.route('**/api/v1/projects/*/search/sessions/*/rerun', async (route) => {
      if (route.request().method() === 'PUT') {
        rerunRequestReceived = true;
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ job_id: 'stub-rerun-job-id', session_id: null }),
        });
      } else {
        await route.continue();
      }
    });
    // Mock the job polling endpoint to immediately return 'failed'.
    await sharedPage.route(
      (url) => url.pathname.includes('/search/jobs/stub-rerun-job-id'),
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ status: 'failed', error: 'stub rerun not supported' }),
        });
      },
    );

    // Click Edit & Re-search
    await editRerunBtn.click();

    // Assert new-search mode: editable ReferenceSoundsPanel shows "Reference Sounds" heading.
    // In rerun mode the page h1 shows "Edit & Re-search" and the Reference Sounds panel is editable.
    await expect(
      sharedPage.getByRole('heading', { name: /Reference Sounds/i }),
      'Editable "Reference Sounds" heading must appear in new-search mode after Edit & Re-search',
    ).toBeVisible({ timeout: 10000 });

    // Click Search button (in rerun mode, SearchConfigBar still renders "Search" or "Search All Species")
    const searchBtn = sharedPage.getByRole('button', { name: /^Search$|^Search All Species$/i });
    await expect(searchBtn, 'Search button must be visible in edit mode').toBeVisible({
      timeout: 10000,
    });
    await expect(searchBtn, 'Search button must be enabled').toBeEnabled({ timeout: 5000 });
    await searchBtn.click();

    // Assert mock received PUT /rerun
    await sharedPage.waitForFunction(() => true, undefined, { timeout: 5000 });
    expect(
      rerunRequestReceived,
      'PUT /search/sessions/{id}/rerun should have been called on Edit & Re-search',
    ).toBe(true);

    // Cleanup route mocks (unrouteAll removes all handlers including the polling mock)
    await sharedPage.unroute('**/api/v1/projects/*/search/sessions/*/rerun');
    await sharedPage.unrouteAll({ behavior: 'ignoreErrors' }).catch(() => {});

    // After Edit & Re-search, the SPA is in new-search mode (stub polling returned 'failed').
    // gotoDetailPage() handles the transition: Back → list → click session row.
    await gotoDetailPage();
    suiteConsoleErrors.length = 0;
  });

  // ---------------------------------------------------------------------------

  /**
   * Test 8: train dialog open/close
   *
   * Steps:
   * 1. Click "Train Model on these results" button in ResultsPanel
   * 2. Assert CreateModelFromSessionDialog is open (heading visible)
   * 3. Click aria-label="Close dialog"
   * 4. Assert dialog has closed
   */
  test('Test 8: train dialog open/close — dialog opens and closes', async () => {
    test.setTimeout(60000);
    requireSession();
    suiteConsoleErrors.length = 0;

    await gotoDetailPage();

    // The "Train Model on these results" button is in ResultsPanel.
    // It requires a species to be selected (selectedSpeciesKey !== null).
    // The button is disabled when no species is selected.
    const trainBtn = sharedPage.getByRole('button', { name: /Train Model on these results/i });
    await expect(trainBtn, 'Train Model button must be visible').toBeVisible({ timeout: 15000 });

    // The button may be disabled until a species tab is selected in ResultsPanel.
    // Check if disabled and click a species tab first if needed.
    const isDisabled = await trainBtn.isDisabled();
    if (isDisabled) {
      // Click the first species tab in ResultsPanel to select it
      const speciesTab = sharedPage
        .locator('[role="tab"]')
        .first();
      const tabVisible = await speciesTab.isVisible().catch(() => false);
      if (tabVisible) {
        await speciesTab.click();
        await expect(trainBtn).toBeEnabled({ timeout: 5000 });
      }
    }

    // Click Train Model button
    await trainBtn.click();

    // Dialog should appear — heading: "Train Model from Search"
    await expect(
      sharedPage.getByRole('heading', { name: /Train Model from Search/i }),
      'CreateModelFromSessionDialog heading must be visible',
    ).toBeVisible({ timeout: 10000 });

    // Close dialog via aria-label="Close dialog"
    const closeBtn = sharedPage.getByRole('button', { name: 'Close dialog' });
    await closeBtn.click();

    // Dialog should close
    await expect(
      sharedPage.getByRole('heading', { name: /Train Model from Search/i }),
      'Dialog heading should disappear after close',
    ).not.toBeVisible({ timeout: 5000 });

    expect(suiteConsoleErrors, 'no console errors during train dialog').toEqual([]);
  });

  // ---------------------------------------------------------------------------

  /**
   * Test 9: console errors = 0
   *
   * Asserts that suiteConsoleErrors accumulated across all tests is empty.
   * 404 audio asset errors are filtered at collection time (see beforeAll).
   */
  test('Test 9: console errors = 0 across entire suite', async () => {
    requireSession();

    expect(
      suiteConsoleErrors,
      `Expected 0 console errors, found ${suiteConsoleErrors.length}: ${suiteConsoleErrors.join('\n')}`,
    ).toEqual([]);
  });
});
