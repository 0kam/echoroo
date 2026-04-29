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
| 10 | `sites` | 改修 | h3_index_member 保持、raw lat/lng 非保持。v5-final §2.4 と整合済 (no-op)。Phase 13 P4 で sites cutover (14 ファイル一括 rename) | FR-028〜031 |
| 11 | `recordings` | 改修 | dataset_id 経由、lat/lng 非保持、gps_stripped flag、auto-obscure 3 列。legacy 命名 (`duration` / `samplerate` / `datetime`) に統一、API は `duration_seconds` alias で wire compat 維持。Phase 13 P3 で `0009_recordings_legacy_rename.py` 適用 | FR-028a |
| 12 | `taxon_sensitivities` | 新規 | IUCN + MOE RDB のグローバルリスト | FR-032 |
| 13 | `iucn_sync_attempts` | 新規 | 週次同期の記録 + 2 週失敗 fail-safe | FR-036 |
| 14 | `annotation_votes` | 改修 | **DB 真** (`voter_user_id` + `project_id` 必須、`vote` smallint)。ORM 側は Phase 13 P1.5 で rename + project_id 追加 + vote smallint 化 (drift reconcile) | FR-037 |
| 15 | `annotation_comments` | 改修 | source（member/guest/trusted バッジ用）。整合済 no-op (Phase 13 で確認のみ) | FR-040 |
| 16 | `api_keys` | 新規 | scope + project_id + allowed_ips + prefix/hashed_secret | FR-074〜084 |
| 17 | `project_audit_log` | 新規 | プロジェクト内完結イベント、hash chain、raw PII なし | FR-088, FR-090〜096 |
| 18 | `platform_audit_log` | 新規 | ユーザーアカウント/認証/superuser 操作、hash chain、raw PII なし | FR-089, FR-090〜096 |
| 19 | `outbox_events` | 新規 | at-least-once 配信 + at-most-once log、retry policy | FR-076a、research §6 |
| 20 | `system_settings` | 新規 | superuser 調整可能な閾値 / デフォルト値 | NFR-006 |
| 21 | `dek_rewrap_failures` | 新規 | DEK 月次 rewrap の失敗追跡 | Runbook 鍵ローテ |
| 22 | `wipe_guard` | 新規 | wipe 2 度目実行防止の 3 点一致ガード | FR-114 |

### Phase 13 supporting tables（baseline 統合 / drift reconcile 対象）

Phase 1-12 累積編集による ORM ↔ DB ↔ spec の三方向乖離を Phase 13 で reconcile する。詳細 schema は v5-final §2.6 で「`Base.metadata` 機械抽出を真」と決定。下記テーブルは §3.22-§3.26 に展開、column 詳細は対応 ORM (`apps/api/echoroo/models/<table>.py`) を canonical とする。

