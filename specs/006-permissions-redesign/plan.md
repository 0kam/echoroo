# Implementation Plan: 権限・公開レベル再設計（Permissions and Visibility Redesign）

**Branch**: `006-permissions-redesign` | **Date**: 2026-04-24 | **Spec**: [spec.md](./spec.md) (Rev.3.2)
**Input**: Feature specification from `/specs/006-permissions-redesign/spec.md`

## Summary

Echoroo の権限モデルをプレローンチ段階で全面的に再設計する。`ProjectVisibility` を **Public / Restricted の 2 段階** に簡素化（Private 廃止）、Permission enum を **28 個に細粒度化**（Project 26 + User 自己管理 2）、`Trusted User` を **Authenticated への ephemeral capability overlay** として導入、**Location Sensitivity を H3 解像度単一軸**で管理する。

権限判定は **単一の `is_allowed` アルゴリズム（2 ステージ: Permission gate + Response filter）** に集約し、全エンドポイントが `Action` Pydantic model を経由する。生 lat/lng は **DB / API / Celery / log / S3 の全経路で排除**（FR-028〜FR-031 + FR-028a〜f）、監査ログは **raw PII を最初から保持しない設計**（keyed hash のみ、FR-090〜FR-096）で GDPR と append-only を構造的に両立する。

認証面では **TOTP 2FA 必須化**（`security_stamp` でセッション revocation）、**API key + scope**（programmatic API と first-party session API を URL prefix で分離）、**Superuser は WebAuthn hardware key 2 本 + IP allowlist + 最低 3 名 + M-of-N 承認**（FR-111）を導入。既存データは全消去し、Alembic 単一ベースライン migration で再構築する（wipe は 3 点一致ガードで 2 度実行不可、FR-114）。

TDD は権限系モジュールに mutation testing 80% 以上 + Canonical Matrix パラメトリック全探索を強制（PR-002〜PR-005）、E2E は P1 + セキュリティ重要シナリオ（SC-004 / SC-005 / SC-009）のみ。ネガティブセキュリティテスト 75+ シナリオを `tests/security/` に配置（PR-007）。

## Technical Context

**Language/Version**:
- Backend: Python 3.11 (Echoroo 既存)
- Frontend: TypeScript 5.x, Svelte 5, SvelteKit 2

**Primary Dependencies**:
- Backend: FastAPI, SQLAlchemy 2.0 (async), Pydantic v2, Alembic, Celery, Redis, h3-py, argon2-cffi, pyotp, webauthn, resend, boto3 (KMS)
- Frontend: SvelteKit 2, TanStack Query, Tailwind CSS, Paraglide JS

**Storage**:
- PostgreSQL 16+（pgvector 拡張）— プロジェクト / ユーザー / 監査ログ / Taxon sensitivity
- Redis — セッション、レート制限バケット、Celery ブローカー、Trusted 失効 pub/sub
- S3 (LocalStack dev / AWS prod) — recordings, audit log Object Lock archive
- AWS KMS（または同等）— TOTP secret CMK + DEK, 招待 HMAC 鍵, 監査ログ chain_key, PII hash key

**Testing**:
- Backend: pytest + pytest-asyncio + mutmut（権限系の mutation testing）+ httpx (contract), testcontainers-python (integration)
- Frontend: Vitest + Playwright (E2E)
- Security: `tests/security/` 配下にネガティブセキュリティテスト 75+ シナリオ（PR-007）

**Target Platform**: Linux server（Docker Compose dev、K8s prod を想定）、モダンブラウザ（Chrome/Firefox/Safari/Edge 最新 2 バージョン）、iOS 15+/Android 11+ のモバイルブラウザ

**Project Type**: Web application（backend + frontend モノレポ、`apps/api` + `apps/web`）

