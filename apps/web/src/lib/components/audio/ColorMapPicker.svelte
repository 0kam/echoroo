<script lang="ts">
  export let value: string = 'viridis';
  export let onChange: (colormap: string) => void;

  const colormaps = [
    { name: 'viridis', colors: ['#440154', '#21918c', '#fde725'] },
    { name: 'magma', colors: ['#000004', '#b73779', '#fcfdbf'] },
    { name: 'inferno', colors: ['#000004', '#bc3754', '#fcffa4'] },
    { name: 'plasma', colors: ['#0d0887', '#cc4778', '#f0f921'] },
    { name: 'cividis', colors: ['#00224e', '#7d7d7d', '#fee838'] },
    { name: 'gray', colors: ['#000000', '#808080', '#ffffff'] },
    { name: 'cool', colors: ['#00ffff', '#ff00ff'] },
    { name: 'twilight', colors: ['#e2d9e2', '#5e4fa2', '#e2d9e2'] },
  ];
</script>

<div class="colormap-picker">
  {#each colormaps as cmap}
    <button
      type="button"
      onclick={() => onChange(cmap.name)}
      class="colormap-option"
      class:selected={value === cmap.name}
    >
      <div
        class="colormap-preview"
        style="background: linear-gradient(to right, {cmap.colors.join(', ')})"
      ></div>
      <span class="colormap-name">{cmap.name}</span>
    </button>
  {/each}
</div>

<style>
  .colormap-picker {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
  }

  .colormap-option {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 0.375rem;
    background: white;
    border: 2px solid transparent;
    border-radius: 0.375rem;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .colormap-option:hover {
    border-color: #d1d5db;
  }

  .colormap-option.selected {
    border-color: #3b82f6;
    background: #eff6ff;
  }

  .colormap-preview {
    width: 4rem;
    height: 1rem;
    border-radius: 0.25rem;
  }

  .colormap-name {
    margin-top: 0.25rem;
    font-size: 0.688rem;
    color: #6b7280;
    text-transform: capitalize;
  }

  .colormap-option.selected .colormap-name {
    color: #3b82f6;
    font-weight: 500;
  }
</style>
