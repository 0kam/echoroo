# P2-B: SearchSessionDetail.svelte 分割プラン (v3)

対象: `apps/web/src/lib/components/search/SearchSessionDetail.svelte` (691 行)
準備: Playwright smoke test **未整備** — Step 0 で先行整備
目標: 2 hook + 1 コンポーネント抽出で parent を **265–320 行**に縮小。behavior 完全保持。

前回 P2-B AnnotationEditor 分割のパターン踏襲:
- hook = `.svelte.ts` + getter 渡し (`() => T`) で reactivity 維持
- callback は `onXxx?: (arg) => void` 形式で optional
- hook 内部に `disposed` フラグ + `dispose()` export
- async 関数は全 `await` 後に `isStale(capturedPid, capturedSid)` ガード
- Step 0 で Playwright smoke 先行、分割は behavior-preserving

## 0. AnnotationEditor 完了ステータス

P2-B AnnotationEditor 分割は **完了** (コミット 0c6833a9 まで 4 コミット、9/9 E2E pass)。
`plan.md` をこの SearchSessionDetail プランで上書きし次フェーズに入る。

## 0.1 Codex review 履歴

- **v1 (2026-04-23)**: Conditional Go
  - High-1: stale-navigation ガードが `getSearchSession` 後だけ → `fetchDataset` / `loadSessionModels` / `finally` にも必要 (旧 session の dataset/models が新 session と混在する)
  - High-2: Test 6/7 内部矛盾 (click 前提 vs 「click しない」)、親 `handleRerunFromDetail` は URL 更新しないので URL assert 不成立
  - Med-1: SessionActionPanel に reconstruction 丸渡しは広すぎ、`dispose/setSession` まで子が触れる。`onBack` も未使用
  - Med-2: 型契約 `readonly string` と現行 `statusLabel()` (関数呼出) の整合未確定
  - Med-3: seed rename 復元を `afterAll` のみではなく test 内 try/finally
  - Low-1〜5: capturedSessionId は低コスト防御、$effect の立ち上がりエッジ条件、親行数レンジ化、renameInputEl Panel 側は妥当、Test 1 aria-label ズレ
- **v2 (2026-04-23)**: 上記全て反映 → 再 Conditional Go
  - High-1: `$state` を値で return するとスナップショット化 → getter 公開 (`get x() { return x; }`) を明記
  - High-2: Test 7 が fork/edit 差分を実質検証できない (両方とも new-search mode 遷移で UI 同型) → Search/Re-run ボタンも click して API route (`POST /batch` vs `PUT /rerun`) を mock で判定
  - Med-1: isStale が sessionId のみ → projectId + sessionId 両方で判定
  - Med-2: loadSessionModels 開始時に sessionModels を空初期化
  - Med-3: rename 丸渡しは dispose まで子が触れる → Pick で narrow
  - Med-5: Test 6/7 locator を plan で確定
- **v3 (本 doc)**: 上記全て反映

## 1. 対象ファイル分析

### 1.1 Script セクション (L1–338: 338 行)

| 行 | カテゴリ | 変数 / 関数 |
|---|---|---|
| L40–107 | 状態 | `session`, `isLoading`, `loadError`, `reconstructedSpecies`, `sessionModels`, `_isLoadingModels`, `_modelsLoadError`, `trainDialogSpeciesKey`, `trainDialogSpeciesMeta`, `isExportingRecordings`, `datasetName`, `isRenaming`, `renameValue`, `isSavingRename`, `renameError`, `renameInputEl` |
| L64–75 | 関数 | `loadSessionModels(pid, sid)` |
| L77–97 | 関数 | `handleCreateModelSuccess()`, `handleExportRecordings()` |
| L113–199 | 関数 | `loadSession(pid, sid)` — fetch + species 再構築 |
| L202–205 | `$effect` | `loadSession` + `loadSessionModels` を実行 |
| L211–260 | `$derived` | `statusLabel`, `statusColor`, `statusDotColor`, `sessionName`, `formattedDate`, `searchDuration` — **全て関数ラッパ形式** `$derived(() => ...)`、使用側は `statusLabel()` と呼出 |
| L266–302 | 関数 | `startRename()`, `cancelRename()`, `saveRename()`, `handleRenameKeydown()` |
| L308–337 | 関数 | `handleEditRerun()`, `handleFork()` |

### 1.2 Markup セクション (L339–691: 353 行)

