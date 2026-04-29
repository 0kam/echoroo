/**
 * Admin layout server load (Phase 15 / 006-permissions-redesign T955).
 *
 * Two-stage gate:
 *   1. The session cookie set by `hooks.server.ts` populates
 *      `locals.isAuthenticated`.  When missing, redirect to /login with
 *      the original path preserved as `redirect=`.
 *   2. The full superuser check lives client-side in `+layout.svelte`
 *      because the access token (and therefore /users/me) is bound to the
 *      browser session, not the server-side session cookie.
 *
 * Per FR-084 the admin section is accessible only via the cookie session
 * — programmatic API key callers cannot reach these routes because the
 * backend rejects superuser actions when the request was authenticated
 * via API key.  This layout server runs only on the SvelteKit edge so
 * the same restriction is naturally upheld.
 */

import { redirect } from '@sveltejs/kit';
import type { LayoutServerLoad } from './$types';
import { localizeHref, deLocalizeHref } from '$lib/paraglide/runtime';

export const load: LayoutServerLoad = async ({ locals, url }) => {
  if (!locals.isAuthenticated) {
    const returnPath = deLocalizeHref(url.pathname);
    throw redirect(
      302,
      localizeHref(`/login?redirect=${encodeURIComponent(returnPath)}`),
    );
  }

  return {};
};
