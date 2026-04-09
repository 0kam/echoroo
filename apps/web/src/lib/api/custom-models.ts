/**
 * Custom SVM classifier models API client.
 *
 * Provides functions for creating, training, and managing custom
 * species classifiers trained on labeled similarity search data.
 */

import type {
  AuditMetrics,
  AuditSetListResponse,
  CustomModel,
  CustomModelCreate,
  CustomModelListResponse,
  CustomModelTrainRequest,
  SamplingRound,
  SamplingRoundListResponse,
} from '$lib/types/custom-model';
import { apiClient } from './client';

const API_BASE = '/api/v1';

/**
 * Fetch all custom models for a project.
 *
 * @param projectId - Project UUID
 * @param params - Optional pagination parameters
 * @returns Paginated list of custom models
 */
export async function fetchCustomModels(
  projectId: string,
  params?: { limit?: number; offset?: number }
): Promise<CustomModelListResponse> {
  const qs = new URLSearchParams();
  if (params?.limit !== undefined) qs.set('limit', String(params.limit));
  if (params?.offset !== undefined) qs.set('offset', String(params.offset));
  const queryString = qs.toString() ? `?${qs.toString()}` : '';

  return apiClient.get<CustomModelListResponse>(
    `${API_BASE}/projects/${projectId}/custom-models${queryString}`
  );
}

/**
 * Create a new custom model.
 *
 * @param projectId - Project UUID
 * @param data - Model creation parameters including name and training sessions
 * @returns The newly created model
 */
export async function createCustomModel(
  projectId: string,
  data: CustomModelCreate
): Promise<CustomModel> {
  return apiClient.post<CustomModel>(`${API_BASE}/projects/${projectId}/custom-models`, data);
}

/**
 * Fetch a single custom model by ID.
 *
 * @param projectId - Project UUID
 * @param modelId - Custom model UUID
 * @returns Full model details including metrics if trained
 */
export async function getCustomModel(projectId: string, modelId: string): Promise<CustomModel> {
  return apiClient.get<CustomModel>(
    `${API_BASE}/projects/${projectId}/custom-models/${modelId}`
  );
}

/**
 * Trigger training for a custom model.
 *
 * Submits a Celery task to train the SVM classifier using the model's
 * configured training sessions and labeled annotations.
 *
 * @param projectId - Project UUID
 * @param modelId - Custom model UUID
 * @param params - Optional training parameters (use_unlabeled, max_unlabeled_samples)
 * @returns Updated model with status set to 'training'
 */
export async function trainCustomModel(
  projectId: string,
  modelId: string,
  params?: CustomModelTrainRequest
): Promise<CustomModel> {
  return apiClient.post<CustomModel>(
    `${API_BASE}/projects/${projectId}/custom-models/${modelId}/train`,
    params ?? {}
  );
}

/**
 * Delete a custom model.
 *
 * @param projectId - Project UUID
 * @param modelId - Custom model UUID to delete
 */
export async function deleteCustomModel(projectId: string, modelId: string): Promise<void> {
  return apiClient.delete<void>(
    `${API_BASE}/projects/${projectId}/custom-models/${modelId}`
  );
}

/**
 * Poll the current status of a custom model.
 *
 * Intended for use in a polling loop while a model is training.
 * Returns the full model including metrics once training completes.
 *
 * @param projectId - Project UUID
 * @param modelId - Custom model UUID
 * @returns Current model state with status and optional metrics
 */
export async function getCustomModelStatus(
  projectId: string,
  modelId: string
): Promise<CustomModel> {
  return getCustomModel(projectId, modelId);
}

// ============================================================
// Sampling rounds API
// ============================================================

/**
 * Generate a new seed-sampling round for a custom model.
 *
 * Triggers the backend to run the three-category sampling algorithm
 * (easy positives, boundary, others) using the given reference embeddings.
 *
 * @param projectId - Project UUID
 * @param modelId - Custom model UUID
 * @param referenceEmbeddingIds - IDs of the reference embeddings to sample around
 * @param config - Optional tuning parameters for the sampling algorithm
 * @returns The newly created SamplingRound (status will be 'pending' initially)
 */
export async function generateSeedSamples(
  projectId: string,
  modelId: string,
  referenceEmbeddingIds: string[],
  config?: {
    easy_positive_k?: number;
    boundary_n?: number;
    boundary_m?: number;
    others_p?: number;
  }
): Promise<SamplingRound> {
  return apiClient.post<SamplingRound>(
    `${API_BASE}/projects/${projectId}/custom-models/${modelId}/seed-samples`,
    {
      reference_embedding_ids: referenceEmbeddingIds,
      config: config ?? null,
    }
  );
}