| 行 | 内容 |
|---|---|
| L340–354 | 戻るボタン (text: `m.search_back_to_sessions()`, aria-label **なし**) |
| L356–391 | loading skeleton / error state |
| L393–521 | セッションヘッダカード (名前・リネーム UI・ステータス・エクスポートボタン) |
| L523–532 | `ReferenceSoundsPanel` (reconstructedSpecies がある場合) |
| L534–570 | アクションボタン (Fork / Edit & Re-search) |
| L572–691 | Results / Linked Models / CreateModelFromSessionDialog |

### 1.3 親コンポーネント `+page.svelte` との契約

- `handleSelectSession(id)`: viewMode = 'detail', URL に `?session=id` を `history.replaceState` で反映 (**reactive ではない**)
- `handleBackToList()`: viewMode = 'list', URL から `session` param 削除
- `handleRerunFromDetail(species, editSessionId, datasetId?)`: viewMode = 'new-search' に変更、`editingSessionId` セット、**URL は更新しない**
- `handleSearch()`: 実際に search job を起動するのは new-search mode で実行ボタン押下時

### 1.4 依存関係まとめ

- **API**: `getSearchSession`, `updateSearchSession`, `exportSearchSessionRecordingsCSV`, `fetchCustomModels`, `fetchDataset` (dynamic import), `getReferenceAudioUrl`
- **型**: `SearchSession`, `TargetSpecies`, `SoundSource`, `SpeciesMatchResult`, `CustomModelListItem`
- **ユーティリティ**: `generateId`, `getSearchSessionStatusLabel/TextClass/DetailDotClass`, `getLocale`, `localizeHref`, `goto`
- **TanStack Query**: **未使用** (raw fetch + `$state`)
- **onMount / onDestroy**: **未使用**
- **window listener**: **なし**
- **`$effect`**: 1 箇所のみ (L202–205)

## 2. 抽出するモジュール一覧

| ファイル (新規) | 行数目安 | 役割 |
|---|---|---|
| `types.ts` | ~65 行 | hook 型契約 |
| `useSessionReconstruction.svelte.ts` | ~150 行 | session fetch + species 再構築 + derived + isStale ヘルパ |
| `useSessionRename.svelte.ts` | ~80 行 | rename state + handlers |
| `SessionActionPanel.svelte` | ~220 行 | ヘッダカード + アクションボタン markup |
| `tests/e2e/search-session-detail.spec.ts` | ~380 行 | Playwright smoke (9 テスト) |

**修正:**
- `SearchSessionDetail.svelte`: 691 行 → **265–320 行** (hard gate ではなく目安レンジ)

## 3. 型契約 (types.ts)

ファイルパス: `apps/web/src/lib/components/search/types.ts`

**方針** (Codex Med-2 / v2 High-1 への回答):
- `$derived(() => ...)` を hook 内で保持し、**外部には関数呼出 (`statusLabel()`) で expose**
- なぜ getter 形式か: 現行コード (L438/459/465-467/480/483/578 等) が `statusLabel()` で呼んでいる。変更範囲最小化のため踏襲
- **state 系 (`session`, `isLoading`, `loadError`, `reconstructedSpecies`, `sessionModels`, `datasetName`) は getter 公開必須** — 実装例:
  ```typescript
  return {
    get session() { return session; },
    get isLoading() { return isLoading; },
    // ...
  };
  ```
  - **理由**: `$state` を値として `return { session }` すると**スナップショット化されて reactivity が切れる** (Svelte 5 runes の仕様)。getter で wrap すると bare read 時に `$state` の proxy が reactivity を保つ
  - `useAnnotationDraft.svelte.ts` L154-162 でも同パターンを採用済
- `SessionRenameHookApi` は DOM 非依存 (`renameInputEl` は含めない)

