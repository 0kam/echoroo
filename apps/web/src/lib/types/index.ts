/**
 * TypeScript type definitions for Echoroo API
 *
 * This file serves as the canonical re-export hub.
 * Domain-specific types are defined in their own modules:
 *   - data.ts: Data management entities (sites, datasets, recordings, clips)
 *   - tag.ts: Project tag management entities
 *
 * Administration and auth types are defined directly in this file
 * since they are foundational and used across the application.
 */

// ============================================
// Re-export domain types
// ============================================

// Re-export project tag types.
export type {
  TagCategory,
  Tag,
  TagDetail,
  TagCreate,
  TagUpdate,
  TagListResponse,
  GBIFSuggestion,
  TagStatistic,
  TagListParams,
} from './tag';

// Re-export data management types
export type {
  DatasetVisibility,
  DatasetStatus,
  DatetimeParseStatus,
  Site,
  SiteDetail,
  SiteCreate,
  SiteUpdate,
  SiteListResponse,
  H3ValidationRequest,
  H3ValidationResponse,
  H3FromCoordinatesRequest,
  H3FromCoordinatesResponse,
  RecorderSummary,
  LicenseSummary,
  UserSummary,
  SiteSummary,
  DatasetDetail,
  DatasetCreate,
  DatasetUpdate,
  DatasetListResponse,
  ImportRequest,
  ImportStatusResponse,
  DateRangeStats,
  RecordingsByDate,
  RecordingsByHour,
  DatasetStatistics,
  ExportRequest,
  RecordingDetail,
  RecordingUpdate,
  RecordingListResponse,
  SpectrogramParams,
  PlaybackParams,
  RecordingSummaryForClip,
  ClipDetail,
  ClipCreate,
  ClipUpdate,
  ClipListResponse,
  ClipGenerateRequest,
  ClipGenerateResponse,
  SiteListParams,
  DatasetListParams,
  RecordingListParams,
  RecordingSearchParams,
  ClipListParams,
} from './data';

// Re-export data types that have the same name but richer definitions
// NOTE: Dataset, Recording, Clip from data.ts are the canonical versions
export type {
  Dataset,
  Recording,
  Clip,
} from './data';

// Re-export detection review types
export * from './detection';

// Re-export global taxon types
export type {
  VernacularName,
  Taxon,
  TaxonDetail,
  TaxonListResponse,
  TaxonSearchResult,
} from './taxon';

// Annotation-scoped DatasetSummary (used in annotation contexts)
// Both data.ts and annotation.ts define DatasetSummary with the same shape
// We re-export from data.ts as it's the primary source
export type { DatasetSummary } from './data';

// Re-export spec/011 US7 banner + activity types
export type {
  BannerItem,
  BannerListResponse,
  BannerDismissRequest,
  ActivityItem,
  ActivityPageResponse,
} from './me';

// ============================================
// Common Types
// ============================================

/**
 * Generic API error response
 */
export interface ErrorResponse {
  detail: string;
  code?: string;
  errors?: Array<{
    field?: string;
    message?: string;
  }>;
}

/**
 * Generic API response wrapper
 */
export interface ApiResponse<T> {
  data: T;
  error?: string;
}

/**
 * Pagination metadata
 */
export interface PaginationMeta {
  total: number;
  page: number;
  limit: number;
}

/**
 * Generic paginated response
 */
export interface PaginatedResponse<T> extends PaginationMeta {
  items: T[];
}

// ============================================
// User Types
// ============================================

/**
 * User entity
 */
export interface User {
  id: string;
  email: string;
  display_name?: string | null;
  organization?: string | null;
  is_active: boolean;
  is_superuser: boolean;
  created_at: string;
  last_login_at?: string | null;
  /**
   * spec/011 US4: set when an admin has reset this user's password to a
   * temporary credential. While true, the (app) guard forces the user to
   * the `/change-password` screen before any other route renders.
   */
  must_change_password?: boolean;
}

/**
 * User response (alias for User)
 */
export type UserResponse = User;

/**
 * User update request
 */
