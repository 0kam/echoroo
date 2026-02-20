/**
 * Annotation Projects API client for TanStack Query.
 */

import type {
  AnnotationProjectCreate,
  AnnotationProjectDetail,
  AnnotationProjectListParams,
  AnnotationProjectListResponse,
  AnnotationProjectUpdate,
  TaskGenerationResponse,
} from '$lib/types/annotation';
import { fetchWithErrorHandling, handleApiResponse } from './errors';

const API_BASE = '/api/v1';

/**
 * Fetch annotation projects for a project.
 */
export async function fetchAnnotationProjects(
  projectId: string,
  params: AnnotationProjectListParams = {}
): Promise<AnnotationProjectListResponse> {
  const searchParams = new URLSearchParams();
  if (params.page) searchParams.set('page', params.page.toString());
  if (params.page_size) searchParams.set('page_size', params.page_size.toString());

  const url = `${API_BASE}/projects/${projectId}/annotation-projects?${searchParams}`;
  const response = await fetchWithErrorHandling(url, { credentials: 'include' });
  return handleApiResponse<AnnotationProjectListResponse>(response);
}

/**
 * Fetch a single annotation project by ID.
 */
export async function fetchAnnotationProject(
  projectId: string,
  annotationProjectId: string
): Promise<AnnotationProjectDetail> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/annotation-projects/${annotationProjectId}`,
    { credentials: 'include' }
  );
  return handleApiResponse<AnnotationProjectDetail>(response);
}

/**
 * Create a new annotation project.
 */
export async function createAnnotationProject(
  projectId: string,
  data: AnnotationProjectCreate
): Promise<AnnotationProjectDetail> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/annotation-projects`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(data),
    }
  );
  return handleApiResponse<AnnotationProjectDetail>(response);
}

/**
 * Update an annotation project.
 */
export async function updateAnnotationProject(
  projectId: string,
  annotationProjectId: string,
  data: AnnotationProjectUpdate
): Promise<AnnotationProjectDetail> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/annotation-projects/${annotationProjectId}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(data),
    }
  );
  return handleApiResponse<AnnotationProjectDetail>(response);
}

/**
 * Delete an annotation project.
 */
export async function deleteAnnotationProject(
  projectId: string,
  annotationProjectId: string
): Promise<void> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/annotation-projects/${annotationProjectId}`,
    {
      method: 'DELETE',
      credentials: 'include',
    }
  );

  if (!response.ok) {
    await handleApiResponse(response);
  }
}

/**
 * Trigger background task generation for an annotation project.
 */
export async function generateTasks(
  projectId: string,
  annotationProjectId: string
): Promise<TaskGenerationResponse> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/annotation-projects/${annotationProjectId}/generate-tasks`,
    {
      method: 'POST',
      credentials: 'include',
    }
  );
  return handleApiResponse<TaskGenerationResponse>(response);
}
