/**
 * Invitation landing page server load.
 *
 * This page lives in the ``(public)`` layout group so it is reachable by
 * **unauthenticated** callers without the ``(app)`` auth guard bouncing them
 * through ``/login?redirect=/invite/{token}`` (which would leak the signed
 * token into the login URL, browser history, and access logs).
 *
 * The signed token is the credential and is the only thing this loader needs
 * to surface. The page itself drives the rest of the flow client-side:
 * ``resolveInvitation(token)`` (public resolver) decides the signed-out vs.
 * signed-in branch, then ``acceptInvitation(token, …)`` performs the in-page
 * accept and navigates to the project returned in the accept response.
 *
 * Token-hydration race fix (spec/011 Gate 3)
 * ------------------------------------------
 * We also surface ``isAuthenticated`` — derived server-side from the HttpOnly
 * ``echoroo_logged_in`` marker cookie in ``hooks.server.ts`` (stored on
 * ``locals.isAuthenticated``). The browser cannot read that marker itself
 * (it is ``HttpOnly``), so this boolean is the page's only reliable signal of
 * whether a real session already exists. The page uses it to decide whether
 * to AWAIT in-memory access-token hydration before the first
 * ``resolveInvitation`` call. A hard navigation into this page wipes the
 * in-memory access token, so a logged-in invitee would otherwise lose the
 * race against the root layout's fire-and-forget ``authStore.initialize()``
 * and resolve anonymously → 401 → error panel. For a genuinely logged-out
 * new user the marker is absent, so the page skips hydration entirely and
 * resolves anonymously (the signup branch).
 */

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params, locals }) => {
  return {
    token: params.token,
    // Server-read session signal (HttpOnly marker → not browser-readable).
    isAuthenticated: locals.isAuthenticated,
  };
};
