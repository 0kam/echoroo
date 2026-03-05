/**
 * SvelteKit server hooks
 * Handle authentication, protected routes, and initial setup.
 * Integrates Paraglide-JS middleware for URL-based locale routing.
 */

import type { Handle } from '@sveltejs/kit';
import { redirect } from '@sveltejs/kit';
import { paraglideMiddleware } from '$lib/paraglide/server';
import { localizeHref, deLocalizeHref } from '$lib/paraglide/runtime';

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
 * Check if a path is protected (strips locale prefix before matching)
 */
function isProtectedRoute(pathname: string): boolean {
  const delocalized = deLocalizeHref(pathname);
  return PROTECTED_ROUTES.some((route) => delocalized.startsWith(route));
}

/**
 * Check if a path is an auth route (strips locale prefix before matching)
 */
function isAuthRoute(pathname: string): boolean {
  const delocalized = deLocalizeHref(pathname);
  return AUTH_ROUTES.some((route) => delocalized.startsWith(route));
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

/**
 * Combined Paraglide i18n + auth handle.
 *
 * The paraglideMiddleware must wrap the entire auth logic so that
 * AsyncLocalStorage context (locale) is available when localizeHref() is called.
 * Excludes API, S3 proxy, and favicon routes from i18n processing.
 */
export const handle: Handle = ({ event, resolve }) => {
  const { pathname } = event.url;

  // Skip i18n processing for API, S3 proxy, and static asset routes
  if (
    pathname.startsWith('/api/') ||
    pathname.startsWith('/s3-proxy/') ||
    pathname.startsWith('/favicon.')
  ) {
    return handleAuth(event, resolve);
  }

  // Wrap auth logic inside paraglideMiddleware so locale context is available
  return paraglideMiddleware(event.request, async ({ request, locale }) => {
    // Store locale in locals for use in load functions
    event.locals.locale = locale;
    // Update the event request to the de-localized version for SvelteKit routing
    event.request = request;
    return handleAuth(event, resolve, locale);
  });
};

/**
 * Auth and routing logic (called inside paraglide middleware context)
 */
async function handleAuth(
  event: Parameters<Handle>[0]['event'],
  resolve: Parameters<Handle>[0]['resolve'],
  locale?: string
): Promise<Response> {
  const { cookies, url } = event;

  // Check setup status before handling any other routing logic
  const setupStatus = await checkSetupStatus();

  const deLocalizedPath = deLocalizeHref(url.pathname);

  // If setup is required and user is not on /setup page, redirect to setup
  if (setupStatus.setup_required && !setupStatus.setup_completed && deLocalizedPath !== '/setup') {
    throw redirect(303, localizeHref('/setup'));
  }

  // If setup is completed and user is trying to access /setup, redirect to login
  if (setupStatus.setup_completed && deLocalizedPath === '/setup') {
    throw redirect(303, localizeHref('/login'));
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
        cookies.delete('_auth_validated', { path: '/' });
        isAuthenticated = false;
      }
    }
  }

  // Store auth state in locals for use in load functions
  event.locals.isAuthenticated = isAuthenticated;

  // Handle protected routes - redirect unauthenticated users to login
  if (isProtectedRoute(url.pathname) && !isAuthenticated) {
    // Redirect to login with return URL (use de-localized path for redirect param)
    const returnUrl = encodeURIComponent(deLocalizeHref(url.pathname) + url.search);
    throw redirect(303, localizeHref(`/login?redirect=${returnUrl}`));
  }

  // Handle auth routes - redirect authenticated users to dashboard
  if (isAuthenticated && isAuthRoute(url.pathname)) {
    throw redirect(303, localizeHref('/dashboard'));
  }

  // Continue with the request, replacing the %paraglide.lang% placeholder in the HTML
  const response = await resolve(event, {
    transformPageChunk: ({ html }) =>
      locale ? html.replace('%paraglide.lang%', locale) : html,
  });
  return response;
}
