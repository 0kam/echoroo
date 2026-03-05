/**
 * SvelteKit reroute hook for Paraglide-JS i18n URL handling.
 * Strips the locale prefix from URLs so SvelteKit can match routes correctly.
 * e.g. /en/dashboard -> /dashboard, /ja/login -> /login
 */

import type { Reroute } from '@sveltejs/kit';
import { deLocalizeUrl } from '$lib/paraglide/runtime';

export const reroute: Reroute = ({ url }) => {
  const delocalized = deLocalizeUrl(url);
  return delocalized.pathname;
};
