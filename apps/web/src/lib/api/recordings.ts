/**
 * Recordings API client for TanStack Query.
 */

import type {
  RecordingDetail,
  RecordingUpdate,
  SpectrogramParams,
  PlaybackParams,
} from '$lib/types/data';
import { apiClient } from './client';

const WEB_API_BASE = '/web-api/v1';
const CSRF_COOKIE_NAME = 'echoroo_csrf';

export type RecordingMediaScope = 'audio' | 'playback' | 'spectrogram' | 'download';

export interface RecordingMediaTokenResponse {
  token: string;
  expires_in: number;
}

export interface ProjectRecordingItem {
  id: string;
  project_id: string;
  dataset_id: string;
  name: string;
  duration_seconds: number | null;
  samplerate: number;
  channels: number;
  datetime: string | null;
  datetime_parse_status: 'pending' | 'success' | 'failed';
  site_h3_index: string | null;
}

export interface ProjectRecordingListResponse {
  items: ProjectRecordingItem[];
  total: number;
  page: number;
  limit: number;
  pages: number;
}

export interface ListRecordingsParams {
  projectId: string;
  datasetId?: string;
  siteId?: string;
  page?: number;
  pageSize?: number;
  search?: string;
  datetimeFrom?: string;
  datetimeTo?: string;
  samplerate?: number;
  sortBy?: string;
  sortOrder?: string;
}

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

/**
 * Fetch recordings for a project.
 */
export async function listRecordings(
  params: ListRecordingsParams
): Promise<ProjectRecordingListResponse> {
  const searchParams = new URLSearchParams();
  if (params.datasetId) searchParams.append('dataset_id', params.datasetId);
  if (params.siteId) searchParams.append('site_id', params.siteId);
  if (params.page) searchParams.append('page', params.page.toString());
  if (params.pageSize) searchParams.append('limit', params.pageSize.toString());
  if (params.search) searchParams.append('search', params.search);
  if (params.datetimeFrom) searchParams.append('datetime_from', params.datetimeFrom);
  if (params.datetimeTo) searchParams.append('datetime_to', params.datetimeTo);
  if (params.samplerate) searchParams.append('samplerate', params.samplerate.toString());
  if (params.sortBy) searchParams.append('sort_by', params.sortBy);
  if (params.sortOrder) searchParams.append('sort_order', params.sortOrder);

  const query = searchParams.toString();
  const url = `${WEB_API_BASE}/projects/${params.projectId}/recordings${query ? `?${query}` : ''}`;
  const response = await apiClient.get<Omit<ProjectRecordingListResponse, 'pages'>>(url);
  const pageSize = response.limit;
  return {
    ...response,
    pages: pageSize > 0 ? Math.max(1, Math.ceil(response.total / pageSize)) : 1,
  };
}

/**
 * Fetch a single recording by ID.
 */
export async function getRecording(
  projectId: string,
  recordingId: string
): Promise<RecordingDetail> {
  return apiClient.get<RecordingDetail>(
    `${WEB_API_BASE}/projects/${projectId}/recordings/${recordingId}`
  );
}

/**
 * Update a recording.
 *
 * spec/009 PR 2: routes through the BFF surface (`/web-api/v1`) so the
 * mutation passes through CSRF + session-cookie auth.
 */
export async function updateRecording(
  projectId: string,
  recordingId: string,
  data: RecordingUpdate
): Promise<RecordingDetail> {
  const headers: Record<string, string> = {};
  const csrfToken = getCsrfToken();
  if (csrfToken) headers['X-CSRF-Token'] = csrfToken;
  return apiClient.patch<RecordingDetail>(
    `${WEB_API_BASE}/projects/${projectId}/recordings/${recordingId}`,
    data,
    { headers }
  );
}

/**
 * Delete a recording.
 *
 * spec/009 PR 2: routes through the BFF surface (`/web-api/v1`).
 */
