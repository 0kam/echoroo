<script lang="ts">
  import { untrack } from 'svelte';
  import type { SpectrogramSettings, Colormap, WindowFunction } from '$lib/types/audio';
  import { WINDOWS, MIN_DB, MIN_CANVAS_HEIGHT, MAX_CANVAS_HEIGHT, CANVAS_HEIGHT_STEP } from '$lib/types/audio';
  import ColorMapPicker from './ColorMapPicker.svelte';

  interface Props {
    settings: SpectrogramSettings;
    onChange: (settings: SpectrogramSettings) => void;
  }

  let { settings, onChange }: Props = $props();

  let isOpen = $state(true);

  // Local copies for immediate UI feedback. Initial values are captured
  // once via untrack(); the $effect below keeps them in sync with the
  // parent's settings prop on subsequent changes.
  let localWindowSize = $state(untrack(() => settings.window_size));
  let localOverlap = $state(untrack(() => settings.overlap));
  let localWindow = $state<WindowFunction>(untrack(() => settings.window));
  let localMinDb = $state(untrack(() => settings.min_dB));
  let localMaxDb = $state(untrack(() => settings.max_dB));
  let localHeight = $state(untrack(() => settings.height));

  // Debounce timeout for slider changes
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;

  function debounceEmit(updated: Partial<SpectrogramSettings>) {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      onChange({ ...settings, ...updated });
    }, 300);
  }

  function handleWindowSizeChange(e: Event) {
    const v = parseFloat((e.target as HTMLInputElement).value);
    localWindowSize = v;
    debounceEmit({ window_size: v });
  }

  function handleOverlapChange(e: Event) {
    const v = parseFloat((e.target as HTMLInputElement).value);
    localOverlap = v;
    debounceEmit({ overlap: v });
  }

  function handleWindowChange(e: Event) {
    const v = (e.target as HTMLSelectElement).value as WindowFunction;
    localWindow = v;
    onChange({ ...settings, window: v });
  }

  function handleMinDbChange(e: Event) {
    const v = parseFloat((e.target as HTMLInputElement).value);
    localMinDb = v;
    if (v < localMaxDb) debounceEmit({ min_dB: v });
  }

  function handleMaxDbChange(e: Event) {
    const v = parseFloat((e.target as HTMLInputElement).value);
    localMaxDb = v;
    if (v > localMinDb) debounceEmit({ max_dB: v });
  }

  function handleHeightChange(e: Event) {
    const v = parseInt((e.target as HTMLInputElement).value, 10);
    localHeight = v;
    debounceEmit({ height: v });
  }

  function handleColormapChange(cmap: string) {
    onChange({ ...settings, cmap: cmap as Colormap });
  }

  function togglePCEN() {
    onChange({ ...settings, pcen: !settings.pcen });
  }

  function toggleNormalize() {
    onChange({ ...settings, normalize: !settings.normalize });
  }

  function toggleClamp() {
    onChange({ ...settings, clamp: !settings.clamp });
  }

  // Sync local state when parent settings change
  $effect(() => {
    localWindowSize = settings.window_size;
    localOverlap = settings.overlap;
    localWindow = settings.window;
    localMinDb = settings.min_dB;
    localMaxDb = settings.max_dB;
    localHeight = settings.height;
  });
</script>

