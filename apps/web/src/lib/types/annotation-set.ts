/**
 * TypeScript type definitions for the AnnotationSet ground-truth system.
 *
 * Mirrors the OpenAPI contracts under `specs/003-annotation/contracts/`.
 * All species references use the public `species_id` field (the backend
 * maps this to the underlying `taxon_id` column at the schema layer).
 */

// ============================================================
// Enumerations
// ============================================================

/** Lifecycle status of an AnnotationSet. */
export type AnnotationSetStatus =
  | 'sampling'
  | 'ready'
  | 'in_progress'
  | 'completed';

/** Lifecycle status of an individual AnnotationSegment. */
export type AnnotationSegmentStatus =
  | 'unannotated'
  | 'annotated'
  | 'skipped';

/**
 * Segmentation strategy for an AnnotationSet.
 *
 * - `fixed`: fixed-length sliding-window slots (requires `segment_length_sec`).
 * - `whole_recording`: one full-length segment per recording; `num_segments`
 *   then acts as the maximum number of recordings to sample.
 */
export type SegmentMode = 'fixed' | 'whole_recording';

/** Model kind recognised by the cross-model evaluation runner. */
export type EvaluationModelKind = 'birdnet' | 'perch' | 'custom';

/** Status of an evaluation run Celery job. */
export type EvaluationRunStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed';

// ============================================================
// Filters (shared across create / read)
// ============================================================

/** Inclusive `[start, end]` date filter (ISO-8601 date strings). */
export interface DateRange {
  start: string;
  end: string;
}

/** Inclusive time-of-day filter with `HH:MM` strings. */
export interface TimeOfDayRange {
  start: string;
  end: string;
}

// ============================================================
// Palette
// ============================================================

/** A single species entry in an AnnotationSet's palette. */
export interface PaletteEntry {
  species_id: string;
  scientific_name: string;
  common_name: string | null;
  position: number;
}

/** Request body for adding a palette entry. */
export interface PaletteEntryCreate {
  species_id: string;
  position?: number;
}

// ============================================================
// AnnotationSet
// ============================================================

/** Aggregate progress counts across all segments in a set. */
export interface AnnotationSetProgress {
  total: number;
  unannotated: number;
  annotated: number;
  skipped: number;
  empty: number;
}

/** Summary AnnotationSet record (list view). */
export interface AnnotationSet {
  id: string;
  project_id: string;
  dataset_id: string;
  created_by_id: string;
  name: string;
  filter_date_range: DateRange | null;
  filter_time_of_day_range: TimeOfDayRange | null;
  segment_mode: SegmentMode;
  segment_length_sec: number | null;
  num_segments: number;
  status: AnnotationSetStatus;
  /** Optional human-readable warning surfaced by the sampler. */
  sampling_warning: string | null;
  created_at: string;
  updated_at: string;
  /**
   * Real per-status segment counts for the list view. The list endpoint
   * always populates this; other producers may omit it (null).
   */
  progress: AnnotationSetProgress | null;
}

/** Full AnnotationSet including palette and per-status counts. */
export interface AnnotationSetDetail extends AnnotationSet {
  palette: PaletteEntry[];
  progress: AnnotationSetProgress;
}

/** Request body for `POST /annotation-sets`. */
export interface AnnotationSetCreate {
  project_id: string;
  dataset_id: string;
  name: string;
  filter_date_range?: DateRange | null;
  filter_time_of_day_range?: TimeOfDayRange | null;
  /** Segmentation strategy. Defaults to `fixed` on the backend if omitted. */
  segment_mode?: SegmentMode;
  /** Required when `segment_mode` is `fixed`; omit for `whole_recording`. */
  segment_length_sec?: number | null;
  /**
   * Target segment count. In `whole_recording` mode this is the maximum
   * number of recordings to sample (one full-length segment each).
   */
  num_segments: number;
}

/** Request body for `PATCH /annotation-sets/{id}`. */
export interface AnnotationSetUpdate {
  name?: string;
}

/** Paginated list response wrapper. */
export interface AnnotationSetListResponse {
  items: AnnotationSet[];
  total: number;
  page: number;
  page_size: number;
}

/** Response from dispatching sampling. */
export interface SamplingDispatchResponse {
  task_id: string;
  status: AnnotationSetStatus;
}

// ============================================================
// AnnotationSegment
// ============================================================

/** Summary row returned by the segment listing endpoint. */
export interface AnnotationSegmentSummary {
  id: string;
  recording_id: string;
  recording_filename: string;
  start_time_sec: number;
  end_time_sec: number;
  is_empty: boolean;
  status: AnnotationSegmentStatus;
  annotated_by_id: string | null;
  annotated_at: string | null;
  annotation_count: number;
}