export interface UserUpdateRequest {
  display_name?: string | null;
  organization?: string | null;
}

// ============================================
// Authentication Types
// ============================================

/**
 * User registration request
 */
export interface UserRegisterRequest {
  email: string;
  password: string;
  display_name?: string;
  captcha_token?: string;
  invitation_token?: string;
}

/**
 * Login request
 */
export interface LoginRequest {
  email: string;
  password: string;
  captcha_token?: string;
}

/**
 * Token response from authentication endpoints
 */
export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

/**
 * CAPTCHA verification request
 */
export interface CaptchaVerifyRequest {
  token: string;
}

/**
 * CAPTCHA verification response
 */
export interface CaptchaVerifyResponse {
  verified: boolean;
  challenge_ts?: string;
}

/**
 * Password change request
 */
export interface PasswordChangeRequest {
  current_password: string;
  new_password: string;
}

// ============================================
// API Token Types
// ============================================

/**
 * API token entity
 */
export interface APIToken {
  id: string;
  name: string;
  last_used_at?: string;
  expires_at?: string;
  is_active: boolean;
  created_at: string;
}

/**
 * API token response (alias for APIToken)
 */
export type APITokenResponse = APIToken;

/**
 * API token create request
 */
export interface APITokenCreateRequest {
  name: string;
  expires_at?: string;
}

/**
 * API token create response (includes plain token)
 */
export interface APITokenCreateResponse extends APIToken {
  token: string;
}

// ============================================
// Project Types
// ============================================

/**
 * Project visibility enum.
 *
 * NOTE: `'restricted'` was introduced by the Permissions Redesign
 * (Phase 8 / FR-014). The backend contract
 * (`specs/006-permissions-redesign/contracts/projects.yaml`) accepts
 * `public` and `restricted`.
 */
export type ProjectVisibility = 'public' | 'restricted';

/**
 * H3 resolutions allowed for the
 * `public_location_precision_h3_res` Restricted-mode toggle (FR-021 /
 * FR-027). Lower numbers are coarser; values are continuous from 3 to 15.
 */
export type RestrictedH3Resolution =
  | 3
  | 4
  | 5
  | 6
  | 7
  | 8
  | 9
  | 10
  | 11
  | 12
  | 13
  | 14
  | 15;

/**
 * Restricted-mode capability toggles persisted on
 * `Project.restricted_config` (FR-014 / FR-020-022).
 *
 * Mirrors the `RestrictedConfig` schema in
 * `specs/006-permissions-redesign/contracts/projects.yaml` (lines
 * 430-454). All eight keys are required at the API layer — defaults
 * live on the backend model column for newly created projects only.
 */
export interface RestrictedConfig {
  allow_media_playback: boolean;
  allow_detection_view: boolean;
  mask_species_in_detection: boolean;
  allow_download: boolean;
  allow_export: boolean;
  allow_voting_and_comments: boolean;
  public_location_precision_h3_res: RestrictedH3Resolution;
  allow_precise_location_to_viewer: boolean;
}

/**
 * Request body for `PATCH /web-api/v1/projects/{id}/restricted-config`
 * (Phase 8 / T400). Same shape as `RestrictedConfig` — the backend
 * Pydantic schema (`RestrictedConfigUpdateRequest`) enforces
 * `Extra.forbid` and `StrictBool` so the entire object must be sent.
 */
export type RestrictedConfigUpdateRequest = RestrictedConfig;

/**
 * Project entity
 *
 * `restricted_config` and `restricted_config_version` were added by
 * the Permissions Redesign (Phase 8 / FR-014, FR-024). They are
 * optional on this type for backwards compatibility — the backend
 * always returns them on the redesigned `/projects` endpoints, but
 * older response shapes may omit them. UI code that surfaces the
 * toggles MUST check for presence and fall back to a Public-style
 * UI when missing.
 */