```typescript
import type { SearchSession, TargetSpecies } from '$lib/types/search';
import type { CustomModelListItem } from '$lib/types/custom-model';

// --- useSessionReconstruction ---

export interface SessionReconstructionInput {
  projectId: () => string;
  sessionId: () => string;
}

/**
 * Reactive state is exposed in two shapes:
 *   - `$state`-backed fields (session, isLoading, loadError, reconstructedSpecies,
 *     sessionModels, datasetName) are bare readonly props. Svelte 5 tracks them.
 *   - `$derived` fields are function getters `() => T` that the consumer calls
 *     (e.g. `reconstruction.statusLabel()`), matching existing call sites.
 */
export interface SessionReconstructionHookApi {
  readonly session: SearchSession | null;
  readonly isLoading: boolean;
  readonly loadError: string | null;
  readonly reconstructedSpecies: TargetSpecies[];
  readonly sessionModels: CustomModelListItem[];
  readonly datasetName: string | null;
  readonly statusLabel: () => string;
  readonly statusColor: () => string;
  readonly statusDotColor: () => string;
  readonly sessionName: () => string;
  readonly formattedDate: () => string;
  readonly searchDuration: () => number;
  setSession(s: SearchSession): void;
  dispose(): void;
}

// --- useSessionRename ---

export interface SessionRenameInput {
  session: () => SearchSession | null;
  projectId: () => string;
  getDisplayName: () => string;
  onRenameSuccess: (updated: SearchSession) => void;
}

export interface SessionRenameHookApi {
  readonly isRenaming: boolean;
  readonly renameValue: string;
  readonly isSavingRename: boolean;
  readonly renameError: string | null;
  setRenameValue(v: string): void;
  startRename(): void;
  cancelRename(): void;
  saveRename(): Promise<void>;
  handleRenameKeydown(e: KeyboardEvent): void;
  dispose(): void;
}
```

## 4. フック設計 — useSessionReconstruction

ファイルパス: `apps/web/src/lib/components/search/useSessionReconstruction.svelte.ts`

### 4.1 責務

- `getSearchSession(projectId, sessionId, getLocale())` を呼び `session` をセット
- `data.parameters?.dataset_id` があれば `fetchDataset()` でデータセット名を解決 (failure は無視)
- `data.species_config` から `TargetSpecies[]` を再構築 (L136–193 のロジック丸ごと移動)
- `fetchCustomModels(projectId, { search_session_id: sessionId })` で `sessionModels` をセット
- 一つの `$effect` で `loadSession` + `loadSessionModels` を呼ぶ (L202–205 相当)
- 6 つの `$derived` 値を関数形式 (`() => T`) で expose
- `setSession(s)` メソッドで rename hook の `onRenameSuccess` から session を更新
- `disposed` フラグ + `dispose()` export

### 4.2 stale-navigation ガード (Codex v1 High-1 + v2 Med-1 + Med-2 対応)

**`isStale(capturedPid, capturedSid)` ヘルパ**を hook 内 private 関数として定義し、**projectId + sessionId 両方で判定**。全 `await` 後と `finally` で適用:

```typescript
function isStale(capturedPid: string, capturedSid: string): boolean {
  return disposed || input.projectId() !== capturedPid || input.sessionId() !== capturedSid;
}

async function loadSession(pid: string, sid: string) {
  const capturedPid = pid;
  const capturedSid = sid;
  isLoading = true;
  loadError = null;
  session = null;
  reconstructedSpecies = [];
  datasetName = null;
  try {
    const data = await getSearchSession(pid, sid, getLocale());
    if (isStale(capturedPid, capturedSid)) return;
    session = data;

    // Species 再構築 (同期処理なので stale check 不要、でも早期 return 済み)
    reconstructedSpecies = reconstructFromConfig(data);

    // Dataset name (別 await あり、再度 stale check)
    if (data.parameters?.dataset_id) {
      try {
        const { fetchDataset } = await import('$lib/api/datasets');
        if (isStale(capturedPid, capturedSid)) return;
        const dataset = await fetchDataset(pid, data.parameters.dataset_id);
        if (isStale(capturedPid, capturedSid)) return;
        datasetName = dataset.name;
      } catch {
        if (isStale(capturedPid, capturedSid)) return;
        // Silent fail — dataset name is optional
      }
    }
  } catch (e) {
    if (isStale(capturedPid, capturedSid)) return;
    loadError = e instanceof Error ? e.message : 'Failed to load session';
  } finally {
    if (!isStale(capturedPid, capturedSid)) isLoading = false;
  }
}

async function loadSessionModels(pid: string, sid: string) {
  const capturedPid = pid;
  const capturedSid = sid;
  isLoadingModels = true;
  modelsLoadError = null;
  sessionModels = []; // v2 Med-2: 開始時に空初期化 (旧 session のモデル残留を防ぐ)
  try {
    const models = await fetchCustomModels(pid, { search_session_id: sid });
    if (isStale(capturedPid, capturedSid)) return;
    sessionModels = models;
  } catch (e) {
    if (isStale(capturedPid, capturedSid)) return;
    modelsLoadError = e instanceof Error ? e.message : 'Failed to load models';
  } finally {
    if (!isStale(capturedPid, capturedSid)) isLoadingModels = false;
  }
}
```

