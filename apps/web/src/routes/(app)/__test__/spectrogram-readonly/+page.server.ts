// Test fixture route — for E2E testing only. DO NOT use in production.
// Guard: only accessible when running in dev mode. In production builds
// (e.g. if this file is ever bundled), the route responds with 404.

import { error } from '@sveltejs/kit';
import { dev } from '$app/environment';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async () => {
  if (!dev) {
    throw error(404, 'Not found');
  }
  return {};
};