/**
 * Public-safe owner sub-object embedded in `Project`.
 *
 * Mirrors `PublicOwnerResponse` in
 * `apps/api/echoroo/schemas/project.py`. Phase 5 polish round 2 /
 * FR-030 deliberately strips PII (`email`, `last_login_at`,
 * `created_at`) from the owner so Guest callers on Public + Active
 * projects cannot pivot from a project response into the owner's
 * private profile. The display string + opaque ID is enough for a "by
 * <author>" byline.
 *
 * If the backend ever surfaces a contact email (via a privileged route
 * such as `GET /projects/{id}/owner-contact` for Authenticated callers
 * on Restricted projects, US4 AC2), it will be added here as an
 * **optional** field — the default shape stays PII-free.
 */
export interface ProjectOwner {
  id: string;
  display_name: string | null;
  /**
   * Optional contact email for the owner. Currently never populated by
   * the public list / detail surfaces (FR-030). Reserved for a future
   * privileged contact route — see the T411 mailto: implementation in
   * `routes/(app)/projects/[id]/+page.svelte`, which falls back to a
   * "no public contact" notice when this is absent.
   */
  email?: string | null;
}

export interface Project {
  id: string;
  name: string;
  description?: string;
  target_taxa?: string;
  visibility: ProjectVisibility;
  /**
   * Display license short_name (e.g. `CC-BY`), joined from the `licenses`
   * master on the response side. spec/012 Phase 3: this stays the response
   * display field; the create/update wire field is the PK `license_id`.
   */
  license?: string;
  /**
   * Project status (Phase 9 / FR-019). Optional for backwards
   * compatibility — older detail responses may omit it.
   */
  status?: ProjectStatus;
  /**
   * Owner sub-object — public-safe (FR-030). See `ProjectOwner`.
   */
  owner: ProjectOwner;
  created_at: string;
  updated_at: string;
  /** Restricted-mode capability toggles (FR-014). */
  restricted_config?: RestrictedConfig;
  /** Monotonic version bumped on every restricted-config PATCH (FR-024). */
  restricted_config_version?: number;
  /**
   * Caller's effective project role (Phase 9 polish round 2 Major 2,
   * FR-014). Resolved server-side from the (project, current_user) pair
   * so the Web UI can gate the Restricted "Request access" callout on
   * a single field instead of probing the admin-only `GET /members`
   * endpoint (which 403s for Members / Viewers and would silently put
   * every Member in the non-member bucket).
   *
   * `null` for Guest and for Authenticated non-members; one of
   * `"owner" | "admin" | "member" | "viewer"` otherwise.
   */
  current_user_role?: 'owner' | 'admin' | 'member' | 'viewer' | null;
}

/**
 * Project response (alias for Project)
 */
export type ProjectResponse = Project;

/**
 * Response from `POST /web-api/v1/projects/`.
 *
 * The SU-bootstrap redesign (preview feedback #1) dropped the create-time
 * `intended_owner_email` flow, so project creation no longer issues a
 * one-shot invitation. The response is now the plain `Project` shape;
 * post-creation ownership transfer is handled separately via
 * `transferOwnership()` (preview feedback #2).
 */
export type ProjectCreateResponse = Project;

/**
 * Project create request.
 *
 * `visibility` and `license_id` are both required by the contract
 * (`specs/006-permissions-redesign/contracts/projects.yaml`,
 * `ProjectCreateRequest.required = [name, visibility, license_id]`).
 *
 * spec/012 Phase 3 (T021-T028): the wire field is the licenses PK
 * `license_id` (e.g. `cc-by`, lowercase) instead of the legacy
 * `license` short_name. The form sources valid ids live from the
 * operator-curated `licenses` master via `useLicenses()`; an unknown id
 * returns 422 `license_not_found`. The response side still surfaces the
 * joined `short_name` via `Project.license`.
 */
export interface ProjectCreateRequest {
  name: string;
  description?: string;
  target_taxa?: string;
  visibility: ProjectVisibility;
  license_id: string;
}

/**
 * Project update request
 */
export interface ProjectUpdateRequest {
  name?: string;
  description?: string;
  target_taxa?: string;
  visibility?: ProjectVisibility;
  license_id?: string;
}