/** Paginated segment list response. */
export interface AnnotationSegmentListResponse {
  items: AnnotationSegmentSummary[];
  total: number;
  page: number;
  page_size: number;
}

/** Request body for `PATCH /segments/{id}`. */
export interface AnnotationSegmentUpdate {
  status?: AnnotationSegmentStatus;
  is_empty?: boolean;
}

/** Query parameters for listing segments. */
export interface ListSegmentsParams {
  status?: AnnotationSegmentStatus;
  is_empty?: boolean;
  page?: number;
  page_size?: number;
}

// ============================================================
// TimeRangeAnnotation
// ============================================================

/** A single time-range annotation attached to a segment. */
export interface TimeRangeAnnotation {
  id: string;
  segment_id: string;
  start_time_sec: number;
  end_time_sec: number;
  species_id: string;
  species_scientific_name: string;
  species_common_name: string | null;
  confidence: number | null;
  created_by_id: string;
  created_at: string;
  updated_at: string;
  note_count: number;
}

/** Request body for creating a TimeRangeAnnotation. */
export interface TimeRangeAnnotationCreate {
  start_time_sec: number;
  end_time_sec: number;
  species_id: string;
  confidence?: number | null;
}

/** Request body for updating a TimeRangeAnnotation. */
export interface TimeRangeAnnotationUpdate {
  start_time_sec?: number;
  end_time_sec?: number;
  species_id?: string;
  confidence?: number | null;
}

// ============================================================
// Notes
// ============================================================

/** A note attached to a segment or annotation. */
export interface AnnotationNote {
  id: string;
  content: string;
  is_issue: boolean;
  created_by_id: string;
  created_at: string;
}

/** Request body for creating a note. */
export interface AnnotationNoteCreate {
  content: string;
  is_issue?: boolean;
}

// ============================================================
// Segment detail (nested annotations + notes)
// ============================================================

/** Full segment detail returned by `GET /segments/{id}`. */
export interface AnnotationSegmentDetail {
  id: string;
  annotation_set_id: string;
  recording_id: string;
  recording_filename: string;
  recording_duration_sec: number;
  start_time_sec: number;
  end_time_sec: number;
  is_empty: boolean;
  status: AnnotationSegmentStatus;
  annotated_by_id: string | null;
  annotated_at: string | null;
  annotations: TimeRangeAnnotation[];
  notes: AnnotationNote[];
}

// ============================================================
// Evaluation
// ============================================================

/** Reference to BirdNET pipeline (no parameters). */
export interface BirdNETModelRef {
  kind: 'birdnet';
}

/** Reference to Perch pipeline (no parameters). */
export interface PerchModelRef {
  kind: 'perch';
}

/** Reference to a specific custom SVM classifier. */
export interface CustomModelRef {
  kind: 'custom';
  model_id: string;
}

/** Discriminated union describing any detection model for evaluation. */
export type EvaluationModelRef = BirdNETModelRef | PerchModelRef | CustomModelRef;

/** Per-species metric row within a model summary. */
export interface SpeciesMetric {
  taxon_id: string;
  scientific_name: string | null;
  common_name: string | null;
  tp_precision: number;
  fp: number;
  tp_recall: number;
  fn: number;
  precision: number;
  recall: number;
  f1: number;
  detections_total: number;
  ground_truths_total: number;
}

/** All-species aggregate metric for a single model reference. */
export interface OverallMetric {
  tp_precision: number;
  fp: number;
  tp_recall: number;
  fn: number;
  precision: number;
  recall: number;
  f1: number;
  detections_total: number;
  ground_truths_total: number;
}

/** Summary bundle for one model reference within an evaluation run. */
export interface ModelEvaluationSummary {
  model_ref: EvaluationModelRef;
  overall: OverallMetric;
  species: SpeciesMetric[];
}

/** Raw evaluation run row (list view / POST response). */
export interface EvaluationRunResponse {
  id: string;
  annotation_set_id: string;
  created_by_id: string;
  status: EvaluationRunStatus;
  requested_model_refs: EvaluationModelRef[];
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

/** Top-level summary response for `GET /evaluation-runs/{id}`. */
export interface EvaluationSummary {
  id: string;
  annotation_set_id: string;
  status: EvaluationRunStatus;
  requested_model_refs: EvaluationModelRef[];
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  models: ModelEvaluationSummary[];
}

/** Paginated list response for evaluation runs. */
export interface EvaluationRunListResponse {
  items: EvaluationRunResponse[];
  total: number;
}

/** Request body for dispatching evaluation. */
export interface EvaluationDispatchRequest {
  model_refs: EvaluationModelRef[];
}
