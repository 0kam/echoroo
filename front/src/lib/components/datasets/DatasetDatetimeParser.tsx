"use client";

import { useCallback, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import api from "@/app/api";
import { DateTimePatternBuilder } from "@/lib/components/datetime";
import { Group, Input } from "@/lib/components/inputs";
import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import { DialogOverlay as Dialog } from "@/lib/components/ui/Dialog";
import Spinner from "@/lib/components/ui/Spinner";
import type { Dataset, DatetimePatternType } from "@/lib/types";

export default function DatasetDatetimeParser({
  dataset,
}: {
  dataset: Dataset;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [patternType, setPatternType] = useState<DatetimePatternType>("strptime");
  const [pattern, setPattern] = useState("");
  const [sampleFilename, setSampleFilename] = useState("");
  const [useVisualBuilder, setUseVisualBuilder] = useState(true);

  const queryClient = useQueryClient();

  // Fetch status
  const { data: status, isLoading: statusLoading } = useQuery({
    queryKey: ["datetime-parse-status", dataset.uuid],
    queryFn: () => api.datasets.getDatetimeParseStatus(dataset.uuid),
    enabled: isOpen,
  });

  // Fetch sample filenames from the dataset
  const { data: sampleFilenames } = useQuery({
    queryKey: ["dataset-filename-samples", dataset.uuid],
    queryFn: () => api.datasets.getFilenameSamples(dataset.uuid, 1),
    enabled: isOpen && useVisualBuilder,
  });

  // Get sample filename from first recording
  const sampleFilenameFromDataset = useMemo(() => {
    if (!sampleFilenames || sampleFilenames.length === 0) return null;
    return sampleFilenames[0];
  }, [sampleFilenames]);

  // Use the visual builder's filename or manual input
  const effectiveFilename = sampleFilename || sampleFilenameFromDataset || "";

  // Handle pattern change from visual builder
  const handlePatternChange = useCallback(
    (newPattern: string, newPatternType: "strptime" | "regex") => {
      setPattern(newPattern);
      setPatternType(newPatternType as DatetimePatternType);
    },
    [],
  );

  // Save pattern mutation
  const {
    mutateAsync: savePattern,
    isPending: isSavingPattern,
    isError: isPatternError,
    error: patternError,
    isSuccess: isPatternSuccess,
    reset: resetPatternMutation,
  } = useMutation({
    mutationFn: () =>
      api.datasets.setDatetimePattern(dataset.uuid, {
        pattern_type: patternType,
        pattern,
        sample_filename: effectiveFilename || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["datetime-parse-status", dataset.uuid],
      });
    },
  });

  // Parse dataset mutation
  const {
    mutateAsync: parseDataset,
    isPending: isParsing,
    isError: isParseError,
    error: parseError,
    isSuccess: isParseSuccess,
    data: parseResult,
  } = useMutation({
    mutationFn: () => api.datasets.parseDatetime(dataset.uuid),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["datetime-parse-status", dataset.uuid],
      });
    },
  });

  const handleSetPattern = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!pattern.trim()) return;
      await savePattern();
    },
    [pattern, savePattern],
  );

  const handleParse = useCallback(async () => {
    if (!confirm("全てのレコーディングのdatetimeをパースします。実行しますか？")) {
      return;
    }
    await parseDataset();
  }, [parseDataset]);

  // Reset when opening dialog
  const handleOpen = useCallback(() => {
    setIsOpen(true);
    resetPatternMutation();
  }, [resetPatternMutation]);

  return (
    <>
      <Button mode="text" variant="primary" onClick={handleOpen}>
        Datetime パース設定
      </Button>

      <Dialog
        isOpen={isOpen}
        onClose={() => setIsOpen(false)}
        title="Datetime パース設定"
      >
        <div className="flex flex-col gap-6 min-w-[600px]">
          {/* Current Status */}
          <Card>
            <div className="flex flex-col gap-3">
              <h3 className="text-sm font-semibold text-stone-900 dark:text-stone-100">
                現在のパース状況
              </h3>
              {statusLoading ? (
                <div className="flex justify-center py-4">
                  <Spinner />
                </div>
              ) : status ? (
                <div className="grid grid-cols-3 gap-4 text-sm">
                  <div className="flex flex-col gap-1">
                    <span className="text-stone-500 dark:text-stone-400">
                      未処理
                    </span>
                    <span className="text-lg font-semibold text-stone-900 dark:text-stone-100">
                      {status.pending}
                    </span>
                  </div>
                  <div className="flex flex-col gap-1">
                    <span className="text-stone-500 dark:text-stone-400">
                      成功
                    </span>
                    <span className="text-lg font-semibold text-emerald-600 dark:text-emerald-400">
                      {status.success}
                    </span>
                  </div>
                  <div className="flex flex-col gap-1">
                    <span className="text-stone-500 dark:text-stone-400">
                      失敗
                    </span>
                    <span className="text-lg font-semibold text-red-600 dark:text-red-400">
                      {status.failed}
                    </span>
                  </div>
                </div>
              ) : null}
            </div>
          </Card>

          {/* Pattern Configuration */}
          <Card>
            <div className="flex flex-col gap-4">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-stone-900 dark:text-stone-100">
                  パターン設定
                </h3>
                <button
                  type="button"
                  onClick={() => setUseVisualBuilder(!useVisualBuilder)}
                  className="text-xs text-emerald-600 dark:text-emerald-400 hover:underline"
                >
                  {useVisualBuilder ? "手動入力に切り替え" : "ビジュアルビルダーに切り替え"}
                </button>
              </div>

              {useVisualBuilder ? (
                // Visual Pattern Builder
                effectiveFilename ? (
                  <DateTimePatternBuilder
                    filename={effectiveFilename}
                    onPatternChange={handlePatternChange}
                  />
                ) : (
                  <div className="py-8 text-center">
                    <Spinner />
                    <p className="text-sm text-stone-500 dark:text-stone-400 mt-2">
                      サンプルファイル名を取得中...
                    </p>
                  </div>
                )
              ) : (
                // Manual Input
                <form onSubmit={handleSetPattern} className="flex flex-col gap-4">
                  <Group label="Pattern" name="pattern">
                    <Input
                      value={pattern}
                      onChange={(e) => setPattern(e.target.value)}
                      placeholder="%Y%m%d_%H%M%S"
                      required
                    />
                  </Group>

                  <Group label="Sample Filename (optional)" name="sample_filename">
                    <Input
                      value={sampleFilename}
                      onChange={(e) => setSampleFilename(e.target.value)}
                      placeholder="20240101_120000.wav"
                    />
                  </Group>
                </form>
              )}

              {/* Save Pattern Button */}
              <div className="flex justify-end gap-2 pt-2 border-t border-stone-200 dark:border-stone-700">
                <Button
                  type="button"
                  mode="text"
                  variant="secondary"
                  onClick={() => setIsOpen(false)}
                >
                  キャンセル
                </Button>
                <Button
                  type="button"
                  variant="primary"
                  disabled={isSavingPattern || !pattern.trim()}
                  onClick={() => savePattern()}
                >
                  {isSavingPattern ? "設定中..." : "パターンを保存"}
                </Button>
              </div>

              {isPatternError && (
                <p className="text-sm text-red-600 dark:text-red-400">
                  パターン設定に失敗しました: {patternError?.message}
                </p>
              )}
              {isPatternSuccess && (
                <p className="text-sm text-emerald-600 dark:text-emerald-400">
                  パターンを保存しました
                </p>
              )}
            </div>
          </Card>

          {/* Parse Action */}
          <Card>
            <div className="flex flex-col gap-4">
              <div>
                <h3 className="text-sm font-semibold text-stone-900 dark:text-stone-100">
                  パース実行
                </h3>
                <p className="text-sm text-stone-500 dark:text-stone-400 mt-1">
                  保存したパターンで全レコーディングのdatetimeをパースします。
                </p>
              </div>

              <div className="flex justify-end">
                <Button
                  variant="primary"
                  onClick={handleParse}
                  disabled={isParsing}
                >
                  {isParsing ? "パース中..." : "パースを実行"}
                </Button>
              </div>

              {isParseError && (
                <p className="text-sm text-red-600 dark:text-red-400">
                  パース実行に失敗しました: {parseError?.message}
                </p>
              )}
              {isParseSuccess && parseResult && (
                <div className="text-sm">
                  <p className="text-emerald-600 dark:text-emerald-400">
                    パースが完了しました
                  </p>
                  <p className="text-stone-600 dark:text-stone-400 mt-1">
                    合計: {parseResult.total} / 成功: {parseResult.success} /
                    失敗: {parseResult.failure}
                  </p>
                </div>
              )}
            </div>
          </Card>
        </div>
      </Dialog>
    </>
  );
}