/**
 * Project lifecycle status (Phase 9 / FR-019).
 *
 * Mirrors `ProjectStatus` in `apps/api/echoroo/models/enums.py` and the
 * `status` enum in `contracts/projects.yaml` (`active`, `dormant`,
 * `archived`).
 */
export type ProjectStatus = 'active' | 'dormant' | 'archived';

/**
 * Project summary returned by `GET /projects` list endpoints (Phase 9 /
 * FR-018, FR-019, FR-030).
 *
 * Mirrors `ProjectSummary` at
 * `specs/006-permissions-redesign/contracts/projects.yaml` (lines
 * 384-395) and the backend `ProjectSummary` Pydantic model
 * (`apps/api/echoroo/schemas/project.py`). Deliberately omits
 * `restricted_config`, `restricted_config_version`, the `owner`
 * sub-object (only `owner_display_name` is exposed), and timestamps so
 * Guest enumeration of Restricted projects (FR-019) cannot leak any
 * field beyond the documented summary slot.
 */
export interface ProjectSummary {
  id: string;
  name: string;
  description: string | null;
  visibility: ProjectVisibility;
  status: ProjectStatus;
  // Display license short_name (e.g. `CC-BY`), joined from the `licenses`
  // master on the response side. Master-driven licenses may include
  // admin-added short_names (e.g. CC-BY-ND). Match `Project.license` shape.
  license: string;
  /**
   * Public-safe display string for the owner. Falls back to the
   * local-part of the email on the backend so this is **never** the
   * full email address (FR-030).
   */
  owner_display_name: string;
  /** Number of Datasets attached to this project. */
  dataset_count: number;
  /**
   * Up to 5 most-frequent species labels for the project (Phase 11
   * backlog — backend currently emits an empty array).
   */
  species_preview: string[];
}

/**
 * Paginated `ProjectSummary` list response — the canonical list contract
 * (Phase 9 / FR-018, FR-019).
 *
 * Mirrors `ProjectListResponse` at
 * `contracts/projects.yaml:374-382`. The contract intentionally exposes
 * only `items / total / page` — no `limit` field — because the page
 * size is known from the request query and never echoed back. Do not
 * extend this with `limit` to "match" `PaginationMeta`; that would
 * drift from the contract.
 */
export interface ProjectSummaryListResponse {
  items: ProjectSummary[];
  total: number;
  page: number;
}

/**
 * @deprecated Phase 9 / FR-018, FR-019 — public list surfaces
 * (`/api/v1/projects` and `/web-api/v1/projects`) now return
 * `ProjectSummaryListResponse` instead, so the Restricted enumeration
 * contract cannot leak `restricted_config` or any field beyond the
 * documented summary slot. This type is kept only for any in-tree
 * helper that still wants the full body alongside pagination metadata
 * (e.g., admin tooling); do not add new references.
 */
export interface ProjectListResponse extends PaginationMeta {
  items: Project[];
}

// ============================================
// Project Overview Types
// ============================================

/**
 * A site entry in the project overview
 */
export interface ProjectOverviewSite {
  id: string;
  name: string;
  /**
   * Phase 13 P4 / T807 (2026-04-28): canonical Site H3 field is
   * `h3_index_member` (matches ORM column + spec data-model §3.10).
   * Permissions redesign Round 2: raw `latitude` / `longitude` are no
   * longer surfaced on the frontend. All spatial signal flows through
   * `h3_index_member`; consumers that need a centre point should
   * derive it via `h3-js`'s `cellToLatLng`. This keeps FR-030
   * enforcement uniform and prevents bypassing the auto-obscure
   * pipeline by holding onto stale member-precise coordinates
   * client-side.
   */
  h3_index_member: string;
  recording_count: number;
  dataset_count: number;
}

/**
 * A calendar entry for recording activity by month
 */
export interface RecordingCalendarEntry {
  year: number;
  month: number;
  /** Number of sites with recordings in this month */
  site_count: number;
  /** Total recordings in this month */
  recording_count: number;
}

/**
 * Project overview response from GET /projects/{project_id}/overview
 */
