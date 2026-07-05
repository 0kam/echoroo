/**
 * useSessionReconstruction — Svelte 5 runes hook that owns the fetch +
 * reconstruction state for a single search session.
 *
 * Extracted from SearchSessionDetail.svelte as Step 1 of the P2-B split
 * (see plan.md §4). The hook:
 *   - Fetches the session via `getSearchSession`, resolves dataset name
 *     via dynamic import of `fetchDataset`, and reconstructs TargetSpecies
 *     from `species_config` + `reference_audio_keys`.
 *   - Fetches linked custom models via `fetchCustomModels`.
 *   - Re-runs both fetches via a single `$effect` keyed on `projectId` /
 *     `sessionId` so navigation between sessions (without unmounting)
 *     refreshes the view.
 *   - Guards every `await` continuation with `isStale(capturedPid, capturedSid)`
 *     so a rapid session change never lets the prior fetch overwrite the
 *     new session's state (plan §4.2 / Codex v1 High-1 + v2 Med-1/Med-2).
 *   - Exposes six derived values as function getters (`statusLabel()`,
 *     etc.) so existing call sites in SearchSessionDetail.svelte and
 *     future SessionActionPanel.svelte keep working unchanged.
 *
 * Lifetime:
 *   - `disposed` short-circuits async continuations on unmount.
 *   - The hook invokes `onDestroy(dispose)` itself as defence-in-depth; the
 *     parent is still expected to call `dispose()` explicitly.
 *
 * Explicitly NOT handled here:
 *   - Rename state — lives in `useSessionRename.svelte.ts` (Step 2).
 *   - Train dialog state / export state / fork/edit handlers — remain in
 *     the parent (Step 3 scope).
 */

import { onDestroy } from 'svelte';
import * as m from '$lib/paraglide/messages';
import { getLocale } from '$lib/paraglide/runtime';
import { getSearchSession, getAuthenticatedReferenceAudioUrl } from '$lib/api/search';
import { fetchCustomModels } from '$lib/api/custom-models';
import { generateId } from '$lib/utils/id';
import {
  getSearchSessionStatusLabel,
  getSearchSessionStatusTextClass,
  getSearchSessionStatusDetailDotClass,
} from '$lib/utils/statusFormatters';
import { formatSpeciesName } from '$lib/utils/speciesFormatters';
import type {
  SearchSession,
  TargetSpecies,
  SoundSource,
} from '$lib/types/search';
import type { CustomModelListItem } from '$lib/types/custom-model';
import type {
  SessionReconstructionHookApi,
  SessionReconstructionInput,
} from './types';

