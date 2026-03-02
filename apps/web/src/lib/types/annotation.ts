/**
 * TypeScript type definitions for the Annotation feature.
 *
 * These are the canonical type definitions for all annotation-related entities.
 * They are re-exported from the main types index ($lib/types).
 */

// ============================================
// Annotation Enums
// ============================================

/**
 * Tag classification category
 */
export type TagCategory = 'species' | 'sound_type' | 'quality';

/**
 * Visibility level of an annotation project
 */
export type AnnotationProjectVisibility = 'private' | 'public';

/**
 * Lifecycle status of an annotation task
 */
export type AnnotationTaskStatus =
  | 'pending'
  | 'in_progress'
  | 'completed'
  | 'review_pending';

/**
 * Human review decision on a clip annotation
 */
export type ReviewStatus = 'unreviewed' | 'approved' | 'rejected';

/**
 * Who or what produced an annotation
 */
export type AnnotationSource = 'human' | 'model';

/**
 * Spatial/temporal geometry shape type
 */
export type GeometryType = 'BoundingBox' | 'TimeInterval';

// ============================================
// Tag Types
// ============================================

/**
 * Tag entity used to label sound events and clips
 */
export interface Tag {
  /** Unique identifier */
  id: string;
  /** Project this tag belongs to */
  project_id: string;
  /** Parent tag identifier for hierarchical taxonomies */
  parent_id?: string | null;
  /** Human-readable tag name */
  name: string;
  /** Classification category */
  category: TagCategory;
  /** GBIF backbone taxon key (species tags only) */
  gbif_taxon_key?: number | null;
  /** Scientific name (species tags only) */
  scientific_name?: string | null;
  /** Common / vernacular name (species tags only) */
  common_name?: string | null;
  /** ISO 8601 creation timestamp */
  created_at: string;
  /** ISO 8601 last-update timestamp */
  updated_at: string;
}

/**
 * Tag with child tags and usage statistics
 */
export interface TagDetail extends Tag {
  /** Direct child tags in the hierarchy */
  children: Tag[];
  /** Number of annotations that reference this tag */
  usage_count: number;
}

/**
 * Request body to create a new tag
 */
export interface TagCreate {
  /** Human-readable tag name */
  name: string;
  /** Classification category */
  category: TagCategory;
  /** Parent tag identifier for hierarchical taxonomies */
  parent_id?: string;
  /** GBIF backbone taxon key (species tags only) */
  gbif_taxon_key?: number;
  /** Scientific name (species tags only) */
  scientific_name?: string;
  /** Common / vernacular name (species tags only) */
  common_name?: string;
}

/**
 * Request body to partially update an existing tag
 */
export interface TagUpdate {
  /** Updated human-readable name */
  name?: string;
  /** Updated parent identifier; pass null to detach from hierarchy */
  parent_id?: string | null;
  /** Updated common / vernacular name */
  common_name?: string;
}

/**
 * Paginated list of tags
 */
export interface TagListResponse {
  /** Tag records for the current page */
  items: Tag[];
  /** Total number of matching tags */
  total: number;
  /** Current page number (1-indexed) */
  page: number;
  /** Number of items per page */
  page_size: number;
  /** Total number of pages */
  pages: number;
}

/**
 * Taxon suggestion returned by the GBIF name-lookup API
 */
export interface GBIFSuggestion {
  /** GBIF backbone taxon key */
  key: number;
  /** Canonical (uninominal / binominal) name without authorship */
  canonical_name: string;
  /** Full scientific name including authorship */
  scientific_name: string;
  /** Taxonomic rank (e.g. "SPECIES", "GENUS") */
  rank: string;
  /** Kingdom name */
  kingdom?: string;
  /** Phylum name */
  phylum?: string;
  /** Class name */
  class_name?: string;
  /** Order name */
  order?: string;
  /** Family name */
  family?: string;
}

/**
 * Tag paired with its usage count, used in statistics responses
 */
