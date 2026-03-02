import type { PageServerLoad } from './$types';
import { redirect } from '@sveltejs/kit';

export const load: PageServerLoad = async ({ cookies }) => {
  const refreshToken = cookies.get('refresh_token');

  if (refreshToken) {
    throw redirect(303, '/dashboard');
  }

  throw redirect(303, '/login');
};
