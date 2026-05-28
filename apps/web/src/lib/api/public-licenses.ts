/**
 * Public license list API + TanStack Query hook (spec/012 PR-B / T025).
 *
 * The project creation form (`/projects/new`) calls this hook to populate
 * its license dropdown live from the operator-curated `licenses` master
 * table (FR-001 / FR-002). Backed by `GET /web-api/v1/licenses` which
 * returns the master ordered by `short_name` ascending and is accessible
 * to any authenticated user (FR-017).
 *
 * `licenses.ts` (next to this file) covers the superuser CRUD surface at
 * `/web-api/v1/admin/licenses/*`. The two files share the same `License`
 * type but never share endpoints — keeping them split avoids accidentally
 * gating the public read behind admin auth.
 *
 * ## TanStack Query configuration
 *
 * Per research §R5 (revised after Codex review), the cache is configured
 * with `staleTime: 0` and `refetchOnMount: 'always'` so every time the
 * form mounts a fresh fetch fires. This satisfies SC-001 ("admin add to
 * user-visible within 5 s") without any cache-invalidation choreography:
 *
 * - Admin opens admin tab → adds `CC-BY-ND` row.
 * - User switches to the `/projects/new` tab they had open.
 * - Re-mount triggers a fresh fetch — the new row is in the dropdown.
 *
 * In-flight deduplication still works (concurrent mounts share one
 * network call), so this is not "no caching" — just no *stale* caching.
 */

import { createQuery, type CreateQueryOptions } from '@tanstack/svelte-query';

import type { LicenseListResponse } from '$lib/types';
import { apiClient } from './client';

const WEB_API_BASE = '/web-api/v1';

/**
 * Stable query key for the public license list. Exported so callers
 * (e.g. tests, manual cache invalidation) can target the same key the
 * hook installs.
 */
export const LICENSES_QUERY_KEY = ['public-licenses'] as const;

/**
 * Fetch the public license list. Used by `useLicenses()` and exposed as a
 * standalone export so non-hook callers (server-side prefetch, tests,
 * manual refetches) can hit the same endpoint without re-implementing the
 * URL.
 */
export async function fetchPublicLicenses(): Promise<LicenseListResponse> {
  return apiClient.get<LicenseListResponse>(`${WEB_API_BASE}/licenses`);
}

/**
 * TanStack Query hook for the public license list (spec/012 PR-B / T025).
 *
 * Components MUST call this inside a Svelte reactive context (e.g. a
 * `$derived` expression) so the store reactivity wires up correctly.
 * Returns the standard `createQuery` store — read `$query.data`,
 * `$query.isLoading`, `$query.error` in the template.
 *
 * The `staleTime: 0` + `refetchOnMount: 'always'` pair is intentional
 * (research §R5). Callers that want to override these MUST do so
 * deliberately; this hook does not expose them as parameters because
 * SC-001 compliance depends on the defaults.
 */
export function useLicenses() {
  const options: CreateQueryOptions<LicenseListResponse> = {
    queryKey: [...LICENSES_QUERY_KEY],
    queryFn: fetchPublicLicenses,
    // SC-001 (admin → user within 5 s): no stale cache window.
    staleTime: 0,
    // Force a refetch every time the form mounts so admin-added rows
    // become visible without waiting for TanStack Query's default
    // background refresh heuristics.
    refetchOnMount: 'always',
  };
  return createQuery(options);
}
