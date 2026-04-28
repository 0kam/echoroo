<script lang="ts" module>
  /**
   * HSpecYMaps — Hidden-Species Y-Maps.
   *
   * A read-only MapLibre-GL component that renders geographic detections
   * whose precise coordinates are intentionally absent (FR-030, FR-031).
   * The only spatial signal we receive is an `h3_index` whose resolution
   * has been clamped server-side via `compute_effective_resolution`
   * (FR-029, research §10):
   *
   *   res 15 — Member-precise (~0.5 m)         → point marker
   *   res 9  — Open / non-member default (~174 m) → small circle marker
   *   res 7  — Coarse (~1.2 km)                  → hex polygon
   *   res 5  — Very coarse (~9 km)               → hex polygon
   *   res 2  — HIDDEN (~158 km)                  → "Restricted location" pin only
   *
   * The component keeps ALL location precision logic on the backend.  We
   * never derive a finer resolution from `h3_index`; we only switch how the
   * cell is visualised based on its already-clamped resolution.
   *
   * Live-updating `points` reactively re-renders sources, markers, and
   * bounds.  Clicking a point fires `onSelect(point)` so callers can wire
   * detection details.
   */

  /**
   * A single point to render on the HSpec Y-Map.
   *
   * `latitude` / `longitude` MUST NOT appear here — that is FR-030 enforced
   * at the API layer.  All spatial signal comes from `h3_index`.
   */
  export interface HSpecPoint {
    /** Stable identifier (e.g. detection id or site id). */
    id: string;
    /**
     * H3 cell at the **effective** resolution returned by the API.
     * `null` means the location is unresolved / suppressed entirely and
     * the point is omitted from the map.
     */
    h3_index: string | null;
    /** Optional short label shown in the tooltip (e.g. species name). */
    label?: string | null;
    /**
     * Optional secondary line in the tooltip (e.g. detection count or
     * timestamp).  Plain text only — rendered via `textContent`.
     */
    sublabel?: string | null;
    /**
     * Optional override colour.  When omitted, the precision tier colour
     * is used (rose for member-precise, foam for open, gold for coarse,
     * love for very coarse, muted for hidden).
     */
    color?: string | null;
  }

  /** Internal precision tier derived from h3 resolution. */
  type PrecisionTier = 'member' | 'open' | 'coarse' | 'very_coarse' | 'hidden';
</script>

