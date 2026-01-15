"use client";

import { useQuery } from "@tanstack/react-query";

import api from "@/app/api";

/**
 * Hook to fetch progress for a foundation model run.
 * Automatically refetches while the run is in progress.
 */
export default function useFoundationModelRunProgress(
  runUuid?: string,
  options?: {
    enabled?: boolean;
    refetchInterval?: number | false;
  },
) {
  return useQuery({
    queryKey: ["foundation-models", "runs", runUuid, "progress"],
    enabled: Boolean(runUuid) && (options?.enabled ?? true),
    refetchInterval: options?.refetchInterval ?? false,
    queryFn: async () => {
      if (!runUuid) {
        throw new Error("runUuid is required");
      }
      return await api.foundationModels.getRunProgress(runUuid);
    },
  });
}