export async function deleteRecording(projectId: string, recordingId: string): Promise<void> {
  const headers: Record<string, string> = {};
  const csrfToken = getCsrfToken();
  if (csrfToken) headers['X-CSRF-Token'] = csrfToken;
  return apiClient.delete<void>(
    `${WEB_API_BASE}/projects/${projectId}/recordings/${recordingId}`,
    { headers }
  );
}

/**
 * Issue a scoped token for native browser media/image requests.
 */
export async function getRecordingMediaToken(
  projectId: string,
  recordingId: string,
  scope: RecordingMediaScope
): Promise<RecordingMediaTokenResponse> {
  const headers: Record<string, string> = {};
  const csrfToken = getCsrfToken();
  if (csrfToken) headers['X-CSRF-Token'] = csrfToken;
  return apiClient.post<RecordingMediaTokenResponse>(
    `${WEB_API_BASE}/projects/${projectId}/recordings/${recordingId}/media-token`,
    { scope },
    { headers }
  );
}

/**
 * Append a scoped media token and return a same-origin path for browser elements.
 */
export function appendMediaTokenToUrl(url: string, token: string): string {
  const parsed = new URL(url, window.location.origin);
  parsed.searchParams.set('media_token', token);
  return parsed.pathname + parsed.search;
}

/**
 * Build a same-origin media URL authenticated with a scoped media token.
 */
export async function getAuthenticatedRecordingMediaUrl(
  projectId: string,
  recordingId: string,
  scope: RecordingMediaScope,
  url: string
): Promise<string> {
  const { token } = await getRecordingMediaToken(projectId, recordingId, scope);
  return appendMediaTokenToUrl(url, token);
}

/**
 * Get URL for playback with optional speed adjustment.
 */
export function getPlaybackUrl(
  projectId: string,
  recordingId: string,
  params?: PlaybackParams
): string {
  const url = new URL(
    `${WEB_API_BASE}/projects/${projectId}/recordings/${recordingId}/playback`,
    window.location.origin
  );
  if (params?.speed) url.searchParams.append('speed', params.speed.toString());
  if (params?.start !== undefined) url.searchParams.append('start', params.start.toString());
  if (params?.end !== undefined) url.searchParams.append('end', params.end.toString());
  return url.toString();
}

/**
 * Get URL for spectrogram image.
 */
export function getSpectrogramUrl(
  projectId: string,
  recordingId: string,
  params?: SpectrogramParams
): string {
  const url = new URL(
    `${WEB_API_BASE}/projects/${projectId}/recordings/${recordingId}/spectrogram`,
    window.location.origin
  );
  if (params?.start !== undefined) url.searchParams.append('start', params.start.toString());
  if (params?.end !== undefined) url.searchParams.append('end', params.end.toString());
  if (params?.n_fft) url.searchParams.append('n_fft', params.n_fft.toString());
  if (params?.hop_length) url.searchParams.append('hop_length', params.hop_length.toString());
  if (params?.freq_min !== undefined)
    url.searchParams.append('freq_min', params.freq_min.toString());
  if (params?.freq_max !== undefined)
    url.searchParams.append('freq_max', params.freq_max.toString());
  if (params?.colormap) url.searchParams.append('colormap', params.colormap);
  if (params?.pcen !== undefined) url.searchParams.append('pcen', params.pcen.toString());
  if (params?.channel !== undefined) url.searchParams.append('channel', params.channel.toString());
  if (params?.width) url.searchParams.append('width', params.width.toString());
  if (params?.height) url.searchParams.append('height', params.height.toString());
  return url.toString();
}

/**
 * Build an authenticated same-origin BFF URL for downloading the original file.
 *
 * W2-4 PR-A moved the download route to the ``/web-api/v1`` BFF media-token
 * surface. Native anchor downloads cannot send an Authorization header, so this
 * issues a short-lived download-scoped media token and appends it to the URL.
 */
export async function getAuthenticatedRecordingDownloadUrl(
  projectId: string,
  recordingId: string
): Promise<string> {
  const url = `${WEB_API_BASE}/projects/${projectId}/recordings/${recordingId}/download`;
  return getAuthenticatedRecordingMediaUrl(projectId, recordingId, 'download', url);
}
