<script lang="ts">
  import { onMount } from 'svelte';
  import type { SoundEventAnnotation, Geometry, TagSummary } from '$lib/types/annotation';

  let {
    width,
    height,
    duration,
    minFreq = 0,
    maxFreq = 22050,
    annotations = [] as SoundEventAnnotation[],
    selectedAnnotationId = null,
    mode = 'select' as 'select' | 'bbox' | 'timeinterval',
    // projectTags is reserved for future tag-based color filtering
    projectTags = [] as TagSummary[],
    oncreate,
    onselect,
    ondelete,
  }: {
    width: number;
    height: number;
    duration: number;
    minFreq?: number;
    maxFreq?: number;
    annotations?: SoundEventAnnotation[];
    selectedAnnotationId?: string | null;
    mode?: 'select' | 'bbox' | 'timeinterval';
    projectTags?: TagSummary[];
    oncreate?: (detail: { geometry: Geometry }) => void;
    onselect?: (detail: { id: string }) => void;
    ondelete?: (detail: { id: string }) => void;
  } = $props();

  // projectTags is reserved for future tag-based color filtering.
  void projectTags;

  // Drawing state
  let isDrawing = $state(false);
  let drawStartX = $state(0);
  let drawStartY = $state(0);
  let drawCurrentX = $state(0);
  let drawCurrentY = $state(0);
  let svgElement: SVGSVGElement | undefined = $state(undefined);

  // ============================================================
  // Coordinate conversion helpers
  // ============================================================

  function timeToX(time: number): number {
    return (time / duration) * width;
  }

  function freqToY(freq: number): number {
    // Inverted: high frequency at top (y=0)
    return height - ((freq - minFreq) / (maxFreq - minFreq)) * height;
  }

  function xToTime(x: number): number {
    return (x / width) * duration;
  }

  function yToFreq(y: number): number {
    return minFreq + ((height - y) / height) * (maxFreq - minFreq);
  }

  function getSvgCoords(event: MouseEvent): { x: number; y: number } {
    if (!svgElement) return { x: 0, y: 0 };
    const rect = svgElement.getBoundingClientRect();
    const scaleX = width / rect.width;
    const scaleY = height / rect.height;
    return {
      x: Math.max(0, Math.min(width, (event.clientX - rect.left) * scaleX)),
      y: Math.max(0, Math.min(height, (event.clientY - rect.top) * scaleY)),
    };
  }

  // ============================================================
  // Geometry -> SVG rect conversion
  // ============================================================

  interface SvgRect {
    x: number;
    y: number;
    width: number;
    height: number;
  }

  function geometryToRect(geometry: Geometry): SvgRect {
    if (geometry.type === 'BoundingBox') {
      // coordinates = [time_start, freq_low, time_end, freq_high]
      const timeStart = geometry.coordinates[0] ?? 0;
      const freqLow   = geometry.coordinates[1] ?? 0;
      const timeEnd   = geometry.coordinates[2] ?? 0;
      const freqHigh  = geometry.coordinates[3] ?? 0;
      const x1 = timeToX(timeStart);
      const x2 = timeToX(timeEnd);
      const y1 = freqToY(freqHigh); // high freq -> smaller y
      const y2 = freqToY(freqLow);  // low freq  -> larger y
      return {
        x: Math.min(x1, x2),
        y: Math.min(y1, y2),
        width: Math.abs(x2 - x1),
        height: Math.abs(y2 - y1),
      };
    } else {
      // TimeInterval: coordinates = [time_start, time_end]
      const timeStart = geometry.coordinates[0] ?? 0;
      const timeEnd   = geometry.coordinates[1] ?? 0;
      const x1 = timeToX(timeStart);
      const x2 = timeToX(timeEnd);
      return {
        x: Math.min(x1, x2),
        y: 0,
        width: Math.abs(x2 - x1),
        height: height,
      };
    }
  }

  // ============================================================
  // Color by tag category
  // ============================================================

  function getAnnotationColor(annotation: SoundEventAnnotation): string {
    const firstTag = annotation.tags[0];
    if (!firstTag) return '#6b7280'; // gray default
    switch (firstTag.category) {
      case 'species':    return '#22c55e'; // green
      case 'sound_type': return '#3b82f6'; // blue
      case 'quality':    return '#eab308'; // yellow
      default:           return '#6b7280';
    }
  }

  // ============================================================
  // Preview rect during drawing
  // ============================================================

  const previewRect = $derived((isDrawing && mode !== 'select')
    ? computePreviewRect()
    : null);

  function computePreviewRect(): SvgRect {
    if (mode === 'timeinterval') {
      return {
        x: Math.min(drawStartX, drawCurrentX),
        y: 0,
        width: Math.abs(drawCurrentX - drawStartX),
        height: height,
      };
    }
    return {
      x: Math.min(drawStartX, drawCurrentX),
      y: Math.min(drawStartY, drawCurrentY),
      width: Math.abs(drawCurrentX - drawStartX),
      height: Math.abs(drawCurrentY - drawStartY),
    };
  }

  // ============================================================
  // Mouse event handlers
  // ============================================================

  function handleMouseDown(event: MouseEvent) {
    if (mode === 'select') return;
    event.preventDefault();
    const { x, y } = getSvgCoords(event);
    isDrawing = true;
    drawStartX = x;
    drawStartY = y;
    drawCurrentX = x;
    drawCurrentY = y;
  }

  function handleMouseMove(event: MouseEvent) {
    if (!isDrawing || mode === 'select') return;
    event.preventDefault();
    const { x, y } = getSvgCoords(event);
    drawCurrentX = x;
    drawCurrentY = y;
  }

  function handleMouseUp(event: MouseEvent) {
    if (!isDrawing || mode === 'select') return;
    event.preventDefault();
    isDrawing = false;

    const { x, y } = getSvgCoords(event);
    drawCurrentX = x;
    drawCurrentY = y;

    // Ignore tiny accidental clicks
    if (Math.abs(drawCurrentX - drawStartX) < 3 && Math.abs(drawCurrentY - drawStartY) < 3) {
      return;
    }

    let geometry: Geometry;

    if (mode === 'bbox') {
      const timeStart = xToTime(Math.min(drawStartX, drawCurrentX));
      const timeEnd   = xToTime(Math.max(drawStartX, drawCurrentX));
      const freqLow   = yToFreq(Math.max(drawStartY, drawCurrentY));
      const freqHigh  = yToFreq(Math.min(drawStartY, drawCurrentY));
      geometry = {
        type: 'BoundingBox',
        coordinates: [timeStart, freqLow, timeEnd, freqHigh],
      };
    } else {
      // timeinterval
      const timeStart = xToTime(Math.min(drawStartX, drawCurrentX));
      const timeEnd   = xToTime(Math.max(drawStartX, drawCurrentX));
      geometry = {
        type: 'TimeInterval',
        coordinates: [timeStart, timeEnd],
      };
    }

    oncreate?.({ geometry });
  }

  function handleMouseLeave(event: MouseEvent) {
    if (isDrawing) {
      handleMouseUp(event);
    }
  }

  function handleAnnotationClick(event: MouseEvent, annotation: SoundEventAnnotation) {
    if (mode !== 'select') return;
    event.stopPropagation();
    onselect?.({ id: annotation.id });
  }

  function handleAnnotationRightClick(event: MouseEvent, annotation: SoundEventAnnotation) {
    event.preventDefault();
    event.stopPropagation();
    ondelete?.({ id: annotation.id });
  }

  function handleKeyDown(event: KeyboardEvent) {
    if (event.key === 'Delete' || event.key === 'Backspace') {
      if (selectedAnnotationId) {
        ondelete?.({ id: selectedAnnotationId });
      }
    }
  }

  onMount(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  });

  // Label visibility: only show if rect is wide enough
  function shouldShowLabel(rect: SvgRect): boolean {
    return rect.width > 40 && rect.height > 16;
  }

  function formatTagLabel(annotation: SoundEventAnnotation): string {
    return annotation.tags.map(t => t.name).join(', ');
  }

  const cursor = $derived(mode === 'select' ? 'default' : 'crosshair');
