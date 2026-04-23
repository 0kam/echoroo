/**
 * Type contracts for the SearchSessionDetail split (P2-B refactor).
 *
 * Declares the API surface for both hooks up-front so follow-up steps do
 * not need to re-touch this file:
 *   - Step 1: `useSessionReconstruction` implements {@link SessionReconstructionHookApi}
 *   - Step 2: `useSessionRename` implements {@link SessionRenameHookApi}
 *
 * Conventions (mirrors `apps/web/src/lib/components/annotation-sets/types.ts`):
 *   - Every reactive input is a getter (`() => T`) so Svelte 5 runes can
 *     observe value changes across the hook's lifetime.
 *   - `$state`-backed fields are exposed as bare readonly props — the hook
 *     returns them via getters (`get x() { return x; }`) so Svelte's proxy
 *     keeps reactivity intact. Returning the raw `$state` value would
 *     snapshot it and break updates at the call site.
 *   - `$derived`-style values are exposed as function getters `() => T` so
 *     existing call sites (e.g. `statusLabel()`) keep working unchanged.
 *   - Every hook exposes a `dispose()` method that the parent calls from
 *     `onDestroy` to short-circuit pending async continuations.
 */

import type { SearchSession, TargetSpecies } from '$lib/types/search';
import type { CustomModelListItem } from '$lib/types/custom-model';

// --- useSessionReconstruction -------------------------------------------

/**
 * Reactive inputs for the session reconstruction hook. Each field is a
 * getter so the hook observes parent-side changes (e.g. sessionId updates
 * when the user navigates between sessions without unmounting).
 */
export interface SessionReconstructionInput {
  /** Current project UUID. */
  projectId: () => string;
  /** Current search session UUID. */
  sessionId: () => string;
}

/**
 * Imperative API returned by {@link useSessionReconstruction}.
 *
 * State-shape contract:
 *   - `session`, `isLoading`, `loadError`, `reconstructedSpecies`,
 *     `sessionModels`, `datasetName` are `$state`-backed readonly fields.
 *     The hook returns them via getters so Svelte 5 rune reactivity is
 *     preserved at the call site (returning a raw `$state` value would
 *     snapshot it).
 *   - The six derived values (`statusLabel`, `statusColor`,
 *     `statusDotColor`, `sessionName`, `formattedDate`, `searchDuration`)
 *     are function getters `() => T`. The consumer invokes them
 *     (e.g. `reconstruction.statusLabel()`), matching the pre-refactor
 *     call sites in `SearchSessionDetail.svelte`.
 */
export interface SessionReconstructionHookApi {
  readonly session: SearchSession | null;
  readonly isLoading: boolean;
  readonly loadError: string | null;
  readonly reconstructedSpecies: TargetSpecies[];
  readonly sessionModels: CustomModelListItem[];
  readonly datasetName: string | null;
  statusLabel: () => string;
  statusColor: () => string;
  statusDotColor: () => string;
  sessionName: () => string;
  formattedDate: () => string;
  searchDuration: () => number;
  /** Update the owned session (used by the rename hook after a successful PATCH). */
  setSession(s: SearchSession): void;
  /**
   * Short-circuit pending async continuations (sets a `disposed` flag).
   * Must be called from the parent's `onDestroy`.
   */
  dispose(): void;
}

// --- useSessionRename ---------------------------------------------------

/**
 * Reactive inputs for the rename hook (Step 2). Declared now so the
 * Step 1 `types.ts` file does not need to be touched in the follow-up PR.
 */
export interface SessionRenameInput {
  /** Current session (null while loading). */
  session: () => SearchSession | null;
  /** Current project UUID. */
  projectId: () => string;
  /** Current display name used to seed the rename input on open. */
  getDisplayName: () => string;
  /** Callback fired after a successful PATCH; parent should `setSession(updated)`. */
  onRenameSuccess: (updated: SearchSession) => void;
}

/**
 * Imperative API returned by {@link useSessionRename}. DOM-agnostic —
 * `renameInputEl` focus management lives in the panel component using a
 * `$state`-backed ref + rising-edge `$effect`.
 */
export interface SessionRenameHookApi {
  readonly isRenaming: boolean;
  readonly renameValue: string;
  readonly isSavingRename: boolean;
  readonly renameError: string | null;
  /** `oninput` handler replacement (bind:value is not usable across hook boundary). */
  setRenameValue(v: string): void;
  startRename(): void;
  cancelRename(): void;
  saveRename(): Promise<void>;
  handleRenameKeydown(e: KeyboardEvent): void;
  /** Detach listeners / short-circuit callbacks. */
  dispose(): void;
}