<div class="settings-panel">
  <button
    type="button"
    class="settings-toggle"
    onclick={() => (isOpen = !isOpen)}
    aria-expanded={isOpen}
  >
    <svg
      class="w-4 h-4 transition-transform {isOpen ? 'rotate-90' : ''}"
      viewBox="0 0 24 24"
      fill="currentColor"
    >
      <path d="M9 18l6-6-6-6" />
    </svg>
    <span class="font-medium text-sm">Spectrogram Settings</span>
  </button>

  {#if isOpen}
    <div class="settings-body">
      <!-- STFT settings -->
      <section class="setting-section">
        <h5 class="section-title">STFT Parameters</h5>

        <div class="setting-row">
          <label class="setting-label" for="window-size">Window size (s)</label>
          <div class="setting-control">
            <input
              id="window-size"
              type="range"
              min="0.001"
              max="0.1"
              step="0.001"
              value={localWindowSize}
              oninput={handleWindowSizeChange}
              class="slider"
            />
            <span class="value-badge">{localWindowSize.toFixed(3)}s</span>
          </div>
        </div>

        <div class="setting-row">
          <label class="setting-label" for="overlap">Overlap</label>
          <div class="setting-control">
            <input
              id="overlap"
              type="range"
              min="0.1"
              max="0.95"
              step="0.05"
              value={localOverlap}
              oninput={handleOverlapChange}
              class="slider"
            />
            <span class="value-badge">{Math.round(localOverlap * 100)}%</span>
          </div>
        </div>

        <div class="setting-row">
          <label class="setting-label" for="window-fn">Window function</label>
          <select
            id="window-fn"
            value={localWindow}
            onchange={handleWindowChange}
            class="setting-select"
          >
            {#each WINDOWS as win}
              <option value={win}>{win}</option>
            {/each}
          </select>
        </div>
      </section>

      <!-- De-noise section -->
      <section class="setting-section">
        <h5 class="section-title">De-noise</h5>
        <div class="toggle-row">
          <!-- svelte-ignore a11y_label_has_associated_control -->
          <label class="toggle-label">
            <div
              class="toggle {settings.pcen ? 'toggle-on' : 'toggle-off'}"
              onclick={togglePCEN}
              onkeydown={(e) => e.key === 'Enter' && togglePCEN()}
              role="switch"
              aria-checked={settings.pcen}
              tabindex="0"
            >
              <div class="toggle-thumb {settings.pcen ? 'translate-x-5' : 'translate-x-1'}"></div>
            </div>
            <span>PCEN normalization</span>
          </label>
        </div>
      </section>

      <!-- Color settings -->
      <section class="setting-section">
        <h5 class="section-title">Color</h5>
        <ColorMapPicker value={settings.cmap} onChange={handleColormapChange} />
      </section>

      <!-- Amplitude settings -->
      <section class="setting-section">
        <h5 class="section-title">Amplitude</h5>

        <div class="setting-row">
          <label class="setting-label" for="min-db">Min dB</label>
          <div class="setting-control">
            <input
              id="min-db"
              type="range"
              min={MIN_DB}
              max="-1"
              step="1"
              value={localMinDb}
              oninput={handleMinDbChange}
              class="slider"
            />
            <span class="value-badge">{localMinDb} dB</span>
          </div>
        </div>

        <div class="setting-row">
          <label class="setting-label" for="max-db">Max dB</label>
          <div class="setting-control">
            <input
              id="max-db"
              type="range"
              min={MIN_DB}
              max="0"
              step="1"
              value={localMaxDb}
              oninput={handleMaxDbChange}
              class="slider"
            />
            <span class="value-badge">{localMaxDb} dB</span>
          </div>
        </div>

        <div class="toggle-row">
          <!-- svelte-ignore a11y_label_has_associated_control -->
          <label class="toggle-label">
            <div
              class="toggle {settings.normalize ? 'toggle-on' : 'toggle-off'}"
              onclick={toggleNormalize}
              onkeydown={(e) => e.key === 'Enter' && toggleNormalize()}
              role="switch"
              aria-checked={settings.normalize}
              tabindex="0"
            >
              <div class="toggle-thumb {settings.normalize ? 'translate-x-5' : 'translate-x-1'}"></div>
            </div>
            <span>Normalize</span>
          </label>

          <!-- svelte-ignore a11y_label_has_associated_control -->
          <label class="toggle-label">
            <div
              class="toggle {settings.clamp ? 'toggle-on' : 'toggle-off'}"
              onclick={toggleClamp}
              onkeydown={(e) => e.key === 'Enter' && toggleClamp()}
              role="switch"
              aria-checked={settings.clamp}
              tabindex="0"
            >
              <div class="toggle-thumb {settings.clamp ? 'translate-x-5' : 'translate-x-1'}"></div>
            </div>
            <span>Clamp</span>
          </label>
        </div>
      </section>

      <!-- Display settings -->
      <section class="setting-section">
        <h5 class="section-title">Display</h5>

        <div class="setting-row">
          <label class="setting-label" for="canvas-height">Height (px)</label>
          <div class="setting-control">
            <input
              id="canvas-height"
              type="range"
              min={MIN_CANVAS_HEIGHT}
              max={MAX_CANVAS_HEIGHT}
              step={CANVAS_HEIGHT_STEP}
              value={localHeight}
              oninput={handleHeightChange}
              class="slider"
            />
            <span class="value-badge">{localHeight}px</span>
          </div>
        </div>
      </section>
    </div>
  {/if}
</div>

<style>
  .settings-panel {
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 0.5rem;
    overflow: hidden;
  }

  :global(.dark) .settings-panel {
    background: #27272a;
    border-color: #3f3f46;
  }

  .settings-toggle {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    width: 100%;
    padding: 0.75rem 1rem;
    background: none;
    border: none;
    cursor: pointer;
    color: #374151;
    text-align: left;
    transition: background 0.15s;
  }

  :global(.dark) .settings-toggle {
    color: #d4d4d8;
  }

  .settings-toggle:hover {
    background: #f3f4f6;
  }

  :global(.dark) .settings-toggle:hover {
    background: #3f3f46;
  }

  .settings-body {
    padding: 0 1rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .setting-section {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .section-title {
    font-size: 0.75rem;
    font-weight: 600;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin: 0;
  }

  :global(.dark) .section-title {
    color: #a1a1aa;
  }

  .setting-row {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }

  .setting-label {
    font-size: 0.8125rem;
    color: #374151;
    min-width: 7rem;
    flex-shrink: 0;
  }

  :global(.dark) .setting-label {
    color: #d4d4d8;
  }

  .setting-control {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex: 1;
  }

  .slider {
    flex: 1;
    height: 4px;
    -webkit-appearance: none;
    appearance: none;
    background: #e5e7eb;
    border-radius: 2px;
    cursor: pointer;
    accent-color: #10b981;
  }

  :global(.dark) .slider {
    background: #3f3f46;
  }

  .value-badge {
    font-size: 0.75rem;
    font-family: monospace;
    color: #6b7280;
    min-width: 4rem;
    text-align: right;
    flex-shrink: 0;
  }

  :global(.dark) .value-badge {
    color: #a1a1aa;
  }

  .setting-select {
    flex: 1;
    padding: 0.375rem 0.5rem;
    border: 1px solid #d1d5db;
    border-radius: 0.375rem;
    font-size: 0.8125rem;
    background: white;
    color: #374151;
  }

  :global(.dark) .setting-select {
    background: #3f3f46;
    border-color: #52525b;
    color: #d4d4d8;
  }

  .toggle-row {
    display: flex;
    flex-wrap: wrap;
    gap: 1rem;
  }

  .toggle-label {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.8125rem;
    color: #374151;
    cursor: pointer;
    user-select: none;
  }

  :global(.dark) .toggle-label {
    color: #d4d4d8;
  }

  .toggle {
    position: relative;
    width: 2.5rem;
    height: 1.25rem;
    border-radius: 9999px;
    cursor: pointer;
    transition: background 0.15s;
    flex-shrink: 0;
  }

  .toggle-on {
    background: #10b981;
  }

  .toggle-off {
    background: #d1d5db;
  }

  :global(.dark) .toggle-off {
    background: #52525b;
  }

  .toggle-thumb {
    position: absolute;
    top: 0.125rem;
    width: 1rem;
    height: 1rem;
    background: white;
    border-radius: 9999px;
    transition: transform 0.15s;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
  }
</style>
