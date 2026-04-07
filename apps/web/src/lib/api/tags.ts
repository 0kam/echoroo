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
 */
export async function fetchTags(
  projectId: string,
  params: TagListParams = {}
): Promise<TagListResponse> {
  const searchParams = new URLSearchParams();
  if (params.page) searchParams.set('page', params.page.toString());
  if (params.page_size) searchParams.set('page_size', params.page_size.toString());
  if (params.category) searchParams.set('category', params.category);
  if (params.search) searchParams.set('search', params.search);

  const url = `${API_BASE}/projects/${projectId}/tags?${searchParams}`;
  return apiClient.get<TagListResponse>(url);
}

/**
 * Fetch a single tag by ID.
 */
export async function fetchTag(projectId: string, tagId: string): Promise<TagDetail> {
  return apiClient.get<TagDetail>(`${API_BASE}/projects/${projectId}/tags/${tagId}`);
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
 */
export async function fetchTagStatistics(projectId: string): Promise<TagStatistic[]> {
  return apiClient.get<TagStatistic[]>(`${API_BASE}/projects/${projectId}/tags/statistics`);
}