**Performance Goals**（spec NFR-001 / NFR-001a / NFR-004 から）:
- 認証 + Permission 判定のみで p95 < 30ms、DB クエリ数 p95 ≤ 4
- Recording list / Detection list 100 件の権限込み応答 p95 < 800ms（per-row Taxon は `WHERE taxon_id IN (...)` の 1 クエリ preload、合計 p95 ≤ 5 クエリ + 1 業務クエリ）
- TOTP 検証レート: IP+user 5/15min、10 連続で 15 分ロック
- API key scope 別: read-only 600/min, vote 60/min, upload 10/min (Redis token bucket)

**Constraints**（spec から）:
- 生 lat/lng を DB カラム・API レスポンス・log・Celery payload・S3 metadata いずれにも保持しない（FR-028〜031、FR-028a〜f）
- 監査ログは append-only、raw PII を最初から保持しない（keyed hash のみ）
- 既存データは全消去、Alembic 単一ベースライン migration（FR-113〜114、wipe 2 度目実行不可 3 点一致ガード）
- Permission 判定は再帰呼び出し禁止、ステージ 2 は DB 再アクセス禁止（FR-008）
- Superuser 操作は programmatic API 不可（FR-084）、WebAuthn hardware key 2 本必須（FR-111）

**Scale/Scope**（プレローンチ想定）:
- 初期ユーザー: ~100 人（市民科学参加者 + 研究者）
- プロジェクト: 10-50（Public + Restricted 混在）
- Recording: 10k+（プロジェクトあたり数百〜数千）
- Detection: 1M+（ML 推論後）
- 成長想定: リリース後 1 年で 10 倍想定（1k ユーザー、500 プロジェクト、100k recording、10M detection）

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### I. Clean Architecture — ✅ PASS

spec Rev.3.2 は明確な 4 層構造:
- **API Layer**: `apps/api/echoroo/api/v1/` + `web-api/v1/`（URL prefix 分離、FR-077）。Permission guard を全エンドポイントで経由（FR-008 + FR-008a Action Pydantic カタログ + CI 静的解析）
- **Service Layer**: Permission 判定（`core/permissions.py` に `is_allowed` / `compute_effective_permissions` / `compute_effective_resolution`）、Invitation accept TX、ownership transfer など
- **Repository Layer**: `ProjectRepository`、`TrustedUserRepository` などで DB クエリをカプセル化。bulk Taxon sensitivity preload を `WHERE IN` で実行（NFR-001a）
- **Domain Models**: `ProjectMember`, `ProjectTrustedUser`, `ProjectInvitation` など、フレームワーク非依存な SQLAlchemy ORM モデル

横断的関心事（認証、CSRF、ロギング、PII hash）は middleware / decorator で分離。

### II. Test-Driven Development — ✅ PASS

spec の PR-001〜PR-007 で TDD を徹底:
- PR-001: Red → Green → Refactor サイクル
- PR-002: 権限系モジュールは unit / contract / integration の 3 層で Canonical Matrix パラメトリック全探索
- PR-003: E2E は P1（US1/2/3/4/8/10/11）+ セキュリティ重要シナリオ（SC-004/005/009）
- PR-004: 権限系 mutation score 80% 以上（mutmut）
- PR-005: カバレッジ 権限系 95% / その他 85%（分岐含む）
- PR-007: ネガティブセキュリティテスト 75+ シナリオ（`tests/security/`）

Contract tests は全 API エンドポイントに必須（Constitution II 準拠）。

### III. Type Safety — ✅ PASS

- Backend: Pydantic v2 (`Extra.forbid` を全 update 系 model に適用、FR-100)、SQLAlchemy 2.0 の 2.x 型注釈、mypy strict mode 必須。`Action` Pydantic model に `model_validator` で整合性強制（FR-008a）
- Frontend: TypeScript strict mode、API レスポンスは OpenAPI 自動生成型（`openapi-typescript`）経由

Runtime validation は system boundaries（API 入力、外部 API レスポンス、IUCN レスポンスの sanity check）で実施（FR-036b）。

### IV. ML Pipeline Architecture — ✅ PASS