**条件優先順位**: `disposed` を先に確認し、次に `projectId` / `sessionId` mismatch を確認。`disposed` は必須 (hook 破棄後に state 書き込むと leak)、id mismatch は race 保護。全て必要。

### 4.3 入力 / 出力

```typescript
export function useSessionReconstruction(input: SessionReconstructionInput): SessionReconstructionHookApi
```

## 5. フック設計 — useSessionRename

ファイルパス: `apps/web/src/lib/components/search/useSessionRename.svelte.ts`

### 5.1 責務

- `isRenaming`, `renameValue`, `isSavingRename`, `renameError` の `$state`
- `startRename()`: `renameValue = input.getDisplayName()`, `isRenaming = true`
- `cancelRename()`: `isRenaming = false`, `renameError = null`
- `saveRename()`: `updateSearchSession(projectId, session.id, renameValue.trim())` → 成功なら `input.onRenameSuccess(updated)` 発火
- `handleRenameKeydown(e)`: Enter → `saveRename()`, Escape → `cancelRename()`
- `setRenameValue(v)`: `oninput` event から呼ぶ (bind:value の代替)
- `disposed` ガード: `await updateSearchSession(...)` 後に `if (disposed) return;`
- **capturedSessionId pattern** (Codex Low-1 対応): 必須ではないが低コスト防御として実装。`saveRename()` 呼出時に `session()?.id` を snapshot、await 後に `session()?.id !== captured` なら `onRenameSuccess` skip。状態フラグ (`isSavingRename`) のリセットは current session 関係なく行う

### 5.2 renameInputEl の focus (Codex Low-2 + Low-4 対応)

`renameInputEl` DOM ref は **SessionActionPanel.svelte 内のローカル `$state`** として保持 (hook は DOM を知らない)。

**立ち上がりエッジのみ focus する** ($effect が isRenaming 以外の原因で再実行されても再 focus しない):

```typescript
// SessionActionPanel.svelte
let renameInputEl = $state<HTMLInputElement | null>(null);
let prevIsRenaming = $state(false);

$effect(() => {
  const now = props.rename.isRenaming;
  if (now && !prevIsRenaming) {
    renameInputEl?.focus();
    renameInputEl?.select();
  }
  prevIsRenaming = now;
});
```

現行 L272 の `setTimeout(..., 0)` は `$effect` が DOM 更新後に実行されるため不要。

### 5.3 入力 / 出力

```typescript
export function useSessionRename(input: SessionRenameInput): SessionRenameHookApi
```

## 6. コンポーネント設計 — SessionActionPanel

ファイルパス: `apps/web/src/lib/components/search/SessionActionPanel.svelte`

### 6.1 Props (Codex Med-1 対応)

**変更**: reconstruction hook 丸渡しではなく、**必要な値と callback のみ**を個別 props として渡す。`dispose/setSession/onBack` は含めない (未使用)。

```typescript
import type { Snippet } from 'svelte';
import type { SearchSession } from '$lib/types/search';
import type { SessionRenameHookApi } from './types';

interface Props {
  session: SearchSession;

  // 再構築値 (getter 形式で reactive 維持)
  statusLabel: () => string;
  statusColor: () => string;
  statusDotColor: () => string;
  sessionName: () => string;
  formattedDate: () => string;
  searchDuration: () => number;
  datasetName: string | null;
  reconstructedSpecies: { length: number }; // または TargetSpecies[]
  hasEditableRerun: boolean; // reconstructedSpecies.length > 0 && status === 'completed'

  // rename hook (v2 Med-3: dispose を子に露出しないよう Pick で narrow)
  rename: Pick<SessionRenameHookApi,
    'isRenaming' | 'renameValue' | 'isSavingRename' | 'renameError' |
    'setRenameValue' | 'startRename' | 'cancelRename' | 'saveRename' | 'handleRenameKeydown'
  >;

  // 親側アクション
  isExportingRecordings: boolean;
  onExportRecordings: () => void;
  onEditRerun: () => void;
  onFork: () => void;

  // ReferenceSoundsPanel を snippet で受け取る (親が species/modelName を知っている)
  referenceAudio?: Snippet;
}
```

### 6.2 markup 構造

