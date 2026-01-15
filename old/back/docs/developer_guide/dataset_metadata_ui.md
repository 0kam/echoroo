# Dataset Metadata UI Design (v3)

## 概要

PLAN.MD に従った、プロジェクトメンバーシップベースの新しいUI設計。H3セルによる位置管理、階層的フィルタリング、可視性制御を中心とした管理インターフェースを提供する。

---

## 🎨 共通コンポーネント

### H3 Map Picker
**目的**: サイトの位置をH3セルで指定するインタラクティブなマップコンポーネント

**技術スタック**:
- Leaflet (地図表示)
- h3-js (H3セル計算・可視化)

**機能**:
- クリックまたはドラッグでH3セルを選択
- 選択されたH3セルをハイライト表示（六角形ポリゴン）
- 双方向バインディング: マップ選択 ⇔ `h3_index` フォームフィールド
- H3セルの中心座標を計算して表示（読み取り専用）
- 解像度切り替え（設定で指定されたデフォルト値を使用）
- 既存サイトの表示（プロジェクトフィルタ付き）

**UI要素**:
- Map canvas (Leaflet)
- H3 index input (text, read-only, copyable)
- Center coordinates display (lat/lon, read-only)
- Resolution selector (optional, defaults to config value)

---

### Hierarchical Filter Panel
**目的**: プロジェクト → サイト → データセットの階層的フィルタリング

**機能**:
- Multi-select filter chips for:
  - Projects
  - Sites (filtered by selected projects)
  - Recorders
  - Licenses
  - Visibility (`public` / `restricted`)
- Clear all / Clear individual filters
- Active filter count badge
- Collapsible sections for each filter category

**UI要素**:
- Accordion-style filter groups
- Searchable dropdowns for each category
- Active filter chips with remove (×) buttons
- "Clear all filters" button

---

### Visibility Badge Component
**目的**: データセット/APの可視性を視覚的に示す

**バリエーション**:
- **Public**: 緑色バッジ、地球アイコン、"Public"
- **Restricted**: オレンジ色バッジ、鍵アイコン、"Restricted"

**使用箇所**:
- データセット一覧カード
- データセット詳細ページ
- AP一覧カード
- サイト詳細ページ（関連データセットリスト）

---

### Metadata Link Card
**目的**: データセット詳細ページで関連メタデータをサマリー表示

**表示項目**:
- Project name (クリックでプロジェクト詳細へ)
- Primary site (クリックでサイト詳細へ、H3セルの中心座標を表示)
- Primary recorder (メーカー + モデル名)
- License (名前 + リンク)
- DOI (あればコピー可能な形式で表示)
- Note (折り畳み可能)

**アクション**:
- "Edit metadata" ボタン (project manager のみ表示)
- Quick jump links to metadata admin pages

---

## 🔧 Admin Console

### 1. Project Admin

#### Project List View
**権限**: 全ユーザーが閲覧可能、作成はスーパーユーザーのみ

**UI要素**:
- Table/card view with columns:
  - Project ID (auto-generated, non-editable)
  - Project name
  - Target taxa (chips)
  - Active status (toggle badge)
  - Member count
  - Dataset count
- "Create Project" button (superuser only)
- Search by name/ID
- Filter by active status

#### Project Detail Page
**権限**: プロジェクトマネージャーが編集可能、メンバーは閲覧のみ

**タブ構成**:
1. **Overview**
   - Edit form for metadata (name, URL, description, target_taxa, admin contact, is_active)
   - URL preview with link validation
   - Target taxa: tag input (comma-separated or chips)
   - Active toggle with confirmation dialog

2. **Members**
   - Member list table:
     - User name/email
     - Role (manager / member) with role badge
     - Added date
     - Actions: Change role, Remove (confirm dialog)
   - "Add Member" button (opens user search modal)
   - Role selector in add modal
   - Prevent removing last manager (validation)

3. **Datasets**
   - Read-only list of datasets belonging to this project
   - Quick links to dataset detail pages
   - "Create Dataset" button (navigates to dataset creation with project pre-selected)

4. **Annotation Projects**
   - Read-only list of APs belonging to this project
   - Quick links to AP detail pages

#### Project Creation Dialog (Superuser only)
**Form fields**:
- Project name (required)
- Description (optional, multiline)
- Initial manager(s) (user search/select, multi-select)
- Submit → auto-generates `project_id` and creates project

---

### 2. Site Admin

