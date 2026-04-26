import type { PageServerLoad } from './$types';
import { redirect } from '@sveltejs/kit';
import { localizeHref } from '$lib/paraglide/runtime';

export const load: PageServerLoad = async ({ cookies }) => {
  const loggedInMarker = cookies.get('echoroo_logged_in');

  if (loggedInMarker === '1') {
    throw redirect(303, localizeHref('/dashboard'));
  }

  throw redirect(303, localizeHref('/login'));
};
