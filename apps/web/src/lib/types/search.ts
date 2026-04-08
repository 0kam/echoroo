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
  /** Recording date/time (parsed from filename or metadata), ISO 8601 string or null */
  recording_datetime: string | null;
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
  /** Whether this source is an uploaded file, a remote URL, or a persisted S3 object */
  origin: 'upload' | 'url' | 's3';
  /** Optional human-readable label for this source */
  label?: string;

  // S3-specific (persisted session reference audio)
  /** Streaming URL for persisted reference audio (set when loading from a saved session) */
  streamUrl?: string;
  /** Index of this source within reference_audio_keys (used to build the streaming URL) */
  sourceIndex?: number;

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
  /** Optional dataset to restrict the search to */
  dataset_id?: string;
  /** Maximum number of results to return per species (default 20) */
  limit_per_species?: number;
}

// ============================================
// Distribution & Sampling Types
// ============================================

/**
 * A single bin in a similarity score distribution histogram.
 */
export interface DistributionBin {
  /** Lower bound of this bin (inclusive), e.g. 0.3 */
  lower: number;
  /** Upper bound of this bin (exclusive), e.g. 0.35 */
  upper: number;
  /** Number of results falling within this bin */
  count: number;
}

/**
 * Response from the session distribution endpoint.
 */
export interface SessionDistributionResponse {
  /** Session UUID */
  session_id: string;
  /** Pre-computed histogram bins */
  bins: DistributionBin[];
  /** Total number of results across all bins */
  total_count: number;
}

/**
 * Response from the session sample endpoint.
 */
export interface SessionSampleResponse {
  /** Session UUID */
  session_id: string;
  /** Randomly sampled results within the requested similarity range */
  results: SimilarityResult[];
  /** Total number of results in the requested range (before sampling) */
  total_in_range: number;
}

/**
 * A single (date, hour) cell in the time-of-day similarity distribution.
 */
export interface TimeDistributionCell {
  /** Date in YYYY-MM-DD format */
  date: string;
  /** Hour of day (0-23) */
  hour: number;
  /** Average similarity for this cell */
  avg_similarity: number;
  /** Number of embeddings in this cell */
  count: number;
}

/**
 * Response from the session time-distribution endpoint.
 */
export interface SessionTimeDistributionResponse {
  /** Session UUID */
  session_id: string;
  /** Average similarity per (date, hour) cell */
  cells: TimeDistributionCell[];
  /** IANA timezone used for hour grouping (e.g. "Asia/Tokyo", "UTC", or "Mixed") */
  timezone: string;
}

/**
 * Aggregated similarity matches for a single species.
 */
export interface SpeciesMatchResult {
  /** Project tag ID for the species */
  tag_id?: string;
  /** Scientific name of the matched species */
  scientific_name: string;
  /** Optional vernacular/common name */
  common_name?: string;
  /** Ordered list of similar audio segments (descending similarity) */
  matches: SimilarityResult[];
}

/**
 * Client-side review status for a search result card.
 */
export type SearchResultStatus = 'unreviewed' | 'confirmed' | 'rejected';

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

// ============================================
// Xeno-canto Search Types
// ============================================

/**
 * A single recording result from the Xeno-canto API.
 */
export interface XenoCantoRecording {
  /** Xeno-canto recording ID (numeric string, e.g. "1065457") */
  xc_id: string;
  /** Scientific name of the species */
  scientific_name: string;
  /** Common/vernacular name of the species */
  common_name: string;
  /** Name of the recordist */
  recordist: string;
  /** Country where the recording was made */
  country: string;
  /** Specific location of the recording */
  location: string;
  /** Latitude of the recording location */
  latitude: number | null;
  /** Longitude of the recording location */
  longitude: number | null;
  /** Type of vocalization (e.g. "song", "call") */
  recording_type: string;
  /** Quality rating (A–E) */
  quality: string;
  /** Duration of the recording (e.g. "1:23") */
  length: string;
  /** Date the recording was made */
  date: string;
  /** Direct URL to the audio file */
  file_url: string;
  /** URL to the sonogram image (small version), or null if unavailable */
  sonogram_url: string | null;
  /** License string for the recording */
  license: string;
}

/**
 * Paginated response from the Xeno-canto search endpoint.
 */
export interface XenoCantoSearchResponse {
  /** Total number of matching recordings */
  total_recordings: number;
  /** Total number of matching species */
  total_species: number;
  /** Current page number (1-indexed) */
  page: number;
  /** Total number of pages */
  total_pages: number;
  /** Recordings on the current page */
  recordings: XenoCantoRecording[];
}

/**
 * Response returned immediately when a batch search job is submitted (202 Accepted).
 */
export interface SearchJobSubmitResponse {
  /** UUID of the submitted search job */
  job_id: string;
  /** Initial status of the job (always "pending" on submission) */
  status: string;
  /** UUID of the search session created for this job */
  session_id?: string;
}

/**
 * Response from polling the search job status endpoint.
 */
export interface SearchJobStatusResponse {
  /** UUID of the search job */
  job_id: string;
  /** Current status of the job */
  status: 'pending' | 'processing' | 'completed' | 'failed';
  /** Progress information during processing, or null if not yet available */
  progress: { species_completed: number; species_total: number } | null;
  /** Full batch search results once completed, or null if not yet done */
  results: BatchSearchResponse | null;
  /** Error message if the job failed, or null otherwise */
  error: string | null;
  /** UUID of the search session associated with this job */
  session_id?: string;
}

// ============================================
// Search Session Types (Phase 5)
// ============================================

/**
 * Full details of a persisted search session, including merged review statuses.
 */
export interface SearchSession {
  id: string;
  project_id: string;
  user_id: string | null;
  name: string | null;
  status: 'pending' | 'running' | 'completed' | 'failed';
  model_name: string;
  parameters: {
    min_similarity?: number;
    limit_per_species?: number;
    dataset_id: string | null;
  } | null;
  species_config: Array<{
    tag_id: string | null;
    scientific_name: string;
    common_name: string | null;
    sources: Array<Record<string, unknown>>;
  }> | null;
  results: BatchSearchResponse | null;
  result_count: number;
  confirmed_count: number;
  rejected_count: number;
  celery_job_id: string | null;
  reference_audio_keys: string[] | null;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * Summary item for listing search sessions.
 */
export interface SearchSessionListItem {
  id: string;
  name: string | null;
  status: 'pending' | 'running' | 'completed' | 'failed';
  model_name: string;
  result_count: number;
  confirmed_count: number;
  rejected_count: number;
  species_config: Array<{
    tag_id: string | null;
    scientific_name: string;
    common_name: string | null;
  }> | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

/**
 * Paginated list of search sessions.
 */
export interface SearchSessionListResponse {
  sessions: SearchSessionListItem[];
  total: number;
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
