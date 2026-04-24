# Research: 権限・公開レベル再設計の技術的決定

**Branch**: `006-permissions-redesign`
**Date**: 2026-04-24
**Input**: [plan.md](./plan.md) Phase 0 で洗い出した技術的決定項目

本ドキュメントは `/speckit.plan` の Phase 0 成果物として、spec.md Rev.3.2 を実装するにあたり **plan 段階で確定すべき技術的決定** を記録する。各項目は「Decision / Rationale / Alternatives / Chosen Because」の 4 要素で整理する。

---

## 1. KMS プロバイダ

**Decision**: **AWS KMS**（envelope encryption + `GenerateMac` API）

**Rationale**:
- spec FR-051（TOTP secret の AES-256-GCM + KMS envelope encryption）、FR-091b（PII hash key を `GenerateMac` 専属）を満たすため、KMS サービスが必須
- Echoroo は既に boto3 経由で S3 (LocalStack) を利用、AWS SDK は導入済み
- `kms:GenerateDataKey` で DEK 発行、`kms:GenerateMac` で keyed HMAC を計算 — 両方を 1 サービスでカバー
- CMK のローテーション（年次自動）・deletion window 30 日最低（FR-114 wipe guard）など、コンプライアンス機能が built-in

**Alternatives**:
- **HashiCorp Vault**: self-hosted の柔軟性は高いが、Vault 自体の可用性管理が必要。プレローンチ段階でのオーバーヘッドが大きい
- **自前 envelope encryption**（KMS なし）: 鍵管理の責務を全てアプリ側で負う。CMK ローテーション・監査ログ取得・IAM 連携を自前で実装すると工数と脆弱性リスクが大きい

**Chosen Because**: 既存 boto3 の流用、envelope + GenerateMac の統合サポート、deletion window / ローテの自動化、プレローンチ段階での最短導入。dev 環境では LocalStack の KMS emulation（コミュニティ版）で代替可能（ただし production-grade 検証は staging で AWS KMS 実体を使う）。

---

## 2. WebAuthn ライブラリ

**Decision**: **Backend: `py_webauthn` (duo-labs/py_webauthn)** / **Frontend: `@simplewebauthn/browser`**

**Rationale**:
- spec FR-111(a) で superuser に WebAuthn hardware key 2 本を必須化、RFC 9052 / WebAuthn Level 3 準拠が必要
- `py_webauthn` は Python 3.11 対応、登録 / 認証 / attestation 検証が揃っており、FIDO Alliance の test suite を通過している
- フロント `@simplewebauthn/browser` は軽量（~10KB gzip）で SvelteKit に統合しやすい。`@simplewebauthn/server` を backend にする選択肢もあるが Python 実装を優先

**Alternatives**:
- **`fido2` (Yubico)**: 機能は豊富だが CTAP 寄りの低レベル API が中心で、WebAuthn フルスタックの抽象が薄い
- **DUO サービス**: Managed 2FA だが superuser のみのため外部依存を抱えるコストが割に合わない

**Chosen Because**: WebAuthn 抽象が高レベルで実装工数が最小、ドキュメント充実、型ヒント完備。hardware key は YubiKey 5 系を primary、SoloKey を backup として想定。

---

## 3. 検索エンジン戦略

**Decision**: **`SearchGate` を 3 adapter contract（FTS / pgvector / OpenSearch）として抽象化**。本リリースでは FTS と pgvector の 2 adapter を実装、OpenSearch adapter は **`NotImplementedError` を raise する stub** として用意し、3 経路すべてで同一 contract test（Permission gate / leak 検証）を実行する。

**Rationale**:
- 現行 Echoroo は pgvector（embedding 類似検索）+ PostgreSQL FTS（種名・tag 名検索）の 2 経路。OpenSearch は未導入（Explore 調査で確認）
- spec FR-025 / FR-025a は「3 経路すべてで Permission gate を即時除外」を要求。契約としては 3 adapter、実体は 2 adapter で進める設計が spec・research・checklist 間のドリフトを解消する
- プレローンチ段階で OpenSearch を導入するとクラスタ運用コストが非線形に増える（最小 3 ノード、メモリ管理、snapshot 管理）
- 抽象クラス `SearchGate` の契約は以下:
  ```python
  class SearchGate(Protocol):
      def search(self, query: SearchQuery, effective_project_ids: frozenset[UUID]) -> SearchResult:
          """全 adapter 共通。effective_project_ids は allow_detection_view=ON のみを含む"""
  
  class FtsSearchAdapter(SearchGate):       # 実装済み
  class PgvectorSearchAdapter(SearchGate):   # 実装済み (k*3 fetch + post-filter)
  class OpenSearchAdapter(SearchGate):
      def search(self, query, effective_project_ids):
          raise NotImplementedError("OpenSearch adapter is a stub; scheduled for v1.1")
  ```
