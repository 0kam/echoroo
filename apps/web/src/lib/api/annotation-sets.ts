/**
 * Annotation-Set API client.
 *
 * spec/009 PR 4: all annotation-set, segment, time-range-annotation,
 * and evaluation-run calls go through ``/web-api/v1`` (cookie + CSRF
 * session boundary). Mutations attach ``X-CSRF-Token`` via the inline
 * helper below.
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
  if (params.dataset_id) qs.set('dataset_id', params.dataset_id);
  if (params.status) qs.set('status', params.status);
  if (params.page !== undefined) qs.set('page', String(params.page));
  if (params.page_size !== undefined) qs.set('page_size', String(params.page_size));
  const query = qs.toString() ? `?${qs.toString()}` : '';
  return apiClient.get<AnnotationSetListResponse>(
    `${WEB_API_BASE}/projects/${params.project_id}/annotation-sets${query}`,
  );
}

/**
 * Fetch a single annotation set with palette + progress.
 *
 * @param locale - BCP 47 locale code so the backend resolves each
 *   `palette[].common_name` for that locale (e.g. 和名 on /ja).
 */
export async function getAnnotationSet(
  projectId: string,
  id: string,
  locale?: string,
): Promise<AnnotationSetDetail> {
  const qs = locale ? `?${new URLSearchParams({ locale }).toString()}` : '';
  return apiClient.get<AnnotationSetDetail>(
    `${WEB_API_BASE}/projects/${projectId}/annotation-sets/${id}${qs}`,
  );
}

/** Create a new annotation set (status starts as `sampling`). */
export async function createAnnotationSet(
  body: AnnotationSetCreate,
): Promise<AnnotationSetDetail> {
  return apiClient.post<AnnotationSetDetail>(
    `${WEB_API_BASE}/projects/${body.project_id}/annotation-sets`,
    body,
    { headers: csrfHeaders() },
  );
}

/** Rename an annotation set (only `name` is mutable after sampling). */
export async function updateAnnotationSet(
  projectId: string,
  id: string,
  body: AnnotationSetUpdate,
): Promise<AnnotationSetDetail> {
  return apiClient.patch<AnnotationSetDetail>(
    `${WEB_API_BASE}/projects/${projectId}/annotation-sets/${id}`,
    body,
    { headers: csrfHeaders() },
  );
}

/** Delete an annotation set (cascades to segments / annotations). */
export async function deleteAnnotationSet(
  projectId: string,
  id: string,
): Promise<void> {
  return apiClient.delete<void>(
    `${WEB_API_BASE}/projects/${projectId}/annotation-sets/${id}`,
    { headers: csrfHeaders() },
  );
}

// ============================================================
// Palette
// ============================================================

/** Add a species to the palette of an annotation set. */
export async function addPalette(
  projectId: string,
  setId: string,
  body: PaletteEntryCreate,
): Promise<PaletteEntry> {
  return apiClient.post<PaletteEntry>(
    `${WEB_API_BASE}/projects/${projectId}/annotation-sets/${setId}/palette`,
    body,
    { headers: csrfHeaders() },
  );
}

/** Remove a species from the palette (existing annotations are preserved). */
export async function removePalette(
  projectId: string,
  setId: string,
  speciesId: string,
): Promise<void> {
  return apiClient.delete<void>(
    `${WEB_API_BASE}/projects/${projectId}/annotation-sets/${setId}/palette/${speciesId}`,
    { headers: csrfHeaders() },
  );
}

// ============================================================
// Segments
// ============================================================

/** List segments within a set (filter by status / is_empty). */
export async function listSegments(
  projectId: string,
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
    `${WEB_API_BASE}/projects/${projectId}/annotation-sets/${setId}/segments${query}`,
  );
}

/** Fetch full segment detail including annotations and notes. */
export async function getSegment(
  projectId: string,
  id: string,
): Promise<AnnotationSegmentDetail> {
  return apiClient.get<AnnotationSegmentDetail>(
    `${WEB_API_BASE}/projects/${projectId}/segments/${id}`,
  );
}

