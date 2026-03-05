/**
 * Taxa API client for global species taxonomy.
 */

import { apiClient } from './client';
import type { TaxonDetail, TaxonListResponse, TaxonSearchResult } from '$lib/types/taxon';

/**
 * Query parameters for listing taxa.
 */
export interface TaxaListParams {
  /** Search term matched against scientific name and vernacular names */
  search?: string;
  /** Filter to non-biological sound sources only */
  is_non_biological?: boolean;
  /** Page number (1-indexed) */
  page?: number;
  /** Number of items per page */
  page_size?: number;
}

/**
 * Fetch a paginated list of taxa.
 */
export async function fetchTaxa(params: TaxaListParams = {}): Promise<TaxonListResponse> {
  const searchParams = new URLSearchParams();
  if (params.search) searchParams.set('search', params.search);
  if (params.is_non_biological !== undefined)
    searchParams.set('is_non_biological', String(params.is_non_biological));
  if (params.page) searchParams.set('page', String(params.page));
  if (params.page_size) searchParams.set('page_size', String(params.page_size));
  const query = searchParams.toString();
  return apiClient.get<TaxonListResponse>(`/api/v1/taxa${query ? `?${query}` : ''}`);
}

/**
 * Fetch a single taxon by ID, including full GBIF metadata and vernacular names.
 */
export async function fetchTaxon(taxonId: string): Promise<TaxonDetail> {
  return apiClient.get<TaxonDetail>(`/api/v1/taxa/${taxonId}`);
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
  return apiClient.get<TaxonSearchResult[]>(`/api/v1/taxa/search?${searchParams.toString()}`);
}