export interface ProjectOverviewResponse {
  sites: ProjectOverviewSite[];
  recording_calendar: RecordingCalendarEntry[];
  total_recordings: number;
  total_sites: number;
  /** Total duration in seconds */
  total_duration: number;
}

// ============================================
// Trusted User Types (Phase 10 / FR-041-046, FR-050)
// ============================================

/**
 * Trusted overlay status. Mirrors the backend ``ProjectTrustedStatus``
 * enum in ``apps/api/echoroo/models/enums.py`` and the
 * ``TrustedUserResponse`` payload from
 * ``specs/006-permissions-redesign/contracts/trusted.yaml``.
 *
 * - ``active``  — overlay is in effect
 * - ``expired`` — ``expires_at`` reached (FR-044, auto-expire worker)
 * - ``revoked`` — Owner explicitly revoked via DELETE (FR-046)
 */
export type ProjectTrustedStatus = 'active' | 'expired' | 'revoked';

/**
 * Permission name allowed on a Trusted invitation. Matches
 * ``TRUSTED_ALLOWED_PERMISSIONS`` (FR-012) — a strict subset of the
 * full Permission enum that the Owner may grant ephemerally.
 */
export type TrustedGrantedPermission =
  | 'view_media'
  | 'view_detection'
  | 'view_precise_location'
  | 'download'
  | 'export'
  | 'search_within_project'
  | 'vote'
  | 'comment';

/**
 * Single Trusted overlay row returned by ``GET /projects/{id}/trusted-users``.
 */
export interface TrustedUser {
  id: string;
  project_id: string;
  user_id: string;
  invitation_id: string;
  granted_by_id: string;
  granted_at: string;
  expires_at: string;
  status: ProjectTrustedStatus;
  granted_permissions: TrustedGrantedPermission[];
  revoked_at: string | null;
}

/**
 * ``GET /projects/{id}/trusted-users`` envelope.
 */
export interface TrustedUserListResponse {
  items: TrustedUser[];
  total: number;
}

/**
 * Body for ``POST /projects/{id}/trusted-users`` (Owner only).
 *
 * - ``duration_seconds`` — 1 second to 1 year (FR-043, default 90 days
 *   on the backend; the Web UI defaults to 7 776 000 = 90 days).
 * - ``granted_permissions`` — non-empty subset of
 *   :type:`TrustedGrantedPermission`.
 */
export interface TrustedUserInviteRequest {
  email: string;
  granted_permissions: TrustedGrantedPermission[];
  duration_seconds: number;
}

/**
 * ``POST /projects/{id}/trusted-users`` 202 response. The plain-text
 * invitation token is delivered out-of-band via email (FR-051) — only
 * ``invitation_id`` leaves the API surface.
 */
export interface TrustedUserInviteResponse {
  invitation_id: string;
}

/**
 * Body for ``PATCH /projects/{id}/trusted-users/{trustedUserId}``
 * (Owner only).
 *
 * Per the contract (``specs/006-permissions-redesign/contracts/trusted.yaml``)
 * the only writable fields are ``expires_at`` (ISO-8601 datetime — the
 * absolute new expiry, ``granted_at + 1 year`` upper bound) and
 * ``granted_permissions`` (allowlist re-validated server-side). The Round 1
 * "Major 4" finding flagged ``extension_seconds`` as contract-non-compliant;
 * UI components compute the new ISO timestamp client-side from the
 * datetime-local picker and send it via ``expires_at``.
 */
export interface TrustedUserUpdateRequest {
  expires_at?: string | null;
  granted_permissions?: TrustedGrantedPermission[] | null;
}

/**
 * ``POST /projects/{project_id}/invitations/{token}/accept`` response.
 *
 * Backend echoes ``kind`` (``member`` or ``trusted``) plus the project_id;
 * for Trusted invitations the ``trusted_user_id`` is also returned, and
 * for Member invitations the ``member_id``.
 */
export interface InvitationAcceptResponse {
  kind: 'member' | 'trusted';
  project_id: string;
  member_id?: string;
  trusted_user_id?: string;
}

