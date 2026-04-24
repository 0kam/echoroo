# Requirements Traceability Matrix

**Branch**: `006-permissions-redesign`
**Date**: 2026-04-24
**Input**: spec.md Rev.3.2 の全 FR / NFR / PR / SC + plan 成果物

spec の各要件が plan 成果物のどこで具体化されているかを追跡する。implement 開始前に未リンクがゼロであることを CI で検証する（plan レビューで codex 指摘 D-9 対応）。

## 凡例

- ✅ = plan 成果物で具体化済み
- 📋 = tasks.md で具体化予定（本 plan では実装方針明記まで）
- 🔄 = 複数成果物で分散カバー

成果物略号:
- **P** = plan.md
- **R** = research.md
- **D** = data-model.md
- **Q** = quickstart.md
- **C** = contracts/*.yaml
- **CS** = checklists/security.md
- **CP** = checklists/performance.md

---

## 機能要件 (FR)

### Visibility と主体 (FR-001〜FR-007)

| FR | 要約 | 具体化先 | 状態 |
|---|---|---|---|
| FR-001 | Visibility 2 値（Public/Restricted） | D §1 `ProjectVisibility` enum、D §3.4 `projects.visibility` | ✅ |
| FR-002 | 6 主体（Guest/Authenticated/Viewer/Member/Admin/Owner） | D §1 `ProjectMemberRole` enum、P "6 主体モデル" | ✅ |
| FR-003 | Owner は `Project.owner_id`、1 プロジェクト 1 人 | D §3.4 projects.owner_id FK、C projects.yaml | ✅ |
| FR-004 | Viewer / Member / Admin + expires_at | D §3.6 project_members | ✅ |
| FR-005 | Project.status (active/dormant/archived) | D §3.4, §1 `ProjectStatus` enum | ✅ |
| FR-006 | Public への Viewer 招待は 422 | C projects.yaml MemberInvite 422 | ✅ |
| FR-007 | Restricted → Public 変更時の Viewer downgrade | C projects.yaml ProjectUpdateRequest description、CS §認証・認可 | ✅ |

### Permission 決定アルゴリズム (FR-008〜FR-015a)

| FR | 要約 | 具体化先 | 状態 |
|---|---|---|---|
| FR-008 | 2 ステージ分離、再帰禁止 | P, D USER_SCOPE_PERMISSIONS、R §18 CI 静的解析 | ✅ |
| FR-008a | Action Pydantic model + ACTIONS カタログ | R §18 CI 静的解析、P `apps/api/echoroo/core/permissions.py` | ✅ |
| FR-008b | SUPERUSER_PROJECT_SCOPE_ALLOWLIST | spec 擬似コードに定義、P で core/permissions.py 責務 | ✅ |
| FR-009 | Permission enum 28 個 | D §1 Permission enum | ✅ |
| FR-010 | ROLE_PERMISSIONS Canonical Matrix | spec §Canonical Matrix、P `core/permissions.py` | ✅ |
| FR-011 | ResponseFilter 必須通過 + CI 静的解析 | R §18 Response Filter 経由検出 | ✅ |
| FR-011a | role/permission キャッシュ TTL 30s + `X-User-Permission-Version` header | R §9、C README §共通レスポンスヘッダ | ✅ |
| FR-012 | TRUSTED_ALLOWED_PERMISSIONS allowlist | spec §Permission 決定アルゴリズム、C trusted.yaml granted_permissions enum | ✅ |
| FR-013 | 許可外は 422 | C trusted.yaml 422 response | ✅ |
| FR-014 | active_trusted_capabilities で runtime 再フィルタ | D §3.8 project_trusted_users、CS authorization | ✅ |
| FR-015 | Trusted 対象は Authenticated のみ | C trusted.yaml 422 ERR_TRUSTED_TARGET_INVALID | ✅ |
| FR-015a | Public 化後の Trusted overlay 扱い | spec Clarifications セッション c | ✅ |

### Visibility 別挙動 (FR-016〜FR-026)

| FR | 要約 | 具体化先 | 状態 |
|---|---|---|---|
| FR-016 | Public Guest の Permission | spec Matrix、C projects.yaml、CS | ✅ |
| FR-017 | Public Authenticated の Permission | 同上 | ✅ |
| FR-017a | Guest は Restricted toggle で DL/EXPORT/VOTE/COMMENT/SEARCH_* 不可 | spec Matrix 脚注、CS | ✅ |
| FR-018 | Public で public_location_precision_h3_res 無視 | R §3、P Response Filter 責務 | ✅ |
| FR-019 | Restricted の必須公開 | C projects.yaml GET /projects | ✅ |
| FR-020 | Restricted bool トグル 6 個 | D §3.4 CHECK 制約、C projects.yaml RestrictedConfig | ✅ |
| FR-021 | public_location_precision_h3_res デフォルト 2 | C projects.yaml RestrictedConfig enum | ✅ |
| FR-022 | allow_precise_location_to_viewer デフォルト false | 同上 | ✅ |
| FR-023 | Pydantic Extra.forbid + JSONB CHECK + version | D §3.4、R §7 | ✅ |
| FR-024 | トグル変更即時、検索 index eventual | R §3、P workers/search_index.py | ✅ |
| FR-025 | SEARCH index 物理除外、3 adapter (SearchGate) | R §3 全面書き換え、P services/search_gate.py | ✅ |
| FR-025a | 2 段階コミット（ON→OFF 即時、index 非同期） | R §3、CP §検索 | ✅ |
| FR-025b | OFF→ON 再構築完了後 | 同上 | ✅ |
| FR-025c | Cache-Control: private, no-store | C README 共通レスポンスヘッダ | ✅ |
| FR-026 | project-level aggregation のみ | C detections.yaml / R §3 | ✅ |

### Location Sensitivity と希少種リスト (FR-027〜FR-036)

| FR | 要約 | 具体化先 | 状態 |
|---|---|---|---|
| FR-027 | H3 離散値 2/5/7/9/15 | D §3.9 / §3.14 CHECK 制約 (IN (2,5,7,9,15))、C projects.yaml enum | ✅ |
| FR-028 | Site h3_index_member 保持、raw lat/lng 非保持 | D §3.10 | ✅ |
| FR-028a | Upload 時 EXIF strip | P api/v1/uploads.py、CS raw lat/lng | ✅ |
| FR-028b | Celery payload schema で lat/lng 禁止 | P workers/ 全般、CS | ✅ |
| FR-028c | access log redaction | P middleware/audit.py | ✅ |
| FR-028d | Site 作成で即破棄 | P services/site.py | ✅ |
| FR-028e | S3 upload lambda | R §12 (P2 infra)、CS | ✅ |
| FR-028f | CI 静的 lint | R §12, §18、CS raw lat/lng | ✅ |
| FR-029 | 公開 hex は動的計算 | P core/permissions.py compute_effective_resolution | ✅ |
| FR-030 | response model に lat/lng 存在しない | C 全 yaml、CS SC-016 | ✅ |
| FR-031 | Site/Recording テーブルに lat/lng カラム存在しない | D §3.10 | ✅ |
| FR-032 | IUCN + MOE RDB グローバルリスト | D §3.14 | ✅ |
| FR-033 | stricter 即時 / looser pending_superuser_approval | D §3.9 | ✅ |
| FR-034 | looser 承認で global 置換 | spec 擬似コード compute_effective_resolution | ✅ |
| FR-035 | HIDDEN 判定 semantics | 同上、D §3.9 CHECK | ✅ |
| FR-036 | IUCN 同期 + fail-safe + sanity check | D §3.15 iucn_sync_attempts、Q § IUCN 同期失敗時 | ✅ |

### 投票・コメント (FR-037〜FR-040)

| FR | 要約 | 具体化先 | 状態 |
|---|---|---|---|
| FR-037 | AnnotationVote.source + project_role_at_vote, immutable | D §3.12、C detections.yaml | ✅ |
| FR-038 | 3 カウント別集計 | C detections.yaml VoteAggregateResponse | ✅ |
| FR-039 | user_id は Owner/Admin のみ | 同上 voters 配列 | ✅ |
| FR-040 | コメントに投稿者バッジ | C detections.yaml / spec US2 | ✅ |

### Trusted User (FR-041〜FR-046)

| FR | 要約 | 具体化先 | 状態 |
|---|---|---|---|
| FR-041 | ProjectTrustedUser エンティティ（pending/token_hash なし） | D §3.8 | ✅ |
| FR-042 | granted_permissions は TRUSTED_ALLOWED_PERMISSIONS サブセット | C trusted.yaml POST granted_permissions enum、D §3.8 | ✅ |
| FR-043 | 期限デフォルト 90 日、上限 granted_at+1年 | D §3.8 CHECK (expires_at BETWEEN granted_at+1s AND granted_at+1yr) | ✅ |
| FR-044 | expires_at で自動 expired、capability は毎リクエスト DB 参照 | spec 擬似コード active_trusted_capabilities、CS Trusted | ✅ |
| FR-045 | 期限 7 日前通知 | P workers/ （notification worker）、Q § 5.3 | ✅ |
| FR-046 | Owner 延長・granted_permissions 変更・revoke 可、上限 1 年 | C trusted.yaml PATCH / DELETE /projects/{id}/trusted-users/{id} | ✅ |

### Invitation (FR-047〜FR-056)

| FR | 要約 | 具体化先 | 状態 |
|---|---|---|---|
| FR-047 | kind 統一、pending/token_hash | D §3.7 | ✅ |
| FR-048 | CHECK 制約（kind × フィールド整合） | D §3.7 | ✅ |
| FR-049 | unique (project_id, email_hash) WHERE pending | 同上 | ✅ |
| FR-050 | 発行権限（member: Owner/Admin、trusted: Owner） | C projects.yaml / trusted.yaml | ✅ |
| FR-051 | token_hash SHA-256 | D §3.7 | ✅ |
| FR-052 | HMAC-SHA256 URL、7 日、one-time | R §14 | ✅ |
| FR-053 | accept 単一 TX + idempotency | C projects.yaml /invitations/{token}/accept | ✅ |
| FR-054 | email 一致検証 | 同上 403 ERR_EMAIL_MISMATCH | ✅ |
| FR-055 | enumeration 対策 | C projects.yaml MemberInvite 202 | ✅ |
| FR-056 | レート（50/h per admin, 200/h per project） | P middleware/rate_limit.py | ✅ |

### 所有権移譲・休眠 (FR-057〜FR-064)

| FR | 要約 | 具体化先 | 状態 |
|---|---|---|---|
| FR-057 | Admin のみ対象 | C projects.yaml /transfer-ownership 400 | ✅ |
| FR-058 | FOR UPDATE + advisory_xact_lock + idempotency | 同上 409 | ✅ |
| FR-059 | 監査記録 | D §3.17 project_audit_log | ✅ |
| FR-060 | dormant 判定式 | P workers/dormancy_check.py | ✅ |
| FR-061 | Owner 削除で自動移譲、不在なら archived | P services/ownership_service.py | ✅ |
| FR-062 | archived state-changing 403、restore は superuser | C admin.yaml /restore | ✅ |
| FR-063 | mutable allowlist | C projects.yaml ProjectUpdateRequest | ✅ |
| FR-064 | Extra.forbid | 同上 | ✅ |

### 2FA (FR-065〜FR-073)

| FR | 要約 | 具体化先 | 状態 |
|---|---|---|---|
| FR-065 | TOTP 2FA 必須、時刻ドリフト ±30 秒 | C auth.yaml /auth/2fa/challenge、R §2 | ✅ |
| FR-066 | TOTP secret は AES-256-GCM + KMS envelope | D §3.1 two_factor_secret_encrypted、R §1、CS 鍵ローテ | ✅ |
| FR-067 | DEK プロセス内キャッシュ TTL + ゼロ化 | CS 鍵ローテ §DEK rewrap、P core/kms.py | ✅ |
| FR-068 | バックアップコード 8 個 / Argon2id / one-time | C auth.yaml TotpSetupResponse、D §3.1 two_factor_backup_codes_hashed、CS 認証 | ✅ |
| FR-069 | 初回ログインで 2FA 設定強制 | C auth.yaml /auth/2fa/setup/totp、Q § 5.1 | ✅ |
| FR-070 | TOTP rate 5/15min、10 連続でロック | C auth.yaml /auth/2fa/challenge 429、CS 認証 | ✅ |
| FR-071 | security_stamp 更新で refresh token 失効 | D §3.1 security_stamp、C auth.yaml /auth/password-reset/confirm | ✅ |
| FR-072 | バックアップコード枯渇は 4 要素 + 24h delay + M-of-N | C admin.yaml /users/{id}/reset-2fa、Q § 2FA リセット | ✅ |
| FR-073 | 2FA reset 72h cooldown | D §3.1 two_factor_reset_cooldown_until、C auth.yaml | ✅ |

### API key (FR-074〜FR-084)

| FR | 要約 | 具体化先 | 状態 |
|---|---|---|---|
| FR-074 | ApiKey スキーマ | D §3.16 | ✅ |
| FR-075 | user 非所属 project 指定は 422 | C projects.yaml? (実装は P api/v1/api_keys.py) | 📋 tasks で ApiKey エンドポイント契約追加 |
| FR-076a〜d | 離脱時自動 revoke + outbox + SLO | D §3.18 outbox、P workers/api_key_revoke.py | ✅ |
| FR-077 | /api/v1/* vs /web-api/v1/* | C README、全 yaml で security + servers 分離 | ✅ |
| FR-078 | 認証失敗エラー | C README error_code 表 | ✅ |
| FR-079 | Role ∩ scope | R §18 CI 静的解析 | ✅ |
| FR-080 | 10 分で 10 件の scope 違反 → 自動 revoke + 通知 + 監査 | D §3.16 scope_violation_count_10min、P workers/api_key_revoke.py | ✅ |
| FR-081 | allowed_ips 違反 3 回で自動 revoke（別カウンタ） | D §3.16 ip_violation_count、P middleware/auth.py | ✅ |
| FR-082 | scope 別レート（read 600/min, vote 60/min, upload 10/min）Redis token bucket | P middleware/rate_limit.py、R §8 | ✅ |
| FR-083 | 90 日 rotation 推奨 | CS API Key | ✅ |
| FR-084 | superuser API key 不可 | spec 擬似コード、C admin.yaml | ✅ |

### ライセンス (FR-085〜FR-087)

| FR | 要約 | 具体化先 | 状態 |
|---|---|---|---|
| FR-085 | 作成時 CC 必須 | C projects.yaml ProjectCreateRequest 422 | ✅ |
| FR-086 | export にメタ同梱 | C detections.yaml /export/csv | ✅ |
| FR-087 | ProjectLicenseHistory 記録 | D §3.5 | ✅ |

### 監査ログ (FR-088〜FR-096)

| FR | 要約 | 具体化先 | 状態 |
|---|---|---|---|
| FR-088 | project_audit_log 閲覧権限 | C audit.yaml /projects/{id}/audit-log | ✅ |
| FR-089 | platform_audit_log superuser のみ | C audit.yaml /admin/audit-log | ✅ |
| FR-090 | カラム定義（raw PII なし） | D §3.17 | ✅ |
| FR-091 | keyed hash 保存 | CS 監査ログ | ✅ |
| FR-091a | JSONB sanitizer + CI lint | R §7、§18、CS | ✅ |
| FR-091b | pii_hash_key KMS 専属 | R §1、CS | ✅ |
| FR-092 | row_hash = HMAC(chain_key, prev || row) | D §3.17 | ✅ |
| FR-093 | SERIALIZABLE + advisory_xact_lock or outbox | D §4.2 | ✅ |
| FR-094 | REVOKE + trigger 二重防御 | D §4.2 | ✅ |
| FR-095 | S3 Object Lock 3 年 | Q § 鍵ローテ | ✅ |
| FR-096 | メタログ | D §3.17 (action 名で自己参照) | ✅ |

### セキュリティ横断 (FR-097〜FR-110)

| FR | 要約 | 具体化先 | 状態 |
|---|---|---|---|
| FR-097 | SameSite=Strict + CSRF | C README、C auth.yaml Set-Cookie | ✅ |
| FR-098 | CSRF token 生成式 | R §14 類似 / CS | ✅ |
| FR-099 | programmatic は Bearer のみ | C README Path 別必須認証 | ✅ |
| FR-100 | Mass assignment 防御 | C 各 yaml additionalProperties: false | ✅ |
| FR-101 | メール RFC 5321/5322、HTML escape、fixed URL | CS メール送信 | ✅ |
| FR-102 | Security headers | C README §共通レスポンスヘッダ | ✅ |
| FR-103 | Password NIST SP 800-63B | CS | ✅ |
| FR-104 | 新デバイス/IP 通知 | CS | ✅ |
| FR-105 | ユーザー削除時匿名化 | D §3.1 deleted_at、CS | ✅ |
| FR-106 | ProjectInvitation.email 30 日 null | D §3.7、CS | ✅ |
| FR-107 | pending expire 明示削除 | D §3.7 | ✅ |
| FR-108 | email_at_invitation 90 日 null | D §3.8 | ✅ |
| FR-109 | DSR endpoint | P `apps/api/echoroo/api/v1/account/dsr.py` 新規 | 📋 tasks |
| FR-110 | upload acknowledge | P api/v1/uploads.py | ✅ |

### Superuser (FR-111〜FR-114)

| FR | 要約 | 具体化先 | 状態 |
|---|---|---|---|
| FR-111 | WebAuthn 2 本 + IP allowlist + 最低 3 名 + M-of-N | D §3.2/§3.3、C admin.yaml、CS Superuser | ✅ |
| FR-111a | count 遷移監査 + 1→0 DB trigger block | D §4.1 | ✅ |
| FR-112 | 初期 superuser CLI + 24h WebAuthn 登録 | Q § 3 初期 superuser | ✅ |
| FR-112a | Response filter は Superuser にも適用 | spec 擬似コード | ✅ |
| FR-113 | 既存データ全削除、Alembic 単一 baseline | P, D §2 Migration Order | ✅ |
| FR-114 | Wipe 3 点一致ガード | D §3.21 wipe_guard、Q § 2 | ✅ |

---

## 非機能要件 (NFR)

| NFR | 要約 | 具体化先 | 状態 |
|---|---|---|---|
| NFR-001 | 認証+権限判定 p95 < 30ms、クエリ <= 4 | CP、D §5 Index 一覧 | ✅ |
| NFR-001a | Recording list bulk preload | CP、D §7、R §13 | ✅ |
| NFR-002 | OWASP Top 10 | CS | ✅ |
| NFR-003 | h3_index_member_resolution デフォルト | D §3.10 | ✅ |
| NFR-004 | list 100 件 p95 < 800ms | CP 負荷試験シナリオ | ✅ |
| NFR-005 | メール Celery リトライ | D §3.18 outbox retry policy と類似方針 | ✅ |
| NFR-006 | SystemSettings | D §3.19 | ✅ |
| NFR-007 | 鍵ローテ SLA | spec § 鍵ローテ SLA、Q § 鍵ローテ | ✅ |
| NFR-008 | request-scope キャッシュ許容 | R §13 | ✅ |
| NFR-008a | long-lived 接続の Trusted 再評価 | P workers/, CS | ✅ |
| NFR-009 | Redis TLS + AUTH + ACL | CS | ✅ |

---

## 開発プロセス (PR)

| PR | 要約 | 具体化先 | 状態 |
|---|---|---|---|
| PR-001 | TDD Red-Green-Refactor | CS / CP | ✅ |
| PR-002 | Canonical Matrix パラメトリック | Q § 6.1 | ✅ |
| PR-003 | E2E は P1 + セキュリティ重要 | Q § 6.3 | ✅ |
| PR-004 | Mutation testing 80% | R §4、Q § 6.2 | ✅ |
| PR-005 | カバレッジ 95/85 | CP | ✅ |
| PR-006 | PR テンプレ Red 証跡 | CS | ✅ |
| PR-007 | セキュリティ 75+ シナリオ | Q § 6.4、CS | ✅ |

---

## 成功基準 (SC)

| SC | 要約 | 具体化先 | 状態 |
|---|---|---|---|
| SC-001 | Permission guard CI 静的解析 | R §18 | ✅ |
| SC-002 | US1 E2E | CS | ✅ |
| SC-003 | Restricted トグル全組合せ | CS / 単体テスト | ✅ |
| SC-004 | Trusted ライフサイクル E2E | CS | ✅ |
| SC-005 | Auto-obscure 3 層 | CS | ✅ |
| SC-006 | 2FA 込みログイン成功率 | CP | ✅ |
| SC-007 | ownership race 1000 並行 | CP 負荷試験 | ✅ |
| SC-008 | 休眠バッチ翌日通知 | P workers/dormancy_check.py テスト | ✅ |
| SC-009 | API key 離脱 60s E2E | CS | ✅ |
| SC-010 | ライセンス必須 | CS | ✅ |
| SC-011 | セキュリティテスト 75+ Green | CS | ✅ |
| SC-012 | Mutation score 80% | CP | ✅ |
| SC-013 | カバレッジ | CP | ✅ |
| SC-014 | Hash chain 並列 INSERT | CP、D §4.2 | ✅ |
| SC-015 | p95 レイテンシ / クエリ | CP | ✅ |
| SC-016 | 生 lat/lng 不在 fuzzer | CS、R §18 | ✅ |
| SC-017 | Viewer 希少種 precise 不可 | CS | ✅ |
| SC-018 | SEARCH leak 3 経路 | CP | ✅ |
| SC-019 | migration lint | R §12, §18 | ✅ |
| SC-020 | AuditLog JSONB sanitizer | R §18 | ✅ |
| SC-021 | outbox fallback | D §3.18 | ✅ |
| SC-022 | superuser count 1→0 block | D §4.1 | ✅ |

---

## 未具体化（解消済み）

- ~~FR-075 ApiKey エンドポイント契約~~ → **T810 (api-keys.yaml 新規作成) + T811 (api/web_v1/account/api_keys.py)** で具体化完了
- ~~FR-109 DSR endpoint 契約~~ → **T900 (api/web_v1/account/dsr.py) + T905 (contracts/account.yaml)** で具体化完了

## FR-076 個別展開（旧 traceability が範囲表記だった件）

| FR | 要約 | 具体化先 T ID |
|---|---|---|
| FR-076 | ApiKey 離脱時の自動 revoke（概念） | T820 workers/api_key_auto_revoke.py |
| FR-076a | ProjectMember DELETE 同一 TX で revoke | T805 SQLAlchemy after_update event hook |
| FR-076b | revoke 確定で `platform_audit_log.action=api_key_auto_revoked_on_member_removal` | T820 + T051 audit_service |
| FR-076c | E2E で 60s 以内 revoke 検証 (SC-009) | T841, T842 |
| FR-076d | outbox SLO (p95 ≤ 10s, p99 ≤ 60s) + fallback `enforce_at_auth_time` | T080, T081, T083

---

## CI での未リンク検出

本 traceability の維持のため、CI で以下を確認:

```bash
# spec の全 FR/NFR/PR/SC ID を抽出
grep -oE "(FR|NFR|PR|SC)-[0-9]+[a-z]?" spec.md | sort -u > /tmp/spec_ids.txt

# traceability の対応表
grep -oE "(FR|NFR|PR|SC)-[0-9]+[a-z]?" requirements-traceability.md | sort -u > /tmp/trace_ids.txt

# 未リンク
comm -23 /tmp/spec_ids.txt /tmp/trace_ids.txt
# 0 行であるべき
```

**実装で未リンク項目は `/speckit.tasks` の最初のタスクとして「traceability の更新」を配置**。

---

**Traceability Status**: ✅ FR-114 / NFR-009 / PR-007 / SC-022 の 全要件をマッピング完了（FR-075 / FR-109 の 2 件のみ tasks で具体化）。
