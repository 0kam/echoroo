"use client";

import { type ChangeEvent, useCallback, useMemo, useState } from "react";

import useActiveUser from "@/app/hooks/api/useActiveUser";
import useAdminUsers from "@/app/hooks/api/useAdminUsers";
import { useMetadataProjects } from "@/app/hooks/api/useMetadata";

import { Checkbox, Group, Input, TextArea } from "@/lib/components/inputs";
import MultiCheckbox, {
  type MultiCheckboxOption,
} from "@/lib/components/inputs/MultiCheckbox";
import Card from "@/lib/components/ui/Card";
import Button from "@/lib/components/ui/Button";
import Spinner from "@/lib/components/ui/Spinner";
import type { Project, ProjectMemberCreate, SimpleUser } from "@/lib/types";
import { textOrUndefined } from "@/lib/utils/forms";

const TARGET_TAXA_OPTIONS: MultiCheckboxOption[] = [
  { value: "Birds", label: "Birds" },
  { value: "Anurans", label: "Anurans" },
  { value: "Insects", label: "Insects" },
  { value: "Bats", label: "Bats" },
  { value: "Land mammals", label: "Land mammals" },
  { value: "Fishes", label: "Fishes" },
  { value: "Cetaceans", label: "Cetaceans" },
];

type ProjectFormState = {
  project_name: string;
  url: string;
  description: string;
  target_taxa: string[];
  admin_name: string;
  admin_email: string;
  is_active: boolean;
  initial_members: ProjectMemberCreate[];
};

const INITIAL_FORM_STATE: ProjectFormState = {
  project_name: "",
  url: "",
  description: "",
  target_taxa: [],
  admin_name: "",
  admin_email: "",
  is_active: true,
  initial_members: [],
};

type EditFormState = Omit<ProjectFormState, "initial_members">;