#### Site List View
**権限**: 全ユーザーが閲覧可能、作成・編集はプロジェクトマネージャーのみ

**UI要素**:
- Card view with:
  - Site ID + name
  - H3 cell (with small map preview or hex icon)
  - Center coordinates (calculated)
  - Related project (if any)
  - Image count
  - Linked dataset count
- "Create Site" button (project manager only)
- Hierarchical filter: filter by project
- Search by site ID/name

#### Site Create/Edit Drawer
**権限**: プロジェクトマネージャーのみ

**Form sections**:
1. **Basic Info**
   - Site ID (text input, required, unique validation)
   - Site name (text input, required)
   - Related project (dropdown, optional)

2. **Location** (H3 Map Picker)
   - Interactive map for H3 cell selection
   - H3 index display (read-only, copyable)
   - Center coordinates display (read-only)

3. **Images** (Image Gallery Manager)
   - Upload button (multi-file support)
   - Image preview grid with drag-to-reorder
   - Display order controls
   - Delete button per image (confirm dialog)
   - File path display (relative to metadata root)

**Validation**:
- Site ID uniqueness check (async)
- H3 index validity check
- Image file type validation (jpg, png, webp)

---

### 3. Dataset Admin

#### Dataset List View
**権限**: 全ユーザーが閲覧可能（restricted は project member のみ）

**UI要素**:
- Table view with columns:
  - Name
  - Project (with link)
  - Site (with link)
  - Recorder
  - License
  - Visibility badge
  - Dataset actions (edit/delete for project manager)
- Hierarchical filter panel:
  - Project → Site → Recorder → License → Visibility
- "Create Dataset" button (project manager only)
- Search by name

#### Dataset Detail View
**権限**: Public は全ユーザー、Restricted はプロジェクトメンバーのみ

**表示要素**:
- Dataset name + UUID
- Visibility badge (prominent)
- Metadata Link Card (project, site, recorder, license, DOI, note)
- Audio directory path (read-only)
- Recording count
- **Datetime parse status section**:
  - Parse status badge (`pending` / `success` / `failed`)
  - Success rate (e.g., "1234/1250 files parsed successfully")
  - "Parse Datetime" button (opens datetime parser modal, project manager only)
  - Error list link (if failures exist, shows failed files)
- **Run foundation models section** (replaces legacy Species Detection page):
  - Two-column card layout placed beneath datetime parsing
  - **Executed Models panel**:
    - Lists each foundation model entry (BirdNET v2.4, Perch v2.0, future versions) with status badge (`Not run`, `Last run <timestamp>`, `Running`)
    - Action menu per row: View last run, Download outputs, Rerun model
  - **Species summary panel**:
    - Table of recent detections aggregated from the latest run (per model)
    - Columns: GBIF scientific name, BirdNET-provided Japanese common name (if available), clip count, avg confidence
    - Tag badges reuse the annotation tag component keyed by `gbif_taxon_id`
    - "Create annotation project from this result" button opens the existing AP wizard seeded with the selected run outputs
  - Footer CTA bar: "Run foundation models" primary button (project manager only) plus helper text about runtime and shared compute budgeting
  - Run history link navigates to an inline drawer showing all previous runs with statuses and download buttons
- Related APs list
- "Edit Dataset" button (project manager only)
- "Create Annotation Project" button (project manager only)

#### Dataset Create/Edit Modal
**権限**: プロジェクトマネージャーのみ

**Form fields**:
- Name (required, unique validation)
- Audio directory (path input with validation)
- **Project** (dropdown, required, filterable)
  - On-the-fly creation option (opens nested modal, superuser only)
- **Primary Site** (dropdown, optional)
  - Search by site ID/name
  - Quick jump to site gallery (opens in new tab)
  - Filtered by selected project (if any)
- **Primary Recorder** (dropdown, optional)
  - Grouped by manufacturer
  - Display format: `{manufacturer} - {recorder_name} ({version})`
- **License** (dropdown, optional)
  - Display format: `{license_name}`
  - Show license link on hover
- **Visibility** (radio buttons, required)
  - `public` (default)
  - `restricted`
  - Helper text explaining implications
- **DOI** (text input, optional)
  - Format validation (regex: `10.\d{4,}/.*`)
  - Inline helper text with example
- **Note** (multiline textarea, optional)

**Validation**:
- Highlight missing optional metadata after save
- Show toast nudging to fill project/site/license when empty
- Enforce DOI format using regex

