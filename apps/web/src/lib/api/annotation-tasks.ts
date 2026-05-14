/**
 * Annotation Tasks API client for TanStack Query.
 */

import type {
  AnnotationTaskDetail,
  AnnotationTaskListResponse,
  AnnotationTaskListParams,
  TaskCompletionResponse,
} from '$lib/types/annotation';
import { apiClient } from './client';
import { ApiError } from './client';

const API_BASE = '/web-api/v1';

/**
 * Fetch a paginated list of annotation tasks for an annotation project.
 */
export async function fetchAnnotationTasks(
  projectId: string,
  annotationProjectId: string,
  params: AnnotationTaskListParams = {}
): Promise<AnnotationTaskListResponse> {
  const searchParams = new URLSearchParams();
  if (params.status) searchParams.set('status', params.status);
  if (params.assigned_to_id) searchParams.set('assigned_to_id', params.assigned_to_id);
  if (params.page) searchParams.set('page', params.page.toString());
  if (params.page_size) searchParams.set('page_size', params.page_size.toString());
  if (params.sort_by) searchParams.set('sort_by', params.sort_by);
  if (params.sort_order) searchParams.set('sort_order', params.sort_order);

  const url = `${API_BASE}/projects/${projectId}/annotation-projects/${annotationProjectId}/tasks?${searchParams}`;
  return apiClient.get<AnnotationTaskListResponse>(url);
}

/**
 * Fetch a single annotation task by ID.
 */
export async function fetchAnnotationTask(
  projectId: string,
  annotationProjectId: string,
  taskId: string
): Promise<AnnotationTaskDetail> {
  return apiClient.get<AnnotationTaskDetail>(
    `${API_BASE}/projects/${projectId}/annotation-projects/${annotationProjectId}/tasks/${taskId}`
  );
}

/**
 * Mark an annotation task as completed.
 */
export async function completeAnnotationTask(
  projectId: string,
  annotationProjectId: string,
  taskId: string
): Promise<TaskCompletionResponse> {
  return apiClient.post<TaskCompletionResponse>(
    `${API_BASE}/projects/${projectId}/annotation-projects/${annotationProjectId}/tasks/${taskId}/complete`
  );
}

/**
 * Fetch the next available annotation task for the current user.
 * Returns null if there are no tasks remaining (204 No Content).
 */
export async function fetchNextAnnotationTask(
  projectId: string,
  annotationProjectId: string
): Promise<AnnotationTaskDetail | null> {
  const response = await apiClient.requestRaw(
    `${API_BASE}/projects/${projectId}/annotation-projects/${annotationProjectId}/tasks/next`
  );
  if (response.status === 204) {
    return null;
  }
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: 'An error occurred' }));
    throw new ApiError(
      errorData.detail || 'Request failed',
      response.status,
      errorData.detail
    );
  }
  return response.json() as Promise<AnnotationTaskDetail>;
}
