---
description: "Task list for 006-permissions-redesign (revised after /speckit.analyse)"
---

# Tasks: 権限・公開レベル再設計

**Input**: `/specs/006-permissions-redesign/` の spec.md / plan.md / research.md / data-model.md / contracts/ / quickstart.md / requirements-traceability.md
**Prerequisites**: 全て揃い、3 者レビュー GO 済み、`/speckit.analyse` 修正反映済み

**Tests**: spec PR-001 で TDD NON-NEGOTIABLE、PR-007 で 75+ シナリオの security test、PR-003 で P1 + セキュリティ重要シナリオ (SC-004/005/009) は E2E 必須

**Organization**: User Story 単位で Phase 分け。Phase 1（Setup）と Phase 2（Foundational）は全 US の前提。以降は各 US を独立 MVP 増分として並列実装可能

**TDD Ordering（全 Phase 共通、PR-001 準拠）**:
1. テストタスク（`test_*.py` / Playwright spec）を先に commit し、CI で **Red (failing) を確認** → その CI run URL を PR description に添付（PR-006、`.github/pull_request_template.md`）
2. 実装タスクを別 commit で追加し CI を **Green** に遷移させる
3. 同一 PR 内で Red → Green が観測できない場合、reviewer は revert を要求する
4. `[P]` 並列タスク間でも各自が自分のテスト → 実装の順を守る（並列性は TDD の免除理由にならない）

## Format: `[ID] [P?] [Story] Description (FR refs)`

- **[P]**: 異なるファイル / 依存なしで並列実行可能
- **[Story]**: US1〜US11 / FN (Foundational) / ST (Setup) / CR (Cross-cutting / Security / Ops)
- `(FR-xxx)` で対応 FR ID を明示。複数 FR にまたがる場合は併記

## Path Conventions

- Backend: `apps/api/echoroo/`
- Frontend: `apps/web/src/`
- Security tests: `apps/api/tests/security/`
- Performance tests: `apps/api/tests/performance/`
- Alembic: `apps/api/alembic/versions/`
- Scripts: `apps/api/echoroo/scripts/` and `scripts/`

---

## Phase 1: Setup（Shared Infrastructure）

- [X] **T001** [ST] feature branch `006-permissions-redesign` の最新化確認 (FR-113)
- [X] **T002** [P] [ST] `apps/api/pyproject.toml` に新規依存追加（全て上限付き SemVer pin）: `pyotp>=2.9.0,<3.0`, `webauthn>=2.5.0,<3.0`, `cryptography>=44.0,<46.0`, `mutmut>=3.2,<4.0` (dev), `testcontainers[postgres,redis]>=4.9,<5.0` (dev) — supply chain リスク軽減、major bump は renovate / dependabot PR 経由のみ (research §16)
- [X] **T003** [P] [ST] `apps/web/package.json` に新規依存追加（caret は SemVer minor 上限のみ許容、`~` 相当の厳格 pin も検討）: `@simplewebauthn/browser@~13.0`, `openapi-typescript@~7.4` (dev) — major 更新を明示承認制にする (research §16)
- [X] **T004** [P] [ST] `scripts/lint_permission_guard.py` 雛形作成（AST、research §18-A、FR-008）
- [X] **T005** [P] [ST] `scripts/lint_response_filter.py` 雛形作成（research §18-B、FR-011）
- [X] **T006** [P] [ST] `scripts/lint_search_gate.py` 雛形作成（research §18-C、FR-025）
- [X] **T007** [P] [ST] `scripts/lint_no_raw_coordinates.py` 雛形（grep + allowlist、FR-028f）
- [X] **T008** [P] [ST] `scripts/lint_kms_isolation.py` 雛形（`core/kms.py` 以外からの KMS 直接呼出検出、FR-091b）
- [X] **T009** [P] [ST] `.github/workflows/ci.yml` に lint / mutation testing / security test ステップ追加 (SC-001、SC-012、SC-013、SC-019、SC-020)
- [X] **T010** [ST] LocalStack KMS 初期化: `scripts/init-localstack.sh` に 4 CMK alias 追加、Redis は TLS + AUTH + ACL を有効化 (FR-051、FR-091b、FR-092、FR-040、NFR-007、NFR-009) (research §1、Runbook 鍵ローテ SLA)
- [X] **T011** [ST] `.env.example` に新規環境変数追加（quickstart.md §1 準拠）
- [X] **T012** [P] [ST] `.github/pull_request_template.md` 新規作成: TDD Red フェーズ CI ログ URL 欄、mutation score (PR-004)、カバレッジ (PR-005)、セキュリティ test ID (PR-007) のチェックリスト欄を配置 (PR-004、PR-005、PR-006、PR-007)

---

## Phase 2: Foundational（Blocking Prerequisites）

**⚠️ CRITICAL**: 本 Phase 完了まで User Story 実装は開始不可

### 2.1 安全装置 + Alembic baseline

- [ ] **T019** [FN] 安全装置: git tag `pre-permissions-redesign-baseline` を main に push、`apps/api/alembic/versions/.archive/` 作成、既存 24 migration を archive ディレクトリに移動（即削除より git 追跡可能）(FR-113)
- [ ] **T020a** [FN] `apps/api/alembic/versions/0001_baseline_permissions_redesign.py` — Enum 型 11 個 + `users` + `superusers` + `superuser_approval_requests` + **`outbox_events` (early)** + `system_settings` (FR-113、data-model §2 Migration Order)
- [ ] **T020b** [FN] 同 baseline migration — `projects` + `project_license_history` + `project_members` + `project_invitations` + `project_trusted_users` + `project_taxon_sensitivity_overrides` + `sites` + `recordings` + `detections` + `annotations` + `tags` + `datasets` (FR-001〜005、FR-028、FR-041、FR-047)
- [ ] **T020c** [FN] 同 baseline migration — `annotation_votes` + `annotation_comments` + `taxon_sensitivities` + `iucn_sync_attempts` + `api_keys` + `project_audit_log` + `platform_audit_log` + `dek_rewrap_failures` + `wipe_guard` (FR-037、FR-074、FR-088、FR-089、FR-114)
- [ ] **T020d** [FN] 同 baseline migration — Index 全定義（data-model §5）、CHECK 制約（FR-048、FR-027 離散値 IN (2,5,7,9,15)、FR-091 等）、`sites.h3_index_member_resolution` デフォルト 15 (NFR-003)、`system_settings` 初期値 seed (NFR-006)
- [ ] **T020e** [FN] 同 baseline migration — Trigger: `prevent_last_superuser_deletion`（FR-111a、current_user='echoroo_app' 限定）、`forbid_audit_log_mutation`（FR-094）
- [ ] **T020f** [FN] 同 baseline migration — PostgreSQL ACL: `REVOKE UPDATE, DELETE ON project_audit_log, platform_audit_log, project_license_history FROM echoroo_app` (FR-094、security 指摘 New-3)
- [ ] **T020g** [FN] 同 baseline migration — genesis row INSERT (project_audit_log + platform_audit_log、`repeat('0', 64)` hash) (FR-092、data-model §3.17)
- [ ] **T021** [FN] `apps/api/echoroo/scripts/check_wipe_guard.py` 実装（3 点一致ガード: DB `wipe_guard` + `alembic_version` + S3 Object Lock marker）(FR-114)
- [ ] **T022** [FN] `apps/api/echoroo/scripts/wipe_database.py` 実装（interactive 確認 + superuser 2 名 M-of-N + `wipe_guard` INSERT）(FR-113、FR-114、quickstart §2)
- [ ] **T023** [FN] `apps/api/tests/integration/test_baseline_migration.py` TDD: 空 DB → `alembic upgrade head` → 22 エンティティが情報スキーマに存在することを assert (FR-113)

