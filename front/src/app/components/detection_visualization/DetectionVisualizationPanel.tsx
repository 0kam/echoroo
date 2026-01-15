"use client";

import { useMemo, useState } from "react";

import useDetectionTemporalData from "@/app/hooks/api/useDetectionTemporalData";
import useInferenceBatchTemporalData from "@/app/hooks/api/useInferenceBatchTemporalData";
import PolarHeatmap from "./PolarHeatmap";

import Loading from "@/lib/components/ui/Loading";

// ============================================================================
// Types
// ============================================================================

interface DetectionVisualizationPanelProps {
  runUuid?: string;
  filterApplicationUuid?: string;
  batchUuid?: string;
  /** Maximum number of species to display in grid view */
  maxGridItems?: number;
  /** Whether to show legend for single species view */
  showLegend?: boolean;
}

// ============================================================================
// Main Component
// ============================================================================

export default function DetectionVisualizationPanel({
  runUuid,
  filterApplicationUuid,
  batchUuid,
  maxGridItems = 12,
  showLegend = false,
}: DetectionVisualizationPanelProps) {
  const [showAll, setShowAll] = useState(false);

  // Fetch temporal data - use either runUuid or batchUuid
  const runQuery = useDetectionTemporalData({
    runUuid: runUuid ?? "",
    filterApplicationUuid,
  });

  const batchQuery = useInferenceBatchTemporalData({
    batchUuid: batchUuid ?? "",
  });

  // Select the appropriate query based on which UUID was provided
  const { data, isLoading, isError, error } = runUuid ? runQuery : batchQuery;

  // Sort species by total detections
  const sortedSpecies = useMemo(() => {
    if (!data?.species) return [];
    return [...data.species].sort((a, b) => b.total_detections - a.total_detections);
  }, [data?.species]);

  // Limit displayed species unless showAll is true
  const displayedSpecies = useMemo(() => {
    if (showAll) return sortedSpecies;
    return sortedSpecies.slice(0, maxGridItems);
  }, [sortedSpecies, showAll, maxGridItems]);

  const hasMore = sortedSpecies.length > maxGridItems;

  // ============================================================================
  // Render States
  // ============================================================================

  if (isLoading) {
    return (
      <div className="flex min-h-[400px] items-center justify-center">
        <Loading />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex min-h-[200px] flex-col items-center justify-center gap-2 text-center">
        <div className="text-red-500">
          <svg
            className="mx-auto h-10 w-10"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
            />
          </svg>
        </div>
        <p className="text-sm text-stone-600 dark:text-stone-400">
          Failed to load detection data
        </p>
        <p className="text-xs text-stone-400">
          {error instanceof Error ? error.message : "Unknown error"}
        </p>
      </div>
    );
  }

  if (!data || sortedSpecies.length === 0) {
    return (
      <div className="flex min-h-[200px] flex-col items-center justify-center gap-2 text-center">
        <div className="text-stone-400">
          <svg
            className="mx-auto h-10 w-10"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4"
            />
          </svg>
        </div>
        <p className="text-sm text-stone-600 dark:text-stone-400">
          No detections found
        </p>
        <p className="text-xs text-stone-400">
          Run a foundation model to generate detection data.
        </p>
      </div>
    );
  }

  // ============================================================================
  // Main Render
  // ============================================================================

  const totalDetections = sortedSpecies.reduce((sum, s) => sum + s.total_detections, 0);

  return (
    <div className="space-y-4">
      {/* Header with Stats */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-6">
          <div>
            <div className="text-2xl font-semibold text-stone-900 dark:text-stone-100">
              {sortedSpecies.length}
            </div>
            <div className="text-xs text-stone-500">Species</div>
          </div>
          <div>
            <div className="text-2xl font-semibold text-stone-900 dark:text-stone-100">
              {totalDetections.toLocaleString()}
            </div>
            <div className="text-xs text-stone-500">Detections</div>
          </div>
          {data.date_range && (
            <div>
              <div className="text-sm font-medium text-stone-700 dark:text-stone-300">
                {new Date(data.date_range[0]).toLocaleDateString("ja-JP")} - {new Date(data.date_range[1]).toLocaleDateString("ja-JP")}
              </div>
              <div className="text-xs text-stone-500">Date range</div>
            </div>
          )}
        </div>
      </div>

      {/* Polar Heatmap Grid */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {displayedSpecies.map((species) => (
          <div
            key={species.scientific_name}
            className="rounded-xl border border-stone-200 bg-white p-4 dark:border-stone-700 dark:bg-stone-900"
          >
            <PolarHeatmap
              data={species.detections}
              scientificName={species.scientific_name}
              commonName={species.common_name ?? undefined}
              totalDetections={species.total_detections}
              size={200}
            />
          </div>
        ))}
      </div>

      {/* Show More / Show Less Button */}
      {hasMore && (
        <div className="flex justify-center">
          <button
            type="button"
            onClick={() => setShowAll(!showAll)}
            className="rounded-lg border border-stone-200 bg-white px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50 dark:border-stone-700 dark:bg-stone-800 dark:text-stone-300 dark:hover:bg-stone-700"
          >
            {showAll
              ? "Show less"
              : `Show all ${sortedSpecies.length} species`}
          </button>
        </div>
      )}
    </div>
  );
}
