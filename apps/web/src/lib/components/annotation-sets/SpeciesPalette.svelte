<script lang="ts">
  /**
   * SpeciesPalette — annotation-set palette chip container + species picker.
   *
   * Shows the AnnotationSet palette as chips (top 9 get number shortcut
   * badges). Clicking a chip fires `onPick(speciesId)`; the editor decides
   * whether to apply it to the current draft or the selected annotation.
   *
   * The "grow palette" search is delegated to {@link UnifiedSpeciesPicker}
   * (mode `palette-search`, GBIF ON). A GBIF pick is materialised into a local
   * taxon via `createTaxonFromGbif` before being added so the palette always
   * stores a real `taxon_id` (preview #2 fix).
   */
  import { onMount, onDestroy } from 'svelte';
  import * as m from '$lib/paraglide/messages';
  import { getLocale } from '$lib/paraglide/runtime';
  import { searchTaxa, createTaxonFromGbif } from '$lib/api/taxa';
  import { toasts } from '$lib/stores/toast';
  import type { PaletteEntry } from '$lib/types/annotation-set';
  import type { SpeciesPickerResult } from '$lib/types/species-picker';
  import { formatSpeciesName } from '$lib/utils/speciesFormatters';
  import UnifiedSpeciesPicker from '$lib/components/shared/UnifiedSpeciesPicker.svelte';
  import { norm } from '$lib/components/shared/unifiedSpeciesPicker';

  interface Props {
    palette: PaletteEntry[];
    /** Highlight these species (e.g., species of selected annotation). */
    highlightedSpeciesId?: string | null;
    /** Disable interaction while a mutation is pending. */
    isBusy?: boolean;
    /** User clicked a palette chip. */
    onPick: (speciesId: string) => void;
    /** User wants to add a new species (resolved taxon_id) to the palette. */
    onAddSpecies: (speciesId: string) => void;
  }

  let {
    palette,
    highlightedSpeciesId = null,
    isBusy = false,
    onPick,
    onAddSpecies,
  }: Props = $props();

  // ============================================================
  // Palette growth — resolve a unified pick to a taxon_id, then add
  // ============================================================

  // Authoritative grey-out: normalized scientific names already in the palette.
  const addedKeys = $derived(new Set(palette.map((e) => norm(e.scientific_name))));

  // Normalized scientific names with an in-flight resolve/add. Passed to the
  // picker so the row stays disabled until the async add settles, preventing a
  // double-POST before `addedKeys` (palette) catches up.
  let pendingKeys = $state(new Set<string>());

  /**
   * Handle a pick from the unified picker. The palette only stores real taxa,
   * so every non-taxon pick is resolved to a `taxon_id` before being added:
   *   - taxon pick → use its id directly
   *   - tag pick   → use the tag's taxon_id; fall back to a taxa search, then
   *     a GBIF materialise, for legacy tags that predate the taxon link
   *   - gbif pick  → get-or-create a local taxon via `createTaxonFromGbif`
   * (custom entry is disabled in palette-search, so it never reaches here.)
   */
  async function handlePalettePick(result: SpeciesPickerResult) {
    const key = norm(result.scientific_name);
    // Defense-in-depth: a row already in the palette or mid-add is a no-op (no
    // POST → no 409). The picker greys these out, but guard here regardless.
    if (addedKeys.has(key) || pendingKeys.has(key)) return;

    pendingKeys = new Set(pendingKeys).add(key);
    try {
      let taxonId: string | null = null;

      if (result.source === 'taxon' && result.taxon_id) {
        taxonId = result.taxon_id;
      } else if (result.source === 'tag') {
        if (result.taxon_id) {
          taxonId = result.taxon_id;
        } else {
          // Legacy tag with no taxon link: resolve by scientific name, then
          // materialise from GBIF so the pick never silently no-ops.
          const matches = await searchTaxa(result.scientific_name, getLocale(), 1);
          taxonId = matches[0]?.id ?? null;
          if (!taxonId) {
            const taxon = await createTaxonFromGbif(
              result.scientific_name,
              result.gbif_key,
              result.common_name,
              getLocale(),
              result.vernacular_names,
            );
            taxonId = taxon.id;
          }
        }
      } else if (result.source === 'gbif') {
        const taxon = await createTaxonFromGbif(
          result.scientific_name,
          result.gbif_key,
          result.common_name,
          getLocale(),
          result.vernacular_names,
        );
        taxonId = taxon.id;
      }

      if (taxonId) {
        onAddSpecies(taxonId);
      } else {
        toasts.error(m.annotation_sets_palette_add_error());
      }
    } catch (err) {
      // Surface resolution/materialisation failures to the user, matching the
      // [setId] page's handlePaletteAdd toast style.
      toasts.error(
        err instanceof Error ? err.message : m.annotation_sets_palette_add_error(),
      );
    } finally {
      const next = new Set(pendingKeys);
      next.delete(key);
      pendingKeys = next;
    }
  }

  // ============================================================
  // Number-key shortcuts (1-9)
  // ============================================================

  function handleKeyDown(e: KeyboardEvent) {
    const target = e.target as HTMLElement | null;
    if (target) {
      const tag = target.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || target.isContentEditable) return;
    }
    if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    const code = e.key;
    if (code >= '1' && code <= '9') {
      const idx = parseInt(code, 10) - 1;
      const entry = palette[idx];
      if (entry) {
        e.preventDefault();
        onPick(entry.species_id);
      }
    }
  }

  onMount(() => window.addEventListener('keydown', handleKeyDown));
  onDestroy(() => {
    window.removeEventListener('keydown', handleKeyDown);
  });

  // ============================================================
  // Presentation helpers
  // ============================================================

  function entryLabel(e: PaletteEntry): string {
    return formatSpeciesName(e.common_name, e.scientific_name);
  }

  /**
   * Deterministic color per species id. Uses category-independent hashing
   * so repeated invocations with the same id produce the same hue.
   */
  function colorForSpecies(id: string): string {
    let hash = 0;
    for (let i = 0; i < id.length; i++) {
      hash = (hash * 31 + id.charCodeAt(i)) | 0;
    }
    const hue = Math.abs(hash) % 360;
    return `hsl(${hue}, 65%, 45%)`;
  }