spec で扱う ML / 重処理は全て Celery task:
- IUCN Red List 同期（週次バッチ、FR-036）
- DEK rewrap（月次バッチ、Runbook）
- API key の scope 違反自動 revoke（outbox pattern、FR-076d）
- 検索 index 再構築（toggle 変更時、FR-025）
- SEARCH_CROSS_PROJECT の ON → OFF / OFF → ON 処理（FR-025a/b）

API サーバーはブロックしない。Celery broker (Redis) は TLS + AUTH + ACL（NFR-009）。

### V. API Versioning — ✅ PASS

全エンドポイントが `/api/v1/*`（programmatic、API key 必須）または `/web-api/v1/*`（first-party session、Cookie + CSRF）の 2 系統（FR-077、FR-099）。major version `v1` で本リデザインをリリース。後方互換性は同一 major version 内で維持。

### USER_SCOPE_PERMISSIONS（SEARCH_CROSS_PROJECT 等）

以下の 3 Permission は **project resource を引数にとらない User-scope Permission**。`is_allowed(user, project=None, action)` のブランチで、Canonical Matrix を bypass してログイン状態のみで判定する:

```python
USER_SCOPE_PERMISSIONS: frozenset[Permission] = frozenset({
    Permission.MANAGE_API_KEY,
    Permission.MANAGE_2FA,
    Permission.SEARCH_CROSS_PROJECT,
})
```

SEARCH_CROSS_PROJECT の検索結果は `SearchGate.execute()` 内部で per-project の `allow_detection_view=ON` フィルタを SQL レベルで適用する。

### CORS ポリシー

- `/api/v1/*`: `Access-Control-Allow-Origin: *`（public）、`Allow-Credentials: false`、Authorization ヘッダのみ受理
- `/web-api/v1/*`: 厳格な same-origin（`https://echoroo.app` のみ）、`Allow-Credentials: true`、Cookie + CSRF
- `/web-api/v1/admin/*`: さらに superuser の IP allowlist（CIDR）で絞る（FR-111）

CORS 設定は FastAPI の `CORSMiddleware` で URL prefix 別に実装し、`middleware/cors.py` で集約。

### CI 静的解析（3 経路）

plan 実装時に以下の 3 種類の CI lint を `scripts/lint_*.py` として実装（research.md §18 参照）:
1. **Permission guard 経由検出**: 全 path operation で `is_allowed` / `Depends(check_action())` 経由
2. **ResponseFilter 経由検出**: Recording/Detection/Site レスポンスが ResponseFilter を通過
3. **SearchGate 経由検出**: `select(Detection)` 系の直接使用を `SearchGate` 経由のみに限定
4. **raw lat/lng regression guard**: migration / ORM / Pydantic / openapi.json に lat/lng カラム・field 追加を検出
5. **ACTIONS カタログ対応**: 全 path operation が `ACTIONS` に登録（pytest リフレクション）

### Security Requirements — ✅ PASS

Constitution § Security の全項目を spec が上回る水準で満たす:
- Authentication: JWT + 2FA + `security_stamp`（FR-065〜FR-073）
- RBAC: service layer で enforce（FR-008 + Canonical Matrix）
- Input validation: Pydantic `Extra.forbid`（FR-100）
- File uploads: EXIF strip + magic byte 検証（FR-028a + 実装で追加）
- SQL injection: SQLAlchemy parameterized query
- Sensitive data logging: PII hash、raw lat/lng redact（FR-028c、FR-091a）
- HTTPS + HSTS（FR-102）
- Rate limiting: TOTP、招待、API key すべて（FR-054、FR-056、FR-082）
- OWASP A01/A07 準拠（NFR-002）

### Review Process — ✅ PASS

全 FR に対応する tests が PR テンプレで必須（PR-006）、mypy + ruff + eslint + tsc が CI gate。

### 結論: **Constitution Check PASS**。追加の正当化（Complexity Tracking）は不要。

## Project Structure

### Documentation (this feature)