/** Update segment state (status, is_empty). */
export async function updateSegment(
  projectId: string,
  id: string,
  body: AnnotationSegmentUpdate,
): Promise<AnnotationSegmentDetail> {
  return apiClient.patch<AnnotationSegmentDetail>(
    `${WEB_API_BASE}/projects/${projectId}/segments/${id}`,
    body,
    { headers: csrfHeaders() },
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
  projectId: string,
  segmentId: string,
  body: TimeRangeAnnotationCreate,
): Promise<TimeRangeAnnotation> {
  return apiClient.post<TimeRangeAnnotation>(
    `${WEB_API_BASE}/projects/${projectId}/segments/${segmentId}/annotations`,
    body,
    { headers: csrfHeaders() },
  );
}

/** Update an existing TimeRangeAnnotation. */
export async function updateAnnotation(
  projectId: string,
  id: string,
  body: TimeRangeAnnotationUpdate,
): Promise<TimeRangeAnnotation> {
  return apiClient.patch<TimeRangeAnnotation>(
    `${WEB_API_BASE}/projects/${projectId}/annotations/${id}`,
    body,
    { headers: csrfHeaders() },
  );
}

/** Delete a TimeRangeAnnotation (parent segment.is_empty may flip). */
export async function deleteAnnotation(
  projectId: string,
  id: string,
): Promise<void> {
  return apiClient.delete<void>(
    `${WEB_API_BASE}/projects/${projectId}/annotations/${id}`,
    { headers: csrfHeaders() },
  );
}

// ============================================================
// Notes
// ============================================================

/** Attach a note to a segment. */
export async function createSegmentNote(
  projectId: string,
  segmentId: string,
  body: AnnotationNoteCreate,
): Promise<AnnotationNote> {
  return apiClient.post<AnnotationNote>(
    `${WEB_API_BASE}/projects/${projectId}/segments/${segmentId}/notes`,
    body,
    { headers: csrfHeaders() },
  );
}

/** Attach a note to a TimeRangeAnnotation. */
export async function createAnnotationNote(
  projectId: string,
  annotationId: string,
  body: AnnotationNoteCreate,
): Promise<AnnotationNote> {
  return apiClient.post<AnnotationNote>(
    `${WEB_API_BASE}/projects/${projectId}/annotations/${annotationId}/notes`,
    body,
    { headers: csrfHeaders() },
  );
}

// ============================================================
// Evaluation
// ============================================================

/** Dispatch a cross-model evaluation run for a set. */
export async function evaluateAnnotationSet(
  projectId: string,
  setId: string,
  body: EvaluationDispatchRequest,
): Promise<EvaluationRunResponse> {
  return apiClient.post<EvaluationRunResponse>(
    `${WEB_API_BASE}/projects/${projectId}/annotation-sets/${setId}/evaluate`,
    body,
    { headers: csrfHeaders() },
  );
}

/**
 * List evaluation runs for a set (most recent first).
 *
 * @param projectId - Project UUID (for BFF scoping)
 * @param setId - AnnotationSet UUID
 * @param params - Optional pagination (limit/offset)
 */
export async function listEvaluationRuns(
  projectId: string,
  setId: string,
  params?: { limit?: number; offset?: number },
): Promise<EvaluationRunListResponse> {
  const qs = new URLSearchParams();
  if (params?.limit !== undefined) qs.set('limit', String(params.limit));
  if (params?.offset !== undefined) qs.set('offset', String(params.offset));
  const query = qs.toString() ? `?${qs.toString()}` : '';
  return apiClient.get<EvaluationRunListResponse>(
    `${WEB_API_BASE}/projects/${projectId}/annotation-sets/${setId}/evaluation-runs${query}`,
  );
}

/** Get grouped-by-model summary for an evaluation run. */
export async function getEvaluationRun(
  projectId: string,
  id: string,
): Promise<EvaluationSummary> {
  return apiClient.get<EvaluationSummary>(
    `${WEB_API_BASE}/projects/${projectId}/evaluation-runs/${id}`,
  );
}

/** Delete an evaluation run (cascades to results). */
export async function deleteEvaluationRun(
  projectId: string,
  id: string,
): Promise<void> {
  return apiClient.delete<void>(
    `${WEB_API_BASE}/projects/${projectId}/evaluation-runs/${id}`,
    { headers: csrfHeaders() },
  );
}