### 2.2 KMS 抽象層

- [ ] **T030a** [FN] `apps/api/echoroo/core/kms.py` — `wrap_dek` / `unwrap_dek`（TOTP secret）(FR-051、FR-066、FR-067)
- [ ] **T030b** [P] [FN] `core/kms.py` — `compute_pii_hash(value) -> str`（`kms:GenerateMac` 専属、key material app に展開しない）(FR-091、FR-091b)
- [ ] **T030c** [P] [FN] `core/kms.py` — `sign_invitation_hmac` / `verify_invitation_hmac`（k_old/k_new 2 鍵並行、14 日 grace）(FR-052、FR-040、research §14)
- [ ] **T030d** [P] [FN] `core/kms.py` — `compute_audit_chain_hash(prev_hash, canonical_row)`（chain_key）(FR-092)
- [ ] **T031** [P] [FN] `apps/api/tests/unit/core/test_kms.py` TDD: LocalStack KMS mock、全関数の unit（T030a〜d 実装前に Red）
- [ ] **T032** [P] [FN] `scripts/lint_kms_isolation.py` 完全実装: `core/kms.py` 以外での `boto3.client('kms')` 使用を検出し fail (FR-091b)

### 2.3 Permission engine（分割）

- [ ] **T040a** [FN] `core/permissions.py` — `Permission` enum 28 個 + `USER_SCOPE_PERMISSIONS` + `TRUSTED_ALLOWED_PERMISSIONS` + `SUPERUSER_PROJECT_SCOPE_ALLOWLIST` 定数定義 (FR-009、FR-012、FR-008b)
- [ ] **T040b** [P] [FN] `core/permissions.py` — `Action` Pydantic model + `@model_validator` 整合性強制 + `ACTIONS: dict[str, Action]` カタログ (FR-008a)
- [ ] **T040c** [P] [FN] `core/permissions.py` — `ROLE_PERMISSIONS` dict 定義（Canonical Matrix、26 Project 権限）(FR-010)
- [ ] **T040d** [FN] `core/permissions.py` — `is_allowed` 実装（ステージ 1 Permission gate、再帰禁止、0 認証 / 0a platform-scope / 0b superuser allowlist / 1 archived / 2 normalize_role / 3 compute_effective_permissions / 4 最終判定）(FR-008)
- [ ] **T040e** [P] [FN] `core/permissions.py` — `compute_effective_permissions`（Matrix + Trusted overlay + Restricted toggle + API key 交差）、request-scope キャッシュ適用 (FR-008、FR-014〜015a、NFR-008)
- [ ] **T040f** [P] [FN] `core/permissions.py` — `compute_effective_resolution`（HIDDEN clamp 先頭、looser override global 置換、Trusted `VIEW_PRECISE_LOCATION`、Taxon sensitivity）(FR-027、FR-034、FR-035)
- [ ] **T040g** [P] [FN] `core/permissions.py` — `normalize_role`（Public では Viewer を Authenticated）、`resolve_role`、`active_trusted_capabilities`、`permissions_from_toggles_for_guest/authenticated`（data-model §1 Permission 決定アルゴリズム）
- [ ] **T041** [P] [FN] `core/response_filter.py` 新規: `apply_response_filter`（effective permissions と normalized_role を引数受取、DB 再アクセス禁止）(FR-011)
- [ ] **T042** [FN] `apps/api/tests/unit/core/test_permissions_matrix.py`: Canonical Matrix パラメトリック全探索（6 主体 × 28 Permission × 2 Visibility × toggle 組合せ）(PR-002、SC-001)
- [ ] **T043** [P] [FN] `apps/api/tests/unit/core/test_compute_effective_resolution.py`: HIDDEN clamp、looser 承認後、Trusted、メンバー解像度 (FR-034、FR-035、SC-017)
- [ ] **T044** [P] [FN] `scripts/lint_permission_guard.py` 完全実装: FastAPI path operation に `is_allowed` / `Depends(check_action)` 経由強制 (research §18-A、SC-001)
- [ ] **T045** [P] [FN] `scripts/lint_response_filter.py` 完全実装: Recording/Detection/Site response_model で `apply_response_filter` 経由強制 (research §18-B)
- [ ] **T046** [FN] `apps/api/tests/security/authorization/test_endpoint_coverage.py`: FastAPI 全 route が `ACTIONS` に登録されていることをリフレクション検証 (research §18-D)
- [ ] **T047** [P] [FN] mutation testing 設定: `mutmut.toml` + CI integration、権限系 4 モジュール対象、**初期は warn-only、Phase 16 T995 で fail に切替** (PR-004、SC-012)

### 2.4 Audit Log + Sanitizer

- [ ] **T050a** [FN] `core/audit.py` — `AuditLogSanitizer` Pydantic model（PII regex + Unicode NFKC 正規化 + URL-decode + base64-decode）(FR-091a)
- [ ] **T050b** [P] [FN] `core/audit.py` — `{hash, hash_version, redacted: true}` 形式への置換ロジック (FR-091a)
- [ ] **T051** [FN] `services/audit_service.py` 新規: project_audit_log / platform_audit_log 書き込み + chain hash 更新 + `SERIALIZABLE` + `pg_advisory_xact_lock('audit_log_chain')` (FR-092、FR-093)
- [ ] **T052** [P] [FN] `apps/api/tests/unit/core/test_audit_sanitizer.py` TDD: 10+ bypass（nested/array/Unicode 同形/URL-encoded/base64/null/制御文字）(FR-091a、SC-020)
- [ ] **T053** [P] [FN] `apps/api/tests/security/audit_log/test_chain_integrity_serialize.py`: SERIALIZE locking unit（並列安全性は T993 で scale 検証）(FR-093)
- [ ] **T055** [P] [FN] `workers/audit_log_export.py` 週次バッチ: chain 再計算 hash を S3 Object Lock append-only export、3 年保持 (FR-095)
- [ ] **T056** [P] [FN] `api/web_v1/audit.py` 新規（`contracts/audit.yaml` 対応）: list project / platform、閲覧自体を自己参照 metalog (FR-088、FR-089、FR-096)

### 2.5 Auth 基盤

- [ ] **T060a** [FN] `core/auth.py` — `security_stamp` による session revocation 基盤 (FR-055、FR-071)
- [ ] **T060b** [P] [FN] `core/auth.py` — JWT access token 15 分実装 (FR-055)
- [ ] **T060c** [P] [FN] `core/auth.py` — refresh token rotation（one-time use + family tracking + reuse detection）(FR-055)
- [ ] **T061** [P] [FN] `services/auth_service.py` 改修: password 認証、NIST SP 800-63B、HaveIBeenPwned 連携、login_attempts レート (FR-103)
- [ ] **T062** [P] [FN] `apps/api/tests/security/authentication/test_refresh_token_rotation.py` TDD: 再利用検知で family revoke (FR-055)