- FTS: SQL の `WHERE projects.allow_detection_view=true` で直接フィルタ
- pgvector: ANN 検索は post-filter になるため `k*3 fetch + effective_project_ids 交差 + k 件返却` で approximate 欠損を吸収
- OpenSearch stub: contract test は `pytest.raises(NotImplementedError)` で通す（実体テストは v1.1 で有効化）
- CI 静的解析: `apps/api/echoroo/api/**/*.py` 内で `select(Detection)` 系を直接使っているコードを検出、`SearchGate` 経由でないものを fail

**Alternatives**:
- **OpenSearch 初期実装まで含める**: 検索速度と機能性（fuzzy match、集計、多言語解析）は優位だが、運用コストが大きく、本リリーススコープ超え
- **Meilisearch**: 軽量で速いが、日本語 tokenizer が未成熟、長期運用での実績に不安
- **`SearchGate` 抽象化なしで 2 adapter 直接**: spec FR-025 の「3 経路」表記とドリフト、checklist / contract test が不整合になる

**Chosen Because**: 初期の scale（1k users / 500 projects / 100k recording / 10M detection 想定）では pgvector + FTS で十分 p95 を満たせる。SearchGate の 3 adapter contract で spec との整合を保ち、OpenSearch 追加時は stub を実装に差し替えるのみで済む。

---

## 4. Mutation Testing Tool

**Decision**: **mutmut**（Python）。Frontend の mutation testing は本リデザインスコープ外（権限系モジュールは backend のみ）

**Rationale**:
- spec PR-004 で権限系モジュールに mutation score 80% 以上を要求
- mutmut は Python の標準的な mutation testing ツール、pytest と統合しやすく、`--paths-to-mutate apps/api/echoroo/core/permissions.py` のような限定適用が可能
- CI では cache（`.mutmut-cache`）で差分だけ再評価、実行時間を短縮

**Alternatives**:
- **Cosmic Ray**: 分散実行に強いが、設定が複雑で pytest 統合が弱い
- **MutPy**: メンテナンスが停滞

**Chosen Because**: 業界標準、pytest 統合、CI で差分実行、学習コスト最小。初期は `core/permissions.py` / `core/audit.py` / `core/auth.py` / `services/permissions.py` の 4 モジュールに集中適用し、mutation score 80% 以上を CI gate として enforce する。

---

## 5. Background Job Scheduler

**Decision**: **Celery Beat**（既存）

**Rationale**:
- Echoroo は既に Celery + Redis ブローカーで ML タスクを処理中（Explore 調査で `workers/celery_app.py` と 12 個の worker ファイル確認）
- spec の定期タスク（IUCN 週次同期 / DEK rewrap 月次 / dormancy 日次 / 搜索 index 再構築 / API key 離脱 revoke outbox）は Celery Beat の schedule で十分表現可能
- 新規依存を増やさないことで運用負荷を最小化

**Alternatives**:
- **APScheduler + Redis**: Distributed-safe な alternative だが、Celery との機能重複で価値が薄い
- **AWS EventBridge**: managed SLA は魅力だが、AWS lock-in が強く、LocalStack dev 環境で emulate できない

**Chosen Because**: 既存インフラ流用、追加依存なし、worker-cpu / worker-gpu 分離とスケジューラを統合運用。GPU 不要なスケジュールジョブは `worker-cpu` キューに載せる。

---

## 6. Audit Log Outbox Pattern

**Decision**: **自前実装**（PostgreSQL テーブル `outbox_events` + Celery worker）

**Rationale**:
- spec FR-076a（ApiKey 離脱時同一 TX revoke）と FR-093（監査ログ並列 INSERT の chain 整合性）の両方で outbox pattern を使用
- 既存 Celery + PostgreSQL を活かし、`outbox_events` テーブル + `status` カラムで at-least-once 配信、separate worker がポーリングで処理
- 外部ライブラリ（`transactional-outbox`、`saga-py`）は、Echoroo のシンプルな要件に対してオーバースペック

