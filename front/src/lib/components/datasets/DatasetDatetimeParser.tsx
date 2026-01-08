"use client";

import { useCallback, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import api from "@/app/api";
import { Select } from "@/lib/components/inputs";
import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import { DialogOverlay as Dialog } from "@/lib/components/ui/Dialog";
import Spinner from "@/lib/components/ui/Spinner";
import type { Dataset } from "@/lib/types";
import DatetimeStringSelector from "./DatetimeStringSelector";
import { generateStrptimePattern, validateDatetimeSelections } from "@/lib/utils/datetime";

type DatetimeComponent = "year" | "month" | "day" | "hour" | "minute" | "second";

interface Selection {
  start: number;
  end: number;
  component: DatetimeComponent;
}

export default function DatasetDatetimeParserNew({
  dataset,
}: {
  dataset: Dataset;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [selectedFilename, setSelectedFilename] = useState<string | null>(null);
  const [selections, setSelections] = useState<
    Partial<Record<DatetimeComponent, Selection>>
  >({});
  const [generatedPattern, setGeneratedPattern] = useState<string>("");

  const queryClient = useQueryClient();

  // Fetch filename samples
  const { data: filenameSamples, isLoading: samplesLoading } = useQuery({
    queryKey: ["filename-samples", dataset.uuid],
    queryFn: () => api.datasets.getFilenameSamples(dataset.uuid, 20),
    enabled: isOpen,
  });

  // Fetch parse status
  const { data: status, isLoading: statusLoading } = useQuery({
    queryKey: ["datetime-parse-status", dataset.uuid],
    queryFn: () => api.datasets.getDatetimeParseStatus(dataset.uuid),
    enabled: isOpen,
  });

  // Save pattern mutation
  const {
    mutateAsync: savePattern,
    isPending: isSavingPattern,
    isError: isPatternError,
    error: patternError,
    isSuccess: isPatternSuccess,
  } = useMutation({
    mutationFn: () =>
      api.datasets.setDatetimePattern(dataset.uuid, {
        pattern_type: "strptime",
        pattern: generatedPattern,
        sample_filename: selectedFilename || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["datetime-parse-status", dataset.uuid],
      });
    },
  });

  // Parse datetime mutation
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

  const handleFilenameSelect = useCallback((filename: string) => {
    setSelectedFilename(filename);
    setSelections({});
    setGeneratedPattern("");
  }, []);

  const handleSelectionsChange = useCallback(
    (newSelections: Record<DatetimeComponent, Selection>) => {
      setSelections(newSelections);

      if (
        selectedFilename &&
        validateDatetimeSelections(newSelections)
      ) {
        const pattern = generateStrptimePattern(selectedFilename, newSelections);
        setGeneratedPattern(pattern);
      }
    },
    [selectedFilename]
  );

  const handleSavePattern = useCallback(async () => {
    if (!generatedPattern) return;
    await savePattern();
  }, [generatedPattern, savePattern]);

  const handleParse = useCallback(async () => {
    await parseDataset();
  }, [parseDataset]);

  const handleReset = useCallback(() => {
    setSelectedFilename(null);
    setSelections({});
    setGeneratedPattern("");
  }, []);

  return (
    <>
      <Button mode="text" variant="primary" onClick={() => setIsOpen(true)}>
        Datetime パース設定
      </Button>

      <Dialog
        isOpen={isOpen}
        onClose={() => setIsOpen(false)}
        title="Datetime パース設定"
      >
        <div className="flex flex-col gap-6">
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

          {/* Step 1: Select Filename */}
          <Card>
            <div className="flex flex-col gap-4">
              <h3 className="text-sm font-semibold text-stone-900 dark:text-stone-100">
                1. サンプルファイル名を選択
              </h3>
              {samplesLoading ? (
                <div className="flex justify-center py-4">
                  <Spinner />
                </div>
              ) : filenameSamples && filenameSamples.length > 0 ? (
                <div className="flex flex-col gap-2">
                  <Select
                    options={[
                      {
                        id: "__placeholder__",
                        label: "ファイル名を選択してください",
                        value: "",
                        disabled: true,
                      },
                      ...filenameSamples.map((filename) => ({
                        id: filename,
                        label: filename,
                        value: filename,
                      })),
                    ]}
                    selected={
                      selectedFilename
                        ? {
                            id: selectedFilename,
                            label: selectedFilename,
                            value: selectedFilename,
                          }
                        : {
                            id: "__placeholder__",
                            label: "ファイル名を選択してください",
                            value: "",
                            disabled: true,
                          }
                    }
                    onChange={handleFilenameSelect}
                  />
                </div>
              ) : (
                <p className="text-sm text-stone-500 dark:text-stone-400">
                  このデータセットにはレコーディングがありません
                </p>
              )}
            </div>
          </Card>

          {/* Step 2: Select datetime components */}
          {selectedFilename && (
            <Card>
              <div className="flex flex-col gap-4">
                <h3 className="text-sm font-semibold text-stone-900 dark:text-stone-100">
                  2. 日時に対応する部分を選択
                </h3>
                <DatetimeStringSelector
                  filename={selectedFilename}
                  onSelectionsChange={handleSelectionsChange}
                />
              </div>
            </Card>
          )}

          {/* Step 3: Generated pattern */}
          {generatedPattern && (
            <Card>
              <div className="flex flex-col gap-4">
                <h3 className="text-sm font-semibold text-stone-900 dark:text-stone-100">
                  3. 生成されたパターン
                </h3>
                <div className="p-3 bg-stone-50 dark:bg-stone-900 rounded border border-stone-300 dark:border-stone-700">
                  <code className="text-sm font-mono text-stone-900 dark:text-stone-100">
                    {generatedPattern}
                  </code>
                </div>
                <div className="flex justify-end gap-2">
                  <Button
                    mode="text"
                    variant="secondary"
                    onClick={handleReset}
                  >
                    やり直す
                  </Button>
                  <Button
                    variant="primary"
                    onClick={handleSavePattern}
                    disabled={isSavingPattern}
                  >
                    {isSavingPattern ? "設定中..." : "パターンを設定"}
                  </Button>
                </div>
                {isPatternError && (
                  <p className="text-sm text-red-600 dark:text-red-400">
                    パターン設定に失敗しました:{" "}
                    {patternError?.message}
                  </p>
                )}
                {isPatternSuccess && (
                  <p className="text-sm text-emerald-600 dark:text-emerald-400">
                    パターンを設定しました
                  </p>
                )}
              </div>
            </Card>
          )}

          {/* Parse Action */}
          <Card>
            <div className="flex flex-col gap-4">
              <div>
                <h3 className="text-sm font-semibold text-stone-900 dark:text-stone-100">
                  パース実行
                </h3>
                <p className="text-sm text-stone-500 dark:text-stone-400 mt-1">
                  設定したパターンで全レコーディングのdatetimeをパースします。
                </p>
              </div>

              <div className="flex justify-end">
                <Button
                  type="button"
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
