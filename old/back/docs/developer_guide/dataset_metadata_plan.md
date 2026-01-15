# Dataset & Metadata Architecture Plan (v3)

## 🎯 目的

プロジェクトベースのメンバーシップ管理を中心に据え、データセットとメタデータ（録音機、設置場所、ライセンス）を明確に関連付けた管理・検索・API連携を実現する。位置情報にはUber H3セルを採用し、プライバシーとセキュリティを両立させた公開設定を提供する。

---

## 📊 スキーマダイアグラム

```mermaid
erDiagram
    PROJECTS ||--o{ PROJECT_MEMBERS : "has members"
    USERS ||--o{ PROJECT_MEMBERS : "participates in"
    PROJECTS ||--o{ DATASET : includes
    SITES ||--o{ DATASET : "primary site"
    RECORDERS ||--o{ DATASET : "primary recorder"
    LICENSES ||--o{ DATASET : applies
    SITES ||--o{ SITE_IMAGES : "has images"
    PROJECTS ||--o{ ANNOTATION_PROJECTS : "manages"
    DATASET ||--o{ ANNOTATION_PROJECTS : "source"
    DATASET ||--o{ RECORDINGS : contains
    DATASET ||--|| DATETIME_PATTERNS : "has pattern"

    PROJECTS {
        string project_id PK "auto-generated, immutable"
        string project_name
        string url
        string description
        text target_taxa
        string admin_name
        string admin_email
        boolean is_active
    }

    PROJECT_MEMBERS {
        int id PK
        string project_id FK
        int user_id FK
        enum role "manager | member"
    }

    USERS {
        int id PK
        string username
        string email
        boolean is_superuser
    }

    DATASET {
        int id PK
        uuid uuid UNIQUE
        string name UNIQUE
        string audio_dir
        enum visibility "public | restricted"
        string project_id FK "NOT NULL"
        string primary_site_id FK
        string primary_recorder_id FK
        string license_id FK
        string doi
        text note
    }

    ANNOTATION_PROJECTS {
        int id PK
        uuid uuid UNIQUE
        string name
        enum visibility "inherited from dataset"
        int dataset_id FK
        string project_id FK
    }

    RECORDINGS {
        int id PK
        uuid uuid UNIQUE
        string path
        int dataset_id FK
        timestamp datetime "NOT NULL after parse"
        string h3_index "inherited from site"
        enum datetime_parse_status "pending | success | failed"
        text datetime_parse_error
    }

    DATETIME_PATTERNS {
        int id PK
        int dataset_id FK UNIQUE
        enum pattern_type "strptime | regex"
        string pattern
        string sample_filename
        timestamp sample_result
    }

    RECORDERS {
        string recorder_id PK
        string manufacturer
        string recorder_name
        string version
        int usage_count "computed"
    }

    SITES {
        string site_id PK
        string site_name
        string h3_index "NOT NULL, H3 cell index"
        string project_id FK
    }

    SITE_IMAGES {
        string site_image_id PK
        string site_id FK
        string site_image_path
        int display_order
    }

    LICENSES {
        string license_id PK
        string license_name
        string license_link
        int usage_count "computed"
    }
```

---

## 🧩 定義されるエンティティ

### `projects`

| フィールド名        | 型         | 制約        | 説明                       | 例                                      |
| --------------- | --------- | ---------- | ------------------------ | -------------------------------------- |
| `project_id`    | character | PK, AUTO   | 自動生成される不変のプロジェクトID      | `proj_a1b2c3d4`                        |
| `project_name`  | character | NOT NULL   | プロジェクト名                 | `SPARROW Field Test`                   |
| `url`           | character | NULLABLE   | プロジェクトURL               | `https://example.org/sparrow`          |
| `description`   | text      | NULLABLE   | 概要                       | `Field validation of SPARROW devices.` |
| `target_taxa`   | text      | NULLABLE   | 対象分類群                    | `birds, insects`                       |
| `admin_name`    | character | NULLABLE   | 管理者名                     | `Ryotaro Okamoto`                      |
| `admin_email`   | character | NULLABLE   | 管理者メールアドレス              | `okamoto@example.jp`                   |
| `is_active`     | boolean   | DEFAULT TRUE | 実施中かどうか                  | `TRUE`                                 |

