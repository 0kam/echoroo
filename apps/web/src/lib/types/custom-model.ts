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
 * A single item in the blind audit set.
 */
export interface AuditSetItem {
  id: string;
  embedding_id: string;
  recording_id: string;
  predicted_proba: number | null;
  annotation_id: string;
  /** Review status from annotation: 'confirmed' | 'rejected' | 'unreviewed' | null */
  review_status: string | null;
  start_time: number | null;
  end_time: number | null;
  created_at: string;
}

/**
 * Paginated list response for audit set items.
 */
export interface AuditSetListResponse {
  items: AuditSetItem[];
  total: number;
}

/**
 * Classification metrics computed from human-reviewed audit set items.
 * Used to independently validate model performance on held-out, unseen data.
 */
export interface AuditMetrics {
  accuracy: number;
  precision: number;
  recall: number;
  f1: number;
  roc_auc: number | null;
  pr_auc: number | null;
  confusion_matrix: [[number, number], [number, number]];
  n_audited: number;
  n_total: number;
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
  /** Metrics computed from human-reviewed blind audit set items, if evaluated. */
  audit_metrics: AuditMetrics | null;
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
  start_time: number | null;
  end_time: number | null;
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
  items: SamplingRoundItem[];
}

/**
 * Paginated list response for sampling rounds.
 */
export interface SamplingRoundListResponse {
  rounds: SamplingRound[];
  total: number;
}