/**
 * Fetch all sampling rounds for a custom model.
 *
 * @param projectId - Project UUID
 * @param modelId - Custom model UUID
 * @returns Paginated list of sampling rounds (most recent first)
 */
export async function getSamplingRounds(
  projectId: string,
  modelId: string
): Promise<SamplingRoundListResponse> {
  return apiClient.get<SamplingRoundListResponse>(
    `${API_BASE}/projects/${projectId}/custom-models/${modelId}/sampling-rounds`
  );
}

/**
 * Fetch a single sampling round including its items.
 *
 * @param projectId - Project UUID
 * @param modelId - Custom model UUID
 * @param roundId - Sampling round UUID
 * @returns Full SamplingRound with items array populated
 */
export async function getSamplingRound(
  projectId: string,
  modelId: string,
  roundId: string
): Promise<SamplingRound> {
  return apiClient.get<SamplingRound>(
    `${API_BASE}/projects/${projectId}/custom-models/${modelId}/sampling-rounds/${roundId}`
  );
}

/**
 * Trigger active-learning sample suggestion for a custom model.
 *
 * Asks the backend to pick the most uncertain samples from the embedding
 * space (those closest to the current decision boundary) and returns a
 * new SamplingRound of type 'active_learning'.
 *
 * @param projectId - Project UUID
 * @param modelId - Custom model UUID (must have been trained at least once)
 * @returns The newly created SamplingRound (status will be 'pending' initially)
 */
export async function suggestNextSamples(
  projectId: string,
  modelId: string
): Promise<SamplingRound> {
  return apiClient.post<SamplingRound>(
    `${API_BASE}/projects/${projectId}/custom-models/${modelId}/suggest-samples`,
    {}
  );
}

/**
 * Apply a trained custom model to all recordings in a dataset.
 *
 * Submits a Celery task that runs the model over every recording in the
 * specified dataset and stores the results as detection runs.
 *
 * @param projectId - Project UUID
 * @param modelId - Custom model UUID (must be in 'trained' or 'deployed' status)
 * @param datasetId - Dataset UUID to run inference on
 * @param threshold - Confidence threshold (0–1, default 0.5)
 * @returns Object containing the created detection_run_id
 */
export async function applyCustomModel(
  projectId: string,
  modelId: string,
  datasetId: string,
  threshold: number = 0.5
): Promise<{ detection_run_id: string }> {
  return apiClient.post<{ detection_run_id: string }>(
    `${API_BASE}/projects/${projectId}/custom-models/${modelId}/apply?dataset_id=${datasetId}&threshold=${threshold}`
  );
}

// ============================================================
// Audit set API
// ============================================================

/**
 * Dispatch async task to generate a score-stratified blind audit set.
 *
 * Only valid for TRAINED models with an artifact. Returns 202 immediately;
 * poll GET /audit-set to check for items once the task completes.
 *
 * @param projectId - Project UUID
 * @param modelId - Custom model UUID (must be TRAINED)
 * @returns Status object confirming the task was dispatched
 */
export async function generateAuditSet(
  projectId: string,
  modelId: string
): Promise<{ status: string }> {
  return apiClient.post<{ status: string }>(
    `${API_BASE}/projects/${projectId}/custom-models/${modelId}/audit-set`,
    {}
  );
}

/**
 * Fetch all audit set items for a custom model.
 *
 * Items are ordered by predicted_proba descending. Each item includes
 * embedding metadata and the current annotation review_status.
 *
 * @param projectId - Project UUID
 * @param modelId - Custom model UUID
 * @returns List of audit set items with review status
 */
export async function getAuditSet(
  projectId: string,
  modelId: string
): Promise<AuditSetListResponse> {
  return apiClient.get<AuditSetListResponse>(
    `${API_BASE}/projects/${projectId}/custom-models/${modelId}/audit-set`
  );
}

/**
 * Evaluate the audit set and compute blind audit metrics.
 *
 * Collects all reviewed (confirmed/rejected) audit items, computes
 * classification metrics, and persists them as model.audit_metrics.
 * Requires at least 2 reviewed items.
 *
 * @param projectId - Project UUID
 * @param modelId - Custom model UUID
 * @returns Computed audit metrics
 */
export async function evaluateAuditSet(
  projectId: string,
  modelId: string
): Promise<AuditMetrics> {
  const res = await apiClient.post<{ model_id: string; audit_metrics: AuditMetrics }>(
    `${API_BASE}/projects/${projectId}/custom-models/${modelId}/audit-set/evaluate`,
    {}
  );
  return res.audit_metrics;
}
