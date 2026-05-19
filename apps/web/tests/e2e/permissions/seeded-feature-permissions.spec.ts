/**
 * Seeded feature-level permission E2E suite.
 *
 * Requires the fixture payload from:
 *   uv run python -m echoroo.scripts.seed_e2e_permissions --confirm
 */

import { expect, test, type Page } from '@playwright/test';
import {
  backendApiUrl,
  expectStatus,
  getBearerTokenAfterLogin,
  login,
  missingEnv,
  readEnv,
  type Role,
  type SeededApiTestUser,
  type SeededFeatureProject,
  type Visibility,
} from './seeded-permissions.helpers';

const SUITE_ENABLED = process.env.E2E_FEATURE_PERMISSIONS_ENABLED === '1';
const PASSWORD = readEnv('E2E_PASSWORD');
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

const PROJECTS: Record<Visibility, SeededFeatureProject> = {
  public: {
    visibility: 'public',
    id: readEnv('E2E_PUBLIC_PROJECT_ID'),
    name: readEnv('E2E_PUBLIC_PROJECT_NAME'),
    datasetId: readEnv('E2E_PUBLIC_DATASET_ID'),
    datasetName: readEnv('E2E_PUBLIC_DATASET_NAME'),
    annotationId: readEnv('E2E_PUBLIC_ANNOTATION_ID'),
    trustedOverlayId: readEnv('E2E_PUBLIC_TRUSTED_OVERLAY_ID'),
  },
  restricted: {
    visibility: 'restricted',
    id: readEnv('E2E_RESTRICTED_PROJECT_ID'),
    name: readEnv('E2E_RESTRICTED_PROJECT_NAME'),
    datasetId: readEnv('E2E_RESTRICTED_DATASET_ID'),
    datasetName: readEnv('E2E_RESTRICTED_DATASET_NAME'),
    annotationId: readEnv('E2E_RESTRICTED_ANNOTATION_ID'),
    trustedOverlayId: readEnv('E2E_RESTRICTED_TRUSTED_OVERLAY_ID'),
  },
};

const REQUIRED_ENV = [
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
  'E2E_PUBLIC_DATASET_ID',
  'E2E_PUBLIC_DATASET_NAME',
  'E2E_PUBLIC_ANNOTATION_ID',
  'E2E_PUBLIC_TRUSTED_OVERLAY_ID',
  'E2E_RESTRICTED_PROJECT_ID',
  'E2E_RESTRICTED_PROJECT_NAME',
  'E2E_RESTRICTED_DATASET_ID',
  'E2E_RESTRICTED_DATASET_NAME',
  'E2E_RESTRICTED_ANNOTATION_ID',
  'E2E_RESTRICTED_TRUSTED_OVERLAY_ID',
] as const;

const MISSING_ENV = missingEnv(REQUIRED_ENV);

const API_EXPECTATIONS: Record<
  Visibility,
  Record<
    Role,
    {
      searchSessions: number;
      exportCsv: number;
      vote: number[];
      comment: number[];
    }
  >
> = {
  public: {
    owner: { searchSessions: 200, exportCsv: 200, vote: [200, 201], comment: [200, 201] },
    admin: { searchSessions: 200, exportCsv: 200, vote: [200, 201], comment: [200, 201] },
    member: { searchSessions: 200, exportCsv: 200, vote: [200, 201], comment: [200, 201] },
    viewer: { searchSessions: 200, exportCsv: 200, vote: [200, 201], comment: [200, 201] },
    nonmember: { searchSessions: 200, exportCsv: 200, vote: [200, 201], comment: [200, 201] },
    trusted: { searchSessions: 200, exportCsv: 200, vote: [200, 201], comment: [200, 201] },
  },
  restricted: {
    owner: { searchSessions: 200, exportCsv: 200, vote: [200, 201], comment: [200, 201] },
    admin: { searchSessions: 200, exportCsv: 200, vote: [200, 201], comment: [200, 201] },
    member: { searchSessions: 200, exportCsv: 200, vote: [200, 201], comment: [200, 201] },
    viewer: { searchSessions: 200, exportCsv: 403, vote: [403], comment: [403] },
    nonmember: { searchSessions: 403, exportCsv: 403, vote: [200, 201], comment: [200, 201] },
    trusted: { searchSessions: 200, exportCsv: 200, vote: [200, 201], comment: [200, 201] },
  },
};