> **設計方針:**
> * グループ（`groups`）への依存を完全に削除。プロジェクトが独立してメンバーシップを管理。
> * `project_id` は自動生成され、変更不可。
> * リストは全ユーザーに公開されるが、詳細・編集・削除はプロジェクトマネージャーに制限。

---

### `project_members`

| フィールド名       | 型      | 制約                 | 説明                   | 例   |
| -------------- | ------ | ------------------ | -------------------- | --- |
| `id`           | integer | PK                 | 内部ID                 | `1` |
| `project_id`   | character | FK, NOT NULL      | プロジェクトID            | `proj_a1b2c3d4` |
| `user_id`      | integer | FK, NOT NULL      | ユーザーID              | `42` |
| `role`         | enum   | NOT NULL           | 役割（`manager` / `member`） | `manager` |

> **設計方針:**
> * `(project_id, user_id)` のユニーク制約を設定。
> * `manager` はプロジェクト・データセット・APの作成・編集・削除が可能。
> * `member` は割り当てられたAPでの作業のみ可能。
> * スーパーユーザーはプロジェクトを作成し、初期マネージャーを割り当て可能。

---

### `sites`

| フィールド名   | 型         | 制約         | 説明              | 例                    |
| -------- | --------- | ---------- | --------------- | -------------------- |
| `site_id` | character | PK         | サイトID           | `tateyama01`         |
| `site_name` | character | NOT NULL   | サイト名            | `Murodo Ridge`       |
| `h3_index` | character | NOT NULL   | Uber H3セル識別子    | `8830800ffffffff`    |
| `project_id` | character | FK, NULLABLE | 関連プロジェクトID（任意） | `proj_a1b2c3d4`      |

> **変更点:**
> * `lat` / `lon` を削除し、`h3_index` に置き換え。
> * H3解像度は設定可能なデフォルト値を使用（例: res 7 or 8）。
> * APIレスポンスには表示用の中心座標を含める（H3セルから計算）。
> * サイト作成・更新にはプロジェクトマネージャー権限が必要。
> * サイトリストは公開されるが、`restricted` データセットに関連するサイトの詳細はメンバーにのみ表示。

---

### `site_images`

| フィールド名        | 型         | 制約         | 説明                    | 例                            |
| --------------- | --------- | ---------- | --------------------- | ---------------------------- |
| `site_image_id` | character | PK         | 画像ID                  | `tateyama01_img01`           |
| `site_id`       | character | FK, NOT NULL | サイトID（FK）             | `tateyama01`                 |
| `site_image_path` | character | NOT NULL   | ファイルパス（メタデータルートからの相対） | `sites/tateyama01/photo.jpg` |
| `display_order` | integer   | DEFAULT 0  | 表示順                   | `1`                          |

> **方針:**
> * 保存先はファイルシステム固定。
> * `site_image_path` はアプリ設定のメタデータストレージルートからの相対パス。
> * `display_order` で表示順を制御可能。

---

### `recorders`

| フィールド名     | 型         | 制約       | 説明           | 例                    |
| ------------- | --------- | -------- | ------------ | -------------------- |
| `recorder_id` | character | PK       | 録音機の一意識別子    | `sm4`                |
| `manufacturer` | character | NOT NULL | メーカー名        | `Wildlife Acoustics` |
| `recorder_name` | character | NOT NULL | 製品名          | `Song Meter SM4`     |
| `version`     | character | NULLABLE | バージョン情報      | `1.2.0`              |

> **方針:**
> * シンプルな参照テーブル。初期シードとして AudioMoth / Song Meter シリーズを登録。
> * 追加は全ユーザー可能。削除はスーパーユーザーのみ、かつ未使用時のみ。
> * `usage_count` は計算フィールド（`datasets` との関連数）。

---

### `licenses`

