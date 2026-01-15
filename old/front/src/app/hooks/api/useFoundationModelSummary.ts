"use client";

import { useQuery } from "@tanstack/react-query";

import api from "@/app/api";

export default function useFoundationModelSummary(datasetUuid?: string) {
  return useQuery({
    queryKey: ["foundation-models", datasetUuid, "summary"],
    enabled: Boolean(datasetUuid),
    queryFn: async () => {
      if (!datasetUuid) {
        throw new Error("datasetUuid is required");
      }
      return await api.foundationModels.getDatasetSummary(datasetUuid);
    },
  });
}
