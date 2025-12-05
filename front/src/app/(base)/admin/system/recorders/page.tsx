"use client";

import { useCallback, useMemo, useState } from "react";

import useActiveUser from "@/app/hooks/api/useActiveUser";
import { useMetadataRecorders } from "@/app/hooks/api/useMetadata";

import { Group, Input } from "@/lib/components/inputs";
import Card from "@/lib/components/ui/Card";
import Button from "@/lib/components/ui/Button";
import Spinner from "@/lib/components/ui/Spinner";
import type { Recorder } from "@/lib/types";
import { textOrUndefined } from "@/lib/utils/forms";

type RecorderFormState = {
  recorder_id: string;
  recorder_name: string;
  manufacturer: string;
  version: string;
};

const INITIAL_FORM_STATE: RecorderFormState = {
  recorder_id: "",
  recorder_name: "",
  manufacturer: "",
  version: "",
};

export default function RecordersPage() {
  const [searchTerm, setSearchTerm] = useState("");
  const [formState, setFormState] =
    useState<RecorderFormState>(INITIAL_FORM_STATE);
  const [editing, setEditing] = useState<
    { id: string; draft: RecorderFormState } | undefined
  >(undefined);

  const { data: activeUser } = useActiveUser();
  const canManage = activeUser?.is_superuser ?? false;

  const query = useMemo(
    () => ({
      search: textOrUndefined(searchTerm),
    }),
    [searchTerm],
  );

  const { query: recordersQuery, create, update, remove } =
    useMetadataRecorders(query);
  const {
    data: recorders,
    isLoading,
    isError,
  } = recordersQuery;

  const handleCreate = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!canManage) return;
      if (!formState.recorder_id.trim() || !formState.recorder_name.trim()) {
        return;
      }

      await create.mutateAsync({
        recorder_id: formState.recorder_id.trim(),
        recorder_name: formState.recorder_name.trim(),
        manufacturer: textOrUndefined(formState.manufacturer),
        version: textOrUndefined(formState.version),
      });
      setFormState(INITIAL_FORM_STATE);
    },
    [canManage, create, formState],
  );

  const startEdit = (recorder: Recorder) => {
    if (!canManage) return;
    setEditing({
      id: recorder.recorder_id,
      draft: {
        recorder_id: recorder.recorder_id,
        recorder_name: recorder.recorder_name,
        manufacturer: recorder.manufacturer ?? "",
        version: recorder.version ?? "",
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
        recorder_name: textOrUndefined(editing.draft.recorder_name) ??
          editing.draft.recorder_name.trim(),
        manufacturer: textOrUndefined(editing.draft.manufacturer),
        version: textOrUndefined(editing.draft.version),
      },
    });
    setEditing(undefined);
  };

  const cancelEdit = () => setEditing(undefined);

  const handleDelete = async (id: string) => {
    if (!canManage) return;
    if (
      !confirm(
        `レコーダー ${id} を削除します。データセットの参照が失われる場合があります。実行しますか?`,
      )
    ) {
      return;
    }
    await remove.mutateAsync(id);
  };

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <form className="grid gap-4 sm:grid-cols-2" onSubmit={handleCreate}>
          <Group label="Recorder ID" name="recorder_id">
            <Input
              value={formState.recorder_id}
              onChange={(event) =>
                setFormState((prev) => ({
                  ...prev,
                  recorder_id: event.target.value,
                }))
              }
              placeholder="sm4"
              required
            />
          </Group>
          <Group label="Recorder Name" name="recorder_name">
            <Input
              value={formState.recorder_name}
              onChange={(event) =>
                setFormState((prev) => ({
                  ...prev,
                  recorder_name: event.target.value,
                }))
              }
              placeholder="Song Meter SM4"
              required
            />
          </Group>
          <Group label="Manufacturer" name="manufacturer">
            <Input
              value={formState.manufacturer}
              onChange={(event) =>
                setFormState((prev) => ({
                  ...prev,
                  manufacturer: event.target.value,
                }))
              }
              placeholder="Wildlife Acoustics"
            />
          </Group>
          <Group label="Version" name="version">
            <Input
              value={formState.version}
              onChange={(event) =>
                setFormState((prev) => ({
                  ...prev,
                  version: event.target.value,
                }))
              }
              placeholder="1.2.0"
            />
          </Group>
          <div className="sm:col-span-2 flex justify-end gap-2">
            <Button
              type="reset"
              mode="text"
              variant="secondary"
              onClick={() => setFormState(INITIAL_FORM_STATE)}
            >
              リセット
            </Button>
            <Button
              type="submit"
              variant="primary"
              disabled={create.isPending}
            >
              {create.isPending ? "追加中..." : "レコーダーを追加"}
            </Button>
          </div>
        </form>
      </Card>

      <Card>
        <div className="flex flex-col gap-4">
          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-stone-900 dark:text-stone-100">
                登録済みレコーダー
              </h2>
              <p className="text-sm text-stone-500 dark:text-stone-400">
                データセット作成時の選択肢として利用されます。
              </p>
            </div>
            <Input
              value={searchTerm}
              onChange={(event) => setSearchTerm(event.target.value)}
              placeholder="IDまたは名称で検索"
              className="md:w-72"
            />
          </div>

          {isError ? (
            <p className="text-sm text-red-600 dark:text-red-400">
              レコーダー一覧の取得に失敗しました。
            </p>
          ) : null}

          {isLoading ? (
            <div className="flex justify-center py-12">
              <Spinner />
            </div>
          ) : recorders && recorders.length > 0 ? (
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
                      メーカー
                    </th>
                    <th className="px-3 py-2 text-left font-semibold">
                      バージョン
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
                  {recorders.map((recorder) => {
                    const isEditing = canManage && editing?.id === recorder.recorder_id;
                    return (
                      <tr
                        key={recorder.recorder_id}
                        className="bg-white dark:bg-stone-900"
                      >
                        <td className="px-3 py-2 font-semibold text-stone-900 dark:text-stone-100">
                          {recorder.recorder_id}
                        </td>
                        <td className="px-3 py-2">
                          {isEditing ? (
                            <Input
                              value={editing?.draft.recorder_name ?? ""}
                              onChange={(event) =>
                                setEditing((prev) =>
                                  prev
                                    ? {
                                        ...prev,
                                        draft: {
                                          ...prev.draft,
                                          recorder_name: event.target.value,
                                        },
                                      }
                                    : prev,
                                )
                              }
                            />
                          ) : (
                            recorder.recorder_name
                          )}
                        </td>
                        <td className="px-3 py-2">
                          {isEditing ? (
                            <Input
                              value={editing?.draft.manufacturer ?? ""}
                              onChange={(event) =>
                                setEditing((prev) =>
                                  prev
                                    ? {
                                        ...prev,
                                        draft: {
                                          ...prev.draft,
                                          manufacturer: event.target.value,
                                        },
                                      }
                                    : prev,
                                )
                              }
                            />
                          ) : (
                            recorder.manufacturer ?? "—"
                          )}
                        </td>
                        <td className="px-3 py-2">
                          {isEditing ? (
                            <Input
                              value={editing?.draft.version ?? ""}
                              onChange={(event) =>
                                setEditing((prev) =>
                                  prev
                                    ? {
                                        ...prev,
                                        draft: {
                                          ...prev.draft,
                                          version: event.target.value,
                                        },
                                      }
                                    : prev,
                                )
                              }
                            />
                          ) : (
                            recorder.version ?? "—"
                          )}
                        </td>
                        <td className="px-3 py-2 hidden md:table-cell">
                          {recorder.usage_count ?? 0}
                        </td>
                        <td className="px-3 py-2 text-stone-500 dark:text-stone-400">
                          {recorder.created_on.toLocaleString()}
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
                                  onClick={commitEdit}
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
                                  onClick={() => startEdit(recorder)}
                                >
                                  編集
                                </Button>
                                <Button
                                  mode="text"
                                  variant="danger"
                                  onClick={() =>
                                    handleDelete(recorder.recorder_id)
                                  }
                                  disabled={
                                    remove.isPending ||
                                    (recorder.usage_count ?? 0) > 0
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
              登録済みのレコーダーがありません。
            </p>
          )}
        </div>
      </Card>
    </div>
  );
}
