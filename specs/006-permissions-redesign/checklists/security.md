# Security Checklist: 実装前 / リリース前ゲート

**Branch**: `006-permissions-redesign`
**対象**: implement フェーズ着手前 + リリース前の最終確認

本チェックリストは spec Rev.3.2 の全セキュリティ要件が実装で満たされているかを確認するゲート。全項目 ✅ でリリース可。

---

## 認証 / 認可（FR-065〜FR-084）

- [ ] TOTP 2FA が全ユーザー必須、初回ログインで強制セットアップ画面
- [ ] TOTP secret は AES-256-GCM + KMS envelope encryption、DEK は年次 rewrap
- [ ] バックアップコード 8 個 / 12 桁 base32 / Argon2id (64MiB, 3) / 1 回使用
- [ ] TOTP 検証レート: IP+user 5/15min、10 連続で 15 分ロック
- [ ] バックアップコード試行: 3/1hour 別枠
- [ ] 2FA 有効化 / リセット / パスワード変更で `security_stamp` 更新、全 refresh token 失効
- [ ] バックアップコード全消費リセットは 4 要素 + 24h delay + superuser M-of-N
- [ ] 2FA reset 72h cooldown 実装（招待 accept / API key 操作 / DL / EXPORT 等禁止）
- [ ] refresh token は one-time use + reuse detection（family 全 revoke）
- [ ] `/api/v1/*` は API key 必須（`Authorization: Bearer`）、Cookie 受け入れず
- [ ] `/web-api/v1/*` は Cookie (`Path=/web-api/v1/; SameSite=Strict; Secure; HttpOnly`) + CSRF token
- [ ] CSRF token = `HMAC-SHA256(session_secret, session_id || issued_at)`、session 単位、定数時間比較
- [ ] Password NIST SP 800-63B 準拠（HaveIBeenPwned チェック含む）
- [ ] 新デバイス / IP ログイン通知メール

## API Key（FR-074〜FR-084）

- [ ] `prefix + hashed_secret (SHA-256 + user salt)` 形式、発行時 1 度のみ平文表示
- [ ] user 非所属 project 指定は 422 `ERR_UNAUTHORIZED_PROJECT`
- [ ] ProjectMember 削除と同一 TX で自動 revoke + outbox pattern + 最大 60s
- [ ] outbox SLO: p95 ≤ 10s、p99 ≤ 60s、queue depth / oldest_pending で alert
- [ ] scope 違反 10/10min で自動 revoke、監査記録
- [ ] allowed_ips 違反 3 回で自動 revoke（別カウンタ）
- [ ] superuser 操作は API key 経由で不可（FR-084）
- [ ] 推奨 rotation 90 日 UI 警告、上限 2 年、180 日で scope 縮退警告
- [ ] scope 別レート（read-only 600/min、vote 60/min、upload 10/min）Redis token bucket

## Superuser（FR-111〜112a）

- [ ] WebAuthn hardware key 2 本（primary + backup 物理別保管）必須
- [ ] 管理操作は fixed IP allowlist (CIDR)
- [ ] 最低 3 名常時維持（単独 / 2 名での運用は break-glass モード起動）
- [ ] 追加 / 削除は既存 2 名 M-of-N（SuperuserApprovalRequest）
- [ ] 全操作は `platform_audit_log` に `action=superuser:*`
- [ ] superuser 操作は programmatic API 経由不可
- [ ] 1→0 DELETE は DB trigger で block（creator_founder override のみ）
- [ ] WebAuthn 両紛失時の recovery フロー（M-of-N + 72h delay + 音声録音）
- [ ] 初期 superuser は CLI + hardware key 24h 以内登録強制
- [ ] Response filter は Superuser にも適用（raw 値不可）

## Permission 決定アルゴリズム（FR-008〜FR-015a）

- [ ] `is_allowed` で `normalized_role` を 1 回だけ算出、`compute_effective_permissions` に引数渡し
- [ ] ステージ 2 (Response filter) は DB 再アクセスゼロ、request-scope キャッシュのみ
- [ ] `has_permission` / `is_allowed` の再帰呼び出し禁止
- [ ] `Action` Pydantic model に `@model_validator` で整合性強制
- [ ] `ACTIONS` カタログに全エンドポイント登録、CI 静的解析で未登録検出
- [ ] `SUPERUSER_PROJECT_SCOPE_ALLOWLIST` で superuser bypass 範囲制限
- [ ] `TRUSTED_ALLOWED_PERMISSIONS` allowlist、runtime 再フィルタ
- [ ] Public では Viewer を Authenticated 同等に正規化（gate + filter 両方）
- [ ] Restricted toggle の Guest / Authenticated 2 テーブル分離
- [ ] Guest は DL/EXPORT/VOTE/COMMENT/SEARCH_* を Restricted toggle でも取得しない