### 2.6 Middleware

- [ ] **T070** [FN] `middleware/auth.py` 改修: `/api/v1/*` は Bearer API key、`/web-api/v1/*` は Cookie + CSRF、URL prefix 分岐 (FR-077、FR-099)
- [ ] **T071** [P] [FN] `middleware/security_headers.py` 新規: CSP nonce + HSTS + X-Frame + Referrer + Permissions + X-Content-Type (FR-102)
- [ ] **T072** [P] [FN] `middleware/csrf.py` 新規: `HMAC-SHA256(session_secret, session_id || issued_at)`、定数時間比較 (FR-098)
- [ ] **T073** [P] [FN] `middleware/audit_logging.py` 新規: access log の PII redaction (FR-028c)
- [ ] **T074** [P] [FN] `middleware/rate_limit.py` 新規: Redis Lua token bucket、TOTP/招待/API key scope 別 (FR-054、FR-056、FR-082)
- [ ] **T075** [P] [FN] `middleware/cors.py` 新規: URL prefix 別 CORS ポリシー (plan §CORS、FR-099)

### 2.7 Outbox Pattern

- [ ] **T080** [FN] `services/outbox_service.py` 新規: `OutboxEvent` 書き込み + `idempotency_key` UNIQUE + MAX_RETRY=5 + backoff + dead_letter、Celery リトライは最大 3 回・指数バックオフ (FR-076a、FR-076d、NFR-005、research §6)
- [ ] **T081** [P] [FN] `workers/outbox_processor.py` 新規: Celery worker-cpu、4 並列、`SELECT FOR UPDATE SKIP LOCKED`、SLO p95≤10s/p99≤60s (FR-076d)
- [ ] **T082** [P] [FN] `apps/api/tests/security/race_conditions/test_outbox_at_most_once_log.py` TDD: worker クラッシュ → retry で重複 audit log が出ない (FR-076a、SC-021)
- [ ] **T083** [P] [FN] `apps/api/tests/security/race_conditions/test_outbox_worker_stop_fallback.py` TDD: worker 5 分停止で `enforce_at_auth_time=true` fallback 動作 (FR-076d、SC-021)
- [ ] **T084** [P] [FN] Celery task 基底 Pydantic model に lat/lng 禁止 validator を定義 (FR-028b)

### 2.8 SearchGate 抽象層

- [ ] **T090** [FN] `services/search_gate.py` 新規: `SearchGate` Protocol、`FtsSearchAdapter`、`PgvectorSearchAdapter`（k*3 fetch + post-filter）、`OpenSearchAdapter` は `NotImplementedError` stub (FR-025、research §3)
- [ ] **T091** [P] [FN] `apps/api/tests/security/search_leak/test_search_gate_isolation.py` TDD: 3 adapter で `allow_detection_view=OFF` 除外 (FR-025a、SC-018)
- [ ] **T092** [P] [FN] `scripts/lint_search_gate.py` 完全実装: `select(Detection)` 系の直接使用検出、`services/search_gate.py` + `repositories/detection.py` 以外で fail (research §18-C)

### 2.9 CI 静的解析 統合

- [X] **T100a** [FN] CI: `lint_permission_guard.py` を warning mode で有効化 (SC-001)
- [X] **T100b** [P] [FN] CI: `lint_response_filter.py` warning mode (FR-011)
- [X] **T100c** [P] [FN] CI: `lint_search_gate.py` warning mode (FR-025)
- [X] **T100d** [P] [FN] CI: `lint_no_raw_coordinates.py` + `lint_kms_isolation.py` warning mode (FR-028f、FR-091b、SC-019)
- [X] **T100e** [P] [FN] CI: OpenAPI 生成後の lat/lng grep assertion (SC-019)
- [X] **T100f** [FN] CI: 全 lint + `test_endpoint_coverage.py` を **blocking mode** に昇格（Foundational 完了時点、User Story 着手の gate）

**Checkpoint**: T100f 通過で Phase 3〜13 並列着手可能

---

## Phase 3: US11 - Permission 細粒度化（P1）🎯 MVP 起点

**Goal**: 既存 API 全てに Permission guard を経由、Viewer/Member 差異実効

### 3.1 Model 改修

- [ ] **T110** [US11] `models/project_member.py` 改修: `expires_at`、CHECK `(role='viewer' OR expires_at IS NULL)`、unique (project_id, user_id) WHERE removed_at IS NULL (FR-004)
- [ ] **T111** [P] [US11] `models/project.py` 改修: visibility 2 値 + status + restricted_config JSONB + license + license_history FK (FR-001、FR-005、FR-085)

### 3.2 ACTIONS カタログ

- [ ] **T115** [US11] `core/actions.py` 新規: 全 FastAPI path operation 用 Action オブジェクト登録 (FR-008a)

### 3.3 既存 API エンドポイント Permission guard 経由化（**個別ファイル分割を前提、同一ファイル衝突なし**）

**重要**: `api/web_v1/projects.py` は以下 4 ファイルに router 分割（architect B-1 対応）:
- `api/web_v1/projects/_core.py`（CRUD）
- `api/web_v1/projects/_members.py`（members / invitations）
- `api/web_v1/projects/_restricted_config.py`（toggle）
- `api/web_v1/projects/_license.py`（license）

- [ ] **T118** [US11] router 分割の前処理: `api/web_v1/projects/__init__.py` で 4 file を include、各ファイル骨格作成
- [ ] **T120** [P] [US11] `api/v1/detections.py` 全面書き換え: list / export CSV / export ml-dataset / get に `check_action` + Response filter (FR-006、spec 既存漏れ修正)
- [ ] **T121** [P] [US11] `api/v1/tags.py` 全面書き換え: `check_action` + CREATE_TAG guard (FR-006)
- [ ] **T122** [P] [US11] `api/v1/uploads.py` 全面書き換え: UPLOAD + EXIF strip 呼出 + acknowledge checkbox (FR-006、FR-028a、FR-110)
- [ ] **T123** [P] [US11] `api/v1/custom_models.py` 全面書き換え: TRAIN_MODEL Admin 以上 (FR-006)
- [ ] **T124** [P] [US11] `api/v1/annotation_votes.py` 改修: source 判定 + VOTE + Viewer 403 (FR-037)
- [ ] **T125** [P] [US11] `api/v1/annotation_comments.py` 改修: source 判定 + COMMENT (FR-040)
- [ ] **T126** [P] [US11] `api/v1/projects.py` 改修: visibility 2 値 + restricted_config + transfer-ownership (FR-003、FR-057、FR-063、FR-064)
- [ ] **T127** [P] [US11] `api/v1/recordings.py` 改修: VIEW_MEDIA + Response filter (FR-016、FR-011)
- [ ] **T128** [P] [US11] `apps/api/echoroo/services/s3_upload_sanitizer.py` 新規: boto3 preprocessor で `PutObject` の object metadata から GPS / lat / lng / gps_* キーを strip (FR-028e、security 重要 1)
- [ ] **T129** [P] [US11] `apps/api/tests/security/authorization/test_upload_exif_and_s3_metadata_strip.py` TDD: GPS EXIF を含む WAV upload で S3 object metadata 生 lat/lng 不在 (FR-028a、FR-028e)

