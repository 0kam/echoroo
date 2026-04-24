# Quickstart: 権限・公開レベル再設計の開発者ガイド

**Branch**: `006-permissions-redesign`
**対象読者**: 実装担当者（backend / frontend / DevOps）

本ドキュメントは spec Rev.3.2 を実装するときに必要なローカル環境セットアップ、初期 superuser 作成、2FA 動作確認、wipe 手順、主要エンドポイントの叩き方をまとめる。詳細な設計は [plan.md](./plan.md) / [research.md](./research.md) / [data-model.md](./data-model.md) / [contracts/](./contracts/) を参照。

---

## 1. ローカル環境起動

### 前提

- Docker + Docker Compose
- リポジトリ clone 済み
- `.env` を `.env.example` から作成し、KMS 系変数を dev 値で埋める（LocalStack KMS 使用）

### 追加の dev 環境変数（本リデザインで新規）

```bash
# KMS（LocalStack）
AWS_KMS_ENDPOINT=http://localstack:4566
AWS_KMS_REGION=us-east-1
AWS_KMS_CMK_2FA_ALIAS=alias/echoroo-2fa-dev
AWS_KMS_CMK_PII_HASH_ALIAS=alias/echoroo-pii-hash-dev
AWS_KMS_CMK_AUDIT_CHAIN_ALIAS=alias/echoroo-audit-chain-dev
AWS_KMS_CMK_INVITATION_HMAC_ALIAS=alias/echoroo-invitation-hmac-dev

# E2E 用 TOTP（テストのみ）
TEST_TOTP_SECRET_BASE32=JBSWY3DPEHPK3PXP
TEST_MODE=true

# Superuser 初期化（wipe 直後のみ有効）
ECHOROO_INITIAL_SUPERUSER_EMAIL=admin1@echoroo.app
```

### サービス起動

```bash
./scripts/docker.sh dev
# db / redis / localstack / backend / worker / worker-cpu / frontend が立ち上がる
```

ログ確認:

```bash
docker logs echoroo-backend --tail 100
docker logs echoroo-frontend --tail 100
docker logs echoroo-worker-1 --tail 100
```

---

## 2. 初期 wipe（リリース前 1 回のみ）

**⚠️ 警告**: この手順はリリース前 1 回のみ実行。S3 の `recordings/` prefix は lifecycle で 7 日後削除、その間は versioning で復元可能（Runbook 参照）

```bash
# 1. wipe_guard 状態確認
docker exec echoroo-backend uv run python -m echoroo.scripts.check_wipe_guard

# 2. superuser 2 名 + 創業者承認を確認（spec FR-114）
# DB に wipe_executed_at row がなく、S3 Object Lock genesis marker が未作成なら OK

# 3. wipe 実行（interactive 確認あり）
docker exec -it echoroo-backend uv run python -m echoroo.scripts.wipe_database
```

wipe 後に baseline migration が自動実行され、空の DB schema が完成する。

---

## 3. 初期 superuser 作成（wipe 直後）

```bash
docker exec -it echoroo-backend uv run python -m echoroo.scripts.init_superuser \
    --email admin1@echoroo.app \
    --display-name "Admin 1"
```

手順:

1. CLI が TOTP secret を生成、QR コード URL を表示
2. iOS / Android の Authenticator アプリで QR スキャン
3. CLI が 6 桁 TOTP コード入力を求める
4. 確認成功で superuser レコード INSERT、一時パスワードがメールで発行
5. 24h 以内に Web UI (`/admin/2fa/webauthn/register`) で WebAuthn hardware key 2 本登録必須（未登録なら自動 revoke）

同様に 3 名目まで作成（FR-111 `最低 3 名` 維持）:

```bash
docker exec -it echoroo-backend uv run python -m echoroo.scripts.init_superuser --email admin2@echoroo.app
docker exec -it echoroo-backend uv run python -m echoroo.scripts.init_superuser --email admin3@echoroo.app
```

初期 IUCN + 環境省 RDB 同期:

```bash
docker exec echoroo-backend uv run python -m echoroo.scripts.initial_iucn_sync
docker exec echoroo-backend uv run python -m echoroo.scripts.seed_moe_rdb
```

---

## 4. 開発中によく使うコマンド

### Backend

```bash
cd apps/api
uv run uvicorn echoroo.main:app --reload     # dev server
uv run pytest                                 # 全テスト
uv run pytest tests/security/                 # セキュリティネガティブ 75+
uv run pytest tests/unit/permissions/         # Canonical Matrix パラメトリック
uv run mypy .                                 # 型チェック
uv run ruff check .                           # lint
uv run mutmut run --paths-to-mutate echoroo/core/permissions.py  # mutation testing
```

### Frontend

```bash
cd apps/web
npm run dev          # dev server
npm run build
npm run check        # type check
npm run lint
npm run test:e2e     # Playwright、TEST_MODE=true で TOTP 自動生成
```

### Alembic migration

```bash
cd apps/api
uv run alembic upgrade head      # baseline 適用
uv run alembic check             # ORM と DB schema の diff 検証
# 注意: 新規 migration の autogenerate は spec 完成後の追加フィーチャー用。baseline 段階では使わない
```

---

## 5. 主要フローの動作確認

### 5.1 新規ユーザー登録 + 2FA セットアップ

```bash
# 1. register
curl -X POST http://localhost:8002/web-api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"alice@example.com","password":"Str0ngP@ss!2026","display_name":"Alice","accept_terms":true}'

# 2. login → challenge_token を得る
curl -X POST http://localhost:8002/web-api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"alice@example.com","password":"Str0ngP@ss!2026"}'

# 3. 初回は 2FA 未設定 → /auth/2fa/setup/totp で QR 取得
# 4. Authenticator で読み込み → /auth/2fa/setup/totp/confirm で 6 桁 code
# 5. その後のログインは /auth/2fa/challenge で totp_code
```

### 5.2 Public プロジェクト作成 + Guest 閲覧

```bash
# Owner がプロジェクト作成（CC-BY 必須）
curl -X POST http://localhost:8002/web-api/v1/projects \
  -H "Cookie: session_id=xxx" \
  -H "X-CSRF-Token: yyy" \
  -H "Content-Type: application/json" \
  -d '{"name":"Tokyo Bird Soundscape","visibility":"public","license":"CC-BY"}'

# Guest（未ログイン）がプロジェクト閲覧
curl http://localhost:8002/web-api/v1/projects/{id}
# レスポンスに h3_index は含まれるが latitude / longitude は含まれない
```

### 5.3 Restricted プロジェクトで Trusted User 招待

```bash
# Owner のみ発行可能（MANAGE_TRUSTED）
curl -X POST http://localhost:8002/web-api/v1/projects/{id}/trusted-users \
  -H "Cookie: session_id=xxx" \
  -H "X-CSRF-Token: yyy" \
  -d '{"email":"researcher@example.com","granted_permissions":["view_media","view_detection","download"],"duration_seconds":7776000}'
# → ProjectInvitation(kind=trusted) 作成、招待メール送信
```

### 5.4 API key 発行 + programmatic アクセス

```bash
# ユーザーが API key 発行（read-only scope）
curl -X POST http://localhost:8002/web-api/v1/account/api-keys \
  -H "Cookie: session_id=xxx" \
  -d '{"granted_permissions":["view_media","view_detection","search_within_project"],"expires_at":"2027-04-24T00:00:00Z"}'
# → prefix + secret が一度だけ表示

# programmatic API で使用
curl http://localhost:8002/api/v1/projects \
  -H "Authorization: Bearer ek_live_abc12345_XXXXXXXXXX"
```

### 5.5 監査ログ確認

```bash
# Owner / Admin が project audit log 閲覧
curl http://localhost:8002/web-api/v1/projects/{id}/audit-log \
  -H "Cookie: session_id=xxx"

# superuser が platform audit log 閲覧
curl http://localhost:8002/web-api/v1/admin/audit-log \
  -H "Cookie: session_id=superuser-xxx"
```

