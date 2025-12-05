"use client";

import { useMemo } from "react";

import Link from "@/lib/components/ui/Link";
import VisibilityBadge from "@/lib/components/ui/VisibilityBadge";
import Button from "@/lib/components/ui/Button";
import type { Recording } from "@/lib/types";

type TableViewProps = {
  recordings: Recording[];
  isLoading: boolean;
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
};

function formatDate(date: string | Date | null | undefined): string {
  if (!date) return "-";
  const d = typeof date === "string" ? new Date(date) : date;
  return d.toLocaleDateString();
}

function formatTime(time: string | Date | null | undefined): string {
  if (!time) return "-";
  if (typeof time === "string") {
    return time.substring(0, 5);
  }
  return new Date(time).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDuration(duration: number | null): string {
  if (duration === null) return "-";
  if (duration < 60) return `${duration.toFixed(1)}s`;
  const minutes = Math.floor(duration / 60);
  const seconds = duration % 60;
  return `${minutes}m ${seconds.toFixed(0)}s`;
}

export default function TableView({
  recordings,
  isLoading,
  page,
  pageSize,
  total,
  onPageChange,
}: TableViewProps) {
  const showingStart = total === 0 ? 0 : page * pageSize + 1;
  const showingEnd = Math.min(total, page * pageSize + recordings.length);
  const totalPages = Math.ceil(total / pageSize);
  const canGoPrev = page > 0;
  const canGoNext = page < totalPages - 1;

  if (isLoading) {
    return (
      <div className="h-96 rounded-lg border border-stone-200 dark:border-stone-700 bg-stone-100 dark:bg-stone-800 flex items-center justify-center">
        <div className="text-stone-500 dark:text-stone-400">
          Loading recordings...
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="overflow-x-auto rounded-lg border border-stone-200 dark:border-stone-700">
        <table className="min-w-full divide-y divide-stone-200 dark:divide-stone-700">
          <thead className="bg-stone-50 dark:bg-stone-800">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-semibold text-stone-900 dark:text-stone-100 uppercase tracking-wider">
                File
              </th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-stone-900 dark:text-stone-100 uppercase tracking-wider hidden md:table-cell">
                Dataset
              </th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-stone-900 dark:text-stone-100 uppercase tracking-wider hidden lg:table-cell">
                Date
              </th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-stone-900 dark:text-stone-100 uppercase tracking-wider hidden lg:table-cell">
                Time
              </th>
              <th className="px-4 py-3 text-right text-xs font-semibold text-stone-900 dark:text-stone-100 uppercase tracking-wider hidden sm:table-cell">
                Duration
              </th>
              <th className="px-4 py-3 text-right text-xs font-semibold text-stone-900 dark:text-stone-100 uppercase tracking-wider hidden xl:table-cell">
                Location
              </th>
            </tr>
          </thead>
          <tbody className="bg-white dark:bg-stone-900 divide-y divide-stone-200 dark:divide-stone-700">
            {recordings.length === 0 ? (
              <tr>
                <td
                  colSpan={6}
                  className="px-4 py-8 text-center text-sm text-stone-500 dark:text-stone-400"
                >
                  No recordings found
                </td>
              </tr>
            ) : (
              recordings.map((recording) => (
                <tr
                  key={recording.uuid}
                  className="hover:bg-stone-50 dark:hover:bg-stone-800 transition-colors"
                >
                  <td className="px-4 py-3">
                    <div className="text-sm font-mono text-stone-900 dark:text-stone-100 truncate max-w-xs">
                      {recording.path}
                    </div>
                  </td>
                  <td className="px-4 py-3 hidden md:table-cell">
                    {recording.dataset ? (
                      <div className="flex items-center gap-2">
                        <Link
                          href={`/datasets/${recording.dataset.uuid}/`}
                          className="text-sm text-emerald-600 dark:text-emerald-400 hover:underline truncate max-w-40"
                        >
                          {recording.dataset.name}
                        </Link>
                        <VisibilityBadge
                          visibility={recording.dataset.visibility}
                        />
                      </div>
                    ) : (
                      <span className="text-sm text-stone-500">-</span>
                    )}
                  </td>
                  <td className="px-4 py-3 hidden lg:table-cell">
                    <span className="text-sm text-stone-700 dark:text-stone-300">
                      {formatDate(recording.date)}
                    </span>
                  </td>
                  <td className="px-4 py-3 hidden lg:table-cell">
                    <span className="text-sm text-stone-700 dark:text-stone-300">
                      {formatTime(recording.time)}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right hidden sm:table-cell">
                    <span className="text-sm text-stone-700 dark:text-stone-300">
                      {formatDuration(recording.duration)}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right hidden xl:table-cell">
                    {recording.latitude != null &&
                    recording.longitude != null ? (
                      <span className="text-xs text-stone-500 dark:text-stone-400 font-mono">
                        {recording.latitude.toFixed(4)},{" "}
                        {recording.longitude.toFixed(4)}
                      </span>
                    ) : (
                      <span className="text-sm text-stone-500">-</span>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between">
        <div className="text-sm text-stone-500 dark:text-stone-400">
          Showing {showingStart} - {showingEnd} of {total} recordings
        </div>
        <div className="flex items-center gap-2">
          <Button
            mode="text"
            padding="px-3 py-1.5"
            disabled={!canGoPrev}
            onClick={() => onPageChange(page - 1)}
          >
            Previous
          </Button>
          <span className="text-sm text-stone-700 dark:text-stone-300">
            Page {page + 1} of {totalPages || 1}
          </span>
          <Button
            mode="text"
            padding="px-3 py-1.5"
            disabled={!canGoNext}
            onClick={() => onPageChange(page + 1)}
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}
