<script lang="ts">
  import type { Site, SiteCreate } from '$lib/types/data';
  import H3MapPicker from '$lib/components/map/H3MapPicker.svelte';
  import * as m from '$lib/paraglide/messages';

  interface Props {
    site?: Site | null;
    onSubmit: (data: SiteCreate) => Promise<void>;
    onCancel?: () => void;
  }

  let { site = null, onSubmit, onCancel = () => {} }: Props = $props();

  let name = $state('');
  let h3Index = $state('');
  let resolution = $state(9);

  // Initialize form fields from site prop once on mount
  $effect(() => {
    name = site?.name ?? '';
    h3Index = site?.h3_index ?? '';
  });
  let isSubmitting = $state(false);
  let error = $state('');

  function handleMapSelect(index: string, _center: [number, number]) {
    h3Index = index;
  }

  async function handleSubmit() {
    if (!name.trim()) {
      error = m.validation_name_required();
      return;
    }
    if (!h3Index) {
      error = m.validation_location_required();
      return;
    }

    error = '';
    isSubmitting = true;

    try {
      await onSubmit({ name: name.trim(), h3_index: h3Index });
    } catch (e) {
      error = e instanceof Error ? e.message : m.error_save_site();
    } finally {
      isSubmitting = false;
    }
  }
</script>

<form class="flex flex-col gap-6" onsubmit={(e) => { e.preventDefault(); handleSubmit(); }}>
  <div class="flex flex-col gap-2">
    <label for="name" class="text-sm font-medium text-gray-700">{m.form_site_name_label()} *</label>
    <input
      type="text"
      id="name"
      bind:value={name}
      placeholder={m.form_site_name_placeholder()}
      maxlength="200"
      required
      class="rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
    />
  </div>

  <div class="flex flex-col gap-2">
    <span class="text-sm font-medium text-gray-700">{m.form_site_location_label()} *</span>
    <p class="m-0 text-xs text-gray-500">{m.form_site_location_hint()}</p>
    <H3MapPicker {h3Index} {resolution} onSelect={handleMapSelect} />
  </div>

  {#if h3Index}
    <div class="flex flex-col gap-2">
      <label for="h3-index-display" class="text-sm font-medium text-gray-700">{m.form_site_h3_index_label()}</label>
      <input
        id="h3-index-display"
        type="text"
        value={h3Index}
        readonly
        class="rounded-md border border-gray-200 bg-gray-50 px-3 py-2 font-mono text-sm text-gray-600"
      />
    </div>
  {/if}

  {#if error}
    <div class="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">
      {error}
    </div>
  {/if}

  <div class="flex justify-end gap-3 border-t border-gray-200 pt-4">
    <button
      type="button"
      onclick={onCancel}
      disabled={isSubmitting}
      class="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {m.form_site_cancel()}
    </button>
    <button
      type="submit"
      disabled={isSubmitting || !name || !h3Index}
      class="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {isSubmitting ? m.form_site_saving() : site ? m.form_site_update() : m.form_site_create()}
    </button>
  </div>
</form>