**Alternatives**:
- **`transactional-outbox` Python lib**: 機能豊富だが依存追加のコストが見合わない
- **Debezium + Kafka**: イベントソーシング系のフル機能、プレローンチには過剰

**Chosen Because**: 実装は `~200 行` の SQLAlchemy + Celery で完結。schema は `{id, event_type, payload JSONB, status, retry_count, created_at, processed_at, last_error}` のシンプル構造。SLO は spec FR-076d で p95 ≤ 10s、p99 ≤ 60s。

---

## 7. JSONB Pydantic Sanitizer

**Decision**: **独自実装 `AuditLogSanitizer`（Pydantic v2 `model_validator` + カスタム deep-walker）**

**Rationale**:
- spec FR-091a で監査ログ JSONB (`before` / `after` / `detail`) の PII を保存時に自動 hash 置換
- 既存の Pydantic `field_validator` は浅い型検証で、nested dict / array の再帰的な PII key regex match には対応しない
- Unicode 同形異字（`＠` / `@`）、URL-encoded（`%40`）、base64 埋め込みなど、ペイロード偽装パターンまでカバーする必要あり（security レビュー H-2 指摘）

**Alternatives**:
- **Python `presidio` (Microsoft)**: NLP ベースで強力だが、依存が重く（~200MB）、false positive 率が高い
- **regex ベース単純置換**: nested dict / array を歩けない、Unicode 同形異字に弱い

**Chosen Because**: 実装は `~150 行`、unit test で 10+ bypass シナリオ（nested dict、array、Unicode 同形異字、URL-encoded、base64、null byte、制御文字）を網羅。`PII_KEY_REGEX` は `r"(?i)(email|ip|user_agent|phone|lat|lng|gps|address|display_name)"` を start point に、実装時に拡張。

---

## 8. Rate Limit Backend

**Decision**: **`fastapi-limiter` + Redis Lua スクリプト**（token bucket）

**Rationale**:
- Echoroo は既に `fastapi-limiter` を依存に持つ（Explore 調査で確認）
- spec の複数のレート制限（FR-054 TOTP、FR-056 招待、FR-082 API key scope 別）を統一的に Redis token bucket で実装
- Lua スクリプトで atomic な refill + consume を実現、分散環境でも正確性を保つ

**Alternatives**:
- **`slowapi`**: FastAPI との統合は良いが、Redis Lua の柔軟性に劣る
- **Envoy / Istio rate limit**: infra 層での制御だが、アプリケーションコンテキスト（scope、user_id）を参照できない

**Chosen Because**: 既存依存、分散 Redis 対応、scope × user × IP の多次元 key をサポート可能。TTL は IP+user 5/15min では `300s sliding window`、API key scope 別は `60s fixed bucket`。

---

## 9. Frontend Role/Permission Cache Invalidation

**Decision**: **`x-user-permission-version` response header + TanStack Query invalidation**

**Rationale**:
- spec FR-011a で「フロント側 role / permission キャッシュは TTL ≤ 30 秒、visibility 変更・role 変更を検知したら即破棄」を要求
- WebSocket / SSE は本リデザインでは導入しない方針（spec Non-goals）のため、pull 型 invalidation が必要
- 全 mutation response に `x-user-permission-version: <sha256-of-effective-permissions>` ヘッダを付与し、クライアントはバージョン変化で `queryClient.invalidateQueries(['permissions'])` を発火

**Alternatives**:
- **Long-polling**: サーバー側リソース消費が大きい
- **Service Worker sync event**: 対応ブラウザが限定

**Chosen Because**: pure HTTP 完結、既存 TanStack Query キャッシュと親和性高、永続接続不要。version は `HMAC-SHA256(session_secret, effective_permissions_json || security_stamp)` の先頭 16 hex で生成（実装は `middleware/response.py`）。

---

## 10. H3 → 地図描画（Frontend）

**Decision**: **`h3-js` 直接使用 + MapLibre GL（既存）**

**Rationale**:
- Echoroo は `h3-js ^4.1.0` と `maplibre-gl ^5.19.0` を既に利用（Explore 調査で確認）
- spec FR-028 で「生 lat/lng を DB / API に持たない」方針のため、フロントでは `h3_index` → `cellToLatLng(index)` で中心点を取得、精度が粗い場合（`H3_RES_5` 以下）は `cellToBoundary(index)` で polygon 描画
- `@turf/h3-js` は h3-js の wrapper で、turf の geojson 変換が便利だが、Echoroo はシンプルな hex 描画で十分

