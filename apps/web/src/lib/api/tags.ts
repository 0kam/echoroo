/**
 * Tags API client for TanStack Query.
 */

import type {
  GBIFSuggestion,
  Tag,
  TagCreate,
  TagDetail,
  TagListParams,
  TagListResponse,
  TagStatistic,
  TagUpdate,
} from '$lib/types/annotation';
import { apiClient } from './client';

const API_BASE = '/api/v1';

/**
 * Fetch paginated tags for a project.
 *
 * Pass `locale` so the backend can resolve each tag's `vernacular_name` for
 * the requested language (BCP-47 code, e.g. "en", "ja").
 */
export async function fetchTags(
  projectId: string,
  params: TagListParams & { locale?: string } = {}
): Promise<TagListResponse> {
  const searchParams = new URLSearchParams();
  if (params.page) searchParams.set('page', params.page.toString());
  if (params.page_size) searchParams.set('page_size', params.page_size.toString());
  if (params.category) searchParams.set('category', params.category);
  if (params.search) searchParams.set('search', params.search);
  if (params.locale) searchParams.set('locale', params.locale);

  const url = `${API_BASE}/projects/${projectId}/tags?${searchParams}`;
  return apiClient.get<TagListResponse>(url);
}

/**
 * Fetch a single tag by ID.
 *
 * `locale` is forwarded so the backend can resolve the localised
 * `vernacular_name` field on the returned tag.
 */
export async function fetchTag(
  projectId: string,
  tagId: string,
  params: { locale?: string } = {},
): Promise<TagDetail> {
  const searchParams = new URLSearchParams();
  if (params.locale) searchParams.set('locale', params.locale);
  const qs = searchParams.toString() ? `?${searchParams.toString()}` : '';
  return apiClient.get<TagDetail>(`${API_BASE}/projects/${projectId}/tags/${tagId}${qs}`);
}

/**
 * Create a new tag.
 */
export async function createTag(projectId: string, data: TagCreate): Promise<Tag> {
  return apiClient.post<Tag>(`${API_BASE}/projects/${projectId}/tags`, data);
}

/**
 * Update an existing tag.
 */
export async function updateTag(
  projectId: string,
  tagId: string,
  data: TagUpdate
): Promise<Tag> {
  return apiClient.patch<Tag>(`${API_BASE}/projects/${projectId}/tags/${tagId}`, data);
}

/**
 * Delete a tag by ID.
 */
export async function deleteTag(projectId: string, tagId: string): Promise<void> {
  return apiClient.delete<void>(`${API_BASE}/projects/${projectId}/tags/${tagId}`);
}

/**
 * Fetch GBIF taxon suggestions for a search query.
 */
export async function fetchGBIFSuggestions(
  projectId: string,
  query: string,
  limit: number = 10
): Promise<GBIFSuggestion[]> {
  const searchParams = new URLSearchParams({ q: query, limit: limit.toString() });
  return apiClient.get<GBIFSuggestion[]>(
    `${API_BASE}/projects/${projectId}/tags/gbif-suggest?${searchParams}`
  );
}

/**
 * Fetch tag usage statistics for a project.
 *
 * Forward `locale` so each returned tag's `vernacular_name` matches the
 * caller's active UI language.
 */
export async function fetchTagStatistics(
  projectId: string,
  params: { locale?: string } = {},
): Promise<TagStatistic[]> {
  const searchParams = new URLSearchParams();
  if (params.locale) searchParams.set('locale', params.locale);
  const qs = searchParams.toString() ? `?${searchParams.toString()}` : '';
  return apiClient.get<TagStatistic[]>(
    `${API_BASE}/projects/${projectId}/tags/statistics${qs}`,
  );
}