| フィールド名     | 型         | 制約       | 説明        | 例                                              |
| ------------- | --------- | -------- | --------- | ---------------------------------------------- |
| `license_id`  | character | PK       | ライセンスID   | `CCBY4`                                        |
| `license_name` | character | NOT NULL | ライセンス名    | `Creative Commons Attribution 4.0`             |
| `license_link` | character | NULLABLE | ライセンスURL  | `https://creativecommons.org/licenses/by/4.0/` |

> **方針:**
> * 初期シードとして CC-BY, CC0, CC-BY-NC を登録。
> * 追加は全ユーザー可能。削除はスーパーユーザーのみ、かつ未使用時のみ。
> * データセット単位で統一されたライセンスを適用（録音単位での上書きは禁止）。

---

### `datasets`（既存テーブルの拡張）

| フィールド名                | 型         | 制約              | 説明                              | 例                                 |
| ---------------------- | --------- | --------------- | ------------------------------- | --------------------------------- |
| `id`                   | integer   | PK              | 既存の主キー（変更なし）                  | `1`                               |
| `uuid`                 | uuid      | UNIQUE          | 既存のUUID（変更なし）                  | `f7b2…`                           |
| `name`                 | character | UNIQUE          | 既存のデータセット名（変更なし）             | `Tateyama 2025 Summer Recordings` |
| `audio_dir`            | character | NOT NULL        | 既存の音声ディレクトリ（アプリ設定基準の相対パス）  | `datasets/tateyama_2025/audio`    |
| `visibility`           | enum      | NOT NULL        | **更新**: `public` / `restricted` のみ | `public`                          |
| `project_id`           | character | FK, **NOT NULL** | **更新**: 必須項目に変更                | `proj_a1b2c3d4`                   |
| `primary_site_id`      | character | FK, NULLABLE    | 新規: 主要サイトID（FK）                | `tateyama01`                      |
| `primary_recorder_id`  | character | FK, NULLABLE    | 新規: 使用録音機ID（FK）                | `sm4`                             |
| `license_id`           | character | FK, NULLABLE    | 新規: 適用ライセンスID（FK）             | `CCBY4`                           |
| `doi`                  | character | NULLABLE        | 新規: DOI                          | `10.5281/zenodo.1234567`          |
| `note`                 | text      | NULLABLE        | 新規: 備考                           | `Includes cicada chorus data.`    |

> **重要な変更:**
> * `visibility` から `PRIVATE` を削除。`public` または `restricted` のみ。
> * `project_id` を必須（NOT NULL）に変更。すべてのデータセットはプロジェクトに所属。
> * `owner_group_id` を削除（グループ依存を排除）。
> * 権限チェックはプロジェクトメンバーシップベースに変更。

---

### `annotation_projects`（既存テーブルの拡張）

| フィールド名       | 型      | 制約         | 説明                            | 例               |
| -------------- | ------ | ---------- | ----------------------------- | --------------- |
| `id`           | integer | PK         | 既存の主キー                        | `1`             |
| `uuid`         | uuid   | UNIQUE     | 既存のUUID                       | `a1b2…`         |
| `name`         | character | NOT NULL   | AP名                           | `Bird Survey Q1` |
| `visibility`   | enum   | NOT NULL   | **更新**: データセットから継承           | `restricted`    |
| `dataset_id`   | integer | FK, NOT NULL | ソースデータセットID                   | `42`            |
| `project_id`   | character | FK, NOT NULL | **新規**: 関連プロジェクトID（dataset経由） | `proj_a1b2c3d4` |

> **設計方針:**
> * APの `visibility` はソースデータセットから自動継承。`restricted` データセットは `restricted` APのみ生成可能。
> * CRUD操作はプロジェクトマネージャーに制限。
> * メンバーは割り当てられたAPでのアノテーション作業のみ可能。

---

### `recordings`（既存テーブルの拡張）

