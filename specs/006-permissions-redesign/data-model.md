# Data Model: 権限・公開レベル再設計

**Branch**: `006-permissions-redesign`
**Date**: 2026-04-24
**Input**: [spec.md Rev.3.2](./spec.md) 主要エンティティ + [research.md](./research.md) 技術決定

本ドキュメントは spec の主要エンティティを SQLAlchemy 2.0 + Alembic 実装レベルに具体化する。Alembic は既存 24 migration を全消去して **単一 baseline `0001_initial_permissions_redesign.py`** で再構築（spec FR-113）。

## 0. エンティティ一覧表

本リデザインで扱う 22 エンティティ（新規 16 + 改修 6）。すべて同一粒度（columns / FK / CHECK / Index）で §3 に展開する。

| # | エンティティ | 状態 | 主な用途 | spec 根拠 |
|---|---|---|---|---|
| 1 | `users` | 改修 | ユーザー基本情報 + 2FA + security_stamp | FR-050〜073、FR-105 |
| 2 | `superusers` | 新規 | プラットフォーム運用権限の別枠 | FR-111 |
| 3 | `superuser_approval_requests` | 新規 | M-of-N 承認 workflow | FR-111 |
| 4 | `projects` | 改修 | visibility 2値 + restricted_config + license + status | FR-001〜FR-024 |
| 5 | `project_license_history` | 新規 | ライセンス変更履歴（遡及しない） | FR-087 |
| 6 | `project_members` | 改修 | role + expires_at（Viewer 期限対応） | FR-004 |
| 7 | `project_invitations` | 改修 | kind (member/trusted) 統一、pending/token_hash | FR-047〜056 |
| 8 | `project_trusted_users` | 新規 | Authenticated への capability overlay | FR-041〜046 |
| 9 | `project_taxon_sensitivity_overrides` | 新規 | 種 × プロジェクトの sensitivity override | FR-033〜034 |
| 10 | `sites` | 改修 | h3_index_member 保持、raw lat/lng 非保持 | FR-028〜031 |
| 11 | `recordings` | 改修 | site_id FK、lat/lng 非保持、gps_stripped flag | FR-028a |
| 12 | `taxon_sensitivities` | 新規 | IUCN + MOE RDB のグローバルリスト | FR-032 |
| 13 | `iucn_sync_attempts` | 新規 | 週次同期の記録 + 2 週失敗 fail-safe | FR-036 |
| 14 | `annotation_votes` | 改修 | source + project_role_at_vote（immutable） | FR-037 |
| 15 | `annotation_comments` | 改修 | source（member/guest/trusted バッジ用） | FR-040 |
| 16 | `api_keys` | 新規 | scope + project_id + allowed_ips + prefix/hashed_secret | FR-074〜084 |
| 17 | `project_audit_log` | 新規 | プロジェクト内完結イベント、hash chain、raw PII なし | FR-088, FR-090〜096 |
| 18 | `platform_audit_log` | 新規 | ユーザーアカウント/認証/superuser 操作、hash chain、raw PII なし | FR-089, FR-090〜096 |
| 19 | `outbox_events` | 新規 | at-least-once 配信 + at-most-once log、retry policy | FR-076a、research §6 |
| 20 | `system_settings` | 新規 | superuser 調整可能な閾値 / デフォルト値 | NFR-006 |
| 21 | `dek_rewrap_failures` | 新規 | DEK 月次 rewrap の失敗追跡 | Runbook 鍵ローテ |
| 22 | `wipe_guard` | 新規 | wipe 2 度目実行防止の 3 点一致ガード | FR-114 |

追加の 既存テーブル（本リデザインで大きな変更なし、**参考**）:
- `datasets` / `annotations` / `tags`: 既存のカラム体系を維持、本リデザインでは `project_id` の参照整合性と `check_project_access` 経由の権限チェック以外の変更なし
- `detection_runs`, `recordings_segments`, etc.: 既存 schema 維持

---

## 1. Enum 定義

全て PostgreSQL の `CREATE TYPE ... AS ENUM` + SQLAlchemy `Enum(..., native_enum=True)` で実装:

```python
class ProjectVisibility(StrEnum):
    PUBLIC = "public"
    RESTRICTED = "restricted"

class ProjectStatus(StrEnum):
    ACTIVE = "active"
    DORMANT = "dormant"
    ARCHIVED = "archived"

class ProjectMemberRole(StrEnum):
    VIEWER = "viewer"
    MEMBER = "member"
    ADMIN = "admin"

class ProjectLicense(StrEnum):
    CC0 = "CC0"
    CC_BY = "CC-BY"
    CC_BY_NC = "CC-BY-NC"
    CC_BY_SA = "CC-BY-SA"

class InvitationKind(StrEnum):
    MEMBER = "member"
    TRUSTED = "trusted"

class InvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    REVOKED = "revoked"

class TrustedUserStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"

class AnnotationVoteSource(StrEnum):
    MEMBER = "member"
    GUEST_AUTHENTICATED = "guest_authenticated"
    TRUSTED_USER = "trusted_user"

class TaxonSensitivitySource(StrEnum):
    IUCN = "iucn"
    MOE_RDB = "moe_rdb"
    MANUAL = "manual"

class TaxonOverrideDirection(StrEnum):
    STRICTER = "stricter"
    LOOSER = "looser"

class TaxonOverrideApprovalStatus(StrEnum):
    APPLIED = "applied"
    PENDING_SUPERUSER_APPROVAL = "pending_superuser_approval"
    REJECTED = "rejected"

class Permission(StrEnum):
    # Project 閲覧系
    VIEW_PROJECT_METADATA = "view_project_metadata"
    VIEW_DATASET_LIST = "view_dataset_list"
    VIEW_MEDIA = "view_media"
    VIEW_DETECTION = "view_detection"
    VIEW_PRECISE_LOCATION = "view_precise_location"
    VIEW_AUDIT_LOG = "view_audit_log"
    # Project 検索・出力系
    SEARCH_WITHIN_PROJECT = "search_within_project"
    # SEARCH_CROSS_PROJECT は User-scope（USER_SCOPE_PERMISSIONS に含まれる）
    # 単一 project resource では判定できないため、is_allowed で resource=None ブランチ経由
    SEARCH_CROSS_PROJECT = "search_cross_project"
    DOWNLOAD = "download"
    EXPORT = "export"
    # Project 編集系
    VOTE = "vote"
    COMMENT = "comment"
    CREATE_TAG = "create_tag"
    ANNOTATE = "annotate"
    UPLOAD = "upload"
    MANAGE_SITE = "manage_site"
    MANAGE_DATASET = "manage_dataset"
    RUN_INFERENCE = "run_inference"
    TRAIN_MODEL = "train_model"
    # Project 管理系
    MANAGE_MEMBERS = "manage_members"
    MANAGE_TRUSTED = "manage_trusted"
    EDIT_PROJECT = "edit_project"
    MANAGE_LICENSE = "manage_license"
    DELETE_PROJECT = "delete_project"
    TRANSFER_OWNERSHIP = "transfer_ownership"
    OVERRIDE_TAXON_SENSITIVITY = "override_taxon_sensitivity"
    # User 自己管理（Matrix 外）
    MANAGE_API_KEY = "manage_api_key"
    MANAGE_2FA = "manage_2fa"

class ApiKeyScopeCategory(StrEnum):
    READ_ONLY = "read_only"
    VOTE = "vote"
    UPLOAD = "upload"
```

### Permission カテゴリ分類

Permission は 2 つのスコープに分類される:

| カテゴリ | Permission | 判定 resource | Matrix 登録 |
|---|---|---|---|
| **Project-scope**（25 個）| VIEW_*（AUDIT_LOG 除く）, SEARCH_WITHIN_PROJECT, DOWNLOAD, EXPORT, VOTE, COMMENT, CREATE_TAG, ANNOTATE, UPLOAD, MANAGE_SITE, MANAGE_DATASET, RUN_INFERENCE, TRAIN_MODEL, MANAGE_MEMBERS, MANAGE_TRUSTED, VIEW_AUDIT_LOG, EDIT_PROJECT, MANAGE_LICENSE, DELETE_PROJECT, TRANSFER_OWNERSHIP, OVERRIDE_TAXON_SENSITIVITY | `project: Project` | ✅ Canonical Matrix |
| **User-scope**（3 個）| MANAGE_API_KEY, MANAGE_2FA, **SEARCH_CROSS_PROJECT** | `resource=None` | ❌ Matrix 外、user のログイン状態のみで判定 |

```python
USER_SCOPE_PERMISSIONS: frozenset[Permission] = frozenset({
    Permission.MANAGE_API_KEY,
    Permission.MANAGE_2FA,
    Permission.SEARCH_CROSS_PROJECT,
})
```

`is_allowed(user, project=None, action)` のブランチ:
- `action.required_permission in USER_SCOPE_PERMISSIONS`: `project` 参照せず、user がログイン済みなら許可（SEARCH_CROSS_PROJECT はさらに Guest 除外）
- それ以外: 通常の Project-scope ロジック（Canonical Matrix + Restricted toggle + Trusted overlay）

