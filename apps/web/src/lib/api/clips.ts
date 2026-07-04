/**
 * Clips API client for TanStack Query.
 */

import type {
  ClipCreate,
  Clip,
  ClipDetail,
  ClipGenerateRequest,
  ClipGenerateResponse,
  ClipListResponse,
  PlaybackParams,
  SpectrogramParams,
  ClipUpdate,
} from '$lib/types/data';
import { apiClient } from './client';
import { getAuthenticatedRecordingMediaUrl, getPlaybackUrl, getSpectrogramUrl } from './recordings';

// spec/009 PR 3a: write surface (create / update / delete / generate)
// migrated to ``/web-api/v1`` (cookie + CSRF). W2-4 PR-A finished the media
// surface: clip audio / spectrogram ride the recording-level playback /
// spectrogram BFF, and clip download uses the ``/web-api/v1`` clip-scoped
// media-token pattern — no builder targets ``/api/v1`` anymore.
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

export interface ListClipsParams {
  projectId: string;
  recordingId: string;
  page?: number;
  pageSize?: number;
  sortBy?: string;
  sortOrder?: string;
}

/**
 * Fetch clips for a recording.
 */
export async function listClips(params: ListClipsParams): Promise<ClipListResponse> {
  const searchParams = new URLSearchParams();
  if (params.page) searchParams.append('page', params.page.toString());
  if (params.pageSize) searchParams.append('page_size', params.pageSize.toString());
  if (params.sortBy) searchParams.append('sort_by', params.sortBy);
  if (params.sortOrder) searchParams.append('sort_order', params.sortOrder);

  const query = searchParams.toString();
  const url = `${WEB_API_BASE}/projects/${params.projectId}/recordings/${params.recordingId}/clips${query ? `?${query}` : ''}`;
  return apiClient.get<ClipListResponse>(url);
}

/**
 * Fetch a single clip by ID.
 */
export async function getClip(
  projectId: string,
  recordingId: string,
  clipId: string
): Promise<ClipDetail> {
  return apiClient.get<ClipDetail>(
    `${WEB_API_BASE}/projects/${projectId}/recordings/${recordingId}/clips/${clipId}`
  );
}

/**
 * Create a new clip.
 */
export async function createClip(
  projectId: string,
  recordingId: string,
  data: ClipCreate
): Promise<ClipDetail> {
  return apiClient.post<ClipDetail>(
    `${WEB_API_BASE}/projects/${projectId}/recordings/${recordingId}/clips`,
    data,
    { headers: csrfHeaders() }
  );
}

/**
 * Update a clip.
 */
export async function updateClip(
  projectId: string,
  recordingId: string,
  clipId: string,
  data: ClipUpdate
): Promise<ClipDetail> {
  return apiClient.patch<ClipDetail>(
    `${WEB_API_BASE}/projects/${projectId}/recordings/${recordingId}/clips/${clipId}`,
    data,
    { headers: csrfHeaders() }
  );
}

/**
 * Delete a clip.
 */
export async function deleteClip(
  projectId: string,
  recordingId: string,
  clipId: string
): Promise<void> {
  return apiClient.delete<void>(
    `${WEB_API_BASE}/projects/${projectId}/recordings/${recordingId}/clips/${clipId}`,
    { headers: csrfHeaders() }
  );
}

/**
 * Auto-generate clips from a recording.
 */
export async function generateClips(
  projectId: string,
  recordingId: string,
  request: ClipGenerateRequest
): Promise<ClipGenerateResponse> {
  return apiClient.post<ClipGenerateResponse>(
    `${WEB_API_BASE}/projects/${projectId}/recordings/${recordingId}/clips/generate`,
    request,
    { headers: csrfHeaders() }
  );
}

/**
 * Get an authenticated same-origin BFF URL for clip audio playback.
 *
 * Native <audio> cannot send Authorization headers, so this reuses the
 * recording playback BFF with clip start/end bounds plus a scoped media token.
 */
export async function getAuthenticatedClipPlaybackUrl(
  projectId: string,
  recordingId: string,
  clip: Pick<Clip, 'start_time' | 'end_time'>,
  params?: Omit<PlaybackParams, 'start' | 'end'>
): Promise<string> {
  const url = getPlaybackUrl(projectId, recordingId, {
    ...params,
    start: clip.start_time,
    end: clip.end_time,
  });
  return getAuthenticatedRecordingMediaUrl(projectId, recordingId, 'playback', url);
}

/**
 * Get an authenticated same-origin BFF URL for a clip spectrogram image.
 *
 * Native <img> cannot send Authorization headers, so this reuses the recording
 * spectrogram BFF with clip start/end bounds plus a scoped media token.
 */
export async function getAuthenticatedClipSpectrogramUrl(
  projectId: string,
  recordingId: string,
  clip: Pick<Clip, 'start_time' | 'end_time'>,
  params?: Omit<SpectrogramParams, 'start' | 'end'>
): Promise<string> {
  const url = getSpectrogramUrl(projectId, recordingId, {
    ...params,
    start: clip.start_time,
    end: clip.end_time,
  });
  return getAuthenticatedRecordingMediaUrl(projectId, recordingId, 'spectrogram', url);
}

/**
 * Build an authenticated same-origin BFF URL for downloading a clip WAV.
 *
 * W2-4 PR-A moved the clip download route to the ``/web-api/v1`` BFF
 * media-token surface. Native anchor downloads cannot send an Authorization
 * header, so this issues a short-lived clip-scoped download media token and
 * appends it to the download URL.
 */
export async function getAuthenticatedClipDownloadUrl(
  projectId: string,
  recordingId: string,
  clipId: string
): Promise<string> {
  const { token } = await apiClient.post<{ token: string; expires_in: number }>(
    `${WEB_API_BASE}/projects/${projectId}/recordings/${recordingId}/clips/${clipId}/media-token`,
    { scope: 'download' },
    { headers: csrfHeaders() }
  );
  const url = new URL(
    `${WEB_API_BASE}/projects/${projectId}/recordings/${recordingId}/clips/${clipId}/download`,
    window.location.origin
  );
  url.searchParams.set('media_token', token);
  return url.pathname + url.search;
}