### 3.4 Tests

- [ ] **T130** [P] [US11] `apps/api/tests/contract/test_permissions.py` 書き換え: T042 の fixture 再利用、28 Permission × 6 主体 × visibility 全組合せ contract (PR-002、SC-001)
- [ ] **T131** [P] [US11] `apps/api/tests/security/authorization/test_viewer_permission_boundary.py`: Viewer が編集系 全操作 403、閲覧系 200 (FR-004)
- [ ] **T132** [P] [US11] `apps/api/tests/security/authorization/test_member_vs_admin.py`: Member が MANAGE_MEMBERS 403、TRAIN_MODEL 403 (FR-008)
- [ ] **T133** [US11] Playwright E2E: Viewer で投票ボタン非活性、MEMBER で有効 (PR-003、P1 重要)
- [ ] **T134** [P] [US11] `apps/api/tests/security/authorization/test_bola_idor_cross_project.py` TDD: 他プロジェクトの detection / site ID で 403 (PR-007 認可 BOLA/IDOR)

---

## Phase 4: US8 - 2FA 必須化（P1）

### 4.1 Model

- [ ] **T140** [US8] `models/user.py` 改修: 2FA 関連カラム + `security_stamp` + `last_login_at` + `last_first_party_activity_at` + `registered_timezone` + `two_factor_reset_cooldown_until` + `deleted_at` (FR-050、FR-060、FR-105)

### 4.2 Service

- [ ] **T145** [US8] `services/two_factor_service.py` 新規: TOTP シークレット生成（`pyotp`）+ KMS envelope + バックアップコード Argon2id + 検証 + reset（security_stamp 更新）(FR-050〜056、FR-065〜072)
- [ ] **T146** [P] [US8] `services/webauthn_service.py` 新規: `py_webauthn` ラッパー、superuser hardware key 登録 / 検証、Redis challenge nonce 5 分 TTL (FR-111、security H-7)

### 4.3 API（分割）

- [ ] **T150a** [US8] `api/web_v1/auth.py` 基礎: register / login / refresh / logout (FR-103、FR-055)
- [ ] **T150b** [P] [US8] `api/web_v1/auth.py` TOTP: `/2fa/challenge` + `/2fa/setup/totp` + `/2fa/setup/totp/confirm` (FR-065、FR-068、FR-069、FR-070)
- [ ] **T150c** [P] [US8] `api/web_v1/auth.py` WebAuthn: `/2fa/webauthn/register` + `/2fa/webauthn/challenge` (FR-111)
- [ ] **T150d** [P] [US8] `api/web_v1/auth.py` password-reset: `/password-reset/request` + `/password-reset/confirm`（security_stamp 更新）(FR-055、FR-071)
- [ ] **T150e** [US8] `apps/api/pyproject.toml`: drop `tests.* ignore_errors = true` mypy override after T150a-d migrate tests off legacy User attrs

### 4.4 Middleware

- [ ] **T155** [US8] `middleware/two_factor_enforcement.py` 新規: 2FA 未設定で設定画面以外を 403 (FR-069)

### 4.5 Frontend

- [ ] **T160** [P] [US8] `apps/web/src/routes/(auth)/register/+page.svelte` 改修 (FR-069)
- [ ] **T161** [P] [US8] `apps/web/src/routes/(app)/account/2fa/+page.svelte` 新規: QR + バックアップコード表示 (FR-068)
- [ ] **T162** [P] [US8] `apps/web/src/routes/(auth)/login/+page.svelte` 改修: 2FA チャレンジ (FR-065)
- [ ] **T163** [P] [US8] `apps/web/tests/e2e/helpers/totp.ts` E2E 用 TOTP 生成 (PR-003)

### 4.6 Tests

- [ ] **T170** [P] [US8] `apps/api/tests/unit/services/test_two_factor_service.py` TDD (FR-050、FR-052、FR-068)
- [ ] **T171** [P] [US8] `apps/api/tests/security/authentication/test_totp_brute_force.py` TDD: 5/15min + 10 連続ロック (FR-054、FR-070)
- [ ] **T172** [P] [US8] `apps/api/tests/security/authentication/test_backup_code_one_time_use.py` TDD (FR-068)
- [ ] **T173** [P] [US8] `apps/api/tests/security/authentication/test_cooldown_after_2fa_reset.py` TDD: 72h cooldown 中の招待 / API key / DL / EXPORT 403 (FR-073)
- [ ] **T174** [US8] Playwright E2E: 新規登録 → 2FA → ログイン → reset → 全 refresh token 失効 (PR-003、P1 重要)
- [ ] **T175** [P] [US8] `apps/api/tests/security/authentication/test_security_stamp_revocation.py` TDD: パスワード変更で全 refresh 失効 (FR-055)
- [ ] **T176** [P] [US8] `apps/api/tests/security/authentication/test_refresh_token_family_reuse.py` TDD: reuse 検出で family 全 revoke (FR-055)
- [ ] **T177** [P] [US8] `apps/api/tests/security/authentication/test_jwt_replay_across_security_stamp.py` TDD: security_stamp 更新後の旧 JWT replay が拒否 (FR-055、FR-071、PR-007 認証)
- [ ] **T178** [P] [US8] `services/login_notification_service.py` 新規: login 成功時に user-agent hash + IP / ASN を prior sessions と比較、新デバイス/新 IP を検出して OutboxEvent (`kind=login_notification`) に enqueue (FR-104)
- [ ] **T180** [P] [US8] `apps/api/tests/security/authentication/test_login_notification.py` TDD: 初回 IP/UA=送信なし、異なる IP で通知、同 IP 連続で抑止 (FR-104)

### 4.7 Workers

- [ ] **T179** [P] [US8] `workers/login_notification_dispatcher.py` 新規: Celery worker-cpu、OutboxEvent `kind=login_notification` を consume、email テンプレート送信、失敗時 3 回リトライ、email header injection 対策適用 (FR-104)

---

## Phase 5: US1 - Guest が Public で録音再生（P1）

- [X] **T200** [US1] `api/web_v1/projects/_core.py` で Public 読み取り経路実装（T118 で分割済み）(FR-009、FR-010、FR-016)
- [X] **T201** [P] [US1] Guest 用 `/web-api/v1/projects` list（Public のみフィルタ、Response filter 経由、生 lat/lng 除外）(FR-016、FR-018、FR-030)
- [X] **T202** [P] [US1] Recording stream endpoint（presigned S3 URL に species 名含めない）(security H-8、FR-016)
- [X] **T210** [US1] `apps/web/src/routes/(public)/explore/projects/[id]/+page.svelte` 新規（h3_index 表示、DL 非活性、403/404 統一）(FR-016、FR-018) — URL は `(app)/projects/[id]` との衝突回避で `/explore/projects/[id]` 採用
- [X] **T211** [P] [US1] `apps/web/src/routes/(public)/+layout.server.ts`（未認証 OK、Public のみ）+ `+layout.svelte`（auth-aware CTA）(FR-016)
- [X] **T220** [P] [US1] `apps/api/tests/security/authorization/test_guest_public_access.py` TDD: Guest 200、DL 401、希少種位置 H3_RES_5 以下、recording list shape minimal、H3 generalisation res15→≤9 (FR-016、FR-018、FR-029、FR-030、SC-016) — 34 tests pass
- [X] **T221** [US1] Playwright E2E: Guest でトップページ → Public 閲覧 → 録音再生 (PR-003、P1 必須、SC-002) — 9 シナリオ env-gated (`PHASE5_E2E_ENABLED`)
- [X] **T200b** [US1] Bonus: `GET /web-api/v1/projects/{id}/recordings` (Guest-aware list endpoint、`PublicRecordingItem` schema、auth_router nested allowlist) — Codex review で必須と判定 (T210 の audio 再生 UI が機能するため)