| # | テーブル | 戦略 | spec 根拠 / 経緯 |
|---|---|---|---|
| 23 | `datasets` | 改修 (legacy 002-data-management から復活) | Phase 13 P2 で `0008_datasets_extension.py`、14 列追加 |
| 24 | `tags` | drift reconcile (ORM 真、taxa-based) | Phase 13 P1.5 で 5 段階 backfill (legacy_taxon_id rename → UUID 追加 → taxa.gbif_taxon_key cast lookup → FK 追加 → legacy drop) |
| 25 | `annotations` | drift reconcile (DB 真、detection-based 簡素) | Phase 13 P1.5 で ORM 縮退 (recording_id/tag_id 等削除)。recording-based 高機能 annotation 機能は Phase 14+ で `recording_annotations` 別 table 化 |
| 26 | `taxa` | 新規 (ORM 化) | Phase 13 P1 で baseline 統合 |
| 27 | `recorders` | 新規 (ORM 化) | Phase 13 P1、recordings 補助テーブル |
| 28 | `licenses` | 新規 (ORM 化) | Phase 13 P1、recordings 補助テーブル |
| 29 | `clips` | 新規 (ORM 化) | Phase 13 P1 |
| 30 | `clip_annotations` | 新規 (ORM 化) | Phase 13 P1 |
| 31 | `annotation_projects` | 新規 (ORM 化) | Phase 13 P1 |
| 32 | `annotation_project_datasets` | 新規 (ORM 化) | Phase 13 P1 |
| 33 | `annotation_project_tags` | 新規 (ORM 化) | Phase 13 P1 |
| 34 | `annotation_sets` | 新規 (ORM 化) | Phase 13 P1 |
| 35 | `annotation_set_species_palette` | 新規 (ORM 化) | Phase 13 P1 |
| 36 | `annotation_segments` | 新規 (ORM 化) | Phase 13 P1 |
| 37 | `annotation_segment_notes` | 新規 (ORM 化) | Phase 13 P1 |
| 38 | `annotation_tasks` | 新規 (ORM 化) | Phase 13 P1 |
| 39 | `sound_event_annotations` | 新規 (ORM 化) | Phase 13 P1 |
| 40 | `sound_event_annotation_tags` | 新規 (ORM 化) | Phase 13 P1 |
| 41 | `clip_annotation_tags` | 新規 (ORM 化) | Phase 13 P1 |
| 42 | `time_range_annotations` | 新規 (ORM 化) | Phase 13 P1 |
| 43 | `time_range_annotation_notes` | 新規 (ORM 化) | Phase 13 P1 |
| 44 | `notes` | 新規 (ORM 化) | Phase 13 P1 |
| 45 | `custom_models` | 新規 (ORM 化) | Phase 13 P1 |
| 46 | `sampling_rounds` | 新規 (ORM 化) | Phase 13 P1 |
| 47 | `sampling_round_items` | 新規 (ORM 化) | Phase 13 P1 |
| 48 | `search_sessions` | 新規 (ORM 化) | Phase 13 P1 |
| 49 | `search_query_embeddings` | 新規 (ORM 化) | Phase 13 P1 |
| 50 | `evaluation_runs` | 新規 (ORM 化) | Phase 13 P1 |
| 51 | `evaluation_results` | 新規 (ORM 化) | Phase 13 P1 |
| 52 | `embeddings` | 新規 (ORM 化) | Phase 13 P1 |
| 53 | `upload_sessions` | 新規 (ORM 化) | Phase 13 P1 |
| 54 | `upload_files` | 新規 (ORM 化) | Phase 13 P1 |
| 55 | `detection_runs` | 改修 (ORM 化、enum 実名統一) | Phase 13 P1、`detectionrunstatus` enum |
| 56 | `detections` | 改修 (DB only → ORM 化) | Phase 13 P1 で ORM 化、`detectionsource` enum widening (`perch`, `similarity_search`, `custom_svm`, `sampling_round` 4 値追加) |

