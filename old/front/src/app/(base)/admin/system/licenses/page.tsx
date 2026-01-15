"use client";

import { useCallback, useMemo, useState } from "react";

import useActiveUser from "@/app/hooks/api/useActiveUser";
import { useMetadataLicenses } from "@/app/hooks/api/useMetadata";

import { Group, Input } from "@/lib/components/inputs";
import Card from "@/lib/components/ui/Card";
import Button from "@/lib/components/ui/Button";
import Spinner from "@/lib/components/ui/Spinner";
import { textOrUndefined } from "@/lib/utils/forms";

type LicenseFormState = {
  license_id: string;
  license_name: string;
  license_link: string;
};

const INITIAL_STATE: LicenseFormState = {
  license_id: "",
  license_name: "",
  license_link: "",
};

export default function LicensesPage() {
  const [searchTerm, setSearchTerm] = useState("");
  const [formState, setFormState] =
    useState<LicenseFormState>(INITIAL_STATE);
  const [editing, setEditing] = useState<
    { id: string; draft: LicenseFormState } | undefined
  >(undefined);

  const { data: activeUser } = useActiveUser();
  const canManage = activeUser?.is_superuser ?? false;

  const query = useMemo(
    () => ({
      search: textOrUndefined(searchTerm),
    }),
    [searchTerm],
  );

  const { query: licensesQuery, create, update, remove } =
    useMetadataLicenses(query);
  const {
    data: licenses,
    isLoading,
    isError,
  } = licensesQuery;

  const resetForm = () => setFormState(INITIAL_STATE);

  const handleCreate = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!canManage) return;
      if (!formState.license_id.trim() || !formState.license_name.trim()) {
        return;
      }
      await create.mutateAsync({
        license_id: formState.license_id.trim(),
        license_name: formState.license_name.trim(),
        license_link: formState.license_link.trim(),
      });
      resetForm();
    },
    [canManage, create, formState],
  );

  const startEdit = (license: LicenseFormState) => {
    if (!canManage) return;
    setEditing({
      id: license.license_id,
      draft: { ...license },
    });
  };

  const commitEdit = async () => {
    if (!editing || !canManage) {
      return;
    }
    await update.mutateAsync({
      id: editing.id,
      payload: {
        license_name:
          textOrUndefined(editing.draft.license_name) ??
          editing.draft.license_name.trim(),
        license_link: textOrUndefined(editing.draft.license_link),
      },
    });
    setEditing(undefined);
  };

  const cancelEdit = () => setEditing(undefined);

  const handleDelete = async (id: string) => {
    if (!canManage) return;
    if (!confirm(`ライセンス ${id} を削除します。よろしいですか?`)) {
      return;
    }
    await remove.mutateAsync(id);
  };

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <form className="grid gap-4 md:grid-cols-3" onSubmit={handleCreate}>
          <Group label="License ID" name="license_id">
            <Input
              value={formState.license_id}
              onChange={(event) =>
                setFormState((prev) => ({
                  ...prev,
                  license_id: event.target.value,
                }))
              }
              placeholder="CCBY4"
              required
            />
          </Group>
          <Group label="License name" name="license_name">
            <Input
              value={formState.license_name}
              onChange={(event) =>
                setFormState((prev) => ({
                  ...prev,
                  license_name: event.target.value,
                }))
              }
              placeholder="Creative Commons Attribution 4.0 International"
              required
            />
          </Group>
          <Group label="License URL" name="license_link">
            <Input
              value={formState.license_link}
              onChange={(event) =>
                setFormState((prev) => ({
                  ...prev,
                  license_link: event.target.value,
                }))
              }
              placeholder="https://creativecommons.org/licenses/by/4.0/"
            />
          </Group>
          <div className="md:col-span-3 flex justify-end gap-2">
            <Button mode="text" variant="secondary" onClick={resetForm}>
              リセット
            </Button>
            <Button
              type="submit"
              variant="primary"
              disabled={create.isPending}
            >
              {create.isPending ? "登録中..." : "ライセンスを追加"}
            </Button>
          </div>
        </form>
      </Card>

      <Card>
        <div className="flex flex-col gap-4">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-stone-900 dark:text-stone-100">
                登録済みライセンス
              </h2>
              <p className="text-sm text-stone-500 dark:text-stone-400">
                データセットの利用条件として選択できます。
              </p>
            </div>
            <Input
              value={searchTerm}
              onChange={(event) => setSearchTerm(event.target.value)}
              placeholder="ID・名称で検索"
              className="sm:w-72"
            />
          </div>

          {isError ? (
            <p className="text-sm text-red-600 dark:text-red-400">
              ライセンス一覧の取得に失敗しました。
            </p>
          ) : null}

          {isLoading ? (
            <div className="flex justify-center py-12">
              <Spinner />
            </div>
          ) : licenses && licenses.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-stone-200 dark:divide-stone-800 text-sm">
                <thead className="bg-stone-100 dark:bg-stone-800">
                  <tr>
                    <th className="px-3 py-2 text-left font-semibold">
                      ID
                    </th>
                    <th className="px-3 py-2 text-left font-semibold">
                      名称
                    </th>
                    <th className="px-3 py-2 text-left font-semibold">
                      URL
                    </th>
                    <th className="px-3 py-2 text-left font-semibold hidden md:table-cell">
                      使用中のデータセット
                    </th>
                    <th className="px-3 py-2 text-left font-semibold">
                      作成日時
                    </th>
                    <th className="px-3 py-2 text-right font-semibold">
                      操作
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-stone-200 dark:divide-stone-800">
                  {licenses.map((license) => {
                    const isEditing = canManage && editing?.id === license.license_id;
                    return (
                      <tr
                        key={license.license_id}
                        className="bg-white dark:bg-stone-900"
                      >
                        <td className="px-3 py-2 font-semibold text-stone-900 dark:text-stone-100">
                          {license.license_id}
                        </td>
                        <td className="px-3 py-2">
                          {isEditing ? (
                            <Input
                              value={editing?.draft.license_name ?? ""}
                              onChange={(event) =>
                                setEditing((prev) =>
                                  prev
                                    ? {
                                        ...prev,
                                        draft: {
                                          ...prev.draft,
                                          license_name: event.target.value,
                                        },
                                      }
                                    : prev,
                                )
                              }
                            />
                          ) : (
                            license.license_name
                          )}
                        </td>
                        <td className="px-3 py-2">
                          {isEditing ? (
                            <Input
                              value={editing?.draft.license_link ?? ""}
                              onChange={(event) =>
                                setEditing((prev) =>
                                  prev
                                    ? {
                                        ...prev,
                                        draft: {
                                          ...prev.draft,
                                          license_link: event.target.value,
                                        },
                                      }
                                    : prev,
                                )
                              }
                            />
                          ) : license.license_link ? (
                            <a
                              href={license.license_link}
                              target="_blank"
                              rel="noreferrer"
                              className="text-emerald-600 dark:text-emerald-300 underline"
                            >
                              {license.license_link}
                            </a>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td className="px-3 py-2 hidden md:table-cell">
                          {license.usage_count ?? 0}
                        </td>
                        <td className="px-3 py-2 text-stone-500 dark:text-stone-400">
                          {license.created_on.toLocaleString()}
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
                                  キャンセル
                                </Button>
                                <Button
                                  mode="text"
                                  variant="primary"
                                  onClick={() => void commitEdit()}
                                  disabled={update.isPending}
                                >
                                  保存
                                </Button>
                              </>
                            ) : (
                              <>
                                <Button
                                  mode="text"
                                  variant="secondary"
                                  onClick={() =>
                                    startEdit({
                                      license_id: license.license_id,
                                      license_name: license.license_name,
                                      license_link: license.license_link ?? "",
                                    })
                                  }
                                >
                                  編集
                                </Button>
                                <Button
                                  mode="text"
                                  variant="danger"
                                  onClick={() =>
                                    handleDelete(license.license_id)
                                  }
                                  disabled={
                                    remove.isPending ||
                                    (license.usage_count ?? 0) > 0
                                  }
                                >
                                  削除
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
              登録済みのライセンスがありません。
            </p>
          )}
        </div>
      </Card>
    </div>
  );
}