export function useSessionReconstruction(
  input: SessionReconstructionInput,
): SessionReconstructionHookApi {
  // --- Core state (exposed via getters below) ---------------------------
  let session = $state<SearchSession | null>(null);
  let isLoading = $state(true);
  let loadError = $state<string | null>(null);
  let reconstructedSpecies = $state<TargetSpecies[]>([]);
  let sessionModels = $state<CustomModelListItem[]>([]);
  let datasetName = $state<string | null>(null);

  // Internal models-loading flags — not exposed on the API surface because
  // the pre-refactor component kept them private (underscore-prefixed). If
  // a caller needs them later, add them to SessionReconstructionHookApi.
  let _isLoadingModels = $state(false);
  let _modelsLoadError = $state<string | null>(null);

  // Set true by `dispose()`. `isStale()` treats a disposed hook as stale so
  // late async continuations can never write back into the closed-over
  // `$state` bindings after unmount.
  let disposed = false;

  /**
   * Returns true when the captured project/session pair no longer matches
   * the current input (or the hook has been disposed). Called after every
   * `await` and inside `finally` blocks — see plan.md §4.2.
   */
  function isStale(capturedPid: string, capturedSid: string): boolean {
    if (disposed) return true;
    return input.projectId() !== capturedPid || input.sessionId() !== capturedSid;
  }

  /**
   * Fetch a session + reconstruct its reference audio TargetSpecies.
   * Every `await` continuation re-checks `isStale` so a navigation to a
   * different session mid-fetch never corrupts the newer state.
   */
  async function loadSession(pid: string, sid: string): Promise<void> {
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

      // Resolve dataset name from parameters.dataset_id (best-effort).
      if (data.parameters?.dataset_id) {
        try {
          const { fetchDataset } = await import('$lib/api/datasets');
          if (isStale(capturedPid, capturedSid)) return;
          const ds = await fetchDataset(pid, data.parameters.dataset_id);
          if (isStale(capturedPid, capturedSid)) return;
          datasetName = ds.name ?? null;
        } catch {
          if (isStale(capturedPid, capturedSid)) return;
          // Non-critical — skip dataset name display.
        }
      }

      // Reconstruct reference audio sources from persisted session data.
      if (data.species_config) {
        const loaded: TargetSpecies[] = [];

        for (const spConfig of data.species_config) {
          const speciesSources = (spConfig.sources ?? []).reduce<SoundSource[]>(
            (acc, srcConfig) => {
              const src = srcConfig as Record<string, unknown>;
              const s3Key = src['s3_key'] as string | undefined;
              const sourceUrl = src['source_url'] as string | undefined;
              const xcId = src['xc_id'] as string | undefined;

              if (s3Key && data.reference_audio_keys) {
                // S3-persisted source (uploaded files). ``streamUrl`` is
                // resolved in a second async pass below because the BFF
                // reference-audio stream is now authenticated with a scoped
                // media token (see getAuthenticatedReferenceAudioUrl).
                const keyIndex = data.reference_audio_keys.indexOf(s3Key);
                if (keyIndex >= 0) {
                  const fileKey = src['file_key'] as string | undefined;
                  acc.push({
                    id: generateId(),
                    origin: 's3' as const,
                    label: fileKey ?? `Source ${keyIndex + 1}`,
                    sourceIndex: keyIndex,
                    start_time: src['start_time'] as number | undefined,
                    end_time: src['end_time'] as number | undefined,
                  });
                }
              } else if (sourceUrl || xcId) {
                // URL-based source (Xeno-Canto). Extract XC ID from URL if
                // not explicitly provided so the label stays stable.
                let resolvedXcId = xcId as string | undefined;
                if (!resolvedXcId && sourceUrl) {
                  const xcMatch = sourceUrl.match(/xeno-canto\.org\/(\d+)/);
                  if (xcMatch) resolvedXcId = xcMatch[1];
                }
                acc.push({
                  id: generateId(),
                  origin: 'url' as const,
                  label: resolvedXcId ? `XC${resolvedXcId}` : (sourceUrl ?? 'URL source'),
                  source_url: sourceUrl,
                  xc_id: resolvedXcId,
                  // Xeno-canto attribution metadata (CC compliance). Persisted
                  // sessions created before W5-1 lack these fields; they stay
                  // undefined and the caption renders nothing (conditional).
                  recordist: src['recordist'] as string | undefined,
                  license: src['license'] as string | undefined,
                  start_time: src['start_time'] as number | undefined,
                  end_time: src['end_time'] as number | undefined,
                });
              }
              return acc;
            },
            [],
          );

          // Include species even if no sources could be reconstructed.
          loaded.push({
            id: generateId(),
            tag_id: spConfig.tag_id,
            scientific_name: spConfig.scientific_name,
            common_name: spConfig.common_name ?? undefined,
            sources: speciesSources,
          });
        }

        // Second pass: resolve authenticated stream URLs for every S3-backed
        // source. Each URL carries a short-lived scoped media token; the token
        // endpoint is hit once per DISTINCT source index (sources sharing an
        // index share one request). URLs are minted here for the session's
        // lifetime — like the recording playback/spectrogram flows, an expired
        // token means the next media fetch 401s and the user reloads.
        const s3Sources = loaded.flatMap((sp) =>
          sp.sources.filter((s) => s.origin === 's3' && s.sourceIndex !== undefined),
        );
        const urlByIndex = new Map<number, Promise<string | undefined>>();
        for (const s of s3Sources) {
          const idx = s.sourceIndex as number;
          if (!urlByIndex.has(idx)) {
            urlByIndex.set(
              idx,
              getAuthenticatedReferenceAudioUrl(pid, sid, idx).catch((e: unknown) => {
                // Non-critical — leave streamUrl unset; SourceCard degrades.
                console.warn(`reference-audio URL resolution failed (source ${idx})`, e);
                return undefined;
              }),
            );
          }
        }
        await Promise.all(
          s3Sources.map(async (s) => {
            s.streamUrl = await urlByIndex.get(s.sourceIndex as number);
          }),
        );
        if (isStale(capturedPid, capturedSid)) return;

        reconstructedSpecies = loaded;
      }
    } catch (e) {
      if (isStale(capturedPid, capturedSid)) return;
      loadError = e instanceof Error ? e.message : m.search_error_search_failed();
    } finally {
      if (!isStale(capturedPid, capturedSid)) {
        isLoading = false;
      }
    }
  }

  /**
   * Fetch linked custom models for the session. Kept separate from
   * `loadSession` (same as pre-refactor) so slow model fetches don't block
   * the main detail render.
   */
  async function loadSessionModels(pid: string, sid: string): Promise<void> {
    const capturedPid = pid;
    const capturedSid = sid;

    _isLoadingModels = true;
    _modelsLoadError = null;
    // Clear prior models eagerly so a navigation to a session with zero
    // linked models does not briefly show the previous session's list
    // (plan.md §4.2 Codex v2 Med-2).
    sessionModels = [];

    try {
      const res = await fetchCustomModels(pid, { search_session_id: sid });
      if (isStale(capturedPid, capturedSid)) return;
      sessionModels = res.models;
    } catch (e) {
      if (isStale(capturedPid, capturedSid)) return;
      _modelsLoadError = e instanceof Error ? e.message : 'Failed to load models';
    } finally {
      if (!isStale(capturedPid, capturedSid)) {
        _isLoadingModels = false;
      }
    }
  }

  // Single $effect that re-runs on projectId / sessionId change. Matches
  // the pre-refactor behaviour at SearchSessionDetail.svelte L202–205.
  $effect(() => {
    const pid = input.projectId();
    const sid = input.sessionId();
    loadSession(pid, sid);
    loadSessionModels(pid, sid);
  });

  // --- Derived values (function getters, see types.ts) ------------------
  //
  // Each derived is stored as a zero-arg `$derived(...)` function so that
  // the consumer-facing getter `() => T` can invoke it and trigger Svelte
  // dependency tracking on every call.  Matches the pre-refactor call
  // sites which already wrote `statusLabel()` etc.
  const statusLabelD = $derived(() => {
    if (!session) return '';
    return getSearchSessionStatusLabel(session.status, {
      completed: m.search_session_status_completed,
      running: m.search_session_status_running,
      failed: m.search_session_status_failed,
      pending: m.search_session_status_pending,
    });
  });

  const statusColorD = $derived(() => {
    if (!session) return 'text-stone-500';
    return getSearchSessionStatusTextClass(session.status);
  });

  const statusDotColorD = $derived(() => {
    if (!session) return 'bg-stone-400';
    return getSearchSessionStatusDetailDotClass(session.status);
  });

  const sessionNameD = $derived(() => {
    if (!session) return '';
    if (session.name) return session.name;
    if (session.species_config && session.species_config.length > 0) {
      return session.species_config
        .map((sp) => formatSpeciesName(sp.common_name, sp.scientific_name))
        .join(', ');
    }
    return m.search_session_detail();
  });

  const formattedDateD = $derived(() => {
    if (!session) return '';
    const dateStr = session.completed_at ?? session.started_at ?? session.created_at;
    try {
      return new Date(dateStr).toLocaleString();
    } catch {
      return dateStr;
    }
  });

  const searchDurationD = $derived(() => {
    if (!session?.results) return 0;
    return session.results.search_duration_ms;
  });

  function setSession(s: SearchSession): void {
    session = s;
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
    get session() {
      return session;
    },
    get isLoading() {
      return isLoading;
    },
    get loadError() {
      return loadError;
    },
    get reconstructedSpecies() {
      return reconstructedSpecies;
    },
    get sessionModels() {
      return sessionModels;
    },
    get datasetName() {
      return datasetName;
    },
    statusLabel: () => statusLabelD(),
    statusColor: () => statusColorD(),
    statusDotColor: () => statusDotColorD(),
    sessionName: () => sessionNameD(),
    formattedDate: () => formattedDateD(),
    searchDuration: () => searchDurationD(),
    setSession,
    dispose,
  };
}
