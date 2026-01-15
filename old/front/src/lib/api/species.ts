import { AxiosInstance } from "axios";

import { SpeciesCandidateSchema } from "@/lib/schemas/species";

import type { SpeciesCandidate } from "@/lib/types";

const DEFAULT_ENDPOINTS = {
  search: "/api/v1/species/search/",
};

export function registerSpeciesAPI(
  instance: AxiosInstance,
  endpoints: typeof DEFAULT_ENDPOINTS = DEFAULT_ENDPOINTS,
) {
  async function searchSpecies({
    q,
    limit = 10,
  }: {
    q: string;
    limit?: number;
  }): Promise<SpeciesCandidate[]> {
    const { data } = await instance.get(endpoints.search, {
      params: { q, limit },
    });
    return SpeciesCandidateSchema.array().parse(data);
  }

  return {
    search: searchSpecies,
  } as const;
}
