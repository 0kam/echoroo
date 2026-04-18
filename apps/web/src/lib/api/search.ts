/**
 * Similarity search API client.
 *
 * Provides functions for searching audio embeddings by similarity using
 * either an existing embedding ID or an uploaded audio file.
 */

import type {
  EmbeddingStats,
  SearchConfig,
  SearchJobStatusResponse,
  SearchJobSubmitResponse,
  SearchSession,
  SearchSessionListResponse,
  SessionDistributionResponse,
  SessionSampleResponse,
  SessionTimeDistributionResponse,
  TargetSpecies,
  XenoCantoSearchResponse,
} from '$lib/types/search';
import { apiClient } from './client';
import { ApiError } from './client';

const API_BASE = '/api/v1';

/**
 * Fetch embedding statistics for a project.
 *
 * Returns counts broken down by model and dataset, useful for checking
 * whether embeddings have been generated before attempting a search.
 *
 * @param projectId - Project UUID
 * @param datasetId - Optional dataset filter
 * @returns Embedding statistics with counts by model and dataset
 */
export async function fetchEmbeddingStats(
  projectId: string,
  datasetId?: string
): Promise<EmbeddingStats> {
  const params = new URLSearchParams();
  if (datasetId) {
    params.set('dataset_id', datasetId);
  }
  const qs = params.toString() ? `?${params.toString()}` : '';
  return apiClient.get<EmbeddingStats>(
    `${API_BASE}/projects/${projectId}/search/embedding-stats${qs}`
  );
}

/**
 * Search Xeno-canto for recordings matching a query and optional filters.
 *
 * @param projectId - Project UUID (used for auth context)
 * @param params - Search parameters including query string and optional filters
 * @returns Paginated list of matching Xeno-canto recordings
 */
export async function searchXenoCanto(
  projectId: string,
  params: {
    query: string;
    country?: string;
    area?: string;
    quality_min?: string;
    recording_type?: string;
    page?: number;
    per_page?: number;
  }
): Promise<XenoCantoSearchResponse> {
  const qs = new URLSearchParams();
  qs.set('query', params.query);
  if (params.country) qs.set('country', params.country);
  if (params.area) qs.set('area', params.area);
  if (params.quality_min) qs.set('quality_min', params.quality_min);
  if (params.recording_type) qs.set('recording_type', params.recording_type);
  if (params.page !== undefined) qs.set('page', String(params.page));
  if (params.per_page !== undefined) qs.set('per_page', String(params.per_page));

  return apiClient.get<XenoCantoSearchResponse>(
    `${API_BASE}/projects/${projectId}/xeno-canto/search?${qs.toString()}`
  );
}

/**
 * Fetch audio for a Xeno-canto recording via the backend proxy.
 *
 * Returns the raw audio as an ArrayBuffer so it can be decoded by the Web Audio API.
 *
 * @param projectId - Project UUID (used for auth context)
 * @param xcId - Xeno-canto recording ID (numeric string, e.g. "1065457")
 * @returns ArrayBuffer containing the raw audio bytes
 */
export async function fetchXenoCantoAudio(
  projectId: string,
  xcId: string
): Promise<ArrayBuffer> {
  const response = await apiClient.requestRaw(
    `${API_BASE}/projects/${projectId}/xeno-canto/audio/${xcId}`
  );
  if (!response.ok) {
    throw new Error(`Failed to fetch Xeno-canto audio: ${response.status} ${response.statusText}`);
  }
  return response.arrayBuffer();
}

/**
 * Build the streaming URL for a persisted reference audio file.
 *
 * The backend streams the audio from S3, supporting HTTP Range headers for seeking.
 *
 * @param projectId - Project UUID
 * @param sessionId - Search session UUID that owns the audio
 * @param sourceIndex - Index of the audio file within the session's reference_audio_keys list
 * @returns Absolute URL path for the streaming endpoint
 */
export function getReferenceAudioUrl(
  projectId: string,
  sessionId: string,
  sourceIndex: number
): string {
  return `${API_BASE}/projects/${projectId}/search/sessions/${sessionId}/reference-audio/${sourceIndex}`;
}

