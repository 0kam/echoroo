import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";

import api from "@/app/api";

import type {
  Group,
  GroupCreate,
  GroupDetail,
  GroupMembership,
  GroupMembershipCreate,
  GroupMembershipUpdate,
  GroupUpdate,
  Page,
} from "@/lib/types";

export function useAdminGroups({
  enabled = true,
  limit = 100,
}: {
  enabled?: boolean;
  limit?: number;
} = {}) {
  const client = useQueryClient();

  const query = useQuery<Page<Group>>({
    queryKey: ["admin", "groups", { limit }],
    queryFn: () => api.groups.list({ limit }),
    enabled,
    staleTime: 10_000,
  });

  const invalidate = () =>
    client.invalidateQueries({ queryKey: ["admin", "groups"] });

  const create = useMutation({
    mutationFn: (payload: GroupCreate) => api.groups.create(payload),
    onSuccess: (group) => {
      toast.success(`Group ${group.name} created`);
      invalidate();
    },
  });

  const update = useMutation({
    mutationFn: ({ id, data }: { id: number; data: GroupUpdate }) =>
      api.groups.update(id, data),
    onSuccess: (group) => {
      toast.success(`Updated ${group.name}`);
      invalidate();
    },
  });

  const remove = useMutation({
    mutationFn: (id: number) => api.groups.delete(id),
    onSuccess: () => {
      toast.success("Group removed");
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

export function useAdminGroupDetail(groupId?: number) {
  return useQuery<GroupDetail>({
    queryKey: ["admin", "groups", "detail", groupId],
    queryFn: () => {
      if (groupId == null) {
        throw new Error("Group id required");
      }
      return api.groups.detail(groupId);
    },
    enabled: groupId != null,
    staleTime: 5_000,
  });
}

export function useAdminGroupMembership(groupId?: number) {
  const client = useQueryClient();

  const invalidate = () => {
    if (groupId != null) {
      client.invalidateQueries({
        queryKey: ["admin", "groups", "detail", groupId],
      });
    }
  };

  const addMember = useMutation({
    mutationFn: (payload: GroupMembershipCreate) => {
      if (groupId == null) throw new Error("Group not selected");
      return api.groups.addMember(groupId, payload);
    },
    onSuccess: (membership: GroupMembership) => {
      toast.success("Member added");
      invalidate();
      return membership;
    },
  });

  const updateMember = useMutation({
    mutationFn: ({ userId, data }: { userId: string; data: GroupMembershipUpdate }) => {
      if (groupId == null) throw new Error("Group not selected");
      return api.groups.updateMember(groupId, userId, data);
    },
    onSuccess: () => {
      toast.success("Membership updated");
      invalidate();
    },
  });

  const removeMember = useMutation({
    mutationFn: (userId: string) => {
      if (groupId == null) throw new Error("Group not selected");
      return api.groups.removeMember(groupId, userId);
    },
    onSuccess: () => {
      toast.success("Member removed");
      invalidate();
    },
  });

  return {
    addMember,
    updateMember,
    removeMember,
  } as const;
}
