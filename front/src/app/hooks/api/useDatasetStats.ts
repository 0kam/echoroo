import { useQuery } from "@tanstack/react-query";

import api from "@/app/api";

import type { DatasetOverviewStats } from "@/lib/types";

export default function useDatasetStats({
  uuid,
  enabled = true,
}: {
  uuid: string;
  enabled?: boolean;
}) {
  return useQuery<DatasetOverviewStats>({
    queryKey: ["dataset", uuid, "stats"],
    queryFn: async () => await api.datasets.getStats(uuid),
    enabled,
    staleTime: 60 * 1000,
  });
}
