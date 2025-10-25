"use client";

import { useContext, useEffect, useMemo, useState } from "react";
import toast from "react-hot-toast";

import api from "@/app/api";
import {
  useGroupDetail,
  useGroupMembershipManagement,
  useManagedGroups,
} from "@/app/hooks/api/useGroupManagement";

import Card from "@/lib/components/ui/Card";
import Spinner from "@/lib/components/ui/Spinner";
import Button from "@/lib/components/ui/Button";
import { Input, Group as InputGroup, Select } from "@/lib/components/inputs";
import { H2 } from "@/lib/components/ui/Headings";

import type { GroupDetail, GroupMembership, GroupRole } from "@/lib/types";

import UserContext from "../../../contexts/user";

const MEMBER_ROLES: GroupRole[] = ["member", "manager"];

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
          {membership.user?.email ?? "—"}
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

function ManagedGroupPanel({
  groups,
  selectedGroupId,
  onSelectGroup,
  detail,
  membership,
}: {
  groups: GroupDetail[];
  selectedGroupId: number | null;
  onSelectGroup: (id: number) => void;
  detail: { data?: GroupDetail; isLoading: boolean };
  membership: ReturnType<typeof useGroupMembershipManagement>;
}) {
  const [username, setUsername] = useState("");
  const [newMemberRole, setNewMemberRole] = useState<GroupRole>("member");

  const handleAddMember = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!username) return;

    try {
      const user = await api.user.lookup(username);
      await membership.addMember.mutateAsync({
        user_id: user.id,
        role: newMemberRole,
      });
      setUsername("");
    } catch (error) {
      toast.error("Unable to add member. Check the username and try again.");
    }
  };

  return (
    <div className="grid gap-4 xl:grid-cols-[1fr,2fr]">
      <div className="space-y-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-stone-500 dark:text-stone-400">
          Managed groups
        </h3>
        <div className="max-h-64 overflow-y-auto">
          {groups.length === 0 ? (
            <p className="text-sm text-stone-500 dark:text-stone-400">
              You are not managing any groups yet.
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
            Select a group to manage its membership.
          </p>
        ) : detail.isLoading ? (
          <div className="flex justify-center py-8">
            <Spinner />
          </div>
        ) : !detail.data ? (
          <p className="text-sm text-stone-500 dark:text-stone-400">
            Unable to load group details. Please try again later.
          </p>
        ) : (
          <div className="space-y-4">
            <div>
              <h3 className="text-lg font-semibold text-stone-900 dark:text-stone-50">
                {detail.data.name}
              </h3>
              {detail.data.description ? (
                <p className="text-sm text-stone-500 dark:text-stone-400">
                  {detail.data.description}
                </p>
              ) : null}
            </div>
            <div className="space-y-2">
              <h4 className="font-semibold text-stone-700 dark:text-stone-200">
                Members
              </h4>
              {detail.data.memberships.length === 0 ? (
                <p className="text-sm text-stone-500 dark:text-stone-400">
                  No members in this group yet.
                </p>
              ) : (
                detail.data.memberships.map((membershipEntry) => (
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
            <form className="space-y-3" onSubmit={handleAddMember}>
              <div className="grid gap-3 sm:grid-cols-[2fr,1fr]">
                <InputGroup label="Username" name="new-member-username">
                  <Input
                    value={username}
                    onChange={(event) => setUsername(event.target.value)}
                    placeholder="Enter username"
                    required
                  />
                </InputGroup>
                <InputGroup label="Role" name="new-member-role">
                  <Select<GroupRole>
                    options={MEMBER_ROLES.map((role) => ({
                      id: role,
                      label: role,
                      value: role,
                    }))}
                    selected={{
                      id: newMemberRole,
                      label: newMemberRole,
                      value: newMemberRole,
                    }}
                    onChange={(role) => setNewMemberRole(role)}
                  />
                </InputGroup>
              </div>
              <p className="text-xs text-stone-500 dark:text-stone-400">
                Enter the exact username of an existing user to add them to this group.
              </p>
              <div className="flex justify-end">
                <Button
                  type="submit"
                  variant="secondary"
                  disabled={!username || membership.addMember.isPending}
                >
                  Add member
                </Button>
              </div>
            </form>
          </div>
        )}
      </div>
    </div>
  );
}

export default function ManageGroupsPage() {
  const currentUser = useContext(UserContext);

  const managedGroupsQuery = useManagedGroups();

  const managedGroups = useMemo(() => {
    const groups = managedGroupsQuery.data ?? [];
    if (!currentUser) return [];
    return groups.filter((group) =>
      group.memberships.some(
        (membership) =>
          membership.user_id === currentUser.id && membership.role === "manager",
      ),
    );
  }, [managedGroupsQuery.data, currentUser]);

  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null);

  useEffect(() => {
    if (managedGroups.length > 0 && selectedGroupId == null) {
      setSelectedGroupId(managedGroups[0].id);
    } else if (
      selectedGroupId != null &&
      !managedGroups.some((group) => group.id === selectedGroupId)
    ) {
      setSelectedGroupId(managedGroups[0]?.id ?? null);
    }
  }, [managedGroups, selectedGroupId]);

  const groupDetail = useGroupDetail(selectedGroupId ?? undefined);
  const membership = useGroupMembershipManagement(selectedGroupId ?? undefined);

  if (!currentUser) {
    return null;
  }

  const managesAnyGroup = managedGroups.length > 0;

  return (
    <div className="space-y-6">
      <div>
        <H2>Group Management</H2>
        <p className="text-sm text-stone-500 dark:text-stone-400">
          Manage membership for the groups where you are a manager.
        </p>
      </div>

      <Card className="space-y-6">
        {managedGroupsQuery.isLoading ? (
          <div className="flex justify-center py-12">
            <Spinner />
          </div>
        ) : !managesAnyGroup ? (
          <p className="text-sm text-stone-500 dark:text-stone-400">
            You are not a manager of any groups yet. Ask an administrator to add
            you as a manager to a group to begin managing memberships.
          </p>
        ) : (
          <ManagedGroupPanel
            groups={managedGroups}
            selectedGroupId={selectedGroupId}
            onSelectGroup={setSelectedGroupId}
            detail={{
              data: groupDetail.data,
              isLoading: groupDetail.isLoading,
            }}
            membership={membership}
          />
        )}
      </Card>
    </div>
  );
}
