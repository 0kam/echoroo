"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import api from "@/app/api";
import type { FoundationModelRunStatus } from "@/lib/types";

export default function useFoundationModelRuns({
  datasetUuid,
  foundationModelSlug,
  status,
  limit = 10,
  offset = 0,
  enabled = true,
}: {
  datasetUuid?: string;
  foundationModelSlug?: string;
  status?: FoundationModelRunStatus;
  limit?: number;
  offset?: number;
  enabled?: boolean;
}) {
  return useQuery({
    queryKey: [
      "foundation-models",
      "runs",
      datasetUuid,
      foundationModelSlug,
      status,
      limit,
      offset,
    ],
    enabled,
    queryFn: async () => {
      return await api.foundationModels.listRuns({
        dataset_uuid: datasetUuid,
        foundation_model_slug: foundationModelSlug,
        status,
        limit,
        offset,
      });
    },
    placeholderData: keepPreviousData,
  });
}
