"use client";

import { useMemo, useState, useCallback, useRef, useEffect } from "react";

// ============================================================================
// Types
// ============================================================================

interface DataPoint {
  date: string; // ISO date string
  hour: number; // 0-23
  count: number;
}

interface PolarHeatmapProps {
  data: DataPoint[];
  scientificName: string;
  commonName?: string;
  totalDetections: number;
  size?: number;
}

interface TooltipState {
  visible: boolean;
  x: number;
  y: number;
  date: string;
  hour: number;
  count: number;
}

// ============================================================================
// Color Scale
// ============================================================================

/**
 * Generate emerald color scale from white to deep emerald.
 * Returns RGB string for given intensity (0-1).
 */
function getEmeraldColor(intensity: number): string {
  if (intensity === 0) {
    return "rgb(250, 250, 250)"; // Near white for zero counts
  }
  // Emerald gradient: from light emerald to dark emerald
  // emerald-100: rgb(209, 250, 229) -> emerald-600: rgb(5, 150, 105)
  const clampedIntensity = Math.min(1, Math.max(0, intensity));

  // Use a power curve for better visual distinction
  const t = Math.pow(clampedIntensity, 0.5);

  const r = Math.round(209 - t * 204);
  const g = Math.round(250 - t * 100);
  const b = Math.round(229 - t * 124);

  return `rgb(${r}, ${g}, ${b})`;
}

/**
 * Generate legend gradient stops.
 */
function getLegendGradient(): string {
  const stops: string[] = [];
  for (let i = 0; i <= 10; i++) {
    const intensity = i / 10;
    stops.push(`${getEmeraldColor(intensity)} ${i * 10}%`);
  }
  return `linear-gradient(to right, ${stops.join(", ")})`;
}

// ============================================================================
// Geometry Helpers
// ============================================================================

/**
 * Convert hour (0-23) to angle in radians.
 * 0:00 is at top (12 o'clock position), going clockwise.
 */
function hourToAngle(hour: number): number {
  return (hour / 24) * 2 * Math.PI - Math.PI / 2;
}

/**
 * Convert polar coordinates to cartesian.
 */
function polarToCartesian(
  cx: number,
  cy: number,
  radius: number,
  angleRad: number,
): { x: number; y: number } {
  return {
    x: cx + radius * Math.cos(angleRad),
    y: cy + radius * Math.sin(angleRad),
  };
}

/**
 * Create SVG arc path for a wedge segment.
 */
function createWedgePath(
  cx: number,
  cy: number,
  innerRadius: number,
  outerRadius: number,
  startAngle: number,
  endAngle: number,
): string {
  const start1 = polarToCartesian(cx, cy, innerRadius, startAngle);
  const end1 = polarToCartesian(cx, cy, innerRadius, endAngle);
  const start2 = polarToCartesian(cx, cy, outerRadius, startAngle);
  const end2 = polarToCartesian(cx, cy, outerRadius, endAngle);

  const largeArcFlag = endAngle - startAngle > Math.PI ? 1 : 0;

  return [
    `M ${start1.x} ${start1.y}`,
    `A ${innerRadius} ${innerRadius} 0 ${largeArcFlag} 1 ${end1.x} ${end1.y}`,
    `L ${end2.x} ${end2.y}`,
    `A ${outerRadius} ${outerRadius} 0 ${largeArcFlag} 0 ${start2.x} ${start2.y}`,
    "Z",
  ].join(" ");
}

// ============================================================================
// Main Component
// ============================================================================

