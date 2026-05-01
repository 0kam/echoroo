/**
 * Public project detail page server load — Phase 5 US1 (T210).
 *
 * Forwards the route parameter to the client. The actual project fetch
 * (`/web-api/v1/projects/{id}`) is intentionally executed client-side via
 * TanStack Query so that Guest browsers get the same caching + retry
 * semantics used elsewhere in the app, and so that the SSR pass does not
 * carry session-bearing cookies on behalf of a Guest.
 */

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params }) => {
  return {
    projectId: params.id,
  };
};
