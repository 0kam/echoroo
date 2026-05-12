/**
 * Typed helper that enforces `meta: { projectId }` on every
 * project-scoped TanStack Query factory.
 *
 * Spec/007 Phase 1.5 / AD-3 / Q23: the global `QueryCache.onError`
 * hook (see `query-client.ts`) relies on `meta.projectId` to know
 * which `['project', projectId]` cache entry to invalidate on a 403
 * demotion. Hand-written `createQuery({ ... })` call-sites can
 * forget to attach `meta` — and a missed `meta` means the demotion
 * mitigation silently no-ops, leaving stale role data in the cache.
 *
 * Routing every project-scoped factory through this helper makes
 * the requirement load-bearing at the type level: the wrapped
 * `meta` field is required, and the runtime body splats the caller
 * options on top so other overrides (staleTime, retry, ...) still
 * apply.
 *
 * Usage (query):
 * ```ts
 * createQuery(
 *   projectQueryOptions(projectId, {
 *     queryKey: ['datasets', projectId],
 *     queryFn: () => fetchDatasets(projectId),
 *   }),
 * );
 * ```
 *
 * Usage (mutation):
 * ```ts
 * createMutation(
 *   projectMutationOptions(projectId, {
 *     mutationFn: (input) => addMember(projectId, input),
 *   }),
 * );
 * ```
 */

import type {
  CreateMutationOptions,
  CreateQueryOptions,
  DefaultError,
  QueryKey,
} from '@tanstack/svelte-query';

/**
 * The shape stamped into `meta` for every project-scoped
 * query/mutation. Extra fields are allowed so callers can add
 * their own diagnostics, but `projectId` is mandatory and must be
 * a non-empty string.
 */
export interface ProjectMeta {
  projectId: string;
  [extra: string]: unknown;
}

/**
 * Wrap `createQuery` options so the `meta.projectId` is filled in
 * automatically. Caller-supplied `meta` (e.g. analytics tags) is
 * merged in, but `projectId` always wins to prevent accidental
 * shadowing.
 */
export function projectQueryOptions<
  TQueryFnData = unknown,
  TError = DefaultError,
  TData = TQueryFnData,
  TQueryKey extends QueryKey = QueryKey,
>(
  projectId: string,
  options: Omit<
    CreateQueryOptions<TQueryFnData, TError, TData, TQueryKey>,
    'meta'
  > & { meta?: Record<string, unknown> },
): CreateQueryOptions<TQueryFnData, TError, TData, TQueryKey> {
  return {
    ...options,
    meta: { ...(options.meta ?? {}), projectId },
  } as CreateQueryOptions<TQueryFnData, TError, TData, TQueryKey>;
}

/**
 * Mutation counterpart to {@link projectQueryOptions}. Same
 * semantics: `meta.projectId` is stamped onto the options so the
 * global `MutationCache.onError` hook can locate the right
 * `['project', projectId]` cache entry on 403.
 */
export function projectMutationOptions<
  TData = unknown,
  TError = DefaultError,
  TVariables = void,
  TOnMutateResult = unknown,
>(
  projectId: string,
  options: Omit<
    CreateMutationOptions<TData, TError, TVariables, TOnMutateResult>,
    'meta'
  > & { meta?: Record<string, unknown> },
): CreateMutationOptions<TData, TError, TVariables, TOnMutateResult> {
  return {
    ...options,
    meta: { ...(options.meta ?? {}), projectId },
  } as CreateMutationOptions<TData, TError, TVariables, TOnMutateResult>;
}
