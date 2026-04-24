# 機能仕様書: 権限・公開レベル再設計（Permissions and Visibility Redesign）

**フィーチャーブランチ**: `006-permissions-redesign`
**作成日**: 2026-04-24（初版）／ Rev.2（3者レビュー 1 回目反映）／ Rev.3（3者レビュー 2 回目反映）／ Rev.3.1（3者レビュー 3 回目の pin-point 追記）／ **Rev.3.2（3者包括レビュー 4 回目の pin-point 追記、`/speckit.plan` 対象）**
**ステータス**: ドラフト（Rev.3.2、3者 GO 済み、plan 着手可）
**入力**: Discord 議論（2026-04-23〜04-24）での合意事項 + codex / architect-reviewer / security-auditor による 4 回の 3者レビュー

## 概要

Echoroo の権限モデルを、プレローンチ段階で全面的に再設計する。現行実装の問題点:

- 複数エンドポイント（`detections`, `tags`, `uploads`, `custom_models`）で `check_project_access` が抜けており、認証さえしていれば非メンバーでも他人のプロジェクトを操作できる
- `ProjectVisibility` に `PUBLIC` 値はあるが実装が存在せず、未ログインユーザーには何も見えない
- Permission enum が `VIEW / EDIT / MANAGE_MEMBERS / DELETE_PROJECT` の 4 種類しかなく、細粒度制御ができない
- VIEWER と MEMBER の差が実効的に機能していない
- 希少種の位置情報を保護する仕組みがない

本スペックは上記を一掃し、以下の設計思想で作り直す:

1. **Public / Restricted の 2 段階 Visibility**（Private 廃止）: Echoroo はエコアコースティクスのインフラで、プロジェクトのメタデータは最低限コミュニティに公開する
2. **Restricted の項目別オーナートグル**: 録音再生・検出結果・種マスク・位置精度・DL・Export・投票・コメント・Viewer への precise location 解放を独立に制御
3. **Location Sensitivity を H3 解像度単一軸で制御**: 録音・種レベルで位置精度を H3 resolution で管理
4. **Trusted User は `Authenticated` への ephemeral capability overlay**: Permission サブセット + 期限付き、allowlist 方式
5. **メール招待ワークフローのみ**: アクセス申請は Echoroo 上で実装しない
6. **2FA 必須化**: 全ユーザー TOTP、superuser は WebAuthn hardware key 追加
7. **既存データ全消去**: プレローンチ、wipe 2 度目実行不可ガード
8. **Permission 決定は 2 ステージ**: (1) Permission gate で認可判定（`effective_permissions` を 1 回だけ算出）、(2) Response filter でレスポンス加工（gate で計算済みの集合を引数で渡す、再帰呼び出し禁止）
9. **TDD 現実解**: 権限系は mutation testing + パラメトリック網羅、E2E は P1 + セキュリティ重要（SC-004 / SC-005 / SC-009）
10. **AuditLog は project_audit_log と platform_audit_log に分離**
11. **監査ログは raw PII を最初から保持しない**: PII は保存時点で keyed hash のみ、GDPR と append-only の両立を構造的に解決
12. **raw lat/lng は全経路で排除**: DB カラム非存在、upload 時 EXIF strip、Celery payload schema で lat/lng 禁止、log redaction、S3 upload lambda で metadata 除去

---

## Clarifications

### セッション 2026-04-23（Discord）

- Q: 3 段階 vs 2 段階 → **A: 2 段階（Private 廃止）**
- Q: Public で Guest が再生可能か → **A: 可（DL/Export/検索/投票/コメントはログイン必須）**
- Q: Restricted のデフォルト → **A: メタ・Dataset 存在のみ公開、他はオーナートグル**
- Q: メンバー/非メンバー投票の区別 → **A: `AnnotationVote.source` + `project_role_at_vote`**
- Q: 位置情報 → **A: Site に H3 二重化、録音・種単位で Sensitivity**
- Q: 希少種リスト → **A: IUCN + MOE RDB + プロジェクト override**
- Q: Trusted 粒度 → **A: Permission サブセット、デフォルト 90 日・上限 1 年**
- Q: アクセス申請 → **A: Echoroo 上で実装しない、メール招待のみ**
- Q: ライセンス → **A: プロジェクト単位 CC 必須**
- Q: プロジェクト削除・オーナー離脱 → **A: 休眠表示、Admin 自動移譲、不在なら archived**
- Q: API アクセス → **A: API key 必須 + scope**
- Q: 2FA → **A: 全ユーザー必須**

### セッション 2026-04-24a（Rev.2 反映）

- Permission 決定アルゴリズム擬似コード化、H3 解像度単一軸化、Trusted を capability overlay として再定義、Viewer を Restricted 招待閲覧専用者として再定義、programmatic API と first-party session API を URL prefix + Cookie Path で分離、招待トークン SHA-256 hash + HMAC 署名 + email 一致、2FA AES-256-GCM + KMS、refresh token revocation、ApiKey scope × Role AND 結合、restricted_config Pydantic + CHECK、TDD を権限系 mutation + パラメトリックに変更、Darwin Core 最小メタを Goal へ

### セッション 2026-04-24b（Rev.3 反映）

- 擬似コードを **Permission gate + Response filter の 2 ステージ分離**、Guest / Viewer を明示
- `VIEW_PRECISE_LOCATION` を Permission enum に正式追加
- `TRUSTED_ALLOWED_PERMISSIONS` allowlist を定数定義、runtime 再フィルタ
- 緩和 override は `compute_effective_resolution` 内の分岐で global を置換
- AuditLog を project / platform に 2 分割
- PII は保存時 keyed hash、raw は保持しない設計に移行
- SEARCH_CROSS_PROJECT は index 物理除外 + project-level aggregation
- Viewer に `expires_at` + `allow_precise_location_to_viewer` トグル、Public では Authenticated 同等
- Invitation / TrustedUser 責務分離（pending/token_hash は Invitation のみ）
- ApiKey 離脱時自動 revoke、superuser 操作は API key 不可
- 鍵ローテ SLA 表、DEK rewrap 月次、HMAC 2 鍵並行、CMK deletion 30 日
- Site の生 lat/lng を DB に保存しない
- NFR-001 p95 <= 4 クエリ、<30ms に緩和、request-scope キャッシュ許容
- Superuser セキュリティ FR-111 独立セクション
- メール RFC 5321 envelope / 5322 header 検証分離

### セッション 2026-04-24c（Rev.3.1 pin-point 追記）

- Q: `has_permission` 再帰で bulk クエリ爆発 → **A: ステージ 1 で `effective_permissions` を 1 回だけ算出、ステージ 2 に引数渡し、再帰禁止**
- Q: Public 時の Viewer 補正が Response filter 側で崩れる → **A: `compute_effective_resolution` でも Public 時は Viewer を Authenticated に正規化**
- Q: `permissions_from_restricted_toggles` の Guest / Authenticated 分岐と Matrix の 🟡 不整合 → **A: `RESTRICTED_TOGGLE_PERMISSIONS_FOR_GUEST` と `RESTRICTED_TOGGLE_PERMISSIONS_FOR_AUTHENTICATED` の 2 テーブルに分離、Matrix 脚注で Guest 列の 🟡 は `VIEW_MEDIA` / `VIEW_DETECTION` のみ適用と明記**
- Q: GDPR × 監査ログ衝突 → **A: 監査ログに raw PII を最初から持たない設計に一本化。`actor_user_id_hash` / `ip_hash` / `user_agent_hash` のみ保存、raw 列は存在しない**
- Q: raw lat/lng の全経路保証 → **A: FR-028a〜e で upload EXIF strip / Celery payload schema / log redaction / S3 upload lambda / SecureString 化を義務付け**
- Q: SEARCH ON→OFF の leak window → **A: 2 段階コミット（Permission gate で即時除外、index 削除は非同期）、検索レスポンスに `Cache-Control: private, no-store`**
- Q: ApiKey 離脱時 revoke のタイミング → **A: `ProjectMember DELETE` の同一 TX + outbox pattern、最大遅延 60s、E2E で検証**
- Q: Action の型定義 → **A: FR-008a で Action Pydantic model + `ACTIONS` カタログ、CI 静的解析で未登録 action 検出**
- Q: Superuser の Permission 経路 → **A: platform-scope guard を別関数化、Response filter は Superuser にも適用（raw 不可）**
- Q: Invitation CHECK 制約 → **A: `status` を含めた CHECK に修正、`trusted_granted_at` は Invitation 側に持たない（ProjectTrustedUser.granted_at のみ）**
- Q: Permission 数の食い違い → **A: Project 権限 26 + User 自己管理 2 = 合計 28 に統一**
- Q: TrustedUser email 命名 → **A: `email_at_invitation` に統一、FR-108 を訂正**
- Q: Recording list の bulk per-row Taxon sensitivity → **A: NFR-001a で「N 行の Taxon は `WHERE taxon_id IN (...)` の 1 クエリ preload、合計 p95 ≤ 5 クエリ」と明文化**

### セッション 2026-04-24d（Rev.3.2 pin-point 追記）

4 回目の 3者包括レビューで全員が「条件付き GO、Critical ゼロ」判定。残る重要指摘を pin-point で反映:

- Q: 擬似コードの superuser 分岐が未定義 → **A: `is_allowed` 冒頭に superuser 分岐 + `SUPERUSER_PROJECT_SCOPE_ALLOWLIST` カタログ**
- Q: `normalize_role` と `compute_effective_permissions` の責務が二重化 → **A: `is_allowed` で `normalized_role` を 1 回確定し引数渡し、`compute_effective_permissions` 内の Public 補正分岐を削除**
- Q: `Action` モデルの整合ルールが曖昧 → **A: `required_permission: Permission | None` + Pydantic `model_validator` で `is_platform_scope=true ⇒ required_permission=None AND is_superuser_only=true` を強制**
- Q: FR-048 CHECK 制約の閉じ切り不足 → **A: `kind/status NOT NULL`、`jsonb_typeof(granted_permissions)='array'`、`trusted_duration_seconds BETWEEN 1 AND 31536000` を追加**
- Q: Public 化後の既存 Trusted overlay の扱い未定義 → **A: 既存 Trusted overlay は有効化される（再招待不要）。ただし Public 化時点で Viewer 属の Trusted は自動 revoke（現行で Viewer への Trusted は発行不可なので該当少ない）**
- Q: HIDDEN 判定の looser override 承認後の semantics → **A: looser override 承認後は global sensitivity を置換した上で HIDDEN 判定し直す（置換後が `H3_RES_2` でなければ HIDDEN 解除）**
- Q: raw lat/lng の将来 regression 防止 → **A: FR-028f で migration / ORM / Pydantic の lat/lng カラム・field 静的 lint を CI 強制**
- Q: 監査ログ JSONB `before` / `after` の PII runtime 混入対策 → **A: FR-091a を runtime sanitizer に改訂、PII regex で hash 置換、`{hash, hash_version, redacted=true}` 形式で正規化**
- Q: SEARCH 2 段階コミットが全検索経路で保証されるか → **A: FR-025a を OpenSearch / pgvector / PostgreSQL FTS の 3 経路すべてで `SearchGate` 必須に改訂、pgvector は post-filter + k*3 fetch、SC-018 を 3 経路で検証**