export interface TagStatistic {
  /** The tag entity */
  tag: Tag;
  /** Number of annotations that reference this tag */
  usage_count: number;
}

// ============================================
// Annotation Project Types
// ============================================

/**
 * Aggregated progress counters for an annotation project
 */
export interface AnnotationProgress {
  /** Total number of tasks in the project */
  total_tasks: number;
  /** Number of tasks with status "completed" */
  completed_tasks: number;
  /** Number of tasks with status "in_progress" */
  in_progress_tasks: number;
  /** Number of tasks with status "pending" */
  pending_tasks: number;
  /** Number of tasks with status "review_pending" */
  review_pending_tasks: number;
}

/**
 * Lightweight dataset reference embedded in project responses
 */
export interface DatasetSummary {
  /** Unique identifier */
  id: string;
  /** Dataset name */
  name: string;
}

/**
 * Lightweight tag reference embedded in project and task responses
 */
export interface TagSummary {
  /** Unique identifier */
  id: string;
  /** Tag name */
  name: string;
  /** Classification category */
  category: string;
}

/**
 * Annotation project entity
 */
export interface AnnotationProject {
  /** Unique identifier */
  id: string;
  /** Parent project identifier */
  project_id: string;
  /** User ID of the project creator */
  created_by_id: string;
  /** Human-readable project name */
  name: string;
  /** Optional project description */
  description?: string | null;
  /** Annotator instructions displayed during the annotation workflow */
  instructions?: string | null;
  /** Project visibility level */
  visibility: AnnotationProjectVisibility;
  /** ISO 8601 creation timestamp */
  created_at: string;
  /** ISO 8601 last-update timestamp */
  updated_at: string;
}

/**
 * Annotation project with associated datasets, tags, and progress counters
 */
export interface AnnotationProjectDetail extends AnnotationProject {
  /** Datasets included in this annotation project */
  datasets: DatasetSummary[];
  /** Tags available for annotators to apply */
  tags: TagSummary[];
  /** Aggregated task progress */
  progress: AnnotationProgress;
}

/**
 * Request body to create a new annotation project
 */
export interface AnnotationProjectCreate {
  /** Human-readable project name */
  name: string;
  /** Optional project description */
  description?: string;
  /** Annotator instructions displayed during the annotation workflow */
  instructions?: string;
  /** Initial visibility level (defaults to 'private') */
  visibility?: AnnotationProjectVisibility;
  /** Dataset IDs to include */
  dataset_ids?: string[];
  /** Tag IDs to make available to annotators */
  tag_ids?: string[];
}

/**
 * Request body to partially update an annotation project
 */
export interface AnnotationProjectUpdate {
  /** Updated project name */
  name?: string;
  /** Updated description */
  description?: string;
  /** Updated annotator instructions */
  instructions?: string;
  /** Updated visibility level */
  visibility?: AnnotationProjectVisibility;
  /** Replacement list of dataset IDs (full replace, not patch) */
  dataset_ids?: string[];
  /** Replacement list of tag IDs (full replace, not patch) */
  tag_ids?: string[];
}

/**
 * Paginated list of annotation projects
 */
export interface AnnotationProjectListResponse {
  /** Annotation project records for the current page */
  items: AnnotationProjectDetail[];
  /** Total number of matching projects */
  total: number;
  /** Current page number (1-indexed) */
  page: number;
  /** Number of items per page */
  page_size: number;
  /** Total number of pages */
  pages: number;
}

/**
 * Response returned when background task generation is triggered
 */
export interface TaskGenerationResponse {
  /** Celery / background task ID for polling status */
  task_id: string;
  /** Human-readable status message */
  message: string;
}

// ============================================
// Annotation Task Types
// ============================================

/**
 * Minimal recording metadata embedded inside a task's clip detail
 */
export interface RecordingSummaryForTask {
  /** Unique identifier */
  id: string;
  /** Original filename of the audio file */
  filename: string;
  /** Sample rate in Hz */
  samplerate: number;
  /** Total duration in seconds */
  duration: number;
}

