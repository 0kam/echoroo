"use client";

import { useMemo } from "react";

import type { Recording } from "@/lib/types";

type TimelineViewProps = {
  recordings: Recording[];
  isLoading: boolean;
};

type DayBucket = {
  date: string;
  count: number;
  recordings: Recording[];
};

type HourBucket = {
  hour: number;
  count: number;
};

function groupByDate(recordings: Recording[]): DayBucket[] {
  const buckets: Map<string, Recording[]> = new Map();

  for (const recording of recordings) {
    if (!recording.datetime) continue;

    // Extract date string from datetime in local timezone (YYYY-MM-DD format)
    const year = recording.datetime.getFullYear();
    const month = String(recording.datetime.getMonth() + 1).padStart(2, '0');
    const day = String(recording.datetime.getDate()).padStart(2, '0');
    const dateStr = `${year}-${month}-${day}`;

    if (!buckets.has(dateStr)) {
      buckets.set(dateStr, []);
    }
    buckets.get(dateStr)!.push(recording);
  }

  return Array.from(buckets.entries())
    .map(([date, recs]) => ({
      date,
      count: recs.length,
      recordings: recs,
    }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

function groupByHour(recordings: Recording[]): HourBucket[] {
  const hourCounts = new Array(24).fill(0);

  for (const recording of recordings) {
    if (!recording.datetime) continue;

    // Extract hour from datetime in local timezone (0-23)
    const hour = recording.datetime.getHours();
    hourCounts[hour]++;
  }

  return hourCounts.map((count, hour) => ({ hour, count }));
}

function getMonthlyData(
  dayBuckets: DayBucket[],
): { month: string; count: number }[] {
  const monthCounts: Map<string, number> = new Map();

  for (const bucket of dayBuckets) {
    const month = bucket.date.substring(0, 7); // YYYY-MM
    monthCounts.set(month, (monthCounts.get(month) || 0) + bucket.count);
  }

  return Array.from(monthCounts.entries())
    .map(([month, count]) => ({ month, count }))
    .sort((a, b) => a.month.localeCompare(b.month));
}

export default function TimelineView({
  recordings,
  isLoading,
}: TimelineViewProps) {
  const dayBuckets = useMemo(() => groupByDate(recordings), [recordings]);
  const hourBuckets = useMemo(() => groupByHour(recordings), [recordings]);
  const monthlyData = useMemo(() => getMonthlyData(dayBuckets), [dayBuckets]);

  const maxMonthCount = useMemo(
    () => Math.max(...monthlyData.map((m) => m.count), 1),
    [monthlyData],
  );

  const maxHourCount = useMemo(
    () => Math.max(...hourBuckets.map((h) => h.count), 1),
    [hourBuckets],
  );

  if (isLoading) {
    return (
      <div className="h-96 rounded-lg border border-stone-200 dark:border-stone-700 bg-stone-100 dark:bg-stone-800 flex items-center justify-center">
        <div className="text-stone-500 dark:text-stone-400">
          Loading timeline...
        </div>
      </div>
    );
  }

  if (recordings.length === 0) {
    return (
      <div className="h-96 rounded-lg border border-stone-200 dark:border-stone-700 bg-stone-100 dark:bg-stone-800 flex items-center justify-center">
        <div className="text-stone-500 dark:text-stone-400">
          No recordings to display
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Monthly Distribution */}
      <div className="rounded-lg border border-stone-200 dark:border-stone-700 p-4">
        <h3 className="text-sm font-semibold text-stone-900 dark:text-stone-100 mb-4">
          Monthly Distribution
        </h3>
        <div className="flex flex-col">
          {/* Bar area with fixed height */}
          <div className="h-32 flex items-end gap-1">
            {monthlyData.map((item) => (
              <div
                key={item.month}
                className="flex-1 flex flex-col items-center group relative"
              >
                <div
                  className="w-full bg-emerald-500 dark:bg-emerald-600 rounded-t transition-all group-hover:bg-emerald-600 dark:group-hover:bg-emerald-500"
                  style={{
                    height: `${(item.count / maxMonthCount) * 100}%`,
                    minHeight: item.count > 0 ? "4px" : "0",
                  }}
                />
                <div className="absolute -top-6 left-1/2 -translate-x-1/2 bg-stone-900 dark:bg-stone-100 text-white dark:text-stone-900 text-xs px-1 py-0.5 rounded opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap z-10">
                  {item.count}
                </div>
              </div>
            ))}
          </div>
          {/* Labels area with spacing */}
          <div className="mt-4 flex gap-1">
            {monthlyData.map((item) => (
              <div key={`label-${item.month}`} className="flex-1 flex justify-center">
                <div className="text-[10px] text-stone-500 dark:text-stone-400 -rotate-45 origin-center whitespace-nowrap">
                  {item.month}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Hourly Distribution */}
      <div className="rounded-lg border border-stone-200 dark:border-stone-700 p-4">
        <h3 className="text-sm font-semibold text-stone-900 dark:text-stone-100 mb-4">
          Time of Day Distribution
        </h3>
        <div className="flex flex-col">
          {/* Bar area with fixed height */}
          <div className="h-24 flex items-end gap-0.5">
            {hourBuckets.map((item) => (
              <div
                key={item.hour}
                className="flex-1 flex flex-col items-center group relative"
              >
                <div
                  className="w-full bg-blue-500 dark:bg-blue-600 rounded-t transition-all group-hover:bg-blue-600 dark:group-hover:bg-blue-500"
                  style={{
                    height: `${(item.count / maxHourCount) * 100}%`,
                    minHeight: item.count > 0 ? "2px" : "0",
                  }}
                />
                <div className="absolute -top-6 left-1/2 -translate-x-1/2 bg-stone-900 dark:bg-stone-100 text-white dark:text-stone-900 text-xs px-1 py-0.5 rounded opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap z-10">
                  {String(item.hour).padStart(2, "0")}:00 - {item.count}
                </div>
              </div>
            ))}
          </div>
          {/* Labels area with spacing - show every 6 hours */}
          <div className="mt-2 flex gap-0.5">
            {hourBuckets.map((item) => (
              <div key={`label-${item.hour}`} className="flex-1 relative">
                {item.hour % 6 === 0 && (
                  <div className="absolute left-1/2 -translate-x-1/2 text-[10px] text-stone-500 dark:text-stone-400">
                    {String(item.hour).padStart(2, "0")}:00
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="rounded-lg border border-stone-200 dark:border-stone-700 p-3">
          <div className="text-2xl font-bold text-stone-900 dark:text-stone-100">
            {recordings.length}
          </div>
          <div className="text-xs text-stone-500 dark:text-stone-400">
            Total Recordings
          </div>
        </div>
        <div className="rounded-lg border border-stone-200 dark:border-stone-700 p-3">
          <div className="text-2xl font-bold text-stone-900 dark:text-stone-100">
            {dayBuckets.length}
          </div>
          <div className="text-xs text-stone-500 dark:text-stone-400">
            Days with Data
          </div>
        </div>
        <div className="rounded-lg border border-stone-200 dark:border-stone-700 p-3">
          <div className="text-2xl font-bold text-stone-900 dark:text-stone-100">
            {monthlyData.length}
          </div>
          <div className="text-xs text-stone-500 dark:text-stone-400">
            Months Covered
          </div>
        </div>
        <div className="rounded-lg border border-stone-200 dark:border-stone-700 p-3">
          <div className="text-2xl font-bold text-stone-900 dark:text-stone-100">
            {recordings
              .reduce((sum, r) => sum + (r.duration ?? 0), 0)
              .toFixed(1)}
            s
          </div>
          <div className="text-xs text-stone-500 dark:text-stone-400">
            Total Duration
          </div>
        </div>
      </div>
    </div>
  );
}
