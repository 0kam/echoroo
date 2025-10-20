import { useQuery } from "@tanstack/react-query";

import api from "@/app/api";

import type { SpeciesCandidate } from "@/lib/types";

export default function useSpeciesSearch({
  query,
  limit = 10,
  enabled = true,
  requestId = 0,
}: {
  query: string;
  limit?: number;
  enabled?: boolean;
  requestId?: number;
}) {
  const trimmed = query.trim();
  const shouldFetch = enabled && trimmed.length >= 2;

  return useQuery<SpeciesCandidate[]>({
    queryKey: ["species-search", trimmed, limit, requestId],
    queryFn: async () => {
      if (trimmed.length < 2) return [];
      return await api.species.search({ q: trimmed, limit });
    },
    enabled: shouldFetch,
    initialData: [],
    staleTime: 0,
  });
}
