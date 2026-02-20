/**
 * Clip Annotations and Sound Event Annotations API client for TanStack Query.
 */

import type {
  ClipAnnotationDetail,
  SoundEventAnnotation,
  SoundEventAnnotationCreate,
  SoundEventAnnotationUpdate,
  Note,
  NoteCreate,
  AddTagRequest,
} from '$lib/types/annotation';
import { fetchWithErrorHandling, handleApiResponse } from './errors';

const API_BASE = '/api/v1';

/**
 * Get or create the clip annotation associated with an annotation task.
 */
export async function getOrCreateClipAnnotation(
  projectId: string,
  taskId: string
): Promise<ClipAnnotationDetail> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/annotation-tasks/${taskId}/clip-annotation`,
    { credentials: 'include' }
  );
  return handleApiResponse<ClipAnnotationDetail>(response);
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
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/clip-annotations/${clipAnnotationId}/tags`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(body),
    }
  );
  return handleApiResponse<ClipAnnotationDetail>(response);
}

/**
 * Remove a tag from a clip annotation.
 */
export async function removeClipTag(
  projectId: string,
  clipAnnotationId: string,
  tagId: string
): Promise<void> {
  const body: AddTagRequest = { tag_id: tagId };
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/clip-annotations/${clipAnnotationId}/tags`,
    {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(body),
    }
  );
  if (response.ok) {
    return;
  }
  await handleApiResponse(response);
}

/**
 * List all sound event annotations for a clip annotation.
 */
export async function listSoundEvents(
  projectId: string,
  clipAnnotationId: string
): Promise<SoundEventAnnotation[]> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/clip-annotations/${clipAnnotationId}/sound-events`,
    { credentials: 'include' }
  );
  return handleApiResponse<SoundEventAnnotation[]>(response);
}

/**
 * Create a new sound event annotation within a clip annotation.
 */
export async function createSoundEvent(
  projectId: string,
  clipAnnotationId: string,
  data: SoundEventAnnotationCreate
): Promise<SoundEventAnnotation> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/clip-annotations/${clipAnnotationId}/sound-events`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(data),
    }
  );
  return handleApiResponse<SoundEventAnnotation>(response);
}

/**
 * Partially update a sound event annotation.
 */
export async function updateSoundEvent(
  projectId: string,
  soundEventId: string,
  data: SoundEventAnnotationUpdate
): Promise<SoundEventAnnotation> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/sound-events/${soundEventId}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(data),
    }
  );
  return handleApiResponse<SoundEventAnnotation>(response);
}

/**
 * Delete a sound event annotation.
 */
export async function deleteSoundEvent(
  projectId: string,
  soundEventId: string
): Promise<void> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/sound-events/${soundEventId}`,
    {
      method: 'DELETE',
      credentials: 'include',
    }
  );
  if (response.ok) {
    return;
  }
  await handleApiResponse(response);
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
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/sound-events/${soundEventId}/tags`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(body),
    }
  );
  return handleApiResponse<SoundEventAnnotation>(response);
}

/**
 * Remove a tag from a sound event annotation.
 */
export async function removeSoundEventTag(
  projectId: string,
  soundEventId: string,
  tagId: string
): Promise<void> {
  const body: AddTagRequest = { tag_id: tagId };
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/sound-events/${soundEventId}/tags`,
    {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(body),
    }
  );
  if (response.ok) {
    return;
  }
  await handleApiResponse(response);
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
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/clip-annotations/${clipAnnotationId}/review`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ status, comment }),
    }
  );
  return handleApiResponse<ClipAnnotationDetail>(response);
}

/**
 * Add a note to a clip annotation.
 */
export async function addNote(
  projectId: string,
  clipAnnotationId: string,
  data: NoteCreate
): Promise<Note> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/clip-annotations/${clipAnnotationId}/notes`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(data),
    }
  );
  return handleApiResponse<Note>(response);
}

/**
 * Apply a tag to multiple clip annotations in a single batch request.
 * Accepts a list of annotation task IDs; the backend resolves the
 * corresponding clip annotations and attaches the specified tag.
 */
export async function batchTagClips(
  projectId: string,
  taskIds: string[],
  tagId: string
): Promise<{ updated_count: number; clip_annotations: ClipAnnotationDetail[] }> {
  const response = await fetchWithErrorHandling(
    `${API_BASE}/projects/${projectId}/clip-annotations/batch-tag`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ task_ids: taskIds, tag_id: tagId }),
    }
  );
  return handleApiResponse<{ updated_count: number; clip_annotations: ClipAnnotationDetail[] }>(
    response
  );
}
