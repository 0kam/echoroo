# P2-B: SpectrogramViewer.svelte 分割プラン (v3)

対象: `apps/web/src/lib/components/audio/SpectrogramViewer.svelte` (925 行)
準備済: Playwright smoke test (`0ec0660b`), RAF scheduler 抽出 (`3a22d9ad`)
目標: 3 モジュール抽出で parent を ~350-400 行に縮小。behavior 完全保持。

**v2 改訂ポイント (Codex 1st review):**
- 可変入力は**全て getter `() => value`** で渡す
- 分割順序を **ChunkManager → Interaction → Canvas** に変更
- **Step 0 (事前 PR)** を追加: 型契約、E2E 追加、`rebuildChunks` 一本化
- `dispose()` 契約を明示
- scheduler は Step 3 で Canvas 子に移管

**v3 改訂ポイント (Codex 2nd review):**
- **`requestRedraw` callback を廃止方針で確定** — `chunks` props 駆動の Canvas `$effect` に redraw を一本化。scheduler の実 API は `request()` 引数なしなので `scheduler.request(drawAll)` 等の擬似シグネチャを plan から除去
- **Canvas resize → redraw 漏れ防止** — Canvas 子の redraw `$effect` 依存に `canvasWidth` / `canvasHeight` を明示的に含める
- **Step 0 E2E を 2 件強化** — ① readonly 検証用 fixture route を追加（既存画面に readonly=true のマウント先が無い）② `rebuildChunks` 二重実行の回帰を HTTP リクエスト数 assert で自動検知
- **hook に `disposed` フラグを導入** — dispose 後の async callback（token refresh 待機中の timer、image onload/onerror、retryChunk 継続）を早期 return でガード
- **canvas ref 方式は `bind:this` を採用** — `{@attach}` は codebase に前例なし、利得小

**v3.1 補足 (Codex 3rd review を反映):**
- **`InteractionMode` は `'idle' | 'panning' | 'zooming'` の 3 値**（当初想定した 'pan' / 'zoom-time' / 'zoom-box' ではない）
- **`B` キーは viewport history back 操作**（mode change ではない）。対応するのは parent の `handleViewportBack()` で、Interaction hook 側ではなく親で持つ
- **`onViewportSave` は引数なし `() => void`**（現行実装に統一）
- fixture route (`/__test__/spectrogram-readonly`) には `+page.server.ts` の dev/test guard を実装済み

---

## 1. 現状マップ

### State（所有権別）
| カテゴリ | 変数 | Line | 用途 |
|---|---|---|---|
| Canvas refs | `canvas`, `containerEl` | 59-60 | DOM 参照 |
| Canvas size | `canvasWidth`, `canvasHeight` | 64-65 | viewport 計算 |
| Interaction | `mousePos`, `isDragging`, `dragStart`, `zoomBox` | 68-73 | マウス状態 |
| Chunk | `chunks`, `chunkImages`, `retryTimers`, `tokenRefreshPromise` | 76-87 | 画像ロード管理 |
| Scheduler | `scheduler` (既抽出) | 91 | RAF coalescing |

### 関数（3 モジュール別）
**A. ChunkManager (~180 行)**
- `buildChunkUrl` L100-130 / `rebuildChunks` L134-192 / `scheduleChunkRetry` L201-236
- `retryChunk` L242-260 / `refreshTokenAndRetryErrors` L267-281 / `triggerLazyLoad` L291-319
- Effect: L326-339 (recording/settings → rebuild), L344-348 (viewport → lazyLoad)
- **現行バグ**: `onMount` (L819) と `$effect` (L326) が両方 `rebuildChunks()` を呼び初期二重実行

**B. Canvas (~200 行)**
- `drawAll` L372-384 / `drawSpectrogram` L386-473 / `drawPlayCursor` L475-486
- `drawMouseCrosshair` L488-510 / `drawZoomBox` L512-544 / `drawTimeAxis` L546-596
- `drawFreqAxis` L598-648 / `formatAxisNum` L650-655
- Effect: L351-361 (state → requestRedraw), L364-370 (size sync)

**C. Interaction (~150 行)**
- `getCanvasPos` L661-668 / `handleMouseMove` L670-696 / `handleMouseDown` L698-710
- `handleMouseUp` L712-739 / `handleMouseLeave` L741-748 / `handleDoubleClick` L750-755
- `handleWheel` L757-799 / `handleKeyDown` L801-817

