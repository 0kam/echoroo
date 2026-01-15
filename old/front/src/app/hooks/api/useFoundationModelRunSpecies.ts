"use client";

import { useQuery } from "@tanstack/react-query";

import api from "@/app/api";

export default function useFoundationModelRunSpecies(runUuid?: string) {
  return useQuery({
    queryKey: ["foundation-models", "runs", runUuid, "species"],
    enabled: Boolean(runUuid),
    queryFn: async () => {
      if (!runUuid) {
        throw new Error("runUuid is required");
      }
      return await api.foundationModels.getRunSpecies(runUuid);
    },
  });
}
