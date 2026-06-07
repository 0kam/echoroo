<script lang="ts">
  /**
   * UnifiedSpeciesPicker — the single species picker used across the app.
   *
   * Transparently merges three sources behind one canonical result shape
   * ({@link SpeciesPickerResult}): project tags → local taxon database → live
   * GBIF backbone. It replaces the three previously-divergent pickers
   * (SpeciesSelector, TagSelector, and the inline palette searches).
   *
   * Modes:
   *   - `add-to-list`    : multi-add panel (reference sounds). Project + Taxon
   *     DB + GBIF + optional custom entry; stays open after a pick; greys out
   *     already-added tags.
   *   - `palette-search` : single-pick dropdown that grows an annotation-set
   *     palette. Taxon DB + GBIF (GBIF ON — this is the preview #2 fix).
   *   - `tag-select`     : chip selector over a project's available tags.
   *     Local filter + optional GBIF, with 1-9 digit shortcuts on the input.
   *
   * Style follows AnnotationEditor.svelte (Tailwind utility classes, Svelte 5
   * runes). All rendered names go through `formatSpeciesName` so every row is
   * consistent across locales.
   */
  import { onMount, onDestroy } from 'svelte';
  import * as m from '$lib/paraglide/messages';
  import { getLocale } from '$lib/paraglide/runtime';
  import { fetchTags } from '$lib/api/tags';
  import { searchGBIF, searchTaxa } from '$lib/api/taxa';
  import type { Tag } from '$lib/types/annotation';
  import type { GBIFSpeciesResult, TaxonSearchResult } from '$lib/types/taxon';
  import type {
    SpeciesPickerMode,
    SpeciesPickerResult,
  } from '$lib/types/species-picker';
  import { formatSpeciesName, displayCommonName } from '$lib/utils/speciesFormatters';
  import {
    dedupTaxa,
    dedupGbif,
    resultFromTag,
    resultFromTaxon,
    resultFromGbif,
    resultFromCustom,
    hasExactMatch,
    isAdded,
    resolveGbifCommonName,
  } from './unifiedSpeciesPicker';

  interface Props {
    /** Behavioural mode (see component doc). */
    mode: SpeciesPickerMode;
    /** Emitted for every pick with the canonical result shape. */
    onPick: (result: SpeciesPickerResult) => void;
    /** Required for `add-to-list` to fetch project tags. */
    projectId?: string;
    /** Tag IDs already added — greyed out in `add-to-list`. */
    addedTagIds?: Set<string>;
    /**
     * Normalized (trim + lowercase) scientific names already present.
     * Authoritative grey-out across all sources (tag/taxon/gbif): a row whose
     * scientific/canonical name is in this set is rendered greyed + disabled
     * and excluded from Enter/digit selection, so a re-pick is a no-op.
     */
    addedKeys?: Set<string>;
    /**
     * Normalized scientific names with an in-flight create/add (same
     * normalization as {@link addedKeys}). Rows in this set are rendered
     * disabled and excluded from selection so a slow async add can't be
     * double-submitted before `addedKeys` catches up. Clear on settle.
     */
    pendingKeys?: Set<string>;
    /** Local tag pool filtered in `tag-select`. */
    availableTags?: Tag[];
    /** Selected tag IDs shown as chips in `tag-select`. */
    selectedTagIds?: string[];
    /** Chip-removal callback for `tag-select`. */
    onTagRemove?: (tagId: string) => void;
    /** Close affordance (add-to-list panel). */
    onClose?: () => void;
    /** Whether to query the live GBIF backbone. */
    showGBIF?: boolean;
    /** Whether to offer a free-text custom entry (add-to-list only). */
    allowCustom?: boolean;
    /** Focus the input on mount. */
    autofocus?: boolean;
    /** Placeholder override for the search input. */
    placeholder?: string;
  }

  let {
    mode,
    onPick,
    projectId,
    addedTagIds = new Set<string>(),
    addedKeys = new Set<string>(),
    pendingKeys = new Set<string>(),
    availableTags = [],
    selectedTagIds = [],
    onTagRemove,
    onClose,
    showGBIF = false,
    allowCustom = false,
    autofocus = false,
    placeholder,
  }: Props = $props();

  // ============================================================
  // State
  // ============================================================

  let inputEl: HTMLInputElement | undefined = $state();
  let query = $state('');
  let tagResults = $state<Tag[]>([]);
  let taxonResults = $state<TaxonSearchResult[]>([]);
  let gbifResults = $state<GBIFSpeciesResult[]>([]);
  let isLoading = $state(false);
  let showDropdown = $state(false);
  let isComposing = $state(false);
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;
  let blurTimer: ReturnType<typeof setTimeout> | null = null;
  /** Monotonic id so out-of-order async responses can be discarded. */
  let searchSeq = 0;

  onMount(() => {
    if (autofocus) inputEl?.focus();
  });

  onDestroy(() => {
    if (debounceTimer) clearTimeout(debounceTimer);
    if (blurTimer) clearTimeout(blurTimer);
  });

  // ============================================================
  // Derived: tag-select local filtering + chips
  // ============================================================

  const selectedTags = $derived(
    availableTags.filter((t) => selectedTagIds.includes(t.id)),
  );

  /** Local (synchronous) filter of available tags for `tag-select`. */
  const filteredTags = $derived(
    mode === 'tag-select'
      ? availableTags.filter(
          (t) =>
            !selectedTagIds.includes(t.id) &&
            (query.trim() === '' ||
              t.name.toLowerCase().includes(query.trim().toLowerCase()) ||
              (t.scientific_name
                ? t.scientific_name.toLowerCase().includes(query.trim().toLowerCase())
                : false)),
        )
      : [],
  );

  // ============================================================
  // Derived: deduped async results (add-to-list / palette-search)
  // ============================================================

  const dedupedTaxa = $derived(dedupTaxa(taxonResults, tagResults));
  const dedupedGbif = $derived(dedupGbif(gbifResults, tagResults, taxonResults));

  const showCustomRow = $derived(
    allowCustom &&
      mode === 'add-to-list' &&
      query.trim().length >= 2 &&
      !hasExactMatch(query, tagResults, taxonResults, gbifResults, getLocale()),
  );

  const hasAnyResult = $derived(
    tagResults.length > 0 ||
      dedupedTaxa.length > 0 ||
      dedupedGbif.length > 0,
  );

  // ============================================================
  // Search
  // ============================================================

  function resetResults() {
    // Bump the sequence so any in-flight response (older seq) is discarded and
    // can't paint stale rows over the now-empty results.
    searchSeq++;
    tagResults = [];
    taxonResults = [];
    gbifResults = [];
    isLoading = false;
  }

  async function runSearch(value: string) {
    const trimmed = value.trim();
    if (trimmed.length < 1) {
      resetResults();
      showDropdown = false;
      return;
    }

    const seq = ++searchSeq;
    isLoading = true;
    showDropdown = true;

    // Locale is omitted from the tag/taxon name match so the search remains
    // locale-agnostic (a user on /en can still find Japanese names); the
    // backend still resolves each row's vernacular_name for display.
    const locale = getLocale();
    const wantGbif = showGBIF && trimmed.length >= 2;

    const tagsP: Promise<Tag[]> =
      mode === 'add-to-list' && projectId
        ? fetchTags(projectId, {
            search: trimmed,
            category: 'species',
            page_size: 20,
            locale,
          }).then((r) => r.items)
        : Promise.resolve([]);

    // `tag-select` filters its local tag pool synchronously; it never hits the
    // taxon DB. Other modes search live taxa.
    const taxaP: Promise<TaxonSearchResult[]> =
      mode === 'tag-select'
        ? Promise.resolve([])
        : searchTaxa(trimmed, locale, mode === 'add-to-list' ? 15 : 10);

    const gbifP: Promise<GBIFSpeciesResult[]> = wantGbif
      ? searchGBIF(trimmed, 10)
      : Promise.resolve([]);

    const [tagRes, taxonRes, gbifRes] = await Promise.allSettled([
      tagsP,
      taxaP,
      gbifP,
    ]);

    // Discard stale responses from a superseded query.
    if (seq !== searchSeq) return;

    tagResults = tagRes.status === 'fulfilled' ? tagRes.value : [];
    taxonResults = taxonRes.status === 'fulfilled' ? taxonRes.value : [];
    gbifResults = gbifRes.status === 'fulfilled' ? gbifRes.value : [];
    isLoading = false;
  }

  function handleInput() {
    // Invalidate any in-flight response immediately so a stale fetch (e.g. when
    // the user clears or shortens the query) can never overwrite fresh state.
    // `runSearch` bumps it again to claim the new request.
    searchSeq++;

    if (mode === 'tag-select') {
      // Local filter is reactive; only GBIF (if enabled) needs a fetch.
      showDropdown = true;
      if (debounceTimer) clearTimeout(debounceTimer);
      if (!showGBIF || query.trim().length < 2) {
        gbifResults = [];
        return;
      }
      debounceTimer = setTimeout(() => void runSearch(query), 300);
      return;
    }

    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => void runSearch(query), 300);
  }

  function clearQuery() {
    query = '';
    resetResults();
    showDropdown = false;
  }

  // ============================================================
  // Pick handlers (canonical result construction)
  // ============================================================

  function pickTag(tag: Tag) {
    // Silent no-op when already present (by id or scientific name).
    if (tagAdded(tag)) return;
    onPick(resultFromTag(tag));
    if (mode === 'add-to-list') {
      // Multi-add: keep the panel open and clear for the next pick.
      clearQuery();
    } else {
      clearQuery();
      if (mode === 'tag-select') inputEl?.focus();
    }
  }

  function pickTaxon(taxon: TaxonSearchResult) {
    if (taxonAdded(taxon)) return;
    onPick(resultFromTaxon(taxon, tagResults));
    clearQuery();
  }

  function pickGbif(gbif: GBIFSpeciesResult) {
    if (gbifAdded(gbif)) return;
    onPick(resultFromGbif(gbif, tagResults, getLocale()));
    clearQuery();
  }

  function pickCustom() {
    if (query.trim().length < 2) return;
    onPick(resultFromCustom(query));
    clearQuery();
  }

  /** Pick the first available, not-already-added result (legacy Enter). */
  function pickFirst() {
    if (mode === 'tag-select') {
      const first = filteredTags.find((t) => !tagAdded(t));
      if (first) pickTag(first);
      return;
    }
    const firstTag = tagResults.find((t) => !tagAdded(t));
    if (firstTag) {
      pickTag(firstTag);
      return;
    }
    const firstTaxon = dedupedTaxa.find((t) => !taxonAdded(t));
    if (firstTaxon) {
      pickTaxon(firstTaxon);
      return;
    }
    const firstGbif = dedupedGbif.find((g) => !gbifAdded(g));
    if (firstGbif) {
      pickGbif(firstGbif);
      return;
    }
    if (showCustomRow) pickCustom();
  }

  // ============================================================
  // Keyboard
  // ============================================================

  function handleKeydown(e: KeyboardEvent) {
    // IME guard: never act mid-composition.
    if (isComposing || e.isComposing) return;

    if (e.key === 'Enter') {
      e.preventDefault();
      pickFirst();
      return;
    }
    if (e.key === 'Escape') {
      e.preventDefault();
      if (query.trim().length > 0) {
        clearQuery();
      } else {
        onClose?.();
      }
      return;
    }

    // tag-select: 1-9 digit shortcuts bound to the INPUT element only, so they
    // never collide with the palette's window-level 1-9 listener.
    if (mode === 'tag-select' && e.key >= '1' && e.key <= '9') {
      if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
      const idx = parseInt(e.key, 10) - 1;
      const tag = filteredTags[idx];
      if (tag) {
        e.preventDefault();
        // Stop the event so it can't also reach SpeciesPalette's window-level
        // 1-9 listener (defense in depth; that handler already bails on INPUT).
        e.stopPropagation();
        pickTag(tag);
      }
    }
  }

  function handleBlur() {
    // Delay so click events on dropdown rows fire before it closes. Tracked so
    // it can be cleared on destroy (avoids a setState-after-unmount leak).
    if (blurTimer) clearTimeout(blurTimer);
    blurTimer = setTimeout(() => {
      showDropdown = false;
    }, 150);
  }

  // ============================================================
  // Display
  // ============================================================

  // ------------------------------------------------------------
  // Added-state (authoritative grey-out via scientific-name keys)
  // ------------------------------------------------------------

  /**
   * True when a scientific/canonical name is either already added OR has an
   * in-flight add (pendingKeys). Both render the row disabled and block a pick,
   * so a slow async create/add can't be double-submitted.
   */
  function nameBlocked(name: string): boolean {
    return isAdded(name, addedKeys) || isAdded(name, pendingKeys);
  }

  /** True when this tag row is already present (by tag id OR scientific name). */
  function tagAdded(tag: Tag): boolean {
    return addedTagIds.has(tag.id) || nameBlocked(tag.scientific_name ?? tag.name);
  }

  function taxonAdded(taxon: TaxonSearchResult): boolean {
    return nameBlocked(taxon.scientific_name);
  }

  function gbifAdded(gbif: GBIFSpeciesResult): boolean {
    return nameBlocked(gbif.canonical_name);
  }

  function tagLabel(tag: Tag): string {
    return formatSpeciesName(displayCommonName(tag), tag.scientific_name ?? tag.name);
  }

  function taxonLabel(taxon: TaxonSearchResult): string {
    return formatSpeciesName(taxon.common_name, taxon.scientific_name);
  }

  function gbifLabel(gbif: GBIFSpeciesResult): string {
    return formatSpeciesName(resolveGbifCommonName(gbif, getLocale()), gbif.canonical_name);
  }

  const resolvedPlaceholder = $derived(
    placeholder ??
      (mode === 'tag-select'
        ? m.annotation_tag_selector_search_placeholder()
        : mode === 'palette-search'
          ? m.annotation_editor_palette_search_placeholder()
          : m.search_species_selector_placeholder()),
  );
