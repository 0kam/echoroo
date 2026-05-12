/**
 * TanStack Query client configuration.
 *
 * Spec/007 Phase 1.5 / AD-3 (Demotion-Race Mitigation, Rev.5.1):
 * a backend-driven role demotion can take effect mid-session while
 * the SPA still holds a cached `Project` object that says the caller
 * has elevated permissions. The next mutation / query then surfaces a
 * 403, but TanStack Query only reports it to the local component —
 * the stale `['project', projectId]` cache survives and the gating
 * UI keeps showing privileged controls until the user manually
 * navigates away.
 *
 * To mitigate, every project-scoped query/mutation MUST be tagged
 * with `meta: { projectId: '<uuid>' }` (see {@link projectQueryOptions}
 * for the typed helper). The global `QueryCache.onError` /
 * `MutationCache.onError` hooks below catch the 403, refetch the
 * project detail (so role/permissions are re-derived from the
 * backend), and show a debounced toast to nudge the user. As a
 * safety net the handler also extracts a project UUID from the
 * request URL when `meta` was omitted.
 *
 * If the failing query IS the project detail itself, we instead
 * remove the cache entry and navigate to a fallback route — a
 * refetch would just 403 again and spin a loop.
 */

import {
  MutationCache,
  QueryCache,
  QueryClient,
} from '@tanstack/svelte-query';
import { goto } from '$app/navigation';
import { localizeHref } from '$lib/paraglide/runtime';
import { toasts } from '$lib/stores/toast';
import { ApiError } from './client';

/**
 * Last-toast timestamps keyed by projectId. Used to dedupe the
 * "your permissions have changed" toast — at most one per project
 * within `TOAST_DEDUPE_WINDOW_MS`.
 *
 * Exported for unit tests; production code should not read/write
 * this directly.
 */
export const _lastToastByProjectId = new Map<string, number>();

const TOAST_DEDUPE_WINDOW_MS = 5_000;

/**
 * Regex that matches a project UUID v4 segment in a request URL.
 *
 * Used as a fallback when a query/mutation forgot to declare
 * `meta: { projectId }`. Accepts both the `/api/v1/projects/{id}/...`
 * and `/web-api/v1/projects/{id}/...` surfaces because both are
 * affected by the demotion race.
 */
const PROJECT_ID_URL_RE =
  /(?:^|\/)projects\/([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})(?:\/|$|\?)/i;

/**
 * Extract a project UUID v4 from a request URL. Returns `null` if
 * no project segment is present (e.g. `/api/v1/users/me`).
 *
 * Exported for unit tests.
 */
export function extractProjectIdFromUrl(url: string | undefined | null): string | null {
  if (!url) return null;
  const m = url.match(PROJECT_ID_URL_RE);
  return m?.[1] ?? null;
}

/**
 * Type guard: is this error a 403 surfaced by the shared `ApiClient`
 * or the cookie-CSRF `callWebApi` helper? Both throw `ApiError` with
 * a numeric `status` field, so we can rely on that single check.
 */
function is403(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 403;
}

interface Handle403Source {
  kind: 'query' | 'mutation';
  queryKey?: readonly unknown[];
  /** Request URL extracted from the error, when available. */
  url?: string | null;
}

/**
 * Core demotion-race handler. Exported for unit tests; do not call
 * directly from feature code.
 */
export function _handle403(
  meta: Record<string, unknown> | undefined,
  source: Handle403Source,
  client: QueryClient,
  now: number = Date.now(),
): void {
  const metaProjectId =
    typeof meta?.projectId === 'string' && meta.projectId.length > 0
      ? (meta.projectId as string)
      : null;
  const projectId = metaProjectId ?? extractProjectIdFromUrl(source.url ?? null);

  if (!projectId) {
    // No projectId context — the failing endpoint is either
    // project-agnostic (account-level) or the caller forgot to
    // tag the query. Either way the demotion mitigation can't
    // target a specific cache key, so just warn the user.
    console.warn(
      '[permissions] 403 received without projectId context',
      { sourceKind: source.kind, queryKey: source.queryKey, url: source.url },
    );
    toasts.warning(
      'Your permissions may have changed. Please refresh the page.',
    );
    return;
  }

  // Refetch-loop guard: if the project detail query ITSELF is the
  // one that 403'd, refetching it would just 403 again. Drop the
  // cache entry and bounce to a fallback page.
  //
  // TODO(spec/007 Phase 4): replace the bounce target with a
  // dedicated `/projects/{id}/no-access` page once design lands.
  const isProjectDetailQuery =
    source.kind === 'query' &&
    Array.isArray(source.queryKey) &&
    source.queryKey.length === 2 &&
    source.queryKey[0] === 'project' &&
    source.queryKey[1] === projectId;

  if (isProjectDetailQuery) {
    client.removeQueries({ queryKey: ['project', projectId], exact: true });
    // Use a fire-and-forget navigation; goto returns a promise but
    // we have nothing useful to do on completion.
    void goto(localizeHref('/projects'), { replaceState: true });
  } else {
    void client.invalidateQueries({
      queryKey: ['project', projectId],
      refetchType: 'active',
    });
  }

  // Toast dedupe: at most one warning per project per 5s. Without
  // this, a page that fires several mutations in parallel (e.g.
  // batch vote) would stack three or four identical toasts.
  const last = _lastToastByProjectId.get(projectId) ?? 0;
  if (now - last > TOAST_DEDUPE_WINDOW_MS) {
    toasts.warning(
      'Your permissions have changed. Refreshing project access...',
    );
    _lastToastByProjectId.set(projectId, now);
  }
}

/**
 * Best-effort extraction of the request URL from an `ApiError`.
 * Our errors don't currently carry the URL, but the regex fallback
 * is still useful when callers explicitly stash one on `meta.url`
 * or when the error message embeds it. Returns `null` otherwise.
 */
function urlFromError(error: unknown, meta: Record<string, unknown> | undefined): string | null {
  if (typeof meta?.url === 'string') return meta.url as string;
  if (
    error &&
    typeof error === 'object' &&
    'request' in error &&
    (error as { request?: { url?: unknown } }).request &&
    typeof (error as { request?: { url?: unknown } }).request?.url === 'string'
  ) {
    return (error as { request: { url: string } }).request.url;
  }
  return null;
}

export const queryClient: QueryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Spec/007 AD-3: tighten the project-detail staleness window
      // so a demotion is picked up promptly on the next focus/refetch.
      // Pages can still override per-query if they need fresher data.
      staleTime: 30_000,
      refetchOnWindowFocus: true,
      retry: 1,
    },
  },
  queryCache: new QueryCache({
    onError: (error, query) => {
      if (!is403(error)) return;
      _handle403(
        query.meta as Record<string, unknown> | undefined,
        {
          kind: 'query',
          queryKey: query.queryKey,
          url: urlFromError(error, query.meta as Record<string, unknown> | undefined),
        },
        queryClient,
      );
    },
  }),
  mutationCache: new MutationCache({
    onError: (error, _variables, _context, mutation) => {
      if (!is403(error)) return;
      _handle403(
        mutation.options.meta as Record<string, unknown> | undefined,
        {
          kind: 'mutation',
          url: urlFromError(
            error,
            mutation.options.meta as Record<string, unknown> | undefined,
          ),
        },
        queryClient,
      );
    },
  }),
});