### 決定された非目標

- Darwin Core 準拠エクスポートのフル実装（最小メタ 2 列のみ本スコープ）
- アノテーション単位の公開設定、ユーザーブロック機能、プロジェクト内データ単位のライセンス分け
- SSE / WebSocket による toggle 変更の即時 push
- 既存データのマイグレーション、組織（Organization）単位の権限管理
- 非 TOTP 型の一般ユーザー 2FA（superuser は WebAuthn 必須）
- 録音中の人声自動検出 / マスキング
- 生 lat/lng の保存（設計段階で排除）

---

## 主体とロール構造 *(必須)*

### 6 主体モデル

| # | 主体 | 説明 |
|---|---|---|
| 1 | **Guest** | 未認証 |
| 2 | **Authenticated** | 認証済み・当プロジェクト未所属 |
| 3 | **Viewer** | Restricted の招待閲覧専用者、`expires_at` 付き |
| 4 | **Member** | 編集権限あり |
| 5 | **Admin** | メンバー管理権限あり |
| 6 | **Owner** | 所有者、1 プロジェクトに 1 人 |

**Superuser** はプラットフォーム横断の別枠（FR-111）。`resolve_role` が Project 判定用に返す値には含まれない（platform-scope guard で別処理）。

### Trusted User (Authenticated への capability overlay)

Authenticated に対する Permission サブセット + 期限付きの overlay。`TRUSTED_ALLOWED_PERMISSIONS` の範囲内のみ付与可。`AnnotationVote.source = trusted_user`。

### Viewer の詳細定義

- Restricted プロジェクトで Owner/Admin が招待、`ProjectMember.role = VIEWER`、`expires_at` (nullable)
- 実効 Permission は固定: `{VIEW_PROJECT_METADATA, VIEW_DATASET_LIST, VIEW_MEDIA, VIEW_DETECTION, SEARCH_WITHIN_PROJECT}`
- DL / Export / VOTE / COMMENT / SEARCH_CROSS_PROJECT は Restricted トグル ON でも **Viewer には付与しない**
- Taxon sensitivity は Authenticated と同じ auto-obscure
- `allow_precise_location_to_viewer` トグル ON で precise location 付与
- **Public プロジェクトでは Viewer は Authenticated 同等**（Permission gate と Response filter の両方で正規化）
- Public への Viewer 新規招待は 422 `ERR_VIEWER_ON_PUBLIC_PROJECT`
- Restricted → Public 変更時、既存 Viewer は role 保持で Permission は Authenticated 相当、UI 警告 + acknowledge checkbox 必須

### Visibility

- **Public**: 全員が メタ・Dataset・Recording 再生・スペクトログラム・検出結果を閲覧可。DL/Export/検索/投票/コメントはログイン必須
- **Restricted**: メタ・Dataset 存在・種リスト概要は全員必須公開、他はオーナートグル
- `Project.status`: `active` / `dormant` / `archived`

---

## Permission 決定アルゴリズム *(必須)*

Permission 判定は 2 ステージで厳密に分離する。**再帰呼び出しを禁止**し、ステージ 1 で算出した `effective_permissions` をステージ 2 に引数で渡す。

### Action モデル（ステージ共通）

```python
class Action(BaseModel):
    name: str                                # e.g. "detection.vote", "project.transfer_ownership"
    required_permission: Permission | None   # platform-scope では None
    is_mutating: bool                        # state-changing かどうか
    is_superuser_only: bool                  # superuser 専用 action かどうか
    is_platform_scope: bool                  # project 無関係の platform-scope action かどうか

    @model_validator(mode="after")
    def _validate_consistency(self) -> "Action":
        if self.is_platform_scope:
            # platform-scope は project を参照しない、必ず superuser のみが触る
            assert self.required_permission is None, "platform-scope actions must not require a project permission"
            assert self.is_superuser_only, "platform-scope actions must be superuser-only"
        else:
            assert self.required_permission is not None, "project-scope actions require a permission"
        return self

ACTIONS: dict[str, Action] = {...}  # 全エンドポイントが登録、CI 静的解析で未登録 action を検出

# Superuser が project-scope action として許可される allowlist
# これに含まれる action のみ、superuser が project の Permission gate を bypass して実行可能
SUPERUSER_PROJECT_SCOPE_ALLOWLIST: frozenset[str] = frozenset({
    "project.restore",              # archived → active の復帰
    "project.taxon_override.approve_looser",  # looser override 承認
    "project.taxon_override.reject_looser",
    "project.iucn.force_resync",    # IUCN 緊急再同期
    "project.audit_log.read_platform",  # platform_audit_log 閲覧
})
```

### ステージ 1: Permission Gate

```python
def is_allowed(user, project, action: Action, auth_method, request) -> tuple[bool, frozenset[Permission]]:

    # 0. 認証層
    if not authenticate(user, auth_method, request):
        return False, frozenset()  # 401

    # 0a. Platform-scope action は project を参照しない別ルート
    if action.is_platform_scope:
        return is_platform_action_allowed(user, action), frozenset()

    # 0b. Superuser の project-scope allowlist 経由
    if user and is_superuser(user):
        if action.name in SUPERUSER_PROJECT_SCOPE_ALLOWLIST:
            # superuser が allowlist 内 action を実行する場合は Matrix を bypass
            effective = frozenset(ROLE_PERMISSIONS["Superuser"])
            request.state.effective_permissions = effective
            request.state.normalized_role = "Superuser"
            return True, effective
        # allowlist 外の project action は通常経路（Superuser も Response filter を通過、raw 不可）
        # ただし superuser は他人プロジェクトで Owner/Admin と同等の Permission にマッピングする
        # 実装詳細は FR-112a 参照

    # 1. Archived プロジェクト制限
    if project.status == "archived" and action.is_mutating:
        return False, frozenset()  # 403 ERR_PROJECT_ARCHIVED

    # 2. normalized_role を 1 回だけ確定（Public での Viewer → Authenticated 正規化を含む）
    normalized_role = normalize_role(user, project)

    # 3. ベース Permission の確定（normalized_role を引数渡し、内部で resolve_role を再呼び出ししない）
    effective = compute_effective_permissions(normalized_role, user, project, auth_method, request)

    # 4. Permission 最終判定
    allowed = action.required_permission in effective

    # 5. Response filter がステージ 2 で使う effective / normalized_role を request.state に格納
    request.state.effective_permissions = effective
    request.state.normalized_role = normalized_role
    return allowed, effective


def compute_effective_permissions(
    normalized_role: str,
    user,
    project,
    auth_method,
    request,
) -> frozenset[Permission]:
    # normalized_role は is_allowed 側で Public/Viewer 補正済み。ここでは resolve_role を呼ばない
    base = set(ROLE_PERMISSIONS[normalized_role])  # Canonical Matrix、Project 権限のみ

    # Trusted overlay は Authenticated のみ
    # （Public 化によって Viewer が Authenticated に正規化された場合、既存 Trusted overlay は有効化される。
    #  Trusted 発行は発行時点の role で判定するため、Viewer への Trusted 付与は FR-015 で 422 として拒否される）
    if normalized_role == "Authenticated":
        trusted = active_trusted_capabilities(user, project)
        trusted = trusted & TRUSTED_ALLOWED_PERMISSIONS  # runtime safety net
        base |= trusted

    # Restricted toggle: Guest / Authenticated のみが追加対象
    if project.visibility == "RESTRICTED":
        if normalized_role == "Guest":
            base |= permissions_from_toggles_for_guest(project.restricted_config)
        elif normalized_role == "Authenticated":
            base |= permissions_from_toggles_for_authenticated(project.restricted_config)
        elif normalized_role == "Viewer":
            # `allow_precise_location_to_viewer` トグルは Viewer への capability 追加として扱う
            if project.restricted_config.allow_precise_location_to_viewer:
                base |= {VIEW_PRECISE_LOCATION}

    # API key scope 交差
    if auth_method == "api_key":
        api_key = request.api_key
        if api_key.project_id is not None and api_key.project_id != project.id:
            return frozenset()
        base &= api_key.granted_permissions

    return frozenset(base)


RESTRICTED_TOGGLE_PERMISSIONS_FOR_GUEST = {
    "allow_media_playback": {VIEW_MEDIA},
    "allow_detection_view": {VIEW_DETECTION},
}
# Guest は DL / EXPORT / VOTE / COMMENT / SEARCH_* を絶対に取得しない（Matrix 🟡 は Guest 列では VIEW_MEDIA / VIEW_DETECTION のみに適用）

RESTRICTED_TOGGLE_PERMISSIONS_FOR_AUTHENTICATED = {
    "allow_media_playback": {VIEW_MEDIA},
    "allow_detection_view": {VIEW_DETECTION},
    "allow_download": {DOWNLOAD},
    "allow_export": {EXPORT},
    "allow_voting_and_comments": {VOTE, COMMENT},
}


TRUSTED_ALLOWED_PERMISSIONS = frozenset({
    VIEW_MEDIA, VIEW_DETECTION, VIEW_PRECISE_LOCATION,
    DOWNLOAD, EXPORT, SEARCH_WITHIN_PROJECT, VOTE, COMMENT,
})
```

### ステージ 2: Response Filter

ステージ 1 の結果 (`effective_permissions` と `normalized_role`) を引数で受け取り、**DB 再アクセスせず**にレスポンス加工する。