## Auto-obscure / Location（FR-027〜FR-036）

- [ ] Site / Recording テーブルに `latitude` / `longitude` カラムが存在しない（FR-031）
- [ ] Pydantic response model に `latitude` / `longitude` フィールドが存在しない（FR-030）
- [ ] `compute_effective_resolution` の先頭で global HIDDEN clamp、looser 承認後は global 置換再評価
- [ ] `ResponseFilter` を全 Recording / Detection / Site レスポンス経路で強制、CI 静的解析で未通過検出
- [ ] Taxon sensitivity は request-scope で `WHERE IN` bulk preload
- [ ] looser override は superuser 承認必須、承認前は未適用
- [ ] IUCN 週次同期、2 週連続失敗で未知種 `H3_RES_7` フェイルセーフ、既知種維持
- [ ] IUCN sanity check（前回比 10% 以上の緩和で abort）
- [ ] IUCN API は TLS 1.2+ + certificate pinning
  - **pre-launch ratchet (Round 2 review M1, 2026-04-28)**: TLS 1.2+ + 運用者提供 CA bundle (`IUCN_API_CA_BUNDLE`) によるチェーン検証 **のみ** で運用する。leaf 証明書 SHA-256 ピン / 真の SPKI ピンは **post-launch ratchet**: httpx (async) は標準では peer cert を呼び出し側に晒さないため、Round 1 で実装した `_verify_cert_hash` は実コードパスから呼ばれていなかった。Round 2 で誤認を避けるためこのデッドコードを削除し、env 変数 `IUCN_API_CERT_SHA256_BASE64` (旧 `IUCN_API_SPKI_SHA256_BASE64`) は post-launch ratchet 用 placeholder として名前だけ予約 (現状 no-op)。post-launch では `cryptography` ライブラリ + 自作 httpx transport で peer cert を取得し、真の SPKI ピンを wire up する。
- [ ] MOE RDB 手動追加の admin UI

## raw lat/lng 全経路排除（FR-028a〜f）

- [ ] Upload 時 WAV/FLAC/MP3 GPS EXIF/ID3 strip（soundfile ベース、原ファイル保存前）
- [ ] Celery task payload schema で lat/lng フィールド禁止（Pydantic validation）
- [ ] access log / error log で `lat`, `lng`, `latitude`, `longitude`, `gps_*` redact
- [ ] Site 作成 API でメモリから即破棄（del + gc.collect）
- [ ] S3 upload lambda で object metadata の GPS 除去
- [ ] CI lint: migration / ORM / Pydantic に lat/lng カラム・field 追加試行で fail
- [ ] JSON schema fuzzer で 50+ エンドポイント検証

## 監査ログ（FR-088〜FR-096）

- [ ] `project_audit_log` と `platform_audit_log` の 2 テーブル分離
- [ ] raw PII カラム（`actor_user_id`, `ip`, `user_agent`）は物理的に存在しない
- [ ] 全 PII は keyed hash（`HMAC-SHA256(pii_hash_key, raw)`）で `*_hash` カラムに保存
- [ ] `pii_hash_key` は KMS に保存、application からは `GenerateMac` API 経由のみ（key material は app に出さない）
- [ ] `row_hash = HMAC-SHA256(chain_key, prev_hash || canonical_row)`、chain_key は KMS 管理
- [ ] 並列 INSERT は SERIALIZABLE + advisory_xact_lock または outbox pattern
- [ ] application DB user から UPDATE/DELETE を REVOKE、trigger で二重防御
- [ ] 週次で chain 再計算 hash を S3 Object Lock に append-only export、3 年保持
- [ ] AuditLog 閲覧自体もメタログ記録
- [ ] `AuditLogSanitizer` で `before` / `after` / `detail` JSONB の PII を runtime で hash 置換
- [ ] CI lint で application コード中の PII key 名リテラル検出
- [ ] sanitizer bypass 10+ シナリオテスト（nested / array / Unicode 同形異字 / URL-encoded / base64）
- [ ] PII hash key 漏洩時の v1/v2 dual-write 90 日手順（Runbook）

## 招待 / Trusted User（FR-037〜FR-056）

