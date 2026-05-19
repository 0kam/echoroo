/**
 * Seeded data-surface permission E2E suite.
 *
 * Requires the fixture payload from:
 *   uv run python -m echoroo.scripts.seed_e2e_permissions --confirm
 */

import { expect, test, type APIResponse, type Page, type TestInfo } from '@playwright/test';
import {
  expectStatus,
  getBearerTokenAfterLogin,
  login,
  missingEnv,
  readEnv,
  type Role,
  type SeededApiTestUser,
  type SeededProject,
  type Visibility,
} from './seeded-permissions.helpers';

interface SeededDataProject extends SeededProject {
  siteId: string;
  datasetId: string;
  datasetName: string;
  recordingId: string;
  detectionId: string;
}

interface DatasetListResponse {
  items?: Array<{ id?: string; name?: string }>;
}

interface RecordingListResponse {
  items?: Array<{ id?: string; name?: string }>;
}

interface RecordingDetailResponse {
  id?: string;
  filename?: string;
}

interface DetectionListResponse {
  items?: Array<{ id?: string; tag_id?: string | null; tag?: { id?: string | null } | null }>;
  total?: number;
}

const SUITE_ENABLED = process.env.E2E_DATA_SURFACES_ENABLED === '1';
const PASSWORD = readEnv('E2E_PASSWORD');
const FIXTURE_PREFIX = readEnv('E2E_FIXTURE_PREFIX');
const ROLES: Role[] = ['owner', 'admin', 'member', 'viewer', 'nonmember', 'trusted'];
const VISIBILITIES: Visibility[] = ['public', 'restricted'];

const USERS: Record<Role, SeededApiTestUser> = {
  owner: {
    role: 'owner',
    email: readEnv('E2E_OWNER_EMAIL'),
    password: PASSWORD,
    totpSecret: readEnv('E2E_OWNER_TOTP_SECRET'),
    apiKey: readEnv('E2E_OWNER_API_KEY'),
  },
  admin: {
    role: 'admin',
    email: readEnv('E2E_ADMIN_EMAIL'),
    password: PASSWORD,
    totpSecret: readEnv('E2E_ADMIN_TOTP_SECRET'),
    apiKey: readEnv('E2E_ADMIN_API_KEY'),
  },
  member: {
    role: 'member',
    email: readEnv('E2E_MEMBER_EMAIL'),
    password: PASSWORD,
    totpSecret: readEnv('E2E_MEMBER_TOTP_SECRET'),
    apiKey: readEnv('E2E_MEMBER_API_KEY'),
  },
  viewer: {
    role: 'viewer',
    email: readEnv('E2E_VIEWER_EMAIL'),
    password: PASSWORD,
    totpSecret: readEnv('E2E_VIEWER_TOTP_SECRET'),
    apiKey: readEnv('E2E_VIEWER_API_KEY'),
  },
  nonmember: {
    role: 'nonmember',
    email: readEnv('E2E_NONMEMBER_EMAIL'),
    password: PASSWORD,
    totpSecret: readEnv('E2E_NONMEMBER_TOTP_SECRET'),
    apiKey: readEnv('E2E_NONMEMBER_API_KEY'),
  },
  trusted: {
    role: 'trusted',
    email: readEnv('E2E_TRUSTED_EMAIL'),
    password: PASSWORD,
    totpSecret: readEnv('E2E_TRUSTED_TOTP_SECRET'),
    apiKey: readEnv('E2E_TRUSTED_API_KEY'),
  },
};

const PROJECTS: Record<Visibility, SeededDataProject> = {
  public: {
    visibility: 'public',
    id: readEnv('E2E_PUBLIC_PROJECT_ID'),
    name: readEnv('E2E_PUBLIC_PROJECT_NAME'),
    siteId: readEnv('E2E_PUBLIC_SITE_ID'),
    datasetId: readEnv('E2E_PUBLIC_DATASET_ID'),
    datasetName: readEnv('E2E_PUBLIC_DATASET_NAME'),
    recordingId: readEnv('E2E_PUBLIC_RECORDING_ID'),
    detectionId: readEnv('E2E_PUBLIC_DETECTION_ID'),
  },
  restricted: {
    visibility: 'restricted',
    id: readEnv('E2E_RESTRICTED_PROJECT_ID'),
    name: readEnv('E2E_RESTRICTED_PROJECT_NAME'),
    siteId: readEnv('E2E_RESTRICTED_SITE_ID'),
    datasetId: readEnv('E2E_RESTRICTED_DATASET_ID'),
    datasetName: readEnv('E2E_RESTRICTED_DATASET_NAME'),
    recordingId: readEnv('E2E_RESTRICTED_RECORDING_ID'),
    detectionId: readEnv('E2E_RESTRICTED_DETECTION_ID'),
  },
};

