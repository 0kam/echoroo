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
 * Trained model performance metrics.
 */
export interface CustomModelMetrics {
  accuracy: number;
  precision: number;
  recall: number;
  f1: number;
  auc_roc: number;
  pr_auc: number;
  best_c: number;
  confusion_matrix: {
    tn: number;
    fp: number;
    fn: number;
    tp: number;
  };
}

/**
 * Statistics collected during the training run.
 */
export interface CustomModelTrainingStats {
  positive_count: number;
  negative_count: number;
  unlabeled_count: number;
  training_duration_seconds: number;
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
  training_session_ids: string[] | null;
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
  target_tag_id?: string;
  training_session_ids: string[];
  embedding_model_name?: string;
}

/**
 * Request body for triggering model training.
 */
export interface CustomModelTrainRequest {
  use_unlabeled?: boolean;
  max_unlabeled_samples?: number;
}