</script>

<div class="flex h-full flex-col">
  <div class="mb-2 flex items-baseline justify-between gap-2">
    <h3 class="text-sm font-semibold text-stone-900 dark:text-stone-100">
      {m.annotation_editor_palette_title()}
    </h3>
    <span class="text-xs text-stone-500">{palette.length}</span>
  </div>

  <p class="mb-3 text-xs text-stone-500">{m.annotation_editor_palette_click_hint()}</p>

  <!-- Palette chips -->
  <div class="flex flex-wrap gap-1.5">
    {#if palette.length === 0}
      <p class="text-xs text-stone-400">{m.annotation_editor_palette_empty()}</p>
    {/if}
    {#each palette as entry, idx (entry.species_id)}
      {@const color = colorForSpecies(entry.species_id)}
      {@const isHighlighted = entry.species_id === highlightedSpeciesId}
      <button
        type="button"
        class="group inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-all disabled:cursor-not-allowed disabled:opacity-50"
        class:ring-2={isHighlighted}
        style:border-color={color}
        style:color={color}
        style:background-color={isHighlighted ? `${color}22` : 'transparent'}
        style:--tw-ring-color={color}
        title={entryLabel(entry)}
        aria-label={entryLabel(entry)}
        disabled={isBusy}
        onclick={() => onPick(entry.species_id)}
      >
        {#if idx < 9}
          <kbd
            class="flex h-4 w-4 flex-shrink-0 items-center justify-center rounded bg-stone-100 font-mono text-[10px] text-stone-600 dark:bg-stone-800 dark:text-stone-400"
          >
            {idx + 1}
          </kbd>
        {/if}
        <span class="truncate">{entryLabel(entry)}</span>
      </button>
    {/each}
  </div>

  <!-- Search box (unified picker, GBIF ON) -->
  <div class="mt-3">
    <UnifiedSpeciesPicker
      mode="palette-search"
      showGBIF
      {addedKeys}
      {pendingKeys}
      onPick={handlePalettePick}
    />
  </div>
</div>
