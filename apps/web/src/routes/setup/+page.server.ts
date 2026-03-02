/**
 * Setup page server-side load function
 * Checks setup status and redirects if already completed
 */

import type { PageServerLoad } from './$types';
import { redirect } from '@sveltejs/kit';

function getServerApiUrl(): string {
  return process.env.ECHOROO_API_URL || 'http://localhost:8002';
}

export const load: PageServerLoad = async () => {
  try {
    const response = await fetch(`${getServerApiUrl()}/api/v1/setup/status`);
    if (!response.ok) {
      throw new Error(`API returned ${response.status}`);
    }
    const setupStatus = await response.json();

    // If setup is already completed, redirect to login
    if (setupStatus.setup_completed) {
      throw redirect(303, '/login');
    }

    return {
      setupStatus,
    };
  } catch (error) {
    // If error is a redirect, rethrow it
    if (error && typeof error === 'object' && 'status' in error && error.status === 303) {
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