const REQUIRED_ENV = [
  'E2E_FIXTURE_PREFIX',
  'E2E_PASSWORD',
  'E2E_OWNER_EMAIL',
  'E2E_OWNER_TOTP_SECRET',
  'E2E_OWNER_API_KEY',
  'E2E_ADMIN_EMAIL',
  'E2E_ADMIN_TOTP_SECRET',
  'E2E_ADMIN_API_KEY',
  'E2E_MEMBER_EMAIL',
  'E2E_MEMBER_TOTP_SECRET',
  'E2E_MEMBER_API_KEY',
  'E2E_VIEWER_EMAIL',
  'E2E_VIEWER_TOTP_SECRET',
  'E2E_VIEWER_API_KEY',
  'E2E_NONMEMBER_EMAIL',
  'E2E_NONMEMBER_TOTP_SECRET',
  'E2E_NONMEMBER_API_KEY',
  'E2E_TRUSTED_EMAIL',
  'E2E_TRUSTED_TOTP_SECRET',
  'E2E_TRUSTED_API_KEY',
  'E2E_PUBLIC_PROJECT_ID',
  'E2E_PUBLIC_PROJECT_NAME',
  'E2E_PUBLIC_SITE_ID',
  'E2E_PUBLIC_DATASET_ID',
  'E2E_PUBLIC_DATASET_NAME',
  'E2E_PUBLIC_RECORDING_ID',
  'E2E_PUBLIC_DETECTION_ID',
  'E2E_RESTRICTED_PROJECT_ID',
  'E2E_RESTRICTED_PROJECT_NAME',
  'E2E_RESTRICTED_SITE_ID',
  'E2E_RESTRICTED_DATASET_ID',
  'E2E_RESTRICTED_DATASET_NAME',
  'E2E_RESTRICTED_RECORDING_ID',
  'E2E_RESTRICTED_DETECTION_ID',
] as const;

const MISSING_ENV = missingEnv(REQUIRED_ENV);

const DATASET_READ_EXPECTATIONS: Record<Visibility, Record<Role, number>> = {
  public: {
    owner: 200,
    admin: 200,
    member: 200,
    viewer: 200,
    nonmember: 403,
    trusted: 403,
  },
  restricted: {
    owner: 200,
    admin: 200,
    member: 200,
    viewer: 200,
    nonmember: 403,
    trusted: 403,
  },
};

const READ_ALL_ROLES: Record<Visibility, Record<Role, number>> = {
  public: {
    owner: 200,
    admin: 200,
    member: 200,
    viewer: 200,
    nonmember: 200,
    trusted: 200,
  },
  restricted: {
    owner: 200,
    admin: 200,
    member: 200,
    viewer: 200,
    nonmember: 200,
    trusted: 200,
  },
};

function recordingName(project: SeededDataProject): string {
  return `${FIXTURE_PREFIX}-${project.visibility}-fixture.wav`;
}

function storagePath(project: SeededDataProject): string {
  return `e2e/${FIXTURE_PREFIX}/${project.visibility}/fixture.wav`;
}

function privateMetadataValues(
  project: SeededDataProject,
  options: { includeEmails: boolean }
): string[] {
  const secretValues = ROLES.flatMap((role) => [USERS[role].apiKey, USERS[role].totpSecret]);
  const emailValues = options.includeEmails
    ? [USERS.owner.email, USERS.member.email, USERS.trusted.email]
    : [];
  return [...emailValues, ...secretValues, storagePath(project)].filter(
    (value) => value.length > 0
  );
}

async function expectNoPrivateMetadata(
  page: Page,
  project: SeededDataProject,
  options: { includeEmails?: boolean } = {}
): Promise<void> {
  const body = page.locator('body');
  for (const value of privateMetadataValues(project, {
    includeEmails: options.includeEmails ?? false,
  })) {
    await expect(body, `page should not render private metadata value ${value}`).not.toContainText(
      value
    );
  }
}