### Callers（props 形状は一切変えない）
- `apps/web/src/lib/components/audio/ClipSpectrogramPlayer.svelte:10`
- `apps/web/src/routes/(app)/projects/[id]/recordings/[recordingId]/+page.svelte:9`

---

## 2. 分割後のアーキテクチャ

```
SpectrogramViewer.svelte (parent, ~350-400 行)
├─ Owns: canvas ref, containerEl ref, canvasWidth, canvasHeight
├─ Template: <canvas bind:this={canvas} on:mousedown={interaction.handleMouseDown} ... />
│   ↑ canvas element と event binding は **parent に残す**（DOM 境界越え最小化）
│
├─ useChunkManager.svelte.ts (~180 行) [Step 1]
│   ├─ Input (all getter):
│   │   recording: () => RecordingDetail
│   │   projectId: () => string
│   │   spectrogramSettings: () => SpectrogramSettings
│   │   viewport: () => SpectrogramWindow
│   │   requestRedraw: () => void
│   ├─ State: chunks, chunkImages, retryTimers, tokenRefreshPromise
│   ├─ Out: {
│   │    get chunks(): SpectrogramChunk[]
│   │    get chunkImages(): HTMLImageElement[]
│   │    refreshTokenAndRetryErrors(): Promise<void>
│   │    dispose(): void
│   │ }
│   ├─ Internal: onDestroy で全 retry timer + image.onload/onerror クリア
│   └─ Effects: rebuild on (recording.id, settings), lazyLoad on viewport
│
├─ useSpectrogramInteraction.svelte.ts (~150 行) [Step 2]
│   ├─ Input (all getter):
│   │   canvas: () => HTMLCanvasElement | undefined
│   │   containerEl: () => HTMLDivElement | undefined
│   │   viewport: () => SpectrogramWindow
│   │   bounds: () => SpectrogramWindow
│   │   canvasWidth: () => number
│   │   canvasHeight: () => number
│   │   spectrogramSettings: () => SpectrogramSettings
│   │   interactionMode: () => InteractionMode
│   │   readonly: () => boolean
│   │   onViewportChange, onViewportSave, onSeek, onModeChange (値で良い — 不変 callback)
│   ├─ State: mousePos, isDragging, dragStart, zoomBox
│   ├─ Out: {
│   │    get mousePos(), get zoomBox(), get isDragging()
│   │    handleMouseMove, handleMouseDown, handleMouseUp, handleMouseLeave,
│   │    handleDoubleClick, handleWheel, handleKeyDown
│   │    dispose(): void
│   │ }
│   └─ 各 handler は canvas() / containerEl() を呼び出して undefined ガード
│
└─ SpectrogramCanvas.svelte (~200 行) [Step 3]
    ├─ Owns: scheduler (parent から引っ越し)
    ├─ Props (getter or $bindable):
    │   canvas: $bindable<HTMLCanvasElement | undefined>  // parent が bind:this で受ける
    │   canvasWidth, canvasHeight, viewport, bounds, chunks, chunkImages,
    │   currentTime, mousePos, zoomBox, interactionMode, spectrogramSettings
    ├─ Template: <canvas bind:this={canvas} class={...} />
    │   ↑ canvas element は子に移動、event handler は親の markup 側で `{@attach}` or `onmount`
    │   で bind（Step 3 で詳細設計。Svelte 5 の event forwarding 方式を採用）
    ├─ Pure render (no state mutation)
    └─ Effects: $effect.pre で size sync → $effect で scheduler.request()
```

### Data flow
- Parent が `canvas` ref を所有（`bind:this` は Canvas 子にしても親に回送）
- `useChunkManager` が `chunks/chunkImages` を所有、parent は getter で読み、子へ pass
- `useSpectrogramInteraction` が `mousePos/zoomBox` を所有、parent は getter で読み、子へ pass
- **Redraw は reactive props 駆動** — Step 3 の SpectrogramCanvas 子 `$effect` が `chunks` / `mousePos` / `zoomBox` / `viewport` / `currentTime` / `interactionMode` / `canvasWidth` / `canvasHeight` を観測して `scheduler.request()` 発火。明示的 `requestRedraw` callback は廃止
- Step 1/2 中は parent 側 `$effect` が chunks / mousePos / zoomBox 等を観測して `scheduler.request()` を呼ぶ（既存挙動と等価）

---

## 3. Step 0: 事前 PR（必須、着手前）

**目的**: 分割本番で頻発するであろう runes / event / race 系の足元固め。

