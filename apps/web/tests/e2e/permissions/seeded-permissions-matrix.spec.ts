/**
 * Seeded permission matrix E2E suite.
 *
 * Requires the fixture payload from:
 *   uv run python -m echoroo.scripts.seed_e2e_permissions --confirm
 */

import { expect, test, type Page } from '@playwright/test';
import {
  login,
  missingEnv,
  readEnv,
  type MatrixRole,
  type SeededProject,
  type Visibility,
} from './seeded-permissions.helpers';

type Role = MatrixRole;

interface TestUser {
  role: Role;
  email: string;
  password: string;
  totpSecret: string;
}

const SUITE_ENABLED = process.env.E2E_PERMISSIONS_MATRIX_ENABLED === '1';
const PASSWORD = readEnv('E2E_PASSWORD');
const ROLES: Role[] = ['owner', 'admin', 'member', 'viewer', 'nonmember'];
const VISIBILITIES: Visibility[] = ['public', 'restricted'];

const USERS: Record<Role, TestUser> = {
  owner: {
    role: 'owner',
    email: readEnv('E2E_OWNER_EMAIL'),
    password: PASSWORD,
    totpSecret: readEnv('E2E_OWNER_TOTP_SECRET'),
  },
  admin: {
    role: 'admin',
    email: readEnv('E2E_ADMIN_EMAIL'),
    password: PASSWORD,
    totpSecret: readEnv('E2E_ADMIN_TOTP_SECRET'),
  },
  member: {
    role: 'member',
    email: readEnv('E2E_MEMBER_EMAIL'),
    password: PASSWORD,
    totpSecret: readEnv('E2E_MEMBER_TOTP_SECRET'),
  },
  viewer: {
    role: 'viewer',
    email: readEnv('E2E_VIEWER_EMAIL'),
    password: PASSWORD,
    totpSecret: readEnv('E2E_VIEWER_TOTP_SECRET'),
  },
  nonmember: {
    role: 'nonmember',
    email: readEnv('E2E_NONMEMBER_EMAIL'),
    password: PASSWORD,
    totpSecret: readEnv('E2E_NONMEMBER_TOTP_SECRET'),
  },
};

const PROJECTS: Record<Visibility, SeededProject> = {
  public: {
    visibility: 'public',
    id: readEnv('E2E_PUBLIC_PROJECT_ID'),
    name: readEnv('E2E_PUBLIC_PROJECT_NAME'),
  },
  restricted: {
    visibility: 'restricted',
    id: readEnv('E2E_RESTRICTED_PROJECT_ID'),
    name: readEnv('E2E_RESTRICTED_PROJECT_NAME'),
  },
};

const REQUIRED_ENV = [
  'E2E_PASSWORD',
  'E2E_OWNER_EMAIL',
  'E2E_OWNER_TOTP_SECRET',
  'E2E_ADMIN_EMAIL',
  'E2E_ADMIN_TOTP_SECRET',
  'E2E_MEMBER_EMAIL',
  'E2E_MEMBER_TOTP_SECRET',
  'E2E_VIEWER_EMAIL',
  'E2E_VIEWER_TOTP_SECRET',
  'E2E_NONMEMBER_EMAIL',
  'E2E_NONMEMBER_TOTP_SECRET',
  'E2E_PUBLIC_PROJECT_ID',
  'E2E_PUBLIC_PROJECT_NAME',
  'E2E_RESTRICTED_PROJECT_ID',
  'E2E_RESTRICTED_PROJECT_NAME',
] as const;

const MISSING_ENV = missingEnv(REQUIRED_ENV);
const AUTH_DECISION_TIMEOUT_MS = 15000;