---

#### Datetime Parser Modal
**権限**: プロジェクトマネージャーのみ

**目的**: データセット内の全録音ファイルのファイル名からdatetimeをパースする

**表示フロー**:

1. **サンプルファイル表示**
   - データセット内の最初の5-10ファイル名を表示
   - ファイル名例: `20250601_120000.wav`, `SPARROW_2025-06-01_12-00-00.wav`

2. **パターン選択**
   - Pattern type selector (radio buttons):
     - `strptime` (Python datetime format)
     - `regex` (正規表現 with named groups)
   - Pattern input field with placeholder examples:
     - strptime: `%Y%m%d_%H%M%S`
     - regex: `(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})_(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})`
   - Helper text with format documentation link

3. **リアルタイムバリデーション**
   - Pattern入力時、サンプルファイルに対してリアルタイムでパース実行
   - 各サンプルファイルの下にパース結果を表示:
     - 成功: 緑色チェック + パース結果 (`2025-06-01 12:00:00`)
     - 失敗: 赤色×マーク + エラーメッセージ
   - 全サンプルが成功した場合のみ「Start Parse」ボタンを有効化

4. **バッチパース実行**
   - "Start Parse" ボタンクリック → バックグラウンドジョブ開始
   - モーダルがプログレスビューに切り替わる:
     - プログレスバー (パース済み / 全体)
     - リアルタイム統計:
       - Total files: 1250
       - Parsed: 1234 (98.7%)
       - Failed: 16 (1.3%)
     - "Cancel" ボタン（ジョブをキャンセル）
     - "Close" ボタン（バックグラウンド続行でモーダルを閉じる）

5. **エラー表示**
   - パース完了後、失敗したファイルのリストを表示:
     - ファイル名
     - エラーメッセージ
     - "Copy error list" ボタン（CSV形式でコピー）
   - "Retry with different pattern" ボタン → ステップ2に戻る
   - "Ignore errors and keep results" ボタン → 成功したファイルのみ保存

**UI要素**:
- Multi-step wizard (5 steps)
- Pattern input with syntax highlighting
- Live validation results table
- Progress bar component
- Error list table with CSV export

**技術ノート**:
- バックグラウンドジョブはCelery or RQ使用
- WebSocketまたはpollingでリアルタイム進捗更新
- パターンとサンプル結果は `datetime_patterns` テーブルに保存

---

### 4. Annotation Projects Admin

#### AP List View
**権限**: Public APは全ユーザー、Restricted APはプロジェクトメンバーのみ

**UI要素**:
- Table view with columns:
  - AP name
  - Source dataset (with link)
  - Project (with link)
  - Visibility badge (inherited from dataset)
  - Assigned members count
  - AP actions (edit/delete for project manager)
- Filter by project/dataset/visibility
- "Create Annotation Project" button (project manager only)

#### AP Create/Edit Modal
**権限**: プロジェクトマネージャーのみ

**Form fields**:
- AP name (required)
- Source dataset (dropdown, required)
  - Visibility hint: "This AP will inherit visibility: {dataset.visibility}"
  - If dataset is `restricted`, show warning badge
- Project (auto-filled from dataset, read-only)
- Description (optional, multiline)
- Assign members (multi-select from project members)

**Validation**:
- Restricted dataset → restricted AP (auto-enforced, non-editable)
- Prevent creating AP from dataset not in same project

---

### 5. Metadata Lookups Admin

#### Recorder Admin
**権限**: 全ユーザーが閲覧・追加可能、削除はスーパーユーザーのみ（未使用時のみ）

**UI要素**:
- CRUD table with columns:
  - Recorder ID
  - Manufacturer
  - Recorder Name
  - Version
  - Usage count (computed, shows number of linked datasets)
  - Actions: Edit, Delete (disabled if usage_count > 0 or not superuser)
- "Add Recorder" button
- Search by ID/name
- Inline validation for duplicate IDs

**Create/Edit Form**:
- Recorder ID (text input, required, unique validation)
- Manufacturer (text input, required)
- Recorder Name (text input, required)
- Version (text input, optional)

**Deletion**:
- Disabled button with tooltip if usage_count > 0: "Cannot delete: used by {N} datasets"
- Superuser-only action
- Confirmation dialog

---

#### License Admin
**権限**: 全ユーザーが閲覧可能、追加は全ユーザー可能、削除はスーパーユーザーのみ（未使用時のみ）