**Alternatives**:
- **`@turf/h3-js`**: geojson 統合は便利だが依存が重い（~500KB gzip 増加）
- **自前の WebGL shader**: 高速だが実装工数大

**Chosen Because**: 既存依存、`h3-js` の `cellToLatLng` / `cellToBoundary` / `polygonToCells` で十分。`h3_index` の resolution に応じて marker / polygon を切替する UI ロジックは `HSpecYMaps.svelte` に集約。

---

## 11. Playwright E2E での 2FA 対応

**Decision**: **固定 TOTP secret + 自動 TOTP 生成**（E2E テスト専用、`TEST_MODE=true` で有効化）

**Rationale**:
- spec PR-003 で E2E は Playwright、テストで 2FA が required なため bypass メカニズムが必要
- 完全 bypass（`TEST_MODE` で 2FA 画面をスキップ）は 2FA flow 自体のテストができなくなる
- 固定 secret `TEST_TOTP_SECRET_BASE32`（環境変数） + Playwright helper で TOTP コードを `pyotp` 互換アルゴリズムで生成し、実際の 6 桁を入力する方式

**Alternatives**:
- **TOTP 画面 bypass**: 2FA flow 自体の E2E が書けない
- **メール / SMS OTP**: インフラが複雑

**Chosen Because**: 2FA flow を完全にテストできつつ、Playwright が TOTP 画面を埋める際の決定性を保てる。`apps/web/tests/e2e/helpers/totp.ts` に `generateTOTP(secret: string): string` ヘルパーを実装、`libs/TOTP` の JS 互換実装を利用。

---

## 12. raw lat/lng Regression Guard (CI lint)

**Decision**: **pre-commit hook + CI grep-based lint**（ruff custom plugin は作らない）

**Rationale**:
- spec FR-028f で migration / ORM / Pydantic に `latitude` / `longitude` / `lat` / `lng` / `gps_*` を含むカラム・field 追加を CI で fail
- ruff custom plugin の開発は ~20 時間の工数、本スコープに見合わない
- pre-commit hook で `grep -rE "(latitude|longitude|lat|lng|gps_)" alembic/versions/` + `grep` Python ファイル内の `Column(` や Pydantic `Field(` を検出できる

**Alternatives**:
- **ruff custom plugin**: 開発工数大、本件限定のため ROI 低
- **SQLAlchemy ORM インスペクション (runtime)**: runtime 検査のみで design time catch できない

**Chosen Because**: 実装 `~50 行` の shell script + pre-commit.yml + GitHub Actions workflow、allowlist 可能（`h3_index_*` のみ許可、他は fail）。false positive は PR コメントで人間判断。将来的に ruff plugin 化は retrospective で再検討。

---

## 13. Location Sensitivity Preload Cache 戦略

**Decision**: **Request-scope dict preload**（spec NFR-001a 準拠）+ Redis fallback なし

**Rationale**:
- spec NFR-001a で「N 行の Taxon sensitivity は `WHERE taxon_id IN (...)` の 1 クエリ preload、合計 p95 ≤ 5 クエリ」を要求
- Recording list / Detection list のエンドポイントで、list 取得クエリ直後に `taxon_id` の set を集めて `SELECT * FROM taxon_sensitivity WHERE taxon_id IN (...)` を 1 回実行、`dict[taxon_id, sensitivity_h3_res]` を `compute_effective_resolution` に引数渡し
- Redis での cross-request キャッシュは「sensitivity 変更の即時反映」と「キャッシュ invalidation の複雑さ」のトレードオフで、初期実装では採用しない

**Alternatives**:
- **Redis cache with TTL 1h**: cross-request 共有で DB 負荷は軽減するが、IUCN 週次同期後の反映遅延が問題
- **in-memory LRU (app process)**: multi-process deployment で同期困難

**Chosen Because**: シンプル、反映即時、IN query は 100 件程度なら十分高速（<5ms）。Redis cache は post-launch で p95 が悪化した場合に追加検討する（NFR-006 で `SystemSettings` 経由で切替可能な設計にしておく）。

---

## 14. 招待トークンの HMAC 署名鍵管理

**Decision**: **KMS envelope + 2 鍵並行方式**（FR-040 + 鍵ローテ SLA）

