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
  SimilarByAudioParams,
  SimilarByEmbeddingRequest,
  SimilaritySearchResponse,
  TargetSpecies,
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
 * Run a multi-species batch similarity search using uploaded reference sounds.
 *
 * Sends species metadata and audio files as multipart/form-data. Each
 * `SoundSource` with `origin === 'upload'` must have a `file` attached;
 * URL-based sources (Phase 2) are forwarded as metadata only.
 *
 * @param projectId - Project UUID
 * @param species - List of target species with reference sound sources
 * @param config - Search configuration (model, threshold, per-species limit)
 * @returns Batch search response with per-species match lists and timing info
 */
export async function searchBatch(
  projectId: string,
  species: TargetSpecies[],
  config: SearchConfig
): Promise<BatchSearchResponse> {
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
  return handleApiResponse<BatchSearchResponse>(response);
}
