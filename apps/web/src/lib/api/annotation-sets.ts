/**
 * Annotation-Set API client.
 *
 * Thin wrappers over the backend endpoints defined by the OpenAPI contracts
 * under `specs/003-annotation/contracts/`. Designed for consumption via
 * TanStack Query (createQuery / createMutation) — each function returns a
 * plain Promise and accepts only serialisable arguments.
 *
 * Terminology: the public API (and therefore these clients) uses
 * `species_id`. The backend maps that to `taxon_id` internally.
 */

import type {
  AnnotationNote,
  AnnotationNoteCreate,
  AnnotationSegmentDetail,
  AnnotationSegmentListResponse,
  AnnotationSegmentUpdate,
  AnnotationSetCreate,
  AnnotationSetDetail,
  AnnotationSetListResponse,
  AnnotationSetStatus,
  AnnotationSetUpdate,
  EvaluationDispatchRequest,
  EvaluationRunListResponse,
  EvaluationRunResponse,
  EvaluationSummary,
  ListSegmentsParams,
  PaletteEntry,
  PaletteEntryCreate,
  TimeRangeAnnotation,
  TimeRangeAnnotationCreate,
  TimeRangeAnnotationUpdate,
} from '$lib/types/annotation-set';
import { apiClient } from './client';

const API_BASE = '/api/v1';

// ============================================================
// AnnotationSet
// ============================================================

/**
 * List annotation sets for a project.
 *
 * @param params - Must include `project_id`; optional dataset/status filters
 *                 and pagination.
 */
export async function listAnnotationSets(params: {
  project_id: string;
  dataset_id?: string;
  status?: AnnotationSetStatus;
  page?: number;
  page_size?: number;
}): Promise<AnnotationSetListResponse> {
  const qs = new URLSearchParams();
  qs.set('project_id', params.project_id);
  if (params.dataset_id) qs.set('dataset_id', params.dataset_id);
  if (params.status) qs.set('status', params.status);
  if (params.page !== undefined) qs.set('page', String(params.page));
  if (params.page_size !== undefined) qs.set('page_size', String(params.page_size));
  return apiClient.get<AnnotationSetListResponse>(
    `${API_BASE}/annotation-sets?${qs.toString()}`,
  );
}

/** Fetch a single annotation set with palette + progress. */
export async function getAnnotationSet(id: string): Promise<AnnotationSetDetail> {
  return apiClient.get<AnnotationSetDetail>(`${API_BASE}/annotation-sets/${id}`);
}

/** Create a new annotation set (status starts as `sampling`). */
export async function createAnnotationSet(
  body: AnnotationSetCreate,
): Promise<AnnotationSetDetail> {
  return apiClient.post<AnnotationSetDetail>(`${API_BASE}/annotation-sets`, body);
}

/** Rename an annotation set (only `name` is mutable after sampling). */
export async function updateAnnotationSet(
  id: string,
  body: AnnotationSetUpdate,
): Promise<AnnotationSetDetail> {
  return apiClient.patch<AnnotationSetDetail>(
    `${API_BASE}/annotation-sets/${id}`,
    body,
  );
}

/** Delete an annotation set (cascades to segments / annotations). */
export async function deleteAnnotationSet(id: string): Promise<void> {
  return apiClient.delete<void>(`${API_BASE}/annotation-sets/${id}`);
}

// ============================================================
// Palette
// ============================================================

/** Add a species to the palette of an annotation set. */
export async function addPalette(
  setId: string,
  body: PaletteEntryCreate,
): Promise<PaletteEntry> {
  return apiClient.post<PaletteEntry>(
    `${API_BASE}/annotation-sets/${setId}/palette`,
    body,
  );
}

/** Remove a species from the palette (existing annotations are preserved). */
export async function removePalette(setId: string, speciesId: string): Promise<void> {
  return apiClient.delete<void>(
    `${API_BASE}/annotation-sets/${setId}/palette/${speciesId}`,
  );
}

// ============================================================
// Segments
// ============================================================