### 0-1. `rebuildChunks` 初期二重実行の解消
- 現状: `onMount` L819 と `$effect` L326 が両方発火し初期 2 回走る
- 対処: `$effect` 一本に統一（`untrack` 済み、初回も確実に走る）。`onMount` の呼出を削除
- **検証**: Playwright で `page.on('request')` により録音ページ初回ロード時の `/spectrogram` エンドポイント呼出数を収集し、同一 chunk が 2 回 fetch されないことを assert（手動 Network 観察ではなく自動回帰検知）

### 0-2. Hook API 型契約を先行導入
- `apps/web/src/lib/components/audio/types.ts` (新規) に下記インターフェース定義:
  - `ChunkManagerInput`, `ChunkManagerApi`
  - `SpectrogramInteractionInput`, `SpectrogramInteractionApi`
  - `SpectrogramCanvasProps`
- まだ実装は移動せず、**型を先行コミット**。これで Step 1-3 の実装は型に合わせるだけ

### 0-3. E2E smoke test 追加（分割前の回帰検出力確保）
`apps/web/tests/e2e/spectrogram.spec.ts` に以下ケースを追加:
- Ctrl+wheel で周波数ズーム、Alt+wheel で時間ズーム、素の wheel で時間 pan
- `X` → `'panning'`, `Z` → `'zooming'` モード切替（`InteractionMode` は `'idle' | 'panning' | 'zooming'` の 3 値）
- `B` → `handleViewportBack()`（モード変更ではなく viewport を履歴スタックから戻す操作）
- `zooming` モードで wheel / ドラッグ → viewport が拡大縮小に収束
- **chunk リクエスト重複なし** (0-1 検証、`page.on('request')` で `/spectrogram` 呼出を集計)

#### readonly 検証用 fixture route
- `apps/web/src/routes/(app)/__test__/spectrogram-readonly/+page.svelte` (新規、dev / test 環境のみ exposed)
- 固定 recording / viewport / bounds を注入し `readonly={true}` で `<SpectrogramViewer />` をマウント
- Playwright で pan / zoom / dblclick を実行し viewport 無変更 + `onViewportChange` 未発火を確認
- `vite.config.ts` で prod ビルドから除外、または `{#if browser && dev}` ガード

3 連続 pass を確認してからコミット。

### Step 0 完了ゲート
- Gate 1: `npm run check` パス
- Gate 2: `npm run test` + 追加 E2E 3 連続 pass
- Gate 3: 手動 Playwright で録音ページを開き、chunk リクエスト波・readonly 動作・modifier wheel・キー切替を目視確認
- 単独 commit（型・テスト・onMount 削除の 3 commit に分割可）

---

## 4. Step 1: `useChunkManager.svelte.ts` 抽出

**ゴール**: chunks / chunkImages / retry / token refresh を hook 化、parent は getter で読む。

### 4-1. 実装仕様
```ts
export interface ChunkManagerInput {
  recording: () => RecordingDetail;
  projectId: () => string;
  spectrogramSettings: () => SpectrogramSettings;
  viewport: () => SpectrogramWindow;
}

export interface ChunkManagerApi {
  readonly chunks: SpectrogramChunk[];
  readonly chunkImages: HTMLImageElement[];
  refreshTokenAndRetryErrors(): Promise<void>;
  dispose(): void;
}

export function useChunkManager(input: ChunkManagerInput): ChunkManagerApi;
```

- `recording()` / `spectrogramSettings()` を読む `$effect` で rebuild
- `viewport()` を読む `$effect` で lazyLoad
- **`requestRedraw` callback は持たない** — image onload/onerror は `chunks` state を更新するだけ。parent（Step 1/2）または Canvas 子（Step 3）の `$effect` が `chunks` を観測して `scheduler.request()` を呼ぶ
- retry timer は Map で所持、`dispose()` で全クリア + `img.onload/onerror = null`
- **`disposed` フラグを private state で持つ** — `dispose()` で `true` 化、以下の各入口で早期 return:
  - image.onload / onerror callback
  - `scheduleChunkRetry` の `setTimeout` callback
  - `retryChunk()` 本体
  - `refreshTokenAndRetryErrors()` の `await` 後
  - `triggerLazyLoad()` 内の非同期 path
- `onDestroy` を hook 内で呼び `dispose()` を実行