<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { cellToBoundary, cellToLatLng, getResolution, isValidCell } from 'h3-js';
  import type * as GeoJSON from 'geojson';
  import 'maplibre-gl/dist/maplibre-gl.css';
  import * as m from '$lib/paraglide/messages';

  interface Props {
    /** Points to render. */
    points: HSpecPoint[];
    /** Optional fixed height. Defaults to 320px. */
    height?: string;
    /** Click handler invoked with the clicked point. */
    onSelect?: (point: HSpecPoint) => void;
    /**
     * Initial map centre [lng, lat]. Only used when `points` is empty
     * during initial mount.  Subsequent prop updates auto-fit bounds.
     */
    initialCenter?: [number, number];
    /** Initial zoom. */
    initialZoom?: number;
    /**
     * When `true` (default), the map auto-fits its viewport to the
     * supplied points on every prop update.  Set `false` for callers that
     * prefer to keep the current camera once the user has interacted with
     * the map (Round 1 review B3 — avoid jank from constant re-fit).
     */
    fitOnUpdate?: boolean;
  }

  const {
    points,
    height = '320px',
    onSelect = () => {},
    initialCenter = [139.6917, 35.6895],
    initialZoom = 4,
    fitOnUpdate = false,
  }: Props = $props();

  let mapContainer: HTMLDivElement | undefined = $state();
  let map: import('maplibre-gl').Map | null = null;
  let mapLoaded = false;
  /**
   * Tracks per-marker DOM nodes that need metadata refresh whenever the
   * caller mutates the underlying point (Round 3 review B3).  The marker
   * element itself owns aria/title/data-* attributes; the optional `text`
   * node is the visible pill label for hidden pins; `tooltip` rebuilds the
   * tooltip body without touching pointer/focus state; `latest` is the
   * mutable closure target that event listeners read from so handlers do
   * not have to be removed/re-added when the point changes.
   */
  interface MarkerEntry {
    marker: import('maplibre-gl').Marker;
    tier: PrecisionTier;
    /** Mutable reference event handlers close over. */
    latest: { point: HSpecPoint; tier: PrecisionTier };
    /** Refresh aria/title/data + visible text + tooltip for a new point. */
    refresh: (point: HSpecPoint) => void;
  }
  /**
   * Round 1 review B3: maintain a stable id → marker map so live updates
   * patch only what changed instead of recreating every DOM marker.  The
   * tier is tracked alongside so we can detect when the same id transitions
   * between tiers (e.g. a detection that becomes obscured).
   */
  let markerById: Map<string, MarkerEntry> = new Map();
  /**
   * Round 3 review B4: focus-dot overlay markers attached to polygon tiers
   * so keyboard users can activate the polygon's onSelect.  Keyed by point
   * id and recreated when the underlying tier/h3_index changes.
   */
  let focusDotById: Map<string, MarkerEntry> = new Map();
  let maplibre: typeof import('maplibre-gl') | null = null;
  /** Round 1 review B2: guard against onMount → onDestroy race. */
  let disposed = false;
  /** True only for the very first refresh after mapLoaded. */
  let firstRefresh = true;

  // ---------------------------------------------------------------------
  // Pure helpers
  // ---------------------------------------------------------------------

  /**
   * Map an H3 resolution to a coarse precision tier used by the renderer.
   *
   * Round 1 review B1: the boundary at res 8 must classify as `coarse`
   * because the spec renders res 5–8 as polygons and res 9–11 as small
   * circles.  Resolutions outside the spec'd `{2, 5, 7, 9, 15}` set are
   * bucketed by proximity so unexpected backend values still render
   * sensibly.
   */
  function tierForResolution(res: number): PrecisionTier {
    if (res <= 2) return 'hidden';
    if (res <= 5) return 'very_coarse';
    if (res <= 8) return 'coarse';
    if (res <= 11) return 'open';
    return 'member';
  }

  /**
   * Tier-default marker / polygon colour.  Mirrors the Rosé Pine semantic
   * palette used elsewhere in the project (rose / foam / gold / love).
   */
  function tierColor(tier: PrecisionTier): string {
    switch (tier) {
      case 'member':
        return '#d7827e'; // Rosé Pine "rose"
      case 'open':
        return '#9ccfd8'; // Rosé Pine "foam"
      case 'coarse':
        return '#f6c177'; // Rosé Pine "gold"
      case 'very_coarse':
        return '#eb6f92'; // Rosé Pine "love"
      case 'hidden':
        return '#908caa'; // Rosé Pine subtle (muted)
    }
  }

  /** Translate a precision tier to a human-readable label for tooltips. */
  function tierLabel(tier: PrecisionTier): string {
    switch (tier) {
      case 'member':
        return m.hspec_y_maps_tier_member();
      case 'open':
        return m.hspec_y_maps_tier_open();
      case 'coarse':
        return m.hspec_y_maps_tier_coarse();
      case 'very_coarse':
        return m.hspec_y_maps_tier_very_coarse();
      case 'hidden':
        return m.hspec_y_maps_tier_hidden();
    }
  }

  /**
   * Build the screen-reader label for a marker / pin (Round 1 review A1).
   * Hidden pins always announce themselves as "Restricted location".
   */
  function ariaLabelFor(point: HSpecPoint, tier: PrecisionTier): string {
    if (tier === 'hidden') {
      return m.hspec_y_maps_hidden_pin_label();
    }
    const label = point.label ?? point.sublabel ?? null;
    if (label) {
      return m.hspec_y_maps_marker_aria_labeled({ label, tier: tierLabel(tier) });
    }
    return m.hspec_y_maps_marker_aria_unlabeled({ tier: tierLabel(tier) });
  }

  /**
   * Convert a single point's H3 cell into a GeoJSON polygon feature.  Only
   * called for tiers that render polygons (very_coarse / coarse).
   */
  function pointToPolygonFeature(point: HSpecPoint, tier: PrecisionTier): GeoJSON.Feature | null {
    if (!point.h3_index || !isValidCell(point.h3_index)) return null;
    // h3-js v4 returns [lat, lng]; GeoJSON wants [lng, lat] and a closed ring.
    const boundary = cellToBoundary(point.h3_index);
    const ring: [number, number][] = boundary.map((c): [number, number] => [c[1], c[0]]);
    const first = ring[0];
    if (first) ring.push(first);
    return {
      type: 'Feature',
      properties: {
        id: point.id,
        tier,
        color: point.color ?? tierColor(tier),
        label: point.label ?? null,
        sublabel: point.sublabel ?? null,
      },
      geometry: {
        type: 'Polygon',
        coordinates: [ring],
      },
    };
  }

  /**
   * Bucket points by precision tier.  Points whose `h3_index` is null or
   * invalid are dropped silently.
   */
  function bucketPoints(input: HSpecPoint[]): Record<PrecisionTier, HSpecPoint[]> {
    const buckets: Record<PrecisionTier, HSpecPoint[]> = {
      member: [],
      open: [],
      coarse: [],
      very_coarse: [],
      hidden: [],
    };
    for (const p of input) {
      if (!p.h3_index || !isValidCell(p.h3_index)) continue;
      const res = getResolution(p.h3_index);
      buckets[tierForResolution(res)].push(p);
    }
    return buckets;
  }

  // ---------------------------------------------------------------------
  // GeoJSON builders
  // ---------------------------------------------------------------------

  function emptyFC(): GeoJSON.FeatureCollection {
    return { type: 'FeatureCollection', features: [] };
  }

  function buildPolygonFC(bucket: HSpecPoint[], tier: PrecisionTier): GeoJSON.FeatureCollection {
    const features: GeoJSON.Feature[] = [];
    for (const p of bucket) {
      const f = pointToPolygonFeature(p, tier);
      if (f) features.push(f);
    }
    return { type: 'FeatureCollection', features };
  }

  // ---------------------------------------------------------------------
  // DOM marker construction (no innerHTML — XSS-safe)
  // ---------------------------------------------------------------------

  /**
   * Wire shared accessibility attributes and keyboard handling onto the
   * marker root (Round 1 review A1).  We expose the marker as a button so
   * keyboard users can focus it with Tab and activate via Enter/Space.
   *
   * Round 3 review B3: handlers close over a mutable `latest` ref so the
   * marker can be metadata-refreshed in place without removing/re-adding
   * listeners (which would lose hover/focus state).
   */
  function makeAccessible(
    host: HTMLButtonElement,
    latest: { point: HSpecPoint; tier: PrecisionTier },
    showTooltip: () => void,
    hideTooltip: () => void,
  ): void {
    host.type = 'button';
    host.setAttribute('aria-label', ariaLabelFor(latest.point, latest.tier));
    host.dataset.pointId = latest.point.id;
    if (latest.point.label) host.title = latest.point.label;
    // Buttons are focusable by default but in Safari rendering inside a
    // map canvas occasionally drops focusability — ensure tabindex is set.
    host.tabIndex = 0;

    host.addEventListener('click', (e) => {
      e.stopPropagation();
      onSelect(latest.point);
    });
    host.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        e.stopPropagation();
        onSelect(latest.point);
      }
    });
    host.addEventListener('mouseenter', showTooltip);
    host.addEventListener('mouseleave', hideTooltip);
    host.addEventListener('focus', showTooltip);
    host.addEventListener('blur', hideTooltip);
  }

  /**
   * Build a tooltip node whose body content (label / sublabel / tier line)
   * can be rebuilt on demand without re-creating the tooltip itself.  The
   * returned `rebuild` rewrites the children in-place so the tooltip's
   * display state and DOM identity are preserved across metadata refreshes
   * (Round 3 review B3).
   */
  function attachTooltip(
    host: HTMLElement,
    initial: { point: HSpecPoint; tier: PrecisionTier },
  ): {
    show: () => void;
    hide: () => void;
    rebuild: (point: HSpecPoint, tier: PrecisionTier) => void;
  } {
    const tooltip = document.createElement('div');
    tooltip.setAttribute('role', 'tooltip');
    tooltip.style.cssText = [
      'position: absolute',
      'background: #191724', // Rosé Pine "base" (dark)
      'color: #e0def4', // Rosé Pine "text"
      'font-size: 12px',
      'line-height: 1.35',
      'padding: 6px 10px',
      'border-radius: 6px',
      'white-space: nowrap',
      'pointer-events: none',
      'bottom: calc(100% + 6px)',
      'left: 50%',
      'transform: translateX(-50%)',
      'display: none',
      'z-index: 1000',
      'width: max-content',
      'max-width: 240px',
      'box-shadow: 0 4px 12px rgba(0,0,0,0.35)',
    ].join(';');

    function rebuild(point: HSpecPoint, tier: PrecisionTier): void {
      // Replace children atomically — textContent='' clears the node.
      tooltip.textContent = '';
      if (point.label) {
        const labelEl = document.createElement('div');
        labelEl.textContent = point.label;
        labelEl.style.fontWeight = '600';
        tooltip.appendChild(labelEl);
      }
      if (point.sublabel) {
        const subEl = document.createElement('div');
        subEl.textContent = point.sublabel;
        subEl.style.opacity = '0.85';
        tooltip.appendChild(subEl);
      }
      const tierEl = document.createElement('div');
      tierEl.textContent = tierLabel(tier);
      tierEl.style.opacity = '0.7';
      tierEl.style.fontSize = '11px';
      tierEl.style.marginTop = point.label || point.sublabel ? '2px' : '0';
      tooltip.appendChild(tierEl);
    }

    rebuild(initial.point, initial.tier);
    host.appendChild(tooltip);
    return {
      show: () => {
        tooltip.style.display = 'block';
      },
      hide: () => {
        tooltip.style.display = 'none';
      },
      rebuild,
    };
  }

  /**
   * Refresh the visual / aria / data state of an existing circle marker so
   * a metadata-only update (label, sublabel, color, etc.) takes effect
   * without recreating the DOM (Round 3 review B3).
   */
  function refreshCircleVisuals(
    host: HTMLButtonElement,
    dot: HTMLDivElement,
    point: HSpecPoint,
    tier: PrecisionTier,
  ): void {
    const fill = point.color ?? tierColor(tier);
    dot.style.background = fill;
    if (tier === 'open') {
      dot.style.outline = `4px solid ${fill}33`;
    } else {
      dot.style.outline = '';
    }
    host.setAttribute('aria-label', ariaLabelFor(point, tier));
    host.dataset.pointId = point.id;
    if (point.label) host.title = point.label;
    else host.removeAttribute('title');
  }

  function createCircleMarker(
    point: HSpecPoint,
    tier: PrecisionTier,
  ): { element: HTMLButtonElement; refresh: (next: HSpecPoint) => void; latest: { point: HSpecPoint; tier: PrecisionTier } } {
    const wrapper = document.createElement('button');
    wrapper.style.position = 'relative';
    wrapper.style.cursor = 'pointer';
    wrapper.style.display = 'inline-block';
    wrapper.style.lineHeight = '0';
    wrapper.style.overflow = 'visible';
    // Reset default <button> chrome so the marker still looks like a dot.
    wrapper.style.background = 'transparent';
    wrapper.style.border = 'none';
    wrapper.style.padding = '0';
    wrapper.style.margin = '0';
    wrapper.style.appearance = 'none';
    wrapper.className = 'hspec-y-maps__marker-button';

    const size = tier === 'member' ? 12 : 14;
    const fill = point.color ?? tierColor(tier);

    const dot = document.createElement('div');
    dot.style.width = `${size}px`;
    dot.style.height = `${size}px`;
    dot.style.borderRadius = '50%';
    dot.style.background = fill;
    dot.style.border = tier === 'member' ? '2px solid #ffffff' : '2px solid rgba(255,255,255,0.85)';
    dot.style.boxShadow = '0 1px 3px rgba(0,0,0,0.35)';
    if (tier === 'open') {
      // Soft halo to communicate "approximate area" at the open tier.
      dot.style.outline = `4px solid ${fill}33`;
      dot.style.outlineOffset = '0';
    }
    wrapper.appendChild(dot);

    const latest = { point, tier };
    const tooltipApi = attachTooltip(wrapper, latest);
    makeAccessible(wrapper, latest, tooltipApi.show, tooltipApi.hide);
    return {
      element: wrapper,
      latest,
      refresh: (next) => {
        latest.point = next;
        refreshCircleVisuals(wrapper, dot, next, tier);
        tooltipApi.rebuild(next, tier);
      },
    };
  }

  function createHiddenPin(
    point: HSpecPoint,
  ): { element: HTMLButtonElement; refresh: (next: HSpecPoint) => void; latest: { point: HSpecPoint; tier: PrecisionTier } } {
    const wrapper = document.createElement('button');
    wrapper.style.position = 'relative';
    wrapper.style.cursor = 'pointer';
    wrapper.style.display = 'inline-flex';
    wrapper.style.alignItems = 'center';
    wrapper.style.gap = '4px';
    wrapper.style.padding = '4px 8px';
    wrapper.style.background = 'rgba(144, 140, 170, 0.92)'; // Rosé Pine "subtle"
    wrapper.style.color = '#ffffff';
    wrapper.style.fontSize = '11px';
    wrapper.style.lineHeight = '1';
    wrapper.style.borderRadius = '999px';
    wrapper.style.whiteSpace = 'nowrap';
    wrapper.style.boxShadow = '0 1px 3px rgba(0,0,0,0.35)';
    wrapper.style.pointerEvents = 'auto';
    wrapper.style.border = 'none';
    wrapper.style.appearance = 'none';
    wrapper.style.fontFamily = 'inherit';
    wrapper.className = 'hspec-y-maps__marker-button hspec-y-maps__marker-button--pill';

    // Lock icon (pure DOM SVG)
    const svgNS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(svgNS, 'svg');
    svg.setAttribute('width', '10');
    svg.setAttribute('height', '10');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', '#ffffff');
    svg.setAttribute('stroke-width', '2.5');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    svg.setAttribute('aria-hidden', 'true');

    const rect = document.createElementNS(svgNS, 'rect');
    rect.setAttribute('x', '3');
    rect.setAttribute('y', '11');
    rect.setAttribute('width', '18');
    rect.setAttribute('height', '11');
    rect.setAttribute('rx', '2');

    const path = document.createElementNS(svgNS, 'path');
    path.setAttribute('d', 'M7 11V7a5 5 0 0110 0v4');

    svg.appendChild(rect);
    svg.appendChild(path);
    wrapper.appendChild(svg);

    const text = document.createElement('span');
    text.textContent = m.hspec_y_maps_hidden_pin_label();
    wrapper.appendChild(text);

    const latest = { point, tier: 'hidden' as PrecisionTier };
    const tooltipApi = attachTooltip(wrapper, latest);
    makeAccessible(wrapper, latest, tooltipApi.show, tooltipApi.hide);
    return {
      element: wrapper,
      latest,
      refresh: (next) => {
        latest.point = next;
        // Hidden pin keeps its visible label fixed ("Restricted location"),
        // but aria/title/tooltip body still reflect the latest point.
        wrapper.setAttribute('aria-label', ariaLabelFor(next, 'hidden'));
        wrapper.dataset.pointId = next.id;
        if (next.label) wrapper.title = next.label;
        else wrapper.removeAttribute('title');
        text.textContent = m.hspec_y_maps_hidden_pin_label();
        tooltipApi.rebuild(next, 'hidden');
      },
    };
  }

  /**
   * Round 3 review B4: keyboard-activatable focus dot for polygon tiers.
   * Polygon click handlers cover pointer activation, but mouse-only event
   * wiring leaves keyboard / screen-reader users stranded.  The focus dot
   * is a small <button> rendered at the polygon centroid that fires the
   * same onSelect on Enter/Space, with a visually de-emphasised look so
   * it does not compete with member/open/hidden tier markers.
   */
  function createFocusDot(
    point: HSpecPoint,
    tier: PrecisionTier,
  ): { element: HTMLButtonElement; refresh: (next: HSpecPoint) => void; latest: { point: HSpecPoint; tier: PrecisionTier } } {
    const wrapper = document.createElement('button');
    wrapper.type = 'button';
    wrapper.className = 'hspec-y-maps__focus-dot';
    wrapper.style.width = '8px';
    wrapper.style.height = '8px';
    wrapper.style.borderRadius = '50%';
    wrapper.style.background = '#908caa'; // Rosé Pine "subtle"
    wrapper.style.border = '1px solid rgba(255,255,255,0.85)';
    wrapper.style.boxShadow = '0 1px 2px rgba(0,0,0,0.25)';
    wrapper.style.padding = '0';
    wrapper.style.margin = '0';
    wrapper.style.cursor = 'pointer';
    wrapper.style.opacity = '0.55';
    wrapper.style.appearance = 'none';
    wrapper.tabIndex = 0;

    const ariaLabel = point.label
      ? m.hspec_y_maps_focus_dot_aria_labeled({ label: point.label, tier: tierLabel(tier) })
      : m.hspec_y_maps_focus_dot_aria_unlabeled({ tier: tierLabel(tier) });
    wrapper.setAttribute('aria-label', ariaLabel);
    wrapper.title = m.hspec_y_maps_focus_dot_tooltip();
    wrapper.dataset.pointId = point.id;

    const latest = { point, tier };

    wrapper.addEventListener('click', (e) => {
      e.stopPropagation();
      onSelect(latest.point);
    });
    wrapper.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        e.stopPropagation();
        onSelect(latest.point);
      }
    });

    const tooltipApi = attachTooltip(wrapper, latest);
    wrapper.addEventListener('mouseenter', tooltipApi.show);
    wrapper.addEventListener('mouseleave', tooltipApi.hide);
    wrapper.addEventListener('focus', tooltipApi.show);
    wrapper.addEventListener('blur', tooltipApi.hide);

    return {
      element: wrapper,
      latest,
      refresh: (next) => {
        latest.point = next;
        const nextAria = next.label
          ? m.hspec_y_maps_focus_dot_aria_labeled({ label: next.label, tier: tierLabel(tier) })
          : m.hspec_y_maps_focus_dot_aria_unlabeled({ tier: tierLabel(tier) });
        wrapper.setAttribute('aria-label', nextAria);
        wrapper.dataset.pointId = next.id;
        tooltipApi.rebuild(next, tier);
      },
    };
  }

  // ---------------------------------------------------------------------
  // MapLibre source/layer/marker management
  // ---------------------------------------------------------------------

  function clearMarkers(): void {
    for (const entry of markerById.values()) entry.marker.remove();
    markerById = new Map();
    for (const entry of focusDotById.values()) entry.marker.remove();
    focusDotById = new Map();
  }

  function addMarkerForPoint(
    mapInstance: import('maplibre-gl').Map,
    libgl: typeof import('maplibre-gl'),
    point: HSpecPoint,
    tier: PrecisionTier,
  ): void {
    if (!point.h3_index || !isValidCell(point.h3_index)) return;
    const [lat, lng] = cellToLatLng(point.h3_index);
    const built =
      tier === 'hidden' ? createHiddenPin(point) : createCircleMarker(point, tier);
    const anchor: import('maplibre-gl').PositionAnchor =
      tier === 'hidden' ? 'bottom' : 'center';
    const marker = new libgl.Marker({ element: built.element, anchor })
      .setLngLat([lng, lat])
      .addTo(mapInstance);
    markerById.set(point.id, {
      marker,
      tier,
      latest: built.latest,
      refresh: built.refresh,
    });
  }

  function addFocusDotForPoint(
    mapInstance: import('maplibre-gl').Map,
    libgl: typeof import('maplibre-gl'),
    point: HSpecPoint,
    tier: PrecisionTier,
  ): void {
    if (!point.h3_index || !isValidCell(point.h3_index)) return;
    // Use the H3 cell centroid so the dot sits inside the polygon area.
    const [lat, lng] = cellToLatLng(point.h3_index);
    const built = createFocusDot(point, tier);
    const marker = new libgl.Marker({ element: built.element, anchor: 'center' })
      .setLngLat([lng, lat])
      .addTo(mapInstance);
    focusDotById.set(point.id, {
      marker,
      tier,
      latest: built.latest,
      refresh: built.refresh,
    });
  }

  /**
   * Determine whether the metadata fields a marker actually renders have
   * changed.  Used to skip refresh churn when the parent re-renders with
   * the same point reference (or an equivalent value) (Round 3 review B3).
   */
  function pointMetadataDiffers(a: HSpecPoint, b: HSpecPoint): boolean {
    return (
      a.label !== b.label ||
      a.sublabel !== b.sublabel ||
      a.color !== b.color ||
      a.h3_index !== b.h3_index
    );
  }

  /**
   * Round 1 review B3: diff-update markers by id rather than wiping the
   * map every refresh.  Markers whose id disappears are removed; markers
   * whose tier changed are recreated; same-id+same-tier entries have their
   * position updated and (Round 3) their metadata refreshed in place so
   * label / sublabel / color / aria-label changes propagate without losing
   * hover / focus state or DOM identity.
   */
  function diffUpdateMarkers(
    mapInstance: import('maplibre-gl').Map,
    libgl: typeof import('maplibre-gl'),
    desired: { point: HSpecPoint; tier: PrecisionTier }[],
    registry: Map<string, MarkerEntry>,
    add: (
      mapInstance: import('maplibre-gl').Map,
      libgl: typeof import('maplibre-gl'),
      point: HSpecPoint,
      tier: PrecisionTier,
    ) => void,
  ): void {
    const desiredById = new Map<string, { point: HSpecPoint; tier: PrecisionTier }>();
    for (const item of desired) desiredById.set(item.point.id, item);

    // Remove markers that are no longer present.
    for (const [id, entry] of registry) {
      if (!desiredById.has(id)) {
        entry.marker.remove();
        registry.delete(id);
      }
    }

    // Add or recreate markers as needed.
    for (const { point, tier } of desired) {
      const existing = registry.get(point.id);
      if (existing && existing.tier === tier) {
        const previous = existing.latest.point;
        // Update position in case the H3 cell moved (re-clamping etc.).
        if (point.h3_index && isValidCell(point.h3_index)) {
          const [lat, lng] = cellToLatLng(point.h3_index);
          existing.marker.setLngLat([lng, lat]);
        }
        // Round 3 review B3: refresh metadata (label / sublabel / color /
        // aria-label / data-* / title / event handler closures) whenever
        // the rendered fields change.  The mutable `latest` ref means
        // existing event listeners pick up the new point automatically.
        if (pointMetadataDiffers(previous, point)) {
          existing.refresh(point);
        }
        continue;
      }
      if (existing) {
        existing.marker.remove();
        registry.delete(point.id);
      }
      add(mapInstance, libgl, point, tier);
    }
  }

  function refreshLayers(currentPoints: HSpecPoint[]): void {
    if (!map || !mapLoaded || !maplibre) return;
    const buckets = bucketPoints(currentPoints);

    // Polygon sources are updated by setData on existing GeoJSON sources.
    const veryCoarseSrc = map.getSource('hspec-very-coarse') as
      | import('maplibre-gl').GeoJSONSource
      | undefined;
    if (veryCoarseSrc) veryCoarseSrc.setData(buildPolygonFC(buckets.very_coarse, 'very_coarse'));

    const coarseSrc = map.getSource('hspec-coarse') as
      | import('maplibre-gl').GeoJSONSource
      | undefined;
    if (coarseSrc) coarseSrc.setData(buildPolygonFC(buckets.coarse, 'coarse'));

    // Visible markers — polygon tiers do NOT receive a primary marker
    // (the polygon hex itself communicates the precision and absorbs
    // pointer clicks via the layer-level click handler wired in onMount).
    const desired: { point: HSpecPoint; tier: PrecisionTier }[] = [
      ...buckets.member.map((p) => ({ point: p, tier: 'member' as PrecisionTier })),
      ...buckets.open.map((p) => ({ point: p, tier: 'open' as PrecisionTier })),
      ...buckets.hidden.map((p) => ({ point: p, tier: 'hidden' as PrecisionTier })),
    ];
    diffUpdateMarkers(map, maplibre, desired, markerById, addMarkerForPoint);

    // Round 3 review B4: keyboard-focusable overlay dots for polygon tiers
    // so non-mouse users can activate the same onSelect.  Kept visually
    // de-emphasised and announced with explicit "Activate area" copy so
    // they are not confused with the precision-tier markers above.
    const focusDesired: { point: HSpecPoint; tier: PrecisionTier }[] = [
      ...buckets.coarse.map((p) => ({ point: p, tier: 'coarse' as PrecisionTier })),
      ...buckets.very_coarse.map((p) => ({ point: p, tier: 'very_coarse' as PrecisionTier })),
    ];
    diffUpdateMarkers(map, maplibre, focusDesired, focusDotById, addFocusDotForPoint);
  }

  function fitToPoints(currentPoints: HSpecPoint[]): void {
    if (!map || !maplibre) return;
    const coords: [number, number][] = [];
    for (const p of currentPoints) {
      if (!p.h3_index || !isValidCell(p.h3_index)) continue;
      const [lat, lng] = cellToLatLng(p.h3_index);
      coords.push([lng, lat]);
    }
    if (coords.length === 0) return;
    if (coords.length === 1) {
      const single = coords[0];
      if (single) {
        map.setCenter(single);
        map.setZoom(11);
      }
      return;
    }
    const lngs = coords.map((c) => c[0]);
    const lats = coords.map((c) => c[1]);
    const bounds = new maplibre.LngLatBounds(
      [Math.min(...lngs), Math.min(...lats)],
      [Math.max(...lngs), Math.max(...lats)],
    );
    map.fitBounds(bounds, { padding: 60, maxZoom: 13, duration: 300 });
  }

  /**
   * Resolve the point that owns a clicked polygon feature so polygon
   * tiers (coarse / very_coarse) can fire onSelect without needing a
   * centroid marker (Round 1 review B4).
   */
  function findPointById(id: unknown): HSpecPoint | null {
    if (typeof id !== 'string') return null;
    return points.find((p) => p.id === id) ?? null;
  }

  // ---------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------

  onMount(async () => {
    if (!mapContainer) return;
    const lib = await import('maplibre-gl');
    // Round 1 review B2: a fast unmount during the dynamic import must not
    // result in instantiating a Map that has nowhere to live.
    if (disposed || !mapContainer) return;
    maplibre = lib;

    const mapInstance = new lib.Map({
      container: mapContainer,
      style: 'https://tiles.openfreemap.org/styles/liberty',
      center: initialCenter,
      zoom: initialZoom,
      scrollZoom: true,
    });
    map = mapInstance;
    mapInstance.addControl(new lib.NavigationControl(), 'top-right');

    mapInstance.on('load', () => {
      // Round 1 review B2: bail out if onDestroy ran while the map was
      // booting.  The map instance has already been removed in that case.
      if (disposed || map !== mapInstance) return;
      mapLoaded = true;

      // Polygon sources / layers — order matters for visual stacking.
      // Very-coarse (largest cells) drawn first so coarse cells overlay them.
      mapInstance.addSource('hspec-very-coarse', { type: 'geojson', data: emptyFC() });
      mapInstance.addLayer({
        id: 'hspec-very-coarse-fill',
        type: 'fill',
        source: 'hspec-very-coarse',
        paint: {
          'fill-color': ['get', 'color'],
          'fill-opacity': 0.18,
        },
      });
      mapInstance.addLayer({
        id: 'hspec-very-coarse-outline',
        type: 'line',
        source: 'hspec-very-coarse',
        paint: {
          'line-color': ['get', 'color'],
          'line-width': 1.5,
          'line-opacity': 0.7,
        },
      });

      mapInstance.addSource('hspec-coarse', { type: 'geojson', data: emptyFC() });
      mapInstance.addLayer({
        id: 'hspec-coarse-fill',
        type: 'fill',
        source: 'hspec-coarse',
        paint: {
          'fill-color': ['get', 'color'],
          'fill-opacity': 0.25,
        },
      });
      mapInstance.addLayer({
        id: 'hspec-coarse-outline',
        type: 'line',
        source: 'hspec-coarse',
        paint: {
          'line-color': ['get', 'color'],
          'line-width': 1.5,
          'line-opacity': 0.85,
        },
      });

      // Round 1 review B4: wire polygon click handlers as the pointer
      // click target for polygon tiers, and surface a pointer cursor so
      // users discover the affordance.  Keyboard activation for polygon
      // tiers is provided by the focus-dot overlays added in
      // refreshLayers (Round 3 review B4).
      const polygonLayers = ['hspec-coarse-fill', 'hspec-very-coarse-fill'];
      for (const layerId of polygonLayers) {
        mapInstance.on('click', layerId, (event) => {
          const feature = event.features?.[0];
          if (!feature) return;
          const id = feature.properties?.id;
          const point = findPointById(id);
          if (point) onSelect(point);
        });
        mapInstance.on('mouseenter', layerId, () => {
          mapInstance.getCanvas().style.cursor = 'pointer';
        });
        mapInstance.on('mouseleave', layerId, () => {
          mapInstance.getCanvas().style.cursor = '';
        });
      }

      refreshLayers(points);
      if (firstRefresh) {
        fitToPoints(points);
        firstRefresh = false;
      }
    });
  });

  onDestroy(() => {
    disposed = true;
    clearMarkers();
    if (map) {
      map.remove();
      map = null;
      mapLoaded = false;
    }
    maplibre = null;
  });

  // Reactively re-render when the caller mutates the `points` prop.
  $effect(() => {
    const current = points;
    if (!map || !mapLoaded) return;
    refreshLayers(current);
    // Round 1 review B3: only auto-fit when the caller explicitly opts in
    // or on the very first reactive update (the onMount load handler also
    // fits once).  This avoids jank on every `points` mutation.
    if (fitOnUpdate) {
      fitToPoints(current);
    }
  });