| フィールド名                | 型         | 制約              | 説明                              | 例                                 |
| ---------------------- | --------- | --------------- | ------------------------------- | --------------------------------- |
| `id`                   | integer   | PK              | 既存の主キー                  | `1`                               |
| `uuid`                 | uuid      | UNIQUE          | 既存のUUID                  | `e4f2…`                           |
| `path`                 | character | NOT NULL        | 既存の音声ファイルパス             | `datasets/tateyama/20250601_120000.wav` |
| `dataset_id`           | integer   | FK, NOT NULL    | 既存のデータセットID                | `42`            |
| `datetime`             | timestamp | **NOT NULL**    | **更新**: 録音日時（パース後必須）        | `2025-06-01 12:00:00` |
| `h3_index`             | character | NULLABLE        | **新規**: 録音位置のH3セル（サイトから継承） | `8830800ffffffff` |
| `datetime_parse_status` | enum     | DEFAULT 'pending' | **新規**: パース状態（`pending` / `success` / `failed`） | `success` |
| `datetime_parse_error`  | text     | NULLABLE        | **新規**: パースエラーメッセージ        | `Invalid date format in filename` |

> **重要な変更:**
> * `datetime` を必須（NOT NULL）に変更。データセット登録後、ファイル名からパースする。
> * `h3_index` を追加。基本的にはデータセットの `primary_site_id` から継承するが、個別設定も可能。
> * `datetime_parse_status` でパース処理の進捗を管理。
> * パースエラーがある場合は `datetime_parse_error` にメッセージを格納し、ユーザーに再設定を促す。

> **datetime パース戦略:**
> 1. データセット作成時、ユーザーにファイル名のdatetimeパターンを指定してもらう（後述のUI参照）。
> 2. バックグラウンドジョブで全録音ファイルのファイル名をパースし、`datetime` を更新。
> 3. パース成功時は `datetime_parse_status = 'success'`、失敗時は `'failed'` + エラーメッセージ。
> 4. エラーがある場合、ユーザーに通知し、パターンの再設定を促す。

---

### `datetime_patterns`（新規テーブル）

| フィールド名          | 型         | 制約              | 説明                              | 例                                 |
| ----------------- | --------- | --------------- | ------------------------------- | --------------------------------- |
| `id`              | integer   | PK              | 内部ID                  | `1`                               |
| `dataset_id`      | integer   | FK, NOT NULL, UNIQUE | データセットID（1対1関係）  | `42`            |
| `pattern_type`    | enum      | NOT NULL        | パターンタイプ（`strptime` / `regex`） | `strptime` |
| `pattern`         | character | NOT NULL        | パターン文字列             | `%Y%m%d_%H%M%S` |
| `sample_filename` | character | NOT NULL        | サンプルファイル名（検証用）        | `20250601_120000.wav` |
| `sample_result`   | timestamp | NOT NULL        | サンプルのパース結果（検証用）      | `2025-06-01 12:00:00` |

> **設計方針:**
> * 1つのデータセットに1つのdatetimeパターンを紐付け（UNIQUE制約）。
> * `pattern_type = 'strptime'` の場合、Pythonの `datetime.strptime` 形式を使用。
> * `pattern_type = 'regex'` の場合、正規表現 + 名前付きグループ（`(?P<year>…)`）を使用。
> * サンプルファイル名とパース結果を保存し、パターン変更時の検証に使用。

---

## 🔗 関係性まとめ

| 関係                            | 説明                                  |
| ----------------------------- | ----------------------------------- |
| `projects` ↔ `users`          | 多対多（`project_members` 経由）         |
| `projects` → `datasets`        | 1対多（1つのプロジェクトに複数データセット）         |
| `projects` → `annotation_projects` | 1対多（1つのプロジェクトに複数AP）              |
| `sites` → `datasets`           | 1対多（1サイトに複数データセット）               |
| `recorders` → `datasets`       | 1対多（1機種で複数データセット）               |
| `licenses` → `datasets`        | 1対多（1ライセンスを複数データセットで共有）       |
| `sites` → `site_images`        | 1対多（1サイトに複数画像）                    |
| `datasets` → `annotation_projects` | 1対多（1データセットから複数AP）               |
| `datasets` → `recordings`      | 1対多（1データセットに複数録音ファイル）           |
| `datasets` ↔ `datetime_patterns` | 1対1（1データセットに1つのパターン）            |

---

## 🔍 データセット横断検索機能

