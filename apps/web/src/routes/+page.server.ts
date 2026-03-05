import type { PageServerLoad } from './$types';
import { redirect } from '@sveltejs/kit';
import { localizeHref } from '$lib/paraglide/runtime';

export const load: PageServerLoad = async ({ cookies }) => {
  const refreshToken = cookies.get('refresh_token');

  if (refreshToken) {
    throw redirect(303, localizeHref('/dashboard'));
  }

  throw redirect(303, localizeHref('/login'));
};