```python
def apply_response_filter(response_obj, resource, effective: frozenset[Permission], role: str, project) -> response_obj:
    # R1. 生 lat/lng は Pydantic model に存在しないので除外（FR-028〜031）
    effective_resolution = compute_effective_resolution(resource, effective, role, project)
    response_obj.h3_index = h3_to_parent(resource.h3_index_member, effective_resolution)

    if should_mask_species(effective, role, project, resource):
        response_obj.species = "(masked)"

    response_obj.location_generalization = effective_resolution
    response_obj.withheld_reason = compute_withheld_reason(resource, effective, role, project)
    return response_obj


def compute_effective_resolution(
    resource,
    effective: frozenset[Permission],
    role: str,
    project,
    taxon_sensitivity_map: dict | None = None,
    override_map: dict | None = None,
) -> int:
    # NFR-001a: bulk リクエストでは preload dict を引数で受け取り、DB 追加アクセスせず。
    # 単体呼び出しでは fallback で TAXON_SENSITIVITY / PROJECT_TAXON_OVERRIDE を参照。
    global_taxon_res = (taxon_sensitivity_map or TAXON_SENSITIVITY).get(resource.taxon_id, H3_RES_9)
    local_override = (override_map or PROJECT_TAXON_OVERRIDE).get((project.id, resource.taxon_id))

    # Step A: override direction を先に評価して「有効 global」を確定（FR-034、FR-035）
    if local_override and local_override.direction == "looser" and local_override.approval_status == "applied":
        effective_global_res = local_override.resolution  # looser 承認は global を置換
        override_source = "looser_approved"
    elif local_override and local_override.direction == "stricter":
        effective_global_res = min_resolution(global_taxon_res, local_override.resolution)
        override_source = "stricter"
    else:
        effective_global_res = global_taxon_res
        override_source = "none"

    # Step B: HIDDEN 判定は「有効 global」で行う（FR-035 semantics）
    # - global が `H3_RES_2` かつ looser で置換されていない → HIDDEN 維持
    # - stricter override で `H3_RES_2` に強化 → HIDDEN 維持
    # - looser 承認済みで `H3_RES_2` 以外に緩和 → HIDDEN 解除（以降の Trusted/Member 分岐で member 解像度可）
    if effective_global_res == H3_RES_2:
        return H3_RES_2  # HIDDEN は Trusted / Viewer でも絶対に解除しない

    # Step C: メンバー / superuser は member 解像度（ただし FR-112a で raw 不可、H3 解像度のみ）
    if role in ("Member", "Admin", "Owner", "Superuser"):
        return resource.h3_index_member_resolution

    # Step D: Trusted の VIEW_PRECISE_LOCATION は member 解像度（HIDDEN は Step B で return 済み）
    if VIEW_PRECISE_LOCATION in effective:
        return resource.h3_index_member_resolution

    # Step E: 非メンバー向け Project toggle は Restricted のみ、Public では常に H3_RES_9
    if project.visibility == "PUBLIC":
        project_toggle_res = H3_RES_9
    else:
        project_toggle_res = project.restricted_config.public_location_precision_h3_res

    return min_resolution(effective_global_res, project_toggle_res)


def normalize_role(user, project):
    # Public では Viewer を Authenticated に正規化。compute_effective_permissions と compute_effective_resolution の両方で使う
    role = resolve_role(user, project)
    if project.visibility == "PUBLIC" and role == "Viewer":
        return "Authenticated"
    return role
```

### 補助定義

- `resolve_role(user, project)`: Owner / Admin / Member / Viewer / Authenticated のうち最も権限の強いロールを返す。Superuser は返さない（platform-scope で別処理）
- `active_trusted_capabilities(user, project)`: `ProjectTrustedUser` を参照、`status=active` + `expires_at > now_utc` の `granted_permissions` を返す。request-scope でキャッシュ（プロセス間キャッシュ禁止）
- `is_platform_action_allowed(user, action)`: superuser の platform-scope action を判定する別関数
- `min_resolution(a, b)`: 2 つの H3 解像度のうち粗い方を返す

---

## Canonical Permission Matrix *(必須)*

### Permission enum (合計 28 個、2 分類)

#### Project 権限 26 個（Matrix 対象）

**閲覧**: `VIEW_PROJECT_METADATA`, `VIEW_DATASET_LIST`, `VIEW_MEDIA`, `VIEW_DETECTION`, `VIEW_PRECISE_LOCATION`, `VIEW_AUDIT_LOG`

**検索・出力**: `SEARCH_WITHIN_PROJECT`, `SEARCH_CROSS_PROJECT`, `DOWNLOAD`, `EXPORT`

**編集**: `VOTE`, `COMMENT`, `CREATE_TAG`, `ANNOTATE`, `UPLOAD`, `MANAGE_SITE`, `MANAGE_DATASET`, `RUN_INFERENCE`, `TRAIN_MODEL`

**管理**: `MANAGE_MEMBERS`, `MANAGE_TRUSTED`, `EDIT_PROJECT`, `MANAGE_LICENSE`, `DELETE_PROJECT`, `TRANSFER_OWNERSHIP`, `OVERRIDE_TAXON_SENSITIVITY`

#### User 自己管理権限 2 個（Matrix 外）

- `MANAGE_API_KEY`: 自分の API key
- `MANAGE_2FA`: 自分の 2FA

合計 **28 個** (Project 26 + User 2)。

### Role × Project Permission マトリクス

凡例: ✅ 常時付与 / ❌ 非付与 / 🟡 Visibility + toggle 依存（Guest 列で 🟡 は `VIEW_MEDIA` / `VIEW_DETECTION` のみ、DL/EXPORT/VOTE/COMMENT/SEARCH は Guest では常に ❌）

| Permission | Guest | Authenticated | Viewer | Member | Admin | Owner |
|---|---|---|---|---|---|---|
| VIEW_PROJECT_METADATA | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| VIEW_DATASET_LIST | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| VIEW_MEDIA | 🟡 | 🟡 | ✅ | ✅ | ✅ | ✅ |
| VIEW_DETECTION | 🟡 | 🟡 | ✅ | ✅ | ✅ | ✅ |
| VIEW_PRECISE_LOCATION | ❌ | ❌（Trusted overlay で追加可） | 🟡 `allow_precise_location_to_viewer` toggle | ✅ | ✅ | ✅ |
| VIEW_AUDIT_LOG | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| SEARCH_WITHIN_PROJECT | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| SEARCH_CROSS_PROJECT | ❌ | ✅ | ❌ | ✅ | ✅ | ✅ |
| DOWNLOAD | ❌ | 🟡 | ❌ | ✅ | ✅ | ✅ |
| EXPORT | ❌ | 🟡 | ❌ | ✅ | ✅ | ✅ |
| VOTE | ❌ | 🟡 | ❌ | ✅ | ✅ | ✅ |
| COMMENT | ❌ | 🟡 | ❌ | ✅ | ✅ | ✅ |
| CREATE_TAG | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |
| ANNOTATE | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |
| UPLOAD | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |
| MANAGE_SITE | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |
| MANAGE_DATASET | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| RUN_INFERENCE | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |
| TRAIN_MODEL | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| MANAGE_MEMBERS | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| MANAGE_TRUSTED | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| EDIT_PROJECT | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| MANAGE_LICENSE | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| DELETE_PROJECT | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| TRANSFER_OWNERSHIP | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| OVERRIDE_TAXON_SENSITIVITY | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |

**脚注**:
- OVERRIDE_TAXON_SENSITIVITY は trigger 権限。stricter は即時、looser は superuser 承認経由
- Guest 列の 🟡 は `VIEW_MEDIA` / `VIEW_DETECTION` のみで意味を持つ。DOWNLOAD / EXPORT / VOTE / COMMENT / SEARCH_* の 🟡 は Authenticated 行のみを指し、Guest 行は常に ❌
- User 自己管理権限（MANAGE_API_KEY, MANAGE_2FA）は本 Matrix 対象外。ログイン済みユーザーは自分のリソースに対して常時保有

### Restricted Toggle → Permission 追加マップ

Guest 対象:
| Toggle | 追加 Permission |
|---|---|
| `allow_media_playback` | VIEW_MEDIA |
| `allow_detection_view` | VIEW_DETECTION |

Authenticated 対象:
| Toggle | 追加 Permission |
|---|---|
| `allow_media_playback` | VIEW_MEDIA |
| `allow_detection_view` | VIEW_DETECTION |
| `allow_download` | DOWNLOAD |
| `allow_export` | EXPORT |
| `allow_voting_and_comments` | VOTE, COMMENT |

`mask_species_in_detection`, `public_location_precision_h3_res`, `allow_precise_location_to_viewer` は Permission 追加ではなく Response filter 内で参照される（`mask_species` は species 書換、`public_location_precision_h3_res` は resolution 計算、`allow_precise_location_to_viewer` は Viewer へ `VIEW_PRECISE_LOCATION` capability 追加）。

---

## ユーザーシナリオとテスト *(必須)*

### ユーザーストーリー 1 - 未ログインユーザーが Public プロジェクトで録音を再生（優先度: P1）

未ログイン来訪者が Public プロジェクトで録音再生とスペクトログラム表示ができる。DL/Export/検索は 401。希少種位置は自動 obscure。

**独立テスト**: Guest で Public 閲覧、再生・スペクトログラム OK、DL ボタン非活性、programmatic API は 401、希少種位置は `H3_RES_5` 以下。

**受け入れシナリオ**:

1. **Given** Public プロジェクト、**When** Guest が一覧を開く、**Then** カード表示（first-party session 経由 200）
2. **Given** Guest が詳細ページ、**When** Recording 再生、**Then** 再生・スペクトログラム表示成功
3. **Given** Guest 状態、**When** DL ボタン押下、**Then** UI が「ログイン必要」、API 直叩きは 401
4. **Given** Guest、**When** `/api/v1/` に API key なしで叩く、**Then** 401 `ERR_API_KEY_REQUIRED`
5. **Given** IUCN `EN` 希少種の検出、**When** Guest 閲覧、**Then** 位置は `H3_RES_5` 以下、生 lat/lng はレスポンスにも DB にも log にも S3 metadata にも存在しない

### ユーザーストーリー 2 - ログイン済み非メンバーが Public プロジェクトをエクスポート・投票（優先度: P1）

**受け入れシナリオ**:

1. **Given** Authenticated が Public 閲覧、**When** CSV エクスポート、**Then** ライセンス + `location_generalization` + `withheld_reason` が同梱
2. **Given** Authenticated、**When** 投票、**Then** `source=guest_authenticated`、`project_role_at_vote=null`
3. **Given** 混在投票、**When** 集計、**Then** メンバー / 非メンバー / Trusted 3 カウント別表示
4. **Given** Authenticated、**When** 他 Authenticated の投票者 ID 取得、**Then** 403（個票は Owner/Admin のみ）
5. **Given** Authenticated コメント、**When** 一覧、**Then** 「非メンバー」バッジ

