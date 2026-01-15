"use client";

import { useQuery } from "@tanstack/react-query";

import api from "@/app/api";

/**
 * Hook to fetch inference batch temporal data for visualization.
 * Returns detection counts grouped by date and hour for a specific inference batch.
 */
export default function useInferenceBatchTemporalData({
  batchUuid,
}: {
  batchUuid?: string;
}) {
  return useQuery({
    queryKey: [
      "detection-visualization",
      "temporal-inference",
      batchUuid,
    ],
    enabled: Boolean(batchUuid),
    queryFn: async () => {
      if (!batchUuid) {
        throw new Error("batchUuid is required");
      }
      return await api.detectionVisualization.getInferenceBatchTemporal({
        batchUuid,
      });
    },
    staleTime: 60_000, // Cache for 1 minute
  });
}
