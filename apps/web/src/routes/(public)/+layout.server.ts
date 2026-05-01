/**
 * (public) layout server load — Phase 5 US1 (T211).
 *
 * This layout group is intentionally NOT auth-guarded. It must be reachable
 * by Guest callers (no `echoroo_logged_in` marker cookie) so unauthenticated
 * visitors can browse Public + Active projects per FR-009 / FR-016.
 *
 * Authenticated users may still traverse these pages — when they are signed
 * in we surface a "Back to dashboard" link via the layout shell instead of
 * the sign-in CTA. The actual project detail load is performed client-side
 * via TanStack Query against `/web-api/v1/projects/{id}` (T200).
 *
 * Note: the root `hooks.server.ts` PROTECTED_ROUTES list does NOT cover the
 * `/explore/*` URL prefix used by this group, so Guests reach this layout
 * without being bounced to /login.
 */

import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async ({ locals }) => {
  // `isAuthenticated` is set by `hooks.server.ts` via the non-sensitive
  // `echoroo_logged_in` marker cookie. We forward both the flag and the
  // negotiated locale so the public layout shell can render the correct
  // CTA + language switcher state without an extra round-trip.
  return {
    isAuthenticated: locals.isAuthenticated,
    locale: locals.locale,
  };
};
