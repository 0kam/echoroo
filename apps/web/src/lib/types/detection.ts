/**
 * TypeScript type definitions for the Detection Review feature.
 *
 * These types mirror the Pydantic schemas from the backend API for the
 * 003-detection-review feature, covering detections, confirmed regions,
 * detection runs, and species summaries.
 */

import type { Recording } from './data';
import type { Tag } from './annotation';

// ============================================
// Detection Enums
// ============================================

/**
 * Origin of a detection: automated model or human review
 */
export type DetectionSource = 'birdnet' | 'perch' | 'perch_search' | 'human';

/**
 * Review state of a detection
 */
export type DetectionStatus = 'unreviewed' | 'confirmed' | 'rejected';

// ============================================
// Vote Types
// ============================================

/**
 * A user's vote on a detection
 */
export type VoteValue = 'agree' | 'disagree' | 'unsure';

/**
 * Signal quality of the species vocalisation in an agreed detection.
 * - solo: only this species is audible
 * - dominant: this species is dominant, others may be present
 * - mixed: this species is present but not dominant
 */
export type SignalQuality = 'solo' | 'dominant' | 'mixed';

/**
 * Consensus status derived from all votes on a detection
 */
export type ConsensusStatus = 'needs_votes' | 'agreed' | 'disputed' | 'rejected';

/**
 * A single vote cast by a user on a detection
 */
export interface DetectionVote {
  /** Unique identifier */
  id: string;
  /** Detection this vote belongs to */
  detection_id: string;
  /** User who cast the vote */
  user_id: string;
  /** Display name of the voter */
  user_display_name: string | null;
  /** The vote value */
  vote: VoteValue;
  /** Signal quality assessment — only present on agree votes */
  signal_quality: SignalQuality | null;
  /** Optional suggested tag (species) if vote is 'disagree' with species suggestion */
  suggested_tag_id: string | null;
  /** Optional reason note */
  note: string | null;
  /** ISO 8601 creation timestamp */
  created_at: string;
  /** ISO 8601 last-update timestamp */
  updated_at: string;
}

/**
 * Aggregated vote summary for a detection
 */
export interface VoteSummary {
  /** Detection identifier */
  detection_id: string;
  /** Number of agree votes */
  agree_count: number;
  /** Number of disagree votes */
  disagree_count: number;
  /** Number of unsure votes */
  unsure_count: number;
  /** Total number of votes */
  total_votes: number;
  /** Derived consensus status */
  consensus: ConsensusStatus;
  /** The current user's vote, if they have voted */
  my_vote: VoteValue | null;
  /** The current user's signal quality selection (only present on agree votes) */
  my_signal_quality: SignalQuality | null;
  /** Breakdown of agree votes by signal quality */
  signal_quality_counts: { solo: number; dominant: number; mixed: number };
  /** All votes with voter info */
  votes: DetectionVote[];
}

/**
 * Request body to cast or update a vote
 */
export interface CastVoteRequest {
  /** The vote value */
  vote: VoteValue;
  /** Signal quality of the vocalisation — only meaningful for agree votes */
  signal_quality?: SignalQuality;
  /** Optional suggested species tag ID (for disagree with wrong species) */
  suggested_tag_id?: string;
  /** Optional note */
  note?: string;
}

/**
 * Lifecycle status of an automated detection run
 */
export type DetectionRunStatus = 'pending' | 'running' | 'completed' | 'failed';

// ============================================
// Core Entity Types
// ============================================

/**
 * A single species detection event within a recording.
 * Detections can be produced by automated models or added manually by a human reviewer.
 */
export interface Detection {
  /** Unique identifier */
  id: string;
  /** Recording this detection belongs to */
  recording_id: string;
  /** Tag (species) associated with this detection; null if unidentified */
  tag_id: string | null;
  /** Detection run that produced this detection; null for human-created detections */
  detection_run_id: string | null;
  /** Origin of the detection */
  source: DetectionSource;
  /** Current review status */
  status: DetectionStatus;
  /** Model confidence score (0–1); null for human detections */
  confidence: number | null;
  /** Detection start offset within the recording, in seconds */
  start_time: number;
  /** Detection end offset within the recording, in seconds */
  end_time: number;
  /** Lower frequency bound in Hz; null if not applicable */
  freq_low: number | null;
  /** Upper frequency bound in Hz; null if not applicable */
  freq_high: number | null;
  /** User ID of the reviewer who accepted or rejected the detection */
  reviewed_by_id: string | null;
  /** ISO 8601 timestamp of the review decision */
  reviewed_at: string | null;
  /** ISO 8601 creation timestamp */
  created_at: string;
  /** ISO 8601 last-update timestamp */
  updated_at: string;
  /** Expanded recording entity (optional, included when requested) */
  recording?: Recording;
  /** Expanded tag entity (optional, included when requested) */
  tag?: Tag;
}

/**
 * A time region within a recording that has been confirmed as fully reviewed.
 * Confirmed regions indicate that a human has verified all detections in the interval.
 */
export interface ConfirmedRegion {
  /** Unique identifier */
  id: string;
  /** Recording this confirmed region belongs to */
  recording_id: string;
  /** Start of the confirmed interval, in seconds */
  start_time: number;
  /** End of the confirmed interval, in seconds */
  end_time: number;
  /** User ID of the reviewer who confirmed this region */
  reviewed_by_id: string;
  /** ISO 8601 creation timestamp */
  created_at: string;
  /** ISO 8601 last-update timestamp */
  updated_at: string;
}

/**
 * An automated detection run that processes recordings to find species occurrences.
 */
export interface DetectionRun {
  /** Unique identifier */
  id: string;
  /** Parent project identifier */
  project_id: string;
  /** Dataset scoped to this run; null means the entire project */
  dataset_id: string | null;
  /** Name of the detection model used */
  model_name: string;
  /** Version of the detection model used */
  model_version: string;
  /** Model-specific parameters used during this run */
  parameters: Record<string, unknown> | null;
  /** Current lifecycle status of the run */
  status: DetectionRunStatus;
  /** Total number of detections produced by this run */
  annotation_count: number;
  /** ISO 8601 timestamp when processing began; null if not yet started */
  started_at: string | null;
  /** ISO 8601 timestamp when processing finished; null if not yet complete */
  completed_at: string | null;
  /** Human-readable error message if the run failed */
  error_message: string | null;
  /** ISO 8601 creation timestamp */
  created_at: string;
  /** ISO 8601 last-update timestamp */
  updated_at: string;
}

/**
 * Aggregated review statistics for a single species (tag) within a context.
 */
export interface SpeciesSummary {
  /** Tag identifier for the species */
  tag_id: string;
  /** Human-readable tag name */
  tag_name: string;
  /** Common / vernacular name of the species; null if not available */
  common_name: string | null;
  /** Scientific name of the species; null if not a species tag */
  scientific_name: string | null;
  /** Total number of detections for this species */
  total_count: number;
  /** Number of detections confirmed by a reviewer */
  confirmed_count: number;
  /** Number of detections rejected by a reviewer */
  rejected_count: number;
  /** Number of detections not yet reviewed */
  unreviewed_count: number;
  /** Mean confidence score across all detections (0–1); null if no scored detections */
  avg_confidence: number | null;
  /** Global taxon identifier linking this species to the taxa table; null if not linked */
  taxon_id?: string | null;
}

// ============================================
// Request Types
// ============================================

/**
 * Request body to create a new detection manually
 */
export interface DetectionCreateRequest {
  /** Recording the detection belongs to */
  recording_id: string;
  /** Tag (species) to associate; omit to create an unidentified detection */
  tag_id?: string;
  /** Origin of the detection */
  source: DetectionSource;
  /** Detection start offset within the recording, in seconds */
  start_time: number;
  /** Detection end offset within the recording, in seconds */
  end_time: number;
  /** Model confidence score (0–1) */
  confidence?: number;
  /** Lower frequency bound in Hz */
  freq_low?: number;
  /** Upper frequency bound in Hz */
  freq_high?: number;
}

/**
 * Request body to mark a time region as fully reviewed (confirmed)
 */
export interface ConfirmRequest {
  /** Start of the interval to confirm, in seconds */
  start_time: number;
  /** End of the interval to confirm, in seconds */
  end_time: number;
}

/**
 * Request body to reassign a detection to a different species
 */
export interface ChangeSpeciesRequest {
  /** ID of the replacement tag (species) */
  new_tag_id: string;
  /** Updated start time, in seconds; omit to keep existing value */
  start_time?: number;
  /** Updated end time, in seconds; omit to keep existing value */
  end_time?: number;
}

// ============================================
// List Response Types
// ============================================

/**
 * Paginated list of detections
 */
export interface DetectionListResponse {
  /** Detection records for the current page */
  items: Detection[];
  /** Total number of matching detections */
  total: number;
  /** Current page number (1-indexed) */
  page: number;
  /** Number of items per page */
  page_size: number;
  /** Total number of pages */
  pages: number;
}

/**
 * List of species summaries with a total count
 */
export interface SpeciesSummaryResponse {
  /** Per-species aggregated statistics */
  items: SpeciesSummary[];
  /** Total number of distinct species in the response */
  total_species: number;
}

/**
 * Paginated list of detection runs
 */
export interface DetectionRunListResponse {
  /** Detection run records for the current page */
  items: DetectionRun[];
  /** Total number of matching runs */
  total: number;
  /** Current page number (1-indexed) */
  page: number;
  /** Number of items per page */
  page_size: number;
  /** Total number of pages */
  pages: number;
}

// ============================================
// Temporal Data Types (Polar Heatmap)
// ============================================

/**
 * A single hourly detection data point for the activity pattern heatmap.
 */
export interface HourlyDetection {
  /** ISO 8601 date string (YYYY-MM-DD) */
  date: string;
  /** Hour of day (0–23) */
  hour: number;
  /** Number of detections in this hour slot */
  count: number;
}

/**
 * Temporal detection data for a single species, used to render the PolarHeatmap.
 */
export interface SpeciesTemporalData {
  /** Tag identifier */
  tag_id: string;
  /** Scientific name of the species */
  scientific_name: string;
  /** Common / vernacular name; null if not available */
  common_name: string | null;
  /** Total detection count across all time slots */
  total_detections: number;
  /** Hourly detection data points */
  detections: HourlyDetection[];
}

/**
 * Response from GET /api/v1/projects/{project_id}/detections/temporal-data
 */
export interface DetectionTemporalDataResponse {
  /** Project identifier */
  project_id: string;
  /** Dataset scoped to this response; null means entire project */
  dataset_id: string | null;
  /** Date range covered by the data [start, end] in ISO 8601; null if no data */
  date_range: [string, string] | null;
  /** Per-species temporal data */
  species: SpeciesTemporalData[];
}

// ============================================
// Frontend Filter State Types
// ============================================

/**
 * Active filter criteria for the detection review UI
 */
export interface DetectionFilters {
  /** Filter by species tag ID */
  tag_id?: string;
  /** Filter by review status */
  status?: DetectionStatus;
  /** Minimum confidence threshold (0–1, inclusive) */
  confidence_min?: number;
  /** Maximum confidence threshold (0–1, inclusive) */
  confidence_max?: number;
  /** Filter to a specific dataset */
  dataset_id?: string;
  /** Filter to a specific recording */
  recording_id?: string;
}
