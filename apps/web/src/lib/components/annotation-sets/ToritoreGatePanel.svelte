<script lang="ts">
  /**
   * ToritoreGatePanel — participation gate shown in place of the annotation
   * editor when the current user is NOT eligible for an annotation set.
   *
   * Internal research-preview feature (`preview/toritore-integration`).
   *
   * Flow:
   *   1. The parent has already fetched eligibility and only mounts this panel
   *      when `eligible === false`. It passes the `required` threshold and the
   *      caller's `my_latest_total_score` (nullable = never submitted).
   *   2. The user uploads their exported ToriTore JSON file. We `JSON.parse`
   *      it client-side (parse errors surface inline), POST the raw object,
   *      then ask the parent to re-fetch eligibility via `onUploaded`.
   *   3. If still ineligible after upload, we show the score-vs-requirement
   *      shortfall message; the parent keeps the editor locked.
   *
   * Visual style follows the existing annotation-set cards (surface-card +
   * border-card) and the inline alert convention (danger / amber tokens).
   */
  import { createMutation } from '@tanstack/svelte-query';
  import * as m from '$lib/paraglide/messages';
  import { uploadToritoreResults } from '$lib/api/me-toritore';

  interface Props {
    /** Required latest-test total score (the set's `min_total_score`). */
    required: number | null;
    /** Caller's latest total score, or `null` if never submitted. */
    myLatestTotalScore: number | null;
    /**
     * Called after a successful upload. The parent re-fetches eligibility and,
     * if now eligible, swaps this panel for the editor. Returning a promise
     * lets us keep the button busy until the re-check settles.
     */
    onUploaded: () => void | Promise<void>;
  }

  let { required, myLatestTotalScore, onUploaded }: Props = $props();

  /** Format a 0–1 score to a fixed 3 decimals (null → em dash). */
  function formatScore(value: number | null): string {
    return value == null ? '—' : value.toFixed(3);
  }

  // ============================================================
  // Upload
  // ============================================================

  let selectedFile = $state<File | null>(null);
  let parseError = $state<string | null>(null);
  let fileInputEl = $state<HTMLInputElement | null>(null);

  function onFileChange(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    selectedFile = input.files?.[0] ?? null;
    parseError = null;
  }

  const uploadMutation = createMutation({
    mutationFn: async (file: File): Promise<void> => {
      const text = await file.text();
      let parsed: unknown;
      try {
        parsed = JSON.parse(text);
      } catch {
        // Surface as an inline parse error rather than a mutation error so the
        // message is specific ("not valid JSON") instead of generic.
        throw new ParseError(m.toritore_gate_upload_parse_error());
      }
      await uploadToritoreResults(parsed);
    },
    onSuccess: async () => {
      parseError = null;
      // Re-evaluate eligibility upstream; the parent unlocks if now eligible.
      await onUploaded();
    },
    onError: (err: Error) => {
      if (err instanceof ParseError) {
        parseError = err.message;
      }
    },
  });

  /** Distinguish client-side JSON parse failures from network/server errors. */
  class ParseError extends Error {}

  function submitUpload() {
    parseError = null;
    if (!selectedFile) {
      parseError = m.toritore_gate_upload_no_file();
      return;
    }
    $uploadMutation.mutate(selectedFile);
  }

  // Non-parse upload errors (network / server) surface via the mutation error.
  const serverError = $derived.by(() => {
    const err = $uploadMutation.error;
    if (!err || err instanceof ParseError) return null;
    return err.message || m.toritore_gate_upload_error();
  });
</script>

<section
  class="rounded-xl border border-card bg-surface-card p-6 shadow-sm"
  aria-labelledby="toritore-gate-heading"
>
  <h2
    id="toritore-gate-heading"
    class="text-lg font-semibold text-stone-900 dark:text-stone-100"
  >
    {m.toritore_gate_heading()}
  </h2>
  <p class="mt-2 text-sm text-stone-600 dark:text-stone-400">
    {m.toritore_gate_explanation({ required: formatScore(required) })}
  </p>

  <!-- Current status -->
  <div
    class="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm dark:border-amber-900/40 dark:bg-amber-900/20"
  >
    {#if myLatestTotalScore == null}
      <p class="text-amber-800 dark:text-amber-300">
        {m.toritore_gate_status_not_submitted()}
      </p>
    {:else}
      <p class="text-amber-800 dark:text-amber-300">
        {m.toritore_gate_status_latest_score({
          value: formatScore(myLatestTotalScore),
        })}
      </p>
      <p class="mt-1 text-amber-700 dark:text-amber-400">
        {m.toritore_gate_status_insufficient({
          current: formatScore(myLatestTotalScore),
          required: formatScore(required),
        })}
      </p>
    {/if}
  </div>

  <!-- Upload -->
  <div class="mt-5">
    <label
      for="toritore-file"
      class="block text-sm font-medium text-stone-700 dark:text-stone-300"
    >
      {m.toritore_gate_upload_label()}
    </label>
    <p class="mt-1 text-xs text-stone-400">{m.toritore_gate_upload_hint()}</p>

    <div class="mt-3 flex flex-wrap items-center gap-3">
      <input
        bind:this={fileInputEl}
        id="toritore-file"
        type="file"
        accept="application/json,.json"
        class="block w-full max-w-sm text-sm text-stone-600 file:mr-3 file:rounded-lg file:border-0 file:bg-primary-100 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-primary-800 hover:file:bg-primary-200 dark:text-stone-300 dark:file:bg-primary-900/30 dark:file:text-primary-300"
        onchange={onFileChange}
        disabled={$uploadMutation.isPending}
      />
      <button
        type="button"
        class="rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700 disabled:opacity-50 dark:bg-primary-500 dark:hover:bg-primary-400"
        onclick={submitUpload}
        disabled={$uploadMutation.isPending || !selectedFile}
      >
        {$uploadMutation.isPending
          ? m.toritore_gate_upload_submitting()
          : m.toritore_gate_upload_submit()}
      </button>
    </div>

    {#if parseError}
      <div
        class="mt-3 rounded-lg border border-danger/30 bg-danger-light p-3 text-sm text-danger"
        role="alert"
      >
        {parseError}
      </div>
    {/if}

    {#if serverError}
      <div
        class="mt-3 rounded-lg border border-danger/30 bg-danger-light p-3 text-sm text-danger"
        role="alert"
      >
        {serverError}
      </div>
    {/if}
  </div>
</section>
