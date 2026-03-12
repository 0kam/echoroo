/**
 * Similarity search API client.
 *
 * Provides functions for searching audio embeddings by similarity using
 * either an existing embedding ID or an uploaded audio file.
 */

import type {
  BatchSearchResponse,
  EmbeddingStats,
  SearchConfig,
  SearchJobStatusResponse,
  SearchJobSubmitResponse,
  SearchSession,
  SearchSessionListResponse,
  SimilarByAudioParams,
  SimilarByEmbeddingRequest,
  SimilaritySearchResponse,
  TargetSpecies,
  XenoCantoSearchResponse,
} from '$lib/types/search';
import { fetchWithErrorHandling, handleApiResponse } from './errors';

const API_BASE = '/api/v1';

/**
 * Search for similar audio segments using an existing stored embedding.
 *
 * @param projectId - Project UUID
 * @param request - Search parameters including embedding_id and optional filters
 * @returns Similarity search response ordered by descending similarity
 */
export async function searchSimilarByEmbedding(
  projectId: string,
  request: SimilarByEmbeddingRequest
): Promise<SimilaritySearchResponse> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/search/similar`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(request),
    }
  );
  return handleApiResponse<SimilaritySearchResponse>(response);
}

/**
 * Search for similar audio segments by uploading an audio clip.
 *
 * Sends the file as multipart/form-data alongside search parameters.
 *
 * @param projectId - Project UUID
 * @param audioFile - Audio file to use as the query
 * @param params - Search parameters (model, limit, threshold, dataset filter)
 * @returns Similarity search response ordered by descending similarity
 */
export async function searchSimilarByAudio(
  projectId: string,
  audioFile: File,
  params: SimilarByAudioParams
): Promise<SimilaritySearchResponse> {
  const formData = new FormData();
  formData.append('audio_file', audioFile);

  if (params.model_name) {
    formData.append('model_name', params.model_name);
  }
  if (params.limit !== undefined) {
    formData.append('limit', String(params.limit));
  }
  if (params.min_similarity !== undefined) {
    formData.append('min_similarity', String(params.min_similarity));
  }
  if (params.dataset_id) {
    formData.append('dataset_id', params.dataset_id);
  }

  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/search/similar-by-audio`,
    {
      method: 'POST',
      credentials: 'include',
      // Do not set Content-Type header — browser sets it with the correct boundary
      body: formData,
    }
  );
  return handleApiResponse<SimilaritySearchResponse>(response);
}

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
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/search/embedding-stats${qs}`,
    { credentials: 'include' }
  );
  return handleApiResponse<EmbeddingStats>(response);
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

  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/xeno-canto/search?${qs.toString()}`,
    { credentials: 'include' }
  );
  return handleApiResponse<XenoCantoSearchResponse>(response);
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
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/xeno-canto/audio/${xcId}`,
    { credentials: 'include' }
  );
  if (!response.ok) {
    throw new Error(`Failed to fetch Xeno-canto audio: ${response.status} ${response.statusText}`);
  }
  return response.arrayBuffer();
}

/**
 * Submit a multi-species batch similarity search job using uploaded reference sounds.
 *
 * Sends species metadata and audio files as multipart/form-data. Each
 * `SoundSource` with `origin === 'upload'` must have a `file` attached;
 * URL-based sources (Phase 2) are forwarded as metadata only.
 *
 * The API now returns 202 Accepted with a job_id immediately. Use
 * `getSearchJobStatus()` to poll for results.
 *
 * @param projectId - Project UUID
 * @param species - List of target species with reference sound sources
 * @param config - Search configuration (model, threshold, per-species limit)
 * @returns Job submission response containing job_id for polling
 */
export async function searchBatch(
  projectId: string,
  species: TargetSpecies[],
  config: SearchConfig
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
      return {
        type: src.origin as 'upload' | 'url',
        source_url: src.source_url ?? null,
        start_time: src.start_time ?? null,
        end_time: src.end_time ?? null,
      };
    }),
  }));

  const metadataObj = {
    species: speciesData,
    model_name: config.model_name,
    min_similarity: config.min_similarity,
    limit_per_species: config.limit_per_species,
    dataset_id: config.dataset_id || null,
  };

  formData.append('metadata', JSON.stringify(metadataObj));

  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/search/batch`,
    {
      method: 'POST',
      credentials: 'include',
      // Do not set Content-Type — browser sets it with the correct multipart boundary
      body: formData,
    }
  );
  return handleApiResponse<SearchJobSubmitResponse>(response);
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
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/search/jobs/${jobId}${params}`,
    { credentials: 'include' }
  );
  return handleApiResponse<SearchJobStatusResponse>(response);
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
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/annotations`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        ...data,
        review_status: data.review_status ?? 'confirmed',
        source: data.source ?? 'similarity_search',
      }),
    }
  );
  return handleApiResponse<unknown>(response);
}

/**
 * Reject a similarity search result by creating a rejected annotation.
 *
 * @param projectId - Project UUID
 * @param data - Result data including recording_id, tag_id, time range, confidence, and optional session
 */
export async function rejectSearchResult(
  projectId: string,
  data: {
    recording_id: string;
    tag_id: string;
    start_time: number;
    end_time: number;
    confidence: number;
    search_session_id?: string;
  }
): Promise<unknown> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/annotations`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        ...data,
        source: 'similarity_search',
        review_status: 'rejected',
      }),
    }
  );
  return handleApiResponse<unknown>(response);
}

/**
 * List persisted search sessions for a project.
 *
 * @param projectId - Project UUID
 * @param limit - Maximum number of sessions to return (default 50)
 * @param offset - Number of sessions to skip for pagination (default 0)
 * @returns Paginated list of search session summaries
 */
export async function listSearchSessions(
  projectId: string,
  limit = 50,
  offset = 0
): Promise<SearchSessionListResponse> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/search/sessions?${params}`,
    { credentials: 'include' }
  );
  return handleApiResponse<SearchSessionListResponse>(response);
}

/**
 * Fetch the full details of a single search session, including merged review statuses.
 *
 * @param projectId - Project UUID
 * @param sessionId - Search session UUID
 * @returns Full search session including results and review counts
 */
export async function getSearchSession(
  projectId: string,
  sessionId: string
): Promise<SearchSession> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/search/sessions/${sessionId}`,
    { credentials: 'include' }
  );
  return handleApiResponse<SearchSession>(response);
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
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/search/sessions/${sessionId}`,
    {
      method: 'DELETE',
      credentials: 'include',
    }
  );
  await handleApiResponse<unknown>(response);
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
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/search/sessions/${sessionId}/export/csv`,
    { credentials: 'include' }
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
