/**
 * Annotation votes API client.
 *
 * Provides functions to cast, update, delete, and retrieve votes
 * on annotations as part of the voting review system.
 *
 * Two URL patterns are supported:
 * - `/detections/{id}/votes` for detection review grids (backward compatibility)
 * - `/annotations/{id}/votes` for generic annotations (search results, etc.)
 */

import type { VoteSummary, CastVoteRequest, VoteValue, SignalQuality } from '$lib/types/detection';
import { apiClient } from './client';

// spec/009 PR 3a: the generic annotation-vote path (used by search-result
// review screens) is migrated to ``/web-api/v1``. The detection-vote path
// (used by the detection review grid) still targets ``/api/v1`` — moving
// it requires extending the detection BFF module first.
const API_BASE = '/api/v1';
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
 * Build the vote URL for a detection (legacy path — still ``/api/v1``).
 */
function detectionVoteUrl(projectId: string, detectionId: string): string {
  return `${API_BASE}/projects/${projectId}/detections/${detectionId}/votes`;
}

/**
 * Build the vote URL for a generic annotation (``/web-api/v1``).
 */
function annotationVoteUrl(projectId: string, annotationId: string): string {
  return `${WEB_API_BASE}/projects/${projectId}/annotations/${annotationId}/votes`;
}

/**
 * Fetch the full vote summary (including `voters[]` and per-source counts)
 * for a detection.  The detection list endpoint only embeds compact
 * `DetectionVoteCounts`; lazy-load this when the UI needs the per-source
 * breakdown or the voter list (FR-038 / FR-039).
 */
export async function getDetectionVoteSummary(
  projectId: string,
  detectionId: string
): Promise<VoteSummary> {
  return apiClient.get<VoteSummary>(detectionVoteUrl(projectId, detectionId));
}

/**
 * Cast or update a vote on a detection.
 * If the user already has a vote, it is updated.
 *
 * @param signalQuality - Only meaningful for 'agree' votes; describes how clearly
 *   this species is audible relative to others in the clip.
 */
export async function castVote(
  projectId: string,
  detectionId: string,
  vote: VoteValue,
  signalQuality?: SignalQuality,
  suggestedTagId?: string,
  note?: string
): Promise<VoteSummary> {
  const body: CastVoteRequest = { vote };
  if (signalQuality !== undefined) body.signal_quality = signalQuality;
  if (suggestedTagId !== undefined) body.suggested_tag_id = suggestedTagId;
  if (note !== undefined) body.note = note;

  return apiClient.post<VoteSummary>(
    detectionVoteUrl(projectId, detectionId),
    body
  );
}

/**
 * Delete the current user's vote on a detection (toggle off).
 *
 * Returns the updated VoteSummary (with recomputed consensus) from the backend.
 * Callers should use the returned summary to update local state directly.
 */
export async function deleteVote(
  projectId: string,
  detectionId: string
): Promise<VoteSummary> {
  return apiClient.delete<VoteSummary>(
    detectionVoteUrl(projectId, detectionId)
  );
}

// ============================================================
// Generic annotation vote functions (for search results, etc.)
// ============================================================

/**
 * Cast or update a vote on an annotation (generic path).
 * Works with any annotation ID, including those from search results.
 */
export async function castAnnotationVote(
  projectId: string,
  annotationId: string,
  vote: VoteValue,
  signalQuality?: SignalQuality,
  suggestedTagId?: string,
  note?: string
): Promise<VoteSummary> {
  const body: CastVoteRequest = { vote };
  if (signalQuality !== undefined) body.signal_quality = signalQuality;
  if (suggestedTagId !== undefined) body.suggested_tag_id = suggestedTagId;
  if (note !== undefined) body.note = note;

  return apiClient.post<VoteSummary>(
    annotationVoteUrl(projectId, annotationId),
    body,
    { headers: csrfHeaders() }
  );
}

/**
 * Delete the current user's vote on an annotation (generic path).
 *
 * Returns the updated VoteSummary (with recomputed consensus) from the backend.
 * Callers should use the returned summary to update local state directly.
 */
export async function deleteAnnotationVote(
  projectId: string,
  annotationId: string
): Promise<VoteSummary> {
  return apiClient.delete<VoteSummary>(
    annotationVoteUrl(projectId, annotationId),
    { headers: csrfHeaders() }
  );
}
