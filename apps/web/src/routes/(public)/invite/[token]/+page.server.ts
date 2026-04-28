/**
 * Invitation landing page server load — Phase 10 / T521 (Round 2 polish).
 *
 * This page lives in the ``(public)`` layout group so that it is reachable
 * by **unauthenticated** callers as well. That intentionally diverges from
 * the original ``(app)/invite/[token]/`` location, which forced the SvelteKit
 * auth guard to redirect Guests to ``/login?redirect=/invite/{token}``.
 * That redirect leaked the signed token into the login URL, browser history,
 * and any access logs that record the ``redirect`` query parameter — see
 * Round 1 finding "Critical 1" for details.
 *
 * Why ``(public)``?
 * -----------------
 * The signed token is the credential. Putting it behind the ``(app)`` auth
 * guard meant SvelteKit's redirect machinery had to round-trip the token
 * through ``/login?redirect=...``. By moving the page under ``(public)`` we
 * bypass the redirect entirely — the page renders for both states (signed
 * out and signed in) and decides locally what to do next:
 *
 * - Signed in  → run ``POST /web-api/v1/projects/{id}/invitations/{token}/accept``.
 * - Signed out → render an in-place "sign in" CTA. The token is *never*
 *   added as a query parameter to the login URL; it stays in
 *   ``sessionStorage`` for the duration of the round-trip and the URL bar
 *   is rewritten via ``history.replaceState`` once the accept succeeds (so
 *   the browser history no longer carries the token either).
 *
 * The owning ``project_id`` is still carried as ``?project_id=...`` because
 * the recipient page must call the project-scoped accept endpoint without
 * decoding the (HMAC-signed, opaque) token client-side.
 */

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params, url }) => {
  const projectId = url.searchParams.get('project_id') ?? null;
  return {
    token: params.token,
    projectId,
  };
};
