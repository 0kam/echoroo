/**
 * Recordings API client for TanStack Query.
 */

import type {
  Recording,
  RecordingDetail,
  RecordingListResponse,
  RecordingUpdate,
  SpectrogramParams,
  PlaybackParams,
} from '$lib/types/data';
import { fetchWithErrorHandling, handleApiResponse } from './errors';

const API_BASE = '/api/v1';

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

/**
 * Fetch recordings for a project.
 */
export async function listRecordings(params: ListRecordingsParams): Promise<RecordingListResponse> {
  const searchParams = new URLSearchParams();
  if (params.datasetId) searchParams.append('dataset_id', params.datasetId);
  if (params.siteId) searchParams.append('site_id', params.siteId);
  if (params.page) searchParams.append('page', params.page.toString());
  if (params.pageSize) searchParams.append('page_size', params.pageSize.toString());
  if (params.search) searchParams.append('search', params.search);
  if (params.datetimeFrom) searchParams.append('datetime_from', params.datetimeFrom);
  if (params.datetimeTo) searchParams.append('datetime_to', params.datetimeTo);
  if (params.samplerate) searchParams.append('samplerate', params.samplerate.toString());
  if (params.sortBy) searchParams.append('sort_by', params.sortBy);
  if (params.sortOrder) searchParams.append('sort_order', params.sortOrder);

  const url = `${API_BASE}/projects/${params.projectId}/recordings?${searchParams}`;
  const response = await fetchWithErrorHandling(url, { credentials: 'include' });
  return handleApiResponse<RecordingListResponse>(response);
}

/**
 * Fetch a single recording by ID.
 */
export async function getRecording(projectId: string, recordingId: string): Promise<RecordingDetail> {
  const response = await fetchWithErrorHandling(`${API_BASE}/projects/${projectId}/recordings/${recordingId}`, {
    credentials: 'include',
  });
  return handleApiResponse<RecordingDetail>(response);
}

/**
 * Update a recording.
 */
export async function updateRecording(
  projectId: string,
  recordingId: string,
  data: RecordingUpdate
): Promise<RecordingDetail> {
  const response = await fetchWithErrorHandling(`${API_BASE}/projects/${projectId}/recordings/${recordingId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  return handleApiResponse<RecordingDetail>(response);
}

/**
 * Delete a recording.
 */
export async function deleteRecording(projectId: string, recordingId: string): Promise<void> {
  const response = await fetchWithErrorHandling(`${API_BASE}/projects/${projectId}/recordings/${recordingId}`, {
    method: 'DELETE',
    credentials: 'include',
  });

  if (!response.ok) {
    await handleApiResponse(response);
  }
}

/**
 * Get URL for streaming audio (returns raw bytes, not JSON).
 */
export function getStreamUrl(projectId: string, recordingId: string): string {
  return `${API_BASE}/projects/${projectId}/recordings/${recordingId}/stream`;
}

/**
 * Get URL for playback with optional speed adjustment.
 */
export function getPlaybackUrl(projectId: string, recordingId: string, params?: PlaybackParams): string {
  const url = new URL(
    `${API_BASE}/projects/${projectId}/recordings/${recordingId}/playback`,
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
    `${API_BASE}/projects/${projectId}/recordings/${recordingId}/spectrogram`,
    window.location.origin
  );
  if (params?.start !== undefined) url.searchParams.append('start', params.start.toString());
  if (params?.end !== undefined) url.searchParams.append('end', params.end.toString());
  if (params?.n_fft) url.searchParams.append('n_fft', params.n_fft.toString());
  if (params?.hop_length) url.searchParams.append('hop_length', params.hop_length.toString());
  if (params?.freq_min !== undefined) url.searchParams.append('freq_min', params.freq_min.toString());
  if (params?.freq_max !== undefined) url.searchParams.append('freq_max', params.freq_max.toString());
  if (params?.colormap) url.searchParams.append('colormap', params.colormap);
  if (params?.pcen !== undefined) url.searchParams.append('pcen', params.pcen.toString());
  if (params?.channel !== undefined) url.searchParams.append('channel', params.channel.toString());
  if (params?.width) url.searchParams.append('width', params.width.toString());
  if (params?.height) url.searchParams.append('height', params.height.toString());
  return url.toString();
}

/**
 * Get URL for downloading the original audio file.
 */
export function getDownloadUrl(projectId: string, recordingId: string): string {
  return `${API_BASE}/projects/${projectId}/recordings/${recordingId}/download`;
}