</script>

{#if mode === 'add-to-list'}
  <!-- ============================================================ -->
  <!-- add-to-list: full panel with section headers + custom entry  -->
  <!-- ============================================================ -->
  <div
    class="space-y-3 rounded-lg border border-stone-200 bg-stone-50 p-4 dark:border-stone-700 dark:bg-stone-800/50"
  >
    <p class="text-sm font-medium text-stone-900 dark:text-stone-100">
      {m.search_species_selector_title()}
    </p>

    <div class="relative">
      <svg
        class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-stone-400"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        aria-hidden="true"
      >
        <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
      </svg>
      <input
        bind:this={inputEl}
        bind:value={query}
        type="text"
        class="w-full rounded-md border border-stone-300 bg-surface-card py-1.5 pl-9 pr-3 text-sm text-stone-900 placeholder-stone-400 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-stone-600"
        placeholder={resolvedPlaceholder}
        oninput={handleInput}
        onkeydown={handleKeydown}
        oncompositionstart={() => (isComposing = true)}
        oncompositionend={() => (isComposing = false)}
        autocomplete="off"
      />
      {#if isLoading}
        <div class="absolute right-3 top-1/2 -translate-y-1/2">
          <div
            class="h-3.5 w-3.5 animate-spin rounded-full border-2 border-stone-300 border-t-primary-500"
          ></div>
        </div>
      {/if}
    </div>

    {#if hasAnyResult}
      <div
        class="max-h-64 divide-y divide-stone-200 overflow-y-auto rounded-lg border border-stone-200 dark:divide-stone-700 dark:border-stone-700"
      >
        {#if tagResults.length > 0}
          <div class="bg-stone-100 px-3 py-1.5 dark:bg-stone-700/30">
            <span class="text-xs font-medium uppercase tracking-wide text-stone-500">
              {m.search_species_section_project()}
            </span>
          </div>
          {#each tagResults as tag (tag.id)}
            {@const alreadyAdded = tagAdded(tag)}
            <div
              class="flex items-center justify-between px-3 py-2 {alreadyAdded
                ? 'opacity-50'
                : 'hover:bg-stone-100 dark:hover:bg-stone-700/50'}"
            >
              <span class="min-w-0 flex-1 truncate text-sm text-stone-900 dark:text-stone-100">
                {tagLabel(tag)}
              </span>
              {#if alreadyAdded}
                <svg
                  class="h-4 w-4 shrink-0 text-stone-400"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  aria-hidden="true"
                >
                  <path d="M20 6 9 17l-5-5" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
              {:else}
                <button
                  type="button"
                  class="ml-2 shrink-0 text-primary-600 transition-colors hover:text-primary-700 dark:text-primary-400"
                  onclick={() => pickTag(tag)}
                  aria-label="Add {tag.scientific_name ?? tag.name}"
                >
                  <svg
                    class="h-4 w-4"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                    aria-hidden="true"
                  >
                    <path d="M12 5v14M5 12h14" stroke-linecap="round" />
                  </svg>
                </button>
              {/if}
            </div>
          {/each}
        {/if}

        {#if dedupedTaxa.length > 0}
          <div class="bg-stone-100 px-3 py-1.5 dark:bg-stone-700/30">
            <span class="text-xs font-medium uppercase tracking-wide text-stone-500">
              {m.search_species_section_taxon_db()}
            </span>
          </div>
          {#each dedupedTaxa as taxon (taxon.id)}
            {@const alreadyAdded = taxonAdded(taxon)}
            <div
              class="flex items-center justify-between px-3 py-2 {alreadyAdded
                ? 'opacity-50'
                : 'hover:bg-stone-100 dark:hover:bg-stone-700/50'}"
            >
              <span class="min-w-0 flex-1 truncate text-sm text-stone-900 dark:text-stone-100">
                {taxonLabel(taxon)}
              </span>
              {#if alreadyAdded}
                <svg
                  class="h-4 w-4 shrink-0 text-stone-400"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  aria-hidden="true"
                >
                  <path d="M20 6 9 17l-5-5" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
              {:else}
                <button
                  type="button"
                  class="ml-2 shrink-0 text-primary-600 transition-colors hover:text-primary-700 dark:text-primary-400"
                  onclick={() => pickTaxon(taxon)}
                  aria-label="Add {taxon.scientific_name}"
                >
                  <svg
                    class="h-4 w-4"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                    aria-hidden="true"
                  >
                    <path d="M12 5v14M5 12h14" stroke-linecap="round" />
                  </svg>
                </button>
              {/if}
            </div>
          {/each}
        {/if}

        {#if dedupedGbif.length > 0}
          <div class="bg-stone-100 px-3 py-1.5 dark:bg-stone-700/30">
            <span class="text-xs font-medium uppercase tracking-wide text-stone-500">
              {m.search_species_section_gbif()}
            </span>
          </div>
          {#each dedupedGbif as gbif (gbif.gbif_key)}
            {@const alreadyAdded = gbifAdded(gbif)}
            <div
              class="flex items-center justify-between px-3 py-2 {alreadyAdded
                ? 'opacity-50'
                : 'hover:bg-stone-100 dark:hover:bg-stone-700/50'}"
            >
              <span class="min-w-0 flex-1 truncate text-sm text-stone-900 dark:text-stone-100">
                {gbifLabel(gbif)}
              </span>
              {#if alreadyAdded}
                <svg
                  class="h-4 w-4 shrink-0 text-stone-400"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  aria-hidden="true"
                >
                  <path d="M20 6 9 17l-5-5" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
              {:else}
                <button
                  type="button"
                  class="ml-2 shrink-0 text-primary-600 transition-colors hover:text-primary-700 dark:text-primary-400"
                  onclick={() => pickGbif(gbif)}
                  aria-label="Add {gbif.canonical_name}"
                >
                  <svg
                    class="h-4 w-4"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                    aria-hidden="true"
                  >
                    <path d="M12 5v14M5 12h14" stroke-linecap="round" />
                  </svg>
                </button>
              {/if}
            </div>
          {/each}
        {/if}
      </div>
    {/if}

    {#if showCustomRow}
      <div class="text-sm text-stone-500">
        <p>{m.search_species_selector_custom_hint()}</p>
        <div class="mt-1 flex items-center gap-2">
          <span class="italic">"{query.trim()}"</span>
          <button
            type="button"
            class="rounded border border-stone-300 px-2 py-0.5 text-xs text-stone-700 transition-colors hover:border-primary-400 hover:text-primary-700 dark:border-stone-600"
            onclick={pickCustom}
          >
            {m.search_species_selector_add_custom()}
          </button>
        </div>
      </div>
    {/if}

    {#if onClose}
      <div class="text-right">
        <button
          type="button"
          class="text-sm text-stone-500 transition-colors hover:text-stone-700 dark:hover:text-stone-200"
          onclick={onClose}
        >
          {m.search_species_selector_close()}
        </button>
      </div>
    {/if}
  </div>
{:else if mode === 'palette-search'}
  <!-- ============================================================ -->
  <!-- palette-search: single-pick dropdown (taxa + GBIF)           -->
  <!-- ============================================================ -->
  <div class="relative">
    <input
      bind:this={inputEl}
      type="search"
      class="w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/20 dark:border-stone-600 dark:bg-stone-800 dark:text-stone-100"
      placeholder={resolvedPlaceholder}
      bind:value={query}
      oninput={handleInput}
      onkeydown={handleKeydown}
      oncompositionstart={() => (isComposing = true)}
      oncompositionend={() => (isComposing = false)}
      onfocus={() => {
        if (query.trim().length >= 2) showDropdown = true;
      }}
      onblur={handleBlur}
      aria-label={resolvedPlaceholder}
    />
    {#if showDropdown && query.trim().length >= 2}
      <div
        class="absolute left-0 right-0 top-full z-20 mt-1 max-h-72 overflow-y-auto rounded-lg border border-stone-200 bg-white shadow-lg dark:border-stone-700 dark:bg-stone-800"
      >
        {#if isLoading}
          <div class="p-3 text-center text-sm text-stone-500">
            {m.annotation_editor_palette_searching()}
          </div>
        {:else if !hasAnyResult}
          <div class="p-3 text-center text-sm text-stone-400">
            {m.annotation_editor_palette_no_matches()}
          </div>
        {:else}
          <ul role="listbox" aria-label={m.annotation_editor_palette_add()}>
            {#each dedupedTaxa as taxon (taxon.id)}
              {@const alreadyAdded = taxonAdded(taxon)}
              <li>
                <button
                  type="button"
                  class="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50 dark:hover:bg-stone-700/40"
                  disabled={alreadyAdded}
                  onclick={() => pickTaxon(taxon)}
                >
                  <span class="min-w-0 truncate text-stone-900 dark:text-stone-100">
                    {taxonLabel(taxon)}
                  </span>
                  <span class="flex-shrink-0 text-xs text-stone-400">{alreadyAdded ? '✓' : '+'}</span>
                </button>
              </li>
            {/each}
            {#each dedupedGbif as gbif (gbif.gbif_key)}
              {@const alreadyAdded = gbifAdded(gbif)}
              <li>
                <button
                  type="button"
                  class="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50 dark:hover:bg-stone-700/40"
                  disabled={alreadyAdded}
                  onclick={() => pickGbif(gbif)}
                >
                  <span class="min-w-0 truncate text-stone-900 dark:text-stone-100">
                    {gbifLabel(gbif)}
                  </span>
                  <span class="flex-shrink-0 text-[10px] uppercase tracking-wide text-stone-400">
                    {alreadyAdded ? '✓' : 'GBIF'}
                  </span>
                </button>
              </li>
            {/each}
          </ul>
        {/if}
      </div>
    {/if}
  </div>
{:else}
  <!-- ============================================================ -->
  <!-- tag-select: chips + local filter dropdown (+ optional GBIF)  -->
  <!-- ============================================================ -->
  <div class="flex flex-col gap-2">
    {#if selectedTags.length > 0}
      <div class="flex flex-wrap gap-1.5">
        {#each selectedTags as tag (tag.id)}
          <span
            class="inline-flex items-center gap-1 rounded-full bg-primary-100 px-2 py-1 text-xs font-medium text-primary-800 dark:bg-primary-900/30 dark:text-primary-300"
          >
            <span class="max-w-[200px] truncate">{tag.name}</span>
            <button
              type="button"
              class="opacity-70 transition hover:opacity-100"
              onclick={() => onTagRemove?.(tag.id)}
              aria-label="Remove {tag.name}"
            >
              &times;
            </button>
          </span>
        {/each}
      </div>
    {/if}

    <div class="relative">
      <input
        bind:this={inputEl}
        type="text"
        class="w-full rounded-md border border-stone-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-stone-600 dark:bg-stone-800 dark:text-stone-100"
        placeholder={resolvedPlaceholder}
        bind:value={query}
        oninput={handleInput}
        onfocus={() => (showDropdown = true)}
        onblur={handleBlur}
        onkeydown={handleKeydown}
        oncompositionstart={() => (isComposing = true)}
        oncompositionend={() => (isComposing = false)}
        autocomplete="off"
      />

      {#if showDropdown}
        <div
          class="absolute left-0 right-0 top-full z-50 mt-1 max-h-80 overflow-y-auto rounded-md border border-stone-200 bg-surface-card shadow-lg dark:border-stone-700"
          role="listbox"
          aria-label={m.annotation_tag_selector_tags_header()}
        >
          {#if filteredTags.length > 0}
            <div class="py-1">
              <div
                class="px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-stone-500"
              >
                {m.annotation_tag_selector_tags_header()}
              </div>
              {#each filteredTags as tag, index (tag.id)}
                {@const alreadyAdded = tagAdded(tag)}
                <!-- svelte-ignore a11y_click_events_have_key_events -->
                <!-- svelte-ignore a11y_interactive_supports_focus -->
                <div
                  class="flex items-center gap-2 px-3 py-2 {alreadyAdded
                    ? 'cursor-not-allowed opacity-50'
                    : 'cursor-pointer hover:bg-stone-100 dark:hover:bg-stone-700/50'}"
                  role="option"
                  aria-selected="false"
                  aria-disabled={alreadyAdded}
                  onclick={() => pickTag(tag)}
                >
                  <span
                    class="inline-flex h-5 w-5 flex-shrink-0 items-center justify-center rounded bg-stone-100 font-mono text-[11px] text-stone-400 dark:bg-stone-800"
                  >
                    {index < 9 ? index + 1 : ''}
                  </span>
                  <span class="min-w-0 flex-1">
                    <span class="block truncate text-sm text-stone-900 dark:text-stone-100">
                      {tag.name}
                    </span>
                    {#if tag.scientific_name}
                      <span class="block truncate text-xs italic text-stone-500">
                        {tag.scientific_name}
                      </span>
                    {/if}
                  </span>
                </div>
              {/each}
            </div>
          {:else if query.trim() === ''}
            <div class="p-3 text-center text-sm text-stone-400">
              {m.annotation_tag_selector_type_to_search()}
            </div>
          {:else}
            <div class="p-3 text-center text-sm text-stone-400">
              {m.annotation_tag_selector_no_match()}
            </div>
          {/if}

          {#if showGBIF && query.trim().length >= 2}
            <div class="border-t border-stone-200 py-1 dark:border-stone-700">
              <div
                class="px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-stone-500"
              >
                {m.annotation_tag_selector_gbif_header()}
              </div>
              {#if isLoading}
                <div class="p-3 text-center text-sm text-stone-500">
                  {m.annotation_tag_selector_gbif_searching()}
                </div>
              {:else if dedupedGbif.length > 0}
                {#each dedupedGbif as gbif (gbif.gbif_key)}
                  {@const alreadyAdded = gbifAdded(gbif)}
                  <!-- svelte-ignore a11y_click_events_have_key_events -->
                  <!-- svelte-ignore a11y_interactive_supports_focus -->
                  <div
                    class="flex items-center justify-between gap-2 px-3 py-2 {alreadyAdded
                      ? 'cursor-not-allowed opacity-50'
                      : 'cursor-pointer hover:bg-stone-100 dark:hover:bg-stone-700/50'}"
                    role="option"
                    aria-selected="false"
                    aria-disabled={alreadyAdded}
                    onclick={() => pickGbif(gbif)}
                  >
                    <span class="min-w-0 flex-1 truncate text-sm text-stone-900 dark:text-stone-100">
                      {gbifLabel(gbif)}
                    </span>
                    {#if gbif.rank}
                      <span class="flex-shrink-0 text-[11px] text-stone-400">{gbif.rank}</span>
                    {/if}
                  </div>
                {/each}
              {:else}
                <div class="p-3 text-center text-sm text-stone-400">
                  {m.annotation_tag_selector_gbif_no_results()}
                </div>
              {/if}
            </div>
          {/if}
        </div>
      {/if}
    </div>
  </div>
{/if}