---

## Phase 6: US2 - Authenticated の Public での Export・投票（P1）

- [X] **T300** [US2] CSV export: license + location_generalization + withheld_reason 必須 (FR-086)
- [X] **T301** [P] [US2] 非メンバー投票: `source=guest_authenticated`、`project_role_at_vote=null` (FR-037)
- [X] **T310** [P] [US2] `apps/api/tests/contract/test_guest_authenticated_vote.py` TDD (FR-037、FR-038)
- [X] **T311** [US2] Playwright E2E: 非メンバー投票 → 「非メンバー」バッジ (PR-003、P1 必須)
- [X] **T312** [P] [US2] `apps/api/tests/security/search_leak/test_export_csv_no_lat_lng.py` TDD: CSV に生 lat/lng 不在 (FR-086、SC-016)
- [X] **T313** [P] [US2] `apps/api/tests/contract/test_vote_voter_id_masking.py` TDD: Owner / Admin は `voters[].user_id` に UUID、他ロール（Member / Viewer / guest_authenticated）は `voters[].user_id=null`、`voters` 配列自体は常に返す（投票可視性は維持）(FR-039)
- [X] **T313b** [P] [US2] `specs/006-permissions-redesign/contracts/detections.yaml` の `VoteAggregateResponse.voters` は spec.md FR-039 と既に整合済み（`items.user_id` は `nullable: true`、description は spec 文言と一致）— Round 1 で確認、無修正 (FR-039)

---

## Phase 7: US10 - ライセンス必須（P1）

- [x] **T320** [US10] `api/web_v1/projects/_core.py` POST `/projects` で license 必須 (FR-085) — NOTE: `restricted_config={}` の CHECK 違反（必須キー欠落）は Phase 2/Phase 8 既存 issue であり、本タスクのスコープ外。Phase 8 T400 (`PATCH /restricted-config` の `Extra.forbid` + 必須キー検証) で扱う。
- [x] **T321** [P] [US10] `apps/web/src/routes/(app)/projects/new/+page.svelte` 改修: license 未選択で非活性 (FR-085)
- [x] **T322** [P] [US10] `services/license_service.py` 新規: `ProjectLicenseHistory` 記録、過去 export 不変 (FR-087)
- [x] **T323** [P] [US10] `apps/api/tests/contract/test_license_required.py` TDD: API 直叩きで 422 (FR-085、SC-010)
- [x] **T324** [US10] Playwright E2E: ライセンス未選択で非活性、CC-BY で作成成功 (PR-003、P1 必須、SC-010)

---

## Phase 8: US3 - Restricted オーナートグル（P1）

- [x] **T400** [US3] `api/web_v1/projects/_restricted_config.py` PATCH 実装（Pydantic `Extra.forbid`）(FR-014、FR-020〜022、FR-023)
- [x] **T401** [P] [US3] `services/restricted_config_service.py` 新規: toggle 変更で監査 + 検索 index 再構築 Celery enqueue (FR-024) — NOTE: FR-025a step 1 (SearchGate `filter_by_allow_detection_view` の `SimilaritySearchService` 配線) は Phase 11 の検索改修タスク (T090/T091) で扱う。Phase 8 では permission gate / `gate_action` が freshly-committed `restricted_config` を読む経路で synchronous 除外を担保し、FR-025a step 2 (async index rebuild) は `echoroo.workers.search_tasks.rebuild_search_index_for_project` stub task として登録される。
- [x] **T402** [P] [US3] `apps/web/src/lib/components/RestrictedToggles.svelte` 新規 (FR-014)
- [x] **T403** [P] [US3] `apps/api/tests/contract/test_restricted_toggles.py` TDD: bool 6 × ON/OFF + precision_h3_res + allow_precise_location_to_viewer 全組合せ (FR-020〜022、SC-003)
- [x] **T404** [US3] Playwright E2E: 各トグル ON/OFF の非メンバー挙動 (PR-003、SC-003)
- [x] **T405** [P] [US3] `apps/api/tests/security/authorization/test_viewer_precise_location_denied.py` TDD: `allow_precise_location_to_viewer=false` 時 Viewer が precise location 取得不可 (FR-022、SC-017)

---

## Phase 9: US4 - Restricted プロジェクトの発見（P1）

- [x] **T410** [US4] GET `/projects` で Restricted もメタ公開 (FR-019)
- [x] **T411** [P] [US4] Restricted 詳細ページに Owner `mailto:` リンク (US4 AC2)
- [x] **T412** [P] [US4] `SEARCH_CROSS_PROJECT` で `allow_detection_view=OFF` は種別ヒットなし (FR-017、FR-026) — Phase 9 polish round 2 致命 2 deferral note: 専用の cross-project search HTTP route 新設は Phase 11 (SearchGate 統合) で扱う。本 Phase では (a) `SimilaritySearchService.search_by_vector` の `respect_restricted_toggle` default を **True** に倒し、(b) 全 production caller (`services/search.py:119`/`:369`/`:1058`、`workers/search_tasks.py:584`) は in-project member route として明示的に `False` を渡す形にし、(c) `SimilarityServiceCandidateProvider` 経由で `PgvectorSearchAdapter` にも SQL gate を配線、で leak prevention を達成する。新規 cross-project caller を追加した場合 default-safe で SQL gate を継承する。
- [x] **T413** [P] [US4] `apps/api/tests/security/search_leak/test_restricted_search_exclusion.py` TDD: 3 経路で toggle ON→OFF 切替直後 1 秒以内の leak なし (FR-017、FR-025a、SC-018)
- [x] **T414** [US4] Playwright E2E: Guest が Restricted メタを一覧で確認 → mailto: リンク動作 (PR-003、P1、architect B-4 対応)

---

## Phase 10: US5 - Trusted User 招待（P2）