### ユーザーストーリー 3 - Restricted オーナートグル（優先度: P1）

**受け入れシナリオ**:

1. **Given** Restricted 新規作成、**Then** 全 bool トグル OFF、`public_location_precision_h3_res=2`、`allow_precise_location_to_viewer=false`
2. **Given** `allow_media_playback=ON`、**Then** Authenticated で再生可、DL は別トグル
3. **Given** `allow_detection_view=ON`, `mask_species_in_detection=true`、**Then** species が `(masked)`
4. **Given** `public_location_precision_h3_res=5`、**Then** Authenticated の地図は H3_RES_5
5. **Given** `allow_voting_and_comments=OFF`、**When** 投票試行、**Then** 403
6. **Given** `allow_detection_view=OFF`、**When** 横断検索 ON→OFF 変更、**Then** 即時に検索結果から除外（FR-025a の 2 段階コミット）
7. **Given** Viewer、**When** 再生、**Then** Restricted トグル無視で再生可能
8. **Given** Viewer + `allow_precise_location_to_viewer=false`、**Then** 非メンバー相当の粒度
9. **Given** Viewer + `allow_precise_location_to_viewer=true`、**Then** メンバー解像度
10. **Given** Viewer で投票、**Then** 403

### ユーザーストーリー 4 - Restricted の発見とオーナー連絡（優先度: P1）

**受け入れシナリオ**:

1. **Given** Restricted、**Then** Guest が一覧で名前・概要・種リスト概要・Dataset 件数を閲覧
2. **Given** Authenticated が Restricted 詳細、**Then** オーナー表示名 + `mailto:` 参加申請リンク
3. **Given** `allow_detection_view=OFF`、**When** 横断検索で種名、**Then** 種別ヒットせず、メタのみヒット

### ユーザーストーリー 5 - Trusted User 招待（優先度: P2）

**受け入れシナリオ**:

1. **Given** Owner、**When** Trusted 招待フォーム送信、**Then** `ProjectInvitation(kind=trusted, status=pending, token_hash=...)` 作成、署名付き URL メール
2. **Given** 受信者ログイン + accept、**Then** `invitation.email == user.email` なら `ProjectTrustedUser(status=active)` 作成、不一致は 403 `ERR_EMAIL_MISMATCH`
3. **Given** Trusted + VIEW_MEDIA、**Then** Restricted `allow_media_playback=OFF` でも再生可
4. **Given** Trusted + VIEW_PRECISE_LOCATION なし、**Then** 非メンバー相当の粒度
5. **Given** Trusted + VIEW_PRECISE_LOCATION + 種が H3_RES_2、**Then** HIDDEN 維持（先頭 clamp で解除不能）
6. **Given** `expires_at` 経過、**Then** 403（毎リクエスト DB 参照）
7. **Given** 期限 7 日前、**Then** 本人 + Owner 通知
8. **Given** Owner 延長、**Then** `expires_at` 更新（`granted_at + 1 年` 上限）
9. **Given** Trusted 投票、**Then** `source=trusted_user`
10. **Given** 招待で `VIEW_AUDIT_LOG` 指定、**Then** 422 `ERR_INVALID_TRUSTED_PERMISSION`

### ユーザーストーリー 6 - Taxon-driven Auto-obscure（優先度: P2）

**受け入れシナリオ**:

1. **Given** IUCN `EN`、**Then** Guest Public 閲覧で `H3_RES_5` 以下
2. **Given** MOE RDB `CR` 相当、**Then** Authenticated 閲覧で `H3_RES_2` (HIDDEN)
3. **Given** stricter override、**Then** 即時反映
4. **Given** looser override、**Then** `pending_superuser_approval`、未適用
5. **Given** superuser 承認、**Then** global 置換分岐で有効化
6. **Given** `H3_RES_2` の種 + Trusted `VIEW_PRECISE_LOCATION`、**Then** HIDDEN 維持
7. **Given** Member、**Then** `h3_index_member_resolution`
8. **Given** auto-obscure 適用、**When** CSV export、**Then** 粗化済み hex のみ、`withheld_reason=taxon_sensitivity:EN`

### ユーザーストーリー 7 - 所有権移譲と休眠検出（優先度: P2）

**受け入れシナリオ**:

1. **Given** Owner、**When** Admin に移譲、**Then** 単一 TX + `SELECT FOR UPDATE` + advisory lock で成功、旧 Owner は Admin
2. **Given** Member / Viewer を指定、**Then** 400 `ERR_INVALID_TRANSFER_TARGET`
3. **Given** 並行移譲、**Then** 片方成功、片方 409
4. **Given** `last_login_at < now_utc - 366d`、**Then** 日次バッチで `dormant` + 通知
5. **Given** Owner 削除 + Admin 存在、**Then** 最古参 Admin に自動移譲
6. **Given** Owner 削除 + Admin 不在、**Then** archived
7. **Given** archived、**When** state-changing、**Then** 403
8. **Given** archived、**When** superuser restore（新 Owner 事前指定必須）、**Then** active 復帰、監査記録

### ユーザーストーリー 8 - 2FA 必須化（優先度: P1）

**受け入れシナリオ**:

1. **Given** 新規登録 → 初回ログイン、**Then** 2FA 設定画面強制、QR + バックアップコード 8 個（12 桁 base32、Argon2id hash）
2. **Given** 2FA 未設定、**When** 他ページ、**Then** 強制ダイアログ
3. **Given** ログアウト後再ログイン、**Then** パスワード + TOTP
4. **Given** TOTP 5 失敗/15min、**Then** 6 回目で 429
5. **Given** 10 連続失敗、**Then** 15 分ロック
6. **Given** バックアップコード 3/1hour 超過、**Then** 429
7. **Given** バックアップコードログイン成功、**Then** TOTP 再設定画面、古いバックアップコード全無効化
8. **Given** 2FA reset、**Then** `security_stamp` 更新、全 refresh token 失効
9. **Given** バックアップコード枯渇、**When** サポート申請、**Then** 4 要素確認 + 24h delay + superuser M-of-N、監査
10. **Given** 2FA reset 直後 72h cooldown、**Then** 招待 accept / API key 発行 / DL / EXPORT / Owner 操作は 403

### ユーザーストーリー 9 - API key と scope（優先度: P2）

**受け入れシナリオ**:

1. **Given** Authenticated が発行、`granted_permissions`、`project_id`（user 所有 project のみ）、期限、allowed_ips 指定、**Then** `ek_live_{32 hex}` を 1 度だけ表示、ApiKey レコード作成
2. **Given** user 非所属 project を指定、**Then** 422 `ERR_UNAUTHORIZED_PROJECT`
3. **Given** `scope={EXPORT}` の Admin key、**When** CSV export、**Then** 成功
4. **Given** `scope={DOWNLOAD}` の Admin key、**When** VOTE、**Then** 403 `ERR_SCOPE_DENIED`
5. **Given** user が ProjectMember から削除、**When** 同一 TX、**Then** `project_id` 付き key は即時 revoke（最大遅延 60s）、所有者通知
6. **Given** superuser が API key で superuser 操作、**Then** 403 `ERR_SUPERUSER_API_KEY_FORBIDDEN`
7. **Given** 10 min で 10 件の scope 違反、**Then** 自動 revoke、通知、監査
8. **Given** `allowed_ips` 違反 3 回、**Then** 自動 revoke（別カウンタ）
9. **Given** Guest が programmatic、**Then** 401 `ERR_API_KEY_REQUIRED`
10. **Given** Web UI が first-party session API（Cookie `Path=/web-api/v1/`）、**Then** 通る（CSRF token 必須）

### ユーザーストーリー 10 - ライセンス必須（優先度: P1）

**受け入れシナリオ**:

1. **Given** 作成画面、**When** ライセンス未選択、**Then** UI ボタン非活性 + ツールチップ
2. **Given** API 直叩き未指定、**Then** 422 `ERR_LICENSE_REQUIRED`
3. **Given** CC-BY 選択、**Then** `Project.license="CC-BY"` 保存
4. **Given** Public + CC-BY-NC export、**Then** CSV ヘッダにライセンス + `license_history` URL + `location_generalization` + `withheld_reason`
5. **Given** Owner がライセンス変更、**Then** `ProjectLicenseHistory` 記録、過去 export は不変

### ユーザーストーリー 11 - Permission 細粒度化（優先度: P1）

**受け入れシナリオ**:

1. **Given** Viewer、**When** VIEW_MEDIA / VIEW_DETECTION / SEARCH_WITHIN_PROJECT、**Then** 成功
2. **Given** Viewer、**When** VOTE / DL / EXPORT / COMMENT / CREATE_TAG、**Then** 403
3. **Given** Member、**When** TRAIN_MODEL、**Then** 403
4. **Given** Admin、**When** MANAGE_MEMBERS、**Then** 成功
5. **Given** Admin、**When** MANAGE_TRUSTED、**Then** 403
6. **Given** Admin、**When** 他 Admin 降格、**Then** 成功、監査
7. **Given** Admin が自分に Trusted、**Then** 422
8. **Given** Owner、**When** OVERRIDE_TAXON_SENSITIVITY stricter、**Then** 即時
9. **Given** Owner、**When** OVERRIDE_TAXON_SENSITIVITY looser、**Then** `pending_superuser_approval`

### エッジケース

- 招待 email 不一致 → 403 `ERR_EMAIL_MISMATCH`
- Trusted scope 変更 → 次リクエストで反映
- 招待期限切れ → `expired`、accept 不可
- TOTP 時刻ドリフト ±30 秒
- CSRF トークン不足 first-party → 403、programmatic API は CSRF 不要
- Project PATCH に mutable 外フィールド → 422 `ERR_UNKNOWN_FIELD`
- 所有権移譲二重クリック → idempotency-key で dedupe
- IUCN 2 週間失敗 → 未知種 `H3_RES_7` フェイルセーフ、既知種は維持、superuser alert
- Owner 削除 + 別 Admin 並行移譲 → advisory lock 先勝ち
- Restricted → Public 変更 → 既存 Viewer は Authenticated 相当、UI 警告 + acknowledge
- Public → Restricted 変更 → 進行中セッションは次リクエストで toggle 反映、既存票は immutable
- Public プロジェクトへの Viewer 招待 → 422 `ERR_VIEWER_ON_PUBLIC_PROJECT`
- superuser 1 名落ち → break-glass モード（24h で新 superuser 追加必須、過ぎたら freeze）
- WebAuthn key 両方紛失 → superuser 2 名 M-of-N + 72h delay + 音声確認録音
- wipe guard 3 点不一致 → 即停止、superuser + 創業者承認

