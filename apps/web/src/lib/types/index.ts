/**
 * TypeScript type definitions for Echoroo API
 * Auto-generated from OpenAPI specification
 */

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
 * Project entity
 */
export interface Project {
  id: string;
  name: string;
  description?: string;
  target_taxa?: string;
  visibility: ProjectVisibility;
  owner: User;
  created_at: string;
  updated_at: string;
}

/**
 * Project response (alias for Project)
 */
export type ProjectResponse = Project;

/**
 * Project create request
 */
export interface ProjectCreateRequest {
  name: string;
  description?: string;
  target_taxa?: string;
  visibility?: ProjectVisibility;
}

/**
 * Project update request
 */
export interface ProjectUpdateRequest {
  name?: string;
  description?: string;
  target_taxa?: string;
  visibility?: ProjectVisibility;
}

/**
 * Project list response with pagination
 */
export interface ProjectListResponse extends PaginationMeta {
  items: Project[];
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
 * System settings update request
 */
export interface SystemSettingsUpdateRequest {
  registration_mode?: 'open' | 'invitation';
  allow_registration?: boolean;
  session_timeout_minutes?: number;
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
// Legacy Types (for backwards compatibility)
// TODO: Migrate existing code to use new types above
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
// Additional Application Types
// ============================================

/**
 * Recording entity
 * Note: This is not in the Administration API spec but used in the app
 */
export interface Recording {
  id: string;
  filename: string;
  path: string;
  duration: number;
  sample_rate: number;
  channels: number;
  datetime?: string;
  site_id?: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

/**
 * Clip entity
 * Note: This is not in the Administration API spec but used in the app
 */
export interface Clip {
  id: string;
  recording_id: string;
  start_time: number;
  end_time: number;
  embedding?: number[];
  created_at: string;
}

/**
 * Tag category enum
 */
export type TagCategory = 'SPECIES' | 'SOUND_TYPE' | 'QUALITY';

/**
 * Tag entity
 * Note: This is not in the Administration API spec but used in the app
 */
export interface Tag {
  id: string;
  name: string;
  category: TagCategory;
  parent_id?: string;
  created_at: string;
}

/**
 * Annotation source enum
 */
export type AnnotationSource = 'HUMAN' | 'MODEL';

/**
 * Annotation geometry type enum
 */
export type AnnotationGeometryType = 'BoundingBox' | 'TimeInterval' | 'Point';

/**
 * Annotation geometry
 */
export interface AnnotationGeometry {
  type: AnnotationGeometryType;
  coordinates: number[];
}

/**
 * Annotation entity
 * Note: This is not in the Administration API spec but used in the app
 */
export interface Annotation {
  id: string;
  clip_id: string;
  tag_id: string;
  geometry: AnnotationGeometry;
  confidence?: number;
  source: AnnotationSource;
  created_by: string;
  created_at: string;
}

/**
 * Dataset entity
 * Note: This is not in the Administration API spec but used in the app
 */
export interface Dataset {
  id: string;
  name: string;
  project_id: string;
  created_at: string;
}

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