function UserSelect({
  users,
  selectedMembers,
  onAdd,
  onRemove,
  onRoleChange,
}: {
  users: SimpleUser[];
  selectedMembers: ProjectMemberCreate[];
  onAdd: (userId: string) => void;
  onRemove: (userId: string) => void;
  onRoleChange: (userId: string, role: "manager" | "member") => void;
}) {
  const [searchTerm, setSearchTerm] = useState("");

  const filteredUsers = useMemo(() => {
    const term = searchTerm.toLowerCase();
    return users.filter(
      (user) =>
        user.username.toLowerCase().includes(term) ||
        user.email?.toLowerCase().includes(term),
    );
  }, [users, searchTerm]);

  const selectedUserIds = useMemo(
    () => new Set(selectedMembers.map((m) => m.user_id)),
    [selectedMembers],
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-2">
        <label className="text-sm font-medium text-stone-700 dark:text-stone-300">
          Initial Members
          <span className="ml-1 text-rose-500">*</span>
        </label>
        <p className="text-xs text-stone-500 dark:text-stone-400">
          At least one manager is required.
        </p>
      </div>

      {/* Selected members */}
      {selectedMembers.length > 0 && (
        <div className="space-y-2">
          {selectedMembers.map((member) => {
            const user = users.find((u) => u.id === member.user_id);
            return (
              <div
                key={member.user_id}
                className="flex items-center justify-between gap-2 rounded-lg border border-stone-200 dark:border-stone-700 bg-stone-50 dark:bg-stone-800 px-3 py-2"
              >
                <span className="text-sm font-medium text-stone-900 dark:text-stone-100">
                  {user?.username ?? member.user_id}
                </span>
                <div className="flex items-center gap-2">
                  <select
                    value={member.role}
                    onChange={(e) =>
                      onRoleChange(
                        member.user_id,
                        e.target.value as "manager" | "member",
                      )
                    }
                    className="rounded border border-stone-300 dark:border-stone-600 bg-white dark:bg-stone-700 px-2 py-1 text-sm text-stone-900 dark:text-stone-100"
                  >
                    <option value="manager">Manager</option>
                    <option value="member">Member</option>
                  </select>
                  <Button
                    mode="text"
                    variant="danger"
                    padding="p-1"
                    onClick={() => onRemove(member.user_id)}
                  >
                    Remove
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* User search and selection */}
      <div className="space-y-2">
        <Input
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          placeholder="Search users by username or email..."
        />
        <div className="max-h-40 overflow-y-auto rounded border border-stone-200 dark:border-stone-700">
          {filteredUsers.length === 0 ? (
            <p className="px-3 py-2 text-sm text-stone-500 dark:text-stone-400">
              No users found
            </p>
          ) : (
            filteredUsers.map((user) => {
              const isSelected = selectedUserIds.has(user.id);
              return (
                <button
                  key={user.id}
                  type="button"
                  disabled={isSelected}
                  onClick={() => onAdd(user.id)}
                  className={`w-full px-3 py-2 text-left text-sm transition-colors ${
                    isSelected
                      ? "bg-stone-100 dark:bg-stone-800 text-stone-400 cursor-not-allowed"
                      : "hover:bg-emerald-50 dark:hover:bg-emerald-900/30 text-stone-900 dark:text-stone-100"
                  }`}
                >
                  <span className="font-medium">{user.username}</span>
                  {user.email && (
                    <span className="ml-2 text-stone-500 dark:text-stone-400">
                      ({user.email})
                    </span>
                  )}
                  {isSelected && (
                    <span className="ml-2 text-emerald-600 dark:text-emerald-400">
                      (selected)
                    </span>
                  )}
                </button>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}

export default function ProjectsPage() {
  const [searchTerm, setSearchTerm] = useState("");
  const [formState, setFormState] =
    useState<ProjectFormState>(INITIAL_FORM_STATE);
  const [editing, setEditing] = useState<
    { id: string; draft: EditFormState } | undefined
  >(undefined);

  const { data: activeUser } = useActiveUser();
  const canManage = activeUser?.is_superuser ?? false;

  const usersHook = useAdminUsers({ enabled: canManage });
  const users = useMemo(() => usersHook.data ?? [], [usersHook.data]);

  const query = useMemo(
    () => ({
      search: textOrUndefined(searchTerm),
    }),
    [searchTerm],
  );

  const {
    query: projectsQuery,
    create,
    update,
    remove,
  } = useMetadataProjects(query);
  const { data: projects, isLoading, isError } = projectsQuery;

  // Form handlers for initial members
  const handleAddMember = useCallback((userId: string) => {
    setFormState((prev) => ({
      ...prev,
      initial_members: [
        ...prev.initial_members,
        { user_id: userId, role: "manager" as const },
      ],
    }));
  }, []);

  const handleRemoveMember = useCallback((userId: string) => {
    setFormState((prev) => ({
      ...prev,
      initial_members: prev.initial_members.filter((m) => m.user_id !== userId),
    }));
  }, []);

  const handleMemberRoleChange = useCallback(
    (userId: string, role: "manager" | "member") => {
      setFormState((prev) => ({
        ...prev,
        initial_members: prev.initial_members.map((m) =>
          m.user_id === userId ? { ...m, role } : m,
        ),
      }));
    },
    [],
  );

  const handleCreate = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!canManage) return;
      if (!formState.project_name.trim()) {
        return;
      }

      // Validate at least one manager
      const hasManager = formState.initial_members.some(
        (m) => m.role === "manager",
      );
      if (!hasManager) {
        alert("At least one manager must be assigned to the project.");
        return;
      }

      await create.mutateAsync({
        project_name: formState.project_name.trim(),
        url: textOrUndefined(formState.url),
        description: textOrUndefined(formState.description),
        target_taxa:
          formState.target_taxa.length > 0
            ? formState.target_taxa.join(", ")
            : undefined,
        admin_name: textOrUndefined(formState.admin_name),
        admin_email: textOrUndefined(formState.admin_email),
        is_active: formState.is_active,
        initial_members: formState.initial_members,
      });
      setFormState(INITIAL_FORM_STATE);
    },
    [canManage, create, formState],
  );

  const startEdit = (project: Project) => {
    if (!canManage) return;
    const targetTaxaArray = project.target_taxa
      ? project.target_taxa.split(",").map((t) => t.trim()).filter((t) => t)
      : [];
    setEditing({
      id: project.project_id,
      draft: {
        project_name: project.project_name,
        url: project.url ?? "",
        description: project.description ?? "",
        target_taxa: targetTaxaArray,
        admin_name: project.admin_name ?? "",
        admin_email: project.admin_email ?? "",
        is_active: project.is_active,
      },
    });
  };

  const commitEdit = async () => {
    if (!editing || !canManage) {
      return;
    }
    await update.mutateAsync({
      id: editing.id,
      payload: {
        project_name:
          textOrUndefined(editing.draft.project_name) ??
          editing.draft.project_name.trim(),
        url: textOrUndefined(editing.draft.url),
        description: textOrUndefined(editing.draft.description),
        target_taxa:
          editing.draft.target_taxa.length > 0
            ? editing.draft.target_taxa.join(", ")
            : undefined,
        admin_name: textOrUndefined(editing.draft.admin_name),
        admin_email: textOrUndefined(editing.draft.admin_email),
        is_active: editing.draft.is_active,
      },
    });
    setEditing(undefined);
  };

  const cancelEdit = () => setEditing(undefined);

  const handleDelete = async (id: string, name: string) => {
    if (!canManage) return;
    if (
      !confirm(
        `Delete project "${name}"? This action cannot be undone and may affect associated data.`,
      )
    ) {
      return;
    }
    await remove.mutateAsync(id);
  };

  return (
    <div className="flex flex-col gap-6">
      {/* Create Project Form */}
      <Card>
        <div className="mb-4">
          <h2 className="text-lg font-semibold text-stone-900 dark:text-stone-100">
            Create New Project
          </h2>
          <p className="text-sm text-stone-500 dark:text-stone-400">
            Add a new project with at least one manager assigned.
          </p>
        </div>

        <form className="grid gap-4 sm:grid-cols-2" onSubmit={handleCreate}>
          <Group label="Project Name" name="project_name">
            <Input
              value={formState.project_name}
              onChange={(e) =>
                setFormState((prev) => ({
                  ...prev,
                  project_name: e.target.value,
                }))
              }
              placeholder="My Research Project"
              required
            />
          </Group>

          <Group label="URL" name="url">
            <Input
              type="url"
              value={formState.url}
              onChange={(e) =>
                setFormState((prev) => ({ ...prev, url: e.target.value }))
              }
              placeholder="https://example.com/project"
            />
          </Group>

          <Group label="Target Taxa" name="target_taxa">
            <MultiCheckbox
              options={TARGET_TAXA_OPTIONS}
              selectedValues={formState.target_taxa}
              onChange={(values) =>
                setFormState((prev) => ({
                  ...prev,
                  target_taxa: values,
                }))
              }
            />
          </Group>

          <Group label="Admin Name" name="admin_name">
            <Input
              value={formState.admin_name}
              onChange={(e) =>
                setFormState((prev) => ({
                  ...prev,
                  admin_name: e.target.value,
                }))
              }
              placeholder="Project Administrator"
            />
          </Group>

          <Group label="Admin Email" name="admin_email">
            <Input
              type="email"
              value={formState.admin_email}
              onChange={(e) =>
                setFormState((prev) => ({
                  ...prev,
                  admin_email: e.target.value,
                }))
              }
              placeholder="admin@example.com"
            />
          </Group>

          <div className="flex items-center">
            <label className="flex items-center gap-2 text-sm text-stone-600 dark:text-stone-300">
              <Checkbox
                checked={formState.is_active}
                onChange={(e: ChangeEvent<HTMLInputElement>) =>
                  setFormState((prev) => ({
                    ...prev,
                    is_active: e.target.checked,
                  }))
                }
              />
              Active
            </label>
          </div>

          <div className="sm:col-span-2">
            <Group label="Description" name="description">
              <TextArea
                value={formState.description}
                onChange={(e) =>
                  setFormState((prev) => ({
                    ...prev,
                    description: e.target.value,
                  }))
                }
                placeholder="Project description..."
                rows={3}
              />
            </Group>
          </div>

          <div className="sm:col-span-2">
            <UserSelect
              users={users}
              selectedMembers={formState.initial_members}
              onAdd={handleAddMember}
              onRemove={handleRemoveMember}
              onRoleChange={handleMemberRoleChange}
            />
          </div>

          <div className="sm:col-span-2 flex justify-end gap-2">
            <Button
              type="reset"
              mode="text"
              variant="secondary"
              onClick={() => setFormState(INITIAL_FORM_STATE)}
            >
              Reset
            </Button>
            <Button type="submit" variant="primary" disabled={create.isPending}>
              {create.isPending ? "Creating..." : "Create Project"}
            </Button>
          </div>
        </form>
      </Card>

      {/* Projects List */}
      <Card>
        <div className="flex flex-col gap-4">
          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-stone-900 dark:text-stone-100">
                Registered Projects
              </h2>
              <p className="text-sm text-stone-500 dark:text-stone-400">
                Manage existing projects and their settings.
              </p>
            </div>
            <Input
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Search by name..."
              className="md:w-72"
            />
          </div>

          {isError ? (
            <p className="text-sm text-red-600 dark:text-red-400">
              Failed to load projects.
            </p>
          ) : null}

          {isLoading ? (
            <div className="flex justify-center py-12">
              <Spinner />
            </div>
          ) : projects && projects.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-stone-200 dark:divide-stone-800 text-sm">
                <thead className="bg-stone-100 dark:bg-stone-800">
                  <tr>
                    <th className="px-3 py-2 text-left font-semibold">ID</th>
                    <th className="px-3 py-2 text-left font-semibold">Name</th>
                    <th className="px-3 py-2 text-left font-semibold hidden md:table-cell">
                      Description
                    </th>
                    <th className="px-3 py-2 text-center font-semibold">
                      Active
                    </th>
                    <th className="px-3 py-2 text-left font-semibold hidden lg:table-cell">
                      Members
                    </th>
                    <th className="px-3 py-2 text-left font-semibold hidden lg:table-cell">
                      Created
                    </th>
                    <th className="px-3 py-2 text-right font-semibold">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-stone-200 dark:divide-stone-800">
                  {projects.map((project) => {
                    const isEditing =
                      canManage && editing?.id === project.project_id;
                    return (
                      <tr
                        key={project.project_id}
                        className="bg-white dark:bg-stone-900"
                      >
                        <td className="px-3 py-2 font-semibold text-stone-900 dark:text-stone-100">
                          {project.project_id}
                        </td>
                        <td className="px-3 py-2">
                          {isEditing ? (
                            <Input
                              value={editing?.draft.project_name ?? ""}
                              onChange={(e) =>
                                setEditing((prev) =>
                                  prev
                                    ? {
                                        ...prev,
                                        draft: {
                                          ...prev.draft,
                                          project_name: e.target.value,
                                        },
                                      }
                                    : prev,
                                )
                              }
                            />
                          ) : (
                            <div>
                              <div className="font-medium text-stone-900 dark:text-stone-100">
                                {project.project_name}
                              </div>
                              {project.url && (
                                <a
                                  href={project.url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="text-xs text-emerald-600 dark:text-emerald-400 hover:underline"
                                >
                                  {project.url}
                                </a>
                              )}
                            </div>
                          )}
                        </td>
                        <td className="px-3 py-2 hidden md:table-cell max-w-xs">
                          {isEditing ? (
                            <Input
                              value={editing?.draft.description ?? ""}
                              onChange={(e) =>
                                setEditing((prev) =>
                                  prev
                                    ? {
                                        ...prev,
                                        draft: {
                                          ...prev.draft,
                                          description: e.target.value,
                                        },
                                      }
                                    : prev,
                                )
                              }
                            />
                          ) : (
                            <span
                              className="text-stone-600 dark:text-stone-400 truncate block"
                              title={project.description ?? ""}
                            >
                              {project.description ?? "—"}
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-center">
                          {isEditing ? (
                            <Checkbox
                              checked={editing?.draft.is_active ?? false}
                              onChange={(e: ChangeEvent<HTMLInputElement>) =>
                                setEditing((prev) =>
                                  prev
                                    ? {
                                        ...prev,
                                        draft: {
                                          ...prev.draft,
                                          is_active: e.target.checked,
                                        },
                                      }
                                    : prev,
                                )
                              }
                            />
                          ) : (
                            <span
                              className={`inline-flex items-center rounded-full px-2 py-1 text-xs font-medium ${
                                project.is_active
                                  ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300"
                                  : "bg-stone-100 text-stone-600 dark:bg-stone-800 dark:text-stone-400"
                              }`}
                            >
                              {project.is_active ? "Active" : "Inactive"}
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2 hidden lg:table-cell">
                          <div className="text-stone-600 dark:text-stone-400">
                            {project.memberships?.length ?? 0} member(s)
                          </div>
                        </td>
                        <td className="px-3 py-2 hidden lg:table-cell text-stone-500 dark:text-stone-400">
                          {project.created_on.toLocaleString()}
                        </td>
                        <td className="px-3 py-2">
                          <div className="flex justify-end gap-2">
                            {isEditing ? (
                              <>
                                <Button
                                  mode="text"
                                  variant="secondary"
                                  onClick={cancelEdit}
                                >
                                  Cancel
                                </Button>
                                <Button
                                  mode="text"
                                  variant="primary"
                                  onClick={commitEdit}
                                  disabled={update.isPending}
                                >
                                  Save
                                </Button>
                              </>
                            ) : (
                              <>
                                <Button
                                  mode="text"
                                  variant="secondary"
                                  onClick={() => startEdit(project)}
                                >
                                  Edit
                                </Button>
                                <Button
                                  mode="text"
                                  variant="danger"
                                  onClick={() =>
                                    handleDelete(
                                      project.project_id,
                                      project.project_name,
                                    )
                                  }
                                  disabled={remove.isPending}
                                >
                                  Delete
                                </Button>
                              </>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-stone-500 dark:text-stone-400">
              No projects registered yet.
            </p>
          )}
        </div>
      </Card>
    </div>
  );
}