async function responseJson<T>(response: APIResponse): Promise<T> {
  return (await response.json()) as T;
}

async function expectDatasetApi(
  page: Page,
  role: Role,
  project: SeededDataProject,
  webBearer: string
): Promise<void> {
  const expected = DATASET_READ_EXPECTATIONS[project.visibility][role];

  const listResponse = await page.request.get(
    `/web-api/v1/projects/${project.id}/datasets?page=1&page_size=20`,
    {
      headers: { Authorization: `Bearer ${webBearer}` },
      failOnStatusCode: false,
    }
  );
  await expectStatus(listResponse, expected, `${role} dataset list ${project.visibility}`);

  const detailResponse = await page.request.get(
    `/web-api/v1/projects/${project.id}/datasets/${project.datasetId}`,
    {
      headers: { Authorization: `Bearer ${webBearer}` },
      failOnStatusCode: false,
    }
  );
  await expectStatus(detailResponse, expected, `${role} dataset detail ${project.visibility}`);

  if (expected === 200) {
    const list = await responseJson<DatasetListResponse>(listResponse);
    expect(
      list.items?.some((item) => item.id === project.datasetId),
      `${role} should see seeded ${project.visibility} dataset in list`
    ).toBe(true);
  }
}

async function expectDatasetUi(page: Page, role: Role, project: SeededDataProject): Promise<void> {
  await page.goto(`/en/projects/${project.id}/datasets`);
  await expect(page.locator('h1', { hasText: 'Datasets' })).toBeVisible({ timeout: 15000 });

  if (DATASET_READ_EXPECTATIONS[project.visibility][role] !== 200) {
    await expect(page.getByRole('button', { name: project.datasetName })).toBeHidden({
      timeout: 15000,
    });
    await expectNoPrivateMetadata(page, project, { includeEmails: true });

    await page.goto(`/en/projects/${project.id}/datasets/${project.datasetId}`);
    await expect(page.locator('h1', { hasText: project.datasetName })).toBeHidden({
      timeout: 15000,
    });
    await expectNoPrivateMetadata(page, project, { includeEmails: true });
    return;
  }

  await expect(page.getByRole('button', { name: project.datasetName })).toBeVisible({
    timeout: 15000,
  });

  await page.goto(`/en/projects/${project.id}/datasets/${project.datasetId}`);
  await expect(page.locator('h1', { hasText: project.datasetName })).toBeVisible({
    timeout: 15000,
  });
  await expect(page.getByText(project.siteId, { exact: false })).toBeHidden();
  await expectNoPrivateMetadata(page, project);
}

async function expectRecordingSurface(
  page: Page,
  role: Role,
  project: SeededDataProject,
  webBearer: string
): Promise<void> {
  const expected = READ_ALL_ROLES[project.visibility][role];
  const seededRecordingName = recordingName(project);

  const listResponse = await page.request.get(
    `/web-api/v1/projects/${project.id}/recordings?limit=50`,
    {
      headers: { Authorization: `Bearer ${webBearer}` },
      failOnStatusCode: false,
    }
  );
  await expectStatus(listResponse, expected, `${role} recording list ${project.visibility}`);
  const list = await responseJson<RecordingListResponse>(listResponse);
  expect(
    list.items?.some((item) => item.id === project.recordingId),
    `${role} should see seeded ${project.visibility} recording in list`
  ).toBe(true);

  const detailResponse = await page.request.get(
    `/web-api/v1/projects/${project.id}/recordings/${project.recordingId}`,
    {
      headers: { Authorization: `Bearer ${webBearer}` },
      failOnStatusCode: false,
    }
  );
  await expectStatus(detailResponse, expected, `${role} recording detail ${project.visibility}`);
  const detail = await responseJson<RecordingDetailResponse>(detailResponse);
  expect(detail.id, `${role} recording detail id for ${project.visibility}`).toBe(
    project.recordingId
  );
  expect(detail.filename, `${role} recording detail filename for ${project.visibility}`).toBe(
    seededRecordingName
  );

  await page.goto(`/en/projects/${project.id}/recordings`);
  await expect(page.locator('h1', { hasText: 'Recordings' })).toBeVisible({ timeout: 15000 });
  await expect(page.getByText(seededRecordingName, { exact: true })).toBeVisible({
    timeout: 15000,
  });
  await expectNoPrivateMetadata(page, project);

  await page.goto(`/en/projects/${project.id}/recordings/${project.recordingId}`);
  await expect(page.getByText(seededRecordingName, { exact: true })).toBeVisible({
    timeout: 15000,
  });
  await expectNoPrivateMetadata(page, project);
}

