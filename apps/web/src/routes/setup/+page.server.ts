/**
 * Setup page server-side load function
 * Checks setup status and redirects if already completed
 */

import type { PageServerLoad } from './$types';
import { redirect } from '@sveltejs/kit';
import { ApiClient } from '$lib/api/client';

export const load: PageServerLoad = async () => {
  const apiClient = new ApiClient();

  try {
    // Check setup status from backend
    const setupStatus = await apiClient.get<{
      setup_required: boolean;
      setup_completed: boolean;
    }>('/api/setup/status');

    // If setup is already completed, redirect to login
    if (setupStatus.setup_completed) {
      throw redirect(303, '/login');
    }

    return {
      setupStatus,
    };
  } catch (error) {
    // If error is a redirect, rethrow it
    if (error instanceof Response && error.status === 303) {
      throw error;
    }

    // For other errors, return default status
    return {
      setupStatus: {
        setup_required: true,
        setup_completed: false,
      },
    };
  }
};