/**
 * Submit a multi-species batch similarity search job using uploaded reference sounds.
 *
 * Sends species metadata and audio files as multipart/form-data. Each
 * `SoundSource` with `origin === 'upload'` must have a `file` attached;
 * URL-based sources are forwarded as metadata only; S3-backed sources from a
 * prior session are referenced via `sourceSessionId`.
 *
 * The API now returns 202 Accepted with a job_id immediately. Use
 * `getSearchJobStatus()` to poll for results.
 *
 * @param projectId - Project UUID
 * @param species - List of target species with reference sound sources
 * @param config - Search configuration (model, threshold, per-species limit)
 * @param sourceSessionId - Optional session UUID whose persisted audio should be reused
 * @returns Job submission response containing job_id for polling
 */
export async function searchBatch(
  projectId: string,
  species: TargetSpecies[],
  config: SearchConfig,
  sourceSessionId?: string
): Promise<SearchJobSubmitResponse> {
  const formData = new FormData();

  // Assign file_keys sequentially across all species / sources
  let fileIndex = 0;

  const speciesData = species.map((sp) => ({
    tag_id: sp.tag_id,
    scientific_name: sp.scientific_name,
    sources: sp.sources.map((src) => {
      if (src.origin === 'upload' && src.file) {
        const fileKey = `source_${fileIndex}`;
        formData.append(fileKey, src.file);
        fileIndex++;
        return {
          type: 'upload' as const,
          file_key: fileKey,
          start_time: src.start_time ?? null,
          end_time: src.end_time ?? null,
        };
      }
      if (src.origin === 's3') {
        // S3-backed source from a prior session — referenced by its index
        return {
          type: 's3' as const,
          source_index: src.sourceIndex ?? null,
          start_time: src.start_time ?? null,
          end_time: src.end_time ?? null,
        };
      }
      return {
        type: src.origin as 'url',
        source_url: src.source_url ?? null,
        start_time: src.start_time ?? null,
        end_time: src.end_time ?? null,
      };
    }),
  }));

  const metadataObj = {
    species: speciesData,
    model_name: config.model_name,
    dataset_id: config.dataset_id || null,
    source_session_id: sourceSessionId || null,
  };

  formData.append('metadata', JSON.stringify(metadataObj));

  // Use requestRaw to avoid automatic Content-Type injection (browser sets multipart boundary)
  const response = await apiClient.requestRaw(
    `${API_BASE}/projects/${projectId}/search/batch`,
    {
      method: 'POST',
      // Do not set Content-Type — browser sets it with the correct multipart boundary
      body: formData,
    }
  );

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'An error occurred' }));
    throw new ApiError(
      errorData.detail || 'Request failed',
      response.status,
      errorData.detail
    );
  }

  return response.json() as Promise<SearchJobSubmitResponse>;
}

/**
 * Poll the status of a previously submitted batch search job.
 *
 * Call this repeatedly (e.g., every 2 seconds) after `searchBatch()` until
 * the status is "completed" or "failed".
 *
 * @param projectId - Project UUID
 * @param jobId - Job UUID returned by `searchBatch()`
 * @param locale - Optional locale for species common name localization (e.g. "ja")
 * @returns Current job status, optional progress info, and results when done
 */
export async function getSearchJobStatus(
  projectId: string,
  jobId: string,
  locale?: string
): Promise<SearchJobStatusResponse> {
  const params = locale ? `?locale=${locale}` : '';
  return apiClient.get<SearchJobStatusResponse>(
    `${API_BASE}/projects/${projectId}/search/jobs/${jobId}${params}`
  );
}

/**
 * Create an annotation from a similarity search result.
 *
 * Posts a confirmed annotation derived from a search result card.
 *
 * @param projectId - Project UUID
 * @param data - Annotation data including recording_id, tag_id, time range, confidence, and optional session
 */
export async function createAnnotationFromSearch(
  projectId: string,
  data: {
    recording_id: string;
    tag_id: string;
    start_time: number;
    end_time: number;
    confidence: number;
    review_status?: string;
    source?: string;
    search_session_id?: string;
  }
): Promise<unknown> {
  return apiClient.post<unknown>(`${API_BASE}/projects/${projectId}/annotations`, {
    ...data,
    review_status: data.review_status ?? 'confirmed',
    source: data.source ?? 'similarity_search',
  });
}

/**
 * List persisted search sessions for a project.
 *
 * @param projectId - Project UUID
 * @param limit - Maximum number of sessions to return (default 50)
 * @param offset - Number of sessions to skip for pagination (default 0)
 * @param locale - Optional locale for species common name localization (e.g. "ja")
 * @returns Paginated list of search session summaries
 */
