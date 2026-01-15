"use client";

import { useMemo, useState, useCallback } from "react";

import type { DatasetRecordingTimelineSegment } from "@/lib/types";

type DayData = {
  date: Date;
  segments: DatasetRecordingTimelineSegment[];
};

type TimelineData = {
  days: DayData[];
  minHour: number;
  maxHour: number;
};

function formatTime(date: Date): string {
  const hours = date.getHours().toString().padStart(2, "0");
  const minutes = date.getMinutes().toString().padStart(2, "0");
  return `${hours}:${minutes}`;
}

function formatDate(date: Date): string {
  const month = date.getMonth() + 1;
  const day = date.getDate();
  return `${month}/${day}`;
}

function formatDateFull(date: Date): string {
  return date.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

// Get local date string (YYYY-MM-DD) in local timezone
function getLocalDateKey(date: Date): string {
  const year = date.getFullYear();
  const month = (date.getMonth() + 1).toString().padStart(2, "0");
  const day = date.getDate().toString().padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function buildTimeline(segments: DatasetRecordingTimelineSegment[]): TimelineData {
  if (segments.length === 0) {
    return { days: [], minHour: 0, maxHour: 24 };
  }

  // Group segments by local date
  const dayMap = new Map<string, DayData>();
  let minHour = 24;
  let maxHour = 0;

  for (const segment of segments) {
    const start = new Date(segment.start);
    const end = new Date(segment.end);
    // Use local date instead of UTC
    const dateKey = getLocalDateKey(start);

    if (!dayMap.has(dateKey)) {
      // Create date at midnight local time
      const [year, month, day] = dateKey.split("-").map(Number);
      dayMap.set(dateKey, {
        date: new Date(year!, month! - 1, day!),
        segments: [],
      });
    }
    dayMap.get(dateKey)!.segments.push(segment);

    // Track hour range
    const startHour = start.getHours();
    const endHour = end.getHours() + (end.getMinutes() > 0 ? 1 : 0);
    minHour = Math.min(minHour, startHour);
    maxHour = Math.max(maxHour, Math.min(endHour + 1, 24));
  }

  // Sort days by date
  const days = Array.from(dayMap.values()).sort(
    (a, b) => a.date.getTime() - b.date.getTime()
  );

  // Ensure at least a 4-hour range for visibility
  if (maxHour - minHour < 4) {
    const center = (minHour + maxHour) / 2;
    minHour = Math.max(0, Math.floor(center - 2));
    maxHour = Math.min(24, Math.ceil(center + 2));
  }

  return { days, minHour, maxHour };
}

function getSegmentPosition(
  segment: DatasetRecordingTimelineSegment,
  minHour: number,
  maxHour: number
): { top: number; height: number } {
  const start = new Date(segment.start);
  const end = new Date(segment.end);

  const startMinutes = start.getHours() * 60 + start.getMinutes();
  const endMinutes = end.getHours() * 60 + end.getMinutes();

  const rangeMinutes = (maxHour - minHour) * 60;
  const offsetMinutes = minHour * 60;

  const top = ((startMinutes - offsetMinutes) / rangeMinutes) * 100;
  const height = ((endMinutes - startMinutes) / rangeMinutes) * 100;

  return { top: Math.max(0, top), height: Math.min(100 - top, height) };
}

export default function DatasetRecordingCalendar({
  timeline,
}: {
  timeline: DatasetRecordingTimelineSegment[];
}) {
  const [hoveredSegment, setHoveredSegment] = useState<DatasetRecordingTimelineSegment | null>(null);
  const { days, minHour, maxHour } = useMemo(() => buildTimeline(timeline), [timeline]);

  const hours = useMemo(() => {
    const result: number[] = [];
    for (let h = minHour; h <= maxHour; h++) {
      result.push(h);
    }
    return result;
  }, [minHour, maxHour]);

  const handleMouseEnter = useCallback((segment: DatasetRecordingTimelineSegment) => {
    setHoveredSegment(segment);
  }, []);

  const handleMouseLeave = useCallback(() => {
    setHoveredSegment(null);
  }, []);

  if (days.length === 0) {
    return (
      <div className="text-sm text-stone-500 dark:text-stone-400">
        Recording timestamps will appear here once parsed.
      </div>
    );
  }

  const totalRecordings = timeline.length;
  const firstDate = days[0]?.date;
  const lastDate = days[days.length - 1]?.date;

  return (
    <div className="space-y-3">
      {/* Header with tooltip area - fixed height to prevent layout shift */}
      <div className="relative h-12">
        <div className="flex items-center justify-between text-xs text-stone-500 dark:text-stone-400">
          <span>
            {totalRecordings} recording{totalRecordings !== 1 ? "s" : ""} over {days.length} day{days.length !== 1 ? "s" : ""}
          </span>
          {firstDate && lastDate && (
            <span>
              {formatDateFull(firstDate)} — {formatDateFull(lastDate)}
            </span>
          )}
        </div>

        {/* Tooltip - absolutely positioned below header */}
        <div
          className={`absolute left-0 top-6 rounded-lg bg-stone-800 dark:bg-stone-200 text-white dark:text-stone-900 p-2 text-xs shadow-lg transition-opacity z-10 ${
            hoveredSegment ? "opacity-100" : "opacity-0 pointer-events-none"
          }`}
        >
          {hoveredSegment && (
            <>
              <div className="font-semibold">
                {formatTime(new Date(hoveredSegment.start))} — {formatTime(new Date(hoveredSegment.end))}
              </div>
              <div className="text-stone-300 dark:text-stone-600 truncate max-w-xs">
                {hoveredSegment.path.split("/").pop()}
              </div>
            </>
          )}
        </div>
      </div>

      <div className="overflow-x-auto pb-2">
        <div className="inline-flex min-w-full">
          {/* Hour labels */}
          <div className="flex flex-col pr-2 text-right text-[10px] text-stone-400 dark:text-stone-500 w-12 flex-shrink-0">
            <div className="h-5" /> {/* Spacer for date labels */}
            <div className="relative flex-1" style={{ height: `${(maxHour - minHour) * 16}px` }}>
              {hours.map((hour) => (
                <div
                  key={hour}
                  className="absolute right-0 leading-none"
                  style={{
                    top: `${((hour - minHour) / (maxHour - minHour)) * 100}%`,
                    transform: "translateY(-50%)",
                  }}
                >
                  {hour.toString().padStart(2, "0")}:00
                </div>
              ))}
            </div>
          </div>

          {/* Timeline grid */}
          <div className="flex gap-0.5">
            {days.map((day, dayIdx) => (
              <div key={day.date.toISOString()} className="flex flex-col">
                {/* Date label */}
                <div className="h-5 text-[9px] text-stone-400 dark:text-stone-500 text-center w-6">
                  {dayIdx % 7 === 0 || days.length <= 14 ? formatDate(day.date) : ""}
                </div>

                {/* Day column */}
                <div
                  className="relative w-6 bg-stone-100 dark:bg-stone-800 rounded-sm"
                  style={{ height: `${(maxHour - minHour) * 16}px` }}
                >
                  {/* Hour grid lines */}
                  {hours.map((hour) => (
                    <div
                      key={hour}
                      className="absolute w-full border-t border-stone-200 dark:border-stone-700"
                      style={{
                        top: `${((hour - minHour) / (maxHour - minHour)) * 100}%`,
                      }}
                    />
                  ))}

                  {/* Recording segments */}
                  {day.segments.map((segment) => {
                    const { top, height } = getSegmentPosition(segment, minHour, maxHour);
                    const isHovered = hoveredSegment?.recording_uuid === segment.recording_uuid;

                    return (
                      <div
                        key={segment.recording_uuid}
                        className={`absolute left-0.5 right-0.5 rounded-sm cursor-pointer transition-colors ${
                          isHovered
                            ? "bg-emerald-500 dark:bg-emerald-400"
                            : "bg-emerald-600 dark:bg-emerald-500"
                        }`}
                        style={{
                          top: `${top}%`,
                          height: `${Math.max(height, 1)}%`,
                          minHeight: "2px",
                        }}
                        onMouseEnter={() => handleMouseEnter(segment)}
                        onMouseLeave={handleMouseLeave}
                        title={`${formatTime(new Date(segment.start))} — ${formatTime(new Date(segment.end))}\n${segment.path}`}
                      />
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-2 text-xs text-stone-500">
        <span className="h-3 w-3 rounded-sm bg-emerald-600 dark:bg-emerald-500" />
        <span>Recording active</span>
      </div>
    </div>
  );
}
