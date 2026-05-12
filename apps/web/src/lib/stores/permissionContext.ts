/**
 * Permission context store helper (Spec 007 Phase 2B.1 / Plan Rev.5.1 AD-2).
 *
 * Centralises the derivation of `ProjectContext` from the auth store,
 * the TanStack Query project result, and the optional pending
 * invitation token. Pages call `usePermissionContext({ projectQuery,
 * routeParams })` and consume the returned `Readable<ProjectContext>`
 * via `$ctx` together with `can()` — see AD-2.
 *
 * Rationale (Codex Rev.2 Q16): without this helper each page
 * re-implements authState calculation (auth.store + projectQuery +
 * URL token), defeating the AD-2 unification goal.
 */

import { derived, readable, type Readable } from 'svelte/store';
import type { CreateQueryResult } from '@tanstack/svelte-query';

import { authStore } from './auth.svelte';
import type { Project } from '$lib/types';
import {
  buildProjectContext,
  type ProjectContext,
} from '$lib/utils/permissions';

/**
 * Shape of the TanStack Query result subset we care about. Accepting
 * the full `CreateQueryResult<Project, Error>` keeps the contract
 * compatible with `createQuery({...})` usage everywhere in the app.
 */
export type ProjectQueryStore = CreateQueryResult<Project, Error>;

export interface UsePermissionContextArgs {
  projectQuery: ProjectQueryStore;
  routeParams: { invitationToken?: string | null };
}

/**
 * Derive a `ProjectContext` store from the inputs above.
 *
 * The derived store recomputes whenever the project query result
 * changes. Auth store changes are picked up via a thin wrapper
 * `readable` (auth store is a runes-based getter object, not a
 * Svelte store, so we re-read it on each query tick — for launch
 * this is sufficient since the auth store is bootstrapped before
 * any project route mounts; multi-tab demotion races are handled
 * by 403-driven invalidation, see AD-3).
 */
export function usePermissionContext(
  args: UsePermissionContextArgs
): Readable<ProjectContext> {
  const { projectQuery, routeParams } = args;
  const invitationToken = routeParams.invitationToken ?? null;

  return derived(projectQuery, ($projectQuery) => {
    return buildProjectContext({
      authStore: {
        isAuthenticated: authStore.isAuthenticated,
        user: authStore.user,
      },
      project: $projectQuery.data,
      projectQueryState: {
        isLoading: $projectQuery.isLoading,
        isError: $projectQuery.isError,
      },
      pendingInvitationToken: invitationToken,
    });
  });
}

/**
 * Construct a Readable<ProjectContext> from a literal context.
 * Useful in tests and Storybook stories where wiring up a full
 * TanStack Query store would be overkill.
 */
export function readableProjectContext(
  ctx: ProjectContext
): Readable<ProjectContext> {
  return readable(ctx);
}
