"use client";

import { useCallback, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import api from "@/app/api";
import { Group, Input, Select } from "@/lib/components/inputs";
import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import { DialogOverlay as Dialog } from "@/lib/components/ui/Dialog";
import Spinner from "@/lib/components/ui/Spinner";
import type { Dataset, DatetimePatternType } from "@/lib/types";

const PATTERN_TYPE_OPTIONS = [
  {
    id: "strptime",
    label: "strptime - Python datetime format codes",
    value: "strptime" as DatetimePatternType,
  },
  {
    id: "regex",
    label: "regex - Regular expression (captures Y,M,D,H,M,S)",
    value: "regex" as DatetimePatternType,
  },
];

export default function DatasetDatetimeParser({
  dataset,
}: {
  dataset: Dataset;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [patternType, setPatternType] = useState<DatetimePatternType>(
    "strptime",
  );
  const [pattern, setPattern] = useState("");
  const [sampleFilename, setSampleFilename] = useState("");

  const queryClient = useQueryClient();

  const { data: status, isLoading: statusLoading } = useQuery({
    queryKey: ["datetime-parse-status", dataset.uuid],
    queryFn: () => api.datasets.getDatetimeParseStatus(dataset.uuid),
    enabled: isOpen,
  });

  const {
    mutateAsync: savePattern,
    isPending: isSavingPattern,
    isError: isPatternError,
    error: patternError,
    isSuccess: isPatternSuccess,
  } = useMutation({
    mutationFn: () =>
      api.datasets.setDatetimePattern(dataset.uuid, {
        pattern_type: patternType,
        pattern,
        sample_filename: sampleFilename || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["datetime-parse-status", dataset.uuid],
      });
    },
  });

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

          {/* Pattern Configuration */}
          <Card>
            <form onSubmit={handleSetPattern} className="flex flex-col gap-4">
              <h3 className="text-sm font-semibold text-stone-900 dark:text-stone-100">
                パターン設定
              </h3>

              <Group label="Pattern Type" name="pattern_type">
                <Select
                  options={PATTERN_TYPE_OPTIONS}
                  selected={
                    PATTERN_TYPE_OPTIONS.find((opt) => opt.value === patternType) ??
                    PATTERN_TYPE_OPTIONS[0]
                  }
                  onChange={(value) =>
                    setPatternType(value as DatetimePatternType)
                  }
                />
              </Group>

              <Group label="Pattern" name="pattern">
                <Input
                  value={pattern}
                  onChange={(e) => setPattern(e.target.value)}
                  placeholder={
                    patternType === "strptime"
                      ? "%Y%m%d_%H%M%S"
                      : "(\\d{4})(\\d{2})(\\d{2})_(\\d{2})(\\d{2})(\\d{2})"
                  }
                  required
                />
              </Group>

              <Group
                label="Sample Filename (optional)"
                name="sample_filename"
              >
                <Input
                  value={sampleFilename}
                  onChange={(e) => setSampleFilename(e.target.value)}
                  placeholder="20240101_120000.wav"
                />
              </Group>

              <div className="flex justify-end gap-2">
                <Button
                  type="button"
                  mode="text"
                  variant="secondary"
                  onClick={() => setIsOpen(false)}
                >
                  キャンセル
                </Button>
                <Button
                  type="submit"
                  variant="primary"
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
            </form>
          </Card>

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
