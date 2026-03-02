/**
 * Detection Review page server load.
 *
 * Passes route params to the page component.
 */

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params }) => {
  return {
    projectId: params.id,
    tagId: params.tagId,
  };
};
