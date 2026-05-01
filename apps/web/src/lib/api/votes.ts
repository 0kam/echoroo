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

const API_BASE = '/api/v1';

/**
 * Build the vote URL for a detection (legacy path).
 */
function detectionVoteUrl(projectId: string, detectionId: string): string {
  return `${API_BASE}/projects/${projectId}/detections/${detectionId}/votes`;
}

/**
 * Build the vote URL for a generic annotation.
 */
function annotationVoteUrl(projectId: string, annotationId: string): string {
  return `${API_BASE}/projects/${projectId}/annotations/${annotationId}/votes`;
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
    body
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
    annotationVoteUrl(projectId, annotationId)
  );
}