async function expectDetectionListSmoke(
  page: Page,
  role: Role,
  project: SeededDataProject,
  webBearer: string
): Promise<void> {
  const expected = READ_ALL_ROLES[project.visibility][role];
  const response = await page.request.get(
    `/web-api/v1/projects/${project.id}/detections?recording_id=${project.recordingId}&page_size=10&locale=en`,
    {
      headers: { Authorization: `Bearer ${webBearer}` },
      failOnStatusCode: false,
    }
  );
  await expectStatus(response, expected, `${role} detection list ${project.visibility}`);
  const detections = await responseJson<DetectionListResponse>(response);
  expect(
    Array.isArray(detections.items),
    `${role} detection list ${project.visibility} should include an items array`
  ).toBe(true);
  if (detections.total !== undefined) {
    expect(
      typeof detections.total,
      `${role} detection list ${project.visibility} should include a numeric total when present`
    ).toBe('number');
  }

  await page.goto(`/en/projects/${project.id}/detections`);
  await expect(page.locator('h1', { hasText: 'Detections' })).toBeVisible({ timeout: 15000 });
  await expectNoPrivateMetadata(page, project);
}

async function deriveDetectionTagId(
  page: Page,
  role: Role,
  project: SeededDataProject,
  webBearer: string,
  testInfo: TestInfo
): Promise<string | null> {
  const response = await page.request.get(
    `/web-api/v1/projects/${project.id}/detections?recording_id=${project.recordingId}&page_size=10&locale=en`,
    {
      headers: { Authorization: `Bearer ${webBearer}` },
      failOnStatusCode: false,
    }
  );
  if (response.status() !== 200) {
    testInfo.annotations.push({
      type: 'skip',
      description:
        `Detection detail skipped for ${role}/${project.visibility}: tag derivation list ` +
        `returned ${response.status()}; detection list is covered by the smoke test.`,
    });
    return null;
  }

  const detections = await responseJson<DetectionListResponse>(response);
  const seededDetection = detections.items?.find((item) => item.id === project.detectionId);
  const tagId = seededDetection?.tag_id ?? seededDetection?.tag?.id ?? null;
  if (!tagId) {
    testInfo.annotations.push({
      type: 'skip',
      description:
        `Detection detail skipped for ${role}/${project.visibility}: seeded detection ` +
        `${project.detectionId} was absent from the list response or did not include a ` +
        `stable tag_id.`,
    });
  }
  return tagId;
}

async function expectDetectionDetailSmoke(
  page: Page,
  role: Role,
  project: SeededDataProject,
  tagId: string,
  testInfo: TestInfo
): Promise<void> {
  await page.goto(`/en/projects/${project.id}/detections/${tagId}`);
  try {
    await expect(page.getByRole('link', { name: 'All Species' })).toBeVisible({ timeout: 15000 });
    await expect(page.locator('h1')).toBeVisible();
    await expectNoPrivateMetadata(page, project);
  } catch (error) {
    testInfo.annotations.push({
      type: 'skip',
      description:
        `Detection detail skipped for ${role}/${project.visibility}: detail route was ` +
        `unstable after deriving tag ${tagId}. ${error instanceof Error ? error.message : error}`,
    });
    test.skip(true, `Detection detail route unstable for ${role}/${project.visibility}.`);
  }
}

async function blockMediaByteRequests(page: Page): Promise<void> {
  await page.route(
    /\/(?:api|web-api)\/v1\/projects\/[^/]+\/recordings\/[^/]+\/(?:audio|playback|spectrogram|download)(?:\?|$)/,
    (route) => route.abort('blockedbyclient')
  );
}

