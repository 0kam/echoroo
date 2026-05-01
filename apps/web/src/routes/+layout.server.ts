/**
 * Root layout server load function
 * Checks authentication state server-side via the non-sensitive
 * `echoroo_logged_in` marker cookie set by the web-auth backend.
 */

import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async ({ cookies, url }) => {
  const loggedInMarker = cookies.get('echoroo_logged_in');
  const hasSession = loggedInMarker === '1';

  return {
    hasSession,
    pathname: url.pathname,
  };
};
