"use client";

import { useCallback, useState } from "react";

type DatetimeComponent = "year" | "month" | "day" | "hour" | "minute" | "second";

interface Selection {
  start: number;
  end: number;
  component: DatetimeComponent;
}

const COMPONENT_LABELS: Record<DatetimeComponent, string> = {
  year: "年 (YYYY)",
  month: "月 (MM)",
  day: "日 (DD)",
  hour: "時 (HH)",
  minute: "分 (MM)",
  second: "秒 (SS)",
};

const COMPONENT_COLORS: Record<DatetimeComponent, string> = {
  year: "bg-blue-200 dark:bg-blue-800",
  month: "bg-green-200 dark:bg-green-800",
  day: "bg-yellow-200 dark:bg-yellow-800",
  hour: "bg-purple-200 dark:bg-purple-800",
  minute: "bg-pink-200 dark:bg-pink-800",
  second: "bg-orange-200 dark:bg-orange-800",
};

const COMPONENTS_ORDER: DatetimeComponent[] = [
  "year",
  "month",
  "day",
  "hour",
  "minute",
  "second",
];

export interface DatetimeStringSelectorProps {
  filename: string;
  onSelectionsChange: (selections: Record<DatetimeComponent, Selection>) => void;
}

export default function DatetimeStringSelector({
  filename,
  onSelectionsChange,
}: DatetimeStringSelectorProps) {
  const [selections, setSelections] = useState<
    Partial<Record<DatetimeComponent, Selection>>
  >({});
  const [currentComponent, setCurrentComponent] = useState<DatetimeComponent>("year");
  const [isSelecting, setIsSelecting] = useState(false);
  const [selectionStart, setSelectionStart] = useState<number | null>(null);

  const handleMouseDown = useCallback(
    (index: number) => {
      setIsSelecting(true);
      setSelectionStart(index);
    },
    []
  );

  const handleMouseMove = useCallback(
    (index: number) => {
      if (!isSelecting || selectionStart === null) return;

      const start = Math.min(selectionStart, index);
      const end = Math.max(selectionStart, index) + 1;

      setSelections((prev) => ({
        ...prev,
        [currentComponent]: { start, end, component: currentComponent },
      }));
    },
    [isSelecting, selectionStart, currentComponent]
  );

  const handleMouseUp = useCallback(() => {
    if (isSelecting && selectionStart !== null) {
      setIsSelecting(false);
      setSelectionStart(null);

      // Move to next component
      const currentIndex = COMPONENTS_ORDER.indexOf(currentComponent);
      if (currentIndex < COMPONENTS_ORDER.length - 1) {
        setCurrentComponent(COMPONENTS_ORDER[currentIndex + 1]);
      }

      // Notify parent
      const currentSelections = selections as Record<DatetimeComponent, Selection>;
      if (Object.keys(currentSelections).length === COMPONENTS_ORDER.length - 1) {
        onSelectionsChange(currentSelections);
      }
    }
  }, [isSelecting, selectionStart, currentComponent, selections, onSelectionsChange]);

  const getCharacterColor = useCallback(
    (index: number): string | null => {
      for (const [component, selection] of Object.entries(selections)) {
        if (index >= selection.start && index < selection.end) {
          return COMPONENT_COLORS[component as DatetimeComponent];
        }
      }
      return null;
    },
    [selections]
  );

  const handleComponentClick = useCallback((component: DatetimeComponent) => {
    setCurrentComponent(component);
  }, []);

  const handleReset = useCallback(() => {
    setSelections({});
    setCurrentComponent("year");
    setIsSelecting(false);
    setSelectionStart(null);
  }, []);

  return (
    <div className="flex flex-col gap-4">
      {/* Instructions */}
      <div className="text-sm text-stone-600 dark:text-stone-400">
        現在選択中:{" "}
        <span className="font-semibold text-stone-900 dark:text-stone-100">
          {COMPONENT_LABELS[currentComponent]}
        </span>
        <p className="mt-1 text-xs">
          ファイル名の文字列をドラッグして{COMPONENT_LABELS[currentComponent]}
          に該当する部分を選択してください。
        </p>
      </div>

      {/* Filename display with selectable characters */}
      <div
        className="font-mono text-lg p-4 bg-stone-50 dark:bg-stone-900 rounded-md select-none border-2 border-stone-300 dark:border-stone-700"
        onMouseLeave={handleMouseUp}
      >
        {filename.split("").map((char, index) => {
          const color = getCharacterColor(index);
          return (
            <span
              key={index}
              className={`cursor-pointer px-0.5 ${color || "hover:bg-stone-200 dark:hover:bg-stone-800"}`}
              onMouseDown={() => handleMouseDown(index)}
              onMouseMove={() => handleMouseMove(index)}
              onMouseUp={handleMouseUp}
            >
              {char}
            </span>
          );
        })}
      </div>

      {/* Component selection buttons */}
      <div className="flex flex-wrap gap-2">
        {COMPONENTS_ORDER.map((component) => {
          const isSelected = currentComponent === component;
          const hasSelection = !!selections[component];
          return (
            <button
              key={component}
              onClick={() => handleComponentClick(component)}
              className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
                isSelected
                  ? "ring-2 ring-emerald-500"
                  : ""
              } ${
                hasSelection
                  ? `${COMPONENT_COLORS[component]} text-stone-900 dark:text-stone-100`
                  : "bg-stone-200 dark:bg-stone-700 text-stone-600 dark:text-stone-400"
              }`}
            >
              {COMPONENT_LABELS[component]}
              {hasSelection && selections[component] && (
                <span className="ml-2 text-xs">
                  &quot;{filename.substring(selections[component]!.start, selections[component]!.end)}&quot;
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Reset button */}
      <div className="flex justify-end">
        <button
          onClick={handleReset}
          className="px-3 py-1 text-sm text-stone-600 dark:text-stone-400 hover:text-stone-900 dark:hover:text-stone-100"
        >
          リセット
        </button>
      </div>

      {/* Preview of selections */}
      {Object.keys(selections).length > 0 && (
        <div className="text-xs text-stone-500 dark:text-stone-400">
          <p className="font-semibold mb-1">選択内容:</p>
          {COMPONENTS_ORDER.map((component) => {
            const selection = selections[component];
            if (!selection) return null;
            return (
              <p key={component}>
                {COMPONENT_LABELS[component]}:{" "}
                <span className="font-mono">
                  &quot;{filename.substring(selection.start, selection.end)}&quot;
                </span>{" "}
                (位置: {selection.start}-{selection.end})
              </p>
            );
          })}
        </div>
      )}
    </div>
  );
}