---

## 要件 *(必須)*

### 機能要件

**Visibility と主体**

- **FR-001**: プロジェクト Visibility は `PUBLIC` / `RESTRICTED` の 2 値。Private なし
- **FR-002**: 6 主体（Guest / Authenticated / Viewer / Member / Admin / Owner）。Trusted User は Authenticated への capability overlay
- **FR-003**: Owner は `Project.owner_id`、1 プロジェクト 1 人
- **FR-004**: Viewer / Member / Admin は `ProjectMember.role` + `expires_at` (nullable)。Viewer は Restricted 専用、Public では Authenticated 同等に強制正規化（`compute_effective_permissions` と `compute_effective_resolution` の両方で適用）
- **FR-005**: `Project.status` = `active` / `dormant` / `archived`。archived 遷移は Owner 削除時（Admin 不在）または superuser のみ
- **FR-006**: Public への Viewer 新規招待は 422 `ERR_VIEWER_ON_PUBLIC_PROJECT`
- **FR-007**: Restricted → Public 変更時、既存 Viewer は role 保持で Permission が Authenticated 相当。**UI で Owner に「既存 Viewer の権限拡張が起きる」の明示警告 + acknowledge checkbox 必須**

**Permission 決定アルゴリズム**

- **FR-008**: 全エンドポイントは spec「Permission 決定アルゴリズム」の 2 ステージに従う。ステージ 1 で `effective_permissions` を 1 度算出し `request.state` に格納、ステージ 2 はそれを引数で受け取り **DB 再アクセスせず・is_allowed 再帰禁止**
- **FR-008a**: `Action` は Pydantic model (`{name, required_permission: Permission | None, is_mutating, is_superuser_only, is_platform_scope}`)。`@model_validator` で `is_platform_scope=True ⇒ required_permission is None AND is_superuser_only=True` を強制、`is_platform_scope=False ⇒ required_permission is not None` を強制。全エンドポイントが `ACTIONS: dict[str, Action]` カタログに登録、CI 静的解析で未登録 action を検出
- **FR-008b**: Superuser の project-scope action allowlist `SUPERUSER_PROJECT_SCOPE_ALLOWLIST` を spec に定義（`project.restore`, `project.taxon_override.approve_looser` / `reject_looser`, `project.iucn.force_resync`, `project.audit_log.read_platform`）。allowlist 内なら superuser が通常の Permission gate を bypass、allowlist 外は通常経路（Response filter は superuser にも適用、FR-112a）
- **FR-009**: Permission enum は 28 個（Project 権限 26 + User 自己管理 2）
- **FR-010**: `ROLE_PERMISSIONS` を Canonical Matrix に従って定義
- **FR-011**: Response filter は専用 Pydantic `ResponseFilter`、Recording / Detection / Site の全レスポンス経路で通過必須、CI 静的解析で未通過を検出

**Trusted User allowlist**

- **FR-012**: `TRUSTED_ALLOWED_PERMISSIONS` = `{VIEW_MEDIA, VIEW_DETECTION, VIEW_PRECISE_LOCATION, DOWNLOAD, EXPORT, SEARCH_WITHIN_PROJECT, VOTE, COMMENT}` のみ
- **FR-013**: 許可外指定は 422 `ERR_INVALID_TRUSTED_PERMISSION`
- **FR-014**: `active_trusted_capabilities` 評価時に runtime 再フィルタ
- **FR-015**: Trusted 対象は **Authenticated のみ（発行時点の role で判定）**、同プロジェクトの Viewer / Member / Admin / Owner には 422 `ERR_TRUSTED_TARGET_INVALID`
- **FR-015a**: Restricted → Public 変更によって元 Viewer が Authenticated 相当に正規化された場合、**既存の Trusted overlay は有効化される**（再招待不要）。ただし Public 化後に新規 Trusted を発行する場合は FR-015 の「発行時点は Authenticated」要件により通常通り発行可能。逆に Public → Restricted 変更で Viewer だったユーザーに残っていた Trusted は自動 revoke されない（そもそも Viewer に Trusted 発行不可なので発生しない）

**Visibility 別挙動**

- **FR-016**: Public で Guest は `VIEW_PROJECT_METADATA, VIEW_DATASET_LIST, VIEW_MEDIA, VIEW_DETECTION` を保有、生 lat/lng は一切含まない
- **FR-017**: Public で Authenticated は FR-016 + `DOWNLOAD, EXPORT, SEARCH_WITHIN_PROJECT, SEARCH_CROSS_PROJECT, VOTE, COMMENT`
- **FR-017a**: **Guest は Restricted toggle で DOWNLOAD / EXPORT / VOTE / COMMENT / SEARCH_* を取得しない**（Matrix 🟡 は Guest 列では VIEW_MEDIA / VIEW_DETECTION のみ有効）
- **FR-018**: Public では `public_location_precision_h3_res` を無視、非メンバー基準は `H3_RES_9`（Taxon sensitivity による減算は適用）
- **FR-019**: Restricted は Guest / Authenticated に `VIEW_PROJECT_METADATA, VIEW_DATASET_LIST` のみ必須公開
- **FR-020**: Restricted bool トグル: `allow_media_playback`, `allow_detection_view`, `mask_species_in_detection`, `allow_download`, `allow_export`, `allow_voting_and_comments`
- **FR-021**: Restricted 数値トグル `public_location_precision_h3_res`（デフォルト 2）
- **FR-022**: Restricted Viewer 向けトグル `allow_precise_location_to_viewer`（デフォルト false）
- **FR-023**: `restricted_config` は Pydantic `Extra.forbid`、DB JSONB + CHECK、`restricted_config_version` カラム
- **FR-024**: トグル変更は即時に権限ガード反映、検索 index は eventual、監査記録

**SEARCH_CROSS_PROJECT index**

- **FR-025**: SEARCH_CROSS_PROJECT の index は `allow_detection_view=ON` プロジェクトのみ物理的に載せる。**全検索経路（OpenSearch / pgvector / PostgreSQL FTS）で同じ原則を適用**、実装は単一の `SearchGate` エントリポイントを経由
- **FR-025a**: **ON → OFF 切替は 2 段階コミット**: (1) Permission gate / 検索クエリで即時除外（`WHERE allow_detection_view=ON` を search query に追加）、(2) index 物理削除は非同期 Celery。**Permission gate が index truth の source**。3 検索経路それぞれで以下:
  - **OpenSearch**: 検索前に `projects.allow_detection_view=ON` の project_id 集合を取得、filter 句に混入
  - **pgvector**: ANN 検索は post-filter になるため `k * 3` 多めに fetch → `SearchGate` で allow_detection_view フィルタ → k 件返却（approximate 欠損対応）
  - **PostgreSQL FTS**: クエリ直接に `WHERE projects.allow_detection_view=true` 付与
  - CI 静的解析で検索を行う関数が `SearchGate` 経由であることを検証
- **FR-025b**: OFF → ON は index 構築完了後にのみ検索対象化
- **FR-025c**: 検索 API レスポンスは `Cache-Control: private, no-store`、CDN キャッシュ禁止
- **FR-026**: SEARCH_CROSS_PROJECT は project-level aggregation のみ返す、detection 個票は SEARCH_WITHIN_PROJECT で再クエリ

**Location Sensitivity と希少種リスト**

- **FR-027**: Location Sensitivity は H3 resolution 単一軸（`H3_RES_2/5/7/9/15`）
- **FR-028**: Site は `h3_index_member` + `h3_index_member_resolution`（デフォルト 15）保持、**DB に生 lat/lng カラムを定義しない**、設置時入力 lat/lng は即 H3_RES_15 変換して破棄
- **FR-028a**: **Upload 時の生 lat/lng 全経路排除**: WAV / FLAC / MP3 の header GPS EXIF / ID3 GPS をアップロード受付時にストリーム strip（soundfile ベース）、原ファイル保存前。GPS 含有は 202 + monitoring
- **FR-028b**: Celery task payload schema で lat/lng フィールドを禁止、`h3_index_member` 文字列のみ許可（Pydantic validation 強制）
- **FR-028c**: access log / error log は request body の `lat`, `lng`, `latitude`, `longitude`, `gps_*` キーを redact、custom log filter 実装
- **FR-028d**: Site 作成 API は受領直後に H3 変換しメモリから即破棄（`del` + `gc.collect`、または SecureString 相当）。request body は access log から redact
- **FR-028e**: S3 upload は object metadata から GPS 除去する upload lambda（別スコープでも可、NFR 記載）
- **FR-028f**: **生 lat/lng の regression guard を CI 強制**:
  - (1) `alembic/versions/**/*.py` 以下の migration に `latitude` / `longitude` / `lat` / `lng` / `gps_*` を含むカラム定義を検出した場合 fail
  - (2) `apps/api/echoroo/models/**/*.py` の SQLAlchemy `Column(...)` 引数名・属性名で同 regex を検出した場合 fail
  - (3) Pydantic Response model の field 名も同 regex で検出 fail
  - allowlist は `h3_index_*` のみ
  - CI pre-commit hook + main branch の push trigger 両方で実行
- **FR-029**: 公開用 hex は `compute_effective_resolution` の結果で `h3_to_parent` を動的計算
- **FR-030**: Recording / Detection / Site の Pydantic response model に `latitude` / `longitude` フィールドを定義しない。Response filter 必須通過、CI snapshot test
- **FR-031**: Site / Recording テーブルに `latitude` / `longitude` カラムを物理的に作成しない
- **FR-032**: 希少種リストは IUCN Red List API（週次）+ MOE RDB（手動）
- **FR-033**: `ProjectTaxonSensitivityOverride`: `direction=stricter` は即時、`direction=looser` は `approval_status=pending_superuser_approval`
- **FR-034**: looser override 承認後は `compute_effective_resolution` 内で global を置換する分岐（単純 min ではない）
- **FR-035**: HIDDEN (`H3_RES_2`) の判定 semantics:
  - **global sensitivity が `H3_RES_2` の種**は、VIEW_PRECISE_LOCATION や allow_precise_location_to_viewer があっても解除されない（`compute_effective_resolution` の先頭で clamp）
  - **ただし** looser override が承認済みで `resolution != H3_RES_2` に置換されている場合は、global が置換された後の値で HIDDEN 判定し直す（= `H3_RES_2` 以外なら HIDDEN 解除され、Trusted VIEW_PRECISE_LOCATION で member 解像度まで許可）
  - stricter override で `H3_RES_2` に強化された場合は、VIEW_PRECISE_LOCATION があっても HIDDEN 維持
  - これにより「緩和方向は superuser 承認で効く、強化方向は常に効く、HIDDEN は承認なしで勝手に解除されない」の設計意図を満たす
