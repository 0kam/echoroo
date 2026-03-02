/**
 * Admin layout server load
 * Checks if user is authenticated (superuser check happens client-side)
 *
 * The server hook only sets locals.isAuthenticated based on the refresh_token cookie.
 * Full user data (including is_superuser) is fetched client-side via the auth store.
 * This layout guard ensures the user at least has a valid session cookie.
 */

import { redirect } from '@sveltejs/kit';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async ({ locals, url }) => {
  // Check if user is authenticated (set by hooks.server.ts)
  if (!locals.isAuthenticated) {
    throw redirect(302, `/login?redirect=${encodeURIComponent(url.pathname)}`);
  }

  return {};
};