### 概要
ユーザーが位置（H3セル範囲）・日付範囲・時刻範囲を指定し、複数のデータセットにまたがって録音ファイルを検索できる機能。

### 検索対象
- **Public データセット**: すべてのユーザーが検索可能
- **Restricted データセット**: 自分が所属するプロジェクトのもののみ検索可能

### 検索条件
| 条件       | 説明                              | 入力方法                       |
| -------- | ------------------------------- | -------------------------- |
| 位置範囲     | H3セル範囲（複数セル選択、または中心点+半径）      | 地図上でのインタラクティブ選択          |
| 日付範囲     | 開始日〜終了日                         | Date range picker          |
| 時刻範囲     | 開始時刻〜終了時刻（日をまたぐ指定も可能）         | Time range slider          |
| プロジェクト   | 特定プロジェクトに絞り込み（複数選択可）          | Multi-select dropdown      |
| サイト      | 特定サイトに絞り込み（複数選択可）             | Multi-select dropdown      |
| 録音機      | 特定録音機に絞り込み（複数選択可）             | Multi-select dropdown      |
| 分類群      | 対象分類群でフィルタ（プロジェクトのtarget_taxa） | Tag filter                 |

### API設計

**エンドポイント**: `GET /api/v1/recordings/search`

**クエリパラメータ**:
```
h3_cells: string[]          # H3セルのリスト（カンマ区切り）
h3_center: string           # 中心H3セル（radius と併用）
h3_radius: integer          # 中心からの範囲（H3セル数）
date_start: date            # 開始日（YYYY-MM-DD）
date_end: date              # 終了日（YYYY-MM-DD）
time_start: time            # 開始時刻（HH:MM:SS）
time_end: time              # 終了時刻（HH:MM:SS）
project_ids: string[]       # プロジェクトID（カンマ区切り）
site_ids: string[]          # サイトID（カンマ区切り）
recorder_ids: string[]      # 録音機ID（カンマ区切り）
target_taxa: string[]       # 対象分類群（カンマ区切り）
limit: integer              # 結果数制限（デフォルト100）
offset: integer             # ページネーション用オフセット
```

**レスポンス例**:
```json
{
  "total": 1543,
  "limit": 100,
  "offset": 0,
  "results": [
    {
      "recording_id": 12345,
      "uuid": "e4f2...",
      "path": "datasets/tateyama/20250601_120000.wav",
      "datetime": "2025-06-01T12:00:00Z",
      "h3_index": "8830800ffffffff",
      "center_lat": 36.5748,
      "center_lon": 137.6042,
      "dataset": {
        "id": 42,
        "name": "Tateyama 2025 Summer",
        "visibility": "public",
        "project_id": "proj_tateyama2025"
      },
      "site": {
        "site_id": "tateyama01",
        "site_name": "Murodo Ridge"
      },
      "recorder": {
        "recorder_id": "audiomoth",
        "manufacturer": "Open Acoustic Devices",
        "recorder_name": "AudioMoth"
      }
    }
    // ... more results
  ]
}
```

### バックエンド実装のポイント

1. **権限フィルタリング**
   ```python
   # Public + 自分のプロジェクトのRestricted
   accessible_datasets = (
       db.query(Dataset)
       .filter(
           or_(
               Dataset.visibility == "public",
               and_(
                   Dataset.visibility == "restricted",
                   Dataset.project_id.in_(user_project_ids)
               )
           )
       )
   )
   ```

2. **H3範囲検索**
   ```python
   # h3_center + h3_radius の場合
   import h3
   center_cell = request.h3_center
   target_cells = h3.k_ring(center_cell, request.h3_radius)

   # 複数セル指定の場合
   query = query.filter(Recording.h3_index.in_(target_cells))
   ```

3. **時刻範囲検索**
   ```python
   # 時刻のみ（日をまたぐ場合も対応）
   if time_start < time_end:
       query = query.filter(
           extract('hour', Recording.datetime) * 60 + extract('minute', Recording.datetime)
           .between(time_start_minutes, time_end_minutes)
       )
   else:  # 日をまたぐ場合（例: 22:00 - 06:00）
       query = query.filter(
           or_(
               extract('hour', Recording.datetime) * 60 + extract('minute', Recording.datetime) >= time_start_minutes,
               extract('hour', Recording.datetime) * 60 + extract('minute', Recording.datetime) <= time_end_minutes
           )
       )
   ```