**Rationale**:
- spec の鍵ローテ SLA 表で「招待 HMAC は 90 日周期、14 日 grace で k_old / k_new 両方 verify、新規署名は k_new のみ」
- 実装は `invitation_hmac_keys` テーブル（または環境変数配列）に `active` と `previous` を持ち、KMS `GenerateMac` 経由で署名生成、検証は両鍵を順に試行

**Alternatives**:
- **単一 HMAC 鍵**: 漏洩時に過去全招待リンクが偽造可能、90 日周期のローテが必須
- **JWT 署名**: 冗長（payload に project_id / email が入るのは不要、opaque token で十分）

**Chosen Because**: spec の SLA を忠実に実装、KMS `GenerateMac` API で鍵を app process memory に露出しない（security M-2）。14 日 grace 後、k_old はカレンダー登録で superuser 2 名 M-of-N 承認の下に削除。

---

## 15. monorepo 運用と Alembic baseline

**Decision**: **既存 Alembic（24 migration）を全消去、単一 baseline `0001_initial_permissions_redesign.py` で再構築**（spec FR-113）

**Rationale**:
- spec FR-113 で「既存データ全削除、Alembic 単一ベースライン migration」を指定
- 既存 24 migration は incremental 変更の歴史で、本リデザインでは無意味（プレローンチで既存 DB を wipe するため）
- 単一 baseline は DB 設計が spec.md の data-model.md と 1:1 対応し、レビュー容易性が高い

**Alternatives**:
- **既存 migration を維持 + 追加 migration**: 24 個に上乗せすると ORM モデルとの対応が複雑化
- **複数 baseline（機能単位）**: alembic の思想とズレる

**Chosen Because**: プレローンチの特権として全消去、単一 baseline で clean start。`wipe_guard` 3 点一致（DB table + alembic revision + S3 Object Lock genesis marker）で 2 度目実行を防止。

---

## 16. Python依存追加リスト

**新規追加が必要な Python 依存**:

| Package | Version | 用途 |
|---|---|---|
| `pyotp` | ≥2.9.0 | TOTP 実装（RFC 6238 準拠） |
| `webauthn` (`py_webauthn`) | ≥2.5.0 | superuser WebAuthn hardware key |
| `cryptography` | ≥44.0 | AES-256-GCM DEK 暗号化、HMAC-SHA256 計算 |
| `mutmut` | ≥3.2 | 権限系 mutation testing（dev 依存） |
| `testcontainers[postgres,redis]` | ≥4.9 | integration test 用 DB / Redis 起動（dev 依存） |

**新規追加が必要な Frontend 依存**:

| Package | Version | 用途 |
|---|---|---|
| `@simplewebauthn/browser` | ^13.0 | WebAuthn クライアント API |
| `openapi-typescript` | ^7.4 | OpenAPI から TypeScript 型自動生成（dev 依存） |

すべてプレローンチ段階で追加するため、既存データや動作への影響なし。

---

## 18. Permission / ResponseFilter / SearchGate 経由検出の CI 静的解析

**Decision**: **AST ベース静的解析**（`libcst` or `ast` モジュール）+ pytest リフレクションテストのハイブリッドで、`is_allowed` 未通過 / `ResponseFilter` 未通過 / `SearchGate` 未通過エンドポイントを CI で検出

**Rationale**:
- spec FR-008 の「全 state-changing / data-read エンドポイントは Permission guard を通過」、FR-011 の「ResponseFilter は全 Recording/Detection/Site レスポンス経路で通過必須」、FR-025 の「全検索経路で SearchGate 強制」を **構造的に保証する仕組み** が plan で謳われているが実装方針が未記述だった
- 3 つの安全網が揃って初めて「実装段階で忘れたエンドポイントを CI が検出する」保証が成立する
- AST + リフレクション両方を使うことで、静的な import/呼び出し検出と、runtime での ACTIONS カタログ対応検証を二重防御化

### 3 種類の CI lint 実装

**A. Permission guard 経由検出（`is_allowed` / `Depends(check_action(...))`）**
```python
# scripts/lint_permission_guard.py
import libcst as cst
# apps/api/echoroo/api/**/*.py の各 @router.get/post/... デコレータ付き関数を走査
# 関数 body に is_allowed(...) / Depends(check_action(...)) の呼び出しが >= 1 個あること
# なければ fail
```
- CI step: `python scripts/lint_permission_guard.py apps/api/echoroo/api/`
- allowlist: `auth.py` の register / login / password-reset 系（認証前のため Permission guard 対象外）

