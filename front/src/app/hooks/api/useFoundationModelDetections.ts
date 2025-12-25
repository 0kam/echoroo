"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import api from "@/app/api";
import type { DetectionFilter } from "@/lib/api/foundation_models";

export type DetectionsQuery = {
  limit?: number;
  offset?: number;
} & DetectionFilter;

/**
 * Hook to fetch detection results for a foundation model run.
 */
export default function useFoundationModelDetections(
  runUuid?: string,
  query: DetectionsQuery = {},
) {
  const {
    limit,
    offset,
    species_tag_id,
    min_confidence,
    max_confidence,
    review_status,
  } = query;

  return useQuery({
    queryKey: [
      "foundation-models",
      "runs",
      runUuid,
      "detections",
      limit,
      offset,
      species_tag_id,
      min_confidence,
      max_confidence,
      review_status,
    ],
    enabled: Boolean(runUuid),
    queryFn: async () => {
      if (!runUuid) {
        throw new Error("runUuid is required");
      }
      return await api.foundationModels.getDetections(runUuid, {
        limit,
        offset,
        species_tag_id,
        min_confidence,
        max_confidence,
        review_status,
      });
    },
    placeholderData: keepPreviousData,
  });
}
