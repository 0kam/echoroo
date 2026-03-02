<script lang="ts">
  import { COLORMAPS, type Colormap } from '$lib/types/audio';

  interface Props {
    value: Colormap;
    onChange: (colormap: string) => void;
  }

  let { value, onChange }: Props = $props();

  // Color gradient previews for each colormap
  const colormapPreviews: Record<Colormap, string[]> = {
    gray: ['#000000', '#808080', '#ffffff'],
    viridis: ['#440154', '#21918c', '#fde725'],
    magma: ['#000004', '#b73779', '#fcfdbf'],
    inferno: ['#000004', '#bc3754', '#fcffa4'],
    plasma: ['#0d0887', '#cc4778', '#f0f921'],
    cividis: ['#00224e', '#7d7d7d', '#fee838'],
    cool: ['#00ffff', '#7f00ff', '#ff00ff'],
    cubehelix: ['#000000', '#238543', '#ffffff'],
    twilight: ['#e2d9e2', '#5e4fa2', '#e2d9e2'],
  };
</script>

<div class="colormap-grid">
  {#each COLORMAPS as cmap}
    <button
      type="button"
      onclick={() => onChange(cmap)}
      class="colormap-option {value === cmap ? 'selected' : ''}"
      title={cmap}
    >
      <div
        class="colormap-preview"
        style="background: linear-gradient(to right, {(colormapPreviews[cmap] ?? ['#000', '#fff']).join(', ')})"
      ></div>
      <span class="colormap-name">{cmap}</span>
    </button>
  {/each}
</div>

<style>
  .colormap-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 0.375rem;
  }

  .colormap-option {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 0.25rem;
    background: white;
    border: 2px solid transparent;
    border-radius: 0.375rem;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  :global(.dark) .colormap-option {
    background: #3f3f46;
  }

  .colormap-option:hover {
    border-color: #d1d5db;
  }

  :global(.dark) .colormap-option:hover {
    border-color: #52525b;
  }

  .colormap-option.selected {
    border-color: #10b981;
    background: #ecfdf5;
  }

  :global(.dark) .colormap-option.selected {
    border-color: #10b981;
    background: #064e3b;
  }

  .colormap-preview {
    width: 4rem;
    height: 0.875rem;
    border-radius: 0.2rem;
  }

  .colormap-name {
    margin-top: 0.2rem;
    font-size: 0.625rem;
    color: #6b7280;
    text-transform: capitalize;
  }

  :global(.dark) .colormap-name {
    color: #a1a1aa;
  }

  .colormap-option.selected .colormap-name {
    color: #10b981;
    font-weight: 600;
  }
</style>
