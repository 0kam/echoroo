"use client";

import { useQuery } from "@tanstack/react-query";

import api from "@/app/api";

/**
 * Hook to fetch detection temporal data for visualization.
 * Returns detection counts grouped by species, date, and hour.
 */
export default function useDetectionTemporalData({
  runUuid,
  filterApplicationUuid,
}: {
  runUuid: string;
  filterApplicationUuid?: string;
}) {
  return useQuery({
    queryKey: [
      "detection-visualization",
      "temporal",
      runUuid,
      filterApplicationUuid,
    ],
    enabled: Boolean(runUuid),
    queryFn: async () => {
      if (!runUuid) {
        throw new Error("runUuid is required");
      }
      return await api.detectionVisualization.getTemporalData({
        runUuid,
        filterApplicationUuid,
      });
    },
    staleTime: 60_000, // Cache for 1 minute
  });
}
