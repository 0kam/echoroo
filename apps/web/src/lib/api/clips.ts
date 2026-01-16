/**
 * Clips API client for TanStack Query.
 */

import type {
  Clip,
  ClipCreate,
  ClipDetail,
  ClipGenerateRequest,
  ClipGenerateResponse,
  ClipListResponse,
  ClipUpdate,
} from '$lib/types/data';
import { fetchWithErrorHandling, handleApiResponse } from './errors';

const API_BASE = '/api/v1';

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

  const url = `${API_BASE}/projects/${params.projectId}/recordings/${params.recordingId}/clips?${searchParams}`;
  const response = await fetchWithErrorHandling(url, { credentials: 'include' });
  return handleApiResponse<ClipListResponse>(response);
}

/**
 * Fetch a single clip by ID.
 */
export async function getClip(
  projectId: string,
  recordingId: string,
  clipId: string
): Promise<ClipDetail> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/recordings/${recordingId}/clips/${clipId}`,
    { credentials: 'include' }
  );
  return handleApiResponse<ClipDetail>(response);
}

/**
 * Create a new clip.
 */
export async function createClip(
  projectId: string,
  recordingId: string,
  data: ClipCreate
): Promise<ClipDetail> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/recordings/${recordingId}/clips`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(data),
    }
  );
  return handleApiResponse<ClipDetail>(response);
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
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/recordings/${recordingId}/clips/${clipId}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(data),
    }
  );
  return handleApiResponse<ClipDetail>(response);
}

/**
 * Delete a clip.
 */
export async function deleteClip(
  projectId: string,
  recordingId: string,
  clipId: string
): Promise<void> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/recordings/${recordingId}/clips/${clipId}`,
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
 * Auto-generate clips from a recording.
 */
export async function generateClips(
  projectId: string,
  recordingId: string,
  request: ClipGenerateRequest
): Promise<ClipGenerateResponse> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/recordings/${recordingId}/clips/generate`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(request),
    }
  );
  return handleApiResponse<ClipGenerateResponse>(response);
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
 * Get URL for downloading clip audio file.
 */
export function getClipDownloadUrl(projectId: string, recordingId: string, clipId: string): string {
  return `${API_BASE}/projects/${projectId}/recordings/${recordingId}/clips/${clipId}/download`;
}