4. **インデックス最適化**
   - `recordings.datetime` にB-treeインデックス
   - `recordings.h3_index` にB-treeインデックス
   - `recordings.dataset_id` に外部キーインデックス（既存）
   - 複合インデックス: `(h3_index, datetime)` で範囲クエリを高速化

---

## 🧱 実装上の注意点

### 1️⃣ マイグレーション設計

* 既存の `groups` テーブルとの関連を削除。
* `datasets.owner_group_id` を削除し、`project_id` を NOT NULL に変更。
* `datasets.visibility` enum から `PRIVATE` を削除。
* `sites` テーブルから `lat`, `lon` を削除し、`h3_index` を追加（NOT NULL）。
* `project_members` テーブルを新規作成（`project_id`, `user_id`, `role`）。
* `datetime_patterns` テーブルを新規作成（データセットとのUNIQUE FK）。
* `recordings` テーブルに以下を追加：
  * `h3_index` (NULLABLE, character)
  * `datetime_parse_status` (enum, DEFAULT 'pending')
  * `datetime_parse_error` (text, NULLABLE)
* `recordings.datetime` を NOT NULL に変更（マイグレーション時は既存データを保護）。
* 以下のインデックスを作成：
  * `CREATE INDEX idx_recordings_datetime ON recordings(datetime);`
  * `CREATE INDEX idx_recordings_h3_index ON recordings(h3_index);`
  * `CREATE INDEX idx_recordings_h3_datetime ON recordings(h3_index, datetime);`
* Alembic で `licenses` に CC-BY / CC0 / CC-BY-NC を自動投入。
* `recorders` に AudioMoth / Song Meter シリーズを初期登録。
* 外部キー制約は `ON DELETE SET NULL` または `ON DELETE RESTRICT` を設定。

### 2️⃣ 認証・認可の変更

* **従来**: グループメンバーシップでアクセス制御。
* **新方式**: プロジェクトメンバーシップでアクセス制御。
  * `manager`: プロジェクト・データセット・AP・サイトの作成・編集・削除。
  * `member`: 割り当てられたAPでの作業のみ。
  * `superuser`: すべての操作 + プロジェクト作成 + メタデータ削除。

### 3️⃣ H3 統合

* Python側: `h3` ライブラリを使用。
* フロントエンド側: `h3-js` + Leaflet でH3セルの可視化。
* デフォルト解像度は設定ファイルで管理（例: `H3_RESOLUTION=7`）。
* APIレスポンスには `site.center_lat` / `site.center_lon` を含める（H3セルから計算）。

### 4️⃣ API / ORM 実装

* ORM（SQLAlchemy）で `relationship()` を定義し、`joinedload()` による eager loading を有効化。
* `/datasets` API に階層的フィルタリングを追加（`project_id`, `site_id`, `recorder_id`, `license_id`）。
* `/sites` API に `project_id` フィルタを追加。
* `restricted` データセット/APはプロジェクトメンバーのみアクセス可能。
* **新規エンドポイント**:
  * `POST /datasets/{id}/datetime_pattern` - datetimeパターンを設定・更新
  * `POST /datasets/{id}/parse_datetime` - バックグラウンドジョブでdatetimeをパース
  * `GET /datasets/{id}/datetime_parse_status` - パース進捗状況を取得
  * `GET /recordings/search` - データセット横断検索（位置・日時範囲）
* **Recording APIの拡張**:
  * レスポンスに `h3_index`, `center_lat`, `center_lon` を含める
  * `datetime_parse_status` を含め、エラーがあればフラグ表示

### 5️⃣ 管理UI

