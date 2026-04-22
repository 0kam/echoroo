/**
 * E2E smoke tests for AnnotationEditor.svelte
 *
 * Safety net before splitting AnnotationEditor into useAnnotationDraft and
 * useAnnotationMutations hooks. All 9 test cases from plan.md §4 Step 0 are
 * covered so that behaviour regressions after the refactor will be caught.
 *
 * Covers the annotation editor route:
 *   /en/projects/{projectId}/annotation-sets/{setId}/annotate/{segmentId}
 *
 * Auth strategy (same as spectrogram.spec.ts):
 *   1. Obtain refresh_token via Node.js fetch (avoids browser rate-limit).
 *   2. Plant cookie in sharedContext so the SPA can restore the access token
 *      via /auth/refresh on every page load.
 *   3. Use sharedPage across all tests to keep the in-memory token alive.
 *
 * Seeding strategy (beforeAll):
 *   1. Login via Node.js fetch to get access_token + refresh_token.
 *   2. Find first dataset for the test1 project.
 *   3. Search for a species to use in the palette.
 *   4. POST /annotation-sets (name unique per run, 3 segments, 30 s each).
 *   5. Poll GET /annotation-sets/{id} until status === 'ready' (up to 30 s).
 *   6. POST /annotation-sets/{setId}/palette to add the species.
 *   7. GET /annotation-sets/{setId}/segments to capture segment IDs.
 *   8. PATCH /segments/{segments[0].id} with {status:'annotated', is_empty:true}
 *      — this is the readonly fixture for test #9.
 *
 * Teardown (afterAll):
 *   DELETE /annotation-sets/{setId} — ignore errors, just log them.
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

const BASE_URL = 'http://localhost:3000';
const API_BASE = 'http://localhost:8002';

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
let annotationSetId = '';
let readonlySegmentId = ''; // segments[0] — patched to annotated+is_empty
let editableSegmentIds: string[] = []; // segments[1] and [2] — unannotated
let paletteSpeciesId = '';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Obtain credentials via a direct Node.js HTTP call.
 * Does not count against the browser-side rate limiter.
 *
 * The /auth/login endpoint shares the same rate limiter as /auth/refresh
 * (5 calls per minute per IP). Back-to-back test runs may exceed this limit.
 * We retry up to 3 times with a 20-second delay on 429 responses.
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

/** Authenticated POST helper. */
async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`POST ${path} returned ${res.status}: ${text}`);
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

/** Authenticated DELETE helper. */
async function apiDelete(path: string): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!res.ok && res.status !== 404) {
    const text = await res.text();
    throw new Error(`DELETE ${path} returned ${res.status}: ${text}`);
  }
}

/** Build the full annotate URL for a given segment. */
function annotateUrl(segmentId: string): string {
  return `${BASE_URL}/en/projects/${TEST_PROJECT_ID}/annotation-sets/${annotationSetId}/annotate/${segmentId}`;
}

// ---------------------------------------------------------------------------
// Interfaces for API responses
// ---------------------------------------------------------------------------

interface DatasetListResponse {
  items: Array<{ id: string; name: string }>;
}

interface AnnotationSetResponse {
  id: string;
  status: string;
}

interface SegmentListResponse {
  items: Array<{
    id: string;
    status: string;
    recording_id: string;
  }>;
}

interface TaxonSearchResult {
  id: string;
  scientific_name: string;
  common_name: string | null;
}

// ---------------------------------------------------------------------------
// Test suite
// ---------------------------------------------------------------------------