/** List segments within a set (filter by status / is_empty). */
export async function listSegments(
  setId: string,
  params: ListSegmentsParams = {},
): Promise<AnnotationSegmentListResponse> {
  const qs = new URLSearchParams();
  if (params.status) qs.set('status', params.status);
  if (params.is_empty !== undefined) qs.set('is_empty', String(params.is_empty));
  if (params.page !== undefined) qs.set('page', String(params.page));
  if (params.page_size !== undefined) qs.set('page_size', String(params.page_size));
  const query = qs.toString() ? `?${qs.toString()}` : '';
  return apiClient.get<AnnotationSegmentListResponse>(
    `${API_BASE}/annotation-sets/${setId}/segments${query}`,
  );
}

/** Fetch full segment detail including annotations and notes. */
export async function getSegment(id: string): Promise<AnnotationSegmentDetail> {
  return apiClient.get<AnnotationSegmentDetail>(`${API_BASE}/segments/${id}`);
}

/** Update segment state (status, is_empty). */
export async function updateSegment(
  id: string,
  body: AnnotationSegmentUpdate,
): Promise<AnnotationSegmentDetail> {
  return apiClient.patch<AnnotationSegmentDetail>(
    `${API_BASE}/segments/${id}`,
    body,
  );
}

// ============================================================
// TimeRangeAnnotation
// ============================================================

/**
 * Create a TimeRangeAnnotation on a segment.
 * Side effect: segment.is_empty is forced to false on success.
 */
export async function createAnnotation(
  segmentId: string,
  body: TimeRangeAnnotationCreate,
): Promise<TimeRangeAnnotation> {
  return apiClient.post<TimeRangeAnnotation>(
    `${API_BASE}/segments/${segmentId}/annotations`,
    body,
  );
}

/** Update an existing TimeRangeAnnotation. */
export async function updateAnnotation(
  id: string,
  body: TimeRangeAnnotationUpdate,
): Promise<TimeRangeAnnotation> {
  return apiClient.patch<TimeRangeAnnotation>(
    `${API_BASE}/annotations/${id}`,
    body,
  );
}

/** Delete a TimeRangeAnnotation (parent segment.is_empty may flip). */
export async function deleteAnnotation(id: string): Promise<void> {
  return apiClient.delete<void>(`${API_BASE}/annotations/${id}`);
}

// ============================================================
// Notes
// ============================================================

/** Attach a note to a segment. */
export async function createSegmentNote(
  segmentId: string,
  body: AnnotationNoteCreate,
): Promise<AnnotationNote> {
  return apiClient.post<AnnotationNote>(
    `${API_BASE}/segments/${segmentId}/notes`,
    body,
  );
}

/** Attach a note to a TimeRangeAnnotation. */
export async function createAnnotationNote(
  annotationId: string,
  body: AnnotationNoteCreate,
): Promise<AnnotationNote> {
  return apiClient.post<AnnotationNote>(
    `${API_BASE}/annotations/${annotationId}/notes`,
    body,
  );
}

// ============================================================
// Evaluation
// ============================================================

/** Dispatch a cross-model evaluation run for a set. */
export async function evaluateAnnotationSet(
  setId: string,
  body: EvaluationDispatchRequest,
): Promise<EvaluationRunResponse> {
  return apiClient.post<EvaluationRunResponse>(
    `${API_BASE}/annotation-sets/${setId}/evaluate`,
    body,
  );
}

/**
 * List evaluation runs for a set (most recent first).
 *
 * @param setId - AnnotationSet UUID
 * @param params - Optional pagination (limit/offset)
 */
export async function listEvaluationRuns(
  setId: string,
  params?: { limit?: number; offset?: number },
): Promise<EvaluationRunListResponse> {
  const qs = new URLSearchParams();
  if (params?.limit !== undefined) qs.set('limit', String(params.limit));
  if (params?.offset !== undefined) qs.set('offset', String(params.offset));
  const query = qs.toString() ? `?${qs.toString()}` : '';
  return apiClient.get<EvaluationRunListResponse>(
    `${API_BASE}/annotation-sets/${setId}/evaluation-runs${query}`,
  );
}

/** Get grouped-by-model summary for an evaluation run. */
export async function getEvaluationRun(id: string): Promise<EvaluationSummary> {
  return apiClient.get<EvaluationSummary>(`${API_BASE}/evaluation-runs/${id}`);
}

/** Delete an evaluation run (cascades to results). */
export async function deleteEvaluationRun(id: string): Promise<void> {
  return apiClient.delete<void>(`${API_BASE}/evaluation-runs/${id}`);
}
