/**
 * Seeded Trusted Overlay permission E2E suite.
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
  type SeededProject,
  type Visibility,
} from './seeded-permissions.helpers';

const SUITE_ENABLED = process.env.E2E_TRUSTED_OVERLAY_ENABLED === '1';
const PASSWORD = readEnv('E2E_PASSWORD');
const VISIBILITIES: Visibility[] = ['public', 'restricted'];
const LIFECYCLE_GRANTED_PERMISSIONS = ['view_media', 'view_detection'] as const;
const LIFECYCLE_EXTENSION_SECONDS = 3600;
const TRUSTED_DURATION_SECONDS = 30 * 24 * 3600;

interface TrustedProject extends SeededProject {
  trustedOverlayId: string;
}

interface LifecycleTrustedProject extends TrustedProject {
  trustedLifecycleOverlayId: string;
  trustedExpiredOverlayId: string;
}

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

const TRUSTED_LIFECYCLE_USER = {
  email: readEnv('E2E_TRUSTED_LIFECYCLE_EMAIL'),
  userId: readEnv('E2E_TRUSTED_LIFECYCLE_USER_ID'),
  totpSecret: readEnv('E2E_TRUSTED_LIFECYCLE_TOTP_SECRET'),
  apiKey: readEnv('E2E_TRUSTED_LIFECYCLE_API_KEY'),
};

const PROJECTS: Record<Visibility, TrustedProject> = {
  public: {
    visibility: 'public',
    id: readEnv('E2E_PUBLIC_PROJECT_ID'),
    name: readEnv('E2E_PUBLIC_PROJECT_NAME'),
    trustedOverlayId: readEnv('E2E_PUBLIC_TRUSTED_OVERLAY_ID'),
  },
  restricted: {
    visibility: 'restricted',
    id: readEnv('E2E_RESTRICTED_PROJECT_ID'),
    name: readEnv('E2E_RESTRICTED_PROJECT_NAME'),
    trustedOverlayId: readEnv('E2E_RESTRICTED_TRUSTED_OVERLAY_ID'),
  },
};

const LIFECYCLE_PROJECT: LifecycleTrustedProject = {
  ...PROJECTS.restricted,
  trustedLifecycleOverlayId: readEnv('E2E_RESTRICTED_TRUSTED_LIFECYCLE_OVERLAY_ID'),
  trustedExpiredOverlayId: readEnv('E2E_RESTRICTED_TRUSTED_EXPIRED_OVERLAY_ID'),
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
  'E2E_TRUSTED_USER_ID',
  'E2E_TRUSTED_TOTP_SECRET',
  'E2E_TRUSTED_API_KEY',
  'E2E_TRUSTED_LIFECYCLE_EMAIL',
  'E2E_TRUSTED_LIFECYCLE_USER_ID',
  'E2E_TRUSTED_LIFECYCLE_TOTP_SECRET',
  'E2E_TRUSTED_LIFECYCLE_API_KEY',
  'E2E_PUBLIC_PROJECT_ID',
  'E2E_PUBLIC_PROJECT_NAME',
  'E2E_PUBLIC_TRUSTED_OVERLAY_ID',
  'E2E_RESTRICTED_PROJECT_ID',
  'E2E_RESTRICTED_PROJECT_NAME',
  'E2E_RESTRICTED_TRUSTED_OVERLAY_ID',
  'E2E_RESTRICTED_TRUSTED_LIFECYCLE_OVERLAY_ID',
  'E2E_RESTRICTED_TRUSTED_EXPIRED_OVERLAY_ID',
] as const;

const MISSING_ENV = missingEnv(REQUIRED_ENV);

interface TrustedOverlayResponse {
  id?: string;
  status?: string;
  user_id?: string;
  expires_at?: string;
  granted_permissions?: string[];
}

interface TrustedOverlayListResponse {
  items?: TrustedOverlayResponse[];
}

async function getCsrfTokenAfterLogin(page: Page): Promise<string> {
  const cookies = await page.context().cookies();
  const csrf = cookies.find((cookie) => cookie.name === 'echoroo_csrf')?.value ?? '';

  expect(
    csrf.length,
    'echoroo_csrf cookie must be present after UI login for trusted overlay mutations'
  ).toBeGreaterThan(0);
  return csrf;
}

async function trustedMutationHeaders(
  page: Page,
  webBearer: string
): Promise<Record<string, string>> {
  return {
    Authorization: `Bearer ${webBearer}`,
    'Content-Type': 'application/json',
    'X-CSRF-Token': await getCsrfTokenAfterLogin(page),
  };
}

async function getTrustedOverlay(
  page: Page,
  webBearer: string,
  project: SeededProject,
  status: 'active' | 'expired' | 'revoked',
  overlayId: string
): Promise<TrustedOverlayResponse | undefined> {
  const response = await page.request.get(
    `/web-api/v1/projects/${project.id}/trusted-users?status=${status}`,
    {
      headers: { Authorization: `Bearer ${webBearer}` },
      failOnStatusCode: false,
    }
  );
  await expectStatus(response, 200, `GET ${status} trusted users for ${project.visibility}`);

  const data = (await response.json()) as TrustedOverlayListResponse;
  return data.items?.find((item) => item.id === overlayId);
}

async function expectTrustedOverlayIsListed(
  page: Page,
  webBearer: string,
  project: TrustedProject
): Promise<void> {
  const response = await page.request.get(
    `/web-api/v1/projects/${project.id}/trusted-users?status=active`,
    {
      headers: { Authorization: `Bearer ${webBearer}` },
      failOnStatusCode: false,
    }
  );
  await expectStatus(response, 200, `GET trusted users for ${project.visibility}`);

  const data = (await response.json()) as {
    items?: Array<{
      id?: string;
      status?: string;
      user_id?: string;
      granted_permissions?: string[];
    }>;
  };
  const overlay = data.items?.find((item) => item.id === project.trustedOverlayId);

  expect(
    overlay,
    `${project.visibility} trusted overlay ${project.trustedOverlayId} should be listed`
  ).toBeTruthy();
  expect(overlay?.status, `${project.visibility} trusted overlay should be active`).toBe('active');
  expect(
    overlay?.user_id,
    `${project.visibility} trusted overlay should belong to the seeded trusted user`
  ).toBe(readEnv('E2E_TRUSTED_USER_ID'));
  expect(
    overlay?.granted_permissions,
    `${project.visibility} trusted overlay should grant export`
  ).toContain('export');
}

async function expectOwnerTrustedUi(page: Page, project: TrustedProject): Promise<void> {
  await page.goto(`/en/projects/${project.id}/trusted`);

  await expect(page.locator('[data-testid="trusted-page"]')).toBeVisible({ timeout: 15000 });
  await expect(page.locator('[data-testid="trusted-invite-form"]')).toBeVisible();
  await expect(page.locator('[data-testid="trusted-admin-readonly-notice"]')).toBeHidden();
  await expect(page.locator('[data-testid="trusted-users-list"]')).toBeVisible();
  await expect(page.locator(`[data-testid="trusted-row-${project.trustedOverlayId}"]`)).toBeVisible(
    { timeout: 15000 }
  );
  await expect(
    page.locator(`[data-testid="trusted-extend-${project.trustedOverlayId}"]`)
  ).toBeEnabled();
  await expect(
    page.locator(`[data-testid="trusted-edit-perms-${project.trustedOverlayId}"]`)
  ).toBeEnabled();
  await expect(
    page.locator(`[data-testid="trusted-revoke-${project.trustedOverlayId}"]`)
  ).toBeEnabled();
}

async function expectAdminTrustedUi(page: Page, project: TrustedProject): Promise<void> {
  await page.goto(`/en/projects/${project.id}/trusted`);

  await expect(page.locator('[data-testid="trusted-page"]')).toBeVisible({ timeout: 15000 });
  await expect(page.locator('[data-testid="trusted-admin-readonly-notice"]')).toBeVisible();
  await expect(page.locator('[data-testid="trusted-invite-form"]')).toBeHidden();
  await expect(page.locator('[data-testid="trusted-users-list"]')).toBeVisible();
  await expect(page.locator(`[data-testid="trusted-row-${project.trustedOverlayId}"]`)).toBeVisible(
    { timeout: 15000 }
  );
  await expect(
    page.locator(`[data-testid="trusted-extend-${project.trustedOverlayId}"]`)
  ).toBeDisabled();
  await expect(
    page.locator(`[data-testid="trusted-edit-perms-${project.trustedOverlayId}"]`)
  ).toBeDisabled();
  await expect(
    page.locator(`[data-testid="trusted-revoke-${project.trustedOverlayId}"]`)
  ).toBeDisabled();
}

async function expectNoTrustedManagementUi(page: Page, project: TrustedProject): Promise<void> {
  await page.goto(`/en/projects/${project.id}/trusted`);

  await page
    .waitForURL(new RegExp(`/projects/${project.id}/?$`), { timeout: 15000 })
    .catch(() => undefined);

  await expect(page.locator('[data-testid="trusted-invite-form"]')).toBeHidden();
  await expect(page.locator('[data-testid="trusted-users-list"]')).toBeHidden();
  await expect(
    page.locator(`[data-testid="trusted-row-${project.trustedOverlayId}"]`)
  ).toBeHidden();
}

async function expectApiStatus(
  page: Page,
  role: Role,
  path: string,
  expected: number
): Promise<void> {
  const response = await page.request.get(backendApiUrl(path), {
    headers: { Authorization: `Bearer ${USERS[role].apiKey}` },
    failOnStatusCode: false,
  });
  await expectStatus(response, expected, `${role} GET ${path}`);
}

test.describe('Seeded trusted overlay permissions @e2e-trusted-overlay', () => {
  test.describe.configure({ timeout: 120000 });

  test.beforeEach(() => {
    test.skip(
      !SUITE_ENABLED,
      'E2E_TRUSTED_OVERLAY_ENABLED=1 is required to run seeded trusted overlay tests.'
    );
    test.skip(
      MISSING_ENV.length > 0,
      `Missing required seeded trusted overlay env vars: ${MISSING_ENV.join(', ')}. ` +
        'Run seed_e2e_permissions.py --confirm and export payload.env.'
    );
  });

  test('owner sees active trusted overlays and full management controls', async ({ page }) => {
    await login(page, USERS.owner);
    const webBearer = await getBearerTokenAfterLogin(page);

    for (const visibility of VISIBILITIES) {
      const project = PROJECTS[visibility];
      await expectOwnerTrustedUi(page, project);
      await expectTrustedOverlayIsListed(page, webBearer, project);
    }
  });

  test('admin sees active trusted overlays in read-only mode', async ({ page }) => {
    await login(page, USERS.admin);
    const webBearer = await getBearerTokenAfterLogin(page);

    for (const visibility of VISIBILITIES) {
      const project = PROJECTS[visibility];
      await expectAdminTrustedUi(page, project);
      await expectTrustedOverlayIsListed(page, webBearer, project);
    }
  });

  for (const role of ['member', 'viewer', 'nonmember', 'trusted'] as const) {
    test(`${role} cannot access trusted overlay management UI`, async ({ page }) => {
      await login(page, USERS[role]);
      await expectNoTrustedManagementUi(page, PROJECTS.public);
    });
  }

  test('trusted overlay grants restricted project API capabilities without membership', async ({
    page,
  }) => {
    const project = PROJECTS.restricted;

    await expectApiStatus(page, 'trusted', `/api/v1/projects/${project.id}/search/sessions`, 200);
    await expectApiStatus(page, 'nonmember', `/api/v1/projects/${project.id}/search/sessions`, 403);
    await expectApiStatus(
      page,
      'trusted',
      `/api/v1/projects/${project.id}/detections/export/csv`,
      200
    );
    await expectApiStatus(
      page,
      'viewer',
      `/api/v1/projects/${project.id}/detections/export/csv`,
      403
    );
    await expectApiStatus(
      page,
      'nonmember',
      `/api/v1/projects/${project.id}/detections/export/csv`,
      403
    );
  });

  test.describe.serial('trusted overlay lifecycle API', () => {
    test('owner can PATCH disposable overlay granted permissions', async ({ page }) => {
      const project = LIFECYCLE_PROJECT;

      await login(page, USERS.owner);
      const webBearer = await getBearerTokenAfterLogin(page);
      const headers = await trustedMutationHeaders(page, webBearer);

      const response = await page.request.patch(
        `/web-api/v1/projects/${project.id}/trusted-users/${project.trustedLifecycleOverlayId}`,
        {
          data: { granted_permissions: [...LIFECYCLE_GRANTED_PERMISSIONS] },
          headers,
          failOnStatusCode: false,
        }
      );
      await expectStatus(response, 200, 'owner PATCH trusted lifecycle permissions');

      const data = (await response.json()) as TrustedOverlayResponse;
      expect(data.id).toBe(project.trustedLifecycleOverlayId);
      expect(data.user_id).toBe(TRUSTED_LIFECYCLE_USER.userId);
      expect(data.granted_permissions?.sort()).toEqual([...LIFECYCLE_GRANTED_PERMISSIONS].sort());

      const listed = await getTrustedOverlay(
        page,
        webBearer,
        project,
        'active',
        project.trustedLifecycleOverlayId
      );
      expect(listed?.granted_permissions?.sort()).toEqual(
        [...LIFECYCLE_GRANTED_PERMISSIONS].sort()
      );
    });

    test('owner can PATCH disposable overlay expiry extension', async ({ page }) => {
      const project = LIFECYCLE_PROJECT;

      await login(page, USERS.owner);
      const webBearer = await getBearerTokenAfterLogin(page);
      const headers = await trustedMutationHeaders(page, webBearer);
      const before = await getTrustedOverlay(
        page,
        webBearer,
        project,
        'active',
        project.trustedLifecycleOverlayId
      );

      expect(before?.expires_at, 'lifecycle overlay should have an initial expiry').toBeTruthy();
      const beforeExpiryMs = Date.parse(before?.expires_at ?? '');

      const response = await page.request.patch(
        `/web-api/v1/projects/${project.id}/trusted-users/${project.trustedLifecycleOverlayId}`,
        {
          data: { extension_seconds: LIFECYCLE_EXTENSION_SECONDS },
          headers,
          failOnStatusCode: false,
        }
      );
      await expectStatus(response, 200, 'owner PATCH trusted lifecycle expiry');

      const data = (await response.json()) as TrustedOverlayResponse;
      const afterExpiryMs = Date.parse(data.expires_at ?? '');
      expect(afterExpiryMs, 'lifecycle overlay expires_at should increase').toBeGreaterThan(
        beforeExpiryMs
      );
    });

    test('admin cannot PATCH or DELETE disposable overlay', async ({ page }) => {
      const project = LIFECYCLE_PROJECT;

      await login(page, USERS.admin);
      const webBearer = await getBearerTokenAfterLogin(page);
      const headers = await trustedMutationHeaders(page, webBearer);

      const patchResponse = await page.request.patch(
        `/web-api/v1/projects/${project.id}/trusted-users/${project.trustedLifecycleOverlayId}`,
        {
          data: { granted_permissions: ['view_media'] },
          headers,
          failOnStatusCode: false,
        }
      );
      await expectStatus(patchResponse, 403, 'admin PATCH trusted lifecycle overlay');

      const deleteResponse = await page.request.delete(
        `/web-api/v1/projects/${project.id}/trusted-users/${project.trustedLifecycleOverlayId}`,
        {
          headers,
          failOnStatusCode: false,
        }
      );
      await expectStatus(deleteResponse, 403, 'admin DELETE trusted lifecycle overlay');
    });

    test('owner can DELETE disposable overlay and revoked filter includes it', async ({ page }) => {
      const project = LIFECYCLE_PROJECT;

      await login(page, USERS.owner);
      const webBearer = await getBearerTokenAfterLogin(page);
      const headers = await trustedMutationHeaders(page, webBearer);

      const deleteResponse = await page.request.delete(
        `/web-api/v1/projects/${project.id}/trusted-users/${project.trustedLifecycleOverlayId}`,
        {
          headers,
          failOnStatusCode: false,
        }
      );
      await expectStatus(deleteResponse, 204, 'owner DELETE trusted lifecycle overlay');

      const revoked = await getTrustedOverlay(
        page,
        webBearer,
        project,
        'revoked',
        project.trustedLifecycleOverlayId
      );
      expect(revoked?.status).toBe('revoked');

      const capabilityResponse = await page.request.get(
        backendApiUrl(`/api/v1/projects/${project.id}/search/sessions`),
        {
          headers: { Authorization: `Bearer ${TRUSTED_LIFECYCLE_USER.apiKey}` },
          failOnStatusCode: false,
        }
      );
      await expectStatus(capabilityResponse, 403, 'trusted lifecycle API key after overlay revoke');
    });

    test('owner can issue a fresh trusted invitation after lifecycle revoke', async ({
      page,
    }, testInfo) => {
      const project = LIFECYCLE_PROJECT;
      const uniqueEmail = `e2e-trusted-lifecycle-${Date.now()}-${testInfo.workerIndex}@echoroo.app`;

      await login(page, USERS.owner);
      const webBearer = await getBearerTokenAfterLogin(page);
      const headers = await trustedMutationHeaders(page, webBearer);

      const response = await page.request.post(`/web-api/v1/projects/${project.id}/trusted-users`, {
        data: {
          email: uniqueEmail,
          granted_permissions: ['view_media', 'view_detection'],
          duration_seconds: TRUSTED_DURATION_SECONDS,
        },
        headers,
        failOnStatusCode: false,
      });
      await expectStatus(response, 202, 'owner POST fresh trusted lifecycle invitation');

      const data = (await response.json()) as { invitation_id?: string };
      expect(
        data.invitation_id,
        'trusted lifecycle invite should return invitation_id'
      ).toBeTruthy();
    });

    test('expired seeded overlay is listed by expired filter', async ({ page }) => {
      const project = LIFECYCLE_PROJECT;

      await login(page, USERS.owner);
      const webBearer = await getBearerTokenAfterLogin(page);

      const expired = await getTrustedOverlay(
        page,
        webBearer,
        project,
        'expired',
        project.trustedExpiredOverlayId
      );

      expect(expired?.status).toBe('expired');
      expect(expired?.user_id).toBe(TRUSTED_LIFECYCLE_USER.userId);
    });
  });
});