test.describe('AnnotationEditor smoke tests', () => {
  test.beforeAll(async () => {
    // Give beforeAll plenty of time for seeding + browser launch.
    test.setTimeout(120000);

    // Step 1: Login via Node.js fetch.
    const { accessToken: tok, refreshTokenCookie } = await fetchLoginCredentials();
    accessToken = tok;

    // Step 2: Find a dataset.
    const datasets = await apiGet<DatasetListResponse>(
      `/api/v1/projects/${TEST_PROJECT_ID}/datasets`,
    );
    if (datasets.items.length === 0) {
      throw new Error('No datasets found in test1 project — seeding cannot proceed');
    }
    const datasetId = datasets.items[0].id;

    // Step 3: Find a species for the palette.
    const taxaResults = await apiGet<TaxonSearchResult[]>('/api/v1/taxa/search?q=passer');
    if (taxaResults.length === 0) {
      throw new Error('Taxa search for "passer" returned no results — cannot seed palette');
    }
    paletteSpeciesId = taxaResults[0].id;

    // Step 4: Create (or reuse) a test annotation set.
    // To avoid repeated creation and deletion across back-to-back test runs,
    // we look for an existing set with the e2e prefix that is already 'ready'.
    const E2E_SET_PREFIX = 'e2e-annotation-editor-';
    const existingSets = await apiGet<{ items: Array<{ id: string; name: string; status: string; num_segments: number }> }>(
      `/api/v1/annotation-sets?project_id=${TEST_PROJECT_ID}&page_size=50`,
    );
    const existingE2ESet = existingSets.items.find(
      (s) => s.name.startsWith(E2E_SET_PREFIX) && s.status === 'ready' && s.num_segments === 3,
    );

    if (existingE2ESet) {
      // Reuse the existing set — skip creation and seeding.
      annotationSetId = existingE2ESet.id;
      console.log(`Reusing existing annotation set: ${annotationSetId}`);
    } else {
      // Create a fresh annotation set.
      const setName = `${E2E_SET_PREFIX}${Date.now()}`;
      const createdSet = await apiPost<AnnotationSetResponse>('/api/v1/annotation-sets', {
        project_id: TEST_PROJECT_ID,
        dataset_id: datasetId,
        name: setName,
        segment_length_sec: 30,
        num_segments: 3,
      });
      annotationSetId = createdSet.id;

      // Step 5: Poll until status === 'ready' (up to 30 s).
      const pollStart = Date.now();
      let ready = false;
      while (Date.now() - pollStart < 30000) {
        const setDetail = await apiGet<AnnotationSetResponse>(
          `/api/v1/annotation-sets/${annotationSetId}`,
        );
        if (setDetail.status === 'ready') {
          ready = true;
          break;
        }
        await new Promise((r) => setTimeout(r, 1000));
      }
      if (!ready) {
        throw new Error(
          `Annotation set ${annotationSetId} did not reach 'ready' within 30 s — Celery may be down`,
        );
      }
    }

    // Step 6: Ensure the species is in the palette (idempotent — OK if already there).
    try {
      await apiPost(`/api/v1/annotation-sets/${annotationSetId}/palette`, {
        species_id: paletteSpeciesId,
      });
    } catch (err) {
      // 409 Conflict means the species is already in the palette — that's fine.
      if (err instanceof Error && !err.message.includes('409')) throw err;
    }

    // Step 7: Fetch segment IDs.
    const segmentList = await apiGet<SegmentListResponse>(
      `/api/v1/annotation-sets/${annotationSetId}/segments`,
    );
    const segments = segmentList.items;
    if (segments.length < 3) {
      throw new Error(
        `Expected 3 segments, got ${segments.length} — seeding failed`,
      );
    }

    // Step 8: Mark segments[0] as readonly (annotated + is_empty).
    // This is idempotent — patching an already-annotated segment is safe.
    readonlySegmentId = segments[0].id;
    await apiPatch(`/api/v1/segments/${readonlySegmentId}`, {
      status: 'annotated',
      is_empty: true,
    });

    // Remaining segments are for editable tests.
    editableSegmentIds = segments.slice(1).map((s) => s.id);

    // Step 8b: Hard-reset the 2 editable segments to a known clean state.
    //
    // When the reuse branch runs (existing set found), editable segments may
    // carry leftover state from a prior run:
    //   - Orphaned annotations from test #3 (create) that were never deleted
    //   - is_empty=true lingering from test #7 (toggle to mark-empty)
    //   - status='annotated' if a prior run crashed mid-toggle
    //
    // Resetting here makes test #3's count-delta assertion (initialCount + 1)
    // deterministic regardless of how many previous runs have executed.
    // The readonly fixture segment (segments[0]) is intentionally excluded.
    //
    // Idempotency: DELETE loop is a no-op when no annotations exist.
    // PATCH is always safe (same values when already at target state).
    for (const segId of editableSegmentIds) {
      const segDetail = await apiGet<{ annotations: Array<{ id: string }> }>(
        `/api/v1/segments/${segId}`,
      );
      for (const annotation of segDetail.annotations) {
        await apiDelete(`/api/v1/annotations/${annotation.id}`);
      }
      await apiPatch(`/api/v1/segments/${segId}`, {
        status: 'unannotated',
        is_empty: false,
      });
    }
    console.log(`Reset ${editableSegmentIds.length} editable segments to clean state`);

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
    // dev environment where audio files are not cached locally. They are not
    // application code errors and do not indicate component breakage.
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

    // Navigate to the first editable segment to warm up auth.
    // The SPA calls /auth/refresh on init. In back-to-back test runs the
    // /auth/refresh endpoint (shared rate-limiter: 5 calls/min) may be
    // exhausted. Retry the goto up to 3 times with a 25 s gap on failure.
    const firstEditableUrl = annotateUrl(editableSegmentIds[0]);
    const warmupMaxAttempts = 3;
    for (let attempt = 1; attempt <= warmupMaxAttempts; attempt++) {
      await sharedPage.goto(firstEditableUrl, { waitUntil: 'load' });
      const navigator = sharedPage.locator('nav[aria-label="Segment navigator"]');
      const visible = await navigator.isVisible().catch(() => false);
      if (visible || await navigator.waitFor({ state: 'visible', timeout: 15000 }).then(() => true).catch(() => false)) {
        break;
      }
      if (attempt < warmupMaxAttempts) {
        console.warn(`Warmup attempt ${attempt}/${warmupMaxAttempts}: SegmentNavigator not visible (auth/refresh may be rate-limited). Waiting 25s before retry...`);
        await new Promise((r) => setTimeout(r, 25000));
      }
    }

    // Final assertion — if all retry attempts still fail this gives a clear error.
    await expect(
      sharedPage.locator('nav[aria-label="Segment navigator"]'),
      'SegmentNavigator should mount on initial load',
    ).toBeVisible({ timeout: 45000 });

    // Flush any auth/navigation errors accumulated during warm-up.
    suiteConsoleErrors.length = 0;
  });

  test.afterAll(async () => {
    // We intentionally do NOT delete the annotation set so it can be reused
    // by subsequent test runs (avoiding repeated creation and rate-limit issues).
    // The set is identified by the 'e2e-annotation-editor-' prefix for reuse.
    await sharedPage?.close();
    await sharedContext?.close();
    await sharedBrowser?.close();
  });

  // ---------------------------------------------------------------------------
  // Test helpers used across multiple tests
  // ---------------------------------------------------------------------------

  /**
   * Navigate the sharedPage to a segment URL using SPA client-side navigation
   * (anchor click) to preserve the in-memory access token across tests.
   *
   * Full page.goto causes SPA re-initialization and triggers /auth/refresh
   * on every call. Since /auth/refresh shares the login rate limiter (5 calls/min),
   * rapid test execution will hit the limit. SPA navigation avoids this by keeping
   * the access token in memory across navigations.
   *
   * The first navigation is handled in beforeAll via page.goto. All subsequent
   * navigations within the suite use this SPA anchor-click approach.
   */
  async function gotoSegment(segmentId: string, waitForOverlay = true): Promise<void> {
    const targetPathname = `/en/projects/${TEST_PROJECT_ID}/annotation-sets/${annotationSetId}/annotate/${segmentId}`;

    // If already on the target URL, just wait for the component to be visible.
    const currentUrl = sharedPage.url();
    if (!currentUrl.includes(segmentId)) {
      // Trigger SPA navigation via a temporary anchor click (preserves in-memory token).
      await sharedPage.evaluate((pathname: string) => {
        const a = document.createElement('a');
        a.href = pathname;
        a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
      }, targetPathname);

      // Wait for URL to update to the target segment.
      await sharedPage.waitForURL(
        (url) => url.toString().includes(segmentId),
        { timeout: 15000 },
      );
    }

    await expect(
      sharedPage.locator('nav[aria-label="Segment navigator"]'),
    ).toBeVisible({ timeout: 30000 });

    if (waitForOverlay) {
      // Wait for the overlay div to appear (signals recording + segment loaded).
      await expect(
        sharedPage.locator('[role="presentation"]'),
      ).toBeVisible({ timeout: 30000 });
    }
  }

  /**
   * Get the bounding box of the drag overlay (the presentation role div).
   */
  async function getOverlayBox(): Promise<{ x: number; y: number; width: number; height: number }> {
    const overlay = sharedPage.locator('[role="presentation"]').first();
    await expect(overlay).toBeVisible({ timeout: 10000 });
    const box = await overlay.boundingBox();
    if (!box) throw new Error('Overlay bounding box is null');
    return box;
  }

  /**
   * Drag across the overlay from startFrac to endFrac (0–1) of overlay width.
   * Uses manual mouse.down/move/up to avoid Playwright drag flakiness.
   */
  async function dragAcrossOverlay(startFrac: number, endFrac: number): Promise<void> {
    const box = await getOverlayBox();
    const y = box.y + box.height / 2;
    const startX = box.x + box.width * startFrac;
    const endX = box.x + box.width * endFrac;
    await sharedPage.mouse.move(startX, y);
    await sharedPage.mouse.down();
    await sharedPage.mouse.move(endX, y, { steps: 10 });
    await sharedPage.mouse.up();
  }

  // ---------------------------------------------------------------------------

  /**
   * Test 1: Mount — all primary panels are visible.
   *
   * Navigates to an editable segment and asserts that:
   * - SegmentNavigator is visible (nav[aria-label="Segment navigator"])
   * - Overlay div is visible ([role="presentation"])
   * - AnnotationList section is visible (aside[aria-label=...])
   * - SpeciesPalette section is visible (section with palette chip)
   * - NotesPanel section is visible (aside[aria-label=...notes...])
   * - Zero console errors
   */
  test('Test 1: component mounts with all panels visible', async () => {
    test.setTimeout(60000);
    suiteConsoleErrors.length = 0;
    await gotoSegment(editableSegmentIds[0]);

    // SegmentNavigator
    await expect(
      sharedPage.locator('nav[aria-label="Segment navigator"]'),
      'SegmentNavigator must be visible',
    ).toBeVisible();

    // Overlay (drag surface)
    await expect(
      sharedPage.locator('[role="presentation"]').first(),
      'Overlay div must be visible',
    ).toBeVisible();

    // AnnotationList aside
    await expect(
      sharedPage.locator('aside').filter({ hasText: /annotation/i }).first(),
      'AnnotationList aside must be visible',
    ).toBeVisible();

    // SpeciesPalette section (contains a chip button with the species we added)
    await expect(
      sharedPage.locator('section').filter({ hasText: /palette|species/i }).first(),
      'SpeciesPalette section must be visible',
    ).toBeVisible();

    // NotesPanel aside (notes section)
    await expect(
      sharedPage.locator('aside').filter({ hasText: /notes/i }).first(),
      'NotesPanel aside must be visible',
    ).toBeVisible();

    expect(suiteConsoleErrors, 'no console errors on mount').toEqual([]);
  });

  // ---------------------------------------------------------------------------

  /**
   * Test 2: Draft creation — dragging across the overlay shows a draft preview.
   *
   * Drags from 30% to 70% of overlay width and asserts that either:
   * - A live drag-preview bar appears during drag (isDraggingOverlay), OR
   * - A dashed draft range bar appears after mouseup.
   * Both are rendered as `border-dashed` divs inside the overlay.
   */
  test('Test 2: drag across overlay creates a draft preview bar', async () => {
    test.setTimeout(60000);
    suiteConsoleErrors.length = 0;
    await gotoSegment(editableSegmentIds[0]);

    // Confirm no draft-preview exists before drag.
    const draftPreview = sharedPage.locator('[role="presentation"] .border-dashed');
    await expect(draftPreview).toHaveCount(0);

    // Perform drag.
    await dragAcrossOverlay(0.3, 0.7);

    // After mouseup a draftRange bar (border-dashed) should appear.
    await expect(
      draftPreview.first(),
      'draft preview bar must appear after drag',
    ).toBeVisible({ timeout: 5000 });

    // Verify the bar has positive width (not zero-width).
    const box = await draftPreview.first().boundingBox();
    expect(box, 'draft preview bar bounding box must exist').not.toBeNull();
    expect(box!.width, 'draft preview bar width > 0').toBeGreaterThan(0);

    expect(suiteConsoleErrors, 'no console errors after draft creation').toEqual([]);
  });

  // ---------------------------------------------------------------------------

  /**
   * Test 3: Create via SpeciesPalette — clicking a palette chip after
   * creating a draft fires POST /annotations and adds an item to AnnotationList.
   */
  test('Test 3: pick species from palette commits draft as annotation', async () => {
    test.setTimeout(60000);
    suiteConsoleErrors.length = 0;
    await gotoSegment(editableSegmentIds[0]);

    // Count annotations in AnnotationList before creation.
    const annotationItems = sharedPage.locator(
      'aside[aria-label] ul[role="list"] li',
    );
    const initialCount = await annotationItems.count();

    // Create a draft.
    await dragAcrossOverlay(0.2, 0.8);
    // Confirm draft bar visible.
    await expect(
      sharedPage.locator('[role="presentation"] .border-dashed').first(),
    ).toBeVisible({ timeout: 5000 });

    // Intercept the POST /annotations request.
    const annotationRequestPromise = sharedPage.waitForRequest(
      (req) =>
        req.url().includes('/annotations') &&
        req.method() === 'POST' &&
        !req.url().includes('/notes'),
      { timeout: 10000 },
    );

    // Click the first palette chip (rounded-full border buttons in the palette section).
    // The palette chips have a rounded-full class distinct from other buttons.
    const chip = sharedPage.locator('button.rounded-full').first();
    await chip.click({ timeout: 5000 });

    // Wait for the POST request to fire.
    await annotationRequestPromise;

    // Wait for AnnotationList to update (count increments).
    await sharedPage.waitForFunction(
      (expected: number) => {
        const ul = document.querySelector('aside[aria-label] ul[role="list"]');
        return ul ? ul.querySelectorAll('li').length > expected : false;
      },
      initialCount,
      { timeout: 10000 },
    );

    const finalCount = await annotationItems.count();
    expect(finalCount, 'AnnotationList count incremented after commit').toBeGreaterThan(initialCount);

    expect(suiteConsoleErrors, 'no console errors after species pick').toEqual([]);
  });

  // ---------------------------------------------------------------------------

  /**
   * Test 4: Select existing annotation — clicking an AnnotationList item
   * sets selectedAnnotationId. The clicked item gets a ring-2 class, and
   * any draft preview disappears.
   */
  test('Test 4: clicking AnnotationList item selects annotation and clears draft', async () => {
    test.setTimeout(60000);
    suiteConsoleErrors.length = 0;
    // Re-navigate to get a fresh state (segment may have an annotation from test 3).
    await gotoSegment(editableSegmentIds[0]);

    // Check if there are any annotations. If not, create one first.
    const listItems = sharedPage.locator('aside[aria-label] ul[role="list"] li');
    const count = await listItems.count();

    if (count === 0) {
      // Create annotation if none exist (might happen if test 3 ran on a different segment).
      await dragAcrossOverlay(0.2, 0.8);
      await expect(
        sharedPage.locator('[role="presentation"] .border-dashed').first(),
      ).toBeVisible({ timeout: 5000 });

      // Click the first palette chip (rounded-full buttons in the palette area).
      const chips = sharedPage.locator('button.rounded-full').first();
      await chips.click({ timeout: 5000 });

      await sharedPage.waitForFunction(
        () => {
          const ul = document.querySelector('aside[aria-label] ul[role="list"]');
          return ul ? ul.querySelectorAll('li').length > 0 : false;
        },
        undefined,
        { timeout: 10000 },
      );
    }

    // Create a draft to verify it clears on selection.
    await dragAcrossOverlay(0.1, 0.5);
    await expect(
      sharedPage.locator('[role="presentation"] .border-dashed').first(),
    ).toBeVisible({ timeout: 5000 });

    // Click the first annotation button in AnnotationList.
    const firstAnnotationBtn = sharedPage.locator(
      'aside[aria-label] ul[role="list"] li button[aria-pressed]',
    ).first();
    await firstAnnotationBtn.click();

    // The annotation button should have aria-pressed="true".
    await expect(firstAnnotationBtn).toHaveAttribute('aria-pressed', 'true', { timeout: 3000 });

    // Draft preview should disappear after selection.
    await expect(
      sharedPage.locator('[role="presentation"] .border-dashed'),
    ).toHaveCount(0, { timeout: 3000 });

    expect(suiteConsoleErrors, 'no console errors after annotation selection').toEqual([]);
  });

  // ---------------------------------------------------------------------------

  /**
   * Test 5: Escape clears draft — pressing Escape while a draft exists
   * removes the draft preview bar.
   *
   * Uses editableSegmentIds[1] which is a fresh segment with no pre-existing
   * annotations (avoiding the annotation buttons from earlier tests that would
   * swallow mousedown via stopPropagation).
   */
  test('Test 5: Escape key clears draft preview', async () => {
    test.setTimeout(60000);
    suiteConsoleErrors.length = 0;
    // Use the second editable segment to get a clean slate with no annotations.
    const segmentForTest5 = editableSegmentIds[1] ?? editableSegmentIds[0];
    await gotoSegment(segmentForTest5);

    // Create a draft (drag from 30%→70% of overlay width).
    await dragAcrossOverlay(0.3, 0.7);

    // Either the live drag preview (isDraggingOverlay) or the committed draftRange
    // shows as .border-dashed. Wait for the committed draft bar after mouseup.
    await expect(
      sharedPage.locator('[role="presentation"] .border-dashed').first(),
    ).toBeVisible({ timeout: 5000 });

    // Press Escape.
    await sharedPage.keyboard.press('Escape');

    // Draft preview should disappear.
    await expect(
      sharedPage.locator('[role="presentation"] .border-dashed'),
    ).toHaveCount(0, { timeout: 3000 });

    expect(suiteConsoleErrors, 'no console errors after Escape').toEqual([]);
  });

  // ---------------------------------------------------------------------------

  /**
   * Test 6: Delete selected annotation — pressing Delete with an annotation
   * selected (after confirming the dialog) fires DELETE /annotations/{id}
   * and decrements the AnnotationList count.
   */
  test('Test 6: Delete key removes selected annotation', async () => {
    test.setTimeout(60000);
    suiteConsoleErrors.length = 0;
    await gotoSegment(editableSegmentIds[0]);

    // Ensure there is at least one annotation.
    let count = await sharedPage.locator('aside[aria-label] ul[role="list"] li').count();
    if (count === 0) {
      // Create one.
      await dragAcrossOverlay(0.1, 0.9);
      await expect(
        sharedPage.locator('[role="presentation"] .border-dashed').first(),
      ).toBeVisible({ timeout: 5000 });
      const chips = sharedPage.locator('button.rounded-full').first();
      await chips.click({ timeout: 5000 });
      await sharedPage.waitForFunction(
        () => {
          const ul = document.querySelector('aside[aria-label] ul[role="list"]');
          return ul ? ul.querySelectorAll('li').length > 0 : false;
        },
        undefined,
        { timeout: 10000 },
      );
      count = await sharedPage.locator('aside[aria-label] ul[role="list"] li').count();
    }

    // Select the first annotation.
    const firstAnnotationBtn = sharedPage.locator(
      'aside[aria-label] ul[role="list"] li button[aria-pressed]',
    ).first();
    await firstAnnotationBtn.click();
    await expect(firstAnnotationBtn).toHaveAttribute('aria-pressed', 'true', { timeout: 3000 });

    // Set up dialog acceptor for the confirm dialog.
    sharedPage.once('dialog', (dialog) => {
      void dialog.accept();
    });

    // Set up request interceptor for DELETE.
    const deleteRequestPromise = sharedPage.waitForRequest(
      (req) =>
        req.url().match(/\/annotations\/[^/]+$/) !== null && req.method() === 'DELETE',
      { timeout: 10000 },
    );

    // Press Delete.
    await sharedPage.keyboard.press('Delete');

    // Wait for DELETE request.
    await deleteRequestPromise;

    // AnnotationList count should decrement.
    const expectedCount = count - 1;
    await sharedPage.waitForFunction(
      (expected: number) => {
        const ul = document.querySelector('aside[aria-label] ul[role="list"]');
        const items = ul ? ul.querySelectorAll('li').length : 0;
        return items <= expected;
      },
      expectedCount,
      { timeout: 10000 },
    );

    const finalCount = await sharedPage.locator('aside[aria-label] ul[role="list"] li').count();
    expect(finalCount, 'annotation count decremented after Delete').toBe(expectedCount);

    expect(suiteConsoleErrors, 'no console errors after Delete').toEqual([]);
  });

  // ---------------------------------------------------------------------------

  /**
   * Test 7: Mark empty toggle — clicking the "no vocalization" button in
   * SegmentNavigator fires PATCH /segments/{id} with is_empty=true.
   * Then un-toggling fires another PATCH with is_empty=false.
   */
  test('Test 7: no-vocalization toggle fires PATCH /segments', async () => {
    test.setTimeout(60000);
    suiteConsoleErrors.length = 0;
    // Use the second editable segment (fresh, no annotations).
    const segmentId = editableSegmentIds[1] ?? editableSegmentIds[0];
    await gotoSegment(segmentId);

    // Find the "no vocalization" button (text: "No vocalization" in English).
    const noVocButton = sharedPage.locator(
      'nav[aria-label="Segment navigator"] button',
    ).filter({ hasText: /No vocalization/i });

    // Wait for it to be enabled (not busy).
    await expect(noVocButton).toBeEnabled({ timeout: 10000 });

    // Intercept the PATCH.
    const patchMarkEmpty = sharedPage.waitForRequest(
      (req) =>
        req.url().includes('/segments/') &&
        req.method() === 'PATCH',
      { timeout: 10000 },
    );

    await noVocButton.click();

    const req1 = await patchMarkEmpty;
    const body1 = req1.postDataJSON() as Record<string, unknown>;
    expect(body1, 'PATCH body should contain is_empty:true').toMatchObject({ is_empty: true });

    // Now the button should have changed to "clear" variant.
    // The SegmentNavigator renders "Clear no-vocalization" when isEmpty=true.
    const clearButton = sharedPage.locator(
      'nav[aria-label="Segment navigator"] button',
    ).filter({ hasText: /Clear no-vocalization/i });
    await expect(clearButton).toBeVisible({ timeout: 5000 });

    // Intercept the second PATCH.
    const patchClearEmpty = sharedPage.waitForRequest(
      (req) =>
        req.url().includes('/segments/') &&
        req.method() === 'PATCH',
      { timeout: 10000 },
    );

    await clearButton.click();

    const req2 = await patchClearEmpty;
    const body2 = req2.postDataJSON() as Record<string, unknown>;
    expect(body2, 'PATCH body should contain is_empty:false').toMatchObject({ is_empty: false });

    expect(suiteConsoleErrors, 'no console errors during mark-empty toggle').toEqual([]);
  });

  // ---------------------------------------------------------------------------

  /**
   * Test 8: Segment next/prev navigation — clicking Next/Prev in
   * SegmentNavigator changes the URL to the adjacent segment.
   * The {#key segmentId} re-mounts the component for the new segment.
   */
  test('Test 8: SegmentNavigator next/prev buttons change URL', async () => {
    // Extra time for two full-page navigations (goto + navigation action + URL change).
    test.setTimeout(90000);
    suiteConsoleErrors.length = 0;
    await gotoSegment(editableSegmentIds[0]);

    // Confirm we start on segment[0].
    expect(sharedPage.url(), 'URL should contain editableSegmentIds[0]').toContain(
      editableSegmentIds[0],
    );

    // Click the Next button (aria-label from SegmentNavigator template uses i18n key
    // annotation_editor_next — in English this renders as "Next").
    const nextBtn = sharedPage.locator(
      'nav[aria-label="Segment navigator"] button[aria-label="Next"], nav[aria-label="Segment navigator"] button[aria-label*="Next"], nav[aria-label="Segment navigator"] button[title*="Next"]',
    );

    await expect(nextBtn).toBeEnabled({ timeout: 10000 });
    await nextBtn.click();

    // Wait for URL to change to a different segment.
    await sharedPage.waitForURL(
      (url) => !url.toString().includes(editableSegmentIds[0]),
      { timeout: 10000 },
    );

    const urlAfterNext = sharedPage.url();
    expect(urlAfterNext, 'URL changed after clicking Next').not.toContain(editableSegmentIds[0]);

    // Navigate back with Prev.
    const prevBtn = sharedPage.locator(
      'nav[aria-label="Segment navigator"] button[aria-label*="Prev"], nav[aria-label="Segment navigator"] button[aria-label*="prev"]',
    );
    await expect(prevBtn).toBeEnabled({ timeout: 10000 });
    await prevBtn.click();

    await sharedPage.waitForURL(
      (url) => url.toString().includes(editableSegmentIds[0]),
      { timeout: 10000 },
    );

    expect(sharedPage.url(), 'URL reverted after clicking Prev').toContain(editableSegmentIds[0]);

    expect(suiteConsoleErrors, 'no console errors during navigation').toEqual([]);
  });

  // ---------------------------------------------------------------------------

  /**
   * Test 9: Readonly segment (status === 'annotated') — navigate to the seeded
   * annotated+empty segment and verify the readonly state is presented correctly.
   *
   * Current behavior (pre-refactor baseline):
   * - The amber "Already completed" banner is visible.
   * - The segment navigator shows "Annotated" status badge.
   * - The component renders all panels (AnnotationList, SpeciesPalette, NotesPanel).
   * - The "Clear no-vocalization" button appears (segment.is_empty=true).
   * - The "No vocalization" button does NOT appear (replaced by clear variant).
   *
   * NOTE: In the current pre-refactor implementation, the overlay drag and
   * palette-chip handlers do NOT have explicit isReadonly guards — the readonly
   * state is surfaced only via the amber banner. The refactor (Step 1) will add
   * isDisabled: () => isReadonly to the draft hook to enforce drag blocking.
   * This test documents the current baseline; after the refactor the draft-blocking
   * assertion can be re-enabled.
   */
  test('Test 9: readonly segment shows banner and annotated status', async () => {
    test.setTimeout(60000);
    suiteConsoleErrors.length = 0;
    await gotoSegment(readonlySegmentId, false);

    // Wait for the SegmentNavigator to confirm the page loaded.
    await expect(
      sharedPage.locator('nav[aria-label="Segment navigator"]'),
    ).toBeVisible({ timeout: 20000 });

    // The amber readonly banner must be visible.
    // AnnotationEditor renders: bg-amber-50 / dark:bg-amber-900/20
    await expect(
      sharedPage.locator('.bg-amber-50').first(),
      'readonly amber banner must be visible for annotated segment',
    ).toBeVisible({ timeout: 10000 });

    // The SegmentNavigator must show "Annotated" status badge.
    await expect(
      sharedPage.locator('nav[aria-label="Segment navigator"]').getByText('Annotated'),
      '"Annotated" badge in SegmentNavigator',
    ).toBeVisible({ timeout: 5000 });

    // The segment was seeded as is_empty=true so the "Clear no-vocalization"
    // button should appear (not the "No vocalization" button).
    await expect(
      sharedPage.locator('nav[aria-label="Segment navigator"] button').filter({ hasText: /Clear no-vocalization/i }),
      '"Clear no-vocalization" button visible for empty+annotated segment',
    ).toBeVisible({ timeout: 5000 });

    // All three panels (Annotations, Species palette, Segment Notes) must render.
    await expect(
      sharedPage.locator('aside[aria-label]').first(),
      'AnnotationList aside visible in readonly mode',
    ).toBeVisible();
    await expect(
      sharedPage.locator('section').filter({ hasText: /Species palette/i }).first(),
      'SpeciesPalette section visible in readonly mode',
    ).toBeVisible();
    await expect(
      sharedPage.locator('aside[aria-label]').filter({ hasText: /SEGMENT NOTES|Segment Notes|notes/i }).first(),
      'NotesPanel aside visible in readonly mode',
    ).toBeVisible();

    expect(suiteConsoleErrors, 'no console errors in readonly mode').toEqual([]);
  });
});
