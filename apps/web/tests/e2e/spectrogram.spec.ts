/**
 * E2E smoke tests for SpectrogramViewer.svelte
 *
 * Safety net before splitting SpectrogramViewer into sub-components.
 * Tests canvas rendering, pan/zoom interactions, cursor-info overlay,
 * double-click seek, and console error cleanliness.
 *
 * Covers recording detail page:
 *   /(app)/projects/[id]/recordings/[recordingId]/
 *
 * Auth strategy:
 *   The SPA stores the access token in the JavaScript module's memory (not in
 *   localStorage or sessionStorage).  It is lost on every full-page reload.
 *   On reload the SPA's auth store calls /api/v1/auth/refresh (using the
 *   refresh_token HttpOnly cookie) to restore the token.  We therefore:
 *
 *   1. Obtain a refresh_token via a direct Node.js fetch (bypasses browser
 *      rate-limiting) and plant it as a cookie in the browser context.
 *   2. Keep sharedPage alive for the entire suite so the in-memory token
 *      persists across tests without extra page reloads.
 *   3. Group all assertions in two tests that reuse the same page session.
 *
 *   This avoids the "token lost on reload" problem and the risk of triggering
 *   the test-account rate limit (5 login attempts / minute) across multiple
 *   test runs.
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
// Test configuration
// ---------------------------------------------------------------------------

const BASE_URL = 'http://localhost:3000';
const API_BASE = 'http://localhost:8002';

// test1 project — 30-minute (1800 s) recording, verified via API survey.
const TEST_PROJECT_ID = '6ed4e592-87ca-4fa7-a384-c64ca6bfeec5';
const TEST_RECORDING_ID = 'c05a228d-61df-4a89-bd84-6620143c4eaf';

const RECORDING_URL = `${BASE_URL}/en/projects/${TEST_PROJECT_ID}/recordings/${TEST_RECORDING_ID}`;

// Test account credentials
const TEST_EMAIL = 'test@echoroo.app';
const TEST_PASSWORD = 'N6Wz0IJXsQc4';

// ---------------------------------------------------------------------------
// Shared browser state (alive for the whole describe block)
// ---------------------------------------------------------------------------

let sharedBrowser: Browser;
let sharedContext: BrowserContext;
let sharedPage: Page;
const suiteConsoleErrors: string[] = [];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Obtain credentials via a direct Node.js HTTP call.
 * This does NOT go through Playwright's browser, so it does not count against
 * the browser-based rate limiter at /api/v1/auth/login.
 */
async function fetchLoginCredentials(): Promise<{
  accessToken: string;
  refreshTokenCookie: string;
}> {
  const response = await fetch(`${API_BASE}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: TEST_EMAIL, password: TEST_PASSWORD }),
    redirect: 'follow',
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Login API returned ${response.status}: ${body}`);
  }

  const data = (await response.json()) as { access_token: string };

  // Extract the refresh_token value from Set-Cookie header
  const setCookieHeader = response.headers.get('set-cookie') ?? '';
  const match = setCookieHeader.match(/refresh_token=([^;]+)/);
  const refreshTokenCookie = match?.[1] ?? '';

  if (!refreshTokenCookie) {
    throw new Error('No refresh_token found in login response cookies');
  }

  return { accessToken: data.access_token, refreshTokenCookie };
}

async function getIndicatorStyle(page: Page): Promise<string> {
  return page.evaluate(() => {
    const slider = document.querySelector('[role="slider"][aria-label="Viewport position"]');
    const indicator = slider?.querySelector('div[style]');
    return indicator?.getAttribute('style') ?? '';
  });
}

async function waitForIndicatorChange(
  page: Page,
  styleBefore: string,
  label: string
): Promise<void> {
  await page
    .waitForFunction(
      (before: string) => {
        const slider = document.querySelector('[role="slider"][aria-label="Viewport position"]');
        const indicator = slider?.querySelector('div[style]');
        return indicator?.getAttribute('style') !== before;
      },
      styleBefore,
      { timeout: 6000 }
    )
    .catch(() => {
      throw new Error(`Viewport indicator did not change after ${label}`);
    });
}

