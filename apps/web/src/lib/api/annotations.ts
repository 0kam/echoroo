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
import { apiClient } from './client';

const API_BASE = '/api/v1';

/**
 * Get or create the clip annotation associated with an annotation task.
 */
export async function getOrCreateClipAnnotation(
  projectId: string,
  taskId: string
): Promise<ClipAnnotationDetail> {
  return apiClient.get<ClipAnnotationDetail>(
    `${API_BASE}/projects/${projectId}/annotation-tasks/${taskId}/clip-annotation`
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
    `${API_BASE}/projects/${projectId}/clip-annotations/${clipAnnotationId}/tags`,
    body
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
    `${API_BASE}/projects/${projectId}/clip-annotations/${clipAnnotationId}/tags/${tagId}`
  );
}

/**
 * List all sound event annotations for a clip annotation.
 */
export async function listSoundEvents(
  projectId: string,
  clipAnnotationId: string
): Promise<SoundEventAnnotation[]> {
  return apiClient.get<SoundEventAnnotation[]>(
    `${API_BASE}/projects/${projectId}/clip-annotations/${clipAnnotationId}/sound-events`
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
    `${API_BASE}/projects/${projectId}/clip-annotations/${clipAnnotationId}/sound-events`,
    data
  );
}

/**
 * Partially update a sound event annotation.
 */
export async function updateSoundEvent(
  projectId: string,
  soundEventId: string,
  data: SoundEventAnnotationUpdate
): Promise<SoundEventAnnotation> {
  return apiClient.patch<SoundEventAnnotation>(
    `${API_BASE}/projects/${projectId}/sound-events/${soundEventId}`,
    data
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
    `${API_BASE}/projects/${projectId}/sound-events/${soundEventId}`
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
    `${API_BASE}/projects/${projectId}/sound-events/${soundEventId}/tags`,
    body
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
    `${API_BASE}/projects/${projectId}/sound-events/${soundEventId}/tags/${tagId}`
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
    `${API_BASE}/projects/${projectId}/clip-annotations/${clipAnnotationId}/review`,
    { status, comment }
  );
}

/**
 * Add a note to a clip annotation.
 */
export async function addNote(
  projectId: string,
  clipAnnotationId: string,
  data: NoteCreate
): Promise<Note> {
  return apiClient.post<Note>(
    `${API_BASE}/projects/${projectId}/clip-annotations/${clipAnnotationId}/notes`,
    data
  );
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
  return apiClient.post<{ updated_count: number; clip_annotations: ClipAnnotationDetail[] }>(
    `${API_BASE}/projects/${projectId}/clip-annotations/batch-tag`,
    { task_ids: taskIds, tag_id: tagId }
  );
}
