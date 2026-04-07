/**
 * Detections page server load - passes route params to the page.
 */

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params }) => {
  return {
    projectId: params.id,
  };
};
