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
 */

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params }) => {
  return {
    token: params.token,
  };
};