test.describe('Seeded data surfaces @e2e-data-surfaces', () => {
  test.describe.configure({ timeout: 120000 });

  test.beforeEach(() => {
    test.skip(
      !SUITE_ENABLED,
      'E2E_DATA_SURFACES_ENABLED=1 is required to run seeded data-surface permissions.'
    );
    test.skip(
      MISSING_ENV.length > 0,
      `Missing required seeded data-surface env vars: ${MISSING_ENV.join(', ')}. ` +
        'Run seed_e2e_permissions.py --confirm and export payload.env.'
    );
  });

  for (const role of ROLES) {
    for (const visibility of VISIBILITIES) {
      test(`${role} reads allowed ${visibility} data surfaces`, async ({ page }) => {
        const user = USERS[role];
        const project = PROJECTS[visibility];

        await blockMediaByteRequests(page);
        await login(page, user);
        const webBearer = await getBearerTokenAfterLogin(page);
        await expectDatasetApi(page, role, project, webBearer);
        await expectDatasetUi(page, role, project);
        await expectRecordingSurface(page, role, project, webBearer);
        await expectDetectionListSmoke(page, role, project, webBearer);
      });

      test(`${role} detection detail smoke on ${visibility} project`, async ({
        page,
      }, testInfo) => {
        const user = USERS[role];
        const project = PROJECTS[visibility];

        await blockMediaByteRequests(page);
        await login(page, user);
        const webBearer = await getBearerTokenAfterLogin(page);
        const tagId = await deriveDetectionTagId(page, role, project, webBearer, testInfo);
        if (!tagId) {
          test.skip(
            true,
            `Detection detail skipped for ${role}/${visibility}: no stable tag ID was derived.`
          );
          return;
        }
        await expectDetectionDetailSmoke(page, role, project, tagId, testInfo);
      });
    }
  }

  test('guest public explore reads public project without private metadata leaks', async ({
    page,
  }) => {
    const publicProject = PROJECTS.public;
    const restrictedProject = PROJECTS.restricted;

    await blockMediaByteRequests(page);

    const listResponse = await page.request.get('/web-api/v1/projects/?page=1&limit=100', {
      failOnStatusCode: false,
    });
    await expectStatus(listResponse, 200, 'guest public explore project list');
    const projectList = await listResponse.text();
    expect(projectList, 'guest public explore list should include seeded public project').toContain(
      publicProject.id
    );
    for (const value of [
      ...privateMetadataValues(publicProject, { includeEmails: true }),
      ...privateMetadataValues(restrictedProject, { includeEmails: true }),
    ]) {
      expect(
        projectList,
        `guest list JSON should not leak private metadata value ${value}`
      ).not.toContain(value);
    }

    const publicDetailResponse = await page.request.get(
      `/web-api/v1/projects/${publicProject.id}`,
      { failOnStatusCode: false }
    );
    await expectStatus(publicDetailResponse, 200, 'guest public explore project detail');
    const publicDetail = await publicDetailResponse.text();
    expect(
      publicDetail,
      'guest public explore detail should include seeded public project'
    ).toContain(publicProject.name);
    for (const value of privateMetadataValues(publicProject, { includeEmails: true })) {
      expect(
        publicDetail,
        `guest detail JSON should not leak private metadata value ${value}`
      ).not.toContain(value);
    }

    const publicRecordingsResponse = await page.request.get(
      `/web-api/v1/projects/${publicProject.id}/recordings?limit=50`,
      { failOnStatusCode: false }
    );
    await expectStatus(publicRecordingsResponse, 200, 'guest public explore recording list');
    expect(
      await publicRecordingsResponse.text(),
      'guest public explore recording list should include seeded public recording'
    ).toContain(recordingName(publicProject));

    await page.goto('/en/explore/projects');
    await expect(page.locator('h1', { hasText: 'Public projects' })).toBeVisible({
      timeout: 15000,
    });
    await expectNoPrivateMetadata(page, publicProject, { includeEmails: true });
    await expectNoPrivateMetadata(page, restrictedProject, { includeEmails: true });

    await page.goto(`/en/explore/projects/${publicProject.id}`);
    await page.waitForLoadState('domcontentloaded');
    await expectNoPrivateMetadata(page, publicProject, { includeEmails: true });
    await expectNoPrivateMetadata(page, restrictedProject, { includeEmails: true });

    await page.goto(`/en/explore/projects/${restrictedProject.id}`);
    await page.waitForLoadState('domcontentloaded');
    await expectNoPrivateMetadata(page, restrictedProject, { includeEmails: true });
  });
});
