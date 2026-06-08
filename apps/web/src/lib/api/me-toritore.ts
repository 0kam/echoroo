/**
 * ToriTore (とりトレ) proficiency client.
 *
 * Internal research-preview feature (`preview/toritore-integration`).
 *
 * All calls route through the shared {@link callWebApi} helper so the
 * `/web-api/v1` Bearer + CSRF + `credentials: 'include'` envelope is applied
 * uniformly. Hand-rolling `fetch` here would drop the `Authorization: Bearer`
 * header (the recurring BFF pitfall → 401), so the envelope stays single-
 * sourced in `projects.ts`.
 *
 * The upload endpoint accepts the *raw* ToriTore JSON object (the parsed
 * contents of the file the user exported); no client-side transformation is
 * performed beyond `JSON.parse`.
 */

import { callWebApi } from './projects';

/** One row of a parsed ToriTore test summary. */
export interface ToritoreTestSummary {
  test_number: number;
  total_score: number | null;
  source_timestamp: string | null;
}

/**
 * Proficiency summary returned by both the upload and read endpoints.
 *
 * - `latest_total_score` — the score of the most recent test, or `null` when
 *   the user has never submitted a result.
 * - `tests` — per-test rows (most recent first; ordering is server-defined).
 * - `per_species_rates` — map of GBIF usageKey (numeric string) → correct rate.
 */
export interface ToritoreSummary {
  latest_total_score: number | null;
  tests: ToritoreTestSummary[];
  per_species_rates: Record<string, number>;
}

/**
 * Annotation-set participation eligibility for the current user.
 *
 * `eligible` is computed server-side: it is `true` when the caller is exempt
 * (Owner / Admin), when the set has no requirement (`required === null`), or
 * when `my_latest_total_score >= required`.
 */
export interface AnnotationSetEligibility {
  required: number | null;
  my_latest_total_score: number | null;
  eligible: boolean;
  is_exempt: boolean;
}

/**
 * Upload a raw ToriTore JSON object.
 *
 * `POST /web-api/v1/me/toritore-results` — body is the parsed JSON object as-is.
 * Returns the recomputed proficiency summary so the caller can immediately
 * re-evaluate eligibility.
 */
export async function uploadToritoreResults(
  rawJson: unknown,
): Promise<ToritoreSummary> {
  return callWebApi<ToritoreSummary>('POST', '/me/toritore-results', rawJson);
}

/** `GET /web-api/v1/me/toritore-results` → current proficiency summary. */
export async function getToritoreSummary(): Promise<ToritoreSummary> {
  return callWebApi<ToritoreSummary>('GET', '/me/toritore-results');
}

/**
 * `GET /web-api/v1/projects/{projectId}/annotation-sets/{setId}/eligibility`
 * → participation eligibility for the current user.
 */
export async function getAnnotationSetEligibility(
  projectId: string,
  setId: string,
): Promise<AnnotationSetEligibility> {
  return callWebApi<AnnotationSetEligibility>(
    'GET',
    `/projects/${projectId}/annotation-sets/${setId}/eligibility`,
  );
}