```text
specs/006-permissions-redesign/
├── plan.md              # This file (this plan output)
├── research.md          # Phase 0 output — technical decisions (KMS 選定、WebAuthn ライブラリ、検索エンジン、mutation testing tool 等)
├── data-model.md        # Phase 1 output — ORM エンティティ詳細、Alembic migration プラン、CHECK 制約、index 設計
├── quickstart.md        # Phase 1 output — 開発者向けのローカル起動 / 2FA セットアップ / 初期 superuser 作成手順
├── contracts/           # Phase 1 output — OpenAPI スキーマ、主要エンドポイント contract
│   ├── auth.yaml        # /web-api/v1/auth (login, 2FA challenge, refresh)
│   ├── projects.yaml    # /api/v1/projects, /web-api/v1/projects
│   ├── trusted.yaml     # Trusted User 発行 / accept / revoke
│   ├── detections.yaml  # Detection list / export / vote
│   ├── audit.yaml       # AuditLog 閲覧
│   └── admin.yaml       # superuser 操作 (archive restore, 2FA reset, IUCN resync)
├── checklists/          # 実装前チェックリスト（security、performance、accessibility）
│   ├── security.md
│   └── performance.md
└── tasks.md             # Phase 2 output (/speckit.tasks 生成、本 plan では作らない)
```

### Source Code (repository root)

Echoroo は Web application（backend + frontend モノレポ）:

