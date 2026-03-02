# 機能仕様書: 検出レビュー

**フィーチャーブランチ**: `003-detection-review`
**作成日**: 2026-03-02
**ステータス**: ドラフト
**入力**: 検出結果のレビュー（新アノテーションモデル、ConfirmedRegion、DetectionRun、Species List View、Detection Review UI、検出エクスポート、ナビゲーション再構築）
**置換対象**: 旧 `003-annotation`（AnnotationProject, AnnotationTask, ClipAnnotation, SoundEventAnnotation を廃止）

## 旧モデルとの対応

| 廃止するモデル | 新モデル | 変更理由 |
|---|---|---|
| AnnotationProject | (廃止) | ユーザーがプロジェクトを自分で構成する必要がない。ML結果を直接レビューする |
| AnnotationTask | (廃止) | タスク管理は不要。検出結果を直接レビューする |
| ClipAnnotation | (廃止) | クリップ単位ではなく録音上の時間セグメント単位に変更 |
| SoundEventAnnotation | Annotation | 録音に直接紐づく時間セグメントアノテーション |
| (なし) | ConfirmedRegion | レビュー済み区間（ネガティブデータ対応） |
| (なし) | DetectionRun | ML実行メタデータ（トレーサビリティ） |

## 用語対応表

| 内部・技術用語 | ユーザー向け表示 |
|---|---|
| Annotation | Detection（検出） |
| Tag (category=species) | Species（種） |
| ConfirmedRegion | レビュー済み区間 |
| DetectionRun | （非公開） |
| Clip | （非公開、ML処理時にメモリ上で動的生成） |

## ユーザーシナリオとテスト *(必須)*

### ユーザーストーリー 1 - Species List View (優先度: P1)

ユーザーがプロジェクトのDetectionsページを開くと、検出された全種のリスト（件数、平均信頼度、レビュー進捗）が表示される。これがユーザーの「何が見つかったか？」という質問に直接回答するエントリーポイントとなる。

**優先度の理由**: 検出結果のレビューワークフローの起点。ユーザーが最初に見る画面であり、全体像を把握するために必須。

**独立テスト**: ML検出結果（Annotation source=birdnet）が存在する状態で、Detectionsページを開き、種ごとの集計が正しく表示されることを確認。

**受け入れシナリオ**:

1. **Given** プロジェクトに検出結果（Annotation）が存在する状態で、**When** ユーザーがDetectionsページを開く、**Then** 種ごとにグループ化されたリストが表示される（種名、検出件数、平均信頼度、レビュー進捗バー）
2. **Given** Species List Viewが表示されている状態で、**When** ユーザーが検索ボックスに種名を入力する、**Then** リストがフィルタリングされる
3. **Given** Species List Viewが表示されている状態で、**When** ユーザーが「Unreviewed」フィルタを選択する、**Then** 未レビューの検出がある種のみが表示される
4. **Given** Species List Viewが表示されている状態で、**When** ユーザーが種名をクリックする、**Then** その種のDetection Review画面に遷移する
5. **Given** プロジェクトに複数データセットがある状態で、**When** ユーザーがデータセットフィルタを選択する、**Then** 選択したデータセットの検出結果のみが集計される
6. **Given** Species List Viewが表示されている状態で、**When** ユーザーがソート順を変更する（件数順、信頼度順、名前順）、**Then** リストが指定の順序で並び替えられる

---

### ユーザーストーリー 2 - Detection Review (優先度: P1)

ユーザーが種をクリックすると、カード型レビューUIが表示される。各カードにミニスペクトログラムと再生ボタンが付き、Confirm/Rejectボタンで確認作業を行う。Confirmする際は鳴き声の実際の時間範囲をドラッグで指定する。

**優先度の理由**: これがEchorooのコアバリュー。ML検出結果を効率的にレビューし、精密なアノテーションを作成する機能。

**独立テスト**: 特定の種の検出結果一覧を表示し、各カードのConfirm/Reject操作、時間範囲選択が正しく動作することを確認。

**受け入れシナリオ**:

1. **Given** 種のDetection Review画面を開いた状態で、**When** 画面が読み込まれる、**Then** カードグリッドが表示され、各カードにミニスペクトログラム、再生ボタン、信頼度スコア、録音ファイル名が表示される
2. **Given** 検出カードが表示されている状態で、**When** 再生ボタンをクリックする、**Then** その検出区間の音声が再生される
3. **Given** 検出カードが表示されている状態で、**When** ユーザーがConfirmボタンをクリックする、**Then** ミニスペクトログラム上でML検出区間がハイライト表示され、ユーザーが鳴き声の実際の時間範囲をドラッグで指定するUIが表示される
4. **Given** 時間範囲指定UIが表示されている状態で、**When** ユーザーがドラッグで範囲を指定してConfirmを確定する、**Then** Annotationのstatusがconfirmedに更新され、ConfirmedRegionが作成され、カードが「確認済み」として表示される
5. **Given** 検出カードが表示されている状態で、**When** ユーザーがRejectボタンをクリックする、**Then** Annotationのstatusがrejectedに更新され、カードが「棄却」として表示される
6. **Given** 検出カードが表示されている状態で、**When** ユーザーが種を変更する（誤同定の修正）、**Then** 正しい種タグを選択して時間範囲を指定した後、新しいAnnotationが作成される
7. **Given** Detection Review画面で、**When** ユーザーがフィルタを変更する（unreviewed/confirmed/rejected/all）、**Then** 該当するステータスの検出のみが表示される
8. **Given** Detection Review画面で、**When** ユーザーが信頼度スライダーを調整する、**Then** 指定した信頼度範囲の検出のみが表示される
9. **Given** Detection Review画面で、**When** ユーザーがキーボードショートカット（C=Confirm, R=Reject, Space=再生）を使用する、**Then** 対応する操作が実行される
10. **Given** スペクトログラム上でML検出区間がハイライト表示されている状態で、**When** ユーザーが確認する、**Then** ML検出区間がガイドとして視覚的に区別される（薄い色でオーバーレイ）

---

### ユーザーストーリー 3 - Detection Data Model (優先度: P1)

新しいAnnotation/ConfirmedRegion/DetectionRunモデルとAPIエンドポイント。Recording直結のアノテーション。

**優先度の理由**: US1とUS2のバックエンド基盤。全てのフロントエンド機能がこのデータモデルとAPIに依存する。

**独立テスト**: APIエンドポイントを直接呼び出し、Annotation/ConfirmedRegion/DetectionRunのCRUD操作が正しく動作することを確認。

**受け入れシナリオ**:

1. **Given** 録音が存在する状態で、**When** 新しいAnnotationを作成する（start_time, end_time, tag_id, source, confidence）、**Then** Annotationが録音に直接紐づいて保存される
2. **Given** Annotationが存在する状態で、**When** ステータスをconfirmedに更新する、**Then** ステータスが更新され、reviewed_by_idとreviewed_atが記録される
3. **Given** 録音が存在する状態で、**When** ConfirmedRegionを作成する（start_time, end_time）、**Then** その時間区間がレビュー済みとして記録される
4. **Given** ConfirmedRegionとAnnotationがある状態で、**When** ネガティブデータを照会する、**Then** ConfirmedRegionのうちAnnotationがない区間がネガティブデータとして返される
5. **Given** DetectionRunを作成する際に、**When** モデル名、バージョン、パラメータを指定する、**Then** 実行メタデータが保存され、生成されたAnnotationと紐づけられる
6. **Given** プロジェクト内に検出結果がある状態で、**When** 種別集計APIを呼び出す、**Then** 種ごとの検出件数、平均信頼度、レビュー済み件数が返される
7. **Given** Annotationにtag_idが設定されている状態で、**When** タグ別にフィルタリングする、**Then** 指定した種のAnnotationのみが返される
8. **Given** Annotationが存在する状態で、**When** 信頼度範囲でフィルタリングする、**Then** 指定範囲内のAnnotationのみが返される

---

### ユーザーストーリー 4 - Detection Export (優先度: P2)

検出結果CSVとML学習用データセットのエクスポート。

**優先度の理由**: 検出結果の外部利用と共有に必要。コアレビュー機能の後に実装可能。

**独立テスト**: 検出結果が存在する状態で、CSVエクスポートとML学習データセットエクスポートを実行し、出力が仕様通りであることを確認。

**受け入れシナリオ**:

1. **Given** 検出結果が存在する状態で、**When** ユーザーが検出結果CSVエクスポートを要求する、**Then** VISION.mdで定義されたフォーマットのCSVがダウンロードされる（recording_filename, start_time, end_time, species, confidence, source, model_name, model_version, verified, verified_by）
2. **Given** エクスポートダイアログで、**When** ユーザーが「確認済みのみ」フィルタを選択する、**Then** confirmed状態のAnnotationのみがエクスポートされる
3. **Given** 確認済みAnnotationとConfirmedRegionが存在する状態で、**When** ユーザーがML学習用データセットエクスポートを要求する、**Then** audio/ディレクトリ、annotations.csv、metadata.json、README.txtを含むZIPがダウンロードされる
4. **Given** ML学習用エクスポートで、**When** ポジティブデータ（確認済みAnnotation区間）を出力する、**Then** 指定した時間範囲の音声が切り出されてaudio/に保存される
5. **Given** ML学習用エクスポートで、**When** ネガティブデータ（ConfirmedRegionのうちAnnotationなし区間）を出力する、**Then** 確認済み無音区間の音声が切り出されてaudio/に保存される
6. **Given** 大量のエクスポート対象がある場合、**When** エクスポートが開始される、**Then** ストリーミングレスポンスで効率的にダウンロードが行われる