**新規 enum 16 件** (Phase 13 P0a / P1 で追加、ORM canonical 命名。Phase 13 P1 R2 致命 #1 fix で `setting_type` は `system_settings.value` の JSONB 化と同時に廃止、17 → 16 に減):
`datetimeparsestatus`, `annotation_set_status`, `annotation_segment_status`, `annotationtaskstatus`, `annotationprojectvisibility`, `reviewstatus`, `geometrytype`, `signalquality`, `consensusstatus`, `detectionrunstatus`, `uploadsessionstatus`, `uploadfilestatus`, `searchsessionstatus`, `votetype`, `custommodelstatus`, `evaluation_run_status`

**enum widening** (Phase 13 P0b、`0006a_enum_widening.py` で `autocommit_block` + `ADD VALUE IF NOT EXISTS`):
- `detectionsource`: `perch`, `similarity_search`, `custom_svm`, `sampling_round` (4 値追加)

DB only から ORM 化対象は `detections` のみ Phase 13 scope。残 10 件 (`api_keys` 旧版 / `superusers` 旧版 / 各種 audit / refresh / token テーブル等) は Phase 14+ で raw SQL → ORM 化予定。

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

### 3.11 `recordings`（既存を改修、lat/lng 非保持確認 + Phase 13 legacy rename）

既存の Recording モデルを維持（Explore 調査で確認、`latitude` / `longitude` カラムは既に存在しない）。`site_id` FK 経由で位置情報を取得。`h3_index_member` / `h3_index_member_resolution` カラムは Recording 側にも追加（録音機材が移動する場合に Site と異なる hex を持つ余地を残す、nullable）:

```python
class Recording(UUIDMixin, TimestampMixin, Base):
    # 既存カラム + 以下を追加
    h3_index_member: Mapped[str | None] = mapped_column(String(32), nullable=True)  # NULL なら site.h3_index_member を使用
    h3_index_member_resolution: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gps_stripped: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # EXIF strip 監視用（FR-028a）
```

**Phase 13 P3 legacy rename + extend** (`0009_recordings_legacy_rename.py`、v5-final §2.3、Codex review 反映で展開):

最終 schema (ORM canonical):

| Column | Type | Null | Default | 備考 |
|--------|------|------|---------|------|
| `id` | UUID | NOT NULL | `gen_random_uuid()` | PK |
| `dataset_id` | UUID | NOT NULL | — | FK `datasets.id ON DELETE CASCADE` |
| `site_id` | UUID | nullable | — | FK `sites.id ON DELETE SET NULL`、override (NULL 時は `dataset.site_id` を使用) |
| `filename` | VARCHAR(255) | NOT NULL | — | |
| `path` | VARCHAR(500) | NOT NULL | — | |
| `hash` | VARCHAR(64) | nullable | — | SHA-256 etc. |
| `duration` | FLOAT | NOT NULL | — | seconds (legacy 命名、API は `duration_seconds` alias) |
| `samplerate` | INTEGER | NOT NULL | — | Hz (legacy 命名、API は `sample_rate` alias) |
| `channels` | INTEGER | NOT NULL | — | mono=1, stereo=2 |
| `bit_depth` | INTEGER | nullable | — | |
| `datetime` | TIMESTAMPTZ | nullable | — | recording 開始時刻 (legacy 命名、API は `recorded_at` alias) |
| `datetime_parse_status` | `datetimeparsestatus` enum | NOT NULL | `'pending'` | |
| `datetime_parse_error` | TEXT | nullable | — | |
| `time_expansion` | FLOAT | NOT NULL | `1.0` | |
| `note` | TEXT | nullable | — | |
| `h3_index_member` | VARCHAR(32) | nullable | — | NULL なら site.h3_index_member 使用 |
| `h3_index_member_resolution` | INTEGER | nullable | — | NULL なら site の resolution 使用 |
| `gps_stripped` | BOOLEAN | NOT NULL | `false` | EXIF strip 監視用 (FR-028a) |
| `created_at` / `updated_at` | TIMESTAMPTZ | NOT NULL | `now()` | TimestampMixin |

**CHECK 制約**:
- `h3_index_member_resolution IS NULL OR h3_index_member_resolution IN (9, 15)`

**UNIQUE**: `(dataset_id, path)`

**Index**:
- `ix_recordings_dataset_id` on `dataset_id`
- `ix_recordings_hash` on `hash`
- `ix_recordings_datetime` on `datetime`
- `ix_recordings_dataset_id_datetime` on `(dataset_id, datetime)`
- `ix_recordings_h3_index_member` on `h3_index_member`

**不在列** (API alias のみ、DB 不在):
- `project_id` (dataset 経由で取得)
- `duration_seconds` / `sample_rate` / `recorded_at` (Pydantic alias で wire compat 維持、Phase 13 P7 で deprecation 検討、現時点では維持)
- `latitude` / `longitude` (FR-031 生 lat/lng 不在)

詳細 schema は `apps/api/echoroo/models/recording.py` を参照、`Base.metadata` 機械抽出を真とする。

---

### 3.12 `annotation_votes`（FR-037〜040、DB 真 drift reconcile）

**戦略**: DB 側を真として ORM を rename / extend (Phase 13 P1.5 で `0007_same_name_reconcile.py`)。

**DB 真の列体系** (v5-final §0.1):
- `voter_user_id` (NOT `user_id`、ORM 側を rename)
- `project_id` UUID NOT NULL FK → `projects.id` (ORM 側に追加)
- `vote` SMALLINT NOT NULL (NOT `VoteType` enum、smallint 値で UP/DOWN 等を表現)
- `source` enum (既存 `AnnotationVoteSource`)
- `project_role_at_vote` enum nullable (既存 `ProjectMemberRole`)

```python
class AnnotationVote(UUIDMixin, TimestampMixin, Base):
    # Phase 13 P1.5 で ORM rename + 追加
    voter_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)  # was: user_id
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)  # 新規追加
    vote: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # was: Enum(VoteType)
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

**追従**: services / repositories / API が `voter_user_id` 命名 + `project_id` を参照、`vote` は smallint で扱う (Phase 13 P1.5 Gate で annotation/vote API smoke 200 必須)。

---

### 3.13 `annotation_comments`

既存の AnnotationComment に `source` を追加（`AnnotationVote` と同じ enum）。

**Phase 13 同名 drift 戦略**: 整合済 no-op (v5-final §0.1)。ORM ↔ DB 一致確認のみ、reconcile 不要。

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

### 3.22 `datasets`（Phase 13 P2 で extension、legacy 002-data-management から復活）

Phase 13 P2 で `0008_datasets_extension.py` 適用、14 列追加 (v5-final §2.2、Codex review 反映で全列展開):

最終 schema (ORM canonical):

| Column | Type | Null | Default | 備考 |
|--------|------|------|---------|------|
| `id` | UUID | NOT NULL | `gen_random_uuid()` | PK |
| `project_id` | UUID | NOT NULL | — | FK `projects.id ON DELETE CASCADE` |
| `site_id` | UUID | NOT NULL | — | FK `sites.id ON DELETE CASCADE` |
| `recorder_id` | VARCHAR(50) | nullable | — | FK `recorders.id ON DELETE SET NULL` (legacy string PK) |
| `license_id` | VARCHAR(50) | nullable | — | FK `licenses.id ON DELETE SET NULL` (legacy string PK) |
| `created_by_id` | UUID | NOT NULL | — | FK `users.id ON DELETE RESTRICT` (NOT NULL のため SET NULL 不可、creator user 削除は dataset 削除を要求) |
| `name` | VARCHAR(200) | NOT NULL | — | |
| `description` | TEXT | nullable | — | |
| `audio_dir` | VARCHAR(500) | nullable | — | ORM 真で nullable (spec 002 NOT NULL は overrided)、deprecated per docstring |
| `visibility` | `datasetvisibility` enum | NOT NULL | `'private'` | |
| `status` | `datasetstatus` enum | NOT NULL | `'pending'` | |
| `doi` | VARCHAR(255) | nullable | — | Digital Object Identifier |
| `gain` | FLOAT | nullable | — | Recording gain in dB |
| `note` | TEXT | nullable | — | |
| `datetime_pattern` | VARCHAR(500) | nullable | — | filename からの datetime parse パターン |
| `datetime_format` | VARCHAR(100) | nullable | — | strptime format |
| `datetime_timezone` | VARCHAR(50) | nullable | — | IANA timezone |
| `total_files` | INTEGER | NOT NULL | `0` | |
| `processed_files` | INTEGER | NOT NULL | `0` | |
| `processing_error` | TEXT | nullable | — | |
| `created_at` / `updated_at` | TIMESTAMPTZ | NOT NULL | `now()` | TimestampMixin |

**UNIQUE**: `(project_id, name)`

**Index**: `(project_id)`, `(site_id)`, `(status)`, `(visibility)`

詳細は `apps/api/echoroo/models/dataset.py` を参照、`Base.metadata` 機械抽出を真とする。**Migration order**: `0008` は既存テーブルへの ALTER で実装、`IF NOT EXISTS` / `checkfirst=True` で idempotent。

---

### 3.23 `recordings` legacy supporting (`recorders` / `licenses`)（Phase 13 P1）

`recordings` の補助テーブルとして Phase 13 P1 で baseline 統合。

**重要**: `Recorder` / `License` は **legacy supporting tables** で、ORM canonical は `id` が **VARCHAR(50) string PK** (UUIDMixin ではない、`002-data-management` 由来)。

```python
class Recorder(TimestampMixin, Base):
    __tablename__ = "recorders"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)  # legacy string PK (e.g. "audiomoth-v1.2.0")
    manufacturer: Mapped[str] = mapped_column(String(100), nullable=False)
    recorder_name: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # 詳細列は ORM 参照


