# Performance Checklist: NFR 達成ゲート

**Branch**: `006-permissions-redesign`
**対象**: implement 完了前のパフォーマンス確認

本チェックリストは spec Rev.3.2 の NFR が満たされるかを確認する。CI の benchmark + staging での負荷試験で検証。

---

## NFR-001 認証 + Permission 判定

- [ ] p95 レイテンシ < 30ms（認証 + 権限判定のみ、ビジネスクエリ除く）
- [ ] DB クエリ数 p95 ≤ 4 個（users + project_members + project_trusted_users + api_keys）
- [ ] request-scope キャッシュのみ、プロセス間キャッシュ禁止
- [ ] 測定は k6 or Locust、100 並行リクエスト x 10 分で 10,000 サンプル

## NFR-001a Bulk list

- [ ] Recording list / Detection list (100 件) の権限込み応答で DB クエリ数 p95 ≤ 5 + 1 業務
- [ ] per-row Taxon sensitivity は `WHERE taxon_id IN (...)` の 1 クエリで preload
- [ ] `compute_effective_resolution` は preload dict を引数受取、追加 DB アクセスゼロ
- [ ] Index: `taxon_sensitivities.taxon_id` が USED in EXPLAIN

## NFR-004 API レスポンス

- [ ] `/api/v1/projects/{id}/detections?page_size=100` の p95 < 800ms
- [ ] `/api/v1/projects/{id}/recordings?page_size=100` の p95 < 800ms
- [ ] 測定は staging DB に 100k recording / 1M detection をロードして実施

## NFR-005 メール送信

- [ ] Celery リトライ最大 3 回、指数バックオフ（1s / 4s / 16s）
- [ ] 招待メールは送信失敗時 7 日以内に再送完了保証
- [ ] Resend API レート制限 monitoring（429 alert）

## NFR-006 SystemSettings

- [ ] `SystemSettings` テーブルで期限 / 閾値 / レート値を override 可能
- [ ] 変更は superuser のみ、監査記録、Slack 通知
- [ ] キャッシュ TTL 60s（読み取り側）

## NFR-007 鍵ローテ SLA

- [ ] TOTP DEK rewrap バッチ月次実行、`DekRewrapFailure` ゼロ
- [ ] 招待 HMAC 鍵 90 日周期 Cron、k_old 14 日 grace
- [ ] CMK deletion window 30 日設定済み

## NFR-008 Permission キャッシュ

- [ ] request-scope dict キャッシュ実装（1 リクエスト内の重複 DB 参照回避）
- [ ] プロセス間キャッシュは禁止（Trusted 即時失効保証のため）
- [ ] 検証: revoke 直後のリクエストで 403 を 1s 以内に返す

## NFR-008a Long-lived 接続

- [ ] WebSocket / SSE / streaming で 5 分ごとに `active_trusted_capabilities` / `security_stamp` 再評価
- [ ] Redis pub/sub で Trusted revoke / 2FA reset 通知、接続切断
- [ ] 測定: 接続中に Trusted revoke → 5 分以内に切断確認

## NFR-009 Redis

- [ ] TLS + AUTH + ACL で worker と app を分離
- [ ] Celery event consumer で監査記録
- [ ] Redis token bucket の Lua スクリプト atomic 動作検証

## 検索 (FR-025, SC-018)

- [ ] OFF → ON 切替直後 1s 以内の leak なし（3 経路全て）
  - PostgreSQL FTS: `WHERE allow_detection_view=true` 必須、EXPLAIN で確認
  - pgvector: k*3 fetch + post-filter
  - OpenSearch: 将来追加時の `SearchGate` 抽象経由
- [ ] toggle 変更 → 検索 index 再構築完了まで検索対象除外
- [ ] 検索レスポンスに `Cache-Control: private, no-store`、CDN キャッシュ禁止

## 監査ログ

- [ ] 並列 INSERT 100 件で hash chain 整合性維持（SERIALIZABLE or outbox）
- [ ] chain verification の週次バッチ p95 < 10 分（500k + 5M 行想定）
- [ ] S3 Object Lock の append-only 書き込みが正常

## 2FA / WebAuthn

- [ ] TOTP 検証 p99 < 50ms
- [ ] WebAuthn challenge / response の p99 < 200ms
- [ ] バックアップコード Argon2id 検証 p99 < 500ms（memory=64MiB, iter=3 を考慮）

## Response Filter

- [ ] Response filter 通過後の serialization 追加オーバーヘッド p99 < 20ms
- [ ] bulk (100 件) 処理は CPU バウンド、単一 request thread で処理

## Alembic baseline migration

- [ ] 空 DB から `alembic upgrade head` が 30 秒以内に完走
- [ ] `alembic check` でモデルと schema の diff ゼロ

## 静的解析 CI 時間

- [ ] mypy strict + ruff check の CI 時間 p95 < 3 分
- [ ] mutmut（権限系 4 モジュール）の CI 時間 p95 < 15 分
- [ ] `tests/security/` の 75+ シナリオ実行 p95 < 10 分

---

## 負荷試験シナリオ

implement 完了後の staging で以下を実施:

### シナリオ 1: Guest Public プロジェクト閲覧

- 100 並行 Guest、各 60 秒、`/web-api/v1/projects` list → project detail → recording list → detection list の順
- 目標: p95 < 800ms、エラー率 < 0.1%

### シナリオ 2: Authenticated 投票 + エクスポート

- 50 並行 Authenticated、各 60 秒、ログイン → 2FA → project → detection vote → CSV export
- 目標: p95 < 1200ms（CSV export 含む）、エラー率 < 0.1%

### シナリオ 3: Trusted User capability 失効 race

- Owner が 100 Trusted を revoke、同時に 100 Trusted がアクセス試行
- 目標: revoke 後 1s 以内の全アクセス 403、誤許可ゼロ

### シナリオ 4: Owner 所有権移譲 race

- 2 Admin が同時に移譲試行
- 目標: 片方成功、片方 409 `ERR_CONFLICT`（advisory lock 正常）

### シナリオ 5: 監査ログ並列 INSERT

- 100 並列で permission 変更系 action 発火
- 目標: chain 整合性 100%、応答時間 p95 < 500ms

---

**Performance Checklist Status**: implement 完了後、staging で全項目を CI benchmark + 手動負荷試験で検証
