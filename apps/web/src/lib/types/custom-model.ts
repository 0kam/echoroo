/**
 * TypeScript type definitions for the Custom SVM Classifier feature.
 *
 * These types mirror the Pydantic schemas from the backend API.
 */

export type CustomModelStatus =
  | 'draft'
  | 'training'
  | 'trained'
  | 'deployed'
  | 'failed'
  | 'archived';

/**
 * Trained model performance metrics (from cross-validation or holdout evaluation).
 *
 * Backend stores best_c in `hyperparameters`, not in `metrics`.
 * `confusion_matrix` is a nested array: [[TN, FP], [FN, TP]].
 */
export interface CustomModelMetrics {
  accuracy: number;
  precision: number;
  recall: number;
  f1: number;
  roc_auc: number;
  pr_auc: number;
  confusion_matrix: [[number, number], [number, number]];
  /** Cross-validation method used (e.g. "Grouped K-Fold", "Standard K-Fold") */
  cv_method?: string;
  /** Warning message if CV had issues (e.g. insufficient groups for grouped CV) */
  cv_warning?: string;
}

/**
 * Statistics collected during the training run.
 */
export interface CustomModelTrainingStats {
  positive_count: number;
  negative_count: number;
  unlabeled_count: number;
  training_duration_s: number;
}

/**
 * Full custom model response including metrics and training details.
 */
export interface CustomModel {
  id: string;
  project_id: string;
  user_id: string | null;
  name: string;
  description: string | null;
  target_tag_id: string | null;
  model_type: string;
  status: CustomModelStatus;
  search_session_id: string | null;
  dataset_id: string | null;
  training_config: Record<string, unknown> | null;
  hyperparameters: Record<string, unknown> | null;
  metrics: CustomModelMetrics | null;
  training_stats: CustomModelTrainingStats | null;
  model_artifact_key: string | null;
  embedding_model_name: string;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * Summary item returned in list responses (no detailed metrics).
 */
export interface CustomModelListItem {
  id: string;
  name: string;
  description: string | null;
  target_tag_id: string | null;
  model_type: string;
  status: CustomModelStatus;
  search_session_id: string | null;
  dataset_id: string | null;
  embedding_model_name: string;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * Paginated list of custom models.
 */
export interface CustomModelListResponse {
  models: CustomModelListItem[];
  total: number;
}

/**
 * Request body for creating a new custom model.
 */
export interface CustomModelCreate {
  name: string;
  description?: string;
  target_tag_id: string;
  embedding_model_name?: string;
  search_session_id?: string;
}

/**
 * Request body for triggering model training.
 */
export interface CustomModelTrainRequest {
  use_unlabeled?: boolean;
  max_unlabeled_samples?: number;
}

// ============================================================
// Sampling rounds (seed sampling + active learning)
// ============================================================

/**
 * A single item within a sampling round, representing one candidate clip
 * drawn from the embedding space for human review.
 */
export interface SamplingRoundItem {
  id: string;
  embedding_id: string;
  /** How this item was selected: nearest-neighbours, boundary, random, or AL */
  sample_type: 'easy_positive' | 'boundary' | 'others' | 'active_learning';
  /** Cosine similarity to the reference embedding (null for 'others') */
  similarity: number | null;
  /** Distance from the current decision boundary (null for seed rounds) */
  decision_distance: number | null;
  annotation_id: string;
  /** 'confirmed' | 'rejected' | 'unsure' | null — set after user labeling */
  review_status: string | null;
  recording_id: string | null;
  /** Original filename of the source recording, for display in cards */
  recording_filename?: string | null;
  start_time: number | null;
  end_time: number | null;
}

/**
 * Histogram of sigmoid(decision_distance) computed over all scored unlabeled
 * embeddings during an active-learning iteration. Used to visualise how the
 * model's prediction distribution shifts between AL rounds so users can
 * decide when to stop sampling and start training.
 */
export interface ScoreDistribution {
  /** 21 bin edges in [0.0, 1.0] that define 20 equal-width bins. */
  bin_edges: number[];
  /** 20 integer counts, one per bin. */
  bin_counts: number[];
  /** Mean sigmoid score across all scored embeddings. */
  mean_score: number;
  /** Count of scored embeddings with sigmoid score >= 0.5. */
  positive_count: number;
  /** Count of scored embeddings with sigmoid score < 0.5. */
  negative_count: number;
  /** Total number of embeddings that were scored for this round. */
  total_scored: number;
}

/**
 * A sampling round groups a set of candidate clips generated in one
 * invocation of the seed-sampling or active-learning algorithm.
 */
export interface SamplingRound {
  id: string;
  custom_model_id: string;
  round_number: number;
  round_type: 'seed' | 'active_learning';
  sampling_config: Record<string, unknown> | null;
  sample_count: number;
  status: 'pending' | 'running' | 'completed' | 'failed';
  job_id: string | null;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
  /**
   * Histogram of sigmoid(decision_distance) over all scored unlabeled
   * embeddings for this AL iteration. Null for seed rounds and for legacy
   * rounds produced before this field was introduced.
   */
  score_distribution?: ScoreDistribution | null;
  items: SamplingRoundItem[];
}

/**
 * Paginated list response for sampling rounds.
 */
export interface SamplingRoundListResponse {
  rounds: SamplingRound[];
  total: number;
}

// ============================================================
// Detection runs (model application jobs)
// ============================================================

/** Status transitions: pending -> running -> (completed | failed) */
export type DetectionRunStatus = 'pending' | 'running' | 'completed' | 'failed';

/**
 * A single detection run, i.e. one "Apply to Dataset" invocation of a
 * custom model. Used to surface progress of inference jobs in the UI.
 */
export interface CustomModelDetectionRun {
  id: string;
  dataset_id: string | null;
  /** Human-readable dataset name if available, for display in the UI. */
  dataset_name: string | null;
  status: DetectionRunStatus;
  /** Annotations produced so far; updated on completion. */
  annotation_count: number;
  /** When the Celery worker started executing this run. */
  started_at: string | null;
  /** When the run finished (either completed or failed). */
  completed_at: string | null;
  /** Error details if status === 'failed'. */
  error_message: string | null;
  /** When the run was enqueued. */
  created_at: string;
}

/** Response listing recent detection runs for a custom model. */
export interface CustomModelDetectionRunListResponse {
  runs: CustomModelDetectionRun[];
  total: number;
}
