import { useCallback, useMemo, useState } from "react";
import { X } from "lucide-react";

import type { SimpleUser } from "@/lib/types";
import Checkbox from "./Checkbox";
import Input from "./Input";

interface UserMultiSelectProps {
  users: SimpleUser[];
  selectedUserIds: string[];
  onChange: (userIds: string[]) => void;
  placeholder?: string;
  isLoading?: boolean;
}

export default function UserMultiSelect({
  users,
  selectedUserIds,
  onChange,
  placeholder = "Search users...",
  isLoading = false,
}: UserMultiSelectProps) {
  const [searchTerm, setSearchTerm] = useState("");
  const [isOpen, setIsOpen] = useState(false);

  const filteredUsers = useMemo(() => {
    if (!searchTerm.trim()) return users;
    const normalized = searchTerm.toLowerCase();
    return users.filter(
      (user) =>
        user.username.toLowerCase().includes(normalized) ||
        user.name?.toLowerCase().includes(normalized) ||
        user.email?.toLowerCase().includes(normalized),
    );
  }, [users, searchTerm]);

  const selectedUsers = useMemo(
    () => users.filter((user) => selectedUserIds.includes(user.id)),
    [users, selectedUserIds],
  );

  const handleToggleUser = useCallback(
    (userId: string) => {
      if (selectedUserIds.includes(userId)) {
        onChange(selectedUserIds.filter((id) => id !== userId));
      } else {
        onChange([...selectedUserIds, userId]);
      }
    },
    [selectedUserIds, onChange],
  );

  const handleRemoveUser = useCallback(
    (userId: string) => {
      onChange(selectedUserIds.filter((id) => id !== userId));
    },
    [selectedUserIds, onChange],
  );

  return (
    <div className="relative">
      {/* Selected users display */}
      {selectedUsers.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-2">
          {selectedUsers.map((user) => (
            <div
              key={user.id}
              className="inline-flex items-center gap-1 rounded-md bg-amber-100 dark:bg-amber-900 px-2 py-1 text-sm text-stone-900 dark:text-stone-100"
            >
              <span>{user.username}</span>
              <button
                type="button"
                onClick={() => handleRemoveUser(user.id)}
                className="rounded hover:bg-amber-200 dark:hover:bg-amber-800 p-0.5"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Search input */}
      <div className="relative">
        <Input
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          onFocus={() => setIsOpen(true)}
          placeholder={placeholder}
          disabled={isLoading}
        />

        {/* Dropdown list */}
        {isOpen && (
          <>
            {/* Backdrop */}
            <div
              className="fixed inset-0 z-10"
              onClick={() => setIsOpen(false)}
            />

            {/* Dropdown */}
            <div className="absolute z-20 mt-1 w-full max-h-60 overflow-auto rounded-md border border-stone-300 dark:border-stone-700 bg-white dark:bg-stone-900 shadow-lg">
              {isLoading ? (
                <div className="px-3 py-2 text-sm text-stone-500">
                  Loading users...
                </div>
              ) : filteredUsers.length === 0 ? (
                <div className="px-3 py-2 text-sm text-stone-500">
                  {searchTerm.trim()
                    ? "No users match your search."
                    : "No users available."}
                </div>
              ) : (
                <div className="py-1">
                  {filteredUsers.map((user) => {
                    const isSelected = selectedUserIds.includes(user.id);
                    return (
                      <label
                        key={user.id}
                        className="flex items-center gap-2 px-3 py-2 hover:bg-stone-100 dark:hover:bg-stone-800 cursor-pointer"
                      >
                        <Checkbox
                          checked={isSelected}
                          onChange={() => handleToggleUser(user.id)}
                        />
                        <div className="flex-1 min-w-0">
                          <div className="font-medium text-stone-900 dark:text-stone-100">
                            {user.username}
                          </div>
                          {user.name && (
                            <div className="text-xs text-stone-500 dark:text-stone-400 truncate">
                              {user.name}
                            </div>
                          )}
                          {user.email && (
                            <div className="text-xs text-stone-500 dark:text-stone-400 truncate">
                              {user.email}
                            </div>
                          )}
                        </div>
                      </label>
                    );
                  })}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
