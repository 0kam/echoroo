/**
 * Root layout server load function
 * Checks authentication state server-side
 */

import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async ({ cookies, url }) => {
  // Check if user has refresh token cookie
  const refreshToken = cookies.get('refresh_token');
  const hasSession = !!refreshToken;

  return {
    hasSession,
    pathname: url.pathname,
  };
};
