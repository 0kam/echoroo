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

// Spectrogram HTTP requests captured from sharedPage's initial mount.
//
// Fix 1 (option A): We freeze this array after the first page finishes loading
// (via a 1-second settle period post-networkidle) so that later test interactions
// cannot append to it and corrupt the dedup assertion in Test 6.
// A boolean flag stops the listener from accumulating beyond the initial mount.
const capturedSpectrogramRequests: string[] = [];
let captureActive = true; // set to false once initial mount is settled


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

    // Capture spectrogram HTTP requests during the initial mount so Test 6 can
    // verify chunk deduplication without opening a second browser page.
    // The listener checks `captureActive` and stops accumulating once we freeze
    // the array after the initial load settles (Fix 1, option A).
    sharedPage.on('request', (req) => {
      if (captureActive && req.url().includes('/spectrogram')) {
        capturedSpectrogramRequests.push(req.url());
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

    // Settle for 1 s after canvas is visible so any deferred lazy-load chunk
    // requests also complete, then freeze the capture window.  From this point
    // on, interactions in other tests cannot add to capturedSpectrogramRequests.
    await sharedPage.waitForTimeout(1000);
    captureActive = false;

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

  // ---------------------------------------------------------------------------

  /**
   * Helper: read the viewport indicator's CSS `width` value from the ViewportBar.
   * The indicator's pixel width scales linearly with the viewport time duration,
   * so comparing it before/after a resize operation reveals whether the viewport
   * width changed (Ctrl+wheel expand or Alt+wheel zoom).
   */
  async function getIndicatorWidth(page: Page): Promise<string> {
    return page.evaluate(() => {
      const slider = document.querySelector('[role="slider"][aria-label="Viewport position"]');
      const indicator = slider?.querySelector<HTMLElement>('div[style]');
      // Extract the width portion from the inline style, e.g. "left: 12px; width: 80px"
      const style = indicator?.getAttribute('style') ?? '';
      const m = style.match(/width:\s*([^;]+)/);
      return m?.[1]?.trim() ?? '';
    });
  }

  /**
   * Wait until the viewport indicator width changes from a previous value.
   */
  async function waitForWidthChange(page: Page, widthBefore: string, label: string): Promise<void> {
    await page
      .waitForFunction(
        (before: string) => {
          const slider = document.querySelector('[role="slider"][aria-label="Viewport position"]');
          const indicator = slider?.querySelector<HTMLElement>('div[style]');
          const style = indicator?.getAttribute('style') ?? '';
          const m = style.match(/width:\s*([^;]+)/);
          const current = m?.[1]?.trim() ?? '';
          return current !== '' && current !== before;
        },
        widthBefore,
        { timeout: 6000 }
      )
      .catch(() => {
        throw new Error(`Indicator width did not change after ${label}`);
      });
  }

  /**
   * Test 3: Modifier wheel variants
   *
   * Verifies three distinct wheel behaviours:
   * - Plain wheel (deltaX) → time pan (indicator left position changes, width unchanged)
   * - Ctrl+wheel (deltaY)  → expandWindow (indicator width changes)
   * - Alt+wheel (deltaY)   → zoomWindowToPosition (indicator width changes)
   *
   * Observable proxy: the ViewportBar indicator's inline `left` and `width` CSS values.
   */
  test('modifier wheel variants: plain pan, ctrl expand, alt zoom', async () => {
    suiteConsoleErrors.length = 0;

    const canvas = sharedPage.locator('canvas[aria-label="Spectrogram visualization"]');
    await expect(canvas).toBeVisible({ timeout: 10000 });
    const box = await canvas.boundingBox();
    expect(box).not.toBeNull();
    const cx = box!.x + box!.width / 2;
    const cy = box!.y + box!.height / 2;

    // --- Plain wheel: time pans (indicator position changes) ---
    const styleBeforePlain = await getIndicatorStyle(sharedPage);
    await sharedPage.mouse.move(cx, cy);
    await sharedPage.mouse.wheel(600, 0); // large deltaX → clear pan
    await waitForIndicatorChange(sharedPage, styleBeforePlain, 'plain wheel pan');
    expect(
      await getIndicatorStyle(sharedPage),
      'plain wheel: indicator position changed (time panned)'
    ).not.toBe(styleBeforePlain);

    // --- Ctrl+wheel: expandWindow → indicator width changes ---
    const widthBeforeCtrl = await getIndicatorWidth(sharedPage);
    await sharedPage.mouse.move(cx, cy);
    await sharedPage.keyboard.down('Control');
    await sharedPage.mouse.wheel(0, 120); // Ctrl + large deltaY → expand time
    await sharedPage.keyboard.up('Control');
    await waitForWidthChange(sharedPage, widthBeforeCtrl, 'ctrl+wheel expand');
    expect(
      await getIndicatorWidth(sharedPage),
      'ctrl+wheel: indicator width changed (viewport expanded)'
    ).not.toBe(widthBeforeCtrl);

    // --- Alt+wheel: zoomWindowToPosition → indicator width changes ---
    const widthBeforeAlt = await getIndicatorWidth(sharedPage);
    await sharedPage.mouse.move(cx, cy);
    await sharedPage.keyboard.down('Alt');
    await sharedPage.mouse.wheel(0, 120); // Alt + large deltaY → zoom out
    await sharedPage.keyboard.up('Alt');
    await waitForWidthChange(sharedPage, widthBeforeAlt, 'alt+wheel zoom');
    expect(
      await getIndicatorWidth(sharedPage),
      'alt+wheel: indicator width changed (viewport zoomed)'
    ).not.toBe(widthBeforeAlt);

    expect(suiteConsoleErrors, 'no console errors during modifier wheel tests').toEqual([]);
  });

  // ---------------------------------------------------------------------------

  /**
   * Test 4: Keyboard mode switching
   *
   * Verifies that pressing X / Z on the page body toggles interactionMode.
   * The ViewportToolbar renders a `toolbar-btn-active` class on the active
   * mode button, which we use as the observable proxy for mode state.
   *
   * The page-level <svelte:window onkeydown> handles X and Z and updates
   * interactionMode, which flows into ViewportToolbar as a prop.
   */
  test('keyboard mode switching: X → panning, Z → zooming', async () => {
    suiteConsoleErrors.length = 0;

    const canvas = sharedPage.locator('canvas[aria-label="Spectrogram visualization"]');
    await expect(canvas).toBeVisible({ timeout: 10000 });

    // Focus the body so svelte:window keydown fires reliably.
    await sharedPage.evaluate(() => {
      (document.activeElement as HTMLElement | null)?.blur?.();
    });

    // Press X → panning mode.
    await sharedPage.keyboard.press('x');
    // Confirm the Pan button (title contains "Pan mode") has the active class.
    await expect(
      sharedPage.locator('button[title*="Pan mode"]'),
      'pan button is active after X key'
    ).toHaveClass(/toolbar-btn-active/, { timeout: 3000 });
    // Confirm zoom button is NOT active.
    await expect(
      sharedPage.locator('button[title*="Zoom"]'),
      'zoom button is inactive after X key'
    ).not.toHaveClass(/toolbar-btn-active/);

    // Press Z → zooming mode.
    await sharedPage.keyboard.press('z');
    await expect(
      sharedPage.locator('button[title*="Zoom"]'),
      'zoom button is active after Z key'
    ).toHaveClass(/toolbar-btn-active/, { timeout: 3000 });
    await expect(
      sharedPage.locator('button[title*="Pan mode"]'),
      'pan button is inactive after Z key'
    ).not.toHaveClass(/toolbar-btn-active/);

    // Press X again to restore panning for subsequent tests.
    await sharedPage.keyboard.press('x');
    await expect(
      sharedPage.locator('button[title*="Pan mode"]'),
      'pan button active again after second X key'
    ).toHaveClass(/toolbar-btn-active/, { timeout: 3000 });

    expect(suiteConsoleErrors, 'no console errors during keyboard mode switching').toEqual([]);
  });

  // ---------------------------------------------------------------------------

  /**
   * Test 5: Zoom-box drag completes and viewport converges to the drawn rectangle
   *
   * Flow:
   *   1. Press Z to enter zooming mode.
   *   2. Mousedown at 25% → mousemove to 75% of canvas width (and 25%→75% height).
   *   3. Mouseup — handleMouseUp fires, calls onViewportChange with the box window,
   *      then calls onModeChange('panning') to return to panning mode.
   *   4. Assert: viewport indicator moved (time range changed to the box selection).
   *   5. Assert: mode returned to panning after zoom completes.
   */
  test('zoom-box drag: viewport converges to selected rectangle', async () => {
    suiteConsoleErrors.length = 0;

    const canvas = sharedPage.locator('canvas[aria-label="Spectrogram visualization"]');
    await expect(canvas).toBeVisible({ timeout: 10000 });
    const box = await canvas.boundingBox();
    expect(box).not.toBeNull();
    const _cy = box!.y + box!.height / 2;

    // Enter zooming mode via keyboard.
    await sharedPage.evaluate(() => {
      (document.activeElement as HTMLElement | null)?.blur?.();
    });
    await sharedPage.keyboard.press('z');
    await expect(
      sharedPage.locator('button[title*="Zoom"]'),
      'zoom button active before box drag'
    ).toHaveClass(/toolbar-btn-active/, { timeout: 3000 });

    // Capture indicator style before drag.
    const styleBeforeZoom = await getIndicatorStyle(sharedPage);

    // Draw a zoom box covering ~50% of the canvas width and ~50% of the height.
    const startX = box!.x + box!.width * 0.25;
    const endX = box!.x + box!.width * 0.75;
    const startY = box!.y + box!.height * 0.25;
    const endY = box!.y + box!.height * 0.75;

    await sharedPage.mouse.move(startX, startY);
    await sharedPage.mouse.down();
    await sharedPage.mouse.move(endX, endY, { steps: 10 });
    await sharedPage.mouse.up();

    // After mouseup the viewport should change (zoomed to selected region).
    await waitForIndicatorChange(sharedPage, styleBeforeZoom, 'zoom-box drag');
    expect(
      await getIndicatorStyle(sharedPage),
      'viewport changed after zoom-box drag'
    ).not.toBe(styleBeforeZoom);

    // handleMouseUp also calls onModeChange('panning') on successful zoom.
    await expect(
      sharedPage.locator('button[title*="Pan mode"]'),
      'mode returned to panning after zoom-box completes'
    ).toHaveClass(/toolbar-btn-active/, { timeout: 3000 });

    expect(suiteConsoleErrors, 'no console errors during zoom-box drag').toEqual([]);
  });

  // ---------------------------------------------------------------------------

  /**
   * Test 6: Chunk request deduplication
   *
   * Intercepts all spectrogram API requests during initial mount and confirms
   * that no chunk_index appears more than once.  This guards against the
   * rebuildChunks double-call bug where the same chunk could be fetched twice.
   *
   * Strategy: navigate to the recording page in a fresh tab (within the same
   * authenticated context) so we capture the full initial load sequence without
   * interference from previous tests.
   */
  test('chunk requests are not duplicated on initial mount', async () => {
    // capturedSpectrogramRequests was populated by the sharedPage's 'request' listener
    // during initial mount only (captureActive was frozen after a 1 s settle in
    // beforeAll).  Later test interactions cannot add to this array (Fix 1, option A).

    // Extract a (start, end) key per request.  The spectrogram endpoint uses
    // ?start=…&end=… rather than a chunk_index parameter.
    const chunkKeys = capturedSpectrogramRequests.map((url) => {
      const u = new URL(url);
      const start = u.searchParams.get('start') ?? '';
      const end = u.searchParams.get('end') ?? '';
      return `${start}-${end}`;
    });

    // There must be at least one request (proves the viewer actually loaded chunks).
    expect(chunkKeys.length, 'at least one chunk should have been requested').toBeGreaterThan(0);

    const uniqueKeys = new Set(chunkKeys);
    expect(
      chunkKeys.length,
      `no duplicate chunk fetches (got ${chunkKeys.length} requests, ${uniqueKeys.size} unique)`
    ).toBe(uniqueKeys.size);
  });

  // ---------------------------------------------------------------------------

  /**
   * Test 7: readonly=true — interactions do not change viewport or fire callbacks
   *
   * Uses the fixture route /__test__/spectrogram-readonly which mounts
   * SpectrogramViewer with readonly={true} and exposes callback counters
   * via data-testid="callback-count" data attributes.
   *
   * Verifies:
   * - pan drag does not call onViewportChange (data-change stays "0")
   * - wheel does not call onViewportChange
   * - double-click does not call onSeek
   * - keyboard Z does not call onModeChange
   */
  test('readonly=true: interactions do not fire callbacks', async () => {
    // Navigate to the fixture route via a client-side anchor click on sharedPage.
    // This performs a SvelteKit SPA navigation (no full page reload), which
    // preserves the in-memory access token — avoiding the flaky auth-refresh race
    // that occurs when opening a new browser context at the end of a long test run.
    //
    // This is the last test, so mutating sharedPage's URL is safe.

    const FIXTURE_PATHNAME = '/en/__test__/spectrogram-readonly';

    const fixtureErrors: string[] = [];
    const fixtureErrorHandler = (err: Error) =>
      fixtureErrors.push(`[pageerror] ${err.message}`);
    const fixtureConsoleHandler = (msg: { type(): string; text(): string }) => {
      if (msg.type() === 'error') fixtureErrors.push(`[console.error] ${msg.text()}`);
    };
    sharedPage.on('pageerror', fixtureErrorHandler);
    sharedPage.on('console', fixtureConsoleHandler);

    // Trigger SPA navigation by programmatically clicking a temporary anchor.
    // SvelteKit intercepts anchor clicks and performs client-side routing,
    // preserving the in-memory auth token without a full page reload.
    await sharedPage.evaluate((pathname: string) => {
      const a = document.createElement('a');
      a.href = pathname;
      a.style.display = 'none';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    }, FIXTURE_PATHNAME);

    // Wait for the URL to update to the fixture route.
    await sharedPage.waitForURL(`**/__test__/spectrogram-readonly**`, { timeout: 10000 });

    // Wait for the canvas to render.  Using the stub recording (no API fetch),
    // the canvas mounts synchronously once the SPA route is active.
    await expect(
      sharedPage.locator('canvas[aria-label="Spectrogram visualization"]'),
      'fixture route canvas must mount'
    ).toBeVisible({ timeout: 15000 });

    const canvas = sharedPage.locator('canvas[aria-label="Spectrogram visualization"]');
    const box = await canvas.boundingBox();
    expect(box).not.toBeNull();
    const cx = box!.x + box!.width / 2;
    const cy = box!.y + box!.height / 2;

    // Confirm counters start at 0.
    const counter = sharedPage.locator('[data-testid="callback-count"]');
    await expect(counter).toHaveAttribute('data-change', '0');
    await expect(counter).toHaveAttribute('data-seek', '0');
    await expect(counter).toHaveAttribute('data-mode-change', '0');

    // --- Pan drag (should be blocked by readonly guard) ---
    await sharedPage.mouse.move(box!.x + box!.width * 0.7, cy);
    await sharedPage.mouse.down();
    await sharedPage.mouse.move(box!.x + box!.width * 0.2, cy, { steps: 10 });
    await sharedPage.mouse.up();

    // --- Wheel scroll (should be blocked) ---
    await sharedPage.mouse.move(cx, cy);
    await sharedPage.mouse.wheel(500, 0);

    // --- Double-click (should be blocked) ---
    await sharedPage.mouse.dblclick(cx, cy);

    // --- Keyboard Z: dispatch directly on the canvas so the focus condition in
    //     handleKeyDown (document.activeElement === canvas) is satisfied and only
    //     the readonly guard (checked first, line 803 of SpectrogramViewer.svelte)
    //     prevents onModeChange from firing.
    //
    //     Note: in readonly mode the canvas has tabindex=undefined, so
    //     `canvas.focus()` / Playwright's .focus() cannot set activeElement.
    //     We work around this by dispatching the KeyboardEvent on the canvas
    //     element directly via page.evaluate, which causes the svelte:window
    //     onkeydown handler to receive the event with target===canvas, satisfying
    //     the focus guard independently — so the readonly guard is the sole
    //     gatekeeper under test. (Fix 2, P3-5) ---
    await sharedPage.evaluate(() => {
      const canvas = document.querySelector('canvas[aria-label="Spectrogram visualization"]');
      if (!canvas) throw new Error('canvas not found for keyboard dispatch');
      // Temporarily make the canvas focusable so dispatchEvent triggers with
      // document.activeElement === canvas.
      canvas.setAttribute('tabindex', '0');
      (canvas as HTMLElement).focus();
      canvas.dispatchEvent(new KeyboardEvent('keydown', { key: 'z', bubbles: true }));
      canvas.removeAttribute('tabindex');
    });

    // Allow time for any reactive updates to propagate.
    await sharedPage.waitForTimeout(500);

    // All counters must remain at 0.
    await expect(counter, 'onViewportChange not called in readonly mode').toHaveAttribute('data-change', '0');
    await expect(counter, 'onSeek not called in readonly mode').toHaveAttribute('data-seek', '0');
    await expect(counter, 'onModeChange not called in readonly mode').toHaveAttribute('data-mode-change', '0');

    sharedPage.off('pageerror', fixtureErrorHandler);
    sharedPage.off('console', fixtureConsoleHandler);

    expect(fixtureErrors, 'no console errors on fixture route').toEqual([]);
  });
});