```svelte
<!-- ヘッダカード (L393-521 相当) -->
<div class="rounded-lg border ...">
  <!-- 名前 + inline rename UI -->
  <!-- ステータス + meta row (datasetName, model_name, searchDuration) -->
  <!-- エクスポートボタン -->
  <!-- failed error message -->
</div>

<!-- ReferenceSoundsPanel (snippet 経由) -->
{#if referenceAudio}
  {@render referenceAudio()}
{/if}

<!-- アクションボタン (L534-570 相当) -->
{#if hasEditableRerun}
  <div class="flex items-center justify-end gap-2">
    <!-- Fork ボタン -->
    <!-- Edit & Re-search ボタン -->
  </div>
{/if}
```

rename input は `value={rename.renameValue}` + `oninput={(e) => rename.setRenameValue(e.currentTarget.value)}` で bind:value を使わない (hook が DOM 非依存のため)。

## 7. SearchSessionDetail の最終形

スクリプト ~100 行、markup ~200 行、合計 **265–320 行目安** (hard gate なし)。

### 7.1 Script 骨格

```typescript
const reconstruction = useSessionReconstruction({
  projectId: () => projectId,
  sessionId: () => sessionId,
});

const rename = useSessionRename({
  session: () => reconstruction.session,
  projectId: () => projectId,
  getDisplayName: () => reconstruction.sessionName(),
  onRenameSuccess: (updated) => reconstruction.setSession(updated),
});

onDestroy(() => {
  reconstruction.dispose();
  rename.dispose();
});

// trainDialogSpeciesKey, trainDialogSpeciesMeta は親に残す
// handleCreateModelSuccess, handleExportRecordings, handleEditRerun, handleFork も親に残す
// Back button は親の markup 直接
```

### 7.2 Markup 骨格

```svelte
<div class="space-y-6">
  <!-- 戻るボタン (親に残す、変更なし) -->

  {#if reconstruction.isLoading}
    <!-- loading skeleton -->
  {:else if reconstruction.loadError}
    <!-- error state -->
  {:else if reconstruction.session}
    <SessionActionPanel
      session={reconstruction.session}
      statusLabel={reconstruction.statusLabel}
      statusColor={reconstruction.statusColor}
      statusDotColor={reconstruction.statusDotColor}
      sessionName={reconstruction.sessionName}
      formattedDate={reconstruction.formattedDate}
      searchDuration={reconstruction.searchDuration}
      datasetName={reconstruction.datasetName}
      reconstructedSpecies={reconstruction.reconstructedSpecies}
      hasEditableRerun={reconstruction.session.status === 'completed' && reconstruction.reconstructedSpecies.length > 0}
      {rename}
      {isExportingRecordings}
      onExportRecordings={handleExportRecordings}
      onEditRerun={handleEditRerun}
      onFork={handleFork}
    >
      {#snippet referenceAudio()}
        {#if reconstruction.reconstructedSpecies.length > 0}
          <ReferenceSoundsPanel
            {projectId}
            species={reconstruction.reconstructedSpecies}
            modelName={reconstruction.session.model_name}
            onSpeciesChange={() => {}}
            readonly={true}
          />
        {/if}
      {/snippet}
    </SessionActionPanel>

    <!-- Results / Linked Models / CreateModelFromSessionDialog (変更なし) -->
  {/if}
</div>
```

## 8. E2E テスト計画 (Step 0)

ファイルパス: `apps/web/tests/e2e/search-session-detail.spec.ts`

### 8.1 定数

```typescript
const BASE_URL = 'http://localhost:3000';
const API_BASE = 'http://localhost:8002';
const TEST_PROJECT_ID = '6ed4e592-87ca-4fa7-a384-c64ca6bfeec5';
const TEST_EMAIL = 'test@echoroo.app';
const TEST_PASSWORD = 'N6Wz0IJXsQc4';
```

### 8.2 Seed 戦略 (Codex Med-3 対応)

新規セッション作成はしない (ML 計算が必要)。`beforeAll` で:

1. `fetchLoginCredentials()` で `accessToken` + `refreshTokenCookie` 取得 (annotation-editor.spec.ts 同パターン、429 retry 付き)
2. `GET /api/v1/projects/{TEST_PROJECT_ID}/search/sessions?limit=50` で既存セッション一覧取得
3. **deterministic 選定**: `status === 'completed' && species_config !== null && result_count > 0` を満たすセッションを **id (ULID/UUID) で昇順 sort**、先頭を `testSessionId` に採用
4. 選定後、`GET /sessions/{testSessionId}` で **ORIGINAL_NAME** を記録 (rename 復元用)
5. 環境変数 override: `E2E_SEARCH_SESSION_ID` が設定されていれば優先 (手動で特定 session を fix 可能)
6. 見つからない場合は `test.skip()` で全テストをスキップ