---

## 6. テスト実行

### 6.1 Canonical Matrix パラメトリックテスト

権限系の unit test は `pytest` で Canonical Matrix 全組合せを網羅:

```python
# apps/api/tests/unit/core/test_permissions_matrix.py
@pytest.mark.parametrize("role", [Role.GUEST, Role.AUTHENTICATED, Role.VIEWER, Role.MEMBER, Role.ADMIN, Role.OWNER])
@pytest.mark.parametrize("visibility", [Visibility.PUBLIC, Visibility.RESTRICTED])
@pytest.mark.parametrize("permission", [Permission.VIEW_MEDIA, Permission.VOTE, Permission.MANAGE_MEMBERS, ...])
def test_canonical_matrix(role, visibility, permission):
    ...
```

### 6.2 Mutation testing

```bash
cd apps/api
uv run mutmut run --paths-to-mutate echoroo/core/permissions.py
uv run mutmut results  # mutation score 表示、80% 以上必須
```

### 6.3 E2E（Playwright with TOTP）

```bash
cd apps/web
npm run test:e2e -- tests/e2e/p1-flows/
# TOTP コードは test-helpers/totp.ts の generateTOTP(TEST_TOTP_SECRET_BASE32) で自動生成
```

### 6.4 ネガティブセキュリティテスト

```bash
cd apps/api
uv run pytest tests/security/ -v
# 認可 / 認証 / 招待 / 検索 leak / 監査 / CSRF / race / 鍵 / API key / Superuser の 75+ シナリオ
```

---

## 7. トラブルシューティング

### Q. Alembic upgrade head が失敗する

A. 既存 DB が古い schema の場合は wipe 手順を先に実行。baseline migration は空 DB を前提とする

### Q. LocalStack KMS alias が見つからない

A. `scripts/init-localstack.sh` で alias を初期化している。再起動:

```bash
docker exec echoroo-localstack-1 awslocal kms list-aliases
```

### Q. 2FA が TOTP 画面で弾かれる（時刻ドリフト）

A. ホスト時計とコンテナ時計を同期（±30 秒許容、FR-065）

### Q. Celery task が実行されない

A. worker-cpu キューで実行されているか確認:

```bash
docker logs echoroo-worker-cpu --tail 100
```

CLAUDE.md にあるように分類・サンプリング・権限系の新しい Celery task は worker-cpu キューに集約。

### Q. superuser が 1 名に減って追加できない

A. break-glass モードを起動（FR-111 / Runbook）:

```bash
curl -X POST http://localhost:8002/web-api/v1/admin/break-glass/activate \
  -H "Cookie: session_id=remaining-superuser-xxx" \
  -H "X-Founder-Channel-Token: YYY"  # 創業者チャンネルから取得
```

72h 以内に新規 superuser 追加必須。

---

## 8. リリース前チェックリスト

[checklists/security.md](./checklists/security.md) と [checklists/performance.md](./checklists/performance.md) に従い、以下を順に確認:

- [ ] Alembic baseline migration が空 DB から完走
- [ ] Constitution Check PASS（plan.md 参照）
- [ ] 権限系 mutation score 80% 以上
- [ ] カバレッジ 権限系 95% / その他 85%
- [ ] `tests/security/` 75+ シナリオ Green
- [ ] Canonical Matrix パラメトリック全組合せ Green
- [ ] P1 E2E（US1/US2/US3/US4/US8/US10/US11）Green
- [ ] 初期 superuser 3 名、各 WebAuthn 2 本登録済み
- [ ] IUCN + 環境省 RDB 初回同期完了
- [ ] wipe_guard 3 点一致（DB + alembic + S3 Object Lock）
- [ ] KMS CMK 4 つ（2FA / PII hash / audit chain / invitation HMAC）作成済み、deletion window 30 日
- [ ] CI に lat/lng regression guard（pre-commit hook + grep lint）設定済み

---

**Quickstart Status**: ✅ 完了、Phase 1 成果物の一部として plan フェーズ終了
