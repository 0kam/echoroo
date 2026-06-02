/**
 * Shared infrastructure helpers for spec/011 Step 12b E2E tests.
 *
 * Centralises:
 *   - BENIGN_CONSOLE_ERROR_PATTERNS (union of all spec variants)
 *   - trackConsoleErrors / assertNoRealConsoleErrors
 *   - refreshAndBuildHeaders — in-browser Bearer + CSRF header factory
 *   - revokeAllTrustedDevicesInBrowser
 *   - BACKEND_CONTAINER constant + dockerAvailable()
 *   - resetInvitationRateLimits — invitation-specific Redis key deletion
 *   - queryBootstrapTransferSummary — read-only audit query via docker exec
 */

import { type Page, expect } from '@playwright/test';
import { spawnSync, execFileSync } from 'child_process';

// ---------------------------------------------------------------------------
// Console error filtering
// ---------------------------------------------------------------------------

/**
 * Union of all benign console-error patterns across spec/011 specs.
 *
 * Includes:
 *   - HTTP 4xx status codes appearing in DevTools error messages
 *   - Vite HMR reconnect noise
 *   - SvelteKit in-flight request cancellations
 */
export const BENIGN_CONSOLE_ERROR_PATTERNS: string[] = [
  '401',
  '403',
  '404',
  '409',
  'net::ERR_ABORTED',
  'Failed to load resource',
  // Vite HMR reconnect noise
  '[vite] server connection lost',
  'WebSocket connection to',
];

function isBenign(msg: string): boolean {
  return BENIGN_CONSOLE_ERROR_PATTERNS.some((p) => msg.includes(p));
}

/**
 * Attach console + pageerror listeners to `page` and return a handle to the
 * collected non-benign errors.
 *
 * @returns A function that returns a snapshot of collected errors (safe to
 *   call multiple times — each call returns a copy).
 */
export function trackConsoleErrors(page: Page): () => string[] {
  const errors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error' && !isBenign(msg.text())) {
      errors.push(msg.text());
    }
  });
  page.on('pageerror', (err) => {
    errors.push(`PAGE ERROR: ${err.message}`);
  });
  return () => [...errors];
}

/**
 * Assert that no real (non-benign) console errors were collected.
 *
 * @param getErrors - The handle returned by `trackConsoleErrors`.
 * @param context   - A descriptive label used in the failure message.
 */
export function assertNoRealConsoleErrors(
  getErrors: () => string[],
  context: string
): void {
  const errors = getErrors();
  expect(
    errors,
    `${context}: unexpected console/page errors: ${errors.join('; ')}`
  ).toHaveLength(0);
}

// ---------------------------------------------------------------------------
// In-browser auth header factory
// ---------------------------------------------------------------------------

/**
 * Call POST /web-api/v1/auth/refresh from inside the authenticated browser
 * page, extract the access_token, and return a headers object suitable for
 * BFF fetch calls.
 *
 * Throws a clear error (including `context`) on refresh failure so failures
 * are easy to diagnose.
 *
 * @param page    - An authenticated Playwright `Page`.
 * @param context - A string identifying which spec/step is calling this
 *                  (used in the thrown error message).
 */