```text
apps/api/                          # FastAPI backend
├── echoroo/
│   ├── api/
│   │   ├── v1/                    # Programmatic API (API key 必須、FR-077)
│   │   │   ├── auth.py            # (新規) JWT + 2FA チャレンジ
│   │   │   ├── projects.py        # 改修 — Permission guard 経由化
│   │   │   ├── recordings.py      # 改修 — Response filter 経由化
│   │   │   ├── detections.py      # 改修 — check_project_access 追加、export に withheld_reason 列
│   │   │   ├── tags.py            # 改修 — check_project_access 追加
│   │   │   ├── uploads.py         # 改修 — EXIF strip (FR-028a)、acknowledge checkbox (FR-110)
│   │   │   ├── custom_models.py   # 改修 — check_project_access 追加
│   │   │   ├── annotation_votes.py # 改修 — source 追加、VOTE permission 強制
│   │   │   ├── annotation_comments.py # 改修 — source 追加
│   │   │   ├── search.py          # 新規 SearchGate (FR-025, 3 経路統一)
│   │   │   ├── trusted.py         # 新規 — Trusted User 発行 / accept / revoke
│   │   │   ├── audit_log.py       # 新規 — project_audit_log 読み取り
│   │   │   └── admin.py           # 新規 — superuser 操作
│   │   └── web_v1/                # First-party session API (Cookie + CSRF、FR-077)
│   │       └── ... (v1 と同じ構造、認証方式のみ異なる)
│   ├── core/
│   │   ├── permissions.py         # 全面書き換え — is_allowed、compute_effective_permissions、compute_effective_resolution、Action モデル、ACTIONS カタログ、SUPERUSER_PROJECT_SCOPE_ALLOWLIST、ROLE_PERMISSIONS
│   │   ├── audit.py               # 新規 — AuditLogSanitizer、PII hash 化、hash chain
│   │   ├── auth.py                # 全面書き換え — TOTP、WebAuthn、security_stamp
│   │   ├── kms.py                 # 新規 — KMS 抽象化 (envelope encryption、GenerateMac)
│   │   └── response_filter.py     # 新規 — Pydantic ResponseFilter (FR-011)
│   ├── middleware/
│   │   ├── auth.py                # 改修 — programmatic/first-party 分離、CSRF enforce
│   │   ├── audit.py               # 新規 — access log with PII redaction (FR-028c)
│   │   └── rate_limit.py          # 新規 — API key scope 別レート (FR-082)
│   ├── models/
│   │   ├── project.py             # 改修 — Visibility 2 値、restricted_config JSONB、license_history 分離
│   │   ├── project_member.py      # 改修 — Viewer expires_at 追加
│   │   ├── project_invitation.py  # 改修 — kind enum、CHECK 制約 (FR-048)
│   │   ├── project_trusted_user.py # 新規 — ephemeral capability overlay
│   │   ├── project_taxon_override.py # 新規
│   │   ├── site.py                # 改修 — latitude/longitude カラム削除 (FR-031)
│   │   ├── user.py                # 改修 — 2FA secret、security_stamp、last_first_party_activity_at
│   │   ├── api_key.py             # 新規
│   │   ├── taxon_sensitivity.py   # 新規
│   │   ├── iucn_sync_attempt.py   # 新規
│   │   ├── audit_log.py           # 新規 — project / platform 2 テーブル、hash chain、raw PII なし
│   │   ├── superuser.py           # 新規
│   │   └── system_settings.py     # 新規
│   ├── repositories/
│   │   └── (各モデルに対応する async repository、bulk preload サポート)
│   ├── services/
│   │   ├── permissions.py         # 新規 — Permission 決定ロジック（core/permissions.py のビジネス側）
│   │   ├── trusted_service.py     # 新規
│   │   ├── invitation_service.py  # 改修 — kind 統一、HMAC 署名、email 一致検証
│   │   ├── ownership_service.py   # 新規 — transfer / dormant / archived / restore
│   │   ├── taxon_service.py       # 新規 — IUCN sync、MOE RDB、override approval
│   │   ├── audit_service.py       # 新規
│   │   ├── api_key_service.py     # 新規
│   │   └── search_gate.py         # 新規 — 3 検索経路の統一 entry
│   ├── workers/
│   │   ├── iucn_sync.py           # 新規 — 週次バッチ、sanity check、cert pinning
│   │   ├── dek_rewrap.py          # 新規 — 月次バッチ
│   │   ├── api_key_revoke.py      # 新規 — 離脱時自動 revoke outbox
│   │   ├── dormancy_check.py      # 新規 — 日次バッチ
│   │   └── search_index.py        # 新規 — toggle 変更時の再構築
│   └── schemas/
│       └── (Pydantic request/response、全て Extra.forbid + ResponseFilter 対応)
├── tests/
│   ├── contract/                  # 全エンドポイントの contract test
│   ├── integration/               # service layer 統合テスト
│   ├── unit/                      # permissions 決定ロジック単体テスト（Canonical Matrix パラメトリック）
│   └── security/                  # 新規 — ネガティブセキュリティ 75+ シナリオ (PR-007)
└── alembic/
    └── versions/
        └── 00000000_baseline.py   # 新規単一 migration (FR-113)、wipe 後に再構築

apps/web/                          # SvelteKit frontend
├── src/
│   ├── routes/
│   │   ├── (public)/              # 新規 — Guest 向け Public プロジェクト閲覧
│   │   │   └── projects/[id]/
│   │   ├── (app)/                 # 既存 — 認証済みユーザー
│   │   │   ├── login/             # 改修 — 2FA flow
│   │   │   ├── register/          # 改修 — 2FA 強制セットアップ
│   │   │   ├── projects/[id]/
│   │   │   │   ├── settings/      # 改修 — restricted_config トグル UI
│   │   │   │   ├── trusted/       # 新規 — Trusted 招待管理
│   │   │   │   ├── members/       # 改修
│   │   │   │   └── audit/         # 新規 — project_audit_log 閲覧
│   │   │   ├── account/
│   │   │   │   ├── 2fa/           # 新規
│   │   │   │   └── api-keys/      # 新規
│   │   │   └── invite/[token]/    # 新規 — 招待 accept
│   │   └── (admin)/               # superuser 専用 UI (Web 限定、FR-084)
│   │       ├── projects/          # archived restore、looser override 承認
│   │       ├── users/             # 2FA reset
│   │       └── audit/             # platform_audit_log 閲覧
│   ├── lib/
│   │   ├── api/                   # 改修 — /api/v1/ と /web-api/v1/ の 2 clients
│   │   ├── stores/
│   │   │   ├── auth.svelte.ts     # 改修 — security_stamp 同期
│   │   │   └── permissions.svelte.ts # 改修 — Canonical Matrix クライアント側キャッシュ (FR-011a TTL 30s)
│   │   ├── utils/
│   │   │   └── h3_to_latlng.ts    # 新規 — @turf/h3-js で地図描画 (spec FR-028a 代替)
│   │   └── components/
│   │       ├── TrustedInviteForm.svelte   # 新規
│   │       ├── RestrictedToggles.svelte   # 新規
│   │       └── HSpecYMaps.svelte          # 改修 — h3_index 経由描画
│   └── hooks.server.ts            # 改修 — CSRF token 発行、Cookie Path=/web-api/v1/
└── tests/
    ├── unit/
    └── e2e/                       # Playwright — P1 + セキュリティ重要シナリオ (SC-004/005/009)

tests/security/                    # 新規 — 75+ ネガティブセキュリティテスト (PR-007)
├── authentication/
├── authorization/
├── invitations/
├── auto_obscure/
├── search_leak/
├── audit_log/
├── csrf/
├── race_conditions/
├── key_rotation/
└── api_key/
```

