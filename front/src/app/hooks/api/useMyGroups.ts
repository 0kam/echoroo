import { useQuery } from "@tanstack/react-query";

import api from "@/app/api";

import type { GroupDetail } from "@/lib/types";

export default function useMyGroups({ enabled = true } = {}) {
  return useQuery<GroupDetail[]>({
    queryKey: ["groups", "me"],
    queryFn: () => api.groups.mine(),
    enabled,
    staleTime: 30_000,
  });
}