export async function refreshAndBuildHeaders(
  page: Page,
  context: string
): Promise<Record<string, string>> {
  return page.evaluate(async (ctx: string): Promise<Record<string, string>> => {
    // Read CSRF token from the echoroo_csrf cookie (httponly=false).
    const csrfMatch = document.cookie
      .split(';')
      .map((c) => c.trim())
      .find((c) => c.startsWith('echoroo_csrf='));
    const csrfToken = csrfMatch ? csrfMatch.split('=').slice(1).join('=') : '';

    // Refresh to get a fresh Bearer token.
    const refreshResp = await fetch('/web-api/v1/auth/refresh', {
      method: 'POST',
      credentials: 'include',
    });

    if (!refreshResp.ok) {
      throw new Error(
        `refreshAndBuildHeaders [${ctx}]: /auth/refresh returned ${refreshResp.status}`
      );
    }

    const refreshData = (await refreshResp.json()) as { access_token?: string };
    const accessToken = refreshData.access_token ?? '';

    if (!accessToken) {
      throw new Error(
        `refreshAndBuildHeaders [${ctx}]: access_token missing in refresh response`
      );
    }

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${accessToken}`,
    };
    if (csrfToken) headers['X-CSRF-Token'] = csrfToken;

    return headers;
  }, context);
}

// ---------------------------------------------------------------------------
// Trusted-device revocation helper
// ---------------------------------------------------------------------------

/**
 * Call POST /web-api/v1/account/trusted-devices/revoke-all from inside the
 * authenticated browser page. Returns the HTTP status code.
 *
 * Shared between banner-stack.spec.ts and sc6-trusted-device-regression.spec.ts.
 */
export async function revokeAllTrustedDevicesInBrowser(page: Page): Promise<number> {
  return page.evaluate(async (): Promise<number> => {
    const csrfMatch = document.cookie
      .split(';')
      .map((c) => c.trim())
      .find((c) => c.startsWith('echoroo_csrf='));
    const csrfToken = csrfMatch ? csrfMatch.split('=').slice(1).join('=') : '';

    let accessToken = '';
    try {
      const refreshResp = await fetch('/web-api/v1/auth/refresh', {
        method: 'POST',
        credentials: 'include',
      });
      if (refreshResp.ok) {
        const refreshData = (await refreshResp.json()) as { access_token?: string };
        accessToken = refreshData.access_token ?? '';
      }
    } catch {
      // Proceed without Bearer.
    }

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };
    if (accessToken) headers['Authorization'] = `Bearer ${accessToken}`;
    if (csrfToken) headers['X-CSRF-Token'] = csrfToken;

    const resp = await fetch('/web-api/v1/account/trusted-devices/revoke-all', {
      method: 'POST',
      credentials: 'include',
      headers,
    });
    return resp.status;
  });
}

// ---------------------------------------------------------------------------
// Docker helpers
// ---------------------------------------------------------------------------

/** Container name, overridable via BACKEND_CONTAINER env var. */
export const BACKEND_CONTAINER: string =
  process.env.BACKEND_CONTAINER ?? 'echoroo-backend';

/**
 * Best-effort check whether `docker exec <container> true` exits 0.
 * Returns `true` if docker is accessible, `false` otherwise.
 */
export function dockerAvailable(): boolean {
  try {
    const result = spawnSync('docker', ['exec', BACKEND_CONTAINER, 'true'], {
      timeout: 5000,
    });
    return result.status === 0;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Invitation rate-limit reset
// ---------------------------------------------------------------------------

/**
 * Delete invitation rate-limit Redis keys for the given actor email+project
 * combinations.
 *
 * Deletes ONLY keys matching the pattern
 *   `invitation_rate:actor:<uuid>` / `invitation_rate:project:<uuid>`.
 * NO FLUSHALL is ever called.
 *
 * @param actorIds - Array of actor UUIDs whose rate-limit keys should be cleared.
 * @param projectIds - Array of project UUIDs whose rate-limit keys should be cleared.
 * @returns `true` on success, `false` if docker is unavailable or the script failed.
 */
export function resetInvitationRateLimits(
  actorIds: string[],
  projectIds: string[]
): boolean {
  // Build the Redis key list inside the Python script (no shell interpolation).
  // The IDs are compile-time constants passed as Python list literals.
  const actorList = JSON.stringify(actorIds);
  const projectList = JSON.stringify(projectIds);

  const script = `
import asyncio, os, json
import redis.asyncio as aioredis

REDIS_URL = os.environ.get('REDIS_URL', 'redis://redis:6379')

async def main() -> None:
    r = await aioredis.from_url(REDIS_URL, decode_responses=True)
    actor_ids = json.loads(${JSON.stringify(actorList)})
    project_ids = json.loads(${JSON.stringify(projectList)})
    keys = (
        [f'invitation_rate:actor:{uid}' for uid in actor_ids]
        + [f'invitation_rate:project:{uid}' for uid in project_ids]
    )
    if keys:
        deleted = await r.delete(*keys)
        print(f'Reset {{deleted}} rate-limit key(s)')
    else:
        print('No keys to reset')
    await r.aclose()

asyncio.run(main())
`.trim();

  try {
    const result = spawnSync(
      'docker',
      ['exec', '-i', BACKEND_CONTAINER, 'sh', '-c', 'cd /app && uv run python -'],
      { input: script, encoding: 'utf8', timeout: 15000 }
    );
    if (result.status === 0) {
      console.log(`Rate-limit reset: ${result.stdout.trim()}`);
      return true;
    } else {
      console.warn(`Rate-limit reset exited ${result.status}: ${result.stderr}`);
      return false;
    }
  } catch (err) {
    console.warn(`Rate-limit reset failed (docker unavailable?): ${err}`);
    return false;
  }
}

// ---------------------------------------------------------------------------
// Bootstrap-transfer audit query
// ---------------------------------------------------------------------------

/**
 * Execute a READ-ONLY SELECT against `project_audit_log` inside the backend
 * container to retrieve the bootstrap_transfer row for `projectId`.
 *
 * - Uses `execFileSync('docker', ['exec', BACKEND_CONTAINER, 'uv', 'run',
 *     'python', '-c', PY_SCRIPT], { ... })` — NO `sh -c`, NO string
 *     interpolation of `projectId` into a shell command.
 * - `projectId` is validated against a UUID regex before use.
 * - The Python script is passed as the `-c` argument to the Python interpreter
 *   directly; `projectId` is passed as a separate argv element.
 * - No temp files are written or left behind.
 *
 * @returns The parsed audit row, or `null` if no row was found.
 * @throws  If `projectId` is not a valid UUID, or if the docker exec fails.
 */
export interface BootstrapTransferRow {
  action: string;
  pts: string | null;
  prior_owner: string | null;
  new_owner: string | null;
}

export function queryBootstrapTransferSummary(projectId: string): BootstrapTransferRow | null {
  const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  if (!UUID_RE.test(projectId)) {
    throw new Error(
      `queryBootstrapTransferSummary: projectId "${projectId}" is not a valid UUID`
    );
  }

  // The Python script receives project_id as sys.argv[1].
  // It is NOT interpolated into the script text — completely safe.
  const pyScript = `
import asyncio, json, sys
from echoroo.core.database import AsyncSessionLocal
from sqlalchemy import text

async def main(project_id: str) -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                "SELECT action,"
                " detail->>'pre_transfer_action_summary' AS pts,"
                " detail->>'prior_owner' AS prior_owner,"
                " detail->>'new_owner' AS new_owner"
                " FROM project_audit_log"
                " WHERE project_id = :pid"
                "   AND action = 'project.ownership.bootstrap_transfer'"
                " ORDER BY created_at DESC"
                " LIMIT 1"
            ),
            {"pid": project_id},
        )
        row = result.fetchone()
        if row is None:
            print("NO_ROW", flush=True)
            sys.exit(1)
        print(json.dumps({
            "action": row[0],
            "pts": row[1],
            "prior_owner": row[2],
            "new_owner": row[3],
        }), flush=True)

asyncio.run(main(sys.argv[1]))
`.trim();

  let rawOutput: string;
  try {
    rawOutput = execFileSync(
      'docker',
      [
        'exec',
        BACKEND_CONTAINER,
        'uv',
        'run',
        'python',
        '-c',
        pyScript,
        // Pass projectId as argv[1] to the Python script.
        projectId,
      ],
      { encoding: 'utf8', timeout: 30000 }
    );
  } catch (err: unknown) {
    const e = err as {
      stdout?: string;
      stderr?: string;
      status?: number;
      message?: string;
    };

    // Exit code 1 from the script means NO_ROW.
    const stdout = e.stdout ?? '';
    if (stdout.includes('NO_ROW')) {
      return null;
    }

    throw new Error(
      `queryBootstrapTransferSummary: docker exec failed (exit ${e.status ?? '?'}): ` +
        `${e.message ?? ''}\nstdout: ${stdout}\nstderr: ${e.stderr ?? '(none)'}`
    );
  }

  // Find the JSON line in the output (ignore uv/SQLAlchemy startup lines).
  const jsonLine = rawOutput
    .trim()
    .split('\n')
    .find((l) => l.trim().startsWith('{'));

  if (!jsonLine) {
    return null;
  }

  return JSON.parse(jsonLine) as BootstrapTransferRow;
}