**rename 復元方針** (Codex Med-3):
- `afterAll` には**依存しない**
- Test 3 (rename save) 内で `try/finally` を使い、rename 完了後に必ず `PATCH /sessions/{id}` で `ORIGINAL_NAME` に戻す
- `afterAll` は最終防御として念のため残すが、test 内 finally が primary

テスト URL: `/en/projects/{TEST_PROJECT_ID}/search?session={testSessionId}`

### 8.3 テストケース (9 個)

| # | テスト名 | 検証内容 |
|---|---|---|
| 1 | session loads | Back to Sessions ボタン (`getByRole('button', { name: /Back to Sessions/i })` で **text locator**) + ヘッダカード表示。loading spinner 消える |
| 2 | species reconstruction | `ReferenceSoundsPanel` が表示され、species 名が session.species_config と一致 |
| 3 | rename save | try/finally で: pencil click → input 表示 → 新名前入力 → Save → ヘッダに新名前 → `PATCH /sessions/{id}` を `page.route` で intercept して request body を assert。finally で ORIGINAL_NAME に PATCH で復元 |
| 4 | rename cancel | pencil click → Cancel → input が消え元名前が表示されたまま |
| 5 | export CSV | Export CSV ボタン click → `page.waitForEvent('download')` で download trigger 確認 OR `GET /export-recordings` の route mock |
| 6 | fork (click + run) | Fork ボタン click → new-search mode 遷移 (locator: `getByRole('heading', { name: /Reference Sounds/i })` で anchor)。`page.route('**/api/v1/projects/*/search/batch', fulfill stub response)` で POST をモック → "Search" button click → mock が **POST /search/batch** を受け取ったか assert (route.request().method === 'POST' かつ URL が /batch で終わる)。stub で 200 + `{ job_id: 'stub' }` 返却 (実 job は作らない) |
| 7 | edit & re-search (click + run) | "Edit & Re-search" ボタン click → new-search mode 遷移。`page.route('**/api/v1/projects/*/search/sessions/*/rerun', fulfill stub response)` で PUT をモック → "Re-run" button click → mock が **PUT /rerun** を受け取ったか assert。fork (POST /batch) と edit (PUT /rerun) の**差分を API route で検証** (UI だけでは区別不能のため) |
| 8 | train dialog open/close | Train Model ボタン click → `CreateModelFromSessionDialog` 開く → `aria-label="Close dialog"` click → 閉じる |
| 9 | console errors = 0 | `suiteConsoleErrors` が空 (404 audio asset error はフィルタ) |

**Test 6/7 補足** (v1 High-2 + v2 High-2 / Med-5 対応):
- 元案の「URL assert」は `handleRerunFromDetail` が URL を更新しないため成立しない
- mode 遷移 UI だけでは fork/edit 両方とも同じ new-search 画面に遷移するため**差分が検証できない**
- **最終解**: mode 遷移 UI を anchor locator として確認 + その後 Search/Re-run ボタンを click して**API route (POST /batch vs PUT /rerun) を page.route() で intercept して判定**
- stub response を返すことで実際の search job は作成せず、assert のみ実行
- **locator は plan で確定**: `getByRole('heading', { name: /Reference Sounds/i })` を anchor に使う (SearchSpeciesPicker / ReferenceSoundsPanel いずれにも存在する見出し)。Step 0 実装時に実ヘッダ文言を `messages/en.json` で検証

### 8.4 共有 page / context パターン

annotation-editor.spec.ts と同パターン:
- `sharedBrowser`, `sharedContext`, `sharedPage` を suite 単位で共有
- `sharedContext.addCookies([{ name: 'refresh_token', value: refreshTokenCookie, domain: 'localhost', path: '/' }])`
- `suiteConsoleErrors: string[]` に page console error を蓄積、テスト #9 でアサート
- 404 audio asset error は filter (ReferenceSoundsPanel が存在しない reference audio を fetch した時に出る)

## 9. 実装ステップ

### Step 0 — Playwright smoke 整備 (1 commit)

- `apps/web/tests/e2e/search-session-detail.spec.ts` 新規作成 (§8)
- 分割前の現状で 9/9 green を確認してから commit
- **Acceptance Criteria**: 3 連続 pass で flaky なし、console error 0
- **Rollback**: Step 0 のみ commit 削除で元通り (分割未着手)

### Step 1 — types.ts + useSessionReconstruction 抽出 (1 commit)

