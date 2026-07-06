/**
 * Seeded vote/comment permission E2E suite.
 *
 * Requires the fixture payload from:
 *   uv run python -m echoroo.scripts.seed_e2e_permissions --confirm
 *
 * Surface split (W2-3):
 * - Votes go through the browser BFF (`/web-api/v1`) — the generic
 *   `/api/v1/.../annotations/{id}/votes` routes were unmounted by W2-3
 *   PR-7 (93d205a7). The BFF requires a first-party session: UI login
 *   (session cookie) + `Authorization: Bearer <access_token>` from
 *   `POST /web-api/v1/auth/refresh`, and an `X-CSRF-Token` header
 *   (from the `echoroo_csrf` cookie) on mutating requests.
 * - Comments stay on the programmatic API (`/api/v1`, still mounted)
 *   using the seeded API keys as Bearer tokens.
 */

import {
  expect,
  test,
  type APIRequestContext,
  type APIResponse,
  type Page,
} from '@playwright/test';
import {
  backendApiUrl,
  expectStatus,
  getBearerTokenAfterLogin,
  login,
  missingEnv,
  readEnv,
  type Role,
  type SeededProject,
  type Visibility,
} from './seeded-permissions.helpers';

const SUITE_ENABLED = process.env.E2E_VOTE_COMMENT_ENABLED === '1';
const ROLES: Role[] = ['owner', 'admin', 'member', 'viewer', 'nonmember', 'trusted'];
const VISIBILITIES: Visibility[] = ['public', 'restricted'];

const CSRF_COOKIE_NAME = 'echoroo_csrf';

interface SeededVoteCommentUser {
  role: Role;
  email: string;
  password: string;
  totpSecret: string;
  apiKey: string;
}

/** Session credentials for the `/web-api/v1` (BFF) vote endpoints. */
interface WebSessionAuth {
  bearer: string;
  csrf: string;
}

interface SeededVoteCommentProject extends SeededProject {
  annotationId: string;
}

interface VoteSummaryResponse {
  annotation_id?: string;
  agree_count?: number;
  disagree_count?: number;
  unsure_count?: number;
  user_vote?: string | null;
  user_signal_quality?: string | null;
  voters?: unknown[];
}

interface CommentListResponse {
  items?: unknown[];
}

interface CommentResponse {
  id?: string;
  annotation_id?: string;
  body?: string;
  commenter_user_id?: string;
}

function seededUser(role: Role, envPrefix: string): SeededVoteCommentUser {
  return {
    role,
    email: readEnv(`E2E_${envPrefix}_EMAIL`),
    password: readEnv('E2E_PASSWORD'),
    totpSecret: readEnv(`E2E_${envPrefix}_TOTP_SECRET`),
    apiKey: readEnv(`E2E_${envPrefix}_API_KEY`),
  };
}

const USERS: Record<Role, SeededVoteCommentUser> = {
  owner: seededUser('owner', 'OWNER'),
  admin: seededUser('admin', 'ADMIN'),
  member: seededUser('member', 'MEMBER'),
  viewer: seededUser('viewer', 'VIEWER'),
  nonmember: seededUser('nonmember', 'NONMEMBER'),
  trusted: seededUser('trusted', 'TRUSTED'),
};