**UI要素**:
- Read-only seeded list (CC-BY, CC0, CC-BY-NC)
- Allow future additions with "Add License" button
- Table with columns:
  - License ID
  - License Name
  - License Link (clickable)
  - Usage count
  - Actions: Edit, Delete (disabled if usage_count > 0 or not superuser)

**Create/Edit Form**:
- License ID (text input, required, unique validation)
- License Name (text input, required)
- License Link (URL input, optional, link validation)

**Deletion**: Same rules as Recorder Admin

---

## 🌐 Public / Member Views

### Dataset Explorer (Public)
**権限**: 全ユーザー（restricted は非表示またはロックアイコン表示）

**UI要素**:
- Hierarchical filter panel (project → site → license → visibility)
- Dataset card grid with:
  - Dataset name
  - Visibility badge
  - Project name
  - Site name (with H3 center coordinates)
  - Recorder + License badges
  - "View Details" button
- Restricted dataset visuals:
  - Lock icon overlay
  - Disabled "View Details" button
  - Tooltip: "Access restricted to project members"
  - No audio preview

---

### Site Detail View (Public)
**権限**: 全ユーザー（restrictedデータセットの詳細はメンバーのみ）

**UI要素**:
- Site name + ID
- H3 hex overlay on map (Leaflet + h3-js)
- Center coordinates display
- Image gallery (carousel or grid)
- Related project info
- Linked datasets list:
  - Public datasets: clickable cards
  - Restricted datasets (non-member): lock icon, no link
- Linked APs list (same visibility rules)

---

### Member-only Features
**対象**: プロジェクトメンバー（manager + member）

**追加機能**:
- Access to restricted datasets/APs in their projects
- Dataset detail page shows full metadata and audio previews
- AP assignment notifications
- Member dashboard showing assigned tasks

---

### Cross-Dataset Recording Search
**権限**: 全ユーザー（Public + 自分のプロジェクトのRestricted）

**目的**: 複数のデータセットにまたがって、位置・日付・時刻を指定して録音ファイルを検索する

**ページ構成**:

#### Search Panel (左サイドバー、collapsible)

1. **Spatial Filter**
   - H3 map picker (Leaflet + h3-js)
   - 選択モード切り替え:
     - **Multi-cell selection**: クリックで複数セル選択（Ctrl+クリックで追加/削除）
     - **Center + radius**: 中心セルをクリック + 半径スライダー（0-10セル）
   - 選択されたH3セルをハイライト表示（青色半透明）
   - 選択セル数の表示（例: "5 cells selected"）
   - "Clear selection" ボタン

2. **Temporal Filter**
   - **Date range picker**:
     - Start date / End date inputs
     - Calendar widget
     - Quick select buttons: "Last 7 days", "Last 30 days", "This year"
   - **Time-of-day slider**:
     - Dual-handle range slider (00:00 - 24:00)
     - Supports wraparound (e.g., 22:00 - 06:00)
     - Visual indicator for wraparound selection
     - Timezone display (based on site or user setting)

3. **Metadata Filters** (hierarchical, collapsible)
   - **Projects** (multi-select dropdown)
   - **Sites** (filtered by selected projects)
   - **Recorders** (multi-select dropdown, grouped by manufacturer)
   - **Target Taxa** (tag input, filtered by project target_taxa)
   - Active filter chips with remove buttons
   - "Clear all filters" button

4. **Search Controls**
   - "Search" button (primary action)
   - "Reset all" button
   - Results limit selector (100 / 500 / 1000)

#### Results Display (右メインエリア)

**デュアルビュー**:

1. **Map View**
   - Leaflet map showing recording locations as markers
   - Marker clustering for dense areas
   - Color-coded by dataset or project
   - Click marker → show recording info popup:
     - Filename
     - Datetime
     - Dataset name (with link)
     - Site name (with link)
     - Audio player (inline preview)
   - Selected H3 cells overlay (reference)

2. **Table View**
   - Paginated data table with columns:
     - Filename (truncated, full path in tooltip)
     - Datetime (sortable)
     - Site (with link)
     - Dataset (with visibility badge + link)
     - Project (with link)
     - Recorder
     - Actions: "Play", "Download", "View Details"
   - Column visibility toggle
   - Export buttons: CSV, JSON
   - Sort by datetime (default), filename, site, dataset