</script>

<div class="hspec-y-maps">
  <div bind:this={mapContainer} class="hspec-y-maps__canvas" style:height></div>

  <!-- Legend reflects the precision tiers actually present so users
       understand why some markers are coarse polygons. -->
  <div class="hspec-y-maps__legend" aria-hidden="true">
    <span class="hspec-y-maps__legend-item">
      <span class="hspec-y-maps__legend-swatch" style:background="#d7827e"></span>
      {m.hspec_y_maps_tier_member()}
    </span>
    <span class="hspec-y-maps__legend-item">
      <span class="hspec-y-maps__legend-swatch" style:background="#9ccfd8"></span>
      {m.hspec_y_maps_tier_open()}
    </span>
    <span class="hspec-y-maps__legend-item">
      <span
        class="hspec-y-maps__legend-swatch hspec-y-maps__legend-swatch--ring"
        style:--ring-color="#f6c177"
      ></span>
      {m.hspec_y_maps_tier_coarse()}
    </span>
    <span class="hspec-y-maps__legend-item">
      <span
        class="hspec-y-maps__legend-swatch hspec-y-maps__legend-swatch--ring"
        style:--ring-color="#eb6f92"
      ></span>
      {m.hspec_y_maps_tier_very_coarse()}
    </span>
    <span class="hspec-y-maps__legend-item">
      <span class="hspec-y-maps__legend-swatch" style:background="#908caa"></span>
      {m.hspec_y_maps_tier_hidden()}
    </span>
  </div>
