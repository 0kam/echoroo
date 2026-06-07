/**
 * Taxa API client for global species taxonomy.
 */

import { apiClient } from './client';
import type { GBIFSpeciesResult, TaxonSearchResult } from '$lib/types/taxon';

const CSRF_COOKIE_NAME = 'echoroo_csrf';

/**
 * Read the double-submit CSRF token from the cookie set by the BFF login flow.
 * Mirrors the helper in `tags.ts`; mutating `/web-api/v1` routes require the
 * `X-CSRF-Token` header to match this cookie.
 */
function getCsrfToken(): string | null {
  if (typeof document === 'undefined') return null;
  const prefix = `${CSRF_COOKIE_NAME}=`;
  const parts = document.cookie ? document.cookie.split('; ') : [];
  for (const part of parts) {
    if (part.startsWith(prefix)) {
      try {
        return decodeURIComponent(part.slice(prefix.length));
      } catch {
        return part.slice(prefix.length);
      }
    }
  }
  return null;
}

function csrfHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const token = getCsrfToken();
  if (token) headers['X-CSRF-Token'] = token;
  return headers;
}

/**
 * Search taxa by name (scientific or vernacular) with optional locale preference.
 *
 * @param q - Search query string
 * @param locale - BCP 47 locale code for vernacular name resolution (e.g. "en", "ja")
 * @param limit - Maximum number of results to return (default: 20)
 */
export async function searchTaxa(
  q: string,
  locale?: string,
  limit: number = 20,
): Promise<TaxonSearchResult[]> {
  const searchParams = new URLSearchParams({ q });
  if (locale) searchParams.set('locale', locale);
  if (limit !== 20) searchParams.set('limit', String(limit));
  return apiClient.get<TaxonSearchResult[]>(`/web-api/v1/taxa/search?${searchParams.toString()}`);
}

/**
 * Search the GBIF backbone taxonomy in real-time for species not yet in the local database.
 *
 * When a non-`en` `locale` is supplied the backend live-enriches each result:
 * `vernacular_names` gains a locale-tagged entry (e.g. language `"ja"`) and
 * `vernacular_name` is overwritten with the locale-resolved value.
 *
 * @param q - Search query string (scientific name or vernacular name)
 * @param limit - Maximum number of results to return (default: 10)
 * @param locale - BCP 47 locale code for vernacular name enrichment (e.g. "en", "ja")
 */
export async function searchGBIF(
  q: string,
  limit: number = 10,
  locale?: string,
): Promise<GBIFSpeciesResult[]> {
  const searchParams = new URLSearchParams({ q });
  if (limit !== 10) searchParams.set('limit', String(limit));
  if (locale) searchParams.set('locale', locale);
  return apiClient.get<GBIFSpeciesResult[]>(
    `/web-api/v1/taxa/gbif-search?${searchParams.toString()}`,
  );
}

/**
 * Materialise a live GBIF search pick into a local taxon (get-or-create).
 *
 * Used by the annotation-set palette: when a user picks a species straight
 * from GBIF (no local taxon row exists yet) we POST it here to obtain a
 * `taxon_id` that the palette can store. Idempotent — repeated calls for the
 * same species return the same taxon.
 *
 * @param scientificName - Canonical scientific name of the GBIF pick
 * @param gbifKey - GBIF backbone taxon key, when known
 * @param commonName - Vernacular name to seed, when available
 * @param locale - BCP 47 locale for the returned `common_name` resolution
 * @param vernacularNames - Language-tagged vernacular names from the GBIF pick;
 *   persisted server-side so the materialized taxon keeps its locale names
 *   (e.g. 和名). When omitted only `common_name` is seeded (backward compat).
 */
export async function createTaxonFromGbif(
  scientificName: string,
  gbifKey?: number | null,
  commonName?: string | null,
  locale?: string,
  vernacularNames?: Array<{ name: string; language: string; source?: string }> | null,
): Promise<TaxonSearchResult> {
  const searchParams = new URLSearchParams();
  if (locale) searchParams.set('locale', locale);
  const qs = searchParams.toString() ? `?${searchParams.toString()}` : '';
  return apiClient.post<TaxonSearchResult>(
    `/web-api/v1/taxa/from-gbif${qs}`,
    {
      scientific_name: scientificName,
      gbif_taxon_key: gbifKey ?? null,
      common_name: commonName ?? null,
      vernacular_names: vernacularNames ?? null,
    },
    { headers: csrfHeaders() },
  );
}
