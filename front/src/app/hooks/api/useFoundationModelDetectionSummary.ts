"use client";

import { useQuery } from "@tanstack/react-query";

import api from "@/app/api";

/**
 * Hook to fetch detection summary for a foundation model run.
 */
export default function useFoundationModelDetectionSummary(runUuid?: string) {
  return useQuery({
    queryKey: ["foundation-models", "runs", runUuid, "detections", "summary"],
    enabled: Boolean(runUuid),
    queryFn: async () => {
      if (!runUuid) {
        throw new Error("runUuid is required");
      }
      return await api.foundationModels.getDetectionSummary(runUuid);
    },
  });
}