- **FR-036**: IUCN 同期は `IucnSyncAttempt` テーブル記録、2 週連続失敗で **未知種のみ** `H3_RES_7` フェイルセーフ、既知種は維持、superuser critical alert

**投票・コメント**

- **FR-037**: `AnnotationVote.source` = `{member, guest_authenticated, trusted_user}`、`project_role_at_vote` スナップショット、immutable
- **FR-038**: 集計は 3 カウント別
- **FR-039**: 非メンバー / Trusted 票の個票 `user_id` は Owner / Admin のみ。他ロールは null シリアライズ
- **FR-040**: コメントに投稿者バッジ

**Trusted User (capability overlay)**

- **FR-041**: `ProjectTrustedUser`: `id, project_id, user_id, invitation_id, granted_by, granted_at, expires_at, status (active/expired/revoked), granted_permissions, email_at_invitation, email_at_invitation_hash`。pending / token_hash は持たない
- **FR-042**: `granted_permissions` は `TRUSTED_ALLOWED_PERMISSIONS` のサブセット
- **FR-043**: 期限デフォルト 90 日、上限 `granted_at + 1 年`
- **FR-044**: `expires_at` 経過で自動 expired、**capability は JWT に焼かず毎リクエスト DB 参照**
- **FR-045**: 期限 7 日前に本人 + Owner 通知
- **FR-046**: Owner は延長・granted_permissions 変更・revoke 可、上限 `granted_at + 1 年`

**Invitation（Member / Trusted 統一）**

- **FR-047**: `ProjectInvitation` は kind (`member` / `trusted`) 統一、pending / token_hash はここのみ
- **FR-048**: CHECK 制約（`trusted_granted_at` は参照しない、`kind` / `status` の NOT NULL と型検証を含む）:
  ```sql
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
  ```
  （`trusted_duration_seconds` の 31536000 = 365 日、FR-043 の上限 1 年と整合）
- **FR-049**: unique index `(project_id, email, status='pending')` は 1 件のみ（kind 混在不可）
- **FR-050**: Member 招待は Owner / Admin 発行可、Trusted 招待は Owner のみ
- **FR-051**: 招待トークン 256-bit 乱数の SHA-256 hash を `token_hash` 保存、平文はメールのみ
- **FR-052**: 招待 URL は HMAC-SHA256 署名、期限 7 日、one-time use
- **FR-053**: accept は `SELECT FOR UPDATE` + token 消費 + `ProjectMember` or `ProjectTrustedUser` 作成を単一 TX、idempotency-key で二重 accept dedupe
- **FR-054**: accept 時に受信者 email とログインユーザー primary（または認証済み secondary）email の一致（NFKC 正規化 + case-insensitive）、不一致 403
- **FR-055**: 招待フォームは成功 / 失敗 同一レスポンス（enumeration 対策）
- **FR-056**: 招待レート: Owner / Admin 50/h、プロジェクト 200/h

**所有権移譲・休眠**

- **FR-057**: Owner は Admin のみ対象に移譲可、Member / Viewer は不可（事前 Admin 昇格要）
- **FR-058**: `SELECT FOR UPDATE` + `pg_advisory_xact_lock(project_id)` + idempotency-key
- **FR-059**: 監査記録
- **FR-060**: dormant 判定 = `max(users.last_login_at, users.last_first_party_activity_at) < now_utc - 366d`。programmatic API 単独では更新しない。日次バッチ、3/1/1 週段階通知
- **FR-061**: Owner 削除で最古参 Admin に自動移譲、不在なら archived
- **FR-062**: archived は state-changing 403、読み取り可。復帰は superuser のみ + 新 Owner 事前指定必須
- **FR-063**: Project 更新 mutable allowlist (`name, description, visibility, restricted_config, license`) のみ PATCH。`owner_id, status, license_history` は別エンドポイント
- **FR-064**: Project PATCH は Pydantic `Extra.forbid`、未知は 422

**2FA**

- **FR-065**: TOTP 2FA 必須、±30 秒 ドリフト
- **FR-066**: TOTP secret は AES-256-GCM + KMS envelope、鍵別インスタンス、年次 rotation
- **FR-067**: DEK プロセス内 `PROCESS_DEK_CACHE_TTL=300s`、使用後ゼロ化、core dump 無効化
- **FR-068**: バックアップコード 8 個 / 12 桁 base32 / Argon2id (64MiB, 3)、定数時間比較、1 回使用
- **FR-069**: 初回ログインで 2FA 設定強制
- **FR-070**: TOTP 5/15min、10 連続で 15 分ロック。バックアップ 3/1hour 別枠
- **FR-071**: 2FA 有効化 / リセット / パスワード変更で `security_stamp` 更新、全 refresh token 失効
- **FR-072**: バックアップコード枯渇リセットは 4 要素 + 24h delay + superuser M-of-N + 監査
- **FR-073**: 2FA reset 72h cooldown。禁止: 招待 accept、API key 操作、DL、EXPORT、プロジェクト作成・参加、ownership transfer、member 管理

**API key と scope**

- **FR-074**: `ApiKey`: `id, user_id, prefix, hashed_secret (SHA-256 + salt), granted_permissions, project_id (nullable), allowed_ips, expires_at (default 1yr, max 2yr), created_at, revoked_at, revoked_reason, last_used_at (1 分 debounce)`
- **FR-075**: user 非所属 project 指定は 422
- **FR-076**: 離脱時自動 revoke
- **FR-076a**: 自動 revoke は `ProjectMember DELETE` の **同一 TX 内で実行**（DB trigger または SQLAlchemy ORM event hook）。TX 失敗時は outbox pattern で最大遅延 60s 以内に revoke
- **FR-076b**: revoke 確定で `platform_audit_log` に `action=api_key_auto_revoked_on_member_removal`
- **FR-076c**: SC-009 に「離脱 → 次リクエスト（最大 60s 以内）で該当 API key が 403」の E2E 検証を含める
- **FR-076d**: outbox 遅延 SLO: p95 ≤ 10s、p99 ≤ 60s。`outbox_queue_depth > 100` または `oldest_pending_age > 60s` で PagerDuty alert。worker 5 分停止時は fallback: `ApiKey.enforce_at_auth_time=true`（認証時に ProjectMember 整合性を直接 DB 照会して強制）
- **FR-077**: `/api/v1/*` (programmatic) は API key 必須、`/web-api/v1/*` (first-party session) は Cookie (`Path=/web-api/v1/`) + CSRF
- **FR-078**: 認証失敗: programmatic は 401 `ERR_API_KEY_REQUIRED / ERR_API_KEY_INVALID`、first-party は 401 + redirect
- **FR-079**: effective = `Role permissions ∩ granted_permissions`、scope 違反 403 `ERR_SCOPE_DENIED`
- **FR-080**: 10 min で 10 件の scope 違反 → 自動 revoke + 通知 + 監査
- **FR-081**: `allowed_ips` 違反 3 回で自動 revoke（別カウンタ）
- **FR-082**: scope 別レート（read-only 600/min、vote 60/min、upload 10/min）Redis token bucket
- **FR-083**: 推奨 rotation 90 日、UI warning バナー、上限 2 年
- **FR-084**: superuser 操作（archived restore / 2FA reset / looser override 承認 / IUCN 再同期 / wipe）は API key 不可、Web UI + 2FA + hardware key + IP allowlist のみ

**ライセンス**

- **FR-085**: 作成時 CC 必須、未選択 422
- **FR-086**: export にライセンス + `license_history` URL + `location_generalization` + `withheld_reason` 同梱
- **FR-087**: ライセンス変更は `ProjectLicenseHistory` 別テーブル記録、過去 export は不変

**監査ログ（raw PII なし設計）**

- **FR-088**: `project_audit_log`: プロジェクト内完結イベント。閲覧は Owner / Admin / superuser
- **FR-089**: `platform_audit_log`: ユーザーアカウント / 認証 / API key / superuser 操作。閲覧は superuser のみ
- **FR-090**: 両テーブルカラム: `id, actor_user_id_hash (keyed hash), project_id (nullable), action, detail (JSONB), request_id, ip_hash (keyed hash), user_agent_hash (keyed hash), before, after, prev_hash, row_hash, created_at`。**raw の actor_user_id / ip / user_agent カラムは存在しない**
- **FR-091**: 書き込み時に keyed hash (`HMAC-SHA256(pii_hash_key, raw)`) のみ保存。これにより GDPR 削除要求が発生しても監査ログの UPDATE / DELETE は不要で append-only を維持
- **FR-091a**: `detail` / `before` / `after` JSONB の PII 扱いを 2 層で強制:
  - **(a) build-time CI lint**: application コードで `audit_log.write(detail={...})` 呼び出しのリテラル引数に PII key 名（`email`, `ip`, `user_agent`, `phone`, `lat`, `lng`, `gps`, `address`, `display_name`）を検出した場合 fail
  - **(b) runtime `AuditLogSanitizer`**: 保存直前に Pydantic model を通し、`detail` / `before` / `after` dict を deep-walk、PII regex match + Unicode 同形異字正規化 + URL-decode + base64 decode を適用、match した value を **`{"hash": HMAC(pii_hash_key, raw), "hash_version": "v1", "redacted": true}`** に置換
  - **(c) 許容例外**: `user_id` (UUID) は FR-105 で「統計整合性のため保持」と定義済みのため生値 OK。ただし `before.owner_id` / `after.owner_id` のような操作対象 user_id は生値で保存可、操作対象の email / IP は hash のみ
  - unit test で sanitizer bypass 10+ シナリオ（nested dict、array 内、Unicode 同形異字、URL-encoded、base64、null byte）を検証