- `apps/web/src/lib/components/search/types.ts` 新規作成 (§3)
- `useSessionReconstruction.svelte.ts` 新規作成 (§4)
  - `loadSession`, `loadSessionModels`, `$effect`, 6 `$derived`, `setSession`, `dispose`, `isStale` を移動
  - **全 `await` 後に `isStale(capturedPid, capturedSid)` 適用**
- `SearchSessionDetail.svelte` 修正: `const reconstruction = useSessionReconstruction(...)` に切り替え、derived 呼出は `reconstruction.statusLabel()` 形式
- E2E 9/9 green を維持して commit
- **Acceptance Criteria**: npm run check pass、E2E 9/9 pass 3 連続
- **Rollback**: `git revert` 1 commit

### Step 2 — useSessionRename 抽出 (1 commit)

- `useSessionRename.svelte.ts` 新規作成 (§5)
  - rename state + 4 ハンドラ + `setRenameValue` + capturedSessionId pattern を移動
- `SearchSessionDetail.svelte` 修正: `const rename = useSessionRename(...)` に切り替え
- E2E 9/9 green を維持して commit
- **Acceptance Criteria**: npm run check pass、E2E 9/9 pass 3 連続、rename save/cancel/keydown が全て動作
- **Rollback**: `git revert` 1 commit

### Step 3 — SessionActionPanel 抽出 (1 commit)

- `SessionActionPanel.svelte` 新規作成 (§6)
  - ヘッダカード (L393–521) + アクションボタン (L534–570) を移動
  - `referenceAudio` snippet prop 追加
  - rename input focus は `$effect` で rising edge のみ
- `SearchSessionDetail.svelte` 修正: `SessionActionPanel` を使用、snippet で `ReferenceSoundsPanel` を渡す
- markup が ~200 行に縮小 (Back button は親に残す)
- E2E 9/9 green を維持して commit
- **Acceptance Criteria**: npm run check pass、E2E 9/9 pass 3 連続
- **Rollback**: `git revert` 1 commit

## 10. 各 Step の Gate チェック

| Gate | 内容 | Step 0 | Step 1 | Step 2 | Step 3 |
|---|---|---|---|---|---|
| Gate 1 | `npm run check` | — (テストのみ) | ✅ | ✅ | ✅ |
| Gate 2 | E2E 9/9 pass 3 連続 | ✅ 初回 baseline | ✅ | ✅ | ✅ |
| Gate 3 | Playwright MCP 手動ブラウザ検証 | — | 最終 Step 後に実施 | — | ✅ |
| Gate 4 | console error 0 | ✅ | ✅ | ✅ | ✅ |

## 11. コミットシーケンス

```
c0c3bf7a^ (現 HEAD)
 ├─ docs: add P2-B SearchSessionDetail split plan (v2)
 ├─ test(web): add Playwright smoke for SearchSessionDetail (9 tests)
 ├─ refactor(web): extract useSessionReconstruction hook from SearchSessionDetail
 ├─ refactor(web): extract useSessionRename hook from SearchSessionDetail
 └─ refactor(web): extract SessionActionPanel from SearchSessionDetail
```

## 12. 行数見積もり

| ファイル | Before | After |
|---|---|---|
| `SearchSessionDetail.svelte` | 691 | **265–320** (目安レンジ) |
| `types.ts` (新規) | — | ~65 |
| `useSessionReconstruction.svelte.ts` (新規) | — | ~150 |
| `useSessionRename.svelte.ts` (新規) | — | ~80 |
| `SessionActionPanel.svelte` (新規) | — | ~220 |
| `search-session-detail.spec.ts` (新規) | — | ~380 |

行数は hard gate にしない — 挙動保持と contract 明確性を優先。

## 13. リスクと緩和策

### 13.1 stale fetch の上書き (v1 High-1 / v2 Med-1 / Med-2 解決済)

§4.2 で `isStale(capturedPid, capturedSid)` を全 await 後と finally で適用。`loadSession` / `loadSessionModels` / `fetchDataset` import / `fetchDataset` 呼出の 4 箇所 + projectId 変化にも対応。`loadSessionModels` 開始時 `sessionModels = []` で旧モデル残留を防ぐ。

### 13.2 rename save 中の session 切り替え

`useSessionRename.saveRename()` 内で `const capturedId = input.session()?.id` → await 後に `if (input.session()?.id !== capturedId) return;` で stale の `onRenameSuccess` 発火を防ぐ。

### 13.3 setSession と $derived の整合