// ============================================
// Project Member Invitation Types (spec/011 US6)
//
// Wire shapes for the project-scoped member invitation endpoints. The
// SU-bootstrap PR adds these to unblock the future collaborators page
// (no UI consumer in this PR beyond the shared `projectsApi` methods).
// ============================================

/**
 * Role granted by a member invitation. Mirrors the lowercase enum the
 * backend `POST /projects/{id}/invitations` body accepts.
 */
export type MemberInvitationRole = 'viewer' | 'member' | 'admin';

/**
 * `POST /projects/{id}/invitations` request — issue a single member
 * invitation bound to one email.
 */
export interface MemberInvitationIssueRequest {
  email: string;
  role: MemberInvitationRole;
}

/**
 * `POST /projects/{id}/invitations` 201 response. `invitation_url` is
 * one-shot (served with no-store) and cannot be recovered after the
 * issuing response is consumed.
 */
export interface MemberInvitationIssueResponse {
  invitation_id: string;
  invitation_url: string;
  expires_at: string;
  bound_email_hash: string;
}

/**
 * `POST /projects/{id}/invitations/bulk` request — issue one invitation
 * per email, all with the same `role`.
 */
export interface BulkInvitationRequest {
  role: MemberInvitationRole;
  emails: string[];
}

/**
 * One element of the 207 multi-status array returned by the bulk issue
 * endpoint. `invitation_url` is one-shot and populated only for the
 * `issued` status; the other statuses leave it `null`.
 */
export interface BulkInvitationResultItem {
  email: string;
  // `already_member`: the email already belongs to an active project member
  // (no invitation issued) — rendered distinctly rather than as a hard error.
  status: 'issued' | 'duplicate_pending' | 'already_member' | 'rate_limited' | 'internal_error';
  invitation_id: string | null;
  invitation_url: string | null;
  expires_at: string | null;
  error_message: string | null;
}

/**
 * One row of `GET /projects/{id}/invitations`. `bound_email` is the
 * plaintext target (operator-visible listing). This is a mixed
 * member+trusted listing item, so several fields are nullable depending
 * on the row `kind` (mirrors backend `schemas/member_invitations.py`):
 * - `role` is null on trusted-kind rows (backend `ProjectMemberRole | None`).
 * - `granted_permissions` is null on member rows (backend `list[str] | None`);
 *   the resolved permission set is only carried on trusted-kind rows.
 * - `expires_at` is always present (backend `expires_at: datetime`).
 */
export interface ProjectInvitationListItem {
  id: string;
  kind: 'member' | 'trusted';
  role: MemberInvitationRole | null;
  granted_permissions: string[] | null;
  status: string;
  bound_email: string;
  issued_by: string;
  issued_at: string;
  expires_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
  declined_at: string | null;
  ownership_transfer_on_accept: boolean;
}

/**
 * `GET /projects/{id}/invitations` response envelope.
 */
export interface ProjectInvitationListResponse {
  items: ProjectInvitationListItem[];
}

/**
 * `POST /projects/{id}/invitations/{invitation_id}/revoke` request body.
 * The reason is optional, recorded for the audit trail when supplied.
 */
export interface InvitationRevokeRequest {
  reason?: string;
}

/**
 * `POST /projects/{id}/invitations/{invitation_id}/revoke` response.
 */
export interface InvitationRevokeResponse {
  invitation_id: string;
  // Backend returns the row's status enum value (happy-path is 'revoked',
  // but keep this wide rather than over-narrowing to a single literal).
  status: string;
  revoked_at: string;
}

// ============================================
// Project Member Types
// ============================================

/**
 * Project member role enum
 */
export type ProjectMemberRole = 'admin' | 'member' | 'viewer';

/**
 * Project member entity
 */
export interface ProjectMember {
  id: string;
  user: User;
  role: ProjectMemberRole;
  joined_at: string;
}

/**
 * Project member response (alias for ProjectMember)
 */
export type ProjectMemberResponse = ProjectMember;

/**
 * Add project member request
 */
export interface ProjectMemberAddRequest {
  email: string;
  role: ProjectMemberRole;
}

/**
 * Update project member request
 */