- [x] **T500** [US5] `models/project_invitation.py` 改修: kind + CHECK + email_hash + trusted_duration_seconds (FR-047、FR-048)
- [x] **T501** [P] [US5] `models/project_trusted_user.py` 新規 (FR-041)
- [x] **T502** [P] [US5] `services/invitation_service.py` 改修: HMAC 署名 + email 一致 + single TX + idempotency-key (FR-052、FR-053、FR-054、FR-055)
- [x] **T503** [P] [US5] `services/trusted_service.py` 新規: allowlist 再フィルタ + 期限 + 延長 + revoke (FR-012、FR-014、FR-043、FR-044、FR-046)
- [x] **T510** [US5] `api/web_v1/trusted.py` 新規（`contracts/trusted.yaml` 対応）(FR-050)
- [x] **T511** [P] [US5] `api/web_v1/projects/_members.py` に `/invitations/{token}/accept` 追加（T118 で分割済みなので衝突なし）(FR-053、FR-054)
- [x] **T512** [P] [US5] `api/web_v1/projects/_members.py` に `DELETE /invitations/{token}` 追加: **受信者** による pending 招待のセルフ decline。token lookup は accept と同じ HMAC 署名検証 + `token_hash` 比較、受信者 email 一致確認（FR-054 準拠）、成功時 `ProjectInvitation.status = DECLINED` 遷移（既存 enum + state machine 流用、新規 enum 値追加なし）+ 監査ログ記録。レスポンス: pending/既 DECLINED → 204（冪等、再 decline も 204 で status 不変）、accepted/expired/revoked → 410、token 未解決 or 他人 token or email 不一致 → 全て **404 に統一**（enumeration 対策、FR-055 準拠） (FR-107、FR-101c、FR-054、FR-055)
- [x] **T513b** [P] [US5] `apps/api/tests/contract/test_invitation_recipient_self_delete.py` TDD: pending 削除 204 + status=DECLINED、再 decline 204 冪等、accepted 410、expired 410、revoked 410、token 未解決 404、他人 token 404、email 不一致 404 (全て 404 統一で enumeration 回避) (FR-107、FR-055)
- [x] **T514** [P] [US5] `workers/trusted_long_lived_invalidation.py` 新規: WebSocket / SSE / streaming 接続で 5 分ごとに `active_trusted_capabilities` / `security_stamp` 再評価、revoke は Redis pub/sub で broadcast (NFR-008a)
- [x] **T515** [P] [US5] `workers/trusted_expiry_notifier.py` 期限 7 日前通知 (FR-045)
- [x] **T516** [P] [US5] `workers/trusted_auto_expire.py` expires_at で自動 expired (FR-044)
- [x] **T520** [P] [US5] `apps/web/src/routes/(app)/projects/[id]/trusted/+page.svelte` 新規 (FR-050)
- [x] **T521** [P] [US5] `apps/web/src/routes/(app)/invite/[token]/+page.svelte` 新規 (FR-053) — Phase 10 Batch 4 で URL token leak 対策のため `(public)/invite/[token]/` に移動 + sessionStorage resume
- [x] **T530** [P] [US5] `apps/api/tests/security/invitations/test_email_mismatch.py` TDD (FR-054)
- [x] **T531** [P] [US5] `apps/api/tests/security/invitations/test_double_accept_idempotency.py` TDD (FR-053)
- [x] **T532** [P] [US5] `apps/api/tests/security/authorization/test_trusted_allowlist_runtime.py` TDD: VIEW_AUDIT_LOG 手動 INSERT でも除外 (FR-014)
- [x] **T533** [US5] Playwright E2E: 発行 → accept → expire → revoke full flow (PR-003、SC-004 セキュリティ重要)

---

## Phase 11: US6 - Taxon-driven Auto-obscure（P2）

- [x] **T600** [US6] `models/taxon_sensitivity.py` 新規 (FR-032)
- [x] **T601** [P] [US6] `models/project_taxon_override.py` 新規 (FR-033)
- [x] **T602** [P] [US6] `models/iucn_sync_attempt.py` 新規 (FR-036)
- [x] **T610** [US6] `services/taxon_sensitivity_service.py` 新規: IUCN + MOE RDB sync + bulk preload + request-scope cache (FR-032、FR-036、NFR-001a)
- [x] **T611** [P] [US6] looser override 承認 workflow: `SuperuserApprovalRequest` 経由 (FR-034)
- [x] **T620** [P] [US6] `workers/iucn_sync.py` 新規: 週次 + TLS cert pinning + sanity check + `IucnSyncAttempt` 記録 + 2 週失敗 fail-safe (FR-036)
- [x] **T621** [P] [US6] `apps/api/echoroo/scripts/initial_iucn_sync.py` CLI（手動初回同期、quickstart §3 対応）(FR-036、security 重要 2)
- [x] **T622** [P] [US6] `apps/api/echoroo/scripts/seed_moe_rdb.py` CLI（環境省 RDB 手動 CSV import）(FR-032、security 重要 2)
- [x] **T630** [P] [US6] `api/web_v1/admin.py` に looser override 承認 endpoint (FR-034、FR-111)
- [x] **T640** [P] [US6] `apps/web/src/lib/components/HSpecYMaps.svelte` 改修: `h3_index` → resolution で marker / polygon (FR-029、research §10)
- [x] **T650** [P] [US6] `apps/api/tests/unit/services/test_auto_obscure.py` TDD: IUCN EN → H3_RES_5、MOE CR → HIDDEN、looser 承認後 global 置換、HIDDEN は Trusted でも解除不能 (FR-034、FR-035)
- [x] **T651** [P] [US6] `apps/api/tests/security/search_leak/test_no_raw_coordinates.py` TDD: 50+ endpoint JSON schema fuzzer (FR-030、FR-031、SC-016)
- [x] **T652** [US6] Playwright E2E: 希少種検出 export CSV で粗化 hex + `withheld_reason=taxon_sensitivity:EN` (PR-003、SC-005 セキュリティ重要)
- [x] **T653** [P] [US6] `apps/api/tests/integration/test_auto_obscure_integration.py`: API レスポンス レベルで lat/lng 不在確認 (FR-030、SC-005 integration 層)

---

## Phase 12: US7 - 所有権移譲と休眠検出（P2）

- [x] **T700** [US7] `services/ownership_service.py` 新規: `SELECT FOR UPDATE` + advisory lock + idempotency-key (FR-057、FR-058、FR-059)
- [x] **T701** [P] [US7] `workers/dormancy_check.py` 新規: 日次 + 3/1/1 週通知 + 366d grace (FR-060、SC-008)
- [x] **T702** [P] [US7] `api/web_v1/admin.py` に archive / restore endpoint (FR-061、FR-062)
- [x] **T703** [P] [US7] `apps/api/tests/security/race_conditions/test_ownership_transfer_race.py` TDD: 1000 並行で 1 件成功 (FR-058、SC-007)
- [x] **T704** [P] [US7] `apps/api/tests/unit/workers/test_dormancy_check.py` TDD: 366 日で dormant + 通知 (FR-060、SC-008)
- [x] **T705** [US7] Playwright E2E: Owner の所有権移譲 UI + dormant バッジ表示 (PR-003、architect B-4 対応)

---

## Phase 13: US9 - API key と scope（P2）