/**
 * Clip details embedded in an annotation task response
 */
export interface ClipDetailForTask {
  /** Unique identifier */
  id: string;
  /** Parent recording identifier */
  recording_id: string;
  /** Clip start offset within the recording, in seconds */
  start_time: number;
  /** Clip end offset within the recording, in seconds */
  end_time: number;
  /** Parent recording summary (optional, may be omitted in list responses) */
  recording?: RecordingSummaryForTask;
}

/**
 * Lightweight annotation project reference embedded in task responses
 */
export interface AnnotationProjectSummary {
  /** Unique identifier */
  id: string;
  /** Project name */
  name: string;
  /** Annotator instructions, if any */
  instructions?: string | null;
  /** Tags available within this project */
  tags: TagSummary[];
}

/**
 * Annotation task entity
 */
export interface AnnotationTask {
  /** Unique identifier */
  id: string;
  /** Parent annotation project identifier */
  annotation_project_id: string;
  /** Clip to be annotated */
  clip_id: string;
  /** User ID of the assigned annotator, if any */
  assigned_to_id?: string | null;
  /** Current lifecycle status */
  status: AnnotationTaskStatus;
  /** Relative priority (higher value = higher priority) */
  priority: number;
  /** ISO 8601 creation timestamp */
  created_at: string;
  /** ISO 8601 last-update timestamp */
  updated_at: string;
}

/**
 * Request body to partially update an annotation task
 */
export interface AnnotationTaskUpdate {
  /** Reassign task to a different user */
  assigned_to_id?: string;
  /** Update lifecycle status */
  status?: AnnotationTaskStatus;
  /** Update priority */
  priority?: number;
}

/**
 * Annotation task with full clip, annotation, and project details
 */
export interface AnnotationTaskDetail extends AnnotationTask {
  /** Full clip details including recording metadata */
  clip: ClipDetailForTask;
  /** Existing clip annotation for this task, if any */
  clip_annotation?: ClipAnnotationDetail | null;
  /** Parent annotation project summary */
  annotation_project: AnnotationProjectSummary;
}

/**
 * Paginated list of annotation tasks
 */
export interface AnnotationTaskListResponse {
  /** Task records for the current page */
  items: AnnotationTask[];
  /** Total number of matching tasks */
  total: number;
  /** Current page number (1-indexed) */
  page: number;
  /** Number of items per page */
  page_size: number;
  /** Total number of pages */
  pages: number;
}

/**
 * Response returned after completing a task, optionally providing the next task
 */
export interface TaskCompletionResponse {
  /** ID of the task that was just completed */
  completed_task_id: string;
  /** Next task to work on, or null if no tasks remain */
  next_task?: AnnotationTaskDetail | null;
}

// ============================================
// Geometry Types
// ============================================

/**
 * Spatial or temporal geometry attached to a sound event annotation
 *
 * For BoundingBox:    coordinates = [time_start, freq_low, time_end, freq_high]
 * For TimeInterval:  coordinates = [time_start, time_end]
 */
export interface Geometry {
  /** Shape type that determines how coordinates are interpreted */
  type: GeometryType;
  /** Geometry-specific coordinate values */
  coordinates: number[];
}

// ============================================
// Sound Event Annotation Types
// ============================================

/**
 * Individual sound event annotation within a clip
 */
export interface SoundEventAnnotation {
  /** Unique identifier */
  id: string;
  /** Parent clip annotation identifier */
  clip_annotation_id: string;
  /** Spatial / temporal bounds of the sound event */
  geometry: Geometry;
  /** Whether annotation was created by a human or a model */
  source: AnnotationSource;
  /** Model confidence score, if applicable (0–1) */
  confidence?: number | null;
  /** Tags applied to this sound event */
  tags: TagSummary[];
  /** User ID of the annotator who created this record */
  created_by_id: string;
  /** ISO 8601 creation timestamp */
  created_at: string;
  /** ISO 8601 last-update timestamp */
  updated_at: string;
}

