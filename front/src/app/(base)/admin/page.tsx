"use client";

import { useContext, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import {
  useAdminGroupDetail,
  useAdminGroupMembership,
  useAdminGroups,
} from "@/app/hooks/api/useAdminGroups";
import useAdminUsers from "@/app/hooks/api/useAdminUsers";

import AdminUserCreateForm from "@/lib/components/users/AdminUserCreateForm";
import Card from "@/lib/components/ui/Card";
import Hero from "@/lib/components/ui/Hero";
import Button from "@/lib/components/ui/Button";
import { Group as InputGroup, Input } from "@/lib/components/inputs";
import Spinner from "@/lib/components/ui/Spinner";

import type {
  AdminUserUpdate,
  Group,
  GroupDetail,
  GroupMembership,
  GroupMembershipUpdate,
  GroupRole,
  SimpleUser,
} from "@/lib/types";

import UserContext from "../../contexts/user";

const MEMBER_ROLES: GroupRole[] = ["member", "manager"];

function UsersSection({
  users,
  isLoading,
  onCreate,
  onToggleAdmin,
  onToggleActive,
  onRemove,
}: {
  users: SimpleUser[];
  isLoading: boolean;
  onCreate: () => void;
  onToggleAdmin: (id: string, value: boolean) => void;
  onToggleActive: (id: string, value: boolean) => void;
  onRemove: (id: string) => void;
}) {
  return (
    <Card className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-stone-900 dark:text-stone-100">
          Users
        </h2>
        <p className="text-sm text-stone-500 dark:text-stone-400">
          Manage user accounts, administrator privileges, and account status.
        </p>
      </div>

      <AdminUserCreateForm onCreate={onCreate} />

      <div className="overflow-x-auto">
        {isLoading ? (
          <div className="flex justify-center py-12">
            <Spinner />
          </div>
        ) : (
          <table className="min-w-full divide-y divide-stone-200 dark:divide-stone-700 text-sm">
            <thead className="bg-stone-100 dark:bg-stone-800">
              <tr>
                <th className="px-3 py-2 text-left font-semibold">Username</th>
                <th className="px-3 py-2 text-left font-semibold">Email</th>
                <th className="px-3 py-2 text-center font-semibold">Admin</th>
                <th className="px-3 py-2 text-center font-semibold">Active</th>
                <th className="px-3 py-2 text-left font-semibold">Created</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-stone-200 dark:divide-stone-700">
              {users.map((user) => (
                <tr key={user.id} className="bg-white dark:bg-stone-900">
                  <td className="px-3 py-2 font-medium text-stone-900 dark:text-stone-100">
                    {user.username}
                  </td>
                  <td className="px-3 py-2 text-stone-600 dark:text-stone-300">
                    {user.email ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-center">
                    <input
                      type="checkbox"
                      className="h-4 w-4 text-emerald-600 focus:ring-emerald-500"
                      checked={user.is_superuser}
                      onChange={(event) =>
                        onToggleAdmin(user.id, event.target.checked)
                      }
                    />
                  </td>
                  <td className="px-3 py-2 text-center">
                    <input
                      type="checkbox"
                      className="h-4 w-4 text-emerald-600 focus:ring-emerald-500"
                      checked={user.is_active}
                      onChange={(event) =>
                        onToggleActive(user.id, event.target.checked)
                      }
                    />
                  </td>
                  <td className="px-3 py-2 text-stone-600 dark:text-stone-300">
                    {user.created_on.toLocaleString()}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Button
                      mode="text"
                      variant="danger"
                      onClick={() => {
                        if (confirm(`Remove user ${user.username}?`)) {
                          onRemove(user.id);
                        }
                      }}
                    >
                      Remove
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Card>
  );
}

function MembershipRow({
  membership,
  onChangeRole,
  onRemove,
}: {
  membership: GroupMembership;
  onChangeRole: (role: GroupRole) => void;
  onRemove: () => void;
}) {
  return (
    <div className="flex items-center justify-between rounded border border-stone-200 dark:border-stone-700 p-3">
      <div>
        <p className="font-medium text-stone-900 dark:text-stone-100">
          {membership.user?.username ?? membership.user_id}
        </p>
        <p className="text-xs text-stone-500 dark:text-stone-400">
          {membership.user?.email ?? "Unknown email"}
        </p>
      </div>
      <div className="flex items-center gap-2">
        <select
          className="rounded border border-stone-300 bg-white px-2 py-1 text-sm dark:bg-stone-900 dark:border-stone-700"
          value={membership.role}
          onChange={(event) => onChangeRole(event.target.value as GroupRole)}
        >
          {MEMBER_ROLES.map((role) => (
            <option key={role} value={role}>
              {role}
            </option>
          ))}
        </select>
        <Button mode="text" variant="danger" onClick={onRemove}>
          Remove
        </Button>
      </div>
    </div>
  );
}

function GroupsSection({
  users,
  groups,
  groupsLoading,
  selectedGroupId,
  onSelectGroup,
  groupDetail,
  onUpdateGroup,
  onDeleteGroup,
  onCreateGroup,
  membership,
}: {
  users: SimpleUser[];
  groups: Group[];
  groupsLoading: boolean;
  selectedGroupId: number | null;
  onSelectGroup: (id: number) => void;
  groupDetail: {
    data?: GroupDetail;
    isLoading: boolean;
  };
  onUpdateGroup: (id: number, data: { name: string; description: string }) => void;
  onDeleteGroup: (id: number) => void;
  onCreateGroup: (data: { name: string; description: string }) => void;
  membership: {
    addMember: { mutate: (payload: { user_id: string; role: GroupRole }) => void };
    updateMember: {
      mutate: (args: { userId: string; data: GroupMembershipUpdate }) => void;
    };
    removeMember: { mutate: (userId: string) => void };
  };
}) {
  const [newGroupName, setNewGroupName] = useState("");
  const [newGroupDescription, setNewGroupDescription] = useState("");

  const detail = groupDetail.data;

  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");

  useEffect(() => {
    if (detail) {
      setEditName(detail.name);
      setEditDescription(detail.description ?? "");
    }
  }, [detail]);

  const memberUserIds = useMemo(() => {
    const ids = new Set<string>();
    detail?.memberships.forEach((member) => ids.add(member.user_id));
    return ids;
  }, [detail?.memberships]);

  const availableUsers = useMemo(
    () => users.filter((user) => !memberUserIds.has(user.id)),
    [users, memberUserIds],
  );

  const [newMemberId, setNewMemberId] = useState<string>("");
  const [newMemberRole, setNewMemberRole] = useState<GroupRole>("member");

  useEffect(() => {
    if (availableUsers.length > 0) {
      setNewMemberId(availableUsers[0].id);
    } else {
      setNewMemberId("");
    }
  }, [availableUsers]);

  return (
    <Card className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-stone-900 dark:text-stone-100">
          Groups
        </h2>
        <p className="text-sm text-stone-500 dark:text-stone-400">
          Create groups and assign group managers to delegate responsibilities.
        </p>
      </div>

      <form
        className="grid gap-2 md:grid-cols-2"
        onSubmit={(event) => {
          event.preventDefault();
          onCreateGroup({ name: newGroupName, description: newGroupDescription });
          setNewGroupName("");
          setNewGroupDescription("");
        }}
      >
        <InputGroup label="Name" name="group-name">
          <Input
            value={newGroupName}
            onChange={(event) => setNewGroupName(event.target.value)}
            required
          />
        </InputGroup>
        <InputGroup label="Description" name="group-description">
          <Input
            value={newGroupDescription}
            onChange={(event) => setNewGroupDescription(event.target.value)}
          />
        </InputGroup>
        <div className="md:col-span-2 flex justify-end">
          <Button type="submit" variant="primary">
            Create group
          </Button>
        </div>
      </form>

      <div className="grid gap-4 xl:grid-cols-[1fr,2fr]">
        <div className="space-y-3">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-stone-500 dark:text-stone-400">
            Existing groups
          </h3>
          <div className="max-h-64 overflow-y-auto">
            {groupsLoading ? (
              <div className="flex justify-center py-8">
                <Spinner />
              </div>
            ) : groups.length === 0 ? (
              <p className="text-sm text-stone-500 dark:text-stone-400">
                No groups yet.
              </p>
            ) : (
              <ul className="space-y-1">
                {groups.map((group) => (
                  <li key={group.id}>
                    <Button
                      mode="text"
                      variant={group.id === selectedGroupId ? "primary" : "secondary"}
                      className="w-full justify-start"
                      onClick={() => onSelectGroup(group.id)}
                    >
                      {group.name}
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        <div className="space-y-4">
          {selectedGroupId == null ? (
            <p className="text-sm text-stone-500 dark:text-stone-400">
              Select a group to view and manage its members.
            </p>
          ) : groupDetail.isLoading || !detail ? (
            <div className="flex justify-center py-8">
              <Spinner />
            </div>
          ) : (
            <div className="space-y-4">
              <form
                className="grid gap-2 md:grid-cols-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  onUpdateGroup(selectedGroupId, {
                    name: editName,
                    description: editDescription,
                  });
                }}
              >
                <InputGroup label="Name" name="edit-name">
                  <Input
                    value={editName}
                    onChange={(event) => setEditName(event.target.value)}
                    required
                  />
                </InputGroup>
                <InputGroup label="Description" name="edit-description">
                  <Input
                    value={editDescription}
                    onChange={(event) => setEditDescription(event.target.value)}
                  />
                </InputGroup>
                <div className="md:col-span-2 flex justify-between">
                  <Button
                    mode="text"
                    variant="danger"
                    onClick={() => {
                      if (confirm(`Delete group ${detail.name}?`)) {
                        onDeleteGroup(selectedGroupId);
                      }
                    }}
                  >
                    Delete group
                  </Button>
                  <Button type="submit" variant="primary">
                    Save changes
                  </Button>
                </div>
              </form>

              <div className="space-y-2">
                <h4 className="font-semibold text-stone-700 dark:text-stone-200">
                  Members
                </h4>
                <div className="space-y-2">
                  {detail.memberships.length === 0 ? (
                    <p className="text-sm text-stone-500 dark:text-stone-400">
                      No members in this group yet.
                    </p>
                  ) : (
                    detail.memberships.map((membershipEntry) => (
                      <MembershipRow
                        key={`${membershipEntry.group_id}-${membershipEntry.user_id}`}
                        membership={membershipEntry}
                        onChangeRole={(role) =>
                          membership.updateMember.mutate({
                            userId: membershipEntry.user_id,
                            data: { role },
                          })
                        }
                        onRemove={() =>
                          membership.removeMember.mutate(membershipEntry.user_id)
                        }
                      />
                    ))
                  )}
                </div>

                <form
                  className="flex flex-col gap-2 md:flex-row"
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (!newMemberId) return;
                    membership.addMember.mutate({
                      user_id: newMemberId,
                      role: newMemberRole,
                    });
                  }}
                >
                  <select
                    className="w-full rounded border border-stone-300 bg-white px-2 py-1 text-sm dark:bg-stone-900 dark:border-stone-700"
                    value={newMemberId}
                    onChange={(event) => setNewMemberId(event.target.value)}
                  >
                    {availableUsers.length === 0 ? (
                      <option value="" disabled>
                        All users already members
                      </option>
                    ) : (
                      availableUsers.map((user) => (
                        <option key={user.id} value={user.id}>
                          {user.username}
                        </option>
                      ))
                    )}
                  </select>
                  <select
                    className="rounded border border-stone-300 bg-white px-2 py-1 text-sm dark:bg-stone-900 dark:border-stone-700"
                    value={newMemberRole}
                    onChange={(event) =>
                      setNewMemberRole(event.target.value as GroupRole)
                    }
                  >
                    {MEMBER_ROLES.map((role) => (
                      <option key={role} value={role}>
                        {role}
                      </option>
                    ))}
                  </select>
                  <Button type="submit" variant="secondary" disabled={!newMemberId}>
                    Add member
                  </Button>
                </form>
              </div>
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

export default function AdminPage() {
  const router = useRouter();
  const currentUser = useContext(UserContext);

  const isAdmin = !!currentUser?.is_superuser;

  useEffect(() => {
    if (currentUser && !currentUser.is_superuser) {
      router.replace("/");
    }
  }, [currentUser, router]);

  const usersHook = useAdminUsers({ enabled: isAdmin });
  const groupsHook = useAdminGroups({ enabled: isAdmin });

  const groups = useMemo(
    () => groupsHook.data?.items ?? [],
    [groupsHook.data],
  );

  const users = useMemo(() => usersHook.data ?? [], [usersHook.data]);

  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null);

  useEffect(() => {
    if (groups.length > 0 && selectedGroupId == null) {
      setSelectedGroupId(groups[0].id);
    }
  }, [groups, selectedGroupId]);

  const groupDetailHook = useAdminGroupDetail(selectedGroupId ?? undefined);
  const membershipHook = useAdminGroupMembership(selectedGroupId ?? undefined);

  if (!isAdmin) {
    return (
      <div className="space-y-4">
        <Hero text="Administration" />
        <p className="text-center text-stone-500 dark:text-stone-400">
          You need administrator privileges to access this page.
        </p>
      </div>
    );
  }

  const handleToggle = (id: string, data: AdminUserUpdate) => {
    usersHook.update.mutate({ id, data });
  };

  return (
    <div className="space-y-8">
      <Hero text="Administration" />
      <div className="grid gap-6 xl:grid-cols-2">
        <UsersSection
          users={users}
          isLoading={usersHook.isLoading}
          onCreate={() => usersHook.refetch()}
          onToggleAdmin={(id, value) => handleToggle(id, { is_superuser: value })}
          onToggleActive={(id, value) => handleToggle(id, { is_active: value })}
          onRemove={(id) => usersHook.remove.mutate(id)}
        />
        <GroupsSection
          users={users}
          groups={groups}
          groupsLoading={groupsHook.isLoading}
          selectedGroupId={selectedGroupId}
          onSelectGroup={setSelectedGroupId}
          groupDetail={{
            data: groupDetailHook.data,
            isLoading: groupDetailHook.isLoading,
          }}
          onUpdateGroup={(id, data) => groupsHook.update.mutate({ id, data })}
          onDeleteGroup={(id) =>
            groupsHook.remove.mutate(id, {
              onSuccess: () => setSelectedGroupId(null),
            })
          }
          onCreateGroup={(data) =>
            groupsHook.create.mutate(data, {
              onSuccess: (group) => setSelectedGroupId(group.id),
            })
          }
          membership={{
            addMember: membershipHook.addMember,
            updateMember: membershipHook.updateMember,
            removeMember: membershipHook.removeMember,
          }}
        />
      </div>
    </div>
  );
}
