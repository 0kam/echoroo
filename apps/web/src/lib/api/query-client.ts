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
 *
 * Spec/009 PR 6 (post-launch UX fix): the original implementation
 * (a) did not dedupe toasts when projectId was absent (account-level
 * 403s could stack toasts), (b) re-invalidated `['project', id]` on
 * every project-scoped 403 even when a toast was already showing,
 * which combined with `refetchOnWindowFocus: true` triggered a
 * burst of duplicate requests after a single demotion. The handler
 * now keeps a unified dedupe map keyed by projectId (or the literal
 * `__no_project__` sentinel) with a longer 30 s window, suppresses
 * the invalidate while the dedupe window is open, and temporarily
 * disables window-focus refetch for 60 s so a stale token cannot
 * keep firing the same 403 burst every time the tab regains focus.
 */

import {
  MutationCache,
  QueryCache,
  QueryClient,
} from '@tanstack/svelte-query';
import { goto } from '$app/navigation';
import { localizeHref } from '$lib/paraglide/runtime';
import { toasts, toastError } from '$lib/stores/toast';
import { ApiError } from './client';

/**
 * Per-mutation meta options recognised by the global
 * `MutationCache.onError` fallback below.
 *
 * `suppressErrorToast`: opt out of the generic error toast when the
 * mutation already surfaces its own inline / toast feedback in a local
 * `onError` handler, so the user does not get double feedback.
 */
interface MutationErrorMeta {
  suppressErrorToast?: boolean;
}

/**
 * Dedupe key used when a 403 has no associated project (account-level
 * endpoints such as `/users/me` or `/admin/...`). Kept as a string
 * literal so it cannot collide with a real UUID v4.
 */
export const NO_PROJECT_KEY = '__no_project__';

/**
 * Last-toast timestamps keyed by projectId (or `NO_PROJECT_KEY`).
 * Used to dedupe the "your permissions have changed" toast and the
 * accompanying invalidate burst.
 *
 * Exported for unit tests; production code should not read/write
 * this directly.
 */
export const _lastToastByKey = new Map<string, number>();

/**
 * Backwards-compat alias retained so external imports do not break
 * while spec/009 PR 6 lands. New code MUST use `_lastToastByKey`.
 *
 * @deprecated Use {@link _lastToastByKey}.
 */
export const _lastToastByProjectId = _lastToastByKey;

const TOAST_DEDUPE_WINDOW_MS = 30_000;
const FOCUS_REFETCH_SUPPRESS_MS = 60_000;

/**
 * Timestamp of the most recent 403, regardless of project. Used to
 * temporarily disable `refetchOnWindowFocus` so a stale session
 * cannot re-fire the same 403 burst the moment the tab regains
 * focus.
 */
let _last403At = 0;

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
  _last403At = now;

  const metaProjectId =
    typeof meta?.projectId === 'string' && meta.projectId.length > 0
      ? (meta.projectId as string)
      : null;
  const projectId = metaProjectId ?? extractProjectIdFromUrl(source.url ?? null);
  const dedupeKey = projectId ?? NO_PROJECT_KEY;

  const last = _lastToastByKey.get(dedupeKey) ?? 0;
  const withinWindow = now - last <= TOAST_DEDUPE_WINDOW_MS;

  // Refetch-loop guard: if the project detail query ITSELF is the
  // one that 403'd, refetching it would just 403 again. Drop the
  // cache entry and bounce to a fallback page. This must run even
  // when the dedupe window is open, otherwise a user landing on a
  // forbidden project page would just see the cached "loading"
  // spinner without ever being redirected.
  //
  // TODO(spec/007 Phase 4): replace the bounce target with a
  // dedicated `/projects/{id}/no-access` page once design lands.
  const isProjectDetailQuery =
    projectId !== null &&
    source.kind === 'query' &&
    Array.isArray(source.queryKey) &&
    source.queryKey.length === 2 &&
    source.queryKey[0] === 'project' &&
    source.queryKey[1] === projectId;

  if (isProjectDetailQuery) {
    client.removeQueries({ queryKey: ['project', projectId], exact: true });
    void goto(localizeHref('/projects'), { replaceState: true });
  } else if (projectId !== null && !withinWindow) {
    // Only invalidate when we are about to surface a fresh toast.
    // Re-invalidating while a previous toast is still on screen just
    // produces another burst of project-scoped queries that will all
    // 403 again until the backend role change propagates.
    void client.invalidateQueries({
      queryKey: ['project', projectId],
      refetchType: 'active',
    });
  }

  if (withinWindow) {
    // Still inside the dedupe window — no toast, no invalidate.
    if (!projectId) {
      console.warn(
        '[permissions] 403 received without projectId context (deduped)',
        { sourceKind: source.kind, queryKey: source.queryKey, url: source.url },
      );
    }
    return;
  }

  if (!projectId) {
    console.warn(
      '[permissions] 403 received without projectId context',
      { sourceKind: source.kind, queryKey: source.queryKey, url: source.url },
    );
    toasts.warning(
      'Your permissions may have changed. Please refresh the page.',
    );
  } else {
    toasts.warning(
      'Your permissions have changed. Refreshing project access...',
    );
  }

  _lastToastByKey.set(dedupeKey, now);
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

/**
 * Window-focus refetch should be suppressed for `FOCUS_REFETCH_SUPPRESS_MS`
 * after the most recent 403 so a stale token cannot keep re-firing the
 * same 403 burst every time the tab regains focus. Exported for tests.
 */
export function _shouldRefetchOnFocus(now: number = Date.now()): boolean {
  if (_last403At === 0) return true;
  return now - _last403At > FOCUS_REFETCH_SUPPRESS_MS;
}

/**
 * Test-only helper: reset the suppression clock between tests so
 * unrelated test ordering does not leak state.
 */
export function _resetFocusRefetchClock(): void {
  _last403At = 0;
}

export const queryClient: QueryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Spec/007 AD-3: tighten the project-detail staleness window
      // so a demotion is picked up promptly on the next focus/refetch.
      // Pages can still override per-query if they need fresher data.
      staleTime: 30_000,
      // Spec/009 PR 6: function form lets us suppress focus-refetch
      // for FOCUS_REFETCH_SUPPRESS_MS after a 403 so a stale session
      // does not keep replaying the same 403 burst on every focus.
      refetchOnWindowFocus: () => _shouldRefetchOnFocus(),
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
      if (is403(error)) {
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
        return;
      }

      // Generic fallback for non-403 mutation failures: surface a toast
      // so the user always gets feedback, UNLESS the mutation opts out
      // via `meta: { suppressErrorToast: true }` because it already
      // renders its own inline / toast error.
      const meta = mutation.options.meta as MutationErrorMeta | undefined;
      if (meta?.suppressErrorToast) return;
      toastError(error);
    },
  }),
});
