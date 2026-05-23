/**
 * Clip Annotations and Sound Event Annotations API client for TanStack Query.
 *
 * Spec/009 PR 2.5: moved off legacy ``/api/v1`` Bearer surface onto the
 * first-party Cookie + CSRF BFF (`/web-api/v1`). The mutation helpers
 * attach the CSRF header via ``csrfHeaders()`` (read from
 * ``echoroo_csrf`` cookie); the GET helper omits it because the BFF
 * exempts GETs from CSRF.
 */

import type {
  ClipAnnotationDetail,
  SoundEventAnnotation,
  SoundEventAnnotationCreate,
  AddTagRequest,
} from '$lib/types/annotation';
import { apiClient } from './client';

const WEB_API_BASE = '/web-api/v1';
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
 * Get or create the clip annotation associated with an annotation task.
 */
export async function getOrCreateClipAnnotation(
  projectId: string,
  taskId: string
): Promise<ClipAnnotationDetail> {
  return apiClient.get<ClipAnnotationDetail>(
    `${WEB_API_BASE}/projects/${projectId}/annotation-tasks/${taskId}/clip-annotation`
  );
}

/**
 * Add a tag to a clip annotation.
 */
export async function addClipTag(
  projectId: string,
  clipAnnotationId: string,
  tagId: string
): Promise<ClipAnnotationDetail> {
  const body: AddTagRequest = { tag_id: tagId };
  return apiClient.post<ClipAnnotationDetail>(
    `${WEB_API_BASE}/projects/${projectId}/clip-annotations/${clipAnnotationId}/tags`,
    body,
    { headers: csrfHeaders() }
  );
}

/**
 * Remove a tag from a clip annotation.
 */
export async function removeClipTag(
  projectId: string,
  clipAnnotationId: string,
  tagId: string
): Promise<void> {
  return apiClient.delete<void>(
    `${WEB_API_BASE}/projects/${projectId}/clip-annotations/${clipAnnotationId}/tags/${tagId}`,
    { headers: csrfHeaders() }
  );
}

/**
 * Create a new sound event annotation within a clip annotation.
 */
export async function createSoundEvent(
  projectId: string,
  clipAnnotationId: string,
  data: SoundEventAnnotationCreate
): Promise<SoundEventAnnotation> {
  return apiClient.post<SoundEventAnnotation>(
    `${WEB_API_BASE}/projects/${projectId}/clip-annotations/${clipAnnotationId}/sound-events`,
    data,
    { headers: csrfHeaders() }
  );
}

/**
 * Delete a sound event annotation.
 */
export async function deleteSoundEvent(
  projectId: string,
  soundEventId: string
): Promise<void> {
  return apiClient.delete<void>(
    `${WEB_API_BASE}/projects/${projectId}/sound-events/${soundEventId}`,
    { headers: csrfHeaders() }
  );
}

/**
 * Add a tag to a sound event annotation.
 */
export async function addSoundEventTag(
  projectId: string,
  soundEventId: string,
  tagId: string
): Promise<SoundEventAnnotation> {
  const body: AddTagRequest = { tag_id: tagId };
  return apiClient.post<SoundEventAnnotation>(
    `${WEB_API_BASE}/projects/${projectId}/sound-events/${soundEventId}/tags`,
    body,
    { headers: csrfHeaders() }
  );
}

/**
 * Remove a tag from a sound event annotation.
 */
export async function removeSoundEventTag(
  projectId: string,
  soundEventId: string,
  tagId: string
): Promise<void> {
  return apiClient.delete<void>(
    `${WEB_API_BASE}/projects/${projectId}/sound-events/${soundEventId}/tags/${tagId}`,
    { headers: csrfHeaders() }
  );
}

/**
 * Submit a review decision (approve or reject) on a clip annotation.
 */
export async function reviewClipAnnotation(
  projectId: string,
  clipAnnotationId: string,
  status: 'approved' | 'rejected',
  comment?: string
): Promise<ClipAnnotationDetail> {
  return apiClient.post<ClipAnnotationDetail>(
    `${WEB_API_BASE}/projects/${projectId}/clip-annotations/${clipAnnotationId}/review`,
    { status, comment },
    { headers: csrfHeaders() }
  );
}
