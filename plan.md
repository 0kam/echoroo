# P2-B: AnnotationEditor.svelte 分割プラン (v3)

対象: `apps/web/src/lib/components/annotation-sets/AnnotationEditor.svelte` (768 行)
準備: Playwright smoke test **未整備** — Step 0 で先行整備
目標: 2 モジュール抽出で parent を ~400 行に縮小。behavior 完全保持。

SpectrogramViewer 分割 (plan v3.1 で完了) のパターン踏襲:
- hook = `.svelte.ts` + getter 渡し (`() => value`) で reactivity 維持
- callback props は `(arg) => prop?.(arg)` で wrap
- hook 内部に `disposed` フラグ + `dispose()` export で多重防御
- Step 0 で Playwright smoke 先行、分割は behavior-preserving
- **DOM ref は親所有** (`bind:this` は親側)、hook には `containerEl: () => HTMLElement | null` getter で渡す (Spectrogram の `canvas: () => canvas` パターン)

**v2 改訂ポイント (Codex 1st review):**
- **keydown 購読は Step 1 開始時点から親統一に一本化** (v1 の「Escape=Draft hook / Delete=Mutation hook」案は中間コミットで仕様ブレのため破棄)
- **readonly 検証を Step 0 必須ケースに昇格** (hook の `isDisabled` 入力が挙動を変える以上、optional 扱いは不可)
- **overlay DOM ref は親所有** (`let overlayEl = $state()` を親に残し、Draft hook には `overlayEl: () => HTMLDivElement | null` を getter で渡す)
- **`pickSpecies` の分岐は親で行う** (hook の action API は `createFromDraft(range, speciesId)` / `updateSpeciesOf(annotationId, speciesId)` を分離公開、親の `pickSpecies(speciesId)` wrapper が `draftRange` / `selectedAnnotationId` を見て dispatch)
- **`onCreated` callback に stale-segment ガード** (呼び出し時点で `segmentId` が一致するかを hook 内で再確認してから発火)

