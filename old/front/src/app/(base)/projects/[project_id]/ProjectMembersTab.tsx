"use client";

import { useState } from "react";
import { Plus, User, Crown, UserCog, Trash2 } from "lucide-react";

import { useProject } from "@/app/hooks/api/useMetadata";

import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import Empty from "@/lib/components/ui/Empty";

import {
  canAddProjectMember,
  canRemoveProjectMember,
  canChangeProjectMemberRole,
} from "@/lib/utils/permissions";

import type { Project, ProjectMember } from "@/lib/types";

interface ProjectMembersTabProps {
  project: Project;
  canEdit: boolean;
  isMember: boolean;
  isManager: boolean;
}

export default function ProjectMembersTab({
  project,
  isManager,
}: ProjectMembersTabProps) {
  const { removeMember, updateMemberRole } = useProject(project.project_id);
  const [isAddingMember, setIsAddingMember] = useState(false);

  const members = project.memberships ?? [];
  const managers = members.filter((m) => m.role === "manager");
  const regularMembers = members.filter((m) => m.role === "member");

  const canManage = isManager;

  const handleRemoveMember = async (userId: string) => {
    if (!confirm("Are you sure you want to remove this member?")) return;
    await removeMember.mutateAsync(userId);
  };

  const handleToggleRole = async (member: ProjectMember) => {
    const newRole = member.role === "manager" ? "member" : "manager";
    await updateMemberRole.mutateAsync({
      userId: member.user_id,
      payload: { role: newRole },
    });
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold">Project Members</h3>
          <p className="text-sm text-stone-600 dark:text-stone-400">
            {members.length} member{members.length !== 1 ? "s" : ""} (
            {managers.length} manager{managers.length !== 1 ? "s" : ""})
          </p>
        </div>
        {canManage && (
          <Button
            variant="primary"
            padding="px-3 py-2"
            onClick={() => setIsAddingMember(true)}
          >
            <Plus className="w-4 h-4 mr-2" />
            Add Member
          </Button>
        )}
      </div>

      {members.length === 0 ? (
        <Empty>
          <User className="w-16 h-16 text-stone-400 dark:text-stone-600 mb-4" />
          <p className="text-lg text-stone-600 dark:text-stone-400">
            No members yet
          </p>
        </Empty>
      ) : (
        <div className="space-y-6">
          {/* Managers */}
          {managers.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold mb-3 text-stone-700 dark:text-stone-300 flex items-center gap-2">
                <Crown className="w-4 h-4 text-yellow-500" />
                Managers ({managers.length})
              </h4>
              <div className="space-y-2">
                {managers.map((member) => (
                  <MemberCard
                    key={member.user_id}
                    member={member}
                    canManage={canManage}
                    onRemove={() => handleRemoveMember(member.user_id)}
                    onToggleRole={() => handleToggleRole(member)}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Regular Members */}
          {regularMembers.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold mb-3 text-stone-700 dark:text-stone-300 flex items-center gap-2">
                <User className="w-4 h-4 text-blue-500" />
                Members ({regularMembers.length})
              </h4>
              <div className="space-y-2">
                {regularMembers.map((member) => (
                  <MemberCard
                    key={member.user_id}
                    member={member}
                    canManage={canManage}
                    onRemove={() => handleRemoveMember(member.user_id)}
                    onToggleRole={() => handleToggleRole(member)}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Add Member Modal Placeholder */}
      {isAddingMember && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <Card className="p-6 max-w-md w-full m-4">
            <h3 className="text-lg font-bold mb-4">Add Member</h3>
            <p className="text-sm text-stone-600 dark:text-stone-400 mb-4">
              Member management UI coming soon
            </p>
            <div className="flex justify-end gap-2">
              <Button mode="text" onClick={() => setIsAddingMember(false)}>
                Cancel
              </Button>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}

interface MemberCardProps {
  member: ProjectMember;
  canManage: boolean;
  onRemove: () => void;
  onToggleRole: () => void;
}

function MemberCard({
  member,
  canManage,
  onRemove,
  onToggleRole,
}: MemberCardProps) {
  const isManager = member.role === "manager";

  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div
            className={`w-10 h-10 rounded-full flex items-center justify-center ${
              isManager
                ? "bg-yellow-100 dark:bg-yellow-900/30"
                : "bg-blue-100 dark:bg-blue-900/30"
            }`}
          >
            {isManager ? (
              <Crown className="w-5 h-5 text-yellow-600 dark:text-yellow-400" />
            ) : (
              <User className="w-5 h-5 text-blue-600 dark:text-blue-400" />
            )}
          </div>
          <div>
            <p className="font-medium">{member.user.username}</p>
            {member.user.name && (
              <p className="text-xs text-stone-500 dark:text-stone-400">
                {member.user.name}
              </p>
            )}
            <p className="text-sm text-stone-600 dark:text-stone-400">
              {isManager ? "Manager" : "Member"}
            </p>
          </div>
        </div>

        {canManage && (
          <div className="flex items-center gap-2">
            <Button
              mode="text"
              padding="p-2"
              onClick={onToggleRole}
              title={
                isManager ? "Demote to member" : "Promote to manager"
              }
            >
              <UserCog className="w-4 h-4" />
            </Button>
            <Button
              mode="text"
              padding="p-2"
              onClick={onRemove}
              className="text-red-600 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300"
              title="Remove member"
            >
              <Trash2 className="w-4 h-4" />
            </Button>
          </div>
        )}
      </div>
    </Card>
  );
}