**B. ResponseFilter 経由検出**
```python
# scripts/lint_response_filter.py
# Recording / Detection / Site の response_model を返すエンドポイントで
# apply_response_filter(...) または @with_response_filter デコレータが経由されているか
```
- CI step: `python scripts/lint_response_filter.py`
- 検出方法: response_model Pydantic class を持つ path operation 関数で、return 直前に filter 呼び出しがあるか

**C. SearchGate 経由検出**
```python
# scripts/lint_search_gate.py
# apps/api/echoroo/api/**/*.py と services/ で
# select(Detection) / select(Annotation) / session.execute で直接検索しているコードを検出
# SearchGate 経由でないものは fail
```
- allowlist: `services/search_gate.py` と `repositories/detection.py`（内部実装）のみ

### D. ACTIONS カタログ対応検証（pytest リフレクション）

```python
# tests/security/authorization/test_endpoint_coverage.py
def test_all_endpoints_registered_in_actions():
    all_endpoints = collect_fastapi_routes(app)  # FastAPI から path operation 一覧を取得
    registered_actions = {a.name for a in ACTIONS.values()}
    for endpoint in all_endpoints:
        assert endpoint.action_name in registered_actions, \
            f"{endpoint.path} is not registered in ACTIONS catalog"
```

### E. raw lat/lng regression guard（§12 と連動）

```bash
# pre-commit hook + CI
grep -rE "(latitude|longitude|\\blat\\b|\\blng\\b|gps_)" \
  alembic/versions/*.py apps/api/echoroo/models/ apps/api/echoroo/schemas/ \
  | grep -vE "h3_index|\\.md:" \
  && exit 1 || exit 0
```

### F. OpenAPI 生成の coordinates 漏洩検出

```bash
# apps/api の開発時 / CI で openapi.json を生成してチェック
uv run python -m echoroo.scripts.dump_openapi > /tmp/openapi.json
grep -E "(latitude|longitude|gps_)" /tmp/openapi.json | grep -v "h3_index" | wc -l == 0
```

**Alternatives**:
- **ruff custom plugin**: Python の AST を native に扱えるが、plugin 開発 ~20h の工数増。3 種類の lint をすべて plugin 化するのは割に合わない
- **runtime のみ検証**: 実行時 middleware で通過チェックするのは pragmatic だが、CI で fail できず本番で初めて発覚するリスク

**Chosen Because**: 既存 Python ツール（libcst, ast）+ pytest で実装 ~200 行、ruff plugin に比べ導入容易。CI で `pytest tests/security/authorization/` + `python scripts/lint_*.py` + `grep` の 3 層で保証。post-launch で ruff plugin 化は retrospective で再検討。

## 17. OpenAPI 自動生成と型共有

**Decision**: **FastAPI の OpenAPI 自動出力** + **`openapi-typescript` で TypeScript 型生成**

**Rationale**:
- Constitution III（Type Safety）で「API レスポンスは OpenAPI 自動生成型経由」を要求
- FastAPI は Pydantic model から OpenAPI 3.1 spec を自動生成
- `openapi-typescript` は CLI で OpenAPI JSON/YAML → TypeScript interfaces を生成、Svelte 側の型として利用

**Alternatives**:
- **gRPC + protoc**: 型共有は強力だが、既存の REST スタイルから逸脱
- **自前型定義**: スキーマの drift リスク

**Chosen Because**: 既存 FastAPI / SvelteKit 構成をそのまま活かす、CI で `openapi.json` の変更を commit に強制することで drift を防ぐ。`contracts/` 配下の YAML は **人手で書く正規の契約**、`openapi.json` は **自動生成結果**、両者を CI で diff check して乖離を検出。

---

## 解決済み NEEDS CLARIFICATION

plan.md の Technical Context で保留していた項目は全て本 research.md で決定済み。`/speckit.tasks` で「ambiguous implementation direction」が残るリスクはなし。

---

## Phase 1 への引き継ぎ

次の Phase 1（Design & Contracts）では以下を生成する:

1. **data-model.md**: 本 research の決定（KMS、Alembic baseline、ORM モデル）を踏まえた全エンティティ詳細
2. **contracts/*.yaml**: OpenAPI 3.1 契約、`/api/v1` と `/web-api/v1` 両方
3. **quickstart.md**: 本 research の KMS / 2FA / wipe 手順を踏まえたローカル起動ガイド
4. **checklists/*.md**: security / performance チェックリスト

**Research Status**: ✅ 完了、Phase 1 へ進行可