export async function listSearchSessions(
  projectId: string,
  limit = 50,
  offset = 0,
  locale?: string
): Promise<SearchSessionListResponse> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (locale) {
    params.set('locale', locale);
  }
  return apiClient.get<SearchSessionListResponse>(
    `${API_BASE}/projects/${projectId}/search/sessions?${params}`
  );
}

/**
 * Fetch the full details of a single search session, including merged review statuses.
 *
 * @param projectId - Project UUID
 * @param sessionId - Search session UUID
 * @param locale - Optional locale for species common name localization (e.g. "ja")
 * @returns Full search session including results and review counts
 */
export async function getSearchSession(
  projectId: string,
  sessionId: string,
  locale?: string
): Promise<SearchSession> {
  const params = locale ? `?locale=${locale}` : '';
  return apiClient.get<SearchSession>(
    `${API_BASE}/projects/${projectId}/search/sessions/${sessionId}${params}`
  );
}

/**
 * Delete a search session and its associated data.
 *
 * @param projectId - Project UUID
 * @param sessionId - Search session UUID to delete
 */
export async function deleteSearchSession(
  projectId: string,
  sessionId: string
): Promise<void> {
  return apiClient.delete<void>(
    `${API_BASE}/projects/${projectId}/search/sessions/${sessionId}`
  );
}

/**
 * Update a search session's mutable fields (currently only the name).
 *
 * @param projectId - Project UUID
 * @param sessionId - Search session UUID to update
 * @param name - New display name for the session
 * @returns Updated search session
 */
export async function updateSearchSession(
  projectId: string,
  sessionId: string,
  name: string
): Promise<SearchSession> {
  return apiClient.patch<SearchSession>(
    `${API_BASE}/projects/${projectId}/search/sessions/${sessionId}`,
    { name }
  );
}

/**
 * Re-run an existing search session with updated reference sources.
 *
 * Updates the session's species_config, clears old results/annotations,
 * and dispatches a new search task on the same session record.
 *
 * @param projectId - Project UUID
 * @param sessionId - Search session UUID to re-run
 * @param species - Updated list of target species with reference sound sources
 * @param config - Search configuration (model, threshold, per-species limit)
 * @param sourceSessionId - Optional session UUID whose persisted audio should be reused
 * @returns Job submission response containing job_id for polling
 */
export async function rerunSearchSession(
  projectId: string,
  sessionId: string,
  species: TargetSpecies[],
  config: SearchConfig,
  sourceSessionId?: string
): Promise<SearchJobSubmitResponse> {
  const formData = new FormData();

  // Assign file_keys sequentially across all species / sources
  let fileIndex = 0;

  const speciesData = species.map((sp) => ({
    tag_id: sp.tag_id,
    scientific_name: sp.scientific_name,
    sources: sp.sources.map((src) => {
      if (src.origin === 'upload' && src.file) {
        const fileKey = `source_${fileIndex}`;
        formData.append(fileKey, src.file);
        fileIndex++;
        return {
          type: 'upload' as const,
          file_key: fileKey,
          start_time: src.start_time ?? null,
          end_time: src.end_time ?? null,
        };
      }
      if (src.origin === 's3') {
        return {
          type: 's3' as const,
          source_index: src.sourceIndex ?? null,
          start_time: src.start_time ?? null,
          end_time: src.end_time ?? null,
        };
      }
      return {
        type: src.origin as 'url',
        source_url: src.source_url ?? null,
        start_time: src.start_time ?? null,
        end_time: src.end_time ?? null,
      };
    }),
  }));

  const metadataObj = {
    species: speciesData,
    model_name: config.model_name,
    dataset_id: config.dataset_id || null,
    source_session_id: sourceSessionId || null,
  };

  formData.append('metadata', JSON.stringify(metadataObj));

  // Use requestRaw to avoid automatic Content-Type injection (browser sets multipart boundary)
  const response = await apiClient.requestRaw(
    `${API_BASE}/projects/${projectId}/search/sessions/${sessionId}/rerun`,
    {
      method: 'PUT',
      body: formData,
    }
  );

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'An error occurred' }));
    throw new ApiError(
      errorData.detail || 'Request failed',
      response.status,
      errorData.detail
    );
  }

  return response.json() as Promise<SearchJobSubmitResponse>;
}

/**
 * Export a search session's results as a CSV file and trigger a browser download.
 *
 * @param projectId - Project UUID
 * @param sessionId - Search session UUID to export
 */