- [ ] **T800** [US9] `models/api_key.py` 新規 (FR-074)
- [ ] **T801** [P] [US9] `services/api_key_service.py` 新規: 発行 + 検証 + scope + 違反カウンタ + 自動 revoke (FR-074、FR-079、FR-080、FR-081)
- [ ] **T805** [P] [US9] `models/project_member.py` に `@event.listens_for(ProjectMember, "after_update")` 実装: `removed_at` set 検出で同一 connection で `OutboxEvent` INSERT (FR-076a、data-model §4.3、architect B-3)
- [ ] **T806** [P] [US9] `apps/api/tests/integration/test_member_removal_outbox_enqueue.py` TDD: TX 内 enqueue 確認
- [ ] **T810** [US9] `specs/006-permissions-redesign/contracts/api-keys.yaml` 新規作成 (FR-075、security 重要 / codex 指摘)
- [ ] **T811** [P] [US9] `api/web_v1/account/api_keys.py` 新規 (FR-074、FR-075)
- [ ] **T820** [P] [US9] `workers/api_key_auto_revoke.py` 新規: outbox processor 経由で 60s 以内 revoke (FR-076a〜c)
- [ ] **T830** [P] [US9] `apps/web/src/routes/(app)/account/api-keys/+page.svelte` 新規 (FR-074)
- [ ] **T840** [P] [US9] `apps/api/tests/security/api_key/test_scope_violation_auto_revoke.py` TDD: 10 min で 10 件違反 → 自動 revoke (FR-080、SC-009)
- [ ] **T841** [P] [US9] `apps/api/tests/security/api_key/test_member_removal_revoke_60s.py` TDD: DELETE → 60s 以内 403 (FR-076a、SC-009)
- [ ] **T842** [US9] Playwright E2E: scope 違反 / 離脱 revoke (PR-003、SC-009 セキュリティ重要)
- [ ] **T843** [P] [US9] `apps/api/tests/security/api_key/test_ip_violation_separate_counter.py` TDD: scope 違反とは別カウンタ (FR-081)

---

## Phase 14: GDPR / DSR / 削除フロー（P2）

- [ ] **T900** [CR] `api/web_v1/account/dsr.py` 新規 (FR-109)
- [ ] **T901** [P] [CR] `services/user_deletion_service.py` 新規: email / display_name 匿名化 (FR-105)
- [ ] **T902** [P] [CR] `workers/invitation_email_null.py` 新規: 30 日後 null 化 (FR-106)
- [ ] **T903** [P] [CR] `workers/trusted_email_null.py` 新規: 90 日後 null 化 (FR-108)
- [ ] **T905** [P] [CR] DSR endpoint 契約: `contracts/account.yaml` 新規または projects.yaml 拡張 (FR-109)

---

## Phase 15: Superuser セキュリティ（P2）

- [ ] **T950** [CR] `models/superuser.py` + `models/superuser_approval_request.py` 新規 (FR-111)
- [ ] **T951** [P] [CR] `services/superuser_service.py` 新規: M-of-N + break-glass 72h + WebAuthn 登録/検証 (FR-111、FR-072)
- [ ] **T952** [P] [CR] `apps/api/echoroo/scripts/init_superuser.py` CLI interactive（TOTP + 一時パスワード + 24h 以内 WebAuthn 登録強制）(FR-112、quickstart §3)
- [ ] **T953** [P] [CR] Trigger `prevent_last_superuser_deletion`: T020e で実装済み、app role 限定 + migrator skip (FR-111a)
- [ ] **T954** [P] [CR] `apps/api/tests/security/race_conditions/test_superuser_last_protection.py` TDD: DB role 別挙動 (FR-111a、SC-022)
- [ ] **T955** [P] [CR] `apps/web/src/routes/(admin)/+layout.server.ts` + WebAuthn UI + IP allowlist 適用 (FR-111)
- [ ] **T956** [P] [CR] `apps/api/tests/security/authorization/test_superuser_api_key_forbidden.py` TDD: superuser 操作が API key 経由で 403 (FR-084、PR-007 Superuser)
- [ ] **T957** [P] [CR] `apps/api/tests/security/race_conditions/test_superuser_break_glass_mode.py` TDD: 1→1 で break-glass 発動、72h タイマー (FR-111)
- [ ] **T958** [P] [CR] `apps/api/tests/security/authorization/test_superuser_response_filter_raw_forbidden.py` TDD: 全 response filter 経路（detections / recordings / sites / tags / exports）を parametric fixture で列挙、superuser 主体でも生 lat/lng / 生座標 / HIDDEN 対象が raw で返らないことを検証（superuser は project-scope allowlist 経由の場合のみ対象読み取り可、raw 生データ bypass は不可）(FR-112a)
- [ ] **T155b** [CR] Wire real `ApiKeyVerifier` (Phase 15 scope) into `AuthRouterMiddleware` and re-enable 2FA enforcement (`TwoFactorEnforcementMiddleware`) for `/api/v1/*`. T155 polish round 2 narrowed the enforcement prefix to `/web-api/v1/*` only because the auth router's `programmatic_prefix` is currently a sentinel — `/api/v1/*` requests never populate `request.state.principal`. Once T950+ ships the KMS-backed verifier, flip `programmatic_prefix` back to `/api/v1` and broaden `TwoFactorEnforcementMiddleware.enforcement_prefix` so FR-069 / FR-073 cover both surfaces (FR-069、FR-073、FR-077)

---

## Phase 16: 最終統合・セキュリティテスト・パフォーマンス

### 16.1 セキュリティテスト 75+（PR-007 個別分解）

本 Phase で spec PR-007 の 11 カテゴリを網羅達成する。既に各 US Phase で個別 T が配置済みのものは再記載しないが、不足分を追加:

- [ ] **T970** [CR] ネガティブセキュリティテスト 75+ 達成確認（個別 T971-T979 + 各 US Phase の個別テストで OWASP Top 10 A01/A07 準拠を満たす）(PR-007、NFR-002、SC-011)
- [ ] **T971** [P] [CR] `tests/security/csrf/test_samesite_strict.py` (FR-097)
- [ ] **T972** [P] [CR] `tests/security/csrf/test_api_v1_no_cookie.py` (FR-077、security C-2)
- [ ] **T973** [P] [CR] `tests/security/race_conditions/test_streaming_permission_change.py` (security H-6、CSV stream 中の permission 変更)
- [ ] **T974** [P] [CR] `tests/security/key_rotation/test_hmac_dual_key.py` (FR-040、14 日 grace)
- [ ] **T975** [P] [CR] `tests/security/key_rotation/test_pii_hash_key_rotation_dual_write.py` (FR-091b、v1/v2 90 日 dual-write)
- [ ] **T976** [P] [CR] `tests/security/invitations/test_email_header_injection.py` (FR-101)
- [ ] **T977** [P] [CR] `tests/security/key_rotation/test_cmk_deletion_window_guard.py` (Runbook CMK deletion 30 日 minimum)
- [ ] **T978** [P] [CR] `tests/security/api_key/test_rotation_180d_scope_degrade.py` (FR-083、180 日 scope 縮退)
- [ ] **T979** [P] [CR] `tests/security/authentication/test_clickjacking_frame_ancestors.py` (FR-102)

### 16.2 Contract tests

- [ ] **T980** [P] [CR] `apps/api/tests/contract/test_openapi_diff.py` 改修: FastAPI 生成 `openapi.json` と `contracts/*.yaml` diff (research §17、SC-019)
- [ ] **T981** [P] [CR] `apps/api/tests/contract/test_security_headers.py` 新規: 全 path operation に HSTS / CSP / X-Frame 等のセキュリティヘッダ必須、Location / metadata 系レスポンスは `Cache-Control: private, no-store` 必須 (FR-025c)、CORS preflight 応答要件は FR-099 系を参照 (FR-102、FR-025c、FR-099、security C-1)
- [ ] **T981b** [P] [CR] `apps/api/tests/security/search_leak/test_search_index_ready_on_toggle_on.py` 新規: `allow_detection_view` OFF → ON 切替時、検索 index 再構築完了 (`index_ready=true`) まで該当プロジェクトの detection が検索結果に含まれないことを TDD 検証 (FR-025b、SC-018 補完)
- [ ] **T982** [P] [CR] `apps/api/tests/contract/test_auth_separation.py` 新規: `/api/v1/*` に Cookie 401、`/web-api/v1/*` に Bearer 401 (FR-077)
- [ ] **T983** [P] [CR] `apps/api/tests/contract/test_operation_security_override.py` 新規: state-changing path operation で csrfToken override を assert (codex 致命 1 / 3)

