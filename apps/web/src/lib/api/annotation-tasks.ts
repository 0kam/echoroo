/**
 * Annotation Tasks API client for TanStack Query.
 */

import type {
  AnnotationTask,
  AnnotationTaskDetail,
  AnnotationTaskListResponse,
  AnnotationTaskUpdate,
  AnnotationTaskListParams,
  TaskCompletionResponse,
} from '$lib/types/annotation';
import { fetchWithErrorHandling, handleApiResponse } from './errors';

const API_BASE = '/api/v1';

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
  const response = await fetchWithErrorHandling(url, { credentials: 'include' });
  return handleApiResponse<AnnotationTaskListResponse>(response);
}

/**
 * Fetch a single annotation task by ID.
 */
export async function fetchAnnotationTask(
  projectId: string,
  annotationProjectId: string,
  taskId: string
): Promise<AnnotationTaskDetail> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/annotation-projects/${annotationProjectId}/tasks/${taskId}`,
    { credentials: 'include' }
  );
  return handleApiResponse<AnnotationTaskDetail>(response);
}

/**
 * Partially update an annotation task.
 */
export async function updateAnnotationTask(
  projectId: string,
  annotationProjectId: string,
  taskId: string,
  data: AnnotationTaskUpdate
): Promise<AnnotationTask> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/annotation-projects/${annotationProjectId}/tasks/${taskId}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(data),
    }
  );
  return handleApiResponse<AnnotationTask>(response);
}

/**
 * Mark an annotation task as completed.
 */
export async function completeAnnotationTask(
  projectId: string,
  annotationProjectId: string,
  taskId: string
): Promise<TaskCompletionResponse> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/annotation-projects/${annotationProjectId}/tasks/${taskId}/complete`,
    {
      method: 'POST',
      credentials: 'include',
    }
  );
  return handleApiResponse<TaskCompletionResponse>(response);
}

/**
 * Fetch the next available annotation task for the current user.
 * Returns null if there are no tasks remaining (204 No Content).
 */
export async function fetchNextAnnotationTask(
  projectId: string,
  annotationProjectId: string
): Promise<AnnotationTaskDetail | null> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/annotation-projects/${annotationProjectId}/tasks/next`,
    { credentials: 'include' }
  );
  if (response.status === 204) {
    return null;
  }
  return handleApiResponse<AnnotationTaskDetail>(response);
}
