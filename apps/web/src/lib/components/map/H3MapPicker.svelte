<script lang="ts">
  import { onMount, onDestroy, untrack } from 'svelte';
  import { cellToBoundary, latLngToCell, isValidCell, cellToLatLng } from 'h3-js';
  import * as maplibregl from 'maplibre-gl';
  import type * as GeoJSON from 'geojson';
  import 'maplibre-gl/dist/maplibre-gl.css';

  interface Props {
    h3Index?: string;
    resolution?: number;
    onSelect?: (h3Index: string, center: [number, number]) => void;
    /** When true, disables click-to-select and hides resolution/selection controls */
    readonly?: boolean;
  }

  let { h3Index = '', resolution = $bindable(9), onSelect = () => {}, readonly = false }: Props = $props();

  let mapContainer: HTMLDivElement;

  let map: maplibregl.Map | null = null;
  let mapLoaded = false;

  // Initial selected hex taken from the h3Index prop; the map click
  // handler mutates this later as the user picks new cells.
  let selectedH3 = $state<string | null>(untrack(() => h3Index || null));
  let hoverH3 = $state<string | null>(null);
  let lastH3IndexProp = $state<string>(untrack(() => h3Index));

  const defaultCenter: [number, number] = [139.6917, 35.6895];
  const defaultZoom = 10;

  function h3ToGeoJSON(h3Cell: string): GeoJSON.FeatureCollection {
    const boundary = cellToBoundary(h3Cell, true);
    const coordinates = boundary.map((c) => [c[0], c[1]]);
    return {
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          properties: {},
          geometry: {
            type: 'Polygon',
            coordinates: [coordinates],
          },
        },
      ],
    };
  }

  const emptyGeoJSON: GeoJSON.FeatureCollection = {
    type: 'FeatureCollection',
    features: [],
  };

  function updateSelectedHex(h3Cell: string) {
    if (!map || !mapLoaded) return;
    const source = map.getSource('h3-selected') as maplibregl.GeoJSONSource | undefined;
    if (source) {
      source.setData(h3ToGeoJSON(h3Cell));
    }
  }

  function clearSelectedHex() {
    if (!map || !mapLoaded) return;
    const source = map.getSource('h3-selected') as maplibregl.GeoJSONSource | undefined;
    if (source) {
      source.setData(emptyGeoJSON);
    }
  }

  function updateHoverHex(h3Cell: string | null) {
    if (!map || !mapLoaded) return;
    const source = map.getSource('h3-hover') as maplibregl.GeoJSONSource | undefined;
    if (source) {
      source.setData(h3Cell ? h3ToGeoJSON(h3Cell) : emptyGeoJSON);
    }
  }

  onMount(async () => {
    const maplibregl = await import('maplibre-gl');

    map = new maplibregl.Map({
      container: mapContainer,
      style: 'https://tiles.openfreemap.org/styles/liberty',
      center: defaultCenter,
      zoom: defaultZoom,
    });

    map.addControl(new maplibregl.NavigationControl(), 'top-right');

    map.on('load', () => {
      mapLoaded = true;

      map!.addSource('h3-hover', { type: 'geojson', data: emptyGeoJSON });
      map!.addLayer({
        id: 'h3-hover-fill',
        type: 'fill',
        source: 'h3-hover',
        paint: { 'fill-color': '#93c5fd', 'fill-opacity': 0.3 },
      });
      map!.addLayer({
        id: 'h3-hover-outline',
        type: 'line',
        source: 'h3-hover',
        paint: { 'line-color': '#3b82f6', 'line-width': 2 },
      });

      map!.addSource('h3-selected', { type: 'geojson', data: emptyGeoJSON });
      map!.addLayer({
        id: 'h3-selected-fill',
        type: 'fill',
        source: 'h3-selected',
        paint: { 'fill-color': '#ef4444', 'fill-opacity': 0.5 },
      });
      map!.addLayer({
        id: 'h3-selected-outline',
        type: 'line',
        source: 'h3-selected',
        paint: { 'line-color': '#dc2626', 'line-width': 3 },
      });

      if (h3Index && isValidCell(h3Index)) {
        selectedH3 = h3Index;
        updateSelectedHex(h3Index);
        const [lat, lng] = cellToLatLng(h3Index);
        map!.setCenter([lng, lat]);
      }
    });

    if (!readonly) {
      map.on('mousemove', (e: maplibregl.MapMouseEvent) => {
        const { lat, lng } = e.lngLat;
        const h3Cell = latLngToCell(lat, lng, resolution);
        if (h3Cell !== hoverH3) {
          hoverH3 = h3Cell;
          updateHoverHex(h3Cell);
        }
      });

      map.on('mouseleave', () => {
        hoverH3 = null;
        updateHoverHex(null);
      });

      map.on('click', (e: maplibregl.MapMouseEvent) => {
        const { lat, lng } = e.lngLat;
        const h3Cell = latLngToCell(lat, lng, resolution);
        selectedH3 = h3Cell;
        updateSelectedHex(h3Cell);
        onSelect(h3Cell, [lat, lng]);
      });
    }
  });

  onDestroy(() => {
    if (map) {
      map.remove();
      map = null;
      mapLoaded = false;
    }
  });

  $effect(() => {
    const incoming = h3Index;
    if (incoming === lastH3IndexProp) return;

    lastH3IndexProp = incoming;
    selectedH3 = incoming || null;

    if (!incoming || !isValidCell(incoming)) {
      clearSelectedHex();
      return;
    }

    updateSelectedHex(incoming);
    if (map && mapLoaded) {
      const [lat, lng] = cellToLatLng(incoming);
      map.setCenter([lng, lat]);
    }
  });

  $effect(() => {
    if (readonly) return;
    const currentResolution = resolution;
    const current = selectedH3;
    if (mapLoaded && current) {
      const [lat, lng] = cellToLatLng(current);
      const newH3 = latLngToCell(lat, lng, currentResolution);
      if (newH3 !== current) {
        selectedH3 = newH3;
        updateSelectedHex(newH3);
        onSelect(newH3, [lat, lng]);
      }
    }
  });
</script>

<div class="h3-map-picker">
  <div bind:this={mapContainer} class="map-container"></div>

  {#if !readonly}
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