**Structure Decision**: **Web application**（backend + frontend モノレポ）。既存の `apps/api/` + `apps/web/` 構造をそのまま使用する。ただし本リデザインでは (a) `core/permissions.py` を全面書き換え、(b) 新規モデル 7+ 個の追加、(c) 既存の全 API エンドポイントに Permission guard を経由させる改修、(d) `tests/security/` ディレクトリの新設、が必要。Alembic は単一ベースライン migration で再構築（FR-113）。

## Complexity Tracking

Constitution Check はすべて PASS のため、Complexity Tracking への記入は不要。

---

## Phase 0: Research (次フェーズ)

`research.md` で以下の technical decisions を確定する:

1. **KMS**: AWS KMS vs HashiCorp Vault vs 自前 envelope encryption の比較、コスト + プレローンチ環境での導入容易性
2. **WebAuthn ライブラリ**: Python `py_webauthn` vs `fido2`、Svelte 側のクライアント実装
3. **検索エンジン**: 現行 PostgreSQL FTS + pgvector に OpenSearch を追加するか、それとも PostgreSQL FTS + pgvector のみで済ませるか（FR-025 の 3 経路抽象化を先に書く）
4. **Mutation testing tool**: mutmut vs Cosmic Ray（PR-004）
5. **Background job scheduler**: Celery Beat（既存）の設定、dormancy / IUCN sync / DEK rewrap の同居戦略
6. **Audit log の outbox pattern**: transactional outbox library（`transactional-outbox` or 自前実装）
7. **JSONB Pydantic sanitizer**: `AuditLogSanitizer` を独自実装、既存の Pydantic `field_validator` と組み合わせる
8. **Rate limit backend**: Redis token bucket（`aiolimiter` or 自前）
9. **Frontend role cache invalidation**: `x-user-permission-version` response header + TanStack Query invalidation
10. **h3 → 地図描画**: `@turf/h3-js` vs `h3-js` 直接使用、精度に応じた polygon vs marker 切替
11. **Playwright での 2FA**: `TEST_MODE` で TOTP バイパス vs 固定 secret + TOTP 自動生成

## Phase 1: Design & Contracts (次フェーズ)

1. **data-model.md**: 全 ORM モデルのカラム、FK、index、CHECK 制約を仕様化
2. **contracts/*.yaml**: OpenAPI 3.1 で /api/v1 と /web-api/v1 の両方を仕様化
3. **quickstart.md**: ローカル起動手順、初期 superuser 作成、2FA セットアップ、wipe 手順
4. **checklists/security.md**: implement 前のセキュリティチェックリスト（25+ 項目）
5. **checklists/performance.md**: NFR-001 / NFR-001a / NFR-004 達成のためのチェックリスト

---

**Plan Status**: Phase 0 (Research) → Phase 1 (Design & Contracts) → `/speckit.tasks` へ。Phase 0/1 の成果物は同一の `/speckit.plan` 実行内で生成する。