**View Toggle**:
- Tab selector: "Map View" / "Table View" / "Split View"
- Split view: map on left, table on right (responsive)

#### Empty States & Feedback

- **No search executed**: "Configure filters and click Search to find recordings"
- **No results**: "No recordings found matching your criteria. Try adjusting filters."
- **Loading state**: Skeleton loaders for map markers and table rows
- **Permission message**: Restricted datasets show lock icon with tooltip: "Restricted to project members"

**UI要素**:
- Collapsible sidebar (responsive, drawer on mobile)
- H3 map with dual selection modes
- Dual-handle time slider with wraparound
- Hierarchical filter chips
- Paginated data table with column controls
- Map marker clustering
- Inline audio player component

**技術ノート**:
- API endpoint: `GET /api/v1/recordings/search`
- Pagination: server-side (limit/offset)
- H3 range calculation: client-side (h3-js) → send cell list to API
- Marker clustering: Leaflet.markercluster
- Audio player: HTML5 audio with streaming support

**UX考慮事項**:
- 検索実行前は結果を表示しない（空の状態メッセージ）
- 大量結果の場合、最初の1000件のみマップに表示（パフォーマンス）
- テーブルビューは全結果をページネーション
- 時刻範囲の日をまたぐ選択は視覚的にわかりやすく表示
- Restricted datasetsの録音は、非メンバーには検索結果に含めない（APIレベルでフィルタ）

---

## 🔍 Navigation & Breadcrumbs

### Admin Sidebar
**新セクション**: "Metadata" (collapsible)
- Projects
- Sites
- Recorders
- Licenses
- Datasets (existing, moved here)
- Annotation Projects (existing, moved here)

### Breadcrumbs
**Examples**:
- `Admin > Metadata > Datasets > {Dataset Name} > Edit`
- `Admin > Metadata > Projects > {Project Name} > Members`
- `Admin > Metadata > Sites > {Site Name} > Gallery`

---

## ✅ Validation & UX Patterns

### Form Validation
- **Required fields**: Inline error messages on blur
- **Unique constraints**: Async validation with debounce (500ms)
- **Format validation**: Real-time regex check (DOI, URLs)
- **FK validation**: Ensure referenced entities exist

### User Feedback
- **Success toast**: "Dataset created successfully"
- **Warning toast**: "Missing optional metadata: Site, License"
- **Error toast**: "Failed to create dataset: Duplicate name"
- **Confirmation dialogs**: For delete/remove actions
- **Loading states**: Skeleton loaders for tables/cards

### Accessibility
- **Keyboard navigation**: Tab order, Enter/Escape handling
- **ARIA labels**: For icons, badges, interactive elements
- **Color contrast**: WCAG AA compliance
- **Screen reader support**: Announce dynamic content changes

---

## 🚀 Implementation Priorities

### Phase 1: Core Metadata Admin
1. Recorder + License admin (simple CRUD)
2. Project creation + member management (superuser)
3. Dataset create/edit with new FK selectors

### Phase 2: H3 Integration
1. H3 Map Picker component
2. Site admin with H3 selection
3. Site detail view with H3 overlay

### Phase 3: Datetime Parsing
1. Datetime parser modal UI (pattern input, sample validation)
2. Backend: `datetime_patterns` table + parse endpoints
3. Background job setup (Celery/RQ) for batch parsing
4. Progress tracking UI (WebSocket or polling)
5. Error handling & retry flow

### Phase 4: Hierarchical Filtering
1. Filter panel component
2. Dataset explorer with multi-level filters
3. Site filtering by project

### Phase 5: Cross-Dataset Search
1. Recording search page layout (sidebar + main area)
2. H3 spatial filter with multi-cell selection
3. Temporal filters (date range + time-of-day slider with wraparound)
4. Backend: `/recordings/search` endpoint with permission filtering
5. Map view with marker clustering
6. Table view with pagination & export
7. Performance optimization (indexes, query tuning)

### Phase 6: Visibility & Access Control
1. Visibility badge component
2. Restricted content UI (lock icons, access messages)
3. Member-only views and permissions
4. Permission-aware search results

### Phase 7: Polish & UX
1. Image gallery manager for sites
2. Metadata link card on dataset detail
3. Breadcrumbs and navigation updates
4. Form validation refinements
5. Responsive design for mobile/tablet

---

この設計は PLAN.MD の UI 要件を完全に反映しています。実装時の疑問点や改善提案があれば共有してください。
