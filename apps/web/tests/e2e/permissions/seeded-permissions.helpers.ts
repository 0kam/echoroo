import { expect, type APIResponse, type Page, type Response } from '@playwright/test';
import { generateTotpCode, waitForFreshTotpWindow } from '../helpers/totp';

export type Role = 'owner' | 'admin' | 'member' | 'viewer' | 'nonmember' | 'trusted';
export type MatrixRole = Exclude<Role, 'trusted'>;
export type Visibility = 'public' | 'restricted';

export interface SeededTestUser {
  role: Role;
  email: string;
  password: string;
  totpSecret: string;
}

export interface SeededApiTestUser extends SeededTestUser {
  apiKey: string;
}

export interface SeededProject {
  visibility: Visibility;
  id: string;
  name: string;
}

export interface SeededFeatureProject extends SeededProject {
  datasetId: string;
  datasetName: string;
  annotationId: string;
  trustedOverlayId: string;
}

const BACKEND_API_BASE_URL = (
  process.env.ECHOROO_API_URL ??
  process.env.PUBLIC_API_URL ??
  'http://localhost:8002'
).replace(/\/+$/, '');

const AUTH_DECISION_TIMEOUT_MS = 15000;
const LOGIN_SUBMIT_ATTEMPTS = 3;
const LOGIN_SUBMIT_DECISION_TIMEOUT_MS = 2500;
const LOGIN_SUBMIT_RETRY_DELAY_MS = 300;

type AuthDecision = 'off-login' | 'two-factor' | 'error';

export function readEnv(name: string): string {
  return process.env[name] ?? '';
}

export function missingEnv(requiredEnv: readonly string[]): string[] {
  return requiredEnv.filter((name) => !process.env[name]);
}

export function backendApiUrl(path: string): string {
  return `${BACKEND_API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`;
}

export async function expectStatus(
  response: APIResponse,
  expected: number | number[],
  label: string
): Promise<void> {
  const expectedStatuses = Array.isArray(expected) ? expected : [expected];
  if (expectedStatuses.includes(response.status())) {
    return;
  }

  expect(
    expectedStatuses,
    `${label} ${response.url()} returned ${response.status()} instead of ${expectedStatuses.join(
      ' or '
    )}. Body: ${await response.text().catch(() => '<unavailable>')}`
  ).toContain(response.status());
}

function isOffLoginPath(pathname: string): boolean {
  return !pathname.replace(/^\/[a-z]{2}(?=\/)/, '').startsWith('/login');
}

async function waitForAuthDecision(
  page: Page,
  timeout = AUTH_DECISION_TIMEOUT_MS
): Promise<AuthDecision> {
  await page.waitForFunction(
    () => {
      const normalizedPath = window.location.pathname.replace(/^\/[a-z]{2}(?=\/)/, '');
      return (
        !normalizedPath.startsWith('/login') ||
        document.querySelector('[data-testid="two-factor-form"]') !== null ||
        document.querySelector('[role="alert"]') !== null
      );
    },
    null,
    { timeout }
  );

  if (isOffLoginPath(new URL(page.url()).pathname)) {
    return 'off-login';
  }
  if (
    await page
      .locator('[data-testid="two-factor-form"]')
      .isVisible()
      .catch(() => false)
  ) {
    return 'two-factor';
  }
  return 'error';
}

async function waitForCompletedLogin(page: Page): Promise<'off-login' | 'error'> {
  await page.waitForFunction(
    () => {
      const normalizedPath = window.location.pathname.replace(/^\/[a-z]{2}(?=\/)/, '');
      return (
        !normalizedPath.startsWith('/login') ||
        document.querySelector('[data-testid="two-factor-error"]') !== null ||
        document.querySelector('[role="alert"]') !== null
      );
    },
    null,
    { timeout: AUTH_DECISION_TIMEOUT_MS }
  );

  return isOffLoginPath(new URL(page.url()).pathname) ? 'off-login' : 'error';
}

async function visibleAlertText(page: Page): Promise<string> {
  const text = await page
    .locator('[role="alert"]')
    .first()
    .textContent()
    .catch(() => null);
  return text?.trim() ?? '<no visible alert text>';
}

async function waitForWebAuthResponse(
  page: Page,
  path: string,
  timeout = AUTH_DECISION_TIMEOUT_MS
): Promise<Response | null> {
  return page
    .waitForResponse(
      (response) =>
        response.url().includes(`/web-api/v1/auth/${path}`) &&
        response.request().method() === 'POST',
      { timeout }
    )
    .catch(() => null);
}

