# API Contracts

本ディレクトリは spec Rev.3.2 の主要 API の OpenAPI 3.1 契約を格納する。FastAPI 実装時は Pydantic model から自動生成される `openapi.json` を正とし、この YAML との diff は CI で検証する（research.md §17）。

## 分離

- **`/api/v1/*`**（programmatic API、FR-077）: API key 必須（Authorization: Bearer）、Cookie 不可
- **`/web-api/v1/*`**（first-party session API、FR-077）: Cookie (`Path=/web-api/v1/; SameSite=Strict`) + CSRF トークン必須、API key 不可

## ファイル

| ファイル | 範囲 | spec 参照 |
|---|---|---|
| [`auth.yaml`](./auth.yaml) | `/web-api/v1/auth/*` — login / email verification / 2FA challenge / TOTP setup / WebAuthn / backup codes / logout / refresh | US8、FR-065〜FR-073、spec/010 |
| [`account.yaml`](./account.yaml) | `/web-api/v1/account/*` — DSR export/delete + trusted-device list/revoke | FR-105、FR-109、spec/010 |
| [`projects.yaml`](./projects.yaml) | `/api/v1/projects/*` + `/web-api/v1/projects/*` — CRUD、visibility 変更、restricted_config、ownership transfer | US1〜US4、US7、US10、FR-001〜FR-024、FR-063、FR-085 |
| [`trusted.yaml`](./trusted.yaml) | `/web-api/v1/projects/{id}/trusted-users` — 招待 / accept / revoke / extend | US5、FR-041〜FR-046 |
| [`detections.yaml`](./detections.yaml) | `/api/v1/projects/{id}/detections/*` — list / get / export CSV / export ML dataset / vote / comment | US1、US2、US6、FR-025〜036、FR-037〜040 |
| [`audit.yaml`](./audit.yaml) | `/api/v1/projects/{id}/audit-log`（project）, `/web-api/v1/admin/audit-log`（platform、superuser） | FR-088〜096 |
| [`admin.yaml`](./admin.yaml) | `/web-api/v1/admin/*` — superuser 操作（archived restore、looser override 承認、IUCN resync、2FA reset） | US7 #8、FR-111〜112、Runbook |

## 共通レスポンス形式

### エラー

```yaml
Error:
  type: object
  required: [error_code, message]
  properties:
    error_code:
      type: string
      example: "ERR_PERMISSION_DENIED"
    message:
      type: string
    request_id:
      type: string
      description: CloudWatch / audit log 連携用
    retry_after:
      type: integer
      nullable: true
      description: 429 時のみ
```

代表的な error_code:
- `ERR_API_KEY_REQUIRED`（401）
- `ERR_API_KEY_INVALID`（401）
- `ERR_PERMISSION_DENIED`（403）
- `ERR_PROJECT_ARCHIVED`（403）
- `ERR_SCOPE_DENIED`（403、API key scope 違反）
- `ERR_COOLDOWN_ACTIVE`（403、2FA reset 72h 中）
- `ERR_SUPERUSER_API_KEY_FORBIDDEN`（403）
- `ERR_EMAIL_MISMATCH`（403、招待 accept）
- `ERR_UNAUTHORIZED_PROJECT`（422、API key project_id 指定で user 非所属）
- `ERR_INVALID_TRUSTED_PERMISSION`（422、allowlist 外）
- `ERR_TRUSTED_TARGET_INVALID`（422、Viewer/Member/Admin/Owner に Trusted）
- `ERR_SELF_TRUSTED_INVALID`（422、Admin 自分自身）
- `ERR_VIEWER_ON_PUBLIC_PROJECT`（422）
- `ERR_LICENSE_REQUIRED`（422）
- `ERR_INVALID_TRANSFER_TARGET`（400、Admin 以外を指定）
- `ERR_UNKNOWN_FIELD`（422、mutable allowlist 外）
- `ERR_CONFLICT`（409、所有権移譲 race）

### 共通レスポンスヘッダ

以下は **全 path operation で必須付与**（spec FR-102 + security review C-1 対応）。各 contract YAML では明示せず、本 README に共通仕様として定義、CI contract test で全レスポンスに付与されていることを assert する。

#### セキュリティ関連（全レスポンス）

| Header | 値 | 根拠 |
|---|---|---|
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains; preload` | FR-102、HSTS |
| `Content-Security-Policy` | `default-src 'self'; script-src 'self' 'nonce-{nonce}'; object-src 'none'; ...` | FR-102、XSS 防御 |
| `X-Frame-Options` | `DENY` | FR-102、Clickjacking |
| `X-Content-Type-Options` | `nosniff` | FR-102 |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | FR-102 |
| `Permissions-Policy` | `geolocation=(), microphone=(), camera=()` | FR-102 |

#### アプリケーション関連（全レスポンス）

| Header | 値 | 根拠 |
|---|---|---|
| `X-Request-Id` | UUID v4 | audit log の `request_id` と一致 |

#### 条件付き

| Header | 条件 | 値 |
|---|---|---|
| `Cache-Control` | 検索 / 認証 / 個人データ系（detection list, export, 2FA, invitation） | `private, no-store`（FR-025c、species mask 漏洩対策） |
| `Cache-Control` | 静的メタ（project metadata 一覧） | `private, max-age=60` |
| `Set-Cookie` | `/web-api/v1/auth/2fa/challenge` 認証成功時 | `session_id=...; Path=/web-api/v1/; HttpOnly; Secure; SameSite=Strict`（FR-097）。spec/010 trusted-device 登録時は追加で `echoroo_trusted_device=...; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age<=2592000` |

## 認証 / 認可

### 共通 `securitySchemes` 定義

全 contract YAML で以下の 2 つの `securitySchemes` を参照する（各 YAML の `components.securitySchemes` に同じ定義をコピー、CI で diff 検証）:

```yaml
components:
  securitySchemes:
    apiKeyAuth:
      type: http
      scheme: bearer
      bearerFormat: "ek_live_{prefix}_{secret}"
      description: |
        Programmatic API 用（`/api/v1/*`）。API key 必須。
        Cookie は無視される（FR-077、FR-099）。
        contract test: Cookie 送信時でも 401 を返すこと。
    sessionCookie:
      type: apiKey
      in: cookie
      name: session_id
      description: |
        First-party session API 用（`/web-api/v1/*`）。
        Cookie `Path=/web-api/v1/; SameSite=Strict; Secure; HttpOnly`（FR-097）。
        state-changing 時は `X-CSRF-Token` header 必須（FR-098）。
    csrfToken:
      type: apiKey
      in: header
      name: X-CSRF-Token
      description: FR-098、HMAC-SHA256(session_secret, session_id || issued_at)