### 16.3 Performance 検証

- [ ] **T990** [P] [CR] k6 / Locust シナリオ `tests/performance/*.py` 5 シナリオ配置（CP §負荷試験）
- [ ] **T991** [P] [CR] Recording list 100 件 p95 < 800ms (NFR-004)
- [ ] **T992** [P] [CR] 認証+権限 p95 < 30ms、クエリ p95 ≤ 4（NFR-001 + NFR-001a の bulk preload 含む）(NFR-001、NFR-001a、SC-015)
- [ ] **T993** [P] [CR] 監査ログ 1000+ 並列 INSERT chain 整合性 (FR-093、SC-014)
- [ ] **T994** [P] [CR] Grafana Dashboard + alerting: 2FA ログイン成功率 SLO < 95% で PagerDuty、30 日 1000 試行以上対象 (SC-006)

### 16.4 Mutation testing

- [ ] **T995** [CR] mutmut の CI gate を **fail モードに昇格**、権限系 4 モジュール mutation score 80% 以上 (PR-004、SC-012)

### 16.5 カバレッジ / Frontend

- [ ] **T996** [CR] pytest-cov で権限系 95% / その他 85% カバレッジ強制 (PR-005、SC-013)
- [ ] **T997** [CR] Frontend E2E full suite gate 化（各 US Phase で配置された Playwright を full suite として 1 回 green 確認、T133/T174/T221/T311/T324/T404/T414/T533/T652/T705/T842 含む）(PR-003)

### 16.6 Runbook 検証

- [ ] **T998** [CR] `scripts/wipe_database.py` + `init_superuser.py` + `initial_iucn_sync.py` + `seed_moe_rdb.py` を quickstart §3 手順で動作確認 (FR-113、FR-114、quickstart)

### 16.7 最終 docs 整合

- [ ] **T999** [CR] `requirements-traceability.md` を tasks と同期、`comm -23 spec_ids trace_ids` で未リンク 0 件を CI 強制

### 16.8 Post-launch cleanup

- [x] **T999b** [POLISH] ~~`apps/web/src/hooks.server.ts:155` の legacy `refresh_token` cookie fallback を撤去する。~~ **完了 (early, Phase 4 中)**: pre-launch でユーザーがいないため transitional fallback は不要だった。`hooks.server.ts` / `+layout.server.ts` / `+page.server.ts` から `refresh_token` cookie 参照を削除し、`echoroo_logged_in` marker のみで認証判定するよう変更済み。`apps/web/src/lib/stores/auth.svelte.ts` の logout transition fallback の再検討は別タスクで継続。

---

## Dependencies（統一依存グラフ）

```
Phase 1 (Setup, T001-T012)
        ↓
Phase 2 (Foundational, T019-T100f)
        ↓
      [T100f が唯一の同期点]
        ↓
  ┌────────────────────────────────────────────────────────┐
  │  Phase 3 (US11) + Phase 4 (US8) + Phase 5-13 すべて並列開始可    │
  │  ただし依存:                                             │
  │  - Phase 3 T118 (router 分割) 完了後に同一ファイル並列が解ける   │
  │  - Phase 5-9 (P1 US1/2/3/4/10) は Phase 3 完了を待つ推奨        │
  │  - Phase 10-13 (P2) は Phase 3 + 4 完了を待つ推奨               │
  │  - **Phase 5-7 (US1/US2/US10) の E2E (T221/T311/T324) は Phase 4│
  │    (US8 2FA) 完了後に実行**: E2E は authenticated user を要し、  │
  │    2FA 未設定ユーザーでは login middleware が 403 を返すため。   │
  │    実装 (service/API) は並列可、E2E gate のみ sequential。       │
  └────────────────────────────────────────────────────────┘
        ↓
Phase 14 (GDPR) + Phase 15 (Superuser) 並列
        ↓
Phase 16 (最終統合、mutation gate 昇格、E2E full suite)
```

**Critical Path**: Phase 1 → Phase 2 → T100f → Phase 3 (US11 MVP) → Phase 16 (gate 昇格)

**並列性の最大化**:
- Phase 2 完了直後の同期点は T100f のみ
- T100f 通過後は Phase 3 / Phase 4 / Phase 5-13 / Phase 14 / Phase 15 すべてが独立 worktree で並列可
- Phase 16 は全 Phase 完了後の直列タスク

**並列不可ペア**:
- T020a〜g は sequential (Alembic migration は単一 file)
- T040a〜g は sequential (core/permissions.py 単一 file)
- その他 [P] マーク付きは独立 file

---

## Parallel Example（SSA 並列起動、worktree isolation 必須）

**Wave 1（Phase 1+2、6 SSA 並列可）**:
- backend-developer × 4: T030a-d / T040a-g / T050a-b / T060a-c 並列（各サブタスクは独立 [P]、ただし同一モジュール内は sequential commit）
- backend-developer × 1: T019 + T020a〜g sequential（単一 Alembic migration file）
- backend-developer × 1: T070-T075 middleware 6 個

**Wave 2（T100f 通過後、最大 8 SSA 並列）**:
- US11 系 T118 完了後、T120-T129 を 7 SSA 並列（各ファイル独立）
- US8 系 T140/T145/T146/T160-T163 を 5 SSA 並列

**Wave 3（P1 全 US + P2 並列、worktree isolation 必須）**:
- US1/US2/US10/US3/US4 を 5 worktree、5 SSA
- US5/US6/US7/US9 を 4 worktree、4 SSA
- 同時に CR 系（Superuser / GDPR）を別 worktree

---

## Checkpoint Summary

| Phase | Checkpoint | MVP 増分 |
|---|---|---|
| 1-2 完了 | T100f blocking gate 通過 | Alembic baseline、全 lint、Permission engine |
| 3 完了 | US11 統合 | 全 API に Permission guard 経由 |
| 4 完了 | US8 統合 | 2FA 必須化 |
| 5-7 完了 | US1/US2/US10 | Public MVP + ライセンス |
| 8-9 完了 | US3/US4 | Restricted トグル |
| 10-13 完了 | US5-9 拡張 | Trusted + Auto-obscure + API key |
| 14-15 | GDPR + Superuser | プロダクション運用 |
| 16 完了 | mutation gate + E2E gate | リリース可能 |

---

## Estimated Effort（変更なし、粒度分割で並列性向上）

- Phase 1-2: 1-2 週間
- Phase 3-4: 2 週間（並列可）
- Phase 5-13: 4-6 週間（大規模並列）
- Phase 14-15: 1 週間
- Phase 16: 2 週間

**合計: 12-16 週（3-4 ヶ月）**、SSA 並列度次第で短縮可