export async function exportSearchSessionCSV(
  projectId: string,
  sessionId: string
): Promise<void> {
  const response = await apiClient.requestRaw(
    `${API_BASE}/projects/${projectId}/search/sessions/${sessionId}/export/csv`
  );

  if (!response.ok) {
    throw new Error(`Failed to export session: ${response.status}`);
  }

  // Trigger browser download
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download =
    response.headers
      .get('Content-Disposition')
      ?.split('filename=')[1]
      ?.replace(/"/g, '') ?? `search_session_${sessionId}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/**
 * Fetch the similarity score distribution for a search session.
 *
 * Returns pre-computed histogram bins showing how many results fall into each
 * similarity range. Used to render the SimilarityHistogram without transferring
 * all individual results to the client.
 *
 * @param projectId - Project UUID
 * @param sessionId - Search session UUID
 * @returns Distribution bins with counts per similarity range
 */
export async function getSessionDistribution(
  projectId: string,
  sessionId: string,
  speciesKey?: string
): Promise<SessionDistributionResponse> {
  const params = new URLSearchParams();
  if (speciesKey) {
    params.set('species_key', speciesKey);
  }
  const qs = params.toString() ? `?${params.toString()}` : '';
  return apiClient.get<SessionDistributionResponse>(
    `${API_BASE}/projects/${projectId}/search/sessions/${sessionId}/distribution${qs}`
  );
}

/**
 * Fetch time-of-day similarity distribution for a search session.
 *
 * Returns average similarity per (date, hour) cell computed over ALL
 * project embeddings, not just the session's top results. Used to render
 * the SearchTimeHeatmap.
 *
 * @param projectId - Project UUID
 * @param sessionId - Search session UUID
 * @returns Time distribution cells with date, hour, avg_similarity, count
 */
export async function getSessionTimeDistribution(
  projectId: string,
  sessionId: string,
  speciesKey?: string
): Promise<SessionTimeDistributionResponse> {
  const params = new URLSearchParams();
  if (speciesKey) {
    params.set('species_key', speciesKey);
  }
  const qs = params.toString() ? `?${params.toString()}` : '';
  return apiClient.get<SessionTimeDistributionResponse>(
    `${API_BASE}/projects/${projectId}/search/sessions/${sessionId}/time-distribution${qs}`
  );
}

/**
 * Fetch a random sample of results within a similarity range from a search session.
 *
 * Used by ResultsPanel to show representative spectrograms for a given
 * similarity band without loading all results.
 *
 * @param projectId - Project UUID
 * @param sessionId - Search session UUID
 * @param minSimilarity - Lower bound of the similarity range (inclusive, 0.0–1.0)
 * @param maxSimilarity - Upper bound of the similarity range (inclusive, 0.0–1.0)
 * @param limit - Maximum number of results to return (default 20)
 * @returns Randomly sampled results within the requested range
 */
export async function getSessionSample(
  projectId: string,
  sessionId: string,
  minSimilarity: number,
  maxSimilarity: number,
  limit = 20,
  speciesKey?: string
): Promise<SessionSampleResponse> {
  const params = new URLSearchParams({
    min_similarity: String(minSimilarity),
    max_similarity: String(maxSimilarity),
    limit: String(limit),
  });
  if (speciesKey) {
    params.set('species_key', speciesKey);
  }
  return apiClient.get<SessionSampleResponse>(
    `${API_BASE}/projects/${projectId}/search/sessions/${sessionId}/sample?${params}`
  );
}

/**
 * Export a search summary CSV for a session.
 *
 * Produces one row per (recording × species) combination, covering ALL
 * recordings in the project's datasets. Recordings without matching
 * embeddings are included with empty similarity columns.
 *
 * @param projectId - Project UUID
 * @param sessionId - Search session UUID to export
 */
export async function exportSearchSessionRecordingsCSV(
  projectId: string,
  sessionId: string,
  locale?: string
): Promise<void> {
  const params = locale ? `?locale=${locale}` : '';
  const response = await apiClient.requestRaw(
    `${API_BASE}/projects/${projectId}/search/sessions/${sessionId}/export-recordings${params}`
  );

  if (!response.ok) {
    throw new Error(`Failed to export recordings: ${response.status}`);
  }

  // Trigger browser download
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download =
    response.headers
      .get('Content-Disposition')
      ?.split('filename=')[1]
      ?.replace(/"/g, '') ?? `recordings_${sessionId}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