### 4-2. parent 側（Svelte Viewer）
```svelte
const chunkMgr = useChunkManager({
  recording: () => recording,
  projectId: () => projectId,
  spectrogramSettings: () => spectrogramSettings,
  viewport: () => viewport,
});

export function refreshTokenAndRetryErrors() {
  return chunkMgr.refreshTokenAndRetryErrors();
}

// Step 1 終了時点の redraw trigger（Step 3 で Canvas 子に移管）
$effect(() => {
  // reactive deps
  chunkMgr.chunks; viewport; currentTime; mousePos; zoomBox; interactionMode;
  scheduler.request();
});
```

- `drawSpectrogram` 等から `chunks` / `chunkImages` を参照する箇所は `chunkMgr.chunks` / `chunkMgr.chunkImages` に置換
- 既存 export `refreshTokenAndRetryErrors` は thin wrapper で互換維持（callers 2 箇所は無変更）

### 4-3. 検証
- Gate 1 + Gate 2（既存 + 0-3 で追加した E2E）3 連続 pass
- Gate 3: `test1` 30 分録音で chunk ロード / リトライ / token refresh（わざと 401 誘発）を確認
- 単独 commit: `refactor(web): extract chunk manager from SpectrogramViewer`

---

## 5. Step 2: `useSpectrogramInteraction.svelte.ts` 抽出

**ゴール**: mouse/wheel/keyboard handler を hook 化。**canvas 要素と event binding は parent に残す**（DOM 境界越えなし）。

### 5-1. 実装仕様
```ts
export interface SpectrogramInteractionInput {
  canvas: () => HTMLCanvasElement | undefined;
  containerEl: () => HTMLDivElement | undefined;
  viewport: () => SpectrogramWindow;
  bounds: () => SpectrogramWindow;
  canvasWidth: () => number;
  canvasHeight: () => number;
  spectrogramSettings: () => SpectrogramSettings;
  interactionMode: () => InteractionMode;  // 'idle' | 'panning' | 'zooming'
  readonly: () => boolean;
  onViewportChange: (vp: SpectrogramWindow) => void;
  onViewportSave?: () => void;             // no-argument callback
  onSeek?: (time: number) => void;
  onModeChange?: (mode: InteractionMode) => void;
}

export interface SpectrogramInteractionApi {
  readonly mousePos: SpectrogramPosition | null;
  readonly zoomBox: { start: ...; end: ... } | null;
  readonly isDragging: boolean;
  handleMouseMove(e: MouseEvent): void;
  handleMouseDown(e: MouseEvent): void;
  handleMouseUp(e: MouseEvent): void;
  handleMouseLeave(): void;
  handleDoubleClick(e: MouseEvent): void;
  handleWheel(e: WheelEvent): void;
  handleKeyDown(e: KeyboardEvent): void;
  dispose(): void;
}
```

- 全 getter は呼出時 evaluation、undefined ガード（特に `canvas()`）
- `mousePos` / `zoomBox` / `isDragging` / `dragStart` は hook 内の `$state`
- Redraw のフック: mousePos / zoomBox 変更時は parent 側の `$effect` が `chunkMgr.chunks` と一緒に観測して `scheduler.request()` を発火
- **`handleKeyDown` の責務**:
  - `X` → `onModeChange('panning')`
  - `Z` → `onModeChange('zooming')`
  - `B` は **hook では処理しない** — viewport history back は親の責務（history stack 管理が hook スコープ外）。親側 `handleKeyDown` / `svelte:window` で拾う既存構造を維持
  - Interaction hook の `handleKeyDown` は `X` / `Z` のみ処理、それ以外は no-op

### 5-2. parent 側
```svelte
const interaction = useSpectrogramInteraction({
  canvas: () => canvas,
  containerEl: () => containerEl,
  viewport: () => viewport,
  bounds: () => bounds,
  canvasWidth: () => canvasWidth,
  canvasHeight: () => canvasHeight,
  spectrogramSettings: () => spectrogramSettings,
  interactionMode: () => interactionMode,
  readonly: () => readonly,
  onViewportChange,
  onViewportSave,
  onSeek,
  onModeChange,
});

// Markup は変更なし（canvas は parent 所有）
<canvas
  bind:this={canvas}
  onmousemove={interaction.handleMouseMove}
  onmousedown={interaction.handleMouseDown}
  ...
/>

$effect(() => {
  // reactive trigger — canvasWidth/Height も含める（resize 時 redraw 保証）
  interaction.mousePos; interaction.zoomBox; interaction.isDragging;
  chunkMgr.chunks;
  viewport; currentTime; interactionMode;
  canvasWidth; canvasHeight;
  scheduler.request();
});
```

