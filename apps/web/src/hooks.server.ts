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

/**
 * Validate refresh token against the backend.
 * Returns true if the token is valid, false otherwise.
 * Also returns the new set-cookie header from the backend if the token was refreshed.
 */
async function validateRefreshToken(
  refreshToken: string
): Promise<{ valid: boolean; setCookieHeader: string | null }> {
  try {
    const response = await fetch(`${getServerApiUrl()}/api/v1/auth/refresh`, {
      method: 'POST',
      headers: {
        Cookie: `refresh_token=${refreshToken}`,
        'Content-Type': 'application/json',
      },
      signal: AbortSignal.timeout(5000),
    });

    if (response.ok) {
      return {
        valid: true,
        setCookieHeader: response.headers.get('set-cookie'),
      };
    }

    // 401 or other error means token is invalid
    return { valid: false, setCookieHeader: null };
  } catch {
    // Backend unreachable - fail open to preserve availability
    // The client-side auth initialization will handle further validation
    return { valid: true, setCookieHeader: null };
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
  let isAuthenticated = false;

  if (refreshToken) {
    // Check if we've recently validated this session (cache for 5 minutes)
    const recentlyValidated = cookies.get('_auth_validated');

    if (recentlyValidated) {
      // Session was validated recently, trust the cached result
      isAuthenticated = true;
    } else {
      // Validate token against the backend
      const { valid, setCookieHeader } = await validateRefreshToken(refreshToken);

      if (valid) {
        isAuthenticated = true;

        // Cache the validation result for 5 minutes to avoid hitting backend on every request
        cookies.set('_auth_validated', '1', {
          path: '/',
          maxAge: 300,
          httpOnly: true,
          secure: false, // dev environment; set to true in production
          sameSite: 'lax',
        });

        // Forward the updated refresh token cookie from the backend if provided
        if (setCookieHeader) {
          // Extract the refresh_token value from the Set-Cookie header
          // Format: "refresh_token=<value>; Path=...; ..."
          const match = setCookieHeader.match(/refresh_token=([^;]+)/);
          const newTokenValue = match?.[1];
          if (newTokenValue) {
            cookies.set('refresh_token', newTokenValue, {
              path: '/',
              httpOnly: true,
              secure: false,
              sameSite: 'lax',
            });
          }
        }
      } else {
        // Token is invalid - clear both possible cookie paths
        // The cookie may have been set on '/' (old) or '/api/v1/auth' (new)
        cookies.delete('refresh_token', { path: '/' });
        cookies.delete('refresh_token', { path: '/' });
        cookies.delete('_auth_validated', { path: '/' });
        isAuthenticated = false;
      }
    }
  }

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