const PROJECTS: Record<Visibility, SeededVoteCommentProject> = {
  public: {
    visibility: 'public',
    id: readEnv('E2E_PUBLIC_PROJECT_ID'),
    name: readEnv('E2E_PUBLIC_PROJECT_NAME'),
    annotationId: readEnv('E2E_PUBLIC_ANNOTATION_ID'),
  },
  restricted: {
    visibility: 'restricted',
    id: readEnv('E2E_RESTRICTED_PROJECT_ID'),
    name: readEnv('E2E_RESTRICTED_PROJECT_NAME'),
    annotationId: readEnv('E2E_RESTRICTED_ANNOTATION_ID'),
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
  'E2E_PUBLIC_ANNOTATION_ID',
  'E2E_RESTRICTED_PROJECT_ID',
  'E2E_RESTRICTED_PROJECT_NAME',
  'E2E_RESTRICTED_ANNOTATION_ID',
] as const;

const MISSING_ENV = missingEnv(REQUIRED_ENV);

const API_EXPECTATIONS: Record<
  Visibility,
  Record<
    Role,
    {
      getVotes: number;
      postVote: number;
      deleteVote: number;
      getComments: number;
      postComment: number;
    }
  >
> = {
  public: {
    owner: { getVotes: 200, postVote: 200, deleteVote: 200, getComments: 200, postComment: 201 },
    admin: { getVotes: 200, postVote: 200, deleteVote: 200, getComments: 200, postComment: 201 },
    member: { getVotes: 200, postVote: 200, deleteVote: 200, getComments: 200, postComment: 201 },
    viewer: { getVotes: 200, postVote: 200, deleteVote: 200, getComments: 200, postComment: 201 },
    nonmember: {
      getVotes: 200,
      postVote: 200,
      deleteVote: 200,
      getComments: 200,
      postComment: 201,
    },
    trusted: {
      getVotes: 200,
      postVote: 200,
      deleteVote: 200,
      getComments: 200,
      postComment: 201,
    },
  },
  restricted: {
    owner: { getVotes: 200, postVote: 200, deleteVote: 200, getComments: 200, postComment: 201 },
    admin: { getVotes: 200, postVote: 200, deleteVote: 200, getComments: 200, postComment: 201 },
    member: { getVotes: 200, postVote: 200, deleteVote: 200, getComments: 200, postComment: 201 },
    viewer: {
      getVotes: 200,
      postVote: 403,
      deleteVote: 403,
      getComments: 200,
      postComment: 403,
    },
    nonmember: {
      getVotes: 200,
      postVote: 200,
      deleteVote: 200,
      getComments: 200,
      postComment: 201,
    },
    trusted: {
      getVotes: 200,
      postVote: 200,
      deleteVote: 200,
      getComments: 200,
      postComment: 201,
    },
  },
};

function authHeaders(apiKey: string): { Authorization: string } {
  return { Authorization: `Bearer ${apiKey}` };
}

/**
 * BFF vote path, relative to the Playwright baseURL so `page.request`
 * goes through the frontend (Vite `/web-api` proxy) and carries the
 * session cookies established by the UI login.
 */
function voteWebApiPath(project: SeededVoteCommentProject): string {
  return `/web-api/v1/projects/${project.id}/annotations/${project.annotationId}/votes`;
}

/** Legacy programmatic comment path (still mounted on `/api/v1`). */
function commentApiPath(project: SeededVoteCommentProject): string {
  return `/api/v1/projects/${project.id}/annotations/${project.annotationId}/comments`;
}

/**
 * Log in through the UI and collect the session credentials the BFF
 * requires: the Bearer access token (via `/web-api/v1/auth/refresh`)
 * and the CSRF token (JS-readable `echoroo_csrf` cookie) for mutations.
 */
async function establishWebSession(
  page: Page,
  user: SeededVoteCommentUser
): Promise<WebSessionAuth> {
  await login(page, user);
  const bearer = await getBearerTokenAfterLogin(page);
  const cookies = await page.context().cookies();
  const csrf = cookies.find((cookie) => cookie.name === CSRF_COOKIE_NAME)?.value ?? '';
  expect(
    csrf.length,
    `${CSRF_COOKIE_NAME} cookie must be present after ${user.role} login`
  ).toBeGreaterThan(0);
  return { bearer, csrf };
}

async function expectVoteSummaryBody(
  response: APIResponse,
  project: SeededVoteCommentProject,
  label: string
): Promise<VoteSummaryResponse> {
  const data = (await response.json()) as VoteSummaryResponse;
  expect(data.annotation_id, `${label} should return annotation_id`).toBe(project.annotationId);
  expect(data.agree_count, `${label} should return agree_count`).toEqual(expect.any(Number));
  expect(data.disagree_count, `${label} should return disagree_count`).toEqual(expect.any(Number));
  expect(data.unsure_count, `${label} should return unsure_count`).toEqual(expect.any(Number));
  expect(Array.isArray(data.voters), `${label} should return voters[]`).toBe(true);
  return data;
}

async function expectCommentListBody(response: APIResponse, label: string): Promise<void> {
  const data = (await response.json()) as CommentListResponse;
  expect(Array.isArray(data.items), `${label} should return items[]`).toBe(true);
}

async function expectCreatedCommentBody(
  response: APIResponse,
  project: SeededVoteCommentProject,
  expectedBody: string,
  label: string
): Promise<void> {
  const data = (await response.json()) as CommentResponse;
  expect(data.id, `${label} should return id`).toEqual(expect.any(String));
  expect(data.annotation_id, `${label} should return annotation_id`).toBe(project.annotationId);
  expect(data.commenter_user_id, `${label} should return commenter_user_id`).toEqual(
    expect.any(String)
  );
  expect(data.body, `${label} should return the created body`).toBe(expectedBody);
}

async function getVotes(
  page: Page,
  auth: WebSessionAuth,
  project: SeededVoteCommentProject
): Promise<APIResponse> {
  return page.request.get(voteWebApiPath(project), {
    headers: { Authorization: `Bearer ${auth.bearer}` },
    failOnStatusCode: false,
  });
}

async function postVote(
  page: Page,
  auth: WebSessionAuth,
  project: SeededVoteCommentProject,
  data: { vote: 'agree'; signal_quality: 'solo' } | { vote: 'disagree' }
): Promise<APIResponse> {
  return page.request.post(voteWebApiPath(project), {
    headers: {
      Authorization: `Bearer ${auth.bearer}`,
      'X-CSRF-Token': auth.csrf,
    },
    data,
    failOnStatusCode: false,
  });
}

async function deleteVote(
  page: Page,
  auth: WebSessionAuth,
  project: SeededVoteCommentProject
): Promise<APIResponse> {
  return page.request.delete(voteWebApiPath(project), {
    headers: {
      Authorization: `Bearer ${auth.bearer}`,
      'X-CSRF-Token': auth.csrf,
    },
    failOnStatusCode: false,
  });
}

async function getComments(
  request: APIRequestContext,
  user: SeededVoteCommentUser,
  project: SeededVoteCommentProject
): Promise<APIResponse> {
  return request.get(backendApiUrl(commentApiPath(project)), {
    headers: authHeaders(user.apiKey),
    failOnStatusCode: false,
  });
}

async function postComment(
  request: APIRequestContext,
  user: SeededVoteCommentUser,
  project: SeededVoteCommentProject,
  body: string
): Promise<APIResponse> {
  return request.post(backendApiUrl(commentApiPath(project)), {
    headers: authHeaders(user.apiKey),
    data: { body },
    failOnStatusCode: false,
  });
}

async function verifyVoteAndCommentPermissions(
  page: Page,
  request: APIRequestContext,
  role: Role,
  project: SeededVoteCommentProject
): Promise<void> {
  const user = USERS[role];
  const expected = API_EXPECTATIONS[project.visibility][role];
  const label = `${role} ${project.visibility}`;

  const auth = await establishWebSession(page, user);

  const votes = await getVotes(page, auth, project);
  await expectStatus(votes, expected.getVotes, `GET votes ${label}`);
  if (votes.status() === 200) {
    await expectVoteSummaryBody(votes, project, `GET votes ${label}`);
  }

  const comments = await getComments(request, user, project);
  await expectStatus(comments, expected.getComments, `GET comments ${label}`);
  if (comments.status() === 200) {
    await expectCommentListBody(comments, `GET comments ${label}`);
  }

  const agreeVote = await postVote(page, auth, project, {
    vote: 'agree',
    signal_quality: 'solo',
  });
  await expectStatus(agreeVote, expected.postVote, `POST agree vote ${label}`);
  if (agreeVote.status() === 200) {
    const summary = await expectVoteSummaryBody(agreeVote, project, `POST agree vote ${label}`);
    expect(summary.user_vote, `POST agree vote ${label} should set user_vote`).toBe('agree');
  }

  const replacementVote = await postVote(page, auth, project, { vote: 'disagree' });
  await expectStatus(replacementVote, expected.postVote, `POST replacement vote ${label}`);
  if (replacementVote.status() === 200) {
    const summary = await expectVoteSummaryBody(
      replacementVote,
      project,
      `POST replacement vote ${label}`
    );
    expect(summary.user_vote, `POST replacement vote ${label} should replace user_vote`).toBe(
      'disagree'
    );
    expect(
      summary.user_signal_quality,
      `POST replacement vote ${label} should clear user_signal_quality`
    ).toBeNull();
  }

  const deleteResponse = await deleteVote(page, auth, project);
  await expectStatus(deleteResponse, expected.deleteVote, `DELETE vote ${label}`);
  if (deleteResponse.status() === 200) {
    const summary = await expectVoteSummaryBody(deleteResponse, project, `DELETE vote ${label}`);
    expect(summary.user_vote, `DELETE vote ${label} should clear user_vote`).toBeNull();
    expect(
      summary.user_signal_quality,
      `DELETE vote ${label} should clear user_signal_quality`
    ).toBeNull();
  }

  const commentBody = `seeded vote-comment ${role} ${project.visibility} ${Date.now()} ${test.info().retry}`;
  const comment = await postComment(request, user, project, commentBody);
  await expectStatus(comment, expected.postComment, `POST comment ${label}`);
  if (comment.status() === 201) {
    await expectCreatedCommentBody(comment, project, commentBody, `POST comment ${label}`);
  }
}

test.describe('Seeded vote/comment permissions @e2e-vote-comment', () => {
  test.describe.configure({ mode: 'serial', timeout: 120000 });

  test.beforeEach(() => {
    test.skip(
      !SUITE_ENABLED,
      'E2E_VOTE_COMMENT_ENABLED=1 is required to run seeded vote/comment permissions.'
    );
    test.skip(
      MISSING_ENV.length > 0,
      `Missing required seeded vote/comment env vars: ${MISSING_ENV.join(', ')}. ` +
        'Run seed_e2e_permissions.py --confirm and export payload.env.'
    );
  });

  for (const visibility of VISIBILITIES) {
    for (const role of ROLES) {
      test(`${role} ${visibility} GET/POST/DELETE vote and GET/POST comment permissions`, async ({
        page,
        request,
      }) => {
        await verifyVoteAndCommentPermissions(page, request, role, PROJECTS[visibility]);
      });
    }
  }
});
