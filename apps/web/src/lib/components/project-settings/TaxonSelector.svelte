<script lang="ts">
  /**
   * TaxonSelector — checkbox group for a project's target taxa.
   *
   * Extracted from the project settings page. Owns the canonical list of
   * target-taxa options (label messages resolved lazily via Paraglide) and
   * two-way binds the selected values back to the parent form.
   */
  import * as m from '$lib/paraglide/messages';

  interface Props {
    /** Currently selected taxa values (two-way bound). */
    selectedTaxa: string[];
    /** Disables interaction while the parent form is saving. */
    disabled?: boolean;
  }

  let { selectedTaxa = $bindable(), disabled = false }: Props = $props();

  const TARGET_TAXA_OPTIONS = [
    { value: 'Birds', label: m.project_target_taxa_option_birds },
    { value: 'Anurans', label: m.project_target_taxa_option_anurans },
    { value: 'Insects', label: m.project_target_taxa_option_insects },
    { value: 'Bats', label: m.project_target_taxa_option_bats },
    { value: 'Land mammals', label: m.project_target_taxa_option_land_mammals },
    { value: 'Fishes', label: m.project_target_taxa_option_fishes },
    { value: 'Cetaceans', label: m.project_target_taxa_option_cetaceans },
  ];

  function toggleTaxon(value: string) {
    selectedTaxa = selectedTaxa.includes(value)
      ? selectedTaxa.filter((taxon) => taxon !== value)
      : [...selectedTaxa, value];
  }
</script>

<div>
  <span id="target-taxa-label" class="block text-sm font-medium text-stone-700">
    {m.project_settings_target_taxa_label()}
  </span>
  <div
    role="group"
    class="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3"
    aria-labelledby="target-taxa-label"
  >
    {#each TARGET_TAXA_OPTIONS as option (option.value)}
      {@const selected = selectedTaxa.includes(option.value)}
      <label
        class={`flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors ${
          disabled ? 'cursor-not-allowed opacity-50' : ''
        } ${
          selected
            ? 'border-primary-500 bg-primary-50 text-primary-700'
            : 'border-stone-200 bg-surface-card text-stone-700 hover:bg-stone-50'
        }`}
      >
        <input
          type="checkbox"
          value={option.value}
          checked={selectedTaxa.includes(option.value)}
          {disabled}
          onchange={() => toggleTaxon(option.value)}
          class="h-4 w-4 rounded border-stone-300 text-primary-600 focus:ring-primary-500"
        />
        {option.label()}
      </label>
    {/each}
  </div>
  <p class="mt-1 text-xs text-stone-500">{m.project_settings_target_taxa_hint()}</p>
</div>