- **FR-091b**: `pii_hash_key` は **application DB user が参照不可**。KMS に保存、application からは `kms:GenerateMac` API 経由のみ使用（key material は app process memory に展開しない）。Redis / env var / config file に書かない。SQLi / app compromise 時も key 平文は漏れない設計。漏洩検知は KMS audit log の `GenerateMac` 呼び出し異常増で実施
- **FR-092**: `row_hash = HMAC-SHA256(chain_key, prev_hash || canonical_row)`、chain_key は KMS 管理
- **FR-093**: 並列 INSERT 対策: `SERIALIZABLE` + `pg_advisory_xact_lock('audit_log_chain')` または outbox pattern
- **FR-094**: PostgreSQL REVOKE で application DB user を INSERT のみに制限、superuser DB ロールも INSERT 以外不可
- **FR-095**: 週次で chain 再計算 hash を S3 Object Lock に append-only、genesis は別 bucket、3 年保持
- **FR-096**: AuditLog 閲覧操作もメタログ記録

**セキュリティ横断**

- **FR-097**: state-changing first-party は `SameSite=Strict; Path=/web-api/v1/; Secure; HttpOnly` Cookie + `X-CSRF-Token` double-submit
- **FR-098**: CSRF token = `HMAC-SHA256(session_secret, session_id || issued_at)`、session 単位、rotation 時更新、定数時間比較
- **FR-099**: programmatic API は Authorization: Bearer のみ、Cookie を受け入れない
- **FR-100**: Mass assignment 防御: 全 update 系に Pydantic `Extra.forbid` + mutable allowlist model
- **FR-101**: メール送信: (a) 受信者 email は **envelope は RFC 5321、header / address parse は RFC 5322** で役割分離検証、制御文字完全拒否、`email-validator` ライブラリ使用、NFKC 正規化。(b) 本文テンプレートは全 user-generated 文字列を HTML escape、ヘッダに user 文字列を入れない。(c) 招待 URL は `https://echoroo.app/invite/{token}` 固定、`?next=` 不受理
- **FR-102**: Security headers 全レスポンス付与
- **FR-103**: Password NIST SP 800-63B 準拠
- **FR-104**: 新デバイス / IP ログイン通知
- **FR-105**: ユーザー削除時: `users.email / display_name` 匿名化、`user_id` は統計整合のため保持。**監査ログは raw PII を持たない設計なので null 化不要**
- **FR-106**: 受諾 / 拒否 / 期限切れから 30 日後、`ProjectInvitation.email` null 化、`email_hash` 別カラム保持
- **FR-107**: pending expire の招待は受信者要求で削除可
- **FR-108**: `ProjectTrustedUser.email_at_invitation` は revoked / expired になった 90 日後に null 化、`email_at_invitation_hash` 別カラム保持
- **FR-109**: DSR エンドポイント（JSON export）
- **FR-110**: Recording upload acknowledge checkbox（人声混入注意）

**Superuser セキュリティ**

- **FR-111**: Superuser 必須:
  - TOTP 2FA + WebAuthn hardware key 2 本（primary + backup 物理別保管）
  - 管理操作は fixed IP allowlist (CIDR)
  - 最低 **3 名** 常時維持（単独禁止）
  - 追加 / 削除は既存 2 名 M-of-N 承認
  - 全操作は `platform_audit_log` に `action=superuser:*`
  - programmatic API 経由で superuser 操作不可
  - 1 名退職時は 72h 緊急 break-glass モード（残 1 名 + 創業者指定別チャンネル 2 要素）、24h 以内追加必須、過ぎたら freeze
  - WebAuthn 両紛失時: 他 superuser 2 名 M-of-N + 72h delay + 本人確認 + 音声録音
- **FR-111a**: superuser 数の遷移を厳格に監査: `platform_audit_log` に `action=superuser:count_changed, detail={from, to, event}` を **同一 TX 内で記録**。`count` カラムを snapshot。3→2 の遷移で 72h break-glass タイマー開始、2→1 で即時 freeze + 創業者 break-glass チャンネル自動通知、**1→0 の DELETE は DB trigger で block**（最後の 1 名の DELETE は creator_founder 手動 override のみ許可）
- **FR-112**: 初期 superuser は CLI interactive で TOTP + 一時パスワード発行、24h 以内に Web UI で hardware key 登録、未登録なら自動 revoke
- **FR-112a**: Response filter は Superuser にも適用（raw 値を通常 UI で見せない）、raw が法的に必要な場合は別 runbook で DB 直 access

**マイグレーション**

- **FR-113**: 既存データ全削除、Alembic 単一 migration
- **FR-114**: Wipe 2 度目実行不可ガード 3 点一致: (a) DB `wipe_guard` テーブル、(b) `alembic_version` 特定 revision、(c) S3 Object Lock compliance mode の genesis marker file。1 点でも「実行済み」なら abort、superuser 2 名 + 創業者承認要

### 非機能要件

- **NFR-001**: 認証 + Permission 判定のみで p95 < 30ms、DB クエリ数 p95 ≤ 4。request-scope キャッシュ許容、プロセス間キャッシュ禁止
- **NFR-001a**: **Recording list / Detection list (N 件) の Permission 処理**: (a) 1 リクエストあたり認証 + role + trusted で最大 4 クエリ (N 非依存)、(b) N 行の Taxon sensitivity は `SELECT ... WHERE taxon_id IN (...)` の 1 クエリ preload、(c) 合計 p95 ≤ 5 クエリ + 1 業務クエリ (list 取得)。ステージ 2 `compute_effective_resolution` は preload dict を引数受取、DB 追加アクセス禁止
- **NFR-002**: OWASP Top 10 準拠
- **NFR-003**: `h3_index_member_resolution` デフォルト `H3_RES_15`
- **NFR-004**: Recording list / Detection list 100 件の権限込み応答 p95 < 800ms
- **NFR-005**: メール失敗 Celery リトライ（最大 3 回、指数バックオフ）
- **NFR-006**: `SystemSettings` で期限 / 閾値 / レート値を override 可能、変更は superuser のみ + 監査 + Slack 通知
- **NFR-007**: 鍵ローテ SLA 表を満たす
- **NFR-008**: Permission 判定 request-scope キャッシュ許容、プロセス間禁止
- **NFR-008a**: **long-lived 接続（WebSocket / SSE / streaming response）では request-scope キャッシュを使わず、5 分ごとに `active_trusted_capabilities` / `security_stamp` を再評価**。Trusted revoke / 2FA reset / security_stamp 更新イベントを Redis pub/sub で broadcast、該当接続は次 event loop で切断
- **NFR-009**: Redis (Celery broker) は TLS + AUTH + ACL、worker と app を分離、Celery event は監査対象

### 鍵ローテ SLA

| 対象 | 鍵 | 周期 | 旧鍵保持 | 手順 |
|---|---|---|---|---|
| TOTP secret | KMS CMK + DEK | CMK 年次、DEK 2^30 or 90 日 | 月次 rewrap | Runbook |
| API key hash salt | user-local | 不変 | — | 漏洩時全 revoke + 再発行 |
| 招待 HMAC | envelope | 90 日 | 14 日 grace (k_old / k_new) | Runbook |
| 監査ログ chain_key | KMS CMK | 年次 | 切替で genesis に記録 | 月次チェック |
| PII hash key | KMS CMK | **不変**（hash 整合性、漏洩時は v2 カラム追加で 90 日 dual-write 後に v1 drop） | — | runbook |
| CSRF session_secret | process-memory | プロセス再起動 | — | K8s rolling |

### 開発プロセス要件（TDD）

- **PR-001**: TDD Red → Green → Refactor
- **PR-002**: 権限系 (FR-008〜FR-046, FR-074〜FR-084) は unit / contract / integration 3 層で Canonical Matrix パラメトリック全探索
- **PR-003**: E2E は P1 (US1 / US2 / US3 / US4 / US8 / US10 / US11) + セキュリティ重要 (SC-004 / SC-005 / SC-009) のみ必須、P2 は integration で十分
- **PR-004**: 権限系モジュールは mutation testing score 80% 以上を CI 強制
- **PR-005**: カバレッジ: 権限系 95% 以上、他 85% 以上、分岐カバレッジ
- **PR-006**: PR テンプレに Red フェーズ CI ログ URL 記入欄
- **PR-007**: ネガティブセキュリティテスト 75+ シナリオ（`tests/security/`）:
  - 認証: 2FA bypass / brute force / token replay / refresh reuse / cooldown bypass
  - 認可: 水平・垂直昇格、BOLA / IDOR、Trusted allowlist runtime bypass、Viewer 権限拡大、superuser API key 禁止、`is_allowed` 非再帰（ステージ 2 の DB 再アクセスゼロ）
  - 招待: email mismatch / 並行 accept / expired accept / XSS / injection / open redirect / enumeration
  - Auto-obscure: 生 lat/lng が全経路 (API / export / log / Celery / S3) で不在、Viewer precise 制限、HIDDEN 不可逆、upload EXIF strip
  - 検索 leak: ON→OFF 即時除外、OFF→ON 構築完了前の除外、Cache-Control no-store
  - 監査: SERIALIZABLE chain integrity、REVOKE 強制、メタログ、PII hash 整合性 rotation 時
  - CSRF / mass assignment / Clickjacking
  - race: ownership / 削除並行 / 二重 accept
  - 鍵: HMAC 2 鍵並行 / DEK rewrap / CMK 誤削除防止 / PII hash v1→v2 dual-write
  - API key: 離脱同一 TX revoke (60s 以内)、180 日経過 scope 縮退、allowed_ips 違反別カウンタ
  - Superuser: break-glass / WebAuthn 両紛失 / programmatic 禁止

### 状態遷移

#### Project.status

```
  [created] → active → (Owner inactive 366d) → dormant → (Owner re-login) → active
                 │                                    │
                 │                                    └ (Owner deleted, admin exists) → active (new owner)
                 │                                    │
                 │                                    └ (Owner deleted, no admin) → archived
                 │
                 └ (Owner deleted, admin exists) → active (new owner)
                 │
                 └ (Owner deleted, no admin) → archived ← (superuser restore with new owner specified) → active
```

- `active`: 全操作可 / `dormant`: バッジのみ、編集可 / `archived`: state-changing 403
- archived 遷移: Owner 削除時（Admin 不在）のみ、他 path なし
- archived 復帰: superuser 限定、新 Owner 事前指定必須

#### ProjectInvitation.status

```
  [created] → pending → (accept, email match, token valid) → accepted → DB record 生成
                  │
                  └ (email mismatch) → pending (403、カウンタ不変)
                  │
                  └ (decline) → declined
                  │
                  └ (expires_at) → expired
                  │
                  └ (owner revoke) → revoked
```

#### ProjectTrustedUser.status

