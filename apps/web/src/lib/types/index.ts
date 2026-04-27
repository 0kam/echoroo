/**
 * TypeScript type definitions for Echoroo API
 *
 * This file serves as the canonical re-export hub.
 * Domain-specific types are defined in their own modules:
 *   - data.ts: Data management entities (sites, datasets, recordings, clips)
 *   - annotation.ts: Annotation feature entities (tags, annotations, tasks)
 *
 * Administration and auth types are defined directly in this file
 * since they are foundational and used across the application.
 */

// ============================================
// Re-export domain types
// ============================================

// Re-export annotation types (canonical for Tag, TagCategory, AnnotationSource, Geometry, etc.)
export type {
  TagCategory,
  AnnotationProjectVisibility,
  AnnotationTaskStatus,
  ReviewStatus,
  AnnotationSource,
  GeometryType,
  Tag,
  TagDetail,
  TagCreate,
  TagUpdate,
  TagListResponse,
  GBIFSuggestion,
  TagStatistic,
  AnnotationProgress,
  TagSummary,
  AnnotationProject,
  AnnotationProjectDetail,
  AnnotationProjectCreate,
  AnnotationProjectUpdate,
  AnnotationProjectListResponse,
  TaskGenerationResponse,
  RecordingSummaryForTask,
  ClipDetailForTask,
  AnnotationProjectSummary,
  AnnotationTask,
  AnnotationTaskUpdate,
  AnnotationTaskDetail,
  AnnotationTaskListResponse,
  TaskCompletionResponse,
  Geometry,
  SoundEventAnnotation,
  SoundEventAnnotationCreate,
  SoundEventAnnotationUpdate,
  ClipAnnotationDetail,
  Note,
  NoteCreate,
  ReviewRequest,
  AddTagRequest,
  AnnotationTaskListParams,
  TagListParams,
  AnnotationProjectListParams,
  ExportFormat,
} from './annotation';

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
  display_name?: string;
  organization?: string;
  is_active: boolean;
  is_superuser: boolean;
  is_verified: boolean;
  created_at: string;
  last_login_at?: string;
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
 * Password reset request
 */
export interface PasswordResetRequest {
  email: string;
}

/**
 * Password reset confirmation
 */
export interface PasswordResetConfirm {
  token: string;
  password: string;
}

/**
 * Email verification request
 */
export interface EmailVerifyRequest {
  token: string;
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
 * Project visibility enum
 */
export type ProjectVisibility = 'private' | 'public';

/**
 * Project license enum (Phase 7 / FR-085).
 *
 * The Permissions Redesign (006) requires every new project to declare a
 * Creative Commons license at create time. This enum mirrors the
 * `ProjectCreateRequest.license` enum in
 * `specs/006-permissions-redesign/contracts/projects.yaml` (CC0, CC-BY,
 * CC-BY-NC, CC-BY-SA).
 */
export type ProjectLicense = 'CC0' | 'CC-BY' | 'CC-BY-NC' | 'CC-BY-SA';

/**
 * Project entity
 */
export interface Project {
  id: string;
  name: string;
  description?: string;
  target_taxa?: string;
  visibility: ProjectVisibility;
  license?: ProjectLicense | string;
  owner: User;
  created_at: string;
  updated_at: string;
}

/**
 * Project response (alias for Project)
 */
export type ProjectResponse = Project;

/**
 * Project create request.
 *
 * `visibility` and `license` are both required by the contract
 * (`specs/006-permissions-redesign/contracts/projects.yaml`,
 * `ProjectCreateRequest.required = [name, visibility, license]`).
 */
export interface ProjectCreateRequest {
  name: string;
  description?: string;
  target_taxa?: string;
  visibility: ProjectVisibility;
  license: ProjectLicense;
}

/**
 * Project update request
 */
export interface ProjectUpdateRequest {
  name?: string;
  description?: string;
  target_taxa?: string;
  visibility?: ProjectVisibility;
  license?: ProjectLicense;
}

/**
 * Project list response with pagination
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
  h3_index: string;
  latitude: number | null;
  longitude: number | null;
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

// ============================================
// Admin Types
// ============================================

/**
 * Admin user update request
 */
export interface AdminUserUpdateRequest {
  is_active?: boolean;
  is_superuser?: boolean;
  is_verified?: boolean;
}

/**
 * Admin user response (alias for User)
 */
export type AdminUserResponse = User;

/**
 * Admin user list response with pagination
 */
export interface AdminUserListResponse extends PaginationMeta {
  items: User[];
}

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
 * License entity
 */
export interface License {
  id: string;
  name: string;
  short_name: string;
  url?: string;
  description?: string;
  created_at: string;
  updated_at: string;
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

// ============================================
// Legacy Annotation Types (deprecated)
// Use the canonical types from annotation.ts via the re-exports above
// ============================================

/**
 * @deprecated Use GeometryType from annotation.ts instead
 */
export type AnnotationGeometryType = 'BoundingBox' | 'TimeInterval' | 'Point';

/**
 * @deprecated Use Geometry from annotation.ts instead
 */
export interface AnnotationGeometry {
  type: AnnotationGeometryType;
  coordinates: number[];
}

/**
 * @deprecated Use SoundEventAnnotation from annotation.ts instead.
 * This flat annotation type is kept for backwards compatibility only.
 */
export interface Annotation {
  id: string;
  clip_id: string;
  tag_id: string;
  geometry: AnnotationGeometry;
  confidence?: number;
  source: 'human' | 'model';
  created_by: string;
  created_at: string;
}
