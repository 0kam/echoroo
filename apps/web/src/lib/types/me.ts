/**
 * spec/011 US7 — banner + activity wire types.
 *
 * Mirrors the Pydantic models in `apps/api/echoroo/api/web_v1/me.py`
 * (`BannerItemOut` / `BannerListOut` / `DismissIn` / `ActivityItemOut` /
 * `ActivityPageOut`). UUIDs serialize as strings, datetimes as ISO-8601.
 *
 * A-13 redaction note: the backend `banner_presenter` guarantees only the
 * banner `summary` is PII-safe. The activity `details` object and the
 * (always-null) `actor_user_id` are NOT redaction-guaranteed and MUST NOT
 * be rendered to the user.
 */

export interface BannerItem {
  audit_table: string;
  /** UUID serialized as string. */
  audit_log_id: string;
  action: string;
  /** ISO-8601 timestamp. */
  occurred_at: string;
  /** Backend-rendered, A-13-safe. Rendered verbatim — DO NOT translate. */
  summary: string;
  /** Always `null` in phase 1; banners deep-link to `/profile/activity`. */
  link: string | null;
}

export interface BannerListResponse {
  items: BannerItem[];
}

export interface BannerDismissRequest {
  audit_table: string;
  /** UUID serialized as string. */
  audit_log_id: string;
}

export interface ActivityItem {
  audit_table: string;
  /** UUID serialized as string. */
  audit_log_id: string;
  action: string;
  /** ISO-8601 timestamp. */
  occurred_at: string;
  project_id: string | null;
  /** ALWAYS `null` (backend only persists the hashed actor id) — do not render. */
  actor_user_id: string | null;
  /** Raw audit metadata — NOT A-13-redacted; never render to the user. */
  details: Record<string, unknown>;
}

export interface ActivityPageResponse {
  items: ActivityItem[];
  /** Opaque keyset cursor; `null` marks the end of the list. */
  next_cursor: string | null;
}