`reconstruction.setSession(updated)` で `session` を更新すると hook 内 6 つの `$derived` が自動再計算。
getter ベースの参照なので追加の wiring 不要。

### 13.4 renameInputEl の focus タイミング

`$effect(() => { ... })` + `prevIsRenaming` で立ち上がりエッジ (false→true) のみ focus (§5.2)。重複 focus / rebound 防止。
`setTimeout(..., 0)` (現行 L272) は排除。

### 13.5 snippet prop の型

`referenceAudio?: Snippet` が型エラーになる場合は `Snippet<[]>` に変更。`npm run check` で確認。

### 13.6 TanStack Query 非使用の維持

今回の抽出でも導入しない。useSessionReconstruction は raw fetch + `$state` のみ。挙動保持を優先。

### 13.7 smoke seed 依存 (Codex Med-3 解決済)

- id sort で deterministic 選定 + env override
- rename 復元は test 内 `try/finally` で確実化、`afterAll` は fallback

### 13.8 getLocale() 非 reactive

現状 `loadSession` 内で `getLocale()` を一度だけ呼ぶ (language 切替で re-load しない)。
挙動保持のため hook 抽出後も同じ。将来 reactive 化したい場合は `input.locale: () => string` を追加する拡張箇所として plan に明記。

### 13.9 Test 6/7 の assert 方法 (v1 High-2 / v2 High-2 解決済)

URL assert は成立しない (`handleRerunFromDetail` 実装上) + mode 遷移 UI 単独では fork/edit 差分検証不能 → **mode 遷移 UI anchor + API route mock (POST /batch vs PUT /rerun) で判定**。stub response で実 job 作成回避。anchor locator は `getByRole('heading', { name: /Reference Sounds/i })` で plan 確定。

### 13.10 i18n キー (E2E セレクタ用)

| i18n key | 英語テキスト | 備考 |
|---|---|---|
| `m.search_back_to_sessions()` | `"Back to Sessions"` | **text locator** (aria-label なし) |
| `m.search_rename_session()` | `"Rename"` (推定) | aria-label or button label |
| `m.search_session_name()` | `"Session Name"` (推定) | |
| `m.search_rename_save()` | `"Save"` | |
| `m.search_rename_cancel()` | `"Cancel"` | |
| `m.search_export_csv()` | `"Export CSV"` | |
| `m.search_fork_session()` | `"Fork as New Session"` (推定) | |
| `m.search_edit_rerun()` | `"Edit & Re-search"` (推定) | |
| hardcoded | `"Close dialog"` (CreateModelFromSessionDialog.svelte L168) | |

Step 0 実装時に `messages/en.json` で実キーと text を確認。

## 14. Codex review v2 ポイント (再レビュー用)

v1 → v2 で以下を修正済。再 review では残存リスクの確認:

1. **§4.2**: `isStale` helper 化 + 全 await 後適用は十分か
2. **§6.1**: SessionActionPanel の Props 個別化で hook 内部実装が漏れていないか
3. **§3**: 型契約 `() => T` 方式で Svelte 5 runes の reactivity が正しく保たれるか (関数呼出は `$derived` を trigger するか)
4. **§8.2**: deterministic seed + try/finally 復元で rename テストの flaky がゼロ化できるか
5. **§8.3**: Test 6/7 の mode 遷移 UI assert の具体的 locator 候補を plan で決めるか、SSA 判断に委ねるか
6. **§5.2**: `prevIsRenaming` で rising edge のみ focus する実装が、focus lost → 再 focus を blocker しないか (ユーザーが他 input に tab した後 rename 編集継続するケース — 現状は blur しない限り再 focus 不要)

## 15. 完了定義

### Gate 1: 静的検証
- `npm run check` pass

### Gate 2: 自動テスト
- `npx playwright test tests/e2e/search-session-detail.spec.ts` → 9/9 pass

### Gate 3: ブラウザ検証 (Step 3 完了後にメインセッションで実施)
- `/en/projects/{TEST_PROJECT_ID}/search?session={testSessionId}` を開く
- ヘッダカード + species 一覧 + アクションボタン確認
- Rename → Save → 名前更新確認
- Console error 0 件

### Gate 4: 完了報告テンプレート
```
## 完了報告
- 変更ファイル: [リスト]
- Gate 1 (静的検証): ✅/❌
- Gate 2 (自動テスト): ✅/❌ [9/9 pass]
- Gate 3 (ブラウザ検証): ✅/❌ [URL + スナップショット要約]
- Gate 4 (コンソールエラー): ✅ 0件 / ❌
```
