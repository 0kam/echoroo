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
import { fetchWithErrorHandling, handleApiResponse } from './errors';

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
  const response = await fetchWithErrorHandling(url, { credentials: 'include' });
  return handleApiResponse<TagListResponse>(response);
}

/**
 * Fetch a single tag by ID.
 */
export async function fetchTag(projectId: string, tagId: string): Promise<TagDetail> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/tags/${tagId}`,
    { credentials: 'include' }
  );
  return handleApiResponse<TagDetail>(response);
}

/**
 * Create a new tag.
 */
export async function createTag(projectId: string, data: TagCreate): Promise<Tag> {
  const response = await fetchWithErrorHandling(`${API_BASE}/projects/${projectId}/tags`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  return handleApiResponse<Tag>(response);
}

/**
 * Update an existing tag.
 */
export async function updateTag(
  projectId: string,
  tagId: string,
  data: TagUpdate
): Promise<Tag> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/tags/${tagId}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(data),
    }
  );
  return handleApiResponse<Tag>(response);
}

/**
 * Delete a tag by ID.
 */
export async function deleteTag(projectId: string, tagId: string): Promise<void> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/tags/${tagId}`,
    {
      method: 'DELETE',
      credentials: 'include',
    }
  );

  if (!response.ok) {
    await handleApiResponse(response);
  }
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
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/tags/gbif-suggest?${searchParams}`,
    { credentials: 'include' }
  );
  return handleApiResponse<GBIFSuggestion[]>(response);
}

/**
 * Fetch tag usage statistics for a project.
 */
export async function fetchTagStatistics(projectId: string): Promise<TagStatistic[]> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/tags/statistics`,
    { credentials: 'include' }
  );
  return handleApiResponse<TagStatistic[]>(response);
}