export interface ProjectMemberUpdateRequest {
  role: ProjectMemberRole;
}

/**
 * Response from `POST /web-api/v1/projects/{id}/transfer-ownership`
 * (SU-bootstrap redesign / preview feedback #2).
 *
 * Owner-only, idempotent under `X-Idempotency-Key`. The target must be
 * an active project Admin; on success the previous owner is demoted to
 * Admin and the new owner is promoted to Owner. `replayed` is `true`
 * when the same idempotency key resolved to an already-applied transfer.
 */
export interface TransferOwnershipResponse {
  project_id: string;
  previous_owner_id: string;
  new_owner_id: string;
  replayed: boolean;
}

// ============================================
// Admin Types
// ============================================

/**
 * Admin user update request.
 *
 * spec/011 follow-up: the backend now only honours ``display_name``.
 * ``is_active`` / ``is_superuser`` / ``is_verified`` remain on the
 * payload for SPA backwards compatibility (the buttons in
 * ``/admin/users`` still send them) but the API silently drops them —
 * actual superuser promotion lives in the ``/admin/superusers`` M-of-N
 * flow. UI element cleanup is tracked separately.
 */
export interface AdminUserUpdateRequest {
  display_name?: string | null;
  /** @deprecated Ignored by the backend (spec/006 dropped users.is_active). */
  is_active?: boolean;
  /** @deprecated Use /admin/superusers + M-of-N approval flow (spec/006 FR-111). */
  is_superuser?: boolean;
  /** @deprecated Ignored by the backend (spec/011 removed email verification). */
  is_verified?: boolean;
}

/**
 * Admin user list item — mirrors backend ``AdminUserListItem``
 * (``apps/api/echoroo/schemas/admin.py``).
 *
 * Used exclusively by ``GET /web-api/v1/admin/users``. The shape
 * deliberately omits the legacy ``is_active`` / ``is_verified`` /
 * ``organization`` fields (dropped by spec/006 + spec/011) and exposes
 * ``is_superuser`` as a JOIN-derived flag from the ``superusers``
 * entitlement table (FR-111). Per-user PATCH responses still reuse the
 * richer :type:`User` shape; this list-only type prevents callers from
 * relying on fields the backend no longer returns for the list surface.
 */
export interface AdminUserListItem {
  id: string;
  email: string;
  display_name: string | null;
  created_at: string;
  last_login_at: string | null;
  is_superuser: boolean;
}

/**
 * Admin user list response with pagination — mirrors backend
 * ``AdminUserListResponse``.
 */
export interface AdminUserListResponse extends PaginationMeta {
  items: AdminUserListItem[];
}

/**
 * @deprecated Use :type:`AdminUserListItem` for the list view, or the
 * generic :type:`User` type for the per-user PATCH response.
 *
 * The pre-spec/006 admin surface returned a ``User`` row plus an extra
 * ``is_verified`` flag; both ``is_verified`` and the embedded
 * ``is_active`` / ``organization`` columns were dropped by the
 * Permissions Redesign + zero-email migration. The alias is preserved
 * only as a compatibility shim for any in-tree caller that still
 * imports it; new code MUST use :type:`AdminUserListItem`.
 */
export type AdminUserResponse = AdminUserListItem;

/**
 * System setting value type
 */
export type SystemSettingValueType = 'string' | 'number' | 'boolean' | 'json';

/**
 * System setting entity
 */
export interface SystemSetting {
  key: string;
  value: string | number | boolean | object;
  value_type: SystemSettingValueType;
  description?: string;
  updated_at: string;
}

/**
 * System setting response (alias for SystemSetting)
 */
export type SystemSettingResponse = SystemSetting;

/**
 * BirdNET species filter mode
 */
export type BirdnetSpeciesFilter = 'none' | 'birdnet_geo';

/**
 * System settings update request
 */
export interface SystemSettingsUpdateRequest {
  registration_mode?: 'open' | 'invitation';
  allow_registration?: boolean;
  session_timeout_minutes?: number;
  birdnet_species_filter?: BirdnetSpeciesFilter;
  birdnet_min_conf?: number;
}

