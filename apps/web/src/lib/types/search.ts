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

// ============================================
// Enhanced Search Types (Phase 1)
// ============================================

/**
 * A reference sound source for species-based batch search.
 */
export interface SoundSource {
  /** Client-generated UUID for UI state management */
  id: string;
  /** Whether this source is an uploaded file or a remote URL */
  origin: 'upload' | 'url';
  /** Optional human-readable label for this source */
  label?: string;

  // Upload-specific
  /** The audio file to upload (only for origin === 'upload') */
  file?: File;

  // URL-specific (Phase 2)
  /** Remote URL pointing to the audio resource */
  source_url?: string;
  /** Xeno-canto recording ID if applicable */
  xc_id?: string;
  /** Xeno-canto quality rating */
  quality?: 'A' | 'B' | 'C' | 'D' | 'E';
  /** Type of recording (e.g. "song", "call") */
  recording_type?: string;
  /** Name of the recordist */
  recordist?: string;
  /** Geographic location of the recording */
  location?: string;

  // Clip selection
  /** Clip start time in seconds within the full audio */
  start_time?: number;
  /** Clip end time in seconds within the full audio */
  end_time?: number;

  // Shared metadata
  /** Full audio duration in seconds */
  duration?: number;
  /** Sample rate of the audio in Hz */
  sample_rate?: number;
  /** Decoded audio buffer for spectrogram rendering */
  audio_data?: ArrayBuffer;
}

/**
 * A target species with one or more reference sound sources.
 */
export interface TargetSpecies {
  /** Client-generated UUID for UI state management */
  id: string;
  /** Project tag ID, or null for a custom species not in this project */
  tag_id: string | null;
  /** Scientific name of the species */
  scientific_name: string;
  /** Optional vernacular/common name */
  common_name?: string;
  /** Reference sound sources for this species */
  sources: SoundSource[];
}

/**
 * Configuration parameters for a batch similarity search.
 */
export interface SearchConfig {
  /** Name of the embedding model to use (e.g. "perch", "birdnet") */
  model_name: string;
  /** Minimum cosine similarity threshold (0.0–1.0) */
  min_similarity: number;
  /** Maximum number of results to return per species */
  limit_per_species: number;
  /** Optional dataset to restrict the search to */
  dataset_id?: string;
}

/**
 * Aggregated similarity matches for a single species.
 */
export interface SpeciesMatchResult {
  /** Scientific name of the matched species */
  scientific_name: string;
  /** Optional vernacular/common name */
  common_name?: string;
  /** Ordered list of similar audio segments (descending similarity) */
  matches: SimilarityResult[];
}

/**
 * Response from the batch species search endpoint.
 */
export interface BatchSearchResponse {
  /** Map from tag_id (or scientific name for custom species) to match results */
  results: Record<string, SpeciesMatchResult>;
  /** Total number of matches across all species */
  total_matches: number;
  /** Wall-clock time the search took on the server, in milliseconds */
  search_duration_ms: number;
}

/**
 * Full UI state for the enhanced sound search feature.
 */
export interface SearchState {
  /** Target species with their reference sound sources */
  species: TargetSpecies[];
  /** Search configuration (model, threshold, limits) */
  config: SearchConfig;
  /** Search results keyed by species identifier, or null if not yet searched */
  results: Record<string, SimilarityResult[]> | null;
  /** Whether a search is currently in progress */
  isSearching: boolean;
  /** Human-readable error message if the last search failed */
  searchError?: string;
}
