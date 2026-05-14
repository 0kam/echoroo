/**
 * Taxa API client for global species taxonomy.
 */

import { apiClient } from './client';
import type { GBIFSpeciesResult, TaxonSearchResult } from '$lib/types/taxon';

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
 * @param q - Search query string (scientific name or vernacular name)
 * @param limit - Maximum number of results to return (default: 10)
 */
export async function searchGBIF(q: string, limit: number = 10): Promise<GBIFSpeciesResult[]> {
  const searchParams = new URLSearchParams({ q });
  if (limit !== 10) searchParams.set('limit', String(limit));
  return apiClient.get<GBIFSpeciesResult[]>(
    `/web-api/v1/taxa/gbif-search?${searchParams.toString()}`,
  );
}
