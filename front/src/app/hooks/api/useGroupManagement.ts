"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";

import api from "@/app/api";

import type {
  GroupDetail,
  GroupMembership,
  GroupMembershipCreate,
  GroupMembershipUpdate,
} from "@/lib/types";

export function useManagedGroups({ enabled = true } = {}) {
  return useQuery<GroupDetail[]>({
    queryKey: ["groups", "managed"],
    queryFn: () => api.groups.mine(),
    enabled,
    staleTime: 30_000,
  });
}

export function useGroupDetail(groupId?: number, { enabled = true } = {}) {
  return useQuery<GroupDetail>({
    queryKey: ["groups", "detail", groupId],
    queryFn: () => {
      if (groupId == null) {
        throw new Error("Group id required");
      }
      return api.groups.detail(groupId);
    },
    enabled: enabled && groupId != null,
    staleTime: 5_000,
  });
}

export function useGroupMembershipManagement(groupId?: number) {
  const client = useQueryClient();

  const invalidate = () => {
    if (groupId != null) {
      client.invalidateQueries({
        queryKey: ["groups", "detail", groupId],
      });
    }
    client.invalidateQueries({ queryKey: ["groups", "managed"] });
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