/**
 * Request body to create a new sound event annotation
 */
export interface SoundEventAnnotationCreate {
  /** Spatial / temporal bounds of the sound event */
  geometry: Geometry;
  /** IDs of tags to attach */
  tag_ids?: string[];
  /** Model confidence score (0–1); omit for human annotations */
  confidence?: number;
  /** Annotation source (defaults to 'human') */
  source?: AnnotationSource;
}

/**
 * Request body to partially update a sound event annotation
 */
export interface SoundEventAnnotationUpdate {
  /** Updated geometry */
  geometry?: Geometry;
  /** Updated confidence score (0–1) */
  confidence?: number;
}

// ============================================
// Clip Annotation Types
// ============================================

/**
 * Reviewer or annotator note attached to a clip annotation
 */
export interface Note {
  /** Unique identifier */
  id: string;
  /** Text content of the note */
  content: string;
  /** Whether this note was left as part of the review process */
  is_review: boolean;
  /** User ID of the note author */
  created_by_id: string;
  /** ISO 8601 creation timestamp */
  created_at: string;
}

/**
 * Request body to create a note on a clip annotation
 */
export interface NoteCreate {
  /** Text content of the note */
  content: string;
  /** Mark note as a review comment (defaults to false) */
  is_review?: boolean;
}

/**
 * Full clip annotation with all sound events, tags, and notes
 */
export interface ClipAnnotationDetail {
  /** Unique identifier */
  id: string;
  /** Associated annotation task identifier */
  task_id: string;
  /** Annotated clip identifier */
  clip_id: string;
  /** Current review decision */
  review_status: ReviewStatus;
  /** User ID of the reviewer, if reviewed */
  reviewed_by_id?: string | null;
  /** ISO 8601 timestamp of the review decision, if reviewed */
  reviewed_at?: string | null;
  /** Clip-level tags applied to the entire clip */
  tags: TagSummary[];
  /** Individual sound event annotations within the clip */
  sound_events: SoundEventAnnotation[];
  /** Notes left by annotators or reviewers */
  notes: Note[];
  /** User ID of the annotator who created this record */
  created_by_id: string;
  /** ISO 8601 creation timestamp */
  created_at: string;
  /** ISO 8601 last-update timestamp */
  updated_at: string;
}

// ============================================
// Review Types
// ============================================

/**
 * Request body to submit a review decision on a clip annotation
 */
export interface ReviewRequest {
  /** Review outcome */
  status: 'approved' | 'rejected';
  /** Optional reviewer comment (stored as a review note) */
  comment?: string;
}

// ============================================
// Tag Operation Types
// ============================================

/**
 * Request body to add a single tag to a clip annotation or sound event
 */
export interface AddTagRequest {
  /** ID of the tag to add */
  tag_id: string;
}

// ============================================
// List Query Params
// ============================================

/**
 * Query parameters for listing annotation tasks
 */
export interface AnnotationTaskListParams {
  /** Filter by task status */
  status?: AnnotationTaskStatus;
  /** Filter by assigned user ID */
  assigned_to_id?: string;
  /** Page number (1-indexed) */
  page?: number;
  /** Number of items per page */
  page_size?: number;
  /** Field to sort by */
  sort_by?: 'priority' | 'created_at' | 'status';
  /** Sort direction */
  sort_order?: 'asc' | 'desc';
}

/**
 * Query parameters for listing tags
 */
export interface TagListParams {
  /** Filter by tag category */
  category?: TagCategory;
  /** Search term matched against name and scientific name */
  search?: string;
  /** Page number (1-indexed) */
  page?: number;
  /** Number of items per page */
  page_size?: number;
}

/**
 * Query parameters for listing annotation projects
 */
export interface AnnotationProjectListParams {
  /** Page number (1-indexed) */
  page?: number;
  /** Number of items per page */
  page_size?: number;
}

/**
 * Supported export formats for annotation data
 */
export type ExportFormat = 'json' | 'csv' | 'aoef';