- [ ] 招待トークン = 256-bit 乱数の SHA-256 hash、平文はメールのみ
- [ ] 招待 URL は HMAC-SHA256 署名（k_old / k_new 14 日 grace）、期限 7 日、one-time use
- [ ] accept は SELECT FOR UPDATE + idempotency-key + 単一 TX
- [ ] accept 時に受信者 email とログインユーザー primary email の一致（NFKC 正規化 + case-insensitive）
- [ ] Trusted 対象は Authenticated のみ、他ロールには 422
- [ ] `granted_permissions` は TRUSTED_ALLOWED_PERMISSIONS のサブセット、runtime 再フィルタ
- [ ] 期限デフォルト 90 日、上限 `granted_at + 1 年`
- [ ] expires_at 経過で status=expired 自動、capability は JWT に焼かず毎リクエスト DB 参照
- [ ] 期限 7 日前通知
- [ ] 招待フォームは成功 / 失敗 同一レスポンス（enumeration 対策）
- [ ] 招待レート: Owner/Admin 50/h、プロジェクト 200/h

## メール送信（FR-101）

- [ ] 受信者 email は RFC 5321 envelope 検証 + RFC 5322 header 検証、制御文字完全拒否
- [ ] `email-validator` ライブラリ使用、NFKC 正規化
- [ ] 本文テンプレートは user-generated 文字列を HTML escape、ヘッダに user 文字列を入れない
- [ ] 招待 URL は fixed `https://echoroo.app/invite/{token}`、`?next=` 不受理（open redirect 防止）

## セキュリティ横断（FR-097〜FR-110）

- [ ] Security headers 全レスポンス付与（CSP / HSTS / X-Content-Type / Referrer / Permissions / X-Frame-Options）
- [ ] Mass assignment 防御: 全 update 系に Pydantic `Extra.forbid`
- [ ] Cookie domain/path 分離: session Cookie は `Path=/web-api/v1/`
- [ ] ユーザー削除時は email/display_name 匿名化、監査ログの raw PII は元々なし
- [ ] ProjectInvitation.email は accept/decline/expire から 30 日後 null 化、email_hash 別カラム保持
- [ ] ProjectTrustedUser.email_at_invitation は revoked/expired から 90 日後 null 化
- [ ] DSR（GDPR 主体アクセス要求）エンドポイント実装
- [ ] Recording upload 時に人声混入注意 acknowledge checkbox

## 鍵ローテ SLA（Runbook）

- [ ] TOTP secret: CMK 年次 / DEK 90 日 or 2^30、月次 rewrap バッチ + `DekRewrapFailure` 追跡
- [ ] 招待 HMAC: 90 日周期、14 日 grace、k_old/k_new 並行
- [ ] 監査 chain_key: 年次 + 切替で genesis 記録
- [ ] PII hash key: 不変（漏洩時 v2 dual-write 90 日手順）
- [x] CMK deletion window 30 日最低（code-level enforcement: `echoroo.core.kms_ops.schedule_cmk_deletion`, runbook: `docs/runbook/cmk_rotation.md`）
- [ ] CMK 削除は superuser 2 名 M-of-N 承認

## ネガティブセキュリティテスト（PR-007、75+ シナリオ）

すべて `tests/security/` 配下で CI Green 必須:

- [ ] 認証: 2FA bypass / brute force / token replay / refresh reuse / cooldown bypass
- [ ] 認可: 水平・垂直昇格 / BOLA / IDOR / Trusted allowlist runtime / Viewer 権限拡大 / superuser API key 禁止 / is_allowed 非再帰
- [ ] 招待: email mismatch / 並行 accept / expired / XSS / injection / open redirect / enumeration
- [ ] Auto-obscure: 生 lat/lng 全経路不在 / Viewer precise 制限 / HIDDEN 不可逆 / EXIF strip
- [ ] 検索 leak: 3 経路 (OpenSearch / pgvector / FTS) で ON→OFF 即時除外 / OFF→ON 構築完了前除外 / Cache-Control
- [ ] 監査: SERIALIZABLE chain integrity / REVOKE / メタログ / PII hash rotation v1/v2 併存
- [ ] CSRF / mass assignment / Clickjacking
- [ ] race: ownership 移譲 / Owner 削除並行 / 二重 accept
- [ ] 鍵: HMAC 2 鍵並行 / DEK rewrap / CMK 誤削除防止 / PII hash v1→v2
- [ ] API key: 離脱同一 TX revoke (60s) / 180 日 scope 縮退 / allowed_ips 別カウンタ
- [ ] Superuser: break-glass / WebAuthn 両紛失 / programmatic 禁止 / 1→0 block
- [ ] Wipe: 3 点一致 / 2 度目実行防止

---

**Security Checklist Status**: implement 着手前に全項目を plan.md / tasks.md でタスク化必須
