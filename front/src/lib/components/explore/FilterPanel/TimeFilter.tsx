"use client";

import { Group, Input } from "@/lib/components/inputs";

type TimeFilterProps = {
  dateStart: string | null;
  dateEnd: string | null;
  timeStart: number | null;
  timeEnd: number | null;
  onDateStartChange: (value: string | null) => void;
  onDateEndChange: (value: string | null) => void;
  onTimeStartChange: (value: number | null) => void;
  onTimeEndChange: (value: number | null) => void;
};

function secondsToTimeString(seconds: number | null): string {
  if (seconds === null) return "";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

function timeStringToSeconds(value: string): number | null {
  if (!value) return null;
  const [hours, minutes] = value.split(":").map(Number);
  if (isNaN(hours) || isNaN(minutes)) return null;
  return hours * 3600 + minutes * 60;
}

export default function TimeFilter({
  dateStart,
  dateEnd,
  timeStart,
  timeEnd,
  onDateStartChange,
  onDateEndChange,
  onTimeStartChange,
  onTimeEndChange,
}: TimeFilterProps) {
  return (
    <div className="space-y-4">
      <div className="space-y-3">
        <h4 className="text-sm font-medium text-stone-700 dark:text-stone-300">
          Date Range
        </h4>
        <div className="grid grid-cols-2 gap-2">
          <Group label="From" name="date_start">
            <Input
              type="date"
              value={dateStart ?? ""}
              onChange={(e) =>
                onDateStartChange(e.target.value || null)
              }
            />
          </Group>
          <Group label="To" name="date_end">
            <Input
              type="date"
              value={dateEnd ?? ""}
              onChange={(e) =>
                onDateEndChange(e.target.value || null)
              }
            />
          </Group>
        </div>
      </div>

      <div className="space-y-3">
        <h4 className="text-sm font-medium text-stone-700 dark:text-stone-300">
          Time of Day
        </h4>
        <div className="grid grid-cols-2 gap-2">
          <Group label="From" name="time_start">
            <Input
              type="time"
              value={secondsToTimeString(timeStart)}
              onChange={(e) =>
                onTimeStartChange(timeStringToSeconds(e.target.value))
              }
            />
          </Group>
          <Group label="To" name="time_end">
            <Input
              type="time"
              value={secondsToTimeString(timeEnd)}
              onChange={(e) =>
                onTimeEndChange(timeStringToSeconds(e.target.value))
              }
            />
          </Group>
        </div>
        <p className="text-xs text-stone-500 dark:text-stone-400">
          Time ranges can wrap around midnight (e.g., 22:00 to 06:00 for
          nocturnal recordings).
        </p>
      </div>
    </div>
  );
}