async function expectProjectDetail(
  page: Page,
  user: TestUser,
  project: SeededProject
): Promise<void> {
  await page.goto(`/en/projects/${project.id}`);
  await expect(page.locator('h1', { hasText: project.name })).toBeVisible({ timeout: 15000 });

  const settingsButton = page.getByRole('button', { name: 'Settings', exact: true });
  const deleteButton = page.getByRole('button', { name: 'Delete', exact: true });
  const requestAccessCallout = page.locator('[data-testid="restricted-request-access"]');

  if (user.role === 'owner' || user.role === 'admin') {
    await expect(settingsButton).toBeVisible();
  } else {
    await expect(settingsButton).toBeHidden();
  }

  if (user.role === 'owner') {
    await expect(deleteButton).toBeVisible();
  } else {
    await expect(deleteButton).toBeHidden();
  }

  if (project.visibility === 'restricted' && user.role === 'nonmember') {
    await expect(requestAccessCallout).toBeVisible();
    await expect(page.getByRole('link', { name: 'Request access', exact: true })).toBeVisible();
  } else {
    await expect(requestAccessCallout).toBeHidden();
  }
}

async function expectDenied(page: Page, messages: RegExp[]): Promise<void> {
  for (const [index, message] of messages.entries()) {
    const denied = page.locator('[role="alert"]').filter({ hasText: message });
    const timeout = index === 0 ? AUTH_DECISION_TIMEOUT_MS : 1000;
    try {
      await expect(denied).toBeVisible({ timeout });
      return;
    } catch {
      // Try the next accepted denial message before collecting failure diagnostics.
    }
  }

  const alerts = page.locator('[role="alert"]');
  const alertTexts: string[] = [];
  for (let index = 0; index < (await alerts.count().catch(() => 0)); index += 1) {
    const alert = alerts.nth(index);
    if (await alert.isVisible().catch(() => false)) {
      const text = await alert.textContent().catch(() => null);
      if (text?.trim()) {
        alertTexts.push(text.trim());
      }
    }
  }

  throw new Error(
    `Expected one of these access-denied messages: ${messages.map(String).join(', ')}. ` +
      `Current URL: ${page.url()}. Visible alert text: ${
        alertTexts
          .map((text) => text.trim())
          .filter(Boolean)
          .join(' | ') || '<no visible alert text>'
      }`
  );
}

async function expectSettingsRoute(
  page: Page,
  user: TestUser,
  project: SeededProject
): Promise<void> {
  await page.goto(`/en/projects/${project.id}/settings`);
  if (user.role === 'owner' || user.role === 'admin') {
    await expect(page.locator('h1', { hasText: 'Project Settings' })).toBeVisible({
      timeout: 15000,
    });
    await expect(page.locator('input[name="name"]')).toHaveValue(project.name);
  } else {
    await expectDenied(page, [
      /You do not have permission to edit this project/,
      /You do not have permission to access this project/,
    ]);
  }
}

async function expectMembersRoute(
  page: Page,
  user: TestUser,
  project: SeededProject
): Promise<void> {
  await page.goto(`/en/projects/${project.id}/members`);
  if (user.role === 'owner' || user.role === 'admin') {
    await expect(page.locator('h1', { hasText: 'Members' })).toBeVisible({ timeout: 15000 });
    await expect(page.getByRole('button', { name: 'Add Member', exact: true })).toBeVisible();
  } else {
    await expectDenied(page, [
      /You do not have permission to manage project members/,
      /You do not have permission to access this project/,
    ]);
  }
}

test.describe('Seeded permissions matrix @e2e-permissions-matrix', () => {
  test.describe.configure({ timeout: 60000 });

  test.beforeEach(() => {
    test.skip(
      !SUITE_ENABLED,
      'E2E_PERMISSIONS_MATRIX_ENABLED=1 is required to run seeded permissions matrix.'
    );
    test.skip(
      MISSING_ENV.length > 0,
      `Missing required seeded permission env vars: ${MISSING_ENV.join(', ')}. ` +
        'Run seed_e2e_permissions.py --confirm and export payload.env.'
    );
  });

  for (const role of ROLES) {
    for (const visibility of VISIBILITIES) {
      test(`${role} permissions on ${visibility} project`, async ({ page }) => {
        const user = USERS[role];
        const project = PROJECTS[visibility];

        await login(page, user);
        await expectProjectDetail(page, user, project);
        await expectSettingsRoute(page, user, project);
        await expectMembersRoute(page, user, project);
      });
    }
  }
});