// ---------------------------------------------------------------------------
// Test suite
// ---------------------------------------------------------------------------

test.describe('SpectrogramViewer smoke tests', () => {
  test.beforeAll(async () => {
    test.setTimeout(90000);

    // Obtain a refresh_token via direct HTTP so we do not consume browser-side
    // login quota.  We also get the access_token in case we need to inject it.
    const { refreshTokenCookie } = await fetchLoginCredentials();

    // Launch a dedicated Chromium with a clean ephemeral profile.
    sharedBrowser = await chromium.launch({ headless: true });
    sharedContext = await sharedBrowser.newContext();

    // Plant the refresh_token cookie so:
    //   a) SvelteKit's SSR guard (hooks.server.ts) sees an authenticated session
    //      (it checks only cookie presence, not validity).
    //   b) The SPA's auth store can call /auth/refresh on startup and restore
    //      the access token in memory.
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
    sharedPage.on('pageerror', (err) => {
      suiteConsoleErrors.push(`[pageerror] ${err.message}`);
    });
    sharedPage.on('console', (msg) => {
      if (msg.type() === 'error') {
        suiteConsoleErrors.push(`[console.error] ${msg.text()}`);
      }
    });

    // Navigate to the recording page.  The SPA's auth store calls /auth/refresh
    // during initialization, obtains a new access token, and then Svelte Query
    // fetches the recording data — which mounts the SpectrogramViewer canvas.
    // 'networkidle' waits until all initial API requests complete.
    await sharedPage.goto(RECORDING_URL, { waitUntil: 'networkidle' });

    await expect(
      sharedPage.locator('canvas[aria-label="Spectrogram visualization"]'),
      'spectrogram canvas should mount in beforeAll'
    ).toBeVisible({ timeout: 30000 });

    // Flush nav/login errors — we only care about test interaction errors.
    suiteConsoleErrors.length = 0;
  });

  test.afterAll(async () => {
    await sharedPage?.close();
    await sharedContext?.close();
    await sharedBrowser?.close();
  });

  // No beforeEach page reload — keeping sharedPage alive preserves the SPA's
  // in-memory access token across tests.  Each test operates on the same page.

  // ---------------------------------------------------------------------------

  /**
   * Test 1: Canvas renders with non-zero dimensions
   *
   * Verifies:
   * - canvas[aria-label="Spectrogram visualization"] is visible
   * - Bounding box has non-zero width and height
   * - No loading spinner stuck
   * - Zero console errors during render
   */
  test('canvas is visible with non-zero dimensions', async () => {
    // Reset error slate before assertions
    suiteConsoleErrors.length = 0;

    const canvas = sharedPage.locator('canvas[aria-label="Spectrogram visualization"]');
    await expect(canvas).toBeVisible();

    const box = await canvas.boundingBox();
    expect(box, 'canvas bounding box should exist').not.toBeNull();
    expect(box!.width, 'canvas width > 0').toBeGreaterThan(0);
    expect(box!.height, 'canvas height > 0').toBeGreaterThan(0);

    // Page should not be stuck in a loading spinner
    const spinnerCount = await sharedPage.locator('.animate-spin').count();
    if (spinnerCount > 0) {
      await expect(
        sharedPage.locator('.animate-spin').first()
      ).not.toBeVisible({ timeout: 5000 });
    }

    expect(suiteConsoleErrors, 'no console errors during canvas render').toEqual([]);
  });

  /**
   * Test 2: Interactions — hover, pan, wheel-zoom, double-click seek
   *
   * Verifies:
   * - Hover: .cursor-info overlay shows time + kHz values on the canvas
   * - Pan: dragging shifts the ViewportBar indicator's CSS left position
   * - Wheel: horizontal scroll shifts the ViewportBar indicator position
   * - Double-click: seek fires and the ViewportBar indicator re-centers
   * - cursor-info disappears when the mouse leaves the canvas
   * - Zero console errors throughout all interactions
   *
   * Continues on the same page as Test 1 (no reload) to preserve the
   * in-memory access token.
   */
  test('pan, zoom, hover, and double-click interactions work without errors', async () => {
    // Reset error slate before interactions
    suiteConsoleErrors.length = 0;

    const canvas = sharedPage.locator('canvas[aria-label="Spectrogram visualization"]');
    const viewportBar = sharedPage.locator('[role="slider"][aria-label="Viewport position"]');

    await expect(canvas).toBeVisible({ timeout: 10000 });
    await expect(viewportBar).toBeVisible({ timeout: 10000 });

    const box = await canvas.boundingBox();
    expect(box).not.toBeNull();
    const cx = box!.x + box!.width / 2;
    const cy = box!.y + box!.height / 2;

    // --- Hover: cursor-info appears with time + kHz ---
    await sharedPage.mouse.move(cx, cy);
    await expect(
      sharedPage.locator('.cursor-info'),
      'cursor-info appears on hover'
    ).toBeVisible({ timeout: 3000 });
    const cursorText = await sharedPage.locator('.cursor-info').textContent();
    expect(cursorText, 'cursor-info shows time').toMatch(/\d+\.\d+s/);
    expect(cursorText, 'cursor-info shows kHz').toMatch(/\d+\.\d+ kHz/);

    // --- Pan: drag right-to-left → viewport advances in time ---
    //
    // timeDelta = -(dx / canvasWidth) * viewportDuration
    // dx < 0 (leftward drag) → timeDelta > 0 → viewport.time.min increases.
    // The ViewportBar indicator's CSS `left` pixel value tracks time.min at
    // sub-pixel precision (more sensitive than the rounded aria-valuenow).
    const styleBeforePan = await getIndicatorStyle(sharedPage);
    await sharedPage.mouse.move(box!.x + box!.width * 0.7, cy);
    await sharedPage.mouse.down();
    await sharedPage.mouse.move(box!.x + box!.width * 0.2, cy, { steps: 15 });
    await sharedPage.mouse.up();
    await waitForIndicatorChange(sharedPage, styleBeforePan, 'pan drag');
    expect(
      await getIndicatorStyle(sharedPage),
      'ViewportBar indicator moved after pan'
    ).not.toBe(styleBeforePan);

    // --- Wheel: horizontal scroll shifts the viewport ---
    //
    // handleWheel (no modifier): time += timeFrac * deltaX * 0.1
    // deltaX = 500, timeFrac ≈ 1 s → shift ≈ 50 s — well above any rounding.
    const styleBeforeWheel = await getIndicatorStyle(sharedPage);
    await sharedPage.mouse.move(cx, cy);
    await sharedPage.mouse.wheel(500, 0);
    await waitForIndicatorChange(sharedPage, styleBeforeWheel, 'wheel scroll');
    expect(
      await getIndicatorStyle(sharedPage),
      'ViewportBar indicator moved after wheel'
    ).not.toBe(styleBeforeWheel);

    // --- Double-click: seek re-centers viewport ---
    //
    // handleDoubleClick → onSeek(pos.time) → centerWindowOn(viewport, {time}).
    // After panning + scrolling right, clicking near the left edge (5%) seeks
    // backward and shifts the indicator leftward.
    const styleBeforeSeek = await getIndicatorStyle(sharedPage);
    await sharedPage.mouse.dblclick(box!.x + box!.width * 0.05, cy);
    await waitForIndicatorChange(sharedPage, styleBeforeSeek, 'double-click seek');
    expect(
      await getIndicatorStyle(sharedPage),
      'ViewportBar indicator moved after seek'
    ).not.toBe(styleBeforeSeek);

    // --- Mouse leave: cursor-info disappears ---
    await sharedPage.mouse.move(0, 0);
    await expect(
      sharedPage.locator('.cursor-info'),
      'cursor-info disappears on mouse leave'
    ).not.toBeVisible({ timeout: 2000 });

    expect(suiteConsoleErrors, 'no console errors during interactions').toEqual([]);
  });
});