export default function PolarHeatmap({
  data,
  scientificName,
  commonName,
  totalDetections,
  size = 300,
}: PolarHeatmapProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [tooltip, setTooltip] = useState<TooltipState>({
    visible: false,
    x: 0,
    y: 0,
    date: "",
    hour: 0,
    count: 0,
  });

  // ============================================================================
  // Data Processing
  // ============================================================================

  const processedData = useMemo(() => {
    if (!data || data.length === 0) {
      return {
        dates: [] as string[],
        maxCount: 0,
        grid: new Map<string, number>(),
      };
    }

    // Get unique dates sorted chronologically
    const dateSet = new Set(data.map((d) => d.date));
    const dates = Array.from(dateSet).sort(
      (a, b) => new Date(a).getTime() - new Date(b).getTime(),
    );

    // Find max count for normalization
    const maxCount = Math.max(...data.map((d) => d.count), 1);

    // Create lookup grid: "date-hour" -> count
    const grid = new Map<string, number>();
    data.forEach((d) => {
      const key = `${d.date}-${d.hour}`;
      grid.set(key, d.count);
    });

    return { dates, maxCount, grid };
  }, [data]);

  const { dates, maxCount, grid } = processedData;

  // ============================================================================
  // Layout Calculations
  // ============================================================================

  const cx = size / 2;
  const cy = size / 2;
  const outerRadius = size / 2 - 30; // Leave room for labels
  const innerRadius = 20; // Small hole in center
  const ringCount = dates.length;
  const ringWidth = ringCount > 0 ? (outerRadius - innerRadius) / ringCount : 0;

  // Hour segments (24 hours)
  const hourAngle = (2 * Math.PI) / 24;

  // ============================================================================
  // Tooltip Handling
  // ============================================================================

  const handleMouseEnter = useCallback(
    (e: React.MouseEvent, date: string, hour: number, count: number) => {
      const svgRect = svgRef.current?.getBoundingClientRect();
      if (!svgRect) return;

      setTooltip({
        visible: true,
        x: e.clientX - svgRect.left,
        y: e.clientY - svgRect.top,
        date,
        hour,
        count,
      });
    },
    [],
  );

  const handleMouseLeave = useCallback(() => {
    setTooltip((prev) => ({ ...prev, visible: false }));
  }, []);

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (!tooltip.visible) return;
      const svgRect = svgRef.current?.getBoundingClientRect();
      if (!svgRect) return;

      setTooltip((prev) => ({
        ...prev,
        x: e.clientX - svgRect.left,
        y: e.clientY - svgRect.top,
      }));
    },
    [tooltip.visible],
  );

  // ============================================================================
  // Format Helpers
  // ============================================================================

  const formatHour = (hour: number): string => {
    return `${hour.toString().padStart(2, "0")}:00`;
  };

  const formatDate = (dateStr: string): string => {
    try {
      const date = new Date(dateStr);
      return date.toLocaleDateString("ja-JP", {
        month: "short",
        day: "numeric",
      });
    } catch {
      return dateStr;
    }
  };

  // ============================================================================
  // Render
  // ============================================================================

  if (dates.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center p-8 text-center">
        <div className="text-stone-400">
          <svg
            className="mx-auto h-12 w-12"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
            />
          </svg>
        </div>
        <p className="mt-2 text-sm text-stone-500">No detection data available</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center gap-4">
      {/* Header */}
      <div className="text-center">
        <h3 className="text-sm font-semibold text-stone-900 dark:text-stone-100">
          {scientificName}
        </h3>
        {commonName && (
          <p className="text-xs text-stone-500 dark:text-stone-400">
            {commonName}
          </p>
        )}
        <p className="mt-1 text-xs text-stone-400">
          {totalDetections.toLocaleString()} detections total
        </p>
      </div>

      {/* SVG Chart */}
      <div className="relative">
        <svg
          ref={svgRef}
          width={size}
          height={size}
          className="overflow-visible"
          onMouseMove={handleMouseMove}
        >
          {/* Background circle */}
          <circle
            cx={cx}
            cy={cy}
            r={outerRadius}
            fill="none"
            stroke="rgb(229, 231, 235)"
            strokeWidth={1}
            className="dark:stroke-stone-700"
          />

          {/* Grid lines for hours */}
          {[0, 6, 12, 18].map((hour) => {
            const angle = hourToAngle(hour);
            const inner = polarToCartesian(cx, cy, innerRadius, angle);
            const outer = polarToCartesian(cx, cy, outerRadius, angle);
            return (
              <line
                key={`grid-${hour}`}
                x1={inner.x}
                y1={inner.y}
                x2={outer.x}
                y2={outer.y}
                stroke="rgb(209, 213, 219)"
                strokeWidth={0.5}
                className="dark:stroke-stone-600"
              />
            );
          })}

          {/* Data wedges */}
          {dates.map((date, dateIndex) => {
            const ringInner = innerRadius + dateIndex * ringWidth;
            const ringOuter = innerRadius + (dateIndex + 1) * ringWidth;

            return Array.from({ length: 24 }, (_, hour) => {
              const key = `${date}-${hour}`;
              const count = grid.get(key) ?? 0;
              const intensity = count / maxCount;

              const startAngle = hourToAngle(hour);
              const endAngle = hourToAngle(hour + 1);

              const path = createWedgePath(
                cx,
                cy,
                ringInner,
                ringOuter,
                startAngle,
                endAngle,
              );

              return (
                <path
                  key={`${date}-${hour}`}
                  d={path}
                  fill={getEmeraldColor(intensity)}
                  stroke="white"
                  strokeWidth={0.5}
                  className="cursor-pointer transition-opacity hover:opacity-80 dark:stroke-stone-800"
                  onMouseEnter={(e) => handleMouseEnter(e, date, hour, count)}
                  onMouseLeave={handleMouseLeave}
                />
              );
            });
          })}

          {/* Center circle (cover) */}
          <circle
            cx={cx}
            cy={cy}
            r={innerRadius}
            fill="white"
            className="dark:fill-stone-900"
          />

          {/* Hour labels */}
          {[0, 6, 12, 18].map((hour) => {
            const angle = hourToAngle(hour);
            const labelRadius = outerRadius + 16;
            const pos = polarToCartesian(cx, cy, labelRadius, angle);

            return (
              <text
                key={`label-${hour}`}
                x={pos.x}
                y={pos.y}
                textAnchor="middle"
                dominantBaseline="middle"
                className="fill-stone-500 text-[10px] font-medium dark:fill-stone-400"
              >
                {formatHour(hour)}
              </text>
            );
          })}
        </svg>

        {/* Tooltip */}
        {tooltip.visible && (
          <div
            className="pointer-events-none absolute z-50 rounded-lg bg-stone-900 px-3 py-2 text-xs text-white shadow-lg dark:bg-stone-700"
            style={{
              left: tooltip.x + 10,
              top: tooltip.y - 40,
              transform: "translateX(-50%)",
            }}
          >
            <div className="font-medium">{formatDate(tooltip.date)}</div>
            <div className="text-stone-300">
              {formatHour(tooltip.hour)} - {formatHour((tooltip.hour + 1) % 24)}
            </div>
            <div className="mt-1 font-semibold text-emerald-400">
              {tooltip.count} detection{tooltip.count !== 1 ? "s" : ""}
            </div>
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="flex flex-col items-center gap-1">
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-stone-500">0</span>
          <div
            className="h-3 w-24 rounded-sm"
            style={{ background: getLegendGradient() }}
          />
          <span className="text-[10px] text-stone-500">{maxCount}</span>
        </div>
        <span className="text-[10px] text-stone-400">Detections per hour</span>
      </div>

      {/* Date range indicator */}
      {dates.length > 1 && (
        <div className="text-center text-[10px] text-stone-400">
          <span className="font-medium">Center:</span> {formatDate(dates[0])}{" "}
          <span className="mx-1 text-stone-300">|</span>
          <span className="font-medium">Edge:</span>{" "}
          {formatDate(dates[dates.length - 1])}
        </div>
      )}
    </div>
  );
}
