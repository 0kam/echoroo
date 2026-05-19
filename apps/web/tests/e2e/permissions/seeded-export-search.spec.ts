/**
 * Seeded export/search permission E2E suite.
 *
 * Requires the fixture payload from:
 *   uv run python -m echoroo.scripts.seed_e2e_permissions --confirm
 */

import { expect, test, type APIResponse } from '@playwright/test';
import { inflateRawSync } from 'node:zlib';
import {
  backendApiUrl,
  expectStatus,
  missingEnv,
  readEnv,
  type Role,
  type SeededApiTestUser,
  type SeededProject,
  type Visibility,
} from './seeded-permissions.helpers';

const SUITE_ENABLED = process.env.E2E_EXPORT_SEARCH_ENABLED === '1';
const FIXTURE_PREFIX = readEnv('E2E_FIXTURE_PREFIX');
const PASSWORD = readEnv('E2E_PASSWORD');
const ROLES: Role[] = ['owner', 'admin', 'member', 'viewer', 'nonmember', 'trusted'];
const VISIBILITIES: Visibility[] = ['public', 'restricted'];

interface SeededExportSearchProject extends SeededProject {
  datasetId: string;
  searchSessionId: string;
  exportableSearchSessionId: string;
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

const PROJECTS: Record<Visibility, SeededExportSearchProject> = {
  public: {
    visibility: 'public',
    id: readEnv('E2E_PUBLIC_PROJECT_ID'),
    name: readEnv('E2E_PUBLIC_PROJECT_NAME'),
    datasetId: readEnv('E2E_PUBLIC_DATASET_ID'),
    searchSessionId: readEnv('E2E_PUBLIC_SEARCH_SESSION_ID'),
    exportableSearchSessionId: readEnv('E2E_PUBLIC_EXPORTABLE_SEARCH_SESSION_ID'),
  },
  restricted: {
    visibility: 'restricted',
    id: readEnv('E2E_RESTRICTED_PROJECT_ID'),
    name: readEnv('E2E_RESTRICTED_PROJECT_NAME'),
    datasetId: readEnv('E2E_RESTRICTED_DATASET_ID'),
    searchSessionId: readEnv('E2E_RESTRICTED_SEARCH_SESSION_ID'),
    exportableSearchSessionId: readEnv('E2E_RESTRICTED_EXPORTABLE_SEARCH_SESSION_ID'),
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
  'E2E_PUBLIC_DATASET_ID',
  'E2E_PUBLIC_SEARCH_SESSION_ID',
  'E2E_PUBLIC_EXPORTABLE_SEARCH_SESSION_ID',
  'E2E_RESTRICTED_PROJECT_ID',
  'E2E_RESTRICTED_PROJECT_NAME',
  'E2E_RESTRICTED_DATASET_ID',
  'E2E_RESTRICTED_SEARCH_SESSION_ID',
  'E2E_RESTRICTED_EXPORTABLE_SEARCH_SESSION_ID',
] as const;

const MISSING_ENV = missingEnv(REQUIRED_ENV);

const API_EXPECTATIONS: Record<
  Visibility,
  Record<
    Role,
    {
      search: number;
      exportCsv: number;
      exportRecordings: number;
      referenceAudio: number;
      datasetExportZip: number;
    }
  >
> = {
  public: {
    owner: {
      search: 200,
      exportCsv: 200,
      exportRecordings: 404,
      referenceAudio: 404,
      datasetExportZip: 200,
    },
    admin: {
      search: 200,
      exportCsv: 200,
      exportRecordings: 404,
      referenceAudio: 404,
      datasetExportZip: 200,
    },
    member: {
      search: 200,
      exportCsv: 200,
      exportRecordings: 404,
      referenceAudio: 404,
      datasetExportZip: 200,
    },
    viewer: {
      search: 200,
      exportCsv: 200,
      exportRecordings: 404,
      referenceAudio: 404,
      datasetExportZip: 200,
    },
    nonmember: {
      search: 200,
      exportCsv: 200,
      exportRecordings: 404,
      referenceAudio: 404,
      datasetExportZip: 200,
    },
    trusted: {
      search: 200,
      exportCsv: 200,
      exportRecordings: 404,
      referenceAudio: 404,
      datasetExportZip: 200,
    },
  },
  restricted: {
    owner: {
      search: 200,
      exportCsv: 200,
      exportRecordings: 404,
      referenceAudio: 404,
      datasetExportZip: 200,
    },
    admin: {
      search: 200,
      exportCsv: 200,
      exportRecordings: 404,
      referenceAudio: 404,
      datasetExportZip: 200,
    },
    member: {
      search: 200,
      exportCsv: 200,
      exportRecordings: 404,
      referenceAudio: 404,
      datasetExportZip: 200,
    },
    viewer: {
      search: 200,
      exportCsv: 403,
      exportRecordings: 403,
      referenceAudio: 404,
      datasetExportZip: 403,
    },
    nonmember: {
      search: 403,
      exportCsv: 403,
      exportRecordings: 403,
      referenceAudio: 403,
      datasetExportZip: 403,
    },
    trusted: {
      search: 200,
      exportCsv: 200,
      exportRecordings: 404,
      referenceAudio: 404,
      datasetExportZip: 200,
    },
  },
};

interface SearchSessionListResponse {
  sessions?: Array<{ id?: string; status?: string; result_count?: number }>;
  total?: number;
}

interface SearchSessionDetailResponse {
  id?: string;
  project_id?: string;
  status?: string;
  result_count?: number;
  confirmed_count?: number;
  rejected_count?: number;
}

interface ErrorDetailResponse {
  detail?: unknown;
}

function extractZipEntry(zipBody: Buffer, entryPath: string): Buffer | null {
  let offset = 0;

  while (offset <= zipBody.length - 30) {
    const signature = zipBody.readUInt32LE(offset);
    if (signature !== 0x04034b50) {
      break;
    }

    const flags = zipBody.readUInt16LE(offset + 6);
    const compressionMethod = zipBody.readUInt16LE(offset + 8);
    const compressedSize = zipBody.readUInt32LE(offset + 18);
    const fileNameLength = zipBody.readUInt16LE(offset + 26);
    const extraFieldLength = zipBody.readUInt16LE(offset + 28);
    const fileNameStart = offset + 30;
    const fileNameEnd = fileNameStart + fileNameLength;
    const dataStart = fileNameEnd + extraFieldLength;
    const dataEnd = dataStart + compressedSize;

    expect(fileNameEnd, 'ZIP local filename should be within body').toBeLessThanOrEqual(
      zipBody.length
    );
    expect(dataEnd, 'ZIP local file data should be within body').toBeLessThanOrEqual(
      zipBody.length
    );
    expect(flags & 0x08, 'ZIP entries should include local sizes').toBe(0);

    const fileName = zipBody.subarray(fileNameStart, fileNameEnd).toString('utf8');
    const compressedData = zipBody.subarray(dataStart, dataEnd);

    if (fileName === entryPath) {
      if (compressionMethod === 0) {
        return compressedData;
      }
      if (compressionMethod === 8) {
        return inflateRawSync(compressedData);
      }
      throw new Error(`Unsupported ZIP compression method ${compressionMethod} for ${entryPath}`);
    }

    offset = dataEnd;
  }

  return null;
}

async function expectCsvResponse(
  response: APIResponse,
  expected: number,
  label: string
): Promise<void> {
  await expectStatus(response, expected, label);
  if (expected !== 200) {
    return;
  }

  expect(
    response.headers()['content-type'] ?? '',
    `${label} should return a CSV content type`
  ).toContain('text/csv');
}

async function expectDatasetZipResponse(
  response: APIResponse,
  expected: number,
  label: string,
  expectedAudioPath?: string
): Promise<void> {
  await expectStatus(response, expected, label);
  if (expected !== 200) {
    return;
  }

  expect(
    response.headers()['content-type'] ?? '',
    `${label} should return a ZIP content type`
  ).toContain('application/zip');
  expect(
    response.headers()['content-disposition'] ?? '',
    `${label} should include a ZIP filename`
  ).toContain('.zip');

  const body = await response.body();
  expect(body.length, `${label} ZIP body should not be empty`).toBeGreaterThan(0);
  expect(body[0], `${label} ZIP body should start with PK`).toBe(0x50);
  expect(body[1], `${label} ZIP body should start with PK`).toBe(0x4b);

  const zipText = body.toString('latin1');
  expect(zipText, `${label} ZIP should include datapackage.json`).toContain('datapackage.json');
  expect(zipText, `${label} ZIP should include deployments.csv`).toContain('deployments.csv');
  expect(zipText, `${label} ZIP should include media.csv`).toContain('media.csv');
  if (expectedAudioPath) {
    expect(zipText, `${label} ZIP should include audio entry`).toContain(expectedAudioPath);
    const audioEntry = extractZipEntry(body, expectedAudioPath);
    expect(audioEntry, `${label} ZIP should include readable audio entry`).not.toBeNull();
    expect(audioEntry?.subarray(0, 4).toString('ascii'), `${label} ZIP audio WAV magic`).toBe(
      'RIFF'
    );
  }
}

function parseCsvLine(line: string): string[] {
  const cells: string[] = [];
  let current = '';
  let inQuotes = false;

  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];

    if (char === '"') {
      if (inQuotes && line[index + 1] === '"') {
        current += '"';
        index += 1;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (char === ',' && !inQuotes) {
      cells.push(current);
      current = '';
    } else {
      current += char;
    }
  }

  cells.push(current);
  return cells;
}

async function expectExportRecordingsCsvResponse(
  response: APIResponse,
  project: SeededExportSearchProject
): Promise<void> {
  await expectStatus(response, 200, `${project.visibility} exportable recordings CSV`);

  expect(
    response.headers()['content-type'] ?? '',
    `${project.visibility} exportable recordings should return a CSV content type`
  ).toContain('text/csv');
  expect(
    response.headers()['content-disposition'] ?? '',
    `${project.visibility} exportable recordings should include a CSV filename`
  ).toContain('.csv');

  const csv = await response.text();
  const lines = csv
    .trim()
    .split(/\r?\n/)
    .map((line) => parseCsvLine(line));

  expect(lines, `${project.visibility} exportable recordings CSV row count`).toHaveLength(2);
  expect(lines[0], `${project.visibility} exportable recordings CSV header`).toEqual([
    'recording_filename',
    'recording_datetime',
    'scientific_name',
    'common_name',
    'max_similarity',
    'min_similarity',
    'avg_similarity',
  ]);
  expect(lines[1], `${project.visibility} exportable recordings CSV row`).toEqual([
    `${FIXTURE_PREFIX}-${project.visibility}-fixture.wav`,
    '2026-05-15 09:00:00',
    'Testus permissionis',
    'E2E Seed Species',
    '1.0000',
    '1.0000',
    '1.0000',
  ]);
}

async function expectReferenceAudioResponse(
  response: APIResponse,
  project: SeededExportSearchProject
): Promise<void> {
  await expectStatus(response, 200, `${project.visibility} exportable reference audio`);

  const headers = response.headers();
  expect(
    headers['content-type'] ?? '',
    `${project.visibility} exportable reference audio should return an audio content type`
  ).toContain('audio/');
  expect(
    headers['accept-ranges'] ?? '',
    `${project.visibility} exportable reference audio should advertise byte ranges`
  ).toBe('bytes');

  const body = await response.body();
  expect(
    body.length,
    `${project.visibility} exportable reference audio body should not be empty`
  ).toBeGreaterThan(0);
  expect(body.subarray(0, 4).toString('ascii'), `${project.visibility} WAV magic`).toBe('RIFF');
}

async function expectReferenceAudioRangeResponse(
  response: APIResponse,
  project: SeededExportSearchProject
): Promise<void> {
  await expectStatus(response, 206, `${project.visibility} exportable reference audio range`);

  const headers = response.headers();
  expect(
    headers['accept-ranges'] ?? '',
    `${project.visibility} exportable reference audio range should advertise byte ranges`
  ).toBe('bytes');
  expect(
    headers['content-range'] ?? '',
    `${project.visibility} exportable reference audio range should include content-range`
  ).toMatch(/^bytes 0-3\//);

  const body = await response.body();
  expect(body.toString('ascii'), `${project.visibility} WAV range magic`).toBe('RIFF');
}

async function expectJsonDetailForExpected404(
  response: APIResponse,
  expected: number,
  expectedDetail: string,
  label: string
): Promise<void> {
  await expectStatus(response, expected, label);
  if (expected !== 404) {
    return;
  }

  const body = (await response.json()) as ErrorDetailResponse;
  expect(body.detail, `${label} should return the expected 404 detail`).toBe(expectedDetail);
}

test.describe('Seeded export/search permissions @e2e-export-search', () => {
  test.describe.configure({ timeout: 120000 });

  test.beforeEach(() => {
    test.skip(
      !SUITE_ENABLED,
      'E2E_EXPORT_SEARCH_ENABLED=1 is required to run seeded export/search permissions.'
    );
    test.skip(
      MISSING_ENV.length > 0,
      `Missing required seeded export/search env vars: ${MISSING_ENV.join(', ')}. ` +
        'Run seed_e2e_permissions.py --confirm and export payload.env.'
    );
  });

  for (const role of ROLES) {
    test(`${role} API export/search permissions`, async ({ page }) => {
      const user = USERS[role];

      for (const visibility of VISIBILITIES) {
        const project = PROJECTS[visibility];
        const expected = API_EXPECTATIONS[visibility][role];
        const headers = { Authorization: `Bearer ${user.apiKey}` };

        const listResponse = await page.request.get(
          backendApiUrl(`/api/v1/projects/${project.id}/search/sessions`),
          {
            headers,
            failOnStatusCode: false,
          }
        );
        await expectStatus(listResponse, expected.search, `${role} search list ${visibility}`);

        if (expected.search === 200) {
          const list = (await listResponse.json()) as SearchSessionListResponse;
          expect(
            list.sessions?.some((session) => session.id === project.searchSessionId),
            `${role} should see seeded ${visibility} search session in list`
          ).toBe(true);
        }

        const detailResponse = await page.request.get(
          backendApiUrl(
            `/api/v1/projects/${project.id}/search/sessions/${project.searchSessionId}`
          ),
          {
            headers,
            failOnStatusCode: false,
          }
        );
        await expectStatus(detailResponse, expected.search, `${role} search detail ${visibility}`);

        if (expected.search === 200) {
          const detail = (await detailResponse.json()) as SearchSessionDetailResponse;
          expect(detail.id, `${role} search detail id for ${visibility}`).toBe(
            project.searchSessionId
          );
          expect(detail.project_id, `${role} search detail project id for ${visibility}`).toBe(
            project.id
          );
          expect(detail.status, `${role} search detail status for ${visibility}`).toBe('completed');
          expect(detail.result_count, `${role} search result count for ${visibility}`).toBe(0);
          expect(detail.confirmed_count, `${role} confirmed count for ${visibility}`).toBe(0);
          expect(detail.rejected_count, `${role} rejected count for ${visibility}`).toBe(0);
        }

        const detectionsExportResponse = await page.request.get(
          backendApiUrl(`/api/v1/projects/${project.id}/detections/export/csv`),
          {
            headers,
            failOnStatusCode: false,
          }
        );
        await expectCsvResponse(
          detectionsExportResponse,
          expected.exportCsv,
          `${role} detections CSV export ${visibility}`
        );

        const searchExportResponse = await page.request.get(
          backendApiUrl(
            `/api/v1/projects/${project.id}/search/sessions/${project.searchSessionId}/export/csv`
          ),
          {
            headers,
            failOnStatusCode: false,
          }
        );
        await expectCsvResponse(
          searchExportResponse,
          expected.exportCsv,
          `${role} search session CSV export ${visibility}`
        );

        const exportRecordingsResponse = await page.request.get(
          backendApiUrl(
            `/api/v1/projects/${project.id}/search/sessions/${project.searchSessionId}/export-recordings`
          ),
          {
            headers,
            failOnStatusCode: false,
          }
        );
        await expectJsonDetailForExpected404(
          exportRecordingsResponse,
          expected.exportRecordings,
          'Session has no results to export',
          `${role} search session recordings export ${visibility}`
        );

        const referenceAudioResponse = await page.request.get(
          backendApiUrl(
            `/api/v1/projects/${project.id}/search/sessions/${project.searchSessionId}/reference-audio/0`
          ),
          {
            headers,
            failOnStatusCode: false,
          }
        );
        await expectJsonDetailForExpected404(
          referenceAudioResponse,
          expected.referenceAudio,
          'Reference audio source index 0 not found',
          `${role} search session reference audio ${visibility}`
        );

        const datasetExportZipResponse = await page.request.get(
          backendApiUrl(
            `/api/v1/projects/${project.id}/datasets/${project.datasetId}/export?include_audio=false`
          ),
          {
            headers,
            failOnStatusCode: false,
          }
        );
        await expectDatasetZipResponse(
          datasetExportZipResponse,
          expected.datasetExportZip,
          `${role} dataset ZIP export ${visibility}`
        );

        const datasetExportZipWithAudioResponse = await page.request.get(
          backendApiUrl(
            `/api/v1/projects/${project.id}/datasets/${project.datasetId}/export?include_audio=true`
          ),
          {
            headers,
            failOnStatusCode: false,
          }
        );
        await expectDatasetZipResponse(
          datasetExportZipWithAudioResponse,
          expected.datasetExportZip,
          `${role} dataset ZIP export with audio ${visibility}`,
          expected.datasetExportZip === 200
            ? `data/e2e/${FIXTURE_PREFIX}/${visibility}/fixture.wav`
            : undefined
        );
      }
    });
  }

  test('owner can export recordings CSV for seeded exportable search sessions', async ({
    page,
  }) => {
    const headers = { Authorization: `Bearer ${USERS.owner.apiKey}` };

    for (const visibility of VISIBILITIES) {
      const project = PROJECTS[visibility];
      const response = await page.request.get(
        backendApiUrl(
          `/api/v1/projects/${project.id}/search/sessions/${project.exportableSearchSessionId}/export-recordings`
        ),
        {
          headers,
          failOnStatusCode: false,
        }
      );

      await expectExportRecordingsCsvResponse(response, project);
    }
  });

  test('owner can stream reference audio for seeded exportable search sessions', async ({
    page,
  }) => {
    const headers = { Authorization: `Bearer ${USERS.owner.apiKey}` };

    for (const visibility of VISIBILITIES) {
      const project = PROJECTS[visibility];
      const referenceAudioUrl = backendApiUrl(
        `/api/v1/projects/${project.id}/search/sessions/${project.exportableSearchSessionId}/reference-audio/0`
      );
      const response = await page.request.get(referenceAudioUrl, {
        headers,
        failOnStatusCode: false,
      });
      await expectReferenceAudioResponse(response, project);

      const rangeResponse = await page.request.get(referenceAudioUrl, {
        headers: {
          ...headers,
          Range: 'bytes=0-3',
        },
        failOnStatusCode: false,
      });
      await expectReferenceAudioRangeResponse(rangeResponse, project);
    }
  });
});