* プロジェクト管理画面: メタデータ編集 + メンバー管理タブ。
* サイト管理画面: H3マップピッカー + 画像ギャラリー管理。
* データセット作成フォーム: プロジェクト・サイト・録音機・ライセンスのセレクタ。
* メタデータ参照テーブル管理: 使用数表示、未使用時のみ削除可能。
* **Datetime パーサーUI**:
  * データセット詳細ページに「Parse Datetime」ボタンを配置
  * パターン設定モーダル（後述の UI.md 参照）:
    1. サンプルファイル名の表示（データセット内の最初の数ファイル）
    2. パターン入力（strptime形式 or regex）
    3. リアルタイムバリデーション（サンプルでパース結果を表示）
    4. 確定後、バックグラウンドジョブでバッチパース
  * パース進捗表示（プログレスバー、成功/失敗数）
  * エラーリスト表示（ファイル名とエラーメッセージ）
  * パターン再設定ボタン
* **横断検索UI**:
  * 独立した「Recording Search」ページ
  * H3マップで範囲選択
  * 日付・時刻範囲ピッカー
  * 階層的フィルタパネル（プロジェクト・サイト・録音機）
  * 検索結果を地図上にプロット + テーブル表示

### 6️⃣ バリデーション

* `project_id` は必須（NOT NULL）。
* `h3_index` は有効なH3セルであることを検証（`h3.h3_is_valid()`）。
* DOI形式のバリデーション（正規表現: `^10\.\d{4,}/\S+$`）。
* ライセンス混在防止のため、`recording` テーブルへの `license_id` は追加しない。
* **Datetimeパターンバリデーション**:
  * strptime形式: `datetime.strptime(sample, pattern)` でテスト
  * regex形式: 必須グループ `(?P<year>...)`, `(?P<month>...)`, `(?P<day>...)`, `(?P<hour>...)`, `(?P<minute>...)` を検証
  * パターン変更時はサンプルで必ずテストし、結果をユーザーに表示

### 7️⃣ テスト & 検証

* Alembic マイグレーション実行後、新テーブル・カラム・enumの変更を確認。
* `project_members` 経由の権限チェックが正常に機能することを確認。
* H3セルのバリデーションと中心座標計算のユニットテスト。
* `restricted` データセットへのアクセス制御のインテグレーションテスト。
* **Datetimeパース機能のテスト**:
  * 様々なファイル名形式（AudioMoth, Song Meter, SPARROW等）のパースをテスト
  * strptime形式とregex形式の両方をテスト
  * エラーハンドリング（不正なパターン、マッチしないファイル名）のテスト
  * バックグラウンドジョブの実行とステータス更新のテスト
* **横断検索機能のテスト**:
  * H3範囲検索（k_ring）の正確性をテスト
  * 時刻範囲検索（日をまたぐケース含む）のテスト
  * 権限フィルタリング（public + 自分のproject）のテスト
  * ページネーションとパフォーマンス（大量データ）のテスト
  * インデックスの効果測定（EXPLAIN ANALYZEで確認）

---

## ✅ まとめ

| 項目                 | 採用方針                         |
| ------------------ | ---------------------------- |
| グループベースの権限管理       | ❌ 削除（プロジェクトメンバーシップに移行）    |
| `PRIVATE` 可視性      | ❌ 削除（`public` / `restricted` のみ） |
| サイト位置情報            | ✅ H3セル（`lat`/`lon` 削除）       |
| `project_id` 必須化   | ✅ 採用（NOT NULL）               |
| 複数サイト・複数レコーダー対応    | ❌ 不採用（単一に限定）               |
| サイト画像保存先           | ✅ ファイルシステム                  |
| ライセンス混在            | ❌ 禁止（データセット単位で統一）          |
| 既存データ移行            | ❌ 対象外（新規プロジェクト）            |
| **Datetime パース機能**  | ✅ 採用（strptime/regex、バックグラウンドジョブ） |
| **横断検索機能**         | ✅ 採用（H3範囲、日時範囲、権限フィルタ）    |
| **Recording位置情報**   | ✅ サイトのH3セルを継承（個別設定も可能）    |

---

この設計は PLAN.MD の方針に完全に準拠し、さらにdatetimeパースとデータセット横断検索機能を追加しています。追加の検討事項や懸念があれば共有してください。
