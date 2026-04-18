<script lang="ts">
  /**
   * SpeciesPalette — interactive species picker.
   *
   * Shows the AnnotationSet palette as chips (top 9 get number shortcut
   * badges). Clicking a chip fires `onPick(speciesId)`; the editor decides
   * whether to apply it to the current draft or the selected annotation.
   *
   * A search input below allows growing the palette by adding new taxa.
   */
  import { onMount, onDestroy } from 'svelte';
  import * as m from '$lib/paraglide/messages';
  import { searchTaxa } from '$lib/api/taxa';
  import type { PaletteEntry } from '$lib/types/annotation-set';
  import type { TaxonSearchResult } from '$lib/types/taxon';

  interface Props {
    palette: PaletteEntry[];
    /** Highlight these species (e.g., species of selected annotation). */
    highlightedSpeciesId?: string | null;
    /** Disable interaction while a mutation is pending. */
    isBusy?: boolean;
    /** User clicked a palette chip. */
    onPick: (speciesId: string) => void;
    /** User wants to add a new species to the palette. */
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
  // Search
  // ============================================================

  let query = $state('');
  let results = $state<TaxonSearchResult[]>([]);
  let searching = $state(false);
  let showDropdown = $state(false);
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;

  function onInput() {
    if (debounceTimer) clearTimeout(debounceTimer);
    const q = query.trim();
    if (q.length < 2) {
      results = [];
      searching = false;
      showDropdown = false;
      return;
    }
    searching = true;
    showDropdown = true;
    debounceTimer = setTimeout(async () => {
      try {
        results = await searchTaxa(q, undefined, 10);
      } catch {
        results = [];
      } finally {
        searching = false;
      }
    }, 300);
  }

  function isInPalette(speciesId: string): boolean {
    return palette.some((p) => p.species_id === speciesId);
  }

  function handleAdd(speciesId: string) {
    onAddSpecies(speciesId);
    query = '';
    results = [];
    showDropdown = false;
  }

  function handleBlur() {
    // Close dropdown on blur (after a tick so onclick on results fires).
    setTimeout(() => {
      showDropdown = false;
    }, 150);
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
    if (debounceTimer) clearTimeout(debounceTimer);
  });

  // ============================================================
  // Presentation helpers
  // ============================================================

  function entryLabel(e: PaletteEntry): string {
    return e.common_name ? `${e.common_name} (${e.scientific_name})` : e.scientific_name;
  }

  function taxonLabel(t: TaxonSearchResult): string {
    return t.common_name ? `${t.common_name} (${t.scientific_name})` : t.scientific_name;
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

  <!-- Search box -->
  <div class="relative mt-3">
    <input
      type="search"
      class="w-full rounded-lg border border-stone-300 bg-white px-3 py-1.5 text-sm shadow-sm focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/20 dark:border-stone-600 dark:bg-stone-800 dark:text-stone-100"
      placeholder={m.annotation_editor_palette_search_placeholder()}
      bind:value={query}
      oninput={onInput}
      onfocus={() => {
        if (query.trim().length >= 2) showDropdown = true;
      }}
      onblur={handleBlur}
      aria-label={m.annotation_editor_palette_search_placeholder()}
    />
    {#if showDropdown && query.trim().length >= 2}
      <div
        class="absolute left-0 right-0 top-full z-20 mt-1 max-h-60 overflow-y-auto rounded-lg border border-stone-200 bg-white shadow-lg dark:border-stone-700 dark:bg-stone-800"
      >
        {#if searching}
          <div class="p-3 text-center text-xs text-stone-500">
            {m.annotation_editor_palette_searching()}
          </div>
        {:else if results.length === 0}
          <div class="p-3 text-center text-xs text-stone-400">
            {m.annotation_editor_palette_no_matches()}
          </div>
        {:else}
          <ul role="listbox" aria-label={m.annotation_editor_palette_add()}>
            {#each results as t (t.id)}
              {@const already = isInPalette(t.id)}
              <li>
                <button
                  type="button"
                  class="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50 dark:hover:bg-stone-700/40"
                  disabled={already || isBusy}
                  onclick={() => handleAdd(t.id)}
                >
                  <span class="min-w-0 truncate text-stone-900 dark:text-stone-100">
                    {taxonLabel(t)}
                  </span>
                  {#if already}
                    <span class="flex-shrink-0 text-xs text-primary-600 dark:text-primary-300">
                      ✓
                    </span>
                  {:else}
                    <span class="flex-shrink-0 text-xs text-stone-400">+</span>
                  {/if}
                </button>
              </li>
            {/each}
          </ul>
        {/if}
      </div>
    {/if}
  </div>
</div>