### 5-3. 検証
- Gate 1 + Gate 2（readonly / modifier wheel / X,Z,B キー / zoom 挙動を含む）3 連続 pass
- Gate 3: 手動で pan / zoom-time / zoom-freq / dblclick seek / readonly / B による viewport back を一通り触る
- 単独 commit: `refactor(web): extract interaction hook from SpectrogramViewer`

---

## 6. Step 3: `SpectrogramCanvas.svelte` 抽出

**ゴール**: 描画関数 8 個 + scheduler を子に移す。canvas 要素も子に移動、`bind:this` で親に露出。

### 6-1. 実装仕様
```svelte
<!-- SpectrogramCanvas.svelte -->
<script lang="ts">
  interface Props {
    canvas: HTMLCanvasElement | undefined;  // $bindable
    canvasWidth: number;
    canvasHeight: number;
    viewport: SpectrogramWindow;
    bounds: SpectrogramWindow;
    chunks: SpectrogramChunk[];
    chunkImages: HTMLImageElement[];
    currentTime: number;
    mousePos: SpectrogramPosition | null;
    zoomBox: { start: ...; end: ... } | null;
    interactionMode: InteractionMode;
    spectrogramSettings: SpectrogramSettings;
    // event forwarding
    onmousemove?: (e: MouseEvent) => void;
    onmousedown?: (e: MouseEvent) => void;
    onmouseup?: (e: MouseEvent) => void;
    onmouseleave?: (e: MouseEvent) => void;
    ondblclick?: (e: MouseEvent) => void;
    onwheel?: (e: WheelEvent) => void;
    onkeydown?: (e: KeyboardEvent) => void;
  }
  let { canvas = $bindable(), ... }: Props = $props();

  const scheduler = useSpectrogramScheduler(drawAll);

  function drawAll() { ... }
  function drawSpectrogram() { ... }
  // ... 他 6 個

  $effect.pre(() => {
    if (!canvas) return;
    canvas.width = canvasWidth;
    canvas.height = canvasHeight;
  });

  $effect(() => {
    // reactive deps — canvasWidth/Height を含めることで resize 時 redraw 保証
    viewport; currentTime; mousePos; zoomBox; chunks; interactionMode;
    canvasWidth; canvasHeight;
    scheduler.request();
  });

  onDestroy(() => scheduler.dispose());
</script>

<canvas
  bind:this={canvas}
  class="spectrogram-canvas ..."
  onmousemove={onmousemove}
  onmousedown={onmousedown}
  ...
/>
```

### 6-2. parent 側
```svelte
<SpectrogramCanvas
  bind:canvas
  canvasWidth={canvasWidth}
  canvasHeight={canvasHeight}
  viewport={viewport}
  bounds={bounds}
  chunks={chunkMgr.chunks}
  chunkImages={chunkMgr.chunkImages}
  currentTime={currentTime}
  mousePos={interaction.mousePos}
  zoomBox={interaction.zoomBox}
  interactionMode={interactionMode}
  spectrogramSettings={spectrogramSettings}
  onmousemove={interaction.handleMouseMove}
  onmousedown={interaction.handleMouseDown}
  onmouseup={interaction.handleMouseUp}
  onmouseleave={interaction.handleMouseLeave}
  ondblclick={interaction.handleDoubleClick}
  onwheel={interaction.handleWheel}
  onkeydown={interaction.handleKeyDown}
/>
```

- scheduler は子側で生成（`drawAll` と同居）、親は import を削除
- Step 2 で parent に書いた redraw `$effect` は削除（子側の effect が props 変更を観測）
- **ChunkManager から `requestRedraw` callback を完全に除去**（v3 方針確定）。image onload で `chunks` state 更新 → Canvas 子 `$effect` が props 経由で reactive に拾う → scheduler.request() 発火

### 6-3. 検証
- Gate 1 + Gate 2 3 連続 pass
- Gate 3: 描画フレーム落ちがないか（scheduler 移動の影響）、canvas resize（window resize）が即時反映されるかを手動確認
- 単独 commit: `refactor(web): extract SpectrogramCanvas component`

---

## 7. 主な難所と対処（改訂）

