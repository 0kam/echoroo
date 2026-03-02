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
export type DetectionSource = 'birdnet' | 'perch_search' | 'human';

/**
 * Review state of a detection
 */
export type DetectionStatus = 'unreviewed' | 'confirmed' | 'rejected';

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
