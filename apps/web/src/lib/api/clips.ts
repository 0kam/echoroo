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
// migrated to ``/web-api/v1`` (cookie + CSRF). Audio / spectrogram /
// download URL builders below still target ``/api/v1`` — they ride the
// media-token scoped-token pattern and are tracked separately.
const API_BASE = '/api/v1';
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
 * Get URL for clip audio playback with optional speed adjustment.
 */
export function getClipAudioUrl(
  projectId: string,
  recordingId: string,
  clipId: string,
  speed?: number
): string {
  const url = new URL(
    `${API_BASE}/projects/${projectId}/recordings/${recordingId}/clips/${clipId}/audio`,
    window.location.origin
  );
  if (speed) url.searchParams.append('speed', speed.toString());
  return url.toString();
}

/**
 * Get URL for clip spectrogram image.
 */
export function getClipSpectrogramUrl(
  projectId: string,
  recordingId: string,
  clipId: string,
  params?: {
    n_fft?: number;
    colormap?: string;
    width?: number;
    height?: number;
  }
): string {
  const url = new URL(
    `${API_BASE}/projects/${projectId}/recordings/${recordingId}/clips/${clipId}/spectrogram`,
    window.location.origin
  );
  if (params?.n_fft) url.searchParams.append('n_fft', params.n_fft.toString());
  if (params?.colormap) url.searchParams.append('colormap', params.colormap);
  if (params?.width) url.searchParams.append('width', params.width.toString());
  if (params?.height) url.searchParams.append('height', params.height.toString());
  return url.toString();
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
 * Get URL for downloading clip audio file.
 */
export function getClipDownloadUrl(projectId: string, recordingId: string, clipId: string): string {
  return `${API_BASE}/projects/${projectId}/recordings/${recordingId}/clips/${clipId}/download`;
}
