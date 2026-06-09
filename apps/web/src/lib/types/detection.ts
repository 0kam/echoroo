/**
 * TypeScript type definitions for the Detection Review feature.
 *
 * These types mirror the Pydantic schemas from the backend API for the
 * 003-detection-review feature, covering detections, confirmed regions,
 * detection runs, and species summaries.
 */

import type { Recording } from './data';
import type { Tag } from './tag';

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
 * Voter relationship to the project at vote-creation time (FR-037).
 * Snapshot is immutable per backend contract — re-voting does not refresh it.
 *
 * - `member`: the voter was a project member (any role) at vote time
 * - `guest_authenticated`: the voter was an authenticated non-member
 *   (Public-project participation)
 * - `trusted_user`: the voter was an active Trusted user (cross-project
 *   moderator). Phase 6 does not produce these but the type allows future
 *   compatibility.
 */
export type AnnotationVoteSource = 'member' | 'guest_authenticated' | 'trusted_user';

/**
 * Project member role recorded as a snapshot at vote-creation time
 * (FR-037). Null when `source` is not `member`.
 */
export type ProjectRoleAtVote = 'viewer' | 'member' | 'admin';

/**
 * Minimal user info embedded in vote responses.
 * Mirrors the backend VoteUserInfo Pydantic schema.
 */
export interface VoteUserInfo {
  id: string;
  email: string;
  display_name: string | null;
}

/**
 * A single vote cast by a user on a detection.
 * Mirrors the backend VoteResponse Pydantic schema.
 *
 * FR-039: `user_id` (and the embedded `user` info) are masked to `null` for
 * non-Owner / non-Admin viewers when the vote's `source` is
 * `guest_authenticated` or `trusted_user`. The vote itself, `source`,
 * and `project_role_at_vote` remain visible. Member votes are never masked.
 */
export interface DetectionVote {
  /** Unique identifier */
  id: string;
  /** Annotation this vote belongs to */
  annotation_id: string;
  /**
   * Voter UUID. Null when masked under FR-039 (non-Owner / non-Admin viewer
   * looking at a guest_authenticated / trusted_user vote).
   */
  user_id: string | null;
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
  /**
   * Embedded voter info. Null when `user_id` is masked under FR-039.
   */
  user: VoteUserInfo | null;
  /**
   * Voter relationship at vote-creation time (FR-037, immutable snapshot).
   */
  source: AnnotationVoteSource;
  /**
   * Voter project role at vote-creation time. Null when `source` is not
   * `member` (FR-037, immutable snapshot).
   */
  project_role_at_vote: ProjectRoleAtVote | null;
}

/**
 * Aggregated vote summary for a detection.
 * Mirrors the backend VoteSummaryResponse Pydantic schema.
 *
 * FR-038: per-source aggregate counts (`member_*` / `guest_authenticated_*` /
 * `trusted_user_*`) are exposed independently so the UI can render the
 * 3-source breakdown required by US2 acceptance scenario #3.
 */
export interface VoteSummary {
  /** Annotation identifier */
  annotation_id: string;
  /** Number of agree votes */
  agree_count: number;
  /** Number of disagree votes */
  disagree_count: number;
  /** Number of unsure votes */
  unsure_count: number;
  /** Derived consensus status */
  consensus_status: ConsensusStatus;
  /** The current user's vote, if they have voted */
  user_vote: VoteValue | null;
  /** The current user's signal quality selection (only present on agree votes) */
  user_signal_quality: SignalQuality | null;
  /** Breakdown of agree votes by signal quality */
  signal_quality_counts: { solo: number; dominant: number; mixed: number };
  /**
   * Individual vote records. Field name matches backend's
   * `VoteSummaryResponse.voters` (renamed from `votes` in Phase 6).
   * Non-member / Trusted entries may have `user_id=null` under FR-039.
   */
  voters: DetectionVote[];
  /** Agree votes from project members (FR-038). */
  member_agree: number;
  /** Disagree votes from project members (FR-038). */
  member_disagree: number;
  /** Agree votes from authenticated non-members (FR-038). */
  guest_authenticated_agree: number;
  /** Disagree votes from authenticated non-members (FR-038). */
  guest_authenticated_disagree: number;
  /** Agree votes from active Trusted users (FR-038). */
  trusted_user_agree: number;
  /** Disagree votes from active Trusted users (FR-038). */
  trusted_user_disagree: number;
}

/**
 * Compact vote counts embedded in detection list/detail responses.
 * Mirrors the backend DetectionVoteCounts Pydantic schema.
 */
export interface DetectionVoteCounts {
  agree_count: number;
  disagree_count: number;
  unsure_count: number;
  user_vote: VoteValue | null;
  user_signal_quality: SignalQuality | null;
  signal_quality_counts: { solo: number; dominant: number; mixed: number };
  consensus_status: ConsensusStatus;
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
  /** Aggregate vote counts and consensus status (always included from backend) */
  votes?: DetectionVoteCounts;
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
  /** English common name; null if not available */
  common_name: string | null;
  /**
   * Locale-resolved vernacular name for the requested `locale` query param.
   * Null when no vernacular entry is available for the active locale.
   */
  vernacular_name?: string | null;
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
  /** English common name; null if not available */
  common_name: string | null;
  /**
   * Locale-resolved vernacular name for the requested `locale` query param.
   * Null when no vernacular entry is available for the active locale.
   */
  vernacular_name?: string | null;
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