// ============================================
// Setup Types
// ============================================

/**
 * Setup status response
 */
export interface SetupStatusResponse {
  setup_required: boolean;
  setup_completed: boolean;
}

/**
 * Setup initialize request
 */
export interface SetupInitializeRequest {
  email: string;
  password: string;
  display_name?: string;
}

/**
 * User payload returned by the setup initialization endpoint
 */
export interface SetupUserResponse {
  id: string;
  email: string;
  display_name?: string | null;
  two_factor_enabled: boolean;
  created_at: string;
  updated_at: string;
}

/**
 * Setup initialize response with one-time bootstrap artifacts
 */
export interface SetupCompleteResponse {
  user: SetupUserResponse;
  totp_secret_base32: string;
  totp_provisioning_uri: string;
  bootstrap_token: string;
  bootstrap_token_expires_at: string;
  webauthn_registration_url: string;
}

// ============================================
// Legacy Type Aliases (for backwards compatibility)
// ============================================

/**
 * @deprecated Use UserUpdateRequest instead
 */
export type UpdateUserRequest = UserUpdateRequest;

/**
 * @deprecated Use PasswordChangeRequest instead
 */
export type ChangePasswordRequest = PasswordChangeRequest;

/**
 * @deprecated Use ProjectCreateRequest instead
 */
export type CreateProjectRequest = ProjectCreateRequest;

/**
 * @deprecated Use ProjectUpdateRequest instead
 */
export type UpdateProjectRequest = ProjectUpdateRequest;

/**
 * @deprecated Use ProjectMemberAddRequest instead
 */
export type AddMemberRequest = ProjectMemberAddRequest;

/**
 * @deprecated Use ProjectMemberUpdateRequest instead
 */
export type UpdateMemberRoleRequest = ProjectMemberUpdateRequest;

/**
 * @deprecated Use SetupStatusResponse instead
 */
export type SetupStatus = SetupStatusResponse;

// ============================================
// License Types
// ============================================

/**
 * License entity.
 *
 * Used by BOTH the admin CRUD surface
 * (`/web-api/v1/admin/licenses/*`, which returns `created_at` /
 * `updated_at`) AND the public read surface
 * (`/web-api/v1/licenses` from spec/012 / FR-001 / FR-017, which omits
 * timestamps because callers populating the project creation dropdown
 * have no reason to render them).
 *
 * Timestamps are therefore declared optional so a single type covers
 * both responses without forcing the public hook to fabricate
 * placeholder dates. Admin pages that need the timestamps fall back
 * gracefully via the `??` operator or by branching on presence.
 */
export interface License {
  id: string;
  name: string;
  short_name: string;
  url?: string;
  description?: string;
  /** Admin-only — present on `/admin/licenses/*` responses, absent on the public list. */
  created_at?: string;
  /** Admin-only — present on `/admin/licenses/*` responses, absent on the public list. */
  updated_at?: string;
}

/**
 * License create request
 */
export interface LicenseCreateRequest {
  id: string;
  name: string;
  short_name: string;
  url?: string;
  description?: string;
}

/**
 * License update request
 */
export interface LicenseUpdateRequest {
  name?: string;
  short_name?: string;
  url?: string;
  description?: string;
}

/**
 * License list response
 */
export interface LicenseListResponse {
  items: License[];
}

// ============================================
// Recorder Types
// ============================================

/**
 * Recorder entity
 */
export interface Recorder {
  id: string;
  manufacturer: string;
  recorder_name: string;
  version?: string;
  created_at: string;
  updated_at: string;
}

/**
 * Recorder create request
 */
export interface RecorderCreateRequest {
  id: string;
  manufacturer: string;
  recorder_name: string;
  version?: string;
}

/**
 * Recorder update request
 */
export interface RecorderUpdateRequest {
  manufacturer?: string;
  recorder_name?: string;
  version?: string;
}

/**
 * Recorder list response
 */
export interface RecorderListResponse {
  items: Recorder[];
  total: number;
  page: number;
  limit: number;
}
