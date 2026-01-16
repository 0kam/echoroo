/**
 * Email verification page server load
 */

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ url }) => {
  const token = url.searchParams.get('token');
  const registered = url.searchParams.get('registered') === 'true';

  return {
    token,
    registered,
  };
};
