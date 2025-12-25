"use client";

import { useQuery } from "@tanstack/react-query";

import api from "@/app/api";

/**
 * Hook to fetch available foundation models.
 */
export default function useFoundationModels() {
  return useQuery({
    queryKey: ["foundation-models"],
    queryFn: async () => {
      return await api.foundationModels.list();
    },
  });
}