**v3 改訂ポイント (Codex Step 0 review):**
- **純粋 refactor に徹する (Option A 確定)**: 現行 AnnotationEditor は `isReadonly` を **バナー表示のみ** で使用し、drag/mutation handler に guard を持たない。Step 1 で Draft hook から **`isDisabled` 入力を削除**し、readonly 抑止はバナー継続。readonly で drag/mutation を no-op にする UX 改善は **別 PR** で実施 (Option B)。
  - 理由: Step 0 spec (test #9) は現行挙動 (banner/badge/button 状態) をアサートしており、isDisabled を追加すると挙動変更になり refactor の純度が落ちる
  - Test #9 は behavior-preserving な regression 検知として機能する (refactor 前後で同じ挙動を維持)
- **Seed 再利用時の editable state リセット**: Playwright spec の `beforeAll` で既存 `e2e-annotation-editor-*` set を再利用する場合、editable segment に前回残した annotations / is_empty フラグを**ハードリセット**する (annotations 全 DELETE + segment PATCH で status='unannotated', is_empty=false)。ローカル再実行の決定性確保

## 1. 現状マップ (Explore SSA 調査結果)

### 1.1 Props / 子構成
- **Props**: `{projectId, setId, segmentId}` のみ (3 つの route param)
- **子**: SegmentNavigator (271), AnnotationList (141), SpeciesPalette (239), NotesPanel (128), ClipSpectrogramPlayer
- **親**: `/projects/[id]/annotation-sets/[setId]/annotate/[segmentId]/+page.svelte` (`{#key segmentId}` で再マウント)

### 1.2 状態 (所有権別)
| カテゴリ | 変数 | 用途 |
|---|---|---|
| Draft | `draftRange`, `isDraggingOverlay`, `dragStartX`, `dragCurrentX`, `overlayEl` | ドラッグ選択 → 時間範囲 |
| Selection | `selectedAnnotationId` | 既存 annotation 選択（draft と排他） |
| DOM ref | `spectrogramContainerEl` | 未使用（削除候補） |

### 1.3 $derived
- Query data: `setDetail` / `segment` / `recording` / `segmentItems`
- Selection: `selectedAnnotation` / `currentIndex` / `hasPrevious` / `hasNext`
- Clip: `clipStart` / `clipEnd` / `clipDuration`
- Mode: `isReadonly` (`status === 'annotated' | 'skipped'`)
- Geometry: `dragPreviewLeft` / `dragPreviewWidth` (% 表示)
- Mutation: `isBusy` (7 mutations の OR)
- Nav: `backHref`

### 1.4 $effect (3 箇所)
- L136-141: segmentId 変更で draftRange + selectedAnnotationId クリア
- L206-213: window `mousemove` / `mouseup` 購読 (ドラッグ)
- L477-478: window `keydown` 購読 (Escape=キャンセル, Delete=削除)

### 1.5 Geometry helpers (L161-227)
- `clientXToTime(clientX)` → 絶対秒。`overlayEl.getBoundingClientRect()` + `clipStart` + `clipDuration`
- `timeToPercent(t)` → % 位置
- **時間表現**: `draftRange` は**絶対**秒。API body は **segment 相対**秒 → commit 時に `- clipStart` 変換 (L326 `pickSpecies`)

### 1.6 Mutations (7 個)
| 名前 | API | invalidate key |
|---|---|---|
| `createAnnotationMutation` | `createAnnotation(segmentId, body)` | segment, set |
| `updateAnnotationSpeciesMutation` | `updateAnnotation(id, {species_id})` | segment |
| `deleteAnnotationMutation` | `deleteAnnotation(id)` | segment, set |
| `updateSegmentMutation` | `updateSegment(segmentId, {...})` | segment, set, segments |
| `addPaletteMutation` | `addPalette(setId, {species_id})` | set |
| `createSegmentNoteMutation` | `createSegmentNote(segmentId, body)` | segment |
| `createAnnotationNoteMutation` | `createAnnotationNote(annotationId, body)` | segment |

- `isBusy = $derived(...7 .isPending の OR)`
- `onError`: 全て `toasts.error(...)` 表示。**楽観更新なし、rollback なし** (invalidate re-fetch のみ)

### 1.7 Action functions (mutation 呼出 wrapper)
- `pickSpecies(speciesId)` — draft があれば create、selectedAnnotation があれば update
- `onDeleteAnnotation(id)` — confirm → delete
- `markNoVocalization()` / `clearNoVocalization()` — updateSegment
- `addSpeciesToPalette(speciesId)` — addPalette
- `addSegmentNote(content, isIssue)` — createSegmentNote
- `addAnnotationNote(content, isIssue)` — createAnnotationNote
- Navigation: `navigatePrevious/Next/skipAndNext` — `goto()`（mutation 非依存）

### 1.8 SpectrogramViewer との関係
**独立**。ClipSpectrogramPlayer は自前で viewport 所有、AnnotationEditor は **pan/zoom 同期なし**。`clipStart`/`clipEnd` は segment メタから取得、overlay div は視覚的に spectrogram の上に重なるが座標系は独立。

### 1.9 既存テスト
- **Playwright**: ゼロ（関連 e2e なし）
- **vitest**: ゼロ
- 直近コミット: `5128c575 feat(web): add annotation set management and editor (Phases B + C)` 一発リリース、follow-up なし

## 2. 目標ファイル構成

| ファイル | 行数目安 | 役割 |
|---|---|---|
| `AnnotationEditor.svelte` | ~400 | queries + 子パネル組み立て + 2 hook wiring |
| `useAnnotationDraft.svelte.ts` (新規) | ~180 | draft state + geometry + drag handlers (keydown は親) |
| `useAnnotationMutations.svelte.ts` (新規) | ~200 | 7 mutations + isBusy + 高レベル actions |
| `types.ts` (新規) | ~60 | Draft / Mutation hook API 契約 |

## 3. 分割の設計判断

### 3.1 Draft hook の境界
**含む:**
- `draftRange`, `isDraggingOverlay`, `dragStartX`, `dragCurrentX`
- `clientXToTime` / `timeToPercent` geometry
- `dragPreviewLeft` / `dragPreviewWidth` derived
- `handleOverlayMouseDown` / `handleWindowMouseMove` / `handleWindowMouseUp`
- window mousemove/mouseup 購読の `$effect`
- `clear()` export (外部からキャンセル、Escape/selection/segmentId 変更時に親が呼ぶ)
- `disposed` フラグ + `dispose()` export

**含まない:**
- commit (mutation 呼出) → 親が `mutations.actions.createFromDraft(draft.draftRange, speciesId)` を呼ぶ
- keydown 購読 (Escape も親で処理して `draft.clear()` を呼ぶ)
- DOM ref 管理 (overlay element は親で `bind:this`、hook には getter `overlayEl: () => HTMLDivElement | null` で渡す)
- 絶対 ↔ 相対変換は **Draft 内では行わない**。Draft は絶対秒の `draftRange` を公開、Mutation 側で相対変換。

**入力 (getter):**
- `overlayEl: () => HTMLDivElement | null` (DOM ref、親所有)
- `clipStart: () => number`, `clipDuration: () => number` (geometry 計算用)

**出力 (reactive object):** `{ draftRange, isDragging, dragPreview: {left, width}, handlers: {onMouseDown}, clear, dispose }`

> **v3 で `isDisabled` 入力を削除**: readonly 時も drag は発火する (現行挙動)。readonly での no-op 化は別 PR (Option B) で実施。

### 3.2 Mutation hook の境界
**含む:**
- 7 `createMutation()` 定義
- `isBusy` derived
- **明示的 action 群** (親が dispatch する):
  - `createFromDraft(range: {start, end}, speciesId)` — 絶対秒 range → 相対秒に変換して createAnnotation
  - `updateSpeciesOf(annotationId, speciesId)` — updateAnnotation
  - `deleteAnnotation(id)` — confirm → delete
  - `markEmpty()` / `clearEmpty()` — updateSegment
  - `addSpeciesToPalette(speciesId)` — addPalette
  - `addSegmentNote(content, isIssue)`
  - `addAnnotationNote(annotationId, content, isIssue)` — id を明示引数 (selectedAnnotationId の reactive 依存を持たせない)
- `onCreated(annotationId: string)` callback export — create 成功時、hook 内で stale-segment ガード (呼出時 `segmentId()` 一致確認) 後に発火
- Invalidation 戦略（現行通り）
- Error toast (現行通り)
- `disposed` フラグ + `dispose()` export

**含まない:**
- Navigation (`goto` は親で、mutation 非依存)
- `pickSpecies` のような分岐ロジック (親の wrapper で `draftRange` / `selectedAnnotationId` を見て `createFromDraft` or `updateSpeciesOf` を選ぶ)
- keydown 購読 (親で Delete を受けて `mutations.actions.deleteAnnotation(selectedAnnotationId)` を呼ぶ)

**入力 (getter):**
- `segmentId: () => string`, `setId: () => string`
- `clipStart: () => number`, `clipDuration: () => number` (createFromDraft の相対変換用)
- `onCreated?: (annotationId: string) => void` (親の selection 同期 callback、optional)

**出力:** `{ isBusy, actions: {createFromDraft, updateSpeciesOf, deleteAnnotation, markEmpty, clearEmpty, addSpeciesToPalette, addSegmentNote, addAnnotationNote}, dispose }`

### 3.3 親側に残る責務
- 4 x `createQuery()` (set / segment / recording / segmentItems)
- Navigation (`navigatePrevious/Next/skipAndNext`)
- 子パネルへの props 組み立て
- `overlayEl` の `bind:this` (DOM ref 所有)
- `selectedAnnotationId` の `$state` 管理 (両 hook が参照するので親が自然)
- `draftRange` と `selectedAnnotationId` の**相互排他ロジック**:
  - annotation select → `draft.clear()` + `selectedAnnotationId = id`
  - create 成功 → `onCreated(id)` callback で `selectedAnnotationId = id` (draft は hook 内で自動クリア or 親で明示 clear)
- segmentId 変更時の reset `$effect` (`draft.clear()` + `selectedAnnotationId = null`)
- `isReadonly` 判定 (バナー表示 + 子パネル isBusy 伝播のみ、hook へは渡さない)
- **`pickSpecies(speciesId)` wrapper** (draft があれば `createFromDraft`、selectedAnnotation があれば `updateSpeciesOf` を dispatch)
- **window keydown 購読** (Escape → `draft.clear()` + `selectedAnnotationId = null`、Delete → `selectedAnnotationId` があれば `mutations.actions.deleteAnnotation(id)`)

### 3.4 Keydown 処理の分担 — **親統一 (最終方針)**
Codex review で確定。hook 側の keydown 購読は **両方とも持たない**。
- 親の `$effect` 1 箇所で `window.addEventListener('keydown', ...)` 購読
- **IME / 入力中ガード (必須)**: handler 冒頭で `event.target` が `INPUT` / `TEXTAREA` / `contentEditable` 要素のとき早期 return。現行実装 (L463-478) にもあるので必ず保持
- Escape: `draft.clear(); selectedAnnotationId = null;`
- Delete / Backspace: `if (selectedAnnotationId) mutations.actions.deleteAnnotation(selectedAnnotationId);`
- cleanup で removeEventListener

### 3.5 `dispose()` 呼び出し点
両 hook とも `disposed` フラグ + `dispose()` export を持つ (Spectrogram パターン踏襲)。**親の `onDestroy` で明示呼び出し**:
```ts
onDestroy(() => {
  draft.dispose();
  mutations.dispose();
});
```
hook 自身の `onDestroy` だと入れ子に注意 — hook は `.svelte.ts` なので Svelte component 文脈外、親 component が呼ぶ。

## 4. 実装ステップ

### Step 0 — Playwright smoke 整備 (1 commit)
**目的**: 分割前に regression 検知網を張る。

**追加するテスト** (`apps/web/tests/e2e/annotation-editor.spec.ts`):
1. ページマウント: `/projects/.../annotate/[segmentId]` で SegmentNavigator + overlay + ClipSpectrogramPlayer + AnnotationList + SpeciesPalette + NotesPanel が表示
2. Draft 作成: overlay をドラッグ → draft preview (% bar) 表示
3. Species pick で commit: SpeciesPalette のチップ click → API `POST /annotations` 発火 → AnnotationList に新規 item
4. 既存 annotation 選択: AnnotationList の item click → `selectedAnnotationId` セット、draft クリア
5. Escape: draft 表示中に Escape → draft クリア
6. Delete: annotation 選択中に Delete + confirm → DELETE request → list から消える
7. Mark empty: SegmentNavigator の「鳥の声なし」toggle → updateSegment PATCH
8. SegmentNavigator Next/Prev: 遷移 → URL 変化 + `{#key segmentId}` で再マウント
9. **Readonly 1 ケース** (Codex 指摘で追加): segment.status=`annotated` の segment を開き、ドラッグ/Escape/Delete/species pick が全て no-op、mutation が発火しないことを確認。fixture で seed 済み segment を利用。

**fixture 戦略:**
- 実データ依存せず、test 用 annotation-set + segments を setup fixture で seed
- auth は SpectrogramViewer test で確立した refresh_token 直接 + cookie 設定方式 (`apps/web/tests/e2e/spectrogram.spec.ts` 参照) を流用
- **readonly 検証は実データ status seed 経由**。fixture route は作らない (SpectrogramViewer の readonly は prop 分岐ロジックがあったが AnnotationEditor の `isReadonly` は `segment.status` 由来で、status=annotated な segment を seed すれば実画面経路で検証可能)

### Step 1 — `types.ts` + Draft hook 抽出 + keydown 親統一 (1 commit)
- `types.ts` で `DraftHook`, `DraftHookInput`, `MutationHook`, `MutationHookInput` 型契約定義 (両方を先に宣言しておくと Step 2 で追従必要なし)
- `useAnnotationDraft.svelte.ts` 新規、L161-227 + L206-213 の drag 処理を移動
- AnnotationEditor.svelte:
  - `overlayEl` は親に残す (`<div bind:this={overlayEl}>`)
  - `const draft = useAnnotationDraft({ overlayEl: () => overlayEl, clipStart: () => clipStart, clipDuration: () => clipDuration, isDisabled: () => isReadonly })`
  - **window keydown 購読を親で統一**: 既存の L477-478 を親の `$effect` に整理し、handler が `draft.clear()` / `selectedAnnotationId = null` / `onDeleteAnnotation(selectedAnnotationId)` を呼ぶ形に変更
  - 未使用 `spectrogramContainerEl` を削除
- `dragPreviewLeft` / `dragPreviewWidth` は `draft.dragPreview.left` / `.width`
- E2E 9/9 green を維持して commit

### Step 2 — Mutation hook 抽出 (1 commit)
- `useAnnotationMutations.svelte.ts` 新規、7 mutations + 明示的 action functions + isBusy を移動
- AnnotationEditor.svelte で `const mutations = useAnnotationMutations({ segmentId: () => segmentId, setId: () => setId, clipStart: () => clipStart, clipDuration: () => clipDuration, onCreated: (id) => { draft.clear(); selectedAnnotationId = id; } })`
- **親の `pickSpecies(speciesId)` wrapper**:
  ```ts
  function pickSpecies(speciesId: string) {
    if (draft.draftRange) {
      mutations.actions.createFromDraft(draft.draftRange, speciesId);
    } else if (selectedAnnotationId) {
      mutations.actions.updateSpeciesOf(selectedAnnotationId, speciesId);
    }
  }
  ```
- `onCreated` の stale-segment ガード: hook 内で `if (segmentId() !== capturedSegmentIdAtMutateTime) return;` で発火抑止 (segmentId 変更後に前の segment の create が返ってきた場合のフェイルセーフ)
- E2E 9/9 green を維持して commit

### (行数目安)
- Step 1 後: parent ~550 行 (draft 抽出分 ~180 + keydown 統一分 ~-10)
- Step 2 後: parent ~400 行 (mutation 抽出分 ~200 + isBusy derived 整理分)

## 5. 移行リスクと緩和

### 5.1 時間原点変換の責務境界
- 親 / Draft / Mutation 3 箇所に散らすと混乱
- **採用**: Draft は**絶対秒**で `draftRange` を公開。Mutation `pickSpecies` が `clipStart` getter を使って相対変換。
- 親は変換を一切意識しない
- **契約のテスト**: `pickSpecies` 呼出時に body が `time_start = draft.start - clipStart` になる unit level か E2E で検証

### 5.2 hook 間の相互作用
- draft 作成 → selection クリア: 親の selection setter から `draft.clear()` 呼ばない（逆方向）。hook が annotation select event を知る必要なし。
- annotation select → draft クリア: 親の `onSelectAnnotation` が `draft.clear()` + `selectedAnnotationId = id`
- commit 成功 → selection = 新規 id + draft クリア: Mutation の `onCreated` callback で親が両方実行

### 5.3 Svelte 5 rune gotcha (SpectrogramViewer で学習済み)
- hook 可変入力は**全て getter** (`() => T`)
- callback prop は wrap (`(arg) => prop?.(arg)`) — init 時 bare 参照を掴まない
- `$state_referenced_locally` 警告回避のため module top-level `void x` 禁止、`$effect` 内のみ
- `$bindable<T>()` for overlay ref

### 5.4 window event 購読の二重化
- Draft (mousemove/mouseup) + 親 (keydown) の 2 系統に限定
- 各 `$effect` の cleanup で確実に removeEventListener

### 5.5 Query の所有権
- `createQuery` を hook に入れると getContext の QueryClient が必要。親に残して hook には getter で渡す方が単純。
- **採用**: Query は全て親。hook 入力は plain reactive getter のみ。

### 5.6 mypy / typecheck 影響
- BE 変更なし、FE のみ。`npm run check` で swelte-check + tsc。
- 型契約 `types.ts` を先に書き、各 hook は実装前に interface 準拠を mypy 代わりに担保

## 6. 検証 (Gate 1-4)

- Gate 1: `npm run check` pass
- Gate 2: `npm run test` は vitest 対象テストがなければ skip、Playwright は該当 spec がブラウザで **9/9 pass**
- Gate 3: Playwright MCP で `/annotation-sets/[id]/annotate/[segmentId]` を開き、ドラッグ→species pick→list に反映を確認
- Gate 4: console error 0

## 7. コミット計画

```
(Step 0) test(web): add Playwright smoke for AnnotationEditor (9 tests, incl. readonly)
(Step 1) refactor(web): extract annotation draft hook and centralize keydown in parent
(Step 2) refactor(web): extract annotation mutation hook from AnnotationEditor
```

## 8. Codex レビュー結果サマリ (v2 反映済)

Codex 1st review (2026-04-22) で **NoGo → 3 点修正で Go**:

1. ✅ keydown 責務の一本化: Step 1 から親統一に確定 (§3.4)
2. ✅ readonly 検証ケース追加: Step 0 の test #9 として必須化 (§4 Step 0)
3. ✅ overlay ref の親所有: `bind:this` は親、hook は getter 受取 (§3.1)

追加で Codex が推奨した設計変更:
4. ✅ `pickSpecies` の分岐は親で dispatch: hook は `createFromDraft` / `updateSpeciesOf` を分離公開 (§3.2, §3.3)
5. ✅ `onCreated` に stale-segment ガード: hook 内 `segmentId()` 一致確認 (§3.2)

7論点への Codex 回答:
- 時間原点変換 → Mutation 側で相対変換 (v1 採用案と一致)
- keydown → 親統一 (v2 で確定)
- pickSpecies 分岐 → 親で dispatch (v2 で変更)
- readonly fixture route → 不要、実 status seed で OK (v1 採用案と一致)
- Step 順序 → Draft → Mutation 可、keydown 方針先行が条件
- 楽観更新 → 今回見送り (refactor と同時は risk 高)
- `onCreated` → 設計 OK、stale-segment ガード追加推奨