</script>

<!-- svelte-ignore a11y-no-noninteractive-tabindex -->
<!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
<svg
  bind:this={svgElement}
  {width}
  {height}
  viewBox="0 0 {width} {height}"
  style="cursor: {cursor}; user-select: none; display: block;"
  tabindex="0"
  onmousedown={handleMouseDown}
  onmousemove={handleMouseMove}
  onmouseup={handleMouseUp}
  onmouseleave={handleMouseLeave}
  role="application"
  aria-label="Annotation canvas"
>
  <!-- Existing annotations -->
  {#each annotations as annotation (annotation.id)}
    {@const rect = geometryToRect(annotation.geometry)}
    {@const color = getAnnotationColor(annotation)}
    {@const isSelected = annotation.id === selectedAnnotationId}

    <g
      class="annotation-group"
      onclick={(e) => handleAnnotationClick(e, annotation)}
      oncontextmenu={(e) => handleAnnotationRightClick(e, annotation)}
      role="button"
      tabindex="0"
      aria-label="Annotation {annotation.id}"
      onkeydown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          onselect?.({ id: annotation.id });
        }
      }}
    >
      <!-- Annotation rectangle -->
      <rect
        x={rect.x}
        y={rect.y}
        width={rect.width}
        height={rect.height}
        fill={color}
        fill-opacity="0.15"
        stroke={color}
        stroke-width={isSelected ? 2.5 : 1.5}
        stroke-dasharray={isSelected ? 'none' : 'none'}
        rx="2"
        style="cursor: {mode === 'select' ? 'pointer' : 'crosshair'};"
      />

      <!-- Selection glow effect -->
      {#if isSelected}
        <rect
          x={rect.x - 1}
          y={rect.y - 1}
          width={rect.width + 2}
          height={rect.height + 2}
          fill="none"
          stroke={color}
          stroke-width="1"
          stroke-opacity="0.4"
          rx="3"
        />
      {/if}

      <!-- Source badge -->
      {#if annotation.source === 'model'}
        <circle
          cx={rect.x + rect.width - 5}
          cy={rect.y + 5}
          r="4"
          fill="#8b5cf6"
          stroke="white"
          stroke-width="0.5"
        />
      {/if}

      <!-- Tag labels -->
      {#if shouldShowLabel(rect) && annotation.tags.length > 0}
        <rect
          x={rect.x + 2}
          y={rect.y + 2}
          width={Math.min(rect.width - 4, formatTagLabel(annotation).length * 6.5 + 6)}
          height="14"
          fill={color}
          fill-opacity="0.85"
          rx="2"
        />
        <text
          x={rect.x + 5}
          y={rect.y + 12}
          font-size="9"
          font-family="system-ui, sans-serif"
          fill="white"
          font-weight="600"
          clip-path="none"
          style="pointer-events: none;"
        >
          {formatTagLabel(annotation).substring(0, Math.floor((rect.width - 10) / 6.5))}
        </text>
      {/if}
    </g>
  {/each}

  <!-- Drawing preview rectangle -->
  {#if previewRect}
    <rect
      x={previewRect.x}
      y={previewRect.y}
      width={previewRect.width}
      height={previewRect.height}
      fill="rgba(59, 130, 246, 0.15)"
      stroke="#3b82f6"
      stroke-width="1.5"
      stroke-dasharray="5,3"
      rx="2"
      style="pointer-events: none;"
    />
  {/if}
</svg>
