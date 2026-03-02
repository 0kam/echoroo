/**
 * SvelteKit server hooks
 * Handle authentication, protected routes, and initial setup
 */

import type { Handle } from '@sveltejs/kit';
import { redirect } from '@sveltejs/kit';

// Define protected routes that require authentication
const PROTECTED_ROUTES = [
  '/dashboard',
  '/recordings',
  '/annotations',
  '/projects',
  '/admin',
  '/profile',
  '/settings',
];

// Define auth routes that should redirect authenticated users
const AUTH_ROUTES = [
  '/login',
  '/register',
  '/forgot-password',
  '/reset-password',
  '/verify-email',
];

/**
 * Check if a path is protected
 */
function isProtectedRoute(pathname: string): boolean {
  return PROTECTED_ROUTES.some((route) => pathname.startsWith(route));
}

/**
 * Check if a path is an auth route
 */
function isAuthRoute(pathname: string): boolean {
  return AUTH_ROUTES.some((route) => pathname.startsWith(route));
}

/**
 * Get backend API URL for server-side requests.
 * In Docker, ECHOROO_API_URL points to the backend service (e.g., http://backend:8000).
 * For local development outside Docker, defaults to http://localhost:8002.
 */
function getServerApiUrl(): string {
  return process.env.ECHOROO_API_URL || 'http://localhost:8002';
}

/**
 * Check setup status from backend
 */
async function checkSetupStatus(): Promise<{
  setup_required: boolean;
  setup_completed: boolean;
}> {
  try {
    const response = await fetch(`${getServerApiUrl()}/api/v1/setup/status`);
    if (!response.ok) {
      throw new Error(`API returned ${response.status}`);
    }
    return await response.json();
  } catch {
    // If API is not available or returns error, assume setup is not required
    // This prevents infinite redirect loops during development
    return {
      setup_required: false,
      setup_completed: true,
    };
  }
}

export const handle: Handle = async ({ event, resolve }) => {
  const { cookies, url } = event;

  // Check setup status before handling any other routing logic
  const setupStatus = await checkSetupStatus();

  // If setup is required and user is not on /setup page, redirect to setup
  if (setupStatus.setup_required && !setupStatus.setup_completed && url.pathname !== '/setup') {
    throw redirect(303, '/setup');
  }

  // If setup is completed and user is trying to access /setup, redirect to login
  if (setupStatus.setup_completed && url.pathname === '/setup') {
    throw redirect(303, '/login');
  }

  // Check if user has refresh token cookie (indicates authenticated session)
  const refreshToken = cookies.get('refresh_token');
  const isAuthenticated = !!refreshToken;

  // Store auth state in locals for use in load functions
  event.locals.isAuthenticated = isAuthenticated;

  // Handle protected routes - redirect unauthenticated users to login
  if (isProtectedRoute(url.pathname) && !isAuthenticated) {
    // Redirect to login with return URL
    const returnUrl = encodeURIComponent(url.pathname + url.search);
    throw redirect(303, `/login?redirect=${returnUrl}`);
  }

  // Handle auth routes - redirect authenticated users to dashboard
  if (isAuthenticated && isAuthRoute(url.pathname)) {
    throw redirect(303, '/dashboard');
  }

  // Continue with the request
  const response = await resolve(event);
  return response;
};
