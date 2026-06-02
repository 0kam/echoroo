/**
 * spec/011 US7 — authenticated banner + activity client (T643).
 *
 * All three calls route through the shared {@link callWebApi} helper so the
 * `/web-api/v1` Bearer + CSRF + `credentials: 'include'` envelope is applied
 * uniformly. Hand-rolling `fetch` here would drop the `Authorization: Bearer`
 * header (the recurring BFF pitfall → 401), so the envelope stays single-
 * sourced in `projects.ts`.
 */

import { callWebApi } from './projects';
import type {
  BannerListResponse,
  ActivityPageResponse,
  BannerDismissRequest,
} from '$lib/types/me';

export const meApi = {
  /** GET /web-api/v1/me/banners → undismissed banners for the caller. */
  async listBanners(): Promise<BannerListResponse> {
    return callWebApi<BannerListResponse>('GET', '/me/banners');
  },

  /**
   * POST /web-api/v1/me/banners/dismiss → 204 (idempotent).
   *
   * A 404 is anti-enumeration (row not found / not yours / bad table all
   * collapse to one status). Callers MUST treat the 404 as "reconcile to
   * server truth" (re-fetch the list), never as a distinct error.
   */
  async dismissBanner(payload: BannerDismissRequest): Promise<void> {
    await callWebApi<void>('POST', '/me/banners/dismiss', payload);
  },

  /** GET /web-api/v1/me/activity?cursor=&limit= → one keyset page. */
  async listActivity(params?: {
    cursor?: string | null;
    limit?: number;
  }): Promise<ActivityPageResponse> {
    const qs = new URLSearchParams();
    if (params?.cursor) qs.set('cursor', params.cursor);
    if (params?.limit != null) qs.set('limit', String(params.limit));
    const suffix = qs.toString() ? `?${qs.toString()}` : '';
    return callWebApi<ActivityPageResponse>('GET', `/me/activity${suffix}`);
  },
};
