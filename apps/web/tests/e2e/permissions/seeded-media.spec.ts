/**
 * Seeded media permission E2E suite.
 *
 * Requires the fixture payload from:
 *   uv run python -m echoroo.scripts.seed_e2e_permissions --confirm
 */

import { expect, test, type APIResponse } from '@playwright/test';
import {
  backendApiUrl,
  expectStatus,
  login,
  missingEnv,
  readEnv,
  type Role,
  type SeededApiTestUser,
  type SeededProject,
  type Visibility,
} from './seeded-permissions.helpers';

const SUITE_ENABLED = process.env.E2E_MEDIA_ENABLED === '1';
const PASSWORD = readEnv('E2E_PASSWORD');
const ROLES: Role[] = ['owner', 'admin', 'member', 'viewer', 'nonmember', 'trusted'];
const VISIBILITIES: Visibility[] = ['public', 'restricted'];

interface SeededMediaProject extends SeededProject {
  recordingId: string;
  clipId: string;
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

const PROJECTS: Record<Visibility, SeededMediaProject> = {
  public: {
    visibility: 'public',
    id: readEnv('E2E_PUBLIC_PROJECT_ID'),
    name: readEnv('E2E_PUBLIC_PROJECT_NAME'),
    recordingId: readEnv('E2E_PUBLIC_RECORDING_ID'),
    clipId: readEnv('E2E_PUBLIC_CLIP_ID'),
  },
  restricted: {
    visibility: 'restricted',
    id: readEnv('E2E_RESTRICTED_PROJECT_ID'),
    name: readEnv('E2E_RESTRICTED_PROJECT_NAME'),
    recordingId: readEnv('E2E_RESTRICTED_RECORDING_ID'),
    clipId: readEnv('E2E_RESTRICTED_CLIP_ID'),
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
  'E2E_PUBLIC_RECORDING_ID',
  'E2E_PUBLIC_CLIP_ID',
  'E2E_RESTRICTED_PROJECT_ID',
  'E2E_RESTRICTED_PROJECT_NAME',
  'E2E_RESTRICTED_RECORDING_ID',
  'E2E_RESTRICTED_CLIP_ID',
] as const;

const MISSING_ENV = missingEnv(REQUIRED_ENV);

type MediaEndpoint = 'audio' | 'playback' | 'spectrogram' | 'download';
type ClipMediaEndpoint = 'audio' | 'spectrogram' | 'download';
type MediaStatusExpectation = number | number[];
type AuthenticatedMediaExpectations = Record<
  Visibility,
  Record<Role, Record<MediaEndpoint, MediaStatusExpectation>>
>;
type AuthenticatedClipMediaExpectations = Record<
  Visibility,
  Record<Role, Record<ClipMediaEndpoint, MediaStatusExpectation>>
>;
type GuestMediaEndpoint = Exclude<MediaEndpoint, 'download'>;
type GuestMediaExpectations = Record<
  Visibility,
  Record<GuestMediaEndpoint, MediaStatusExpectation>
>;
type GuestClipMediaExpectations = Record<
  Visibility,
  Record<ClipMediaEndpoint, MediaStatusExpectation>
>;

interface MediaCase {
  endpoint: MediaEndpoint;
  path: string;
  expectedContentType: RegExp;
  minBytes: number;
  validateBody?: (body: Buffer, label: string) => void;
}

interface ClipMediaCase {
  endpoint: ClipMediaEndpoint;
  path: string;
  expectedContentType: RegExp;
  minBytes: number;
  validateBody: (body: Buffer, label: string) => void;
}

const MEDIA_CASES: MediaCase[] = [
  {
    endpoint: 'audio',
    path: 'audio',
    expectedContentType: /^audio\//,
    minBytes: 16,
  },
  {
    endpoint: 'playback',
    path: 'playback',
    expectedContentType: /^audio\//,
    minBytes: 16,
  },
  {
    endpoint: 'spectrogram',
    path: 'spectrogram?end=1&width=320&height=120',
    expectedContentType: /^image\/png/,
    minBytes: 128,
    validateBody: (body, label) => {
      expect(body.subarray(0, 8).toString('hex'), `${label} should return PNG bytes`).toBe(
        '89504e470d0a1a0a'
      );
    },
  },
  {
    endpoint: 'download',
    path: 'download',
    expectedContentType: /^audio\//,
    minBytes: 128,
    validateBody: (body, label) => {
      expect(body.subarray(0, 4).toString('ascii'), `${label} should return WAV bytes`).toBe(
        'RIFF'
      );
    },
  },
];

const CLIP_MEDIA_CASES: ClipMediaCase[] = [
  {
    endpoint: 'audio',
    path: 'audio',
    expectedContentType: /^audio\/wav/,
    minBytes: 128,
    validateBody: (body, label) => {
      expect(body.subarray(0, 4).toString('ascii'), `${label} should return WAV bytes`).toBe(
        'RIFF'
      );
    },
  },
  {
    endpoint: 'spectrogram',
    path: 'spectrogram?width=320&height=120',
    expectedContentType: /^image\/png/,
    minBytes: 128,
    validateBody: (body, label) => {
      expect(body.subarray(0, 8).toString('hex'), `${label} should return PNG bytes`).toBe(
        '89504e470d0a1a0a'
      );
    },
  },
  {
    endpoint: 'download',
    path: 'download',
    expectedContentType: /^audio\/wav/,
    minBytes: 128,
    validateBody: (body, label) => {
      expect(body.subarray(0, 4).toString('ascii'), `${label} should return WAV bytes`).toBe(
        'RIFF'
      );
    },
  },
];

const GUEST_MEDIA_CASES: Array<MediaCase & { endpoint: GuestMediaEndpoint }> = MEDIA_CASES.filter(
  (mediaCase): mediaCase is MediaCase & { endpoint: GuestMediaEndpoint } =>
    mediaCase.endpoint !== 'download'
);

// Recording download is intentionally modeled as VIEW_MEDIA-gated in this suite,
// matching RECORDING_MEDIA_ACTION rather than a separate DOWNLOAD permission.
const AUTHENTICATED_MEDIA_EXPECTATIONS: AuthenticatedMediaExpectations = {
  public: {
    owner: { audio: [200, 206], playback: [200, 206], spectrogram: 200, download: 200 },
    admin: { audio: [200, 206], playback: [200, 206], spectrogram: 200, download: 200 },
    member: { audio: [200, 206], playback: [200, 206], spectrogram: 200, download: 200 },
    viewer: { audio: [200, 206], playback: [200, 206], spectrogram: 200, download: 200 },
    nonmember: { audio: [200, 206], playback: [200, 206], spectrogram: 200, download: 200 },
    trusted: { audio: [200, 206], playback: [200, 206], spectrogram: 200, download: 200 },
  },
  restricted: {
    owner: { audio: [200, 206], playback: [200, 206], spectrogram: 200, download: 200 },
    admin: { audio: [200, 206], playback: [200, 206], spectrogram: 200, download: 200 },
    member: { audio: [200, 206], playback: [200, 206], spectrogram: 200, download: 200 },
    viewer: { audio: [200, 206], playback: [200, 206], spectrogram: 200, download: 200 },
    nonmember: { audio: [200, 206], playback: [200, 206], spectrogram: 200, download: 200 },
    trusted: { audio: [200, 206], playback: [200, 206], spectrogram: 200, download: 200 },
  },
};

const GUEST_MEDIA_EXPECTATIONS: GuestMediaExpectations = {
  public: {
    audio: [200, 206],
    playback: [200, 206],
    spectrogram: 200,
  },
  restricted: {
    audio: [200, 206],
    playback: [200, 206],
    spectrogram: 200,
  },
};

// Clip audio/spectrogram are VIEW_MEDIA-gated. Clip download is DOWNLOAD-gated.
const AUTHENTICATED_CLIP_MEDIA_EXPECTATIONS: AuthenticatedClipMediaExpectations = {
  public: {
    owner: { audio: 200, spectrogram: 200, download: 200 },
    admin: { audio: 200, spectrogram: 200, download: 200 },
    member: { audio: 200, spectrogram: 200, download: 200 },
    viewer: { audio: 200, spectrogram: 200, download: 200 },
    nonmember: { audio: 200, spectrogram: 200, download: 200 },
    trusted: { audio: 200, spectrogram: 200, download: 200 },
  },
  restricted: {
    // Restricted public playback toggles allow VIEW_MEDIA without membership; download still requires DOWNLOAD.
    owner: { audio: 200, spectrogram: 200, download: 200 },
    admin: { audio: 200, spectrogram: 200, download: 200 },
    member: { audio: 200, spectrogram: 200, download: 200 },
    viewer: { audio: 200, spectrogram: 200, download: 403 },
    nonmember: { audio: 200, spectrogram: 200, download: 403 },
    trusted: { audio: 200, spectrogram: 200, download: 200 },
  },
};

const GUEST_CLIP_MEDIA_EXPECTATIONS: GuestClipMediaExpectations = {
  public: {
    audio: 401,
    spectrogram: 401,
    download: 401,
  },
  restricted: {
    audio: 401,
    spectrogram: 401,
    download: 401,
  },
};

function legacyMediaUrl(project: SeededMediaProject, mediaCase: MediaCase): string {
  return backendApiUrl(
    `/api/v1/projects/${project.id}/recordings/${project.recordingId}/${mediaCase.path}`
  );
}

function clipMediaUrl(project: SeededMediaProject, mediaCase: ClipMediaCase): string {
  return backendApiUrl(
    `/api/v1/projects/${project.id}/recordings/${project.recordingId}/clips/${project.clipId}/${mediaCase.path}`
  );
}

function mediaHeaders(user?: SeededApiTestUser, mediaCase?: MediaCase): Record<string, string> {
  const headers: Record<string, string> = {};
  if (user) {
    headers.Authorization = `Bearer ${user.apiKey}`;
  }
  if (mediaCase?.endpoint === 'audio' || mediaCase?.endpoint === 'playback') {
    headers.Range = 'bytes=0-255';
  }
  return headers;
}

async function expectMediaResponse(
  response: APIResponse,
  expectedStatus: MediaStatusExpectation,
  mediaCase: MediaCase,
  label: string
): Promise<void> {
  await expectStatus(response, expectedStatus, label);
  if (response.status() !== 200 && response.status() !== 206) {
    return;
  }

  expect(
    response.headers()['content-type'] ?? '',
    `${label} should return a media content type`
  ).toMatch(mediaCase.expectedContentType);

  const body = Buffer.from(await response.body());
  expect(body.length, `${label} should return real media bytes`).toBeGreaterThan(
    mediaCase.minBytes
  );
  mediaCase.validateBody?.(body, label);
}

async function expectClipMediaResponse(
  response: APIResponse,
  expectedStatus: MediaStatusExpectation,
  mediaCase: ClipMediaCase,
  label: string
): Promise<void> {
  await expectStatus(response, expectedStatus, label);
  if (response.status() !== 200) {
    return;
  }

  expect(
    response.headers()['content-type'] ?? '',
    `${label} should return a clip media content type`
  ).toMatch(mediaCase.expectedContentType);

  const body = Buffer.from(await response.body());
  expect(body.length, `${label} should return real clip media bytes`).toBeGreaterThan(
    mediaCase.minBytes
  );
  mediaCase.validateBody(body, label);
}

test.describe('Seeded media permissions @e2e-media', () => {
  test.describe.configure({ timeout: 120000 });

  test.beforeEach(() => {
    test.skip(!SUITE_ENABLED, 'E2E_MEDIA_ENABLED=1 is required to run seeded media permissions.');
    test.skip(
      MISSING_ENV.length > 0,
      `Missing required seeded media env vars: ${MISSING_ENV.join(', ')}. ` +
        'Run seed_e2e_permissions.py --confirm and export payload.env.'
    );
  });

  for (const role of ROLES) {
    test(`${role} API media access returns real bytes`, async ({ page }) => {
      const user = USERS[role];

      for (const visibility of VISIBILITIES) {
        const project = PROJECTS[visibility];
        for (const mediaCase of MEDIA_CASES) {
          const label = `${role} ${mediaCase.endpoint} ${visibility}`;
          const expectedStatus =
            AUTHENTICATED_MEDIA_EXPECTATIONS[visibility][role][mediaCase.endpoint];
          const response = await page.request.get(legacyMediaUrl(project, mediaCase), {
            headers: mediaHeaders(user, mediaCase),
            failOnStatusCode: false,
          });
          await expectMediaResponse(response, expectedStatus, mediaCase, label);
        }
      }
    });
  }

  for (const role of ROLES) {
    test(`${role} API clip media access returns real bytes`, async ({ page }) => {
      const user = USERS[role];

      for (const visibility of VISIBILITIES) {
        const project = PROJECTS[visibility];
        for (const mediaCase of CLIP_MEDIA_CASES) {
          const label = `${role} clip ${mediaCase.endpoint} ${visibility}`;
          const expectedStatus =
            AUTHENTICATED_CLIP_MEDIA_EXPECTATIONS[visibility][role][mediaCase.endpoint];
          const response = await page.request.get(clipMediaUrl(project, mediaCase), {
            headers: { Authorization: `Bearer ${user.apiKey}` },
            failOnStatusCode: false,
          });
          await expectClipMediaResponse(response, expectedStatus, mediaCase, label);
        }
      }
    });
  }

  test('guest media follows public/restricted playback toggles', async ({ page }) => {
    for (const visibility of VISIBILITIES) {
      const project = PROJECTS[visibility];
      for (const mediaCase of GUEST_MEDIA_CASES) {
        const label = `guest ${mediaCase.endpoint} ${visibility}`;
        const expectedStatus = GUEST_MEDIA_EXPECTATIONS[visibility][mediaCase.endpoint];
        const response = await page.request.get(legacyMediaUrl(project, mediaCase), {
          headers: mediaHeaders(undefined, mediaCase),
          failOnStatusCode: false,
        });
        await expectMediaResponse(response, expectedStatus, mediaCase, label);
      }
    }
  });

  test('guest clip media requires authentication', async ({ page }) => {
    for (const visibility of VISIBILITIES) {
      const project = PROJECTS[visibility];
      for (const mediaCase of CLIP_MEDIA_CASES) {
        const label = `guest clip ${mediaCase.endpoint} ${visibility}`;
        const expectedStatus = GUEST_CLIP_MEDIA_EXPECTATIONS[visibility][mediaCase.endpoint];
        const response = await page.request.get(clipMediaUrl(project, mediaCase), {
          failOnStatusCode: false,
        });
        await expectClipMediaResponse(response, expectedStatus, mediaCase, label);
      }
    }
  });

  for (const role of ['owner', 'trusted'] as const) {
    test(`${role} restricted recording detail wires media UI`, async ({ page }) => {
      const user = USERS[role];
      const project = PROJECTS.restricted;
      const recordingPath = `/en/projects/${project.id}/recordings/${project.recordingId}`;

      await login(page, user);

      const spectrogramResponsePromise = page.waitForResponse(
        (response) =>
          response
            .url()
            .includes(
              `/web-api/v1/projects/${project.id}/recordings/${project.recordingId}/spectrogram`
            ) && response.status() === 200,
        { timeout: 30000 }
      );
      const mediaTokenResponsePromise = page.waitForResponse(
        (response) =>
          response
            .url()
            .includes(
              `/web-api/v1/projects/${project.id}/recordings/${project.recordingId}/media-token`
            ) && response.status() === 200,
        { timeout: 30000 }
      );
      const playbackResponsePromise = page.waitForResponse(
        (response) =>
          response
            .url()
            .includes(
              `/web-api/v1/projects/${project.id}/recordings/${project.recordingId}/playback`
            ) && [200, 206].includes(response.status()),
        { timeout: 30000 }
      );
      const clipListResponsePromise = page.waitForResponse(
        (response) =>
          response
            .url()
            .includes(
              `/web-api/v1/projects/${project.id}/recordings/${project.recordingId}/clips`
            ) && response.status() === 200,
        { timeout: 30000 }
      );
      const clipPreviewResponsePromise = page.waitForResponse(
        (response) => {
          const url = response.url();
          return (
            url.includes(
              `/web-api/v1/projects/${project.id}/recordings/${project.recordingId}/spectrogram`
            ) &&
            url.includes('media_token=') &&
            url.includes('start=') &&
            url.includes('end=') &&
            url.includes('width=160') &&
            url.includes('height=60') &&
            response.status() === 200
          );
        },
        { timeout: 30000 }
      );

      await page.goto(recordingPath);
      await spectrogramResponsePromise;
      await mediaTokenResponsePromise;
      await playbackResponsePromise;
      await clipListResponsePromise;
      await clipPreviewResponsePromise;
      await expect(page.locator('canvas[aria-label="Spectrogram visualization"]')).toBeVisible({
        timeout: 30000,
      });
      const clipPreviewImage = page.getByTestId('clip-preview-image').first();
      await expect(clipPreviewImage).toBeVisible({
        timeout: 30000,
      });

      const playButton = page.getByRole('button', { name: /^(Play|Pause)$/ }).first();
      await expect(playButton).toBeVisible({ timeout: 15000 });
      await playButton.click();
      await expect(page.locator('audio')).toHaveCount(1);

      const clipDetailSpectrogramResponsePromise = page.waitForResponse(
        (response) => {
          const url = response.url();
          return (
            url.includes(
              `/web-api/v1/projects/${project.id}/recordings/${project.recordingId}/spectrogram`
            ) &&
            url.includes('media_token=') &&
            url.includes('start=') &&
            url.includes('end=') &&
            url.includes('width=600') &&
            url.includes('height=200') &&
            response.status() === 200
          );
        },
        { timeout: 30000 }
      );
      const clipPlaybackResponsePromise = page.waitForResponse(
        (response) => {
          const url = response.url();
          return (
            url.includes(
              `/web-api/v1/projects/${project.id}/recordings/${project.recordingId}/playback`
            ) &&
            url.includes('media_token=') &&
            url.includes('start=') &&
            url.includes('end=') &&
            [200, 206].includes(response.status())
          );
        },
        { timeout: 30000 }
      );

      const clipRow = clipPreviewImage.locator('xpath=ancestor::tr[1]');
      await expect(clipRow).toBeVisible({ timeout: 15000 });
      await clipRow.click();
      await clipDetailSpectrogramResponsePromise;
      await expect(page.getByTestId('clip-detail-spectrogram')).toBeVisible({ timeout: 30000 });
      await expect(page.getByTestId('clip-detail-audio')).toHaveAttribute(
        'src',
        /\/web-api\/v1\/projects\/.+\/recordings\/.+\/playback\?.*media_token=/
      );
      await page.getByTestId('clip-detail-play').click();
      await clipPlaybackResponsePromise;
    });
  }
});
