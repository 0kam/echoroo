<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  // @ts-expect-error - h3-js doesn't have TypeScript declarations
  import { cellToBoundary, latLngToCell, isValidCell, getResolution, cellToLatLng } from 'h3-js';

  export let h3Index: string = '';
  export let resolution: number = 9;
  export let onSelect: (h3Index: string, center: [number, number]) => void = () => {};

  let mapContainer: HTMLDivElement;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let map: any = null;
  let selectedH3: string | null = h3Index || null;

  // Default center (Tokyo)
  const defaultCenter: [number, number] = [139.6917, 35.6895];
  const defaultZoom = 10;

  onMount(async () => {
    // Dynamically import mapbox-gl to avoid SSR issues
    // @ts-expect-error - mapbox-gl types not available for dynamic import
    const mapboxglModule = await import('mapbox-gl');
    const mapboxgl = mapboxglModule.default;
    await import('mapbox-gl/dist/mapbox-gl.css');

    // Use public style (no token required for basic maps)
    map = new mapboxgl.Map({
      container: mapContainer,
      style: 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
      center: defaultCenter,
      zoom: defaultZoom,
    });

    map.addControl(new mapboxgl.NavigationControl(), 'top-right');

    map.on('load', () => {
      // Add source for H3 hexagons
      map!.addSource('h3-hexagons', {
        type: 'geojson',
        data: {
          type: 'FeatureCollection',
          features: [],
        },
      });

      // Add fill layer
      map!.addLayer({
        id: 'h3-hexagons-fill',
        type: 'fill',
        source: 'h3-hexagons',
        paint: {
          'fill-color': '#3b82f6',
          'fill-opacity': 0.4,
        },
      });

      // Add outline layer
      map!.addLayer({
        id: 'h3-hexagons-outline',
        type: 'line',
        source: 'h3-hexagons',
        paint: {
          'line-color': '#1d4ed8',
          'line-width': 2,
        },
      });

      // Show initial selection if provided
      if (h3Index && isValidCell(h3Index)) {
        showHexagon(h3Index);
        const [lat, lng] = cellToLatLng(h3Index);
        map!.setCenter([lng, lat]);
      }
    });

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    map.on('click', (e: any) => {
      const { lat, lng } = e.lngLat;
      const h3Cell = latLngToCell(lat, lng, resolution);
      selectedH3 = h3Cell;
      showHexagon(h3Cell);
      onSelect(h3Cell, [lat, lng]);
    });
  });

  onDestroy(() => {
    if (map) {
      map.remove();
      map = null;
    }
  });

  function showHexagon(h3Cell: string) {
    if (!map) return;

    const boundary = cellToBoundary(h3Cell, true);
    const coordinates = boundary.map(([lat, lng]: [number, number]) => [lng, lat]);
    coordinates.push(coordinates[0]); // Close the polygon

    const geojson = {
      type: 'FeatureCollection' as const,
      features: [
        {
          type: 'Feature' as const,
          properties: { h3Index: h3Cell },
          geometry: {
            type: 'Polygon' as const,
            coordinates: [coordinates],
          },
        },
      ],
    };

    const source = map.getSource('h3-hexagons');
    if (source) {
      source.setData(geojson);
    }
  }

  // Update hexagon when resolution changes
  $: if (map && selectedH3) {
    const [lat, lng] = cellToLatLng(selectedH3);
    const newH3 = latLngToCell(lat, lng, resolution);
    if (newH3 !== selectedH3) {
      selectedH3 = newH3;
      showHexagon(newH3);
      onSelect(newH3, [lat, lng]);
    }
  }
</script>

<div class="h3-map-picker">
  <div bind:this={mapContainer} class="map-container"></div>

  <div class="controls">
    <label>
      Resolution:
      <input type="range" bind:value={resolution} min="5" max="15" step="1" />
      <span>{resolution}</span>
    </label>
  </div>

  {#if selectedH3}
    <div class="selection-info">
      <p><strong>Selected H3:</strong> <code>{selectedH3}</code></p>
    </div>
  {/if}
</div>

<style>
  .h3-map-picker {
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .map-container {
    width: 100%;
    height: 400px;
    border-radius: 0.5rem;
    border: 1px solid #e5e7eb;
  }

  .controls {
    display: flex;
    gap: 1rem;
    align-items: center;
  }

  .controls label {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.875rem;
    color: #374151;
  }

  .controls input[type='range'] {
    width: 150px;
  }

  .selection-info {
    padding: 0.75rem;
    background: #f3f4f6;
    border-radius: 0.375rem;
    font-size: 0.875rem;
  }

  .selection-info code {
    font-family: monospace;
    background: #e5e7eb;
    padding: 0.125rem 0.25rem;
    border-radius: 0.25rem;
  }
</style>