const DATASET_DETAIL_BUTTONS: Record<Role, { edit: boolean; delete: boolean; export: boolean }> = {
  owner: { edit: true, delete: true, export: true },
  admin: { edit: true, delete: true, export: true },
  member: { edit: false, delete: false, export: true },
  viewer: { edit: false, delete: false, export: false },
  nonmember: { edit: false, delete: false, export: false },
  trusted: { edit: false, delete: false, export: false },
};

async function expectButtonVisibility(
  page: Page,
  name: string,
  shouldBeVisible: boolean
): Promise<void> {
  const button = page.getByRole('button', { name, exact: true });
  if (shouldBeVisible) {
    await expect(button).toBeVisible();
  } else {
    await expect(button).toBeHidden();
  }
}

async function expectDatasetUi(
  page: Page,
  role: Role,
  project: SeededFeatureProject
): Promise<void> {
  await page.goto(`/en/projects/${project.id}/datasets`);
  await expect(page.locator('h1', { hasText: 'Datasets' })).toBeVisible({ timeout: 15000 });

  if (role === 'nonmember' || role === 'trusted') {
    await expect(page.getByRole('button', { name: 'New Dataset', exact: true })).toBeHidden();
    await expect(page.getByRole('button', { name: 'Delete dataset' }).first()).toBeHidden();
    await expect(page.getByRole('button', { name: project.datasetName })).toBeHidden({
      timeout: 15000,
    });
    return;
  }

  await expect(page.getByRole('button', { name: project.datasetName })).toBeVisible();
  await expectButtonVisibility(page, 'New Dataset', role === 'owner' || role === 'admin');

  // The list row delete button is intentionally not role-gated in the current
  // UI helper path; detail-page Edit/Delete below are the canonical gates.
  await expect(page.getByRole('button', { name: 'Delete dataset' }).first()).toBeVisible();

  await page.goto(`/en/projects/${project.id}/datasets/${project.datasetId}`);
  await expect(page.locator('h1', { hasText: project.datasetName })).toBeVisible({
    timeout: 15000,
  });

  const buttons = DATASET_DETAIL_BUTTONS[role];
  await expectButtonVisibility(page, 'Edit', buttons.edit);
  await expectButtonVisibility(page, 'Delete', buttons.delete);
  await expectButtonVisibility(page, 'Export', buttons.export);
}

