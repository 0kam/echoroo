/**
 * Tags API client for TanStack Query.
 *
 * spec/009 PR 3a: all tag CRUD + GBIF + statistics calls go through
 * ``/web-api/v1`` (cookie + CSRF session boundary). Mutations attach
 * ``X-CSRF-Token`` via the inline helper below.
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

const WEB_API_BASE = '/web-api/v1';
const CSRF_COOKIE_NAME = 'echoroo_csrf';

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

  const url = `${WEB_API_BASE}/projects/${projectId}/tags?${searchParams}`;
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
  return apiClient.get<TagDetail>(`${WEB_API_BASE}/projects/${projectId}/tags/${tagId}${qs}`);
}

/**
 * Create a new tag.
 */
export async function createTag(projectId: string, data: TagCreate): Promise<Tag> {
  return apiClient.post<Tag>(
    `${WEB_API_BASE}/projects/${projectId}/tags`,
    data,
    { headers: csrfHeaders() }
  );
}

/**
 * Update an existing tag.
 */
export async function updateTag(
  projectId: string,
  tagId: string,
  data: TagUpdate
): Promise<Tag> {
  return apiClient.patch<Tag>(
    `${WEB_API_BASE}/projects/${projectId}/tags/${tagId}`,
    data,
    { headers: csrfHeaders() }
  );
}

/**
 * Delete a tag by ID.
 */
export async function deleteTag(projectId: string, tagId: string): Promise<void> {
  return apiClient.delete<void>(
    `${WEB_API_BASE}/projects/${projectId}/tags/${tagId}`,
    { headers: csrfHeaders() }
  );
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
    `${WEB_API_BASE}/projects/${projectId}/tags/gbif-suggest?${searchParams}`
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
    `${WEB_API_BASE}/projects/${projectId}/tags/statistics${qs}`,
  );
}
