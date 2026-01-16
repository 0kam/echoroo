/**
 * Admin layout server load
 * Checks if user is superuser
 */

import { redirect } from '@sveltejs/kit';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async ({ locals, url }) => {
  // Check if user is authenticated
  if (!locals.user) {
    throw redirect(302, `/login?redirect=${encodeURIComponent(url.pathname)}`);
  }

  // Check if user is superuser
  if (!locals.user.is_superuser) {
    throw redirect(302, '/dashboard');
  }

  return {
    user: locals.user,
  };
};
