/**
 * TypeScript type definitions for the Similarity Search feature.
 *
 * These types mirror the Pydantic schemas from the backend API,
 * covering similarity search requests, results, and embedding statistics.
 */

// ============================================
// Similarity Search Types
// ============================================

/**
 * A single similarity search result.
 */
export interface SimilarityResult {
  /** Unique identifier for the embedding */
  embedding_id: string;
  /** Recording that contains this embedding */
  recording_id: string;
  /** Original filename of the recording */
  recording_filename: string;
  /** Dataset that contains the recording */
  dataset_id: string;
  /** Start time of the audio segment within the recording, in seconds */
  start_time: number;
  /** End time of the audio segment within the recording, in seconds */
  end_time: number;
  /** Cosine similarity score (0.0–1.0) */
  similarity: number;
}

/**
 * Response from similarity search endpoints.
 */
export interface SimilaritySearchResponse {
  /** Ordered list of similar audio segments (descending similarity) */
  results: SimilarityResult[];
  /** Name of the model used for the search */
  query_model: string;
  /** Total number of results returned */
  total_results: number;
}

/**
 * Statistics about stored embeddings for a project.
 */
export interface EmbeddingStats {
  /** Total number of embeddings across all models */
  total_count: number;
  /** Count per model name, e.g. { birdnet: 1000, perch: 500 } */
  by_model: Record<string, number>;
  /** Count per dataset UUID string */
  by_dataset: Record<string, number>;
}

// ============================================
// Request Types
// ============================================

/**
 * Parameters for searching by an existing embedding ID.
 */
export interface SimilarByEmbeddingRequest {
  /** Embedding ID to use as the query vector */
  embedding_id: string;
  /** Model name to search within */
  model_name?: string;
  /** Maximum number of results to return */
  limit?: number;
  /** Minimum cosine similarity threshold (0.0–1.0) */
  min_similarity?: number;
  /** Optional dataset filter */
  dataset_id?: string;
}

/**
 * Parameters for the audio-upload-based similarity search.
 */
export interface SimilarByAudioParams {
  /** Model name to generate embedding and search */
  model_name?: string;
  /** Maximum number of results to return */
  limit?: number;
  /** Minimum cosine similarity threshold (0.0–1.0) */
  min_similarity?: number;
  /** Optional dataset filter */
  dataset_id?: string;
}
