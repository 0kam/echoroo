"use client";

import { useCallback, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import api from "@/app/api";
import { Group, Input, Select } from "@/lib/components/inputs";
import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import { DialogOverlay as Dialog } from "@/lib/components/ui/Dialog";
import Spinner from "@/lib/components/ui/Spinner";
import type { Project, ProjectMember, ProjectMemberRole } from "@/lib/types";

const ROLE_OPTIONS = [
  {
    id: "member",
    label: "Member – can browse restricted resources",
    value: "member" as ProjectMemberRole,
  },
  {
    id: "manager",
    label: "Manager – can edit metadata and manage membership",
    value: "manager" as ProjectMemberRole,
  },
];

type ProjectMemberManagerProps = {
  project: Project;
  onMembershipChange?: () => void;
};

export default function ProjectMemberManager({
  project,
  onMembershipChange,
}: ProjectMemberManagerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [addMemberUserId, setAddMemberUserId] = useState("");
  const [addMemberRole, setAddMemberRole] =
    useState<ProjectMemberRole>("member");

  const queryClient = useQueryClient();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["project-members", project.project_id],
    queryFn: async () => api.metadata.projects.get(project.project_id),
    enabled: isOpen,
    staleTime: 15_000,
  });

  const members = useMemo<ProjectMember[]>(() => {
    return data?.memberships ?? project.memberships ?? [];
  }, [data?.memberships, project.memberships]);

  const invalidateMembers = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: ["project-members", project.project_id],
    });
    onMembershipChange?.();
  }, [onMembershipChange, project.project_id, queryClient]);

  const {
    mutateAsync: addMember,
    isPending: isAddingMember,
    isError: isAddError,
  } = useMutation({
    mutationFn: (payload: { user_id: string; role: ProjectMemberRole }) =>
      api.metadata.projectMembers.add(project.project_id, payload),
    onSuccess: () => {
      setAddMemberUserId("");
      setAddMemberRole("member");
      invalidateMembers();
    },
  });

  const { mutateAsync: removeMember, isPending: isRemovingMember } = useMutation({
    mutationFn: (userId: string) =>
      api.metadata.projectMembers.remove(project.project_id, userId),
    onSuccess: invalidateMembers,
  });

  const { mutateAsync: updateMemberRole, isPending: isUpdatingRole } = useMutation({
    mutationFn: ({
      userId,
      role,
    }: {
      userId: string;
      role: ProjectMemberRole;
    }) =>
      api.metadata.projectMembers.updateRole(project.project_id, userId, {
        role,
      }),
    onSuccess: invalidateMembers,
  });

  const handleAddMember = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!addMemberUserId.trim()) {
        return;
      }
      await addMember({
        user_id: addMemberUserId.trim(),
        role: addMemberRole,
      });
    },
    [addMember, addMemberRole, addMemberUserId],
  );

  const handleRemoveMember = useCallback(
    async (member: ProjectMember) => {
      if (
        !confirm(
          `ユーザー ${member.user_id} をプロジェクトから削除しますか？`,
        )
      ) {
        return;
      }
      await removeMember(member.user_id);
    },
    [removeMember],
  );

  const handleRoleChange = useCallback(
    async (userId: string, nextRole: ProjectMemberRole) => {
      await updateMemberRole({ userId, role: nextRole });
    },
    [updateMemberRole],
  );

  const managerCount = useMemo(
    () => members.filter((member) => member.role === "manager").length,
    [members],
  );

  return (
    <>
      <Button
        mode="text"
        variant="primary"
        onClick={() => setIsOpen(true)}
        padding="px-3 py-2"
      >
        Manage Members
      </Button>

      <Dialog
        isOpen={isOpen}
        onClose={() => setIsOpen(false)}
        title={`${project.project_name} – Membership`}
      >
        <div className="flex flex-col gap-6 max-w-3xl">
          <Card className="space-y-4">
            <form onSubmit={handleAddMember} className="space-y-4">
              <h3 className="text-sm font-semibold text-stone-900 dark:text-stone-100">
                Add Member
              </h3>
              <Group
                label="User ID (UUID)"
                name="user_id"
                help="Paste the user's UUID. The account must already exist."
              >
                <Input
                  value={addMemberUserId}
                  onChange={(event) => setAddMemberUserId(event.target.value)}
                  placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                  required
                />
              </Group>
              <Group label="Role" name="role">
                <Select
                  options={ROLE_OPTIONS}
                  selected={
                    ROLE_OPTIONS.find((opt) => opt.value === addMemberRole) ??
                    ROLE_OPTIONS[0]
                  }
                  onChange={(value) =>
                    setAddMemberRole(value as ProjectMemberRole)
                  }
                />
              </Group>
              <div className="flex justify-end">
                <Button
                  type="submit"
                  variant="primary"
                  disabled={isAddingMember}
                >
                  {isAddingMember ? "追加中…" : "Add Member"}
                </Button>
              </div>
              {isAddError ? (
                <p className="text-sm text-red-600 dark:text-red-400">
                  メンバーの追加に失敗しました。UUIDと権限を確認してください。
                </p>
              ) : null}
            </form>
          </Card>

          <Card className="space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-stone-900 dark:text-stone-100">
                Current Members
              </h3>
              <span className="inline-flex items-center gap-2 rounded-full bg-emerald-100 dark:bg-emerald-900/30 px-3 py-1 text-xs font-semibold text-emerald-700 dark:text-emerald-200">
                {managerCount} manager{managerCount === 1 ? "" : "s"}
              </span>
            </div>

            {isLoading ? (
              <div className="flex justify-center py-12">
                <Spinner />
              </div>
            ) : isError ? (
              <p className="text-sm text-red-600 dark:text-red-400">
                メンバー情報の取得に失敗しました。
              </p>
            ) : members.length === 0 ? (
              <p className="text-sm text-stone-600 dark:text-stone-300">
                このプロジェクトにはまだメンバーが登録されていません。
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-stone-200 dark:divide-stone-800 text-sm">
                  <thead className="bg-stone-100 dark:bg-stone-800">
                    <tr>
                      <th className="px-3 py-2 text-left font-semibold">
                        User ID
                      </th>
                      <th className="px-3 py-2 text-left font-semibold">
                        Role
                      </th>
                      <th className="px-3 py-2 text-right font-semibold">
                        Actions
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-stone-200 dark:divide-stone-800">
                    {members.map((member) => (
                      <tr
                        key={member.user_id}
                        className="bg-white dark:bg-stone-900"
                      >
                        <td className="px-3 py-2 font-mono text-xs">
                          {member.user_id}
                        </td>
                        <td className="px-3 py-2 max-w-xs">
                          <Select
                            options={ROLE_OPTIONS}
                            selected={
                              ROLE_OPTIONS.find((opt) => opt.value === member.role) ??
                              ROLE_OPTIONS[0]
                            }
                            onChange={(value) =>
                              handleRoleChange(
                                member.user_id,
                                value as ProjectMemberRole,
                              )
                            }
                          />
                        </td>
                        <td className="px-3 py-2">
                          <div className="flex justify-end">
                            <Button
                              mode="text"
                              variant="danger"
                              onClick={() => handleRemoveMember(member)}
                              disabled={isRemovingMember}
                            >
                              Remove
                            </Button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <div className="flex justify-end">
            <Button mode="outline" onClick={() => setIsOpen(false)}>
              Close
            </Button>
          </div>
        </div>
      </Dialog>
    </>
  );
}