</div>

<style>
  .hspec-y-maps {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    width: 100%;
  }

  .hspec-y-maps__canvas {
    width: 100%;
    border-radius: 0.5rem;
    border: 1px solid rgb(231 229 228); /* stone-200 */
    overflow: hidden;
  }

  .hspec-y-maps__legend {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
    font-size: 0.75rem;
    color: rgb(87 83 78); /* stone-600 */
  }

  .hspec-y-maps__legend-item {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
  }

  .hspec-y-maps__legend-swatch {
    display: inline-block;
    width: 0.75rem;
    height: 0.75rem;
    border-radius: 9999px;
    border: 1px solid rgba(0, 0, 0, 0.1);
  }

  .hspec-y-maps__legend-swatch--ring {
    background: transparent;
    border: 2px solid var(--ring-color, #f6c177);
    border-radius: 0.15rem;
  }

  /* Round 1 review A1: clear focus indicator for keyboard users.  The
     marker hosts are <button>s so they receive focus naturally; this
     ring matches the Rosé Pine focus treatment used elsewhere. */
  :global(.hspec-y-maps__marker-button:focus-visible) {
    outline: 2px solid #d7827e;
    outline-offset: 3px;
    border-radius: 9999px;
  }
  :global(.hspec-y-maps__marker-button--pill:focus-visible) {
    outline-offset: 2px;
    border-radius: 999px;
  }

  /* Round 3 review B4: focus-dot accessibility overlay for polygon tiers.
     Kept visually subtle (Rosé Pine "subtle") so it does not compete with
     primary tier markers, but receives a clear focus ring for keyboard
     users and slightly intensifies on hover/focus so pointer users can
     also discover it as an affordance. */
  :global(.hspec-y-maps__focus-dot) {
    transition: opacity 120ms ease, transform 120ms ease;
  }
  :global(.hspec-y-maps__focus-dot:hover),
  :global(.hspec-y-maps__focus-dot:focus-visible) {
    opacity: 1;
    transform: scale(1.25);
  }
  :global(.hspec-y-maps__focus-dot:focus-visible) {
    outline: 2px solid #d7827e;
    outline-offset: 3px;
  }
</style>
