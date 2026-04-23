/**
 * useSessionRename — Svelte 5 runes hook that owns the inline rename flow
 * for a single search session.
 *
 * Extracted from SearchSessionDetail.svelte as Step 2 of the P2-B split
 * (see plan.md §5). The hook:
 *   - Tracks the inline rename UI state (`isRenaming`, `renameValue`,
 *     `isSavingRename`, `renameError`).
 *   - Exposes `startRename` / `cancelRename` / `saveRename` plus a
 *     `handleRenameKeydown` handler (Enter saves, Escape cancels).
 *   - Provides `setRenameValue` so the consumer can drive the input via
 *     `oninput` — Svelte `bind:value` is not usable across the hook
 *     boundary because the hook does not own the DOM node.
 *   - Calls `updateSearchSession(projectId, id, trimmedName)` and hands the
 *     resulting session back via `onRenameSuccess` so the parent (or the
 *     reconstruction hook) can update its own state.
 *
 * Lifetime + safety:
 *   - `disposed` short-circuits async continuations so late `updateSearchSession`
 *     resolutions never mutate `$state` after unmount.
 *   - A `capturedSessionId` snapshot taken before the `await` ensures the
 *     `onRenameSuccess` callback never fires when the user has navigated
 *     to a different session mid-flight. The `isSavingRename` flag is
 *     still reset in `finally` regardless (see plan.md §5.1 / §13.2).
 *   - The hook invokes `onDestroy(dispose)` itself as defence-in-depth; the
 *     parent is still expected to call `dispose()` explicitly.
 *
 * Explicitly NOT handled here:
 *   - DOM focus management (`renameInputEl.focus()`) — the parent (Step 3
 *     will move this into SessionActionPanel) owns the DOM ref and uses a
 *     rising-edge `$effect` on `isRenaming` to focus the input after
 *     Svelte commits the DOM update (plan.md §5.2).
 */

import { onDestroy } from 'svelte';
import * as m from '$lib/paraglide/messages';
import { updateSearchSession } from '$lib/api/search';
import type {
  SessionRenameHookApi,
  SessionRenameInput,
} from './types';

export function useSessionRename(
  input: SessionRenameInput,
): SessionRenameHookApi {
  // --- Core state (exposed via getters below) ---------------------------
  let isRenaming = $state(false);
  let renameValue = $state('');
  let isSavingRename = $state(false);
  let renameError = $state<string | null>(null);

  // Set true by `dispose()`. Async continuations bail out when disposed so
  // unmount cannot race into a `$state` write on closed-over bindings.
  let disposed = false;

  function setRenameValue(v: string): void {
    renameValue = v;
  }

  function startRename(): void {
    if (disposed) return;
    renameValue = input.getDisplayName();
    renameError = null;
    isRenaming = true;
  }

  function cancelRename(): void {
    if (disposed) return;
    isRenaming = false;
    renameError = null;
  }

  /**
   * Persist the current `renameValue` via PATCH. Guarded by:
   *   - null session check (parent hasn't finished loading)
   *   - empty-after-trim check (don't save blank names)
   *   - `disposed` check after the await (unmount)
   *   - `capturedSessionId` mismatch after the await (parent navigated to
   *     a different session mid-flight) — only `onRenameSuccess` is
   *     skipped in this case; `isSavingRename` is always reset in finally.
   */
  async function saveRename(): Promise<void> {
    if (disposed) return;
    const current = input.session();
    if (!current || !renameValue.trim()) return;

    const capturedSessionId = current.id;

    isSavingRename = true;
    renameError = null;
    try {
      const updated = await updateSearchSession(
        input.projectId(),
        current.id,
        renameValue.trim(),
      );
      if (disposed) return;

      // If the parent swapped sessions while the PATCH was in flight,
      // don't push the stale `updated` into the new session's state.
      const stillCurrent = input.session()?.id === capturedSessionId;
      if (stillCurrent) {
        input.onRenameSuccess(updated);
        isRenaming = false;
      }
    } catch (e) {
      if (disposed) return;
      const stillCurrent = input.session()?.id === capturedSessionId;
      if (stillCurrent) {
        renameError = e instanceof Error ? e.message : m.search_error_search_failed();
      }
    } finally {
      // Always reset the saving flag — even if stale — so the UI does not
      // stay in a spinner state after a late resolution.
      if (!disposed) {
        isSavingRename = false;
      }
    }
  }

  function handleRenameKeydown(e: KeyboardEvent): void {
    if (e.key === 'Enter') {
      e.preventDefault();
      void saveRename();
    } else if (e.key === 'Escape') {
      cancelRename();
    }
  }

  function dispose(): void {
    if (disposed) return;
    disposed = true;
  }

  // Defence-in-depth: if the hook is invoked from a component context we
  // also react to onDestroy. The parent is still expected to call
  // `dispose()` explicitly from its own `onDestroy`.
  onDestroy(dispose);

  return {
    get isRenaming() {
      return isRenaming;
    },
    get renameValue() {
      return renameValue;
    },
    get isSavingRename() {
      return isSavingRename;
    },
    get renameError() {
      return renameError;
    },
    setRenameValue,
    startRename,
    cancelRename,
    saveRename,
    handleRenameKeydown,
    dispose,
  };
}