SEARCH_CROSS_PROJECT を持つユーザーが検索を発火した場合、Response は各 project の `allow_detection_view=ON` を filter して per-project aggregation を返す（`SearchGate.execute` が内部で `WHERE allow_detection_view=true` を SQL レベルで適用、FR-025）。

**Canonical Matrix では SEARCH_CROSS_PROJECT を「Guest ❌、Authenticated 以上 ✅」として扱う**（Matrix 列としては表示するが、Project-scope 判定ロジックは bypass）。

---

## 2. Migration Order（単一 baseline 内での作成順）

PostgreSQL FK 依存関係 + SQLAlchemy event listener の load 順に従い、以下の順で CREATE:

1. Enum 型（上記 11 個）
2. `users` + `superusers` + `superuser_approval_requests`
3. **`outbox_events`**（依存なし、app 起動時の ORM event listener がここに INSERT する可能性があるため**テーブル系を作る前**に早期作成）
4. `system_settings`
5. `projects` + `project_license_history`
6. `project_members`
7. `project_invitations`
8. `project_trusted_users`
9. `project_taxon_sensitivity_overrides`
10. `sites` + `datasets` + `recordings` + `detections` + `annotations` + `tags`（既存概念を改修）
11. `annotation_votes` + `annotation_comments`
12. `taxon_sensitivities` + `iucn_sync_attempts`
13. `api_keys`
14. `project_audit_log` + `platform_audit_log`
15. `dek_rewrap_failures`
16. `wipe_guard`（2 度目実行防止用、FR-114）
17. 全 Index / Trigger（後述）

---

## 3. エンティティ詳細

### 3.1 `users`

```python
class User(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)  # argon2
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 2FA (FR-051, FR-066, FR-068)
    two_factor_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    two_factor_secret_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)  # AES-256-GCM + KMS envelope
    two_factor_secret_dek_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    two_factor_backup_codes_hashed: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)  # Argon2id 各要素
    # Session revocation (FR-055, FR-071)
    security_stamp: Mapped[str] = mapped_column(String(64), default=lambda: secrets.token_hex(32), nullable=False)
    # Dormancy / activity (FR-060)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_first_party_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    registered_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)  # e.g. "Asia/Tokyo"
    # GDPR (FR-105)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Cooldown (FR-073)
    two_factor_reset_cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

**Index**: `email`, `deleted_at`（soft delete クエリ用）

---

### 3.2 `superusers`（FR-111 の独立テーブル）

```python
class Superuser(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "superusers"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    added_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)  # 初期 superuser は NULL
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    webauthn_credentials: Mapped[list[dict]] = mapped_column(JSONB, default=list, nullable=False)  # 2 本登録必須
    allowed_ip_cidrs: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
```

**Index**: `user_id` (unique), `revoked_at`

**DB Trigger** (FR-111a): `BEFORE DELETE ON superusers` で「残 1 名の DELETE」を block（creator_founder override 用の session variable `app.superuser_deletion_override = 'true'` が設定されていない限り）

---

### 3.3 `superuser_approval_requests`（FR-111 M-of-N）

```python
class SuperuserApprovalRequest(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "superuser_approval_requests"
    action: Mapped[str] = mapped_column(String(100), nullable=False)  # "superuser_add", "looser_override_approve", etc.
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False)
    requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("superusers.id"), nullable=False)
    approvals: Mapped[list[dict]] = mapped_column(JSONB, default=list, nullable=False)  # [{"superuser_id": ..., "approved_at": ...}]
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

---

### 3.4 `projects`

```python
class Project(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    visibility: Mapped[ProjectVisibility] = mapped_column(
        Enum(ProjectVisibility, native_enum=True), nullable=False
    )
    license: Mapped[ProjectLicense] = mapped_column(
        Enum(ProjectLicense, native_enum=True), nullable=False
    )  # FR-085 必須
    restricted_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    restricted_config_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, native_enum=True), default=ProjectStatus.ACTIVE, nullable=False
    )
    dormant_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 既存の review フィールドは残す（spec の変更対象外）
    review_min_votes: Mapped[int] = mapped_column(Integer, default=2)
    review_consensus_threshold: Mapped[float] = mapped_column(Float, default=0.667)
```

**CHECK 制約** (PostgreSQL `jsonb_schema` or CHECK):
```sql
CHECK (
  restricted_config IS NOT NULL
  AND jsonb_typeof(restricted_config) = 'object'
  AND (visibility != 'restricted' OR (
    -- restricted 時は必須キーが揃っていること
    restricted_config ? 'allow_media_playback' AND
    restricted_config ? 'allow_detection_view' AND
    restricted_config ? 'mask_species_in_detection' AND
    restricted_config ? 'allow_download' AND
    restricted_config ? 'allow_export' AND
    restricted_config ? 'allow_voting_and_comments' AND
    restricted_config ? 'public_location_precision_h3_res' AND
    restricted_config ? 'allow_precise_location_to_viewer'
  ))
)
```

