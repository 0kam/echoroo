<script lang="ts">
  /**
   * SourceInfo - Displays name, clip range, and metadata for a sound source.
   *
   * In readonly mode the name is a button that toggles the spectrogram viewer.
   * Shows XC metadata (recordist, quality, location) for URL-origin sources.
   */
  import * as m from '$lib/paraglide/messages.js';
  import { formatLicenseLabel, licenseHref } from '$lib/utils/licenseFormatters';
  import type { SoundSource } from '$lib/types/search';

  interface Props {
    source: SoundSource;
    displayName: string;
    clipInfo: string;
    hasClipRange: boolean;
    readonly?: boolean;
    showSpectrogram?: boolean;
    isLoadingSpectrogram?: boolean;
    onToggleSpectrogram?: () => void;
  }

  let {
    source,
    displayName,
    clipInfo,
    hasClipRange,
    readonly = false,
    showSpectrogram = false,
    isLoadingSpectrogram = false,
    onToggleSpectrogram,
  }: Props = $props();
</script>

<div class="min-w-0 flex-1">
  {#if readonly}
    <button
      type="button"
      class="truncate text-sm font-medium transition-colors
             {showSpectrogram ? 'text-primary-600 dark:text-primary-400' : 'text-stone-900 hover:text-primary-600 dark:hover:text-primary-400'}
             {isLoadingSpectrogram ? 'animate-pulse' : ''}"
      onclick={onToggleSpectrogram}
      disabled={isLoadingSpectrogram}
      title={showSpectrogram ? 'Hide spectrogram' : 'Show spectrogram'}
    >
      {displayName}
    </button>
  {:else}
    <p class="truncate text-sm text-stone-900">{displayName}</p>
  {/if}

  {#if source.origin === 'url'}
    <p class="truncate text-xs text-stone-400">
      {[source.recording_type, source.quality ? `Q:${source.quality}` : null, source.recordist, source.location]
        .filter(Boolean)
        .join(' · ')}
    </p>
    {#if hasClipRange}
      <p class="text-xs text-primary-600 dark:text-primary-400">
        {m.search_clip_range({ start: (source.start_time ?? 0).toFixed(1) + 's', end: (source.end_time ?? 0).toFixed(1) + 's' })}
      </p>
    {/if}
    {#if source.license}
      {@const licLabel = formatLicenseLabel(source.license)}
      {@const licUrl = licenseHref(source.license)}
      <p class="truncate text-xs text-stone-400">
        {m.search_license_label()}:
        {#if licUrl}
          <a href={licUrl} target="_blank" rel="noopener noreferrer" class="hover:underline">{licLabel}</a>
        {:else}
          {licLabel}
        {/if}
        {#if source.xc_id}
          &middot;
          <a
            href={`https://xeno-canto.org/${source.xc_id}`}
            target="_blank"
            rel="noopener noreferrer"
            class="hover:underline"
          >XC{source.xc_id}</a>
        {/if}
      </p>
    {/if}
  {:else}
    <p class="text-xs text-stone-400">{clipInfo}</p>
  {/if}
</div>
