"use client";

import { useQuery } from "@tanstack/react-query";

import api from "@/app/api";

/**
 * Hook to fetch a single foundation model run by UUID.
 */
export default function useFoundationModelRun(runUuid?: string) {
  return useQuery({
    queryKey: ["foundation-models", "runs", runUuid],
    enabled: Boolean(runUuid),
    queryFn: async () => {
      if (!runUuid) {
        throw new Error("runUuid is required");
      }
      return await api.foundationModels.getRun(runUuid);
    },
  });
}