---

### ユーザーストーリー 5 - Navigation Restructure (優先度: P2)

プロジェクトのサイドバーナビゲーションをVISION.mdの5項目構成に変更する。

**優先度の理由**: ユーザー体験の改善に重要だが、既存のナビゲーションでも機能的には運用可能。

**独立テスト**: プロジェクト画面でサイドバーが5項目（Overview, Sites & Data, Detections, Reports, Settings）で表示されることを確認。

**受け入れシナリオ**:

1. **Given** プロジェクト画面を開いた状態で、**When** サイドバーを確認する、**Then** 5項目（Overview, Sites & Data, Detections, Reports, Settings）が表示される
2. **Given** サイドバーで「Sites & Data」をクリックした状態で、**When** ページが読み込まれる、**Then** サイト管理、データセット管理、録音ブラウザが統合されたビューが表示される
3. **Given** サイドバーで「Detections」をクリックした状態で、**When** ページが読み込まれる、**Then** Species List Viewが表示される
4. **Given** サイドバーで「Reports」をクリックした状態で、**When** ページが読み込まれる、**Then** エクスポートオプション（検出CSV、ML学習データセット）が表示される
5. **Given** サイドバーで「Settings」をクリックした状態で、**When** ページが読み込まれる、**Then** プロジェクト設定とメンバー管理が表示される

---

### エッジケース

- 検出結果が0件のプロジェクトでDetectionsページを開いた場合どうなるか？ → 空状態メッセージ「No detections yet. Import a dataset to start.」を表示
- 同一時間範囲に複数のAnnotationが存在する場合どうなるか？ → 許容する（同じ区間に複数の種が検出される場合があるため）
- ConfirmedRegionが重複する場合どうなるか？ → 重複を許容するが、ネガティブデータ計算時にはマージして処理する
- Confirmの時間範囲が元のML検出区間を超える場合どうなるか？ → 許容する（ML検出が実際の鳴き声より短い場合がある）
- DetectionRunが中断された場合どうなるか？ → ステータスをfailedに更新し、既に生成されたAnnotationは保持する
- 種を変更してConfirmした場合に元のAnnotationはどうなるか？ → 元のAnnotationはrejectedに、新しいAnnotationが正しい種で作成される

## 要件 *(必須)*

### 機能要件

#### 新データモデル
- **FR-001**: システムは、Recording上の時間セグメントとしてAnnotationを作成できなければならない（start_time, end_time, tag_id, source, confidence, status）
- **FR-002**: Annotationのsourceは`birdnet`、`perch_search`、`human`のいずれかでなければならない
- **FR-003**: Annotationのstatusは`unreviewed`、`confirmed`、`rejected`のいずれかでなければならない
- **FR-004**: Annotationの信頼度（confidence）は0.0〜1.0の範囲でなければならない（ML検出の場合）
- **FR-005**: Annotationにはオプションでfreq_low、freq_highを設定できなければならない
- **FR-006**: システムは、Recording上のレビュー済み時間区間としてConfirmedRegionを作成できなければならない
- **FR-007**: ConfirmedRegionとAnnotationの組み合わせにより、ポジティブデータ・ネガティブデータ・不明の区別ができなければならない
- **FR-008**: システムは、ML実行メタデータ（DetectionRun）を保存できなければならない（model_name, model_version, parameters, status, annotation_count）
- **FR-009**: AnnotationはDetectionRunにオプションで紐づけられなければならない

#### Species List View
- **FR-010**: システムは、プロジェクト内の全Annotationを種ごとにグループ化して集計できなければならない
- **FR-011**: 集計にはdetection_count（件数）、avg_confidence（平均信頼度）、reviewed_count（レビュー済み件数）、confirmed_count（確認済み件数）、rejected_count（棄却件数）を含めなければならない
- **FR-012**: 集計をデータセットでフィルタリングできなければならない
- **FR-013**: 種名検索、ステータスフィルタ、ソート（件数/信頼度/名前）をサポートしなければならない