**Index**: `visibility`, `status`, `owner_id`, `(status, dormant_since)`（dormancy batch 用）

---

### 3.5 `project_license_history`

```python
class ProjectLicenseHistory(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "project_license_history"
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    old_license: Mapped[ProjectLicense | None] = mapped_column(Enum(ProjectLicense, native_enum=True), nullable=True)
    new_license: Mapped[ProjectLicense] = mapped_column(Enum(ProjectLicense, native_enum=True), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    changed_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
```

**Index**: `(project_id, changed_at DESC)`（最新取得用）

---

### 3.6 `project_members`

```python
class ProjectMember(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "project_members"
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    role: Mapped[ProjectMemberRole] = mapped_column(Enum(ProjectMemberRole, native_enum=True), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    invited_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # Viewer 期限
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

**Unique**: `(project_id, user_id)` where `removed_at IS NULL`
**Index**: `(project_id, role)`, `(user_id, project_id)`

---

### 3.7 `project_invitations`（FR-047〜056）

```python
class ProjectInvitation(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "project_invitations"
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[InvitationKind] = mapped_column(Enum(InvitationKind, native_enum=True), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 30 日後 null 化（FR-106）
    email_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # HMAC-SHA256 keyed hash
    role: Mapped[ProjectMemberRole | None] = mapped_column(
        Enum(ProjectMemberRole, native_enum=True), nullable=True
    )  # kind='member' のみ
    granted_permissions: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)  # kind='trusted' のみ
    trusted_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)  # kind='trusted' のみ
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)  # SHA-256(token)
    invited_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # 招待リンクの期限（7日）
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    declined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[InvitationStatus] = mapped_column(
        Enum(InvitationStatus, native_enum=True), default=InvitationStatus.PENDING, nullable=False
    )
```

**CHECK 制約** (FR-048 改訂版 + security H-1 status 整合):
```sql
-- kind × フィールド整合
CHECK (
  kind IS NOT NULL AND status IS NOT NULL AND
  (
    (kind = 'member'
      AND role IS NOT NULL
      AND granted_permissions IS NULL
      AND trusted_duration_seconds IS NULL)
    OR
    (kind = 'trusted'
      AND role IS NULL
      AND jsonb_typeof(granted_permissions) = 'array'
      AND trusted_duration_seconds IS NOT NULL
      AND trusted_duration_seconds BETWEEN 1 AND 31536000)
  )
)

-- status × *_at タイムスタンプ整合（security H-1）
CHECK (
  (status = 'accepted'  AND accepted_at IS NOT NULL AND declined_at IS NULL AND revoked_at IS NULL)
  OR (status = 'declined' AND declined_at IS NOT NULL AND accepted_at IS NULL AND revoked_at IS NULL)
  OR (status = 'revoked'  AND revoked_at IS NOT NULL)
  OR (status = 'pending'  AND accepted_at IS NULL AND declined_at IS NULL AND revoked_at IS NULL)
  OR (status = 'expired'  AND accepted_at IS NULL AND declined_at IS NULL)
)
```

**Unique Index**: `(project_id, email_hash)` WHERE `status='pending'`（FR-049、kind 混在防止）
**Index**: `token_hash` (unique)、`(status, expires_at)`（expired バッチ用）

---

### 3.8 `project_trusted_users`（FR-041〜046）

```python
class ProjectTrustedUser(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "project_trusted_users"
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    invitation_id: Mapped[UUID] = mapped_column(ForeignKey("project_invitations.id"), nullable=False)
    granted_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[TrustedUserStatus] = mapped_column(
        Enum(TrustedUserStatus, native_enum=True), default=TrustedUserStatus.ACTIVE, nullable=False
    )
    granted_permissions: Mapped[list[str]] = mapped_column(JSONB, nullable=False)  # Permission 配列
    email_at_invitation: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 90 日後 null 化（FR-108）
    email_at_invitation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

**CHECK 制約**:
```sql
CHECK (jsonb_typeof(granted_permissions) = 'array' AND jsonb_array_length(granted_permissions) > 0)
CHECK (expires_at > granted_at AND expires_at <= granted_at + INTERVAL '1 year')
```

**Index**: `(project_id, user_id, status)`（active trusted lookup）、`(status, expires_at)`（expire バッチ）

---

### 3.9 `project_taxon_sensitivity_overrides`（FR-033〜034）

```python
class ProjectTaxonSensitivityOverride(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "project_taxon_sensitivity_overrides"
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    taxon_id: Mapped[str] = mapped_column(String(64), nullable=False)  # GBIF species key
    sensitivity_h3_res: Mapped[int] = mapped_column(Integer, nullable=False)
    direction: Mapped[TaxonOverrideDirection] = mapped_column(Enum(TaxonOverrideDirection, native_enum=True), nullable=False)
    approval_status: Mapped[TaxonOverrideApprovalStatus] = mapped_column(
        Enum(TaxonOverrideApprovalStatus, native_enum=True),
        default=TaxonOverrideApprovalStatus.APPLIED,  # stricter は即時 applied、looser は pending_superuser_approval
        nullable=False,
    )
    requested_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    approved_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("superusers.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
```

**CHECK 制約**:
```sql
-- spec FR-027 の離散値に統一（2=HIDDEN相当、5=VERY_COARSE、7=COARSE、9=OPEN、15=MEMBER 精密）
CHECK (sensitivity_h3_res IN (2, 5, 7, 9, 15))
CHECK (
  (direction = 'stricter' AND approval_status = 'applied')
  OR
  (direction = 'looser' AND approval_status IN ('pending_superuser_approval', 'applied', 'rejected'))
)
```

**Unique**: `(project_id, taxon_id, approval_status)` for `approval_status='applied'`（1 種 1 override）
**Index**: `(taxon_id, approval_status)`（bulk preload 用）

---

### 3.10 `sites`（既存を改修、生 lat/lng カラム削除）

```python
class Site(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "sites"
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    h3_index_member: Mapped[str] = mapped_column(String(32), nullable=False)
    h3_index_member_resolution: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    # **latitude / longitude カラムは存在しない**（FR-031）
```

**CHECK 制約**: `h3_index_member_resolution IN (9, 15)`（member は精密のみ、spec NFR-003 デフォルト 15、9 は低精度センサー用）
**Unique**: `(project_id, name)`、`(project_id, h3_index_member)`
**Index**: `h3_index_member`（bulk lookup）

---

### 3.11 `recordings`（既存を改修、lat/lng 非保持確認）

既存の Recording モデルを維持（Explore 調査で確認、`latitude` / `longitude` カラムは既に存在しない）。`site_id` FK 経由で位置情報を取得。`h3_index_member` / `h3_index_member_resolution` カラムは Recording 側にも追加（録音機材が移動する場合に Site と異なる hex を持つ余地を残す、nullable）:

```python
class Recording(UUIDMixin, TimestampMixin, Base):
    # 既存カラム + 以下を追加
    h3_index_member: Mapped[str | None] = mapped_column(String(32), nullable=True)  # NULL なら site.h3_index_member を使用
    h3_index_member_resolution: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gps_stripped: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # EXIF strip 監視用（FR-028a）
```

---

### 3.12 `annotation_votes`（FR-037〜040）

既存の AnnotationVote に以下を追加:

```python
class AnnotationVote(UUIDMixin, TimestampMixin, Base):
    # 既存カラム + 以下を追加
    source: Mapped[AnnotationVoteSource] = mapped_column(
        Enum(AnnotationVoteSource, native_enum=True), nullable=False
    )
    project_role_at_vote: Mapped[ProjectMemberRole | None] = mapped_column(
        Enum(ProjectMemberRole, native_enum=True), nullable=True
    )  # member のみ保存、それ以外は NULL
```

**CHECK 制約**:
```sql
CHECK (
  (source = 'member' AND project_role_at_vote IS NOT NULL)
  OR
  (source IN ('guest_authenticated', 'trusted_user') AND project_role_at_vote IS NULL)
)
```

---

### 3.13 `annotation_comments`

既存の AnnotationComment に `source` を追加（`AnnotationVote` と同じ enum）。

---

### 3.14 `taxon_sensitivities`（FR-032、グローバル）

```python
class TaxonSensitivity(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "taxon_sensitivities"
    taxon_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[TaxonSensitivitySource] = mapped_column(
        Enum(TaxonSensitivitySource, native_enum=True), nullable=False
    )
    category: Mapped[str | None] = mapped_column(String(10), nullable=True)  # "CR", "EN", "VU", "NT", "LC"
    sensitivity_h3_res: Mapped[int] = mapped_column(Integer, nullable=False)  # 推奨値は category から導出
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
```

**CHECK 制約** (spec FR-027 離散値統一):
```sql
CHECK (sensitivity_h3_res IN (2, 5, 7, 9, 15))
```

**Unique**: `(taxon_id, source)`
**Index**: `taxon_id`（bulk preload）、`(source, updated_at)`（IUCN sync diff）

---

### 3.15 `iucn_sync_attempts`

```python
class IucnSyncAttempt(UUIDMixin, Base):
    __tablename__ = "iucn_sync_attempts"
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # "success", "failure"
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    loosened_species_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # sanity check 用
```

**Index**: `(status, started_at DESC)`

---

### 3.16 `api_keys`

```python
class ApiKey(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "api_keys"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    prefix: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)  # "ek_live_xxxxxxxx"
    hashed_secret: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA-256 + per-user salt
    granted_permissions: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    allowed_ip_cidrs: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scope_violation_count_10min: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ip_violation_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
```

**CHECK 制約**:
```sql
CHECK (expires_at > created_at AND expires_at <= created_at + INTERVAL '2 years')
CHECK (jsonb_typeof(granted_permissions) = 'array')
```

**Index**: `prefix` (unique)、`(user_id, revoked_at)`、`(project_id, revoked_at)`、`(expires_at)` (expire batch)

---

### 3.17 `project_audit_log` / `platform_audit_log`（FR-088〜096）

両テーブル同一構造:

```python
class ProjectAuditLog(UUIDMixin, Base):
    __tablename__ = "project_audit_log"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_user_id_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # HMAC-SHA256(pii_hash_key, actor_user_id)
    # project_id は nullable=True。運用行では常に非 NULL、genesis 行のみ NULL。CHECK 制約で強制
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g. "project.member_added", "project.toggle_changed"
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # sanitized, FR-091a
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    ip_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_agent_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class PlatformAuditLog(UUIDMixin, Base):
    __tablename__ = "platform_audit_log"
    # 構造は ProjectAuditLog と同一だが project_id カラムは存在しない（platform-scope のみ）
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_user_id_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    # e.g. "auth.login", "auth.2fa_challenge", "auth.2fa_reset_by_superuser",
    #      "api_key.created", "api_key.auto_revoked_on_member_removal",
    #      "superuser.added", "superuser.break_glass_activated",
    #      "superuser.count_changed", "platform.iucn_force_resync"
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    ip_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_agent_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False)
```

**CHECK 制約**（project_audit_log のみ、genesis 例外）:
```sql
-- project_id は genesis 行のみ NULL を許容、運用行では必須
CHECK (action = 'genesis' OR project_id IS NOT NULL)
```

**両テーブル共通の genesis row**: baseline migration の最後で
```sql
INSERT INTO project_audit_log (id, created_at, actor_user_id_hash, project_id, action, detail, request_id, ip_hash, user_agent_hash, before, after, prev_hash, row_hash)
VALUES (gen_random_uuid(), now(), repeat('0', 64), NULL, 'genesis', '{}'::jsonb, 'genesis', repeat('0', 64), repeat('0', 64), NULL, NULL, repeat('0', 64), compute_genesis_row_hash());
INSERT INTO platform_audit_log (id, created_at, actor_user_id_hash, action, detail, request_id, ip_hash, user_agent_hash, before, after, prev_hash, row_hash)
VALUES (gen_random_uuid(), now(), repeat('0', 64), 'genesis', '{}'::jsonb, 'genesis', repeat('0', 64), repeat('0', 64), NULL, NULL, repeat('0', 64), compute_genesis_row_hash());
```
実装では Alembic の `op.create_table` 後に `op.execute("...")` で genesis INSERT。**project_audit_log の `project_id` は genesis 以外では NOT NULL 相当**（CHECK 制約で強制）。

**PostgreSQL ACL**（FR-094）:
```sql
REVOKE UPDATE, DELETE ON project_audit_log FROM echoroo_app;
REVOKE UPDATE, DELETE ON platform_audit_log FROM echoroo_app;
-- 挿入は許可
GRANT INSERT ON project_audit_log TO echoroo_app;
GRANT INSERT ON platform_audit_log TO echoroo_app;
```

**Index**:
- `(project_id, created_at DESC)`（project audit 閲覧）
- `(action, created_at DESC)`（action type 別集計）
- `(actor_user_id_hash, created_at DESC)`（特定ユーザーの行動追跡、pii_hash_key 経由の逆引き）

**Genesis row**: 各テーブル最初の行は `prev_hash = "0000...0000"`（64 桁）、`row_hash = HMAC-SHA256(chain_key, "0000...0000" || canonical_row)`

---

### 3.18 `outbox_events`（FR-076a + research §6）

```python
class OutboxEvent(UUIDMixin, Base):
    __tablename__ = "outbox_events"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)  # "api_key_revoke_on_member_removal" 等
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    # pending → processing → done / failed → dead_letter（MAX_RETRY 超過）
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # at-most-once log guarantee（security H-5）: audit_log 書き込みで dedupe 用
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
```

**Retry policy**:
- `MAX_RETRY = 5`
- `BACKOFF_SCHEDULE = [1, 4, 16, 64, 256]`（秒）
- 5 回失敗で `status=dead_letter` に遷移、superuser に PagerDuty alert
- worker poll: `SELECT * FROM outbox_events WHERE status='pending' AND (next_retry_at IS NULL OR next_retry_at <= now()) ORDER BY created_at LIMIT N FOR UPDATE SKIP LOCKED`
- worker 並列度: 4 pod、poll 間隔 1s、SLO（FR-076d）: p95 ≤ 10s, p99 ≤ 60s

**at-most-once log guarantee**:
- worker は処理開始時に `idempotency_key` を計算（例: `f"{event_type}:{payload.user_id}:{payload.project_id}:{outbox_id}"`）
- audit log 書き込み前に `SELECT ... WHERE detail->>'outbox_idempotency_key' = :key` で重複検出
- 重複なら INSERT skip、`status=done` に直接遷移

**Index**:
- `(status, next_retry_at) WHERE status IN ('pending', 'processing')`（worker poll）
- `(event_type, created_at DESC)`（type 別集計）
- `idempotency_key` (unique)

---

### 3.19 `system_settings`（NFR-006）

```python
class SystemSettings(Base):
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_by_id: Mapped[UUID] = mapped_column(ForeignKey("superusers.id"), nullable=False)
```

初期値（baseline migration で seed）:
- `trusted_default_duration_seconds`: 7776000 (90 日)
- `trusted_max_duration_seconds`: 31536000 (1 年)
- `dormant_threshold_seconds`: 31622400 (366 日、1 日 grace)
- `api_key_rotation_warn_days`: 90
- `api_key_scope_violation_window_seconds`: 600
- `api_key_scope_violation_threshold`: 10
- `totp_verify_window_per_15min`: 5
- `totp_lockout_threshold`: 10

---

### 3.20 `dek_rewrap_failures`（Runbook 鍵ローテ）

```python
class DekRewrapFailure(UUIDMixin, Base):
    __tablename__ = "dek_rewrap_failures"
    table_name: Mapped[str] = mapped_column(String(100), nullable=False)
    row_id: Mapped[UUID] = mapped_column(UUID, nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    error_detail: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

---

### 3.21 `wipe_guard`（FR-114）

```python
class WipeGuard(Base):
    __tablename__ = "wipe_guard"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    wiped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    wiped_by_superuser_ids: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
```

**CHECK**: `id = 1`（シングルトン）。初期 baseline migration では row を挿入しない。wipe 実行時に superuser 2 名 + creator_founder 承認とともに INSERT、2 度目実行時は row 存在で abort。

---

## 4. Trigger / DB レベルロジック

### 4.1 Superuser 1→0 block（FR-111a）

```sql
CREATE OR REPLACE FUNCTION prevent_last_superuser_deletion()
RETURNS trigger AS $$
BEGIN
    -- application DB user (echoroo_app) のみを対象、Alembic migration role は除外
    -- session variable injection 対策: superuser_deletion_override は SP 内でのみセットされる経路に限定
    IF current_user = 'echoroo_app' THEN
        IF (SELECT COUNT(*) FROM superusers WHERE revoked_at IS NULL) <= 1 THEN
            IF current_setting('app.superuser_deletion_override', true) IS DISTINCT FROM 'true' THEN
                RAISE EXCEPTION 'Cannot delete last superuser without creator_founder override';
            END IF;
        END IF;
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER superuser_last_protection
BEFORE DELETE ON superusers
FOR EACH ROW
EXECUTE FUNCTION prevent_last_superuser_deletion();
```

**二重防御**（security H-2）:
- アプリ層の `SuperuserService.remove_superuser(user_id, founder_webauthn_assertion)` が stored procedure 的に session variable `app.superuser_deletion_override` を set する経路のみを許容
- trigger は `current_user = 'echoroo_app'` に限定、migration role (`echoroo_migrator`) や PostgreSQL superuser role では trigger skip（rollback migration を可能にする）
- session variable の set は BEGIN/COMMIT の中で行い、外部クライアント（psql 直接接続）からは不可（`pg_hba.conf` の role 制限）
- Test: `tests/security/race_conditions/test_superuser_last_protection.py` で DB role 別の挙動を検証

### 4.2 Audit log UPDATE / DELETE 禁止（FR-094）

前述の REVOKE で実現。ただし安全のため trigger で二重防御:

```sql
CREATE OR REPLACE FUNCTION forbid_audit_log_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER project_audit_log_immutable
BEFORE UPDATE OR DELETE ON project_audit_log
FOR EACH ROW
EXECUTE FUNCTION forbid_audit_log_mutation();

CREATE TRIGGER platform_audit_log_immutable
BEFORE UPDATE OR DELETE ON platform_audit_log
FOR EACH ROW
EXECUTE FUNCTION forbid_audit_log_mutation();
```

### 4.3 ApiKey 離脱時自動 revoke（FR-076a）

`ProjectMember` の `removed_at` set と同一 TX で outbox_events に enqueue する SQLAlchemy ORM event hook（または DB trigger）。Python 側実装:

```python
@event.listens_for(ProjectMember, "after_update")
def enqueue_api_key_revoke(mapper, connection, target):
    if target.removed_at is not None and target.removed_at == recently_set():
        connection.execute(
            insert(OutboxEvent).values(
                event_type="api_key_revoke_on_member_removal",
                payload={"user_id": str(target.user_id), "project_id": str(target.project_id)},
            )
        )
```

---

## 5. Index 一覧（パフォーマンス向け）

NFR-001 / NFR-001a を満たすために以下の複合 index を追加:

| テーブル | Index | 用途 |
|---|---|---|
| `project_members` | `(user_id, project_id) WHERE removed_at IS NULL` | resolve_role lookup (~1ms) |
| `project_trusted_users` | `(user_id, project_id, status)` | active trusted lookup |
| `taxon_sensitivities` | `taxon_id` | bulk preload (WHERE IN) |
| `project_taxon_sensitivity_overrides` | `(project_id, taxon_id, approval_status)` | override lookup |
| `projects` | `(status, dormant_since DESC)` | dormancy batch |
| `api_keys` | `(expires_at) WHERE revoked_at IS NULL` | expire batch |
| `outbox_events` | `(status, next_retry_at) WHERE status IN ('pending', 'processing')` | worker poll（next_retry_at IS NULL なら即時 poll、非 NULL なら backoff 後） |

---

## 6. データ型サイズ見積もり

| テーブル | 初期行数 | 1 年後 |
|---|---|---|
| `users` | 100 | 1,000 |
| `projects` | 50 | 500 |
| `project_members` | 500 | 5,000 |
| `recordings` | 10k | 100k |
| `detections` | 1M | 10M |
| `annotation_votes` | 500k | 5M |
| `project_audit_log` | 10k | 500k |
| `platform_audit_log` | 100k | 5M |
| `taxon_sensitivities` | 10k | 20k (IUCN 更新含む) |

1 年後で DB サイズは ~50 GB、PostgreSQL 16 の single instance で十分対応可（IOPS と Connection Pool を適切に設定）。

---

## 7. SQLAlchemy Session / Connection

spec NFR-001 / NFR-001a を満たすため:

- **async session pool**: 20 connections（`poolclass=NullPool` は使わない、pgBouncer 経由での `transaction` pooling mode 想定）
- **request-scope session**: `Depends(get_db)` で 1 リクエスト 1 session
- **Bulk preload**: `session.execute(select(TaxonSensitivity).where(TaxonSensitivity.taxon_id.in_(ids)))` を Recording list endpoint の最初に実行、dict 化して `compute_effective_resolution` に引数渡し

---

## 8. Alembic Baseline Migration の検証

baseline migration 完成後、以下を CI で verify:

1. `alembic upgrade head` が error なしで完走
2. ORM model と DB schema が一致（`alembic check` で autogenerate diff がゼロ）
3. 全 CHECK 制約 / unique / index が期待通り作成されている（`pg_catalog` クエリで assertion）
4. Superuser trigger が動作（unit test で INSERT + DELETE シナリオ）
5. Audit log の REVOKE が application DB user に適用（UPDATE / DELETE で error）

---

## 9. 将来拡張の余地

spec 非目標で保留した機能（Organization、Darwin Core full、ユーザーブロック、SSE push 等）を将来追加する際の migration 互換性:

- **Organization**: `Project.owner_id` を polymorphic にする余地として、将来 `owner_type` カラム追加（現状は `User` 固定）
- **Darwin Core full**: `ProjectAuditLog.detail` JSONB に additional fields を追加可能
- **ユーザーブロック**: `user_blocks` 新規テーブルで実装可能、既存 schema 影響なし

---

**Data Model Status**: ✅ 完了、`contracts/` 作成へ進行可
