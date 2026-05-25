/**
 * Unit tests for the demotion-race mitigation (spec/007 Phase 1.5 /
 * AD-3) plus the spec/009 PR 6 toast/invalidate dedupe hardening.
 *
 * Covers:
 *
 *   - `extractProjectIdFromUrl` regex (UUID v4 segment matches; non-UUID
 *     segments like `/projects/feed` are rejected).
 *   - `_handle403` with `meta.projectId` → invalidateQueries on the
 *     `['project', projectId]` key on the FIRST hit only (subsequent
 *     hits within the dedupe window must NOT re-invalidate).
 *   - `_handle403` URL fallback when meta is missing.
 *   - `_handle403` with no projectId context → dedupe still applies
 *     via the `__no_project__` sentinel key.
 *   - Refetch-loop guard: 403 on the project detail query itself →
 *     removeQueries + goto fallback (NOT invalidate), even when the
 *     dedupe window is open.
 *   - Toast dedupe — at most one toast per key within the 30 s
 *     window, per-project isolation, re-arm after the window
 *     elapses.
 *   - Window-focus refetch suppression for 60 s after the most
 *     recent 403.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient } from '@tanstack/svelte-query';

// Mocks must be hoisted before importing the module under test.
vi.mock('$app/navigation', () => ({
  goto: vi.fn(() => Promise.resolve()),
}));

vi.mock('$lib/paraglide/runtime', () => ({
  localizeHref: (href: string) => href,
}));

const toastWarning = vi.fn();
vi.mock('$lib/stores/toast', () => ({
  toasts: {
    warning: (msg: string) => toastWarning(msg),
    error: vi.fn(),
    success: vi.fn(),
  },
}));

// Now import the module under test — its top-level QueryClient
// construction will pick up the mocks above.
import {
  NO_PROJECT_KEY,
  _handle403,
  _lastToastByKey,
  _resetFocusRefetchClock,
  _shouldRefetchOnFocus,
  extractProjectIdFromUrl,
} from '$lib/api/query-client';
import { goto } from '$app/navigation';

const VALID_UUID = '11111111-2222-4333-8444-555555555555';

describe('extractProjectIdFromUrl', () => {
  it('extracts a valid UUID v4 from /api/v1/projects/{id}/...', () => {
    expect(
      extractProjectIdFromUrl(`/api/v1/projects/${VALID_UUID}/datasets`),
    ).toBe(VALID_UUID);
  });

  it('extracts a valid UUID v4 from /web-api/v1/projects/{id}', () => {
    expect(
      extractProjectIdFromUrl(`/web-api/v1/projects/${VALID_UUID}`),
    ).toBe(VALID_UUID);
  });

  it('extracts a valid UUID v4 followed by a query string', () => {
    expect(
      extractProjectIdFromUrl(`/api/v1/projects/${VALID_UUID}?include=stats`),
    ).toBe(VALID_UUID);
  });

  it('returns null for non-UUID segments like /projects/feed', () => {
    expect(extractProjectIdFromUrl('/api/v1/projects/feed')).toBeNull();
  });

  it('returns null for an unrelated URL', () => {
    expect(extractProjectIdFromUrl('/api/v1/users/me')).toBeNull();
  });

  it('returns null for empty / null / undefined input', () => {
    expect(extractProjectIdFromUrl('')).toBeNull();
    expect(extractProjectIdFromUrl(null)).toBeNull();
    expect(extractProjectIdFromUrl(undefined)).toBeNull();
  });

  it('rejects a malformed UUID (wrong version digit)', () => {
    // version digit is 9, not 1-5 → must not match.
    const malformed = '11111111-2222-9333-8444-555555555555';
    expect(
      extractProjectIdFromUrl(`/api/v1/projects/${malformed}/datasets`),
    ).toBeNull();
  });
});

describe('_handle403 — invalidate via meta.projectId', () => {
  let client: QueryClient;

  beforeEach(() => {
    client = new QueryClient();
    toastWarning.mockClear();
    _lastToastByKey.clear();
    _resetFocusRefetchClock();
    vi.mocked(goto).mockClear();
  });

  afterEach(() => {
    client.clear();
  });

  it('invalidates ["project", projectId] on the first 403 for the key', () => {
    const spy = vi.spyOn(client, 'invalidateQueries');
    _handle403(
      { projectId: VALID_UUID },
      { kind: 'mutation', url: null },
      client,
    );

    expect(spy).toHaveBeenCalledWith({
      queryKey: ['project', VALID_UUID],
      refetchType: 'active',
    });
    expect(toastWarning).toHaveBeenCalledTimes(1);
  });

  it('falls back to URL extraction when meta is missing', () => {
    const spy = vi.spyOn(client, 'invalidateQueries');
    _handle403(
      undefined,
      {
        kind: 'mutation',
        url: `/api/v1/projects/${VALID_UUID}/detections/abc`,
      },
      client,
    );

    expect(spy).toHaveBeenCalledWith({
      queryKey: ['project', VALID_UUID],
      refetchType: 'active',
    });
  });

  it('suppresses invalidate inside the dedupe window (spec/009 PR 6)', () => {
    const spy = vi.spyOn(client, 'invalidateQueries');

    _handle403({ projectId: VALID_UUID }, { kind: 'mutation' }, client, 1_000_000);
    _handle403({ projectId: VALID_UUID }, { kind: 'mutation' }, client, 1_010_000); // +10s
    _handle403({ projectId: VALID_UUID }, { kind: 'mutation' }, client, 1_020_000); // +20s

    // Only the first call should have invalidated; the next two are
    // within the 30 s dedupe window.
    expect(spy).toHaveBeenCalledTimes(1);
    expect(toastWarning).toHaveBeenCalledTimes(1);
  });

  it('re-invalidates once the dedupe window elapses', () => {
    const spy = vi.spyOn(client, 'invalidateQueries');

    _handle403({ projectId: VALID_UUID }, { kind: 'mutation' }, client, 1_000_000);
    _handle403({ projectId: VALID_UUID }, { kind: 'mutation' }, client, 1_031_000); // +31s

    expect(spy).toHaveBeenCalledTimes(2);
    expect(toastWarning).toHaveBeenCalledTimes(2);
  });

  it('warns + generic toast when neither meta nor URL contains a project id', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');

    _handle403(
      undefined,
      { kind: 'mutation', url: '/api/v1/users/me' },
      client,
    );

    expect(invalidateSpy).not.toHaveBeenCalled();
    expect(warnSpy).toHaveBeenCalled();
    expect(toastWarning).toHaveBeenCalledWith(
      expect.stringContaining('refresh'),
    );
    warnSpy.mockRestore();
  });

  it('dedupes the no-projectId toast (spec/009 PR 6)', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

    _handle403(undefined, { kind: 'mutation', url: '/api/v1/users/me' }, client, 1_000_000);
    _handle403(undefined, { kind: 'mutation', url: '/api/v1/users/me' }, client, 1_005_000);
    _handle403(undefined, { kind: 'mutation', url: '/api/v1/admin/users' }, client, 1_020_000);

    // All three share the NO_PROJECT_KEY sentinel; only the first
    // should reach the toast store.
    expect(toastWarning).toHaveBeenCalledTimes(1);
    expect(_lastToastByKey.has(NO_PROJECT_KEY)).toBe(true);
    warnSpy.mockRestore();
  });
});

describe('_handle403 — refetch-loop guard for project detail query', () => {
  let client: QueryClient;

  beforeEach(() => {
    client = new QueryClient();
    toastWarning.mockClear();
    _lastToastByKey.clear();
    _resetFocusRefetchClock();
    vi.mocked(goto).mockClear();
  });

  it('removes the cache + navigates when the project detail itself 403s', () => {
    const removeSpy = vi.spyOn(client, 'removeQueries');
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');

    _handle403(
      { projectId: VALID_UUID },
      {
        kind: 'query',
        queryKey: ['project', VALID_UUID],
        url: `/api/v1/projects/${VALID_UUID}`,
      },
      client,
    );

    expect(removeSpy).toHaveBeenCalledWith({
      queryKey: ['project', VALID_UUID],
      exact: true,
    });
    expect(invalidateSpy).not.toHaveBeenCalled();
    expect(goto).toHaveBeenCalledWith('/projects', { replaceState: true });
  });

  it('still invalidates when the failing query is a different project-scoped one', () => {
    const removeSpy = vi.spyOn(client, 'removeQueries');
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');

    _handle403(
      { projectId: VALID_UUID },
      {
        kind: 'query',
        queryKey: ['datasets', VALID_UUID],
        url: null,
      },
      client,
    );

    expect(invalidateSpy).toHaveBeenCalled();
    expect(removeSpy).not.toHaveBeenCalled();
    expect(goto).not.toHaveBeenCalled();
  });

  it('still bounces inside the dedupe window when project detail 403s', () => {
    const removeSpy = vi.spyOn(client, 'removeQueries');

    // Prime dedupe with a sibling query.
    _handle403(
      { projectId: VALID_UUID },
      { kind: 'query', queryKey: ['datasets', VALID_UUID] },
      client,
      1_000_000,
    );
    // Project detail 403 inside the window — bounce must still fire.
    _handle403(
      { projectId: VALID_UUID },
      { kind: 'query', queryKey: ['project', VALID_UUID] },
      client,
      1_001_000,
    );

    expect(removeSpy).toHaveBeenCalledWith({
      queryKey: ['project', VALID_UUID],
      exact: true,
    });
    expect(goto).toHaveBeenCalled();
  });
});

describe('_handle403 — toast dedupe', () => {
  let client: QueryClient;

  beforeEach(() => {
    client = new QueryClient();
    toastWarning.mockClear();
    _lastToastByKey.clear();
    _resetFocusRefetchClock();
  });

  it('shows at most one toast per project within the 30s window', () => {
    _handle403({ projectId: VALID_UUID }, { kind: 'mutation' }, client, 1_000_000);
    _handle403({ projectId: VALID_UUID }, { kind: 'mutation' }, client, 1_000_500);
    _handle403({ projectId: VALID_UUID }, { kind: 'mutation' }, client, 1_020_000); // +20s

    expect(toastWarning).toHaveBeenCalledTimes(1);
  });

  it('re-arms after 30s elapsed', () => {
    _handle403({ projectId: VALID_UUID }, { kind: 'mutation' }, client, 1_000_000);
    _handle403({ projectId: VALID_UUID }, { kind: 'mutation' }, client, 1_031_000); // +31s

    expect(toastWarning).toHaveBeenCalledTimes(2);
  });

  it('keeps dedupe per-project (different projectIds → separate toasts)', () => {
    const otherProject = '99999999-aaaa-4bbb-8ccc-dddddddddddd';
    _handle403({ projectId: VALID_UUID }, { kind: 'mutation' }, client, 1_000_000);
    _handle403({ projectId: otherProject }, { kind: 'mutation' }, client, 1_000_100);

    expect(toastWarning).toHaveBeenCalledTimes(2);
  });
});

describe('_shouldRefetchOnFocus — 60s suppression after 403 (spec/009 PR 6)', () => {
  let client: QueryClient;

  beforeEach(() => {
    client = new QueryClient();
    toastWarning.mockClear();
    _lastToastByKey.clear();
    _resetFocusRefetchClock();
  });

  it('returns true when no 403 has occurred', () => {
    expect(_shouldRefetchOnFocus(1_000_000)).toBe(true);
  });

  it('returns false for 60s after a 403', () => {
    _handle403({ projectId: VALID_UUID }, { kind: 'mutation' }, client, 1_000_000);
    expect(_shouldRefetchOnFocus(1_000_100)).toBe(false);
    expect(_shouldRefetchOnFocus(1_030_000)).toBe(false);
    expect(_shouldRefetchOnFocus(1_060_000)).toBe(false);
  });

  it('returns true once 60s has elapsed since the last 403', () => {
    _handle403({ projectId: VALID_UUID }, { kind: 'mutation' }, client, 1_000_000);
    expect(_shouldRefetchOnFocus(1_060_001)).toBe(true);
  });

  it('extends suppression on every fresh 403', () => {
    _handle403({ projectId: VALID_UUID }, { kind: 'mutation' }, client, 1_000_000);
    expect(_shouldRefetchOnFocus(1_059_000)).toBe(false);
    // Fresh 403 at +59s — clock should reset.
    _handle403({ projectId: VALID_UUID }, { kind: 'mutation' }, client, 1_059_000);
    expect(_shouldRefetchOnFocus(1_100_000)).toBe(false);
    expect(_shouldRefetchOnFocus(1_119_001)).toBe(true);
  });
});
