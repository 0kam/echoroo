import { expect, test, type Locator, type Page } from '@playwright/test';
import {
  getBearerTokenAfterLogin,
  login,
  readEnv,
  type SeededTestUser,
} from './permissions/seeded-permissions.helpers';
import { wavPath } from './helpers/wav';

const projectId = readEnv('E2E_PUBLIC_PROJECT_ID');
const datasetId = readEnv('E2E_PUBLIC_DATASET_ID');
const password = readEnv('E2E_PASSWORD');

const ownerUser: SeededTestUser = {
  role: 'owner',
  email: readEnv('E2E_OWNER_EMAIL'),
  password,
  totpSecret: readEnv('E2E_OWNER_TOTP_SECRET'),
};

const memberUser: SeededTestUser = {
  role: 'member',
  email: readEnv('E2E_MEMBER_EMAIL'),
  password,
  totpSecret: readEnv('E2E_MEMBER_TOTP_SECRET'),
};

const requiredOwnerEnv = [
  'E2E_OWNER_EMAIL',
  'E2E_OWNER_TOTP_SECRET',
  'E2E_PASSWORD',
  'E2E_PUBLIC_PROJECT_ID',
  'E2E_PUBLIC_DATASET_ID',
] as const;
const missingOwnerEnv = requiredOwnerEnv.filter((name) => !process.env[name]);

const requestUrlsByPage = new WeakMap<Page, string[]>();

function uploadSection(page: Page): Locator {
  return page.getByRole('heading', { name: /Upload Audio Files/ }).locator('..');
}

async function chooseFiles(page: Page, paths: string[]): Promise<void> {
  await page.setInputFiles('#file-drop-zone-input', paths);
}

async function startUpload(page: Page): Promise<void> {
  await uploadSection(page).getByRole('button', { name: /^Upload \d+ file/ }).click();
}

async function waitForDone(page: Page): Promise<void> {
  await expect(uploadSection(page).getByText(/Upload and import complete/)).toBeVisible({
    timeout: 180_000,
  });
}

async function openDataset(page: Page, user: SeededTestUser): Promise<void> {
  await login(page, user);
  await page.goto(`/en/projects/${projectId}/datasets/${datasetId}`);
}

function chunkUrls(page: Page): string[] {
  return (requestUrlsByPage.get(page) ?? []).filter((url) => url.includes('/chunks?offset='));
}

function sessionIdFromChunkUrl(url: string): string {
  const match = url.match(/\/upload-sessions\/([^/]+)\/files\/[^/]+\/chunks\?offset=/);
  expect(match, `could not find an upload session id in ${url}`).not.toBeNull();
  return match![1];
}

