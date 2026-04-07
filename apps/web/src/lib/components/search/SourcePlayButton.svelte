<script lang="ts">
  /**
   * SourcePlayButton - Play/stop button for a sound source.
   *
   * Handles two playback modes:
   * - Streaming (URL/S3): uses HTML Audio element
   * - Upload: uses Web Audio API with decoded buffer
   *
   * For XC URL sources also renders an external link to xeno-canto.org.
   */
  import * as m from '$lib/paraglide/messages.js';
  import type { SoundSource } from '$lib/types/search';

  interface Props {
    source: SoundSource;
    isPlaying: boolean;
    isUrlPlaying: boolean;
    urlAudioError: boolean;
    onTogglePlay: () => void;
    onToggleUrlPlay: () => void;
  }

  let {
    source,
    isPlaying,
    isUrlPlaying,
    urlAudioError,
    onTogglePlay,
    onToggleUrlPlay,
  }: Props = $props();

  const isStreamingSource = $derived(source.origin === 'url' || source.origin === 's3');
</script>

{#if isStreamingSource}
  <button
    type="button"
    class="shrink-0 transition-colors
           {urlAudioError
             ? 'text-danger hover:text-danger/80'
             : isUrlPlaying
               ? 'text-primary-600 hover:text-primary-700 dark:text-primary-400'
               : 'text-stone-500 hover:text-primary-600'}"
    onclick={onToggleUrlPlay}
    aria-label={isUrlPlaying ? m.search_clip_stop() : m.search_clip_play_selection()}
    title={urlAudioError ? 'Playback failed' : isUrlPlaying ? 'Pause' : 'Play preview'}
  >
    {#if urlAudioError}
      <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
        <circle cx="12" cy="12" r="10" />
        <path d="M12 8v4m0 4h.01" stroke-linecap="round" />
      </svg>
    {:else if isUrlPlaying}
      <svg class="h-4 w-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <rect x="6" y="4" width="4" height="16" rx="1" />
        <rect x="14" y="4" width="4" height="16" rx="1" />
      </svg>
    {:else}
      <svg class="h-4 w-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M8 5.14v13.72a1 1 0 0 0 1.5.86l11-6.86a1 1 0 0 0 0-1.72l-11-6.86A1 1 0 0 0 8 5.14z" />
      </svg>
    {/if}
  </button>

  {#if source.origin === 'url' && source.xc_id}
    <a
      href="https://xeno-canto.org/{source.xc_id}"
      target="_blank"
      rel="noopener noreferrer"
      class="shrink-0 text-stone-400 transition-colors hover:text-primary-600"
      title={m.search_xc_listen()}
      aria-label={m.search_xc_listen()}
    >
      <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
        <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14 21 3" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </a>
  {/if}
{:else}
  <button
    type="button"
    class="shrink-0 text-stone-500 transition-colors hover:text-primary-600"
    onclick={onTogglePlay}
    aria-label={isPlaying ? m.search_clip_stop() : m.search_clip_play_selection()}
  >
    {#if isPlaying}
      <svg class="h-4 w-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <rect x="6" y="6" width="12" height="12" rx="1" />
      </svg>
    {:else}
      <svg class="h-4 w-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M8 5.14v13.72a1 1 0 0 0 1.5.86l11-6.86a1 1 0 0 0 0-1.72l-11-6.86A1 1 0 0 0 8 5.14z" />
      </svg>
    {/if}
  </button>
{/if}
