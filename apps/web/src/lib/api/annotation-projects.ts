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

const API_BASE = '/web-api/v1';
const CSRF_COOKIE_NAME = 'echoroo_csrf';

function getCsrfToken(): string | null {
  if (typeof document === 'undefined') return null;
  const prefix = `${CSRF_COOKIE_NAME}=`;
  const parts = document.cookie ? document.cookie.split('; ') : [];
  for (const part of parts) {
    if (part.startsWith(prefix)) {
      try {
        return decodeURIComponent(part.slice(prefix.length));
      } catch {
        return part.slice(prefix.length);
      }
    }
  }
  return null;
}

function csrfHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const token = getCsrfToken();
  if (token) headers['X-CSRF-Token'] = token;
  return headers;
}

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
    data,
    { headers: csrfHeaders() }
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
    `${API_BASE}/projects/${projectId}/annotation-projects/${annotationProjectId}`,
    { headers: csrfHeaders() }
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
    `${API_BASE}/projects/${projectId}/annotation-projects/${annotationProjectId}/generate-tasks`,
    undefined,
    { headers: csrfHeaders() }
  );
}