async function responseText(response: Response | null): Promise<string> {
  if (!response) return '<no response captured>';
  return response.text().catch(() => '<response body unavailable>');
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

async function isCredentialFormVisible(page: Page): Promise<boolean> {
  const emailVisible = await page
    .locator('input[name="email"]')
    .isVisible()
    .catch(() => false);
  const passwordVisible = await page
    .locator('input[name="password"]')
    .isVisible()
    .catch(() => false);
  return emailVisible && passwordVisible;
}

async function submitCredentialsWithRetry(page: Page, user: SeededTestUser): Promise<AuthDecision> {
  const emailInput = page.locator('input[name="email"]');
  const passwordInput = page.locator('input[name="password"]');
  const submitButton = page.locator('button[type="submit"]');
  let lastUrl = page.url();
  let lastCredentialFormVisible = false;

  for (let attempt = 1; attempt <= LOGIN_SUBMIT_ATTEMPTS; attempt += 1) {
    await expect(emailInput).toBeVisible({ timeout: AUTH_DECISION_TIMEOUT_MS });
    await expect(passwordInput).toBeVisible({ timeout: AUTH_DECISION_TIMEOUT_MS });
    await emailInput.fill(user.email);
    await passwordInput.fill(user.password);

    const loginResponsePromise = waitForWebAuthResponse(
      page,
      'login',
      LOGIN_SUBMIT_DECISION_TIMEOUT_MS
    );
    await submitButton.click();

    const [loginResponse, quickDecision] = await Promise.all([
      loginResponsePromise,
      waitForAuthDecision(page, LOGIN_SUBMIT_DECISION_TIMEOUT_MS).catch(() => null),
    ]);
    if (loginResponse && !loginResponse.ok()) {
      throw new Error(
        `Login failed for ${user.role} (${user.email}) with ${loginResponse.status()}: ` +
          `${await responseText(loginResponse)}`
      );
    }
    if (quickDecision) {
      return quickDecision;
    }
    if (loginResponse) {
      const decision = await waitForAuthDecision(page).catch((error: unknown) => {
        throw new Error(
          `Login response was received for ${user.role} (${user.email}), but the page did not ` +
            `show TOTP, an alert, or leave /login within ${AUTH_DECISION_TIMEOUT_MS}ms: ` +
            `${errorMessage(error)}`
        );
      });
      return decision;
    }

    lastUrl = page.url();
    lastCredentialFormVisible = await isCredentialFormVisible(page);
    if (!lastCredentialFormVisible || attempt === LOGIN_SUBMIT_ATTEMPTS) {
      break;
    }

    await page.waitForTimeout(LOGIN_SUBMIT_RETRY_DELAY_MS);
  }

  throw new Error(
    `Login submit did not produce a /web-api/v1/auth/login response, TOTP form, off-login ` +
      `navigation, or alert after ${LOGIN_SUBMIT_ATTEMPTS} attempts for ${user.role} ` +
      `(${user.email}). Current URL: ${lastUrl}; credential form visible: ` +
      `${lastCredentialFormVisible ? 'yes' : 'no'}.`
  );
}

export async function login(page: Page, user: SeededTestUser): Promise<void> {
  await page.goto('/en/login');

  const firstDecision = await submitCredentialsWithRetry(page, user);

  if (firstDecision === 'off-login') {
    return;
  }
  if (firstDecision === 'error') {
    throw new Error(
      `Login failed for ${user.role} (${user.email}): ${await visibleAlertText(page)}`
    );
  }
  if (!user.totpSecret) {
    throw new Error(`Missing TOTP secret for ${user.role} (${user.email})`);
  }

  await waitForFreshTotpWindow();
  await page
    .locator('[data-testid="two-factor-code-input"]')
    .fill(generateTotpCode(user.totpSecret));

  const challengeResponsePromise = waitForWebAuthResponse(page, '2fa/challenge');
  await page.locator('[data-testid="two-factor-submit"]').click();

  const [challengeResponse, secondDecision] = await Promise.all([
    challengeResponsePromise,
    waitForCompletedLogin(page),
  ]);
  if (challengeResponse && !challengeResponse.ok()) {
    throw new Error(
      `2FA challenge failed for ${user.role} (${user.email}) with ${challengeResponse.status()}: ` +
        `${await responseText(challengeResponse)}`
    );
  }
  if (secondDecision !== 'off-login') {
    throw new Error(
      `2FA login failed for ${user.role} (${user.email}): ${await visibleAlertText(page)}`
    );
  }
}

export async function getBearerTokenAfterLogin(page: Page): Promise<string> {
  const response = await page.request.post('/web-api/v1/auth/refresh', {
    failOnStatusCode: false,
  });
  if (response.status() !== 200) {
    throw new Error(
      `web-api/v1/auth/refresh returned ${response.status()} after UI login. ` +
        `Body: ${await response.text().catch(() => '<unavailable>')}`
    );
  }

  const data = (await response.json()) as { access_token?: string };
  if (!data.access_token) {
    throw new Error('web-api/v1/auth/refresh succeeded but did not return access_token');
  }
  return data.access_token;
}