```

### Path 別の必須認証

| Path prefix | security（必須） | 排他 |
|---|---|---|
| `/api/v1/*` | `apiKeyAuth: []` のみ | Cookie 受け入れず（送られても無視 + 401） |
| `/web-api/v1/*` (read) | `sessionCookie: []` | API key 受け入れず（送られても 401） |
| `/web-api/v1/*` (state-changing) | `sessionCookie: [], csrfToken: []` | 同上 |
| `/web-api/v1/auth/register`, `/auth/login`, `/auth/password-reset/request`, `/auth/verify-email`, `/auth/verify-email/resend` | なし（未認証公開） | — |

各 contract YAML の path operation には `security:` ブロックを必ず明示。CI contract test で `servers` と `security` の組合せが上記表と一致することを検証。

### File-level security vs Path-operation security override

各 YAML は以下の規則に従う（OpenAPI 3.1 の semantic: 配列要素 = OR、要素内 object 複数 key = AND）:

1. **File-level `security`**: **最も緩い `read-only` 経路** のみ宣言
   ```yaml
   security:
     - apiKeyAuth: []       # programmatic read
     - sessionCookie: []    # first-party read
   ```
   file-level はあくまで read-only の default。state-changing 系には必ず override する。

2. **Path-operation `security` override**: state-changing (POST/PATCH/DELETE)、および CSRF 必須の operation で以下に書き換え:
   ```yaml
   security:
     - apiKeyAuth: []                      # programmatic state-changing（Bearer のみ）
     - sessionCookie: []                   # first-party state-changing では
       csrfToken: []                       # Cookie + CSRF を AND で要求
   ```

3. **未認証 operation**（`/web-api/v1/auth/register`, `/auth/login`, `/auth/password-reset/request`, `/auth/verify-email`, `/auth/verify-email/resend`, `/auth/2fa/challenge`）:
   ```yaml
   security: []
   ```

4. **Superuser-only operation**（`/web-api/v1/admin/*`）: `superuserSession` securityScheme を別途定義して使用:
   ```yaml
   security:
     - superuserSession: []
   ```

CI contract test で以下を検証:
- すべての path operation が `security:` を持つ（file-level default または operation override）
- state-changing HTTP メソッド（POST/PATCH/DELETE/PUT）の operation は override で `csrfToken` を含む（`security: []` の未認証系を除く）
- `/api/v1/*` path では `sessionCookie` 系が security から除外されている（Cookie 不可 契約）
- `/web-api/v1/*` path では `apiKeyAuth` が security から除外されている（API key 不可 契約）

### CORS ポリシー

- `/api/v1/*`: `Access-Control-Allow-Origin: *`（public）、`Allow-Credentials: false`、Authorization ヘッダのみ受理
- `/web-api/v1/*`: 厳格な same-origin（`https://echoroo.app` のみ）、`Allow-Credentials: true`、Cookie + CSRF
- `/web-api/v1/admin/*`: さらに IP allowlist（superuser の fixed CIDR）で絞る（FR-111）

### Server 分離の原則

OpenAPI の `servers` はファイル単位で **programmatic か first-party のどちらか一方に固定**:

- `auth.yaml` → `https://echoroo.app/web-api/v1` のみ（programmatic には auth endpoint なし）
- `admin.yaml` → `https://echoroo.app/web-api/v1/admin` のみ（programmatic 不可、FR-084）
- `trusted.yaml` → `https://echoroo.app/web-api/v1` のみ
- `audit.yaml` → `https://echoroo.app/web-api/v1` のみ（project audit は Owner/Admin の Web、platform audit は superuser の Web）
- `projects.yaml`, `detections.yaml` → **両方**（programmatic と first-party の両対応）、ただし各 path operation で security 明示

両 API とも同じ FastAPI サービスで実装、認証 middleware が URL prefix で分岐する。

## Permission / Response Filter

全エンドポイントは `Action` カタログに登録された action 経由で Permission gate を通過し、list / get 系レスポンスは `ResponseFilter` を通して `h3_index` 解像度調整 + `species` マスクが適用される。Response には以下のフィールドが常に含まれる（list 系）:

```yaml
ResourceWithSensitivity:
  type: object
  properties:
    h3_index:
      type: string
      description: computed by compute_effective_resolution
    location_generalization:
      type: integer
      description: 適用された H3 resolution（FR-086）
    withheld_reason:
      type: string
      enum: [none, project_toggle, taxon_sensitivity, hidden]
      description: FR-086
    species:
      type: string
      description: mask_species_in_detection=true の場合 "(masked)"
```

---

詳細は各 YAML を参照。FastAPI 実装時に Pydantic model が OpenAPI 自動生成の正となり、ここの YAML は **人間可読の正規契約**として維持される（drift は CI で検出、research.md §17）。