| # | 難所 | 対処 |
|---|---|---|
| D1 | chunks / chunkImages の parallel array 同期 | useChunkManager 内部に閉じ込め、parent は getter で read-only |
| D2 | Redraw effect の依存チェーン分断 | Step 3 で Canvas 子の `$effect` に集約、deps は props 経由で自動 reactive |
| D3 | Canvas resize のタイミング | Canvas 子で `$effect.pre` により size sync → `$effect` で redraw（phase 分離） |
| D4 | canvas ref が undefined な瞬間 | 全 hook で canvas を getter で受け、undefined ガード |
| D5 | token refresh thundering herd | useChunkManager 内 private state で dedup 維持 |
| **D6 (新)** | **Hook 入力の reactivity 切れ** | **可変入力は全 getter (`() => value`)**。callback (onViewportChange 等) は値で可 |
| **D7 (新)** | **Canvas DOM 境界越え** | **Step 1-2 は canvas を parent markup に残す**。Step 3 で `$bindable` + event props で一度に移管 |
| **D8 (新)** | **scheduler 所有権の一貫性** | **Step 3 で scheduler を Canvas 子側に移す**。Step 1-2 中は parent 所有のまま使う |
| **D9 (新)** | **rebuildChunks 初期二重実行** | **Step 0 で `onMount` 呼出を削除**、`$effect` 一本化 |
| **D10 (新)** | **cleanup 漏れ** | 各 hook で `dispose()` を export + 内部 `onDestroy` で自動呼出の両方 |
| **D11 (v3)** | **dispose 後の async callback 継続** | hook 内 `disposed` フラグで token refresh / retry timer / image onload の各入口で早期 return |
| **D12 (v3)** | **Canvas resize 時の redraw 漏れ** | Canvas redraw `$effect` 依存に `canvasWidth` / `canvasHeight` を明示的に含める |

---

## 8. リスクと緩和（改訂）

| リスク | 発生シナリオ | 緩和 |
|---|---|---|
| Effect 発火順序変化 | resize effect と redraw effect が分離後に逆転 | `$effect.pre` で size を先に、smoke test で canvas 描画確認 |
| Reactivity 切れ | getter を忘れて値渡しした input | 型契約（Step 0）で `() => T` を強制、`never`-style で違反検知 |
| Image onload → redraw 未発火 | chunks state 更新の reactive 伝搬が切れる | Canvas 子 `$effect` 依存に `chunks` を明示、getter 渡しで proxy 境界を維持 |
| dispose 後に timer が発火 | retry timer が dispose 後に実行、または `await` 中に component 破棄 | `disposed` フラグで各入口で早期 return、`clearTimeout` + `img.onload = null` で多重防御 |
| Callee 2 箇所の props 形状 break | SpectrogramViewer の public API 変更 | **props 形状は一切変更しない** |
| Event handler が canvas に届かない | Step 3 で event props の書き忘れ | 型契約で全 7 event を必須 or optional 明示、Playwright で全網羅 |
| Scheduler 二重所有 | Step 3 移管時に parent 側にも残る | Step 3 commit で parent 側 `useSpectrogramScheduler` import を削除、diff で確認 |

---

## 9. 完了ゲート（CLAUDE.md 準拠）

各 Step で以下を通過:
- Gate 1: `npm run check` (web) パス
- Gate 2: `npm run test` (vitest) パス、`npx playwright test tests/e2e/spectrogram.spec.ts` 3 連続 pass
- Gate 3: Playwright MCP でテストアカウント (`test@echoroo.app`) + test1 30 分録音で canvas 描画 / hover / pan / zoom / dblclick / readonly / modifier wheel / キー切替を手動確認、console error 0
- Gate 4: 完了報告テンプレート遵守

---

## 10. 見積

| Step | 内容 | 見積 |
|---|---|---|
| 0 | 型契約 + E2E 追加 + rebuildChunks 一本化 | 0.5 セッション |
| 1 | useChunkManager 抽出 | 1 セッション |
| 2 | useSpectrogramInteraction 抽出 | 1 セッション |
| 3 | SpectrogramCanvas 抽出 + scheduler 移管 | 1 セッション |
| 合計 | | 3-3.5 セッション、Step ごとに独立 commit |

---

## 11. 確定した設計方針（v3）

- **`requestRedraw` callback は不採用** — ChunkManager は `chunks` state 更新のみ、redraw は Canvas 子 `$effect` の reactive 伝搬に一任（Step 1/2 中は parent `$effect` が暫定）
- **canvas ref 方式は `bind:this`** — `{@attach}` は codebase 前例なし
- **Canvas 子は event handler を forwarding only** — 親から event props を受けて内部 `<canvas>` に流すだけ
- **scheduler 所有権は Canvas 子** — Step 3 で parent から移管、以降 parent は scheduler を保持しない
