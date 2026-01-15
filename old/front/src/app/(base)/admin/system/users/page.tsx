"use client";

import { useMemo } from "react";

import useAdminUsers from "@/app/hooks/api/useAdminUsers";

import AdminUserCreateForm from "@/lib/components/users/AdminUserCreateForm";
import Card from "@/lib/components/ui/Card";
import Button from "@/lib/components/ui/Button";
import Spinner from "@/lib/components/ui/Spinner";

import type { AdminUserUpdate, SimpleUser } from "@/lib/types";

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
          User Accounts
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

export default function UsersPage() {
  const usersHook = useAdminUsers({ enabled: true });
  const users = useMemo(() => usersHook.data ?? [], [usersHook.data]);

  const handleToggle = (id: string, data: AdminUserUpdate) => {
    usersHook.update.mutate({ id, data });
  };

  return (
    <div className="space-y-6">
      <UsersSection
        users={users}
        isLoading={usersHook.isLoading}
        onCreate={() => usersHook.refetch()}
        onToggleAdmin={(id, value) => handleToggle(id, { is_superuser: value })}
        onToggleActive={(id, value) => handleToggle(id, { is_active: value })}
        onRemove={(id) => usersHook.remove.mutate(id)}
      />
    </div>
  );
}