```
  (Invitation accepted) → active → (expires_at) → expired
                             │
                             └ (owner revoke) → revoked
                             │
                             └ (owner extend) → active (new expires_at)
                             │
                             └ (owner edit permissions, allowlist 再検証) → active (new granted_permissions)
```

### 主要エンティティ

- **Project**: `id, name, description, owner_id, visibility, license, restricted_config (JSONB), restricted_config_version, status, dormant_since, archived_since, created_at, updated_at`
- **ProjectLicenseHistory**: `id, project_id, old_license, new_license, changed_at, changed_by`
- **ProjectMember**: `project_id, user_id, role, joined_at, expires_at (nullable)`
- **ProjectInvitation**: `id, project_id, kind, email, email_hash, role (member only), granted_permissions (trusted only), trusted_duration_seconds (trusted only), token_hash, invited_by_id, expires_at, accepted_at, status`
- **ProjectTrustedUser**: `id, project_id, user_id, invitation_id, granted_by, granted_at, expires_at, status, granted_permissions, email_at_invitation, email_at_invitation_hash`
- **ProjectTaxonSensitivityOverride**: `id, project_id, taxon_id, sensitivity_h3_res, direction, approval_status, requested_by, approved_by, approved_at`
- **Site**: `id, project_id, name, h3_index_member, h3_index_member_resolution`。**latitude / longitude カラムは存在しない**
- **Recording** / **Detection**: Site / Recording を FK で参照、独自 lat/lng を持たない
- **TaxonSensitivity**: `taxon_id, source (iucn/moe_rdb/manual), category, sensitivity_h3_res, updated_at`
- **IucnSyncAttempt**: `id, started_at, finished_at, status, error_detail, synced_count`
- **AnnotationVote**: 既存 + `source, project_role_at_vote`
- **AnnotationComment**: `source`
- **User**: 既存 + `two_factor_enabled, two_factor_secret_encrypted, two_factor_backup_codes_hashed, security_stamp, last_login_at, last_first_party_activity_at, registered_timezone, deleted_at`
- **ApiKey**: FR-074 参照
- **Superuser**: `user_id, added_by, added_at, webauthn_credentials, allowed_ips`
- **SuperuserApprovalRequest**: `id, action, detail, requested_by, approvals, status`
- **ProjectAuditLog**, **PlatformAuditLog**: FR-088〜096、**raw PII カラムなし**
- **SystemSettings**: `key, value, updated_at, updated_by`
- **DekRewrapFailure**: `id, table_name, row_id, attempted_at, error_detail`

---

## 成功基準 *(必須)*

- **SC-001**: 全プロジェクト系エンドポイントが Permission guard 通過、CI 静的解析
- **SC-002**: US1 Playwright E2E
- **SC-003**: Restricted トグル全組合せ (bool 6 + `allow_precise_location_to_viewer`) × ON/OFF を unit + integration で網羅
- **SC-004**: US5 Trusted (発行 / accept / use / expire / revoke / allowlist 違反) **E2E**
- **SC-005**: Taxon-driven auto-obscure の 3 層検証（unit / integration / **E2E**）
- **SC-006**: 2FA 込みログイン成功率 95% 以上（30 日、1000 試行）
- **SC-007**: ownership 移譲 race 1000 並行で ちょうど 1 件成功
- **SC-008**: 休眠検出バッチ翌日通知
- **SC-009**: API key scope 違反 → 403、10 件で revoke、**離脱 60s 以内自動 revoke** を **E2E**
- **SC-010**: ライセンス必須 UI + API
- **SC-011**: `tests/security/` 75+ ネガティブシナリオ Green
- **SC-012**: 権限系 mutation score 80% 以上
- **SC-013**: 権限系カバレッジ 95% 以上、他 85% 以上
- **SC-014**: 監査ログ hash chain 改ざん検知、REVOKE 強制、100 並列 INSERT chain 整合性、PII hash key rotation 時 v1/v2 併存整合性
- **SC-015**: 認証 + 権限判定 p95 < 30ms、クエリ数 p95 ≤ 4、Recording list 100 件でも p95 ≤ 5 (NFR-001a)
- **SC-016**: Recording / Detection / Site 全レスポンスに生 lat/lng 不在を JSON schema fuzzer で 50+ エンドポイント検証
- **SC-017**: Viewer が希少種 precise location 不可（`allow_precise_location_to_viewer=false` 時）
- **SC-018**: SEARCH index ON→OFF 切替直後（1s 以内）の leak なし、OFF→ON 構築完了前のヒットなしを **OpenSearch / pgvector / PostgreSQL FTS の 3 経路それぞれで検証**
- **SC-019**: migration / ORM / Pydantic に `latitude` / `longitude` / `lat` / `lng` / `gps_*` を含むカラム・field 追加を試みると CI lint で fail（FR-028f 規制、新規 PR で regression 防止）
- **SC-020**: 監査ログ JSONB `before` / `after` / `detail` に任意 payload で PII 混入（nested dict / array / Unicode 同形異字 / URL-encoded / base64）を試みると `AuditLogSanitizer` が自動 hash 置換（FR-091a 規制、10+ bypass シナリオ）
- **SC-021**: ApiKey 離脱 → 次リクエスト 60s 以内 revoke、outbox worker 10 分停止時は fallback で強制（FR-076a/076d）
- **SC-022**: superuser count 1→0 の DELETE が DB trigger で block、creator_founder override のみ許可（FR-111a）

---

## 非目標（Out of Scope）

- Darwin Core フル実装
- アノテーション単位の公開設定
- ユーザーブロック
- プロジェクト内データ単位ライセンス
- SSE / WebSocket の toggle 即時 push
- 既存データマイグレーション
- 非 TOTP 型の一般ユーザー 2FA
- 組織単位権限管理
- 録音中の人声自動検出 / マスキング
- 生 lat/lng 保存

---

## 前提条件

- プレローンチ、互換性不要
- SpecKit: plan → tasks → analyse → implement
- Rev.3.1 は 3 回目 3者レビュー残論点を pin-point 反映、security 差分レビューで最終確認
- AWS KMS で envelope encryption
- Resend (SMTP)、RFC 5321 / 5322 検証
- IUCN Red List API credentials 別途調達、HTTPS + certificate pinning

---

## 運用 Runbook

### 既存データ wipe 手順（リリース前 1 回のみ）

1. **赤字警告**: リリース前 1 回のみ。2 度目は絶対不可
2. **S3 は 7 日間 versioning で復元可能**であることを明記
3. 実行には superuser 2 名 M-of-N + DB 接続先明示確認 (`SELECT current_database(), inet_server_addr()`)
4. `wipe_guard` 3 点一致チェック: (a) DB table, (b) alembic revision, (c) S3 Object Lock genesis marker
5. 1 点でも「実行済み」なら即停止、superuser + 創業者承認要
6. 全テーブル `TRUNCATE ... CASCADE`、S3 `recordings/` prefix は lifecycle 任せ（7 日）
7. Alembic `upgrade head`
8. 初期 superuser 作成: CLI interactive で TOTP + 一時パスワード発行、24h 以内に Web UI で WebAuthn hardware key 2 本登録
9. IUCN + MOE RDB 初回同期
10. Smoke test（Public、Guest、2FA、Trusted allowlist、監査 chain）
11. `wipe_guard` 3 点に記録、以降 block
12. ロールバック不能宣言

### IUCN 同期失敗時

- バッチ失敗 → `IucnSyncAttempt` 記録 + Sentry
- 2 週連続 → 未知種のみ `H3_RES_7`、既知維持、PagerDuty alert
- 手動で credentials + 再同期
- TLS certificate pinning (SPKI hash) 検証
- sanity check: 前回比 10% 以上の sensitivity 緩和で abort + superuser alert

### 2FA リセットサポート

1. サポート受付
2. 本人確認 4 要素（登録メール + 現パスワード + 最終ログイン時刻 + 最後発行 API key prefix）。API key 発行歴がない場合は 3 要素必須 + 代替（登録時 IP 履歴最終 5 件）
3. 24h delay（緊急時 superuser 2 名 M-of-N で skip 可）
4. `POST /admin/users/{id}/reset-2fa` 実行、監査記録
5. 72h cooldown 通知、緊急解除は superuser M-of-N + 4 要素 + 24h delay で短縮可

### archived 復帰

1. Owner または Admin が申請
2. superuser が **新 Owner 事前決定**（UI ドロップダウン必須、default なし）
3. 復活メンバー allowlist 明示、選ばれなかった旧メンバーは `removed_at` 設定
4. `POST /admin/projects/{id}/restore?new_owner_user_id={uuid}` 実行
5. 全旧メンバー通知

### 鍵ローテ月次チェックリスト

1. KMS CMK 有効化状態
2. DEK rewrap バッチ成功ログ (`DekRewrapFailure` 空)
3. 古い CMK バージョン残レコード減少
4. HMAC k_old 削除日カレンダー登録
5. PII hash key 検証サンプリング

### HMAC 鍵ローテ

- 90 日ごと `k_new`、14 日 `k_old` / `k_new` 両方 verify、新規は `k_new`、14 日後 `k_old` 削除、KMS 管理、superuser 2 名 M-of-N

### DEK rewrap バッチ

- 月次、対象: `users.two_factor_secret_encrypted` など、`dek_version` カラムで partial 許容
- chunk size 1000、TX 分割、失敗は `DekRewrapFailure` に記録 + superuser 通知
- 完了判定: `WHERE dek_version < current_version` カウント 0 → 旧 DEK 廃棄

### CMK 削除

- deletion window 最低 30 日（Terraform lint で enforcement）
- 実行には superuser 2 名 M-of-N + DR runbook 確認
- 誤削除時: 別リージョン backup から復元

### PII hash key 漏洩時

1. 新鍵 `k_new` 生成、`actor_user_id_hash_v2` カラム追加
2. 新イベントから両方書き込み (dual-write)
3. 90 日後に v1 drop、旧鍵破棄
4. chain 検証は v1 hash_row をそのまま使う（chain_key は別管理で整合性維持）

### API key salt 漏洩時

- 全 API key を強制 revoke、全ユーザー通知、新 salt + 新 key 発行、監査記録

### Superuser 空白期間（1 名落ち）

- 72h 緊急 break-glass: 残 1 名 + 創業者指定別チャンネル（Resend 管理アカウント等）の 2 要素
- 24h 以内に新 superuser 追加必須、過ぎたら全 superuser 操作 freeze
- break-glass 発動は別種の `platform_audit_log` イベント
