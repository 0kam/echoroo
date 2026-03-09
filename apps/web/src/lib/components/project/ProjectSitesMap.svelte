<script lang="ts">
  /**
   * ProjectSitesMap - Read-only map showing project site locations.
   *
   * Displays H3 hexagon polygons for each site along with SVG pin markers.
   * Auto-fits bounds to show all sites. Hover shows site name and recording count.
   */

  import { onMount, onDestroy } from 'svelte';
  import { goto } from '$app/navigation';
  import { cellToBoundary, cellToLatLng, isValidCell } from 'h3-js';
  import 'maplibre-gl/dist/maplibre-gl.css';
  import { localizeHref } from '$lib/paraglide/runtime';
  import type { ProjectOverviewSite } from '$lib/types';

  interface Props {
    sites: ProjectOverviewSite[];
    projectId: string;
  }

  let { sites, projectId }: Props = $props();

  let mapContainer: HTMLDivElement | undefined = $state();
  let map: import('maplibre-gl').Map | null = null;
  let mapLoaded = false;
  let markers: import('maplibre-gl').Marker[] = [];

  function buildHexGeoJSON(siteList: ProjectOverviewSite[]): GeoJSON.FeatureCollection {
    const features: GeoJSON.Feature[] = [];
    for (const site of siteList) {
      if (!site.h3_index || !isValidCell(site.h3_index)) continue;
      // cellToBoundary returns [lat, lng][] in h3-js v4; swap to [lng, lat] for GeoJSON.
      const boundary = cellToBoundary(site.h3_index);
      // Explicitly map to [lng, lat] and close the ring (GeoJSON requires first === last).
      const ring: [number, number][] = boundary.map((c): [number, number] => [c[1], c[0]]);
      const first = ring[0];
      if (first) ring.push(first); // close polygon ring
      const coordinates = ring;
      features.push({
        type: 'Feature',
        properties: {
          site_id: site.id,
          name: site.name,
          recording_count: site.recording_count,
        },
        geometry: {
          type: 'Polygon',
          coordinates: [coordinates],
        },
      });
    }
    return { type: 'FeatureCollection', features };
  }

  /**
   * Create a safe SVG pin marker element using DOM APIs (no innerHTML).
   */
  function createPinElement(siteId: string, siteName: string, recordingCount: number): HTMLDivElement {
    const wrapper = document.createElement('div');
    wrapper.style.position = 'relative';
    wrapper.style.cursor = 'pointer';
    // Ensure the wrapper shrinks to fit the SVG content.
    // Without this, a block-level div expands to full container width,
    // which causes the anchor transform to be computed incorrectly.
    wrapper.style.display = 'inline-block';
    wrapper.style.lineHeight = '0';
    // Allow tooltip to overflow beyond the wrapper bounds (SVG is only 24px wide).
    wrapper.style.overflow = 'visible';

    // SVG pin icon
    const svgNS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(svgNS, 'svg');
    svg.setAttribute('width', '24');
    svg.setAttribute('height', '32');
    svg.setAttribute('viewBox', '0 0 24 32');

    const path = document.createElementNS(svgNS, 'path');
    path.setAttribute(
      'd',
      'M12 0C5.373 0 0 5.373 0 12c0 8.25 12 20 12 20S24 20.25 24 12C24 5.373 18.627 0 12 0z'
    );
    path.setAttribute('fill', '#2563eb');
    path.setAttribute('stroke', '#1d4ed8');
    path.setAttribute('stroke-width', '1');

    const circle = document.createElementNS(svgNS, 'circle');
    circle.setAttribute('cx', '12');
    circle.setAttribute('cy', '12');
    circle.setAttribute('r', '5');
    circle.setAttribute('fill', 'white');

    svg.appendChild(path);
    svg.appendChild(circle);
    wrapper.appendChild(svg);

    // Tooltip
    const tooltip = document.createElement('div');
    tooltip.style.cssText = [
      'position: absolute',
      'background: #111827',
      'color: white',
      'font-size: 12px',
      'line-height: 1.4',
      'padding: 4px 8px',
      'border-radius: 4px',
      'white-space: nowrap',
      'pointer-events: none',
      'bottom: 36px',
      // Center over the 24px-wide SVG pin: left=12px (half of pin width) then shift by -50% of tooltip width.
      'left: 12px',
      'transform: translateX(-50%)',
      'display: none',
      'z-index: 1000',
      'width: max-content',
    ].join(';');

    // Safe text content only
    const nameSpan = document.createElement('span');
    nameSpan.textContent = `${siteName} (${recordingCount} recordings)`;
    tooltip.appendChild(nameSpan);

    wrapper.appendChild(tooltip);

    wrapper.addEventListener('mouseenter', () => {
      tooltip.style.display = 'inline-block';
    });
    wrapper.addEventListener('mouseleave', () => {
      tooltip.style.display = 'none';
    });

    wrapper.addEventListener('click', (e) => {
      // Prevent the map click event from firing
      e.stopPropagation();
      goto(localizeHref(`/projects/${projectId}/sites/${siteId}`));
    });

    return wrapper;
  }

  function addMarkers(
    mapInstance: import('maplibre-gl').Map,
    maplibregl: typeof import('maplibre-gl'),
    siteList: ProjectOverviewSite[]
  ) {
    // Clear existing markers
    for (const marker of markers) {
      marker.remove();
    }
    markers = [];

    for (const site of siteList) {
      if (!site.h3_index || !isValidCell(site.h3_index)) continue;

      // Always derive marker position from H3 cell center to ensure it aligns with the hex polygon.
      // cellToLatLng returns [lat, lng]; MapLibre expects [lng, lat].
      const [lat, lng] = cellToLatLng(site.h3_index);

      const el = createPinElement(site.id, site.name, site.recording_count);

      const marker = new maplibregl.Marker({ element: el, anchor: 'bottom' })
        .setLngLat([lng, lat])
        .addTo(mapInstance);

      markers.push(marker);
    }
  }

  function fitBounds(
    mapInstance: import('maplibre-gl').Map,
    maplibregl: typeof import('maplibre-gl'),
    siteList: ProjectOverviewSite[]
  ) {
    const coords: [number, number][] = [];

    for (const site of siteList) {
      if (site.latitude != null && site.longitude != null) {
        coords.push([site.longitude, site.latitude]);
      } else if (site.h3_index && isValidCell(site.h3_index)) {
        const [lat, lng] = cellToLatLng(site.h3_index);
        coords.push([lng, lat]);
      }
    }

    if (coords.length === 0) return;

    if (coords.length === 1) {
      const singleCoord = coords[0];
      if (singleCoord) {
        mapInstance.setCenter(singleCoord);
        mapInstance.setZoom(11);
      }
      return;
    }

    const lngs = coords.map((c) => c[0]);
    const lats = coords.map((c) => c[1]);
    const minLng = Math.min(...lngs);
    const maxLng = Math.max(...lngs);
    const minLat = Math.min(...lats);
    const maxLat = Math.max(...lats);

    const bounds = new maplibregl.LngLatBounds([minLng, minLat], [maxLng, maxLat]);
    mapInstance.fitBounds(bounds, { padding: 60, maxZoom: 13 });
  }

  onMount(async () => {
    if (!mapContainer) return;

    const maplibregl = await import('maplibre-gl');

    map = new maplibregl.Map({
      container: mapContainer,
      style: 'https://tiles.openfreemap.org/styles/liberty',
      center: [139.6917, 35.6895],
      zoom: 6,
      scrollZoom: false,
    });

    map.addControl(new maplibregl.NavigationControl(), 'top-right');

    map.on('load', () => {
      if (!map) return;
      mapLoaded = true;

      // Add H3 hex polygon source and layers
      map.addSource('sites-hex', {
        type: 'geojson',
        data: buildHexGeoJSON(sites),
      });

      map.addLayer({
        id: 'sites-hex-fill',
        type: 'fill',
        source: 'sites-hex',
        paint: {
          'fill-color': '#3b82f6',
          'fill-opacity': 0.2,
        },
      });

      map.addLayer({
        id: 'sites-hex-outline',
        type: 'line',
        source: 'sites-hex',
        paint: {
          'line-color': '#2563eb',
          'line-width': 2,
        },
      });

      // Add markers
      addMarkers(map, maplibregl, sites);

      // Fit map to show all sites
      fitBounds(map, maplibregl, sites);
    });
  });

  onDestroy(() => {
    for (const marker of markers) {
      marker.remove();
    }
    markers = [];
    if (map) {
      map.remove();
      map = null;
      mapLoaded = false;
    }
  });

  // Reactively update when sites prop changes
  $effect(() => {
    const currentSites = sites;
    if (!map || !mapLoaded) return;

    const source = map.getSource('sites-hex') as import('maplibre-gl').GeoJSONSource | undefined;
    if (source) {
      source.setData(buildHexGeoJSON(currentSites));
    }

    import('maplibre-gl').then((maplibregl) => {
      if (!map || !mapLoaded) return;
      addMarkers(map, maplibregl, currentSites);
      fitBounds(map, maplibregl, currentSites);
    });
  });
</script>

<div bind:this={mapContainer} class="h-[300px] w-full rounded-lg border border-stone-200"></div>
