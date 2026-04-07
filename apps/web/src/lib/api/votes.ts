/**
 * Detection votes API client.
 *
 * Provides functions to cast, update, delete, and retrieve votes
 * on detections as part of the voting review system.
 */

import type { VoteSummary, CastVoteRequest, VoteValue } from '$lib/types/detection';
import { apiClient } from './client';

const API_BASE = '/api/v1';

/**
 * Cast or update a vote on a detection.
 * If the user already has a vote, it is updated.
 */
export async function castVote(
  projectId: string,
  detectionId: string,
  vote: VoteValue,
  suggestedTagId?: string,
  note?: string
): Promise<VoteSummary> {
  const body: CastVoteRequest = { vote };
  if (suggestedTagId !== undefined) body.suggested_tag_id = suggestedTagId;
  if (note !== undefined) body.note = note;

  return apiClient.post<VoteSummary>(
    `${API_BASE}/projects/${projectId}/detections/${detectionId}/votes`,
    body
  );
}

/**
 * Delete the current user's vote on a detection (toggle off).
 */
export async function deleteVote(
  projectId: string,
  detectionId: string
): Promise<void> {
  return apiClient.delete<void>(
    `${API_BASE}/projects/${projectId}/detections/${detectionId}/votes/me`
  );
}

/**
 * Retrieve the vote summary for a detection, including all votes
 * and the current user's vote.
 */
export async function getVotes(
  projectId: string,
  detectionId: string
): Promise<VoteSummary> {
  return apiClient.get<VoteSummary>(
    `${API_BASE}/projects/${projectId}/detections/${detectionId}/votes`
  );
}