async function expectTrustedManagementUi(
  page: Page,
  role: Role,
  project: SeededFeatureProject
): Promise<void> {
  await page.goto(`/en/projects/${project.id}/trusted`);

  if (role === 'owner') {
    await expect(page.locator('[data-testid="trusted-page"]')).toBeVisible({ timeout: 15000 });
    await expect(page.locator('[data-testid="trusted-invite-form"]')).toBeVisible();
    await expect(page.locator('[data-testid="trusted-admin-readonly-notice"]')).toBeHidden();
    return;
  }

  if (role === 'admin') {
    await expect(page.locator('[data-testid="trusted-page"]')).toBeVisible({ timeout: 15000 });
    await expect(page.locator('[data-testid="trusted-admin-readonly-notice"]')).toBeVisible();
    await expect(page.locator('[data-testid="trusted-invite-form"]')).toBeHidden();
    return;
  }

  await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/?$`), { timeout: 15000 });
  await expect(page.locator('[data-testid="trusted-invite-form"]')).toBeHidden();
  await expect(page.locator('h1', { hasText: project.name })).toBeVisible();
}

async function expectTrustedOverlayIsListed(
  page: Page,
  webBearer: string,
  project: SeededFeatureProject
): Promise<void> {
  const response = await page.request.get(
    `/web-api/v1/projects/${project.id}/trusted-users?status=active`,
    {
      headers: { Authorization: `Bearer ${webBearer}` },
      failOnStatusCode: false,
    }
  );
  await expectStatus(response, 200, `GET trusted users for ${project.visibility}`);
  const data = (await response.json()) as { items?: Array<{ id?: string }> };
  expect(
    data.items?.some((item) => item.id === project.trustedOverlayId),
    `${project.visibility} trusted overlay ${project.trustedOverlayId} should be listed`
  ).toBe(true);
}

async function verifyApiPermissions(
  page: Page,
  role: Role,
  apiKey: string,
  project: SeededFeatureProject
): Promise<void> {
  const expected = API_EXPECTATIONS[project.visibility][role];

  const searchSessions = await page.request.get(
    backendApiUrl(`/api/v1/projects/${project.id}/search/sessions`),
    {
      headers: { Authorization: `Bearer ${apiKey}` },
      failOnStatusCode: false,
    }
  );
  await expectStatus(
    searchSessions,
    expected.searchSessions,
    `${role} search ${project.visibility}`
  );

  const exportCsv = await page.request.get(
    backendApiUrl(`/api/v1/projects/${project.id}/detections/export/csv`),
    {
      headers: { Authorization: `Bearer ${apiKey}` },
      failOnStatusCode: false,
    }
  );
  await expectStatus(exportCsv, expected.exportCsv, `${role} export ${project.visibility}`);

  const vote = await page.request.post(
    backendApiUrl(`/api/v1/projects/${project.id}/annotations/${project.annotationId}/votes`),
    {
      headers: { Authorization: `Bearer ${apiKey}` },
      data: { vote: 'agree', signal_quality: 'solo' },
      failOnStatusCode: false,
    }
  );
  await expectStatus(vote, expected.vote, `${role} vote ${project.visibility}`);

  const comment = await page.request.post(
    backendApiUrl(`/api/v1/projects/${project.id}/annotations/${project.annotationId}/comments`),
    {
      headers: { Authorization: `Bearer ${apiKey}` },
      data: {
        body: `feature-permissions ${role} ${project.visibility} ${Date.now()}`,
      },
      failOnStatusCode: false,
    }
  );
  await expectStatus(comment, expected.comment, `${role} comment ${project.visibility}`);
}

test.describe('Seeded feature permissions @e2e-feature-permissions', () => {
  test.describe.configure({ timeout: 120000 });

  test.beforeEach(() => {
    test.skip(
      !SUITE_ENABLED,
      'E2E_FEATURE_PERMISSIONS_ENABLED=1 is required to run seeded feature permissions.'
    );
    test.skip(
      MISSING_ENV.length > 0,
      `Missing required seeded feature permission env vars: ${MISSING_ENV.join(', ')}. ` +
        'Run seed_e2e_permissions.py --confirm and export payload.env.'
    );
  });

  for (const role of ROLES) {
    test(`${role} API and UI feature permissions`, async ({ page }) => {
      const user = USERS[role];

      await login(page, user);
      const webBearer = await getBearerTokenAfterLogin(page);

      for (const visibility of VISIBILITIES) {
        const project = PROJECTS[visibility];
        await verifyApiPermissions(page, role, user.apiKey, project);
        await expectDatasetUi(page, role, project);
      }

      await expectTrustedManagementUi(page, role, PROJECTS.public);
      if (role === 'owner') {
        await expectTrustedOverlayIsListed(page, webBearer, PROJECTS.public);
        await expectTrustedOverlayIsListed(page, webBearer, PROJECTS.restricted);
      }
    });
  }

  test('guest can view public explore detail without owner email leak', async ({ page }) => {
    const project = PROJECTS.public;

    await page.goto(`/en/explore/projects/${project.id}`);
    await expect(page.locator('h1', { hasText: project.name })).toBeVisible({ timeout: 15000 });
    await expect(page.getByText(project.name, { exact: true }).first()).toBeVisible();
    await expect(page.locator('body')).not.toContainText(USERS.owner.email);
  });
});