test.describe.serial('resumable uploads (storage slice 2)', () => {
  test.setTimeout(240_000);
  test.skip(
    missingOwnerEnv.length > 0,
    `missing required upload E2E environment: ${missingOwnerEnv.join(', ')}`,
  );

  test.beforeEach(({ page }) => {
    const requestUrls: string[] = [];
    requestUrlsByPage.set(page, requestUrls);
    page.on('request', (request) => requestUrls.push(request.url()));
  });

  test.afterEach(({ page }) => {
    const origin = new URL(page.url()).origin;
    const externalUrls = (requestUrlsByPage.get(page) ?? []).filter(
      (url) => !url.startsWith(origin),
    );
    expect(externalUrls, 'no request leaves the app origin').toEqual([]);
  });

  test('fresh upload', async ({ page }) => {
    const aPath = wavPath('a.wav', 600);
    const bPath = wavPath('b.wav', 30);

    await openDataset(page, ownerUser);
    await chooseFiles(page, [aPath, bPath]);
    await startUpload(page);
    await waitForDone(page);

    const chunks = chunkUrls(page);
    expect(chunks.length).toBeGreaterThanOrEqual(4);

    await page.reload();
    const recordings = page.locator('table');
    await expect(recordings).toBeVisible();
    await expect(recordings).toContainText('a.wav');
    await expect(recordings).toContainText('b.wav');
  });

  test('interrupt and automatic retry', async ({ page }) => {
    const cPath = wavPath('c.wav', 600);
    let aborted = false;
    await page.route(/\/chunks\?offset=8388608$/, async (route) => {
      if (!aborted) {
        aborted = true;
        await route.abort('connectionreset');
        return;
      }
      await route.continue();
    });

    await openDataset(page, ownerUser);
    await chooseFiles(page, [cPath]);
    await startUpload(page);
    await waitForDone(page);

    const retried = chunkUrls(page).filter((url) => url.endsWith('/chunks?offset=8388608'));
    expect(retried).toHaveLength(2);
  });

  test('reload during transfer, then resume', async ({ page }) => {
    const dPath = wavPath('d.wav', 600);
    const hangingChunk = /\/chunks\?offset=16777216$/;
    await page.route(hangingChunk, async () => {
      await new Promise<void>(() => {});
    });

    await openDataset(page, ownerUser);
    await chooseFiles(page, [dPath]);
    const thirdChunkRequest = page.waitForRequest(
      (request) => request.url().includes('/chunks?offset=16777216'),
      { timeout: 180_000 },
    );
    await startUpload(page);
    const request = await thirdChunkRequest;
    const sessionId = sessionIdFromChunkUrl(request.url());
    const requestCountBeforeReload = (requestUrlsByPage.get(page) ?? []).length;

    await page.reload();
    await expect(page.getByText(/You have an unfinished upload/)).toBeVisible();
    await page.unroute(hangingChunk);
    await chooseFiles(page, [dPath]);
    await waitForDone(page);

    const afterReload = (requestUrlsByPage.get(page) ?? [])
      .slice(requestCountBeforeReload)
      .filter((url) => url.includes(`/upload-sessions/${sessionId}/`));
    const resumedOffsets = afterReload
      .map((url) => url.match(/\/chunks\?offset=(\d+)/)?.[1])
      .filter((offset): offset is string => offset !== undefined)
      .map(Number);
    expect(resumedOffsets).not.toContain(0);
    expect(resumedOffsets).not.toContain(8388608);
    expect(resumedOffsets.every((offset) => offset >= 16777216)).toBe(true);
  });

  test('partial import', async ({ page }) => {
    const ePath = wavPath('e.wav', 30);
    const fPath = wavPath('f.wav', 600);
    let failedFileId: string | undefined;
    let sessionId: string | undefined;

    await page.route(/\/upload-sessions$/, async (route) => {
      if (route.request().method() !== 'POST') {
        await route.continue();
        return;
      }
      const response = await route.fetch();
      const body = (await response.json()) as {
        session_id: string;
        files: Array<{ file_id: string; original_filename: string }>;
      };
      sessionId = body.session_id;
      failedFileId = body.files.find((file) => file.original_filename === 'f.wav')?.file_id;
      expect(failedFileId).toBeTruthy();
      await route.fulfill({ response });
    });
    await page.route(/\/chunks\?offset=/, async (route) => {
      if (failedFileId && route.request().url().includes(`/files/${failedFileId}/chunks?`)) {
        await route.fulfill({
          status: 413,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Chunk exceeds declared file size' }),
        });
        return;
      }
      await route.continue();
    });

    await openDataset(page, ownerUser);
    await chooseFiles(page, [ePath, fPath]);
    await startUpload(page);
    await expect(uploadSection(page).getByText(/could not be sent/)).toBeVisible({
      timeout: 180_000,
    });
    await uploadSection(page)
      .getByRole('button', { name: /Import without the 1 failed/ })
      .click();
    await waitForDone(page);

    expect(sessionId).toBeTruthy();
    const bearer = await getBearerTokenAfterLogin(page);
    const statusResponse = await page.request.get(
      `/web-api/v1/projects/${projectId}/datasets/${datasetId}/upload-sessions/${sessionId}`,
      {
        headers: { Authorization: `Bearer ${bearer}` },
        failOnStatusCode: false,
      },
    );
    expect(statusResponse.ok()).toBe(true);
    const status = (await statusResponse.json()) as {
      files: Array<{ original_filename: string; status: string }>;
    };
    expect(status.files.find((file) => file.original_filename === 'f.wav')?.status).toBe('skipped');
    expect(status.files.find((file) => file.original_filename === 'e.wav')?.status).toBe('imported');
  });

  test('members cannot upload', async ({ page }) => {
    test.skip(
      !process.env.E2E_MEMBER_EMAIL || !process.env.E2E_MEMBER_TOTP_SECRET,
      'missing E2E_MEMBER_EMAIL or E2E_MEMBER_TOTP_SECRET',
    );
    await openDataset(page, memberUser);
    await expect(page.locator('h1')).toBeVisible();
    await page.waitForLoadState('networkidle');
    await expect(page.getByRole('heading', { name: /Upload Audio Files/ })).toHaveCount(0);
  });
});