#### Detection Review UI
- **FR-014**: システムは、カードグリッド形式で検出結果を表示しなければならない
- **FR-015**: 各カードにはミニスペクトログラム、再生ボタン、信頼度スコア、録音ファイル名を含めなければならない
- **FR-016**: ML検出区間をスペクトログラム上でハイライト表示しなければならない
- **FR-017**: ユーザーがConfirm操作時に鳴き声の実際の時間範囲をドラッグで指定できなければならない
- **FR-018**: Confirm/Reject操作でAnnotationのステータスが更新されなければならない
- **FR-019**: Confirm操作時にConfirmedRegionが自動的に作成されなければならない
- **FR-020**: 種の変更（誤同定の修正）をサポートしなければならない
- **FR-021**: フィルタ（ステータス、信頼度範囲）をサポートしなければならない
- **FR-022**: キーボードショートカット（C=Confirm, R=Reject, Space=再生）をサポートしなければならない

#### 検出エクスポート
- **FR-023**: システムは、検出結果をCSV形式でエクスポートできなければならない（VISION.md準拠フォーマット）
- **FR-024**: エクスポートにフィルタ（ステータス、種、データセット）を適用できなければならない
- **FR-025**: システムは、ML学習用データセット（音声+annotations.csv+metadata.json+README.txt）をZIP形式でエクスポートできなければならない
- **FR-026**: ML学習用データセットにはポジティブデータ（確認済みAnnotation区間）とネガティブデータ（ConfirmedRegionのAnnotationなし区間）を含めなければならない

#### ナビゲーション
- **FR-027**: プロジェクトサイドバーは5項目（Overview, Sites & Data, Detections, Reports, Settings）で構成されなければならない
- **FR-028**: 旧Annotations/Datasets/Recordings/Sitesルートからのリダイレクトまたは統合をサポートしなければならない

### 主要エンティティ

- **Annotation（検出/アノテーション）**: 録音上の時間セグメントに対する種同定。start_time, end_time, recording_id, tag_id, source, confidence, status, freq_low, freq_high, detection_run_id, reviewed_by_id, reviewed_atを持つ
- **ConfirmedRegion（確認済み区間）**: 人がレビューした録音上の時間区間。start_time, end_time, recording_id, reviewed_by_idを持つ。Annotationありの区間=ポジティブ、なし=ネガティブ
- **DetectionRun（検出実行記録）**: ML実行メタデータ。project_id, model_name, model_version, parameters, status, annotation_count, dataset_idを持つ
- **Tag（種タグ）**: 既存のTagモデルを再利用。category=speciesの場合にAnnotationで使用

## 成功基準 *(必須)*

### 測定可能な成果

- **SC-001**: Species List Viewが1秒以内に表示される（10,000件のAnnotation）
- **SC-002**: Detection Reviewカードグリッドが2秒以内に表示される（100件のカード）
- **SC-003**: Confirm/Reject操作が500ms以内に完了する
- **SC-004**: ミニスペクトログラムが1秒以内に描画される
- **SC-005**: 音声再生が500ms以内に開始される
- **SC-006**: CSVエクスポートが10,000件のAnnotationに対して5秒以内に完了する
- **SC-007**: 95%のユーザーがサポートなしで検出レビューワークフローを開始できる
- **SC-008**: レビュー速度: 1件あたり平均5秒以内（Confirm/Reject操作のみ）

## 前提条件

- 002-data-management（Site, Dataset, Recording）が実装済みである
- 001-administration（User, Project, Tag）が実装済みである
- ML検出パイプライン（BirdNET自動実行）は別機能として実装される（本機能はデータモデルとAPIのみ提供）
- 音声ファイルはサーバーファイルシステムに存在する

## Clarifications

### Session 2026-03-02

- Q: 旧annotation系モデル（AnnotationProject, AnnotationTask, ClipAnnotation, SoundEventAnnotation）はどう扱うか？ → A: 新テーブルを作成し、旧テーブルは非推奨化。マイグレーションで旧テーブルを残しつつ新テーブルを追加
- Q: Tagモデルはそのまま使うか？ → A: そのまま使う。category=speciesのTagをAnnotationのtag_idとして参照
- Q: Clipモデルとの関係は？ → A: ClipはML処理時の内部概念に留め、AnnotationはRecordingに直接紐づける。既存Clipテーブルは残す
- Q: DetectionRunのstatusにはどのような値があるか？ → A: pending, running, completed, failed
- Q: AnnotationのsourceはAnnotationSourceと同じenumか？ → A: 新しいDetectionSource enumを作成（birdnet, perch_search, human）。旧AnnotationSource（human, model）とは別