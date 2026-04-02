/**
 * Custom SVM classifier models API client.
 *
 * Provides functions for creating, training, and managing custom
 * species classifiers trained on labeled similarity search data.
 */

import type {
  CustomModel,
  CustomModelCreate,
  CustomModelListResponse,
  CustomModelTrainRequest,
} from '$lib/types/custom-model';
import { fetchWithErrorHandling, handleApiResponse } from './errors';

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

  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/custom-models${queryString}`,
    { credentials: 'include' }
  );
  return handleApiResponse<CustomModelListResponse>(response);
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
  const response = await fetchWithErrorHandling(`${API_BASE}/projects/${projectId}/custom-models`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(data),
  });
  return handleApiResponse<CustomModel>(response);
}

/**
 * Fetch a single custom model by ID.
 *
 * @param projectId - Project UUID
 * @param modelId - Custom model UUID
 * @returns Full model details including metrics if trained
 */
export async function getCustomModel(projectId: string, modelId: string): Promise<CustomModel> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/custom-models/${modelId}`,
    { credentials: 'include' }
  );
  return handleApiResponse<CustomModel>(response);
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
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/custom-models/${modelId}/train`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(params ?? {}),
    }
  );
  return handleApiResponse<CustomModel>(response);
}

/**
 * Delete a custom model.
 *
 * @param projectId - Project UUID
 * @param modelId - Custom model UUID to delete
 */
export async function deleteCustomModel(projectId: string, modelId: string): Promise<void> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/custom-models/${modelId}`,
    {
      method: 'DELETE',
      credentials: 'include',
    }
  );
  await handleApiResponse<unknown>(response);
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
