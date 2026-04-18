/**
 * Annotation Projects API client for TanStack Query.
 */

import type {
  AnnotationProjectCreate,
  AnnotationProjectDetail,
  AnnotationProjectListParams,
  AnnotationProjectListResponse,
  TaskGenerationResponse,
} from '$lib/types/annotation';
import { apiClient } from './client';

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
  return apiClient.get<AnnotationProjectListResponse>(url);
}

/**
 * Fetch a single annotation project by ID.
 */
export async function fetchAnnotationProject(
  projectId: string,
  annotationProjectId: string
): Promise<AnnotationProjectDetail> {
  return apiClient.get<AnnotationProjectDetail>(
    `${API_BASE}/projects/${projectId}/annotation-projects/${annotationProjectId}`
  );
}

/**
 * Create a new annotation project.
 */
export async function createAnnotationProject(
  projectId: string,
  data: AnnotationProjectCreate
): Promise<AnnotationProjectDetail> {
  return apiClient.post<AnnotationProjectDetail>(
    `${API_BASE}/projects/${projectId}/annotation-projects`,
    data
  );
}

/**
 * Delete an annotation project.
 */
export async function deleteAnnotationProject(
  projectId: string,
  annotationProjectId: string
): Promise<void> {
  return apiClient.delete<void>(
    `${API_BASE}/projects/${projectId}/annotation-projects/${annotationProjectId}`
  );
}

/**
 * Trigger background task generation for an annotation project.
 */
export async function generateTasks(
  projectId: string,
  annotationProjectId: string
): Promise<TaskGenerationResponse> {
  return apiClient.post<TaskGenerationResponse>(
    `${API_BASE}/projects/${projectId}/annotation-projects/${annotationProjectId}/generate-tasks`
  );
}
