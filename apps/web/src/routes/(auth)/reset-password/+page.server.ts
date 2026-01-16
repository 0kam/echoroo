/**
 * Reset password page server load
 */

import type { PageServerLoad } from './$types';
import { error } from '@sveltejs/kit';

export const load: PageServerLoad = async ({ url }) => {
  const token = url.searchParams.get('token');

  if (!token) {
    throw error(400, 'Reset token is required');
  }

  return {
    token,
  };
};
