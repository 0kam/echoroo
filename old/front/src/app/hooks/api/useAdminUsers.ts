import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";

import api from "@/app/api";

import type { AdminUserUpdate, SimpleUser, UserCreate } from "@/lib/types";

export default function useAdminUsers({
  enabled = true,
  limit = 100,
}: {
  enabled?: boolean;
  limit?: number;
} = {}) {
  const client = useQueryClient();

  const query = useQuery<SimpleUser[]>({
    queryKey: ["admin", "users", { limit }],
    queryFn: () => api.adminUsers.list({ limit }),
    enabled,
    staleTime: 10_000,
  });

  const invalidate = () =>
    client.invalidateQueries({ queryKey: ["admin", "users"] });

  const create = useMutation({
    mutationFn: (data: UserCreate) => api.adminUsers.create(data),
    onSuccess: (user) => {
      toast.success(`User ${user.username} created`);
      invalidate();
    },
  });

  const update = useMutation({
    mutationFn: ({ id, data }: { id: string; data: AdminUserUpdate }) =>
      api.adminUsers.update(id, data),
    onSuccess: (user) => {
      toast.success(`Updated ${user.username}`);
      invalidate();
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.adminUsers.delete(id),
    onSuccess: () => {
      toast.success("User removed");
      invalidate();
    },
  });

  return {
    data: query.data,
    isLoading: query.isLoading,
    isError: query.isError,
    refetch: query.refetch,
    create,
    update,
    remove,
  } as const;
}