class License(TimestampMixin, Base):
    __tablename__ = "licenses"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)  # legacy string PK (e.g. "CC-BY-4.0")
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    short_name: Mapped[str] = mapped_column(String(50), nullable=False)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 詳細列は ORM 参照
```

`Dataset.recorder_id` / `Dataset.license_id` は `VARCHAR(50)` の FK でこれらを参照する (UUID FK ではない)。詳細列定義は `apps/api/echoroo/models/{recorder,license}.py`、`Base.metadata` 機械抽出を真とする。

---

### 3.24 `annotations`（DB 真 drift reconcile、Phase 13 P1.5）

**戦略**: DB 側 (detection-based 簡素な構造) を真とし、ORM を縮退 (recording_id / tag_id 等の冗長列を削除)。`0007_same_name_reconcile.py` で適用。

DB 真の最小列体系:
- `id` UUID PK
- `detection_id` UUID FK → `detections.id` ON DELETE CASCADE (NOT NULL)
- `created_by_id` UUID FK → `users.id`
- `created_at` / `updated_at`
- 業務列 (label / confidence 等は detection 側に集約)

```python
class Annotation(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "annotations"
    detection_id: Mapped[UUID] = mapped_column(ForeignKey("detections.id", ondelete="CASCADE"), nullable=False)
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    # ORM 縮退: recording_id / tag_id 等の旧列は削除 (DB に存在しない)
```

recording-based 高機能 annotation 機能 (segments / tasks / sound_event 等) は **Phase 14+ で `recording_annotations` 別 table 化** で対応。詳細 schema は `apps/api/echoroo/models/annotation.py`、`Base.metadata` 機械抽出を真とする。

---

### 3.25 `tags`（ORM 真 drift reconcile、taxa-based、Phase 13 P1.5 で 5 段階 backfill）

**戦略**: ORM 側 (taxa-based、UUID FK) を真とし、DB 側を 5 段階で backfill (v5-final §0.4)。`0007_same_name_reconcile.py` で適用。

```python
class Tag(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "tags"
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("tags.id"), nullable=True)
    taxon_id: Mapped[UUID | None] = mapped_column(ForeignKey("taxa.id"), nullable=True)  # 5 段階 backfill 後 FK
    gbif_taxon_key: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scientific_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    common_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
```

**5 段階 backfill** (v5-final §0.4):
1. legacy `taxon_id` (str64) を `legacy_taxon_id` に rename
2. UUID `taxon_id` 列を nullable で追加
3. `parent_id` / `gbif_taxon_key` / `scientific_name` / `common_name` 追加
4. `taxa.gbif_taxon_key` (int) と `legacy_taxon_id` (str64 = 数値文字列) を `~ '^[0-9]+$'` 正規表現でフィルタしつつ INTEGER cast で逆引き backfill。形式不正な legacy 値は NULL のまま (frontend が tag re-tagging で対応、Phase 14+)
5. FK 追加 + `ix_tags_taxon_id` 作成 + `legacy_taxon_id` drop

dev DB は data 0 件想定、production data 不在 (pre-launch) のため backfill 安全。

**`taxa` テーブル**: Phase 13 P1 で baseline 統合、`gbif_taxon_key` int unique、`scientific_name` / `vernacular_name` 等を保持。詳細は `apps/api/echoroo/models/taxon.py`。

---

### 3.26 Supporting tables overview（Phase 13 P1 で baseline 統合、ORM canonical）

§0 表 #29-#54 (clips / clip_annotations / annotation_projects / annotation_sets / annotation_segments / annotation_tasks / sound_event_annotations / sampling_rounds / search_sessions / evaluation_runs / embeddings / upload_sessions / upload_files / custom_models / notes 等) は **`Base.metadata` 機械抽出を真**とする (v5-final §2.6)。本 spec では各 column 詳細を列挙せず、対応 ORM file (`apps/api/echoroo/models/<table>.py`) を canonical reference とする。

理由:
1. Phase 13 P0a で `Base.metadata` から **静的 1 回生成** した `0006_schema_reconcile_static.py` が単一の真であり、spec で重複定義すると三方向乖離が再発する
2. Phase 13 P5 normalized introspection が ORM ↔ DB の一致を CI で保証する (volatile 列 id/created_at/updated_at 除外、業務 key 比較)
3. spec での詳細列挙は読み手の混乱と保守負荷を招く

**新規 enum 17 件** + **enum widening** (`detectionsource` 4 値追加) は §0 末尾の一覧を参照。enum 実名は ORM canonical (`Enum(name=...)` 引数と一致、snake_case 統一)、`_create_enums()` helper の登録名は `grep -E "Enum\(.+ name=" apps/api/echoroo/models/` で検証する。

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

## 8a. Phase 13 schema reconcile rationale（Phase 1-12 累積整合化）

Phase 1-12 の累積編集により、ORM (`apps/api/echoroo/models/*.py`) ↔ DB (`information_schema` / `pg_catalog`) ↔ spec (本 data-model.md) の三方向 schema 乖離が発生。Phase 13 で spec-first reconciliation 戦略 (新案 D、6 ラウンド Codex review GO 確定、`/tmp/plan-merged-v5-final.md`) により完全整合状態に reconcile する。

### 経緯

- Phase 1-2 baseline で `0001_initial_permissions_redesign.py` が 22 エンティティを CREATE。Phase 3-12 で順次拡張 (`0002` 〜 `0005`) が積み上がる過程で ORM と DB の同名 drift が複数発生
- Phase 6 / Phase 11 ブラウザ Gate 3 (US1 Public 録音再生 / US2 Authenticated vote) が schema 不整合により 500 エラーで block
- Phase 13 で **`Base.metadata` 機械抽出 + delta migration** によって fresh DB と既存 dev DB が同一最終形に到達することを保証

### DB only テーブルの ORM 化 scope

DB に存在するが ORM が存在しない (DB only) テーブルは合計 11 件:
- **Phase 13 scope** (1 件): `detections` (ORM 化、`detectionsource` enum widening 含む)
- **Phase 14+ scope** (10 件): `api_keys` 旧版 / `superusers` 旧版 / 各種 audit テーブル / refresh / token テーブル等 — raw SQL → ORM 化を将来 phase で順次実施

### 同名 drift 戦略まとめ (v5-final §0.1)

| Table | 戦略 | 適用 migration |
|-------|------|----------------|
| `annotations` | **DB 真** (detection-based)、ORM 縮退、recording-based 機能は Phase 14+ で `recording_annotations` 別 table 化 | `0007_same_name_reconcile.py` |
| `tags` | **ORM 真** (taxa-based)、DB を 5 段階で backfill | `0007_same_name_reconcile.py` |
| `annotation_votes` | **DB 真** (`voter_user_id` + `project_id`、`vote` smallint)、ORM rename + project_id 追加 | `0007_same_name_reconcile.py` |
| `annotation_comments` | 整合済 no-op (確認のみ) | — |

### Migration revision chain

Phase 13 完了後の revision chain:

```
0001 → 0002 → 0003 → 0004 → 0005 → 0006 → 0006a → 0007 → 0008 → 0009
```

- `0001` baseline: 最終形 (全 supporting tables + 全 enums + datasets/recordings/sites の最終列) を含む。fresh DB は `0001` で完成、delta `0006-0009` は no-op
- `0002`〜`0005`: Phase 3-12 で積み上がった既存 delta
- `0006_schema_reconcile_static.py`: Phase 13 P0a で `Base.metadata` から静的 1 回生成 (ORM only 32 tables + 17 新規 enums + detections ORM)。以後 ORM 変更で migration 不変
- `0006a_enum_widening.py`: Phase 13 P0b、`autocommit_block()` + `ADD VALUE IF NOT EXISTS` で `detectionsource` 4 値追加 (`perch`, `similarity_search`, `custom_svm`, `sampling_round`)
- `0007_same_name_reconcile.py`: Phase 13 P1.5、annotations/tags/annotation_votes drift reconcile + services / repositories / API 追従 + annotation/vote API smoke 200 Gate
- `0008_datasets_extension.py`: Phase 13 P2、datasets 14 列追加
- `0009_recordings_legacy_rename.py`: Phase 13 P3、recordings legacy 命名 rename + extend + 制約

### Baseline edit と delta migration の重複回避ルール

**fresh DB は `0001 → 0009` を順次適用するため、`0006-0009` の各 delta は冪等でなければならない**:

- `0006` の `op.create_table()` は `IF NOT EXISTS` 相当 (`op.execute("CREATE TABLE IF NOT EXISTS ...")` または手動 inspector check)
- `0007` の rename / add column も `IF NOT EXISTS` / `IF EXISTS` ガード
- `0006a` の `ALTER TYPE ADD VALUE` は既に `IF NOT EXISTS`
- baseline `0001` は最終形を含み、delta は fresh DB では no-op
- 既存 dev DB は `0005` まで適用済の状態から `0006-0009` を順次適用して fresh DB と同じ最終形に到達

これにより fresh と既存 DB が `0009` 適用後に **完全に同一最終形** になる。

### Volatile column normalize ルール (Phase 13 P5)

`Alembic R3 normalized introspection` (P5 Gate) で fresh DB と既存 dev DB upgrade 後の 9 種比較を行う際、以下の volatile 列を除外して業務 key で比較:

- `id` (UUID 自動生成、行ごとに異なる)
- `created_at` / `updated_at` (timestamp、apply 時刻に依存)

比較対象の 9 種:
1. `information_schema.columns` (column 定義)
2. `pg_constraint` (CHECK / UNIQUE / FK 定義)
3. `pg_index` (predicate 含む)
4. `pg_enum` (enum label set)
5. FK ondelete 動作
6. `pg_attribute.attnotnull`
7. `pg_attrdef` (default 値)
8. `pg_trigger`
9. seed rows (volatile 列除外、業務 key で比較)

### Phase 13 完了後の状態

- ORM ↔ DB ↔ spec の三方向乖離ゼロ
- Phase 6 / Phase 11 ブラウザ Gate 3 通過可 (Public project → site → dataset → recording upload → detection → vote → CSV export → auto-obscure map 完走)
- 残課題: API contract cleanup (Phase 13 P7、`duration_seconds` API alias は wire compat 維持、削除は後日 deprecation cycle で実施)

---

## 9. 将来拡張の余地

spec 非目標で保留した機能（Organization、Darwin Core full、ユーザーブロック、SSE push 等）を将来追加する際の migration 互換性:

- **Organization**: `Project.owner_id` を polymorphic にする余地として、将来 `owner_type` カラム追加（現状は `User` 固定）
- **Darwin Core full**: `ProjectAuditLog.detail` JSONB に additional fields を追加可能
- **ユーザーブロック**: `user_blocks` 新規テーブルで実装可能、既存 schema 影響なし

---

**Data Model Status**: ✅ 完了、`contracts/` 作成へ進行可
