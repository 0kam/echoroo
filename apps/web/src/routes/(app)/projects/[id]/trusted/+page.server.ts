/**
 * Trusted User management page (Phase 10 / T520).
 *
 * Server-side loader only forwards the path parameter so the client-side
 * component can drive the data fetch + role-based UI gating. We
 * intentionally do not fetch the project + trusted-list here so that
 * unauthorised callers receive the same `(app)` layout shell instead of
 * a server-side 5xx, mirroring the project detail page (`+page.server.ts`).
 */

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params }) => {
  return {
    projectId: params.id,
  };
};
