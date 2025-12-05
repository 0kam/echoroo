"use client";

import { Menu, Transition } from "@headlessui/react";
import { Fragment, useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import toast from "react-hot-toast";

import useDataset from "@/app/hooks/api/useDataset";
import useNotes from "@/app/hooks/api/useNotes";
import useDatasetStats from "@/app/hooks/api/useDatasetStats";
import DatasetSitesMap from "@/app/components/datasets/DatasetSitesMap";
import DatasetRecordingCalendar from "@/app/components/datasets/DatasetRecordingCalendar";
import api from "@/app/api";

import DatasetOverviewBase from "@/lib/components/datasets/DatasetOverview";
import { CalendarIcon, DownloadIcon, MapIcon } from "@/lib/components/icons";
import Button from "@/lib/components/ui/Button";

import type { Dataset } from "@/lib/types";

const downloadOptions = [
  {
    id: "metadata",
    label: "Metadata only",
    description: "Downloads deployments.csv and media.csv as a ZIP.",
    includeAudio: false,
  },
  {
    id: "audio",
    label: "Metadata + Audio",
    description: "Includes Audio/ directory with all recordings.",
    includeAudio: true,
  },
];

function formatDuration(seconds?: number | null): string | null {
  if (seconds == null || Number.isNaN(seconds) || seconds <= 0) {
    return null;
  }
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const parts = [];
  if (hours > 0) parts.push(`${hours}h`);
  if (minutes > 0) parts.push(`${minutes}m`);
  if (!parts.length) {
    const remainingSeconds = Math.round(seconds % 60);
    parts.push(`${remainingSeconds}s`);
  }
  return parts.join(" ");
}

export default function DatasetOverview({ dataset }: { dataset: Dataset }) {
  const router = useRouter();

  const { data, state } = useDataset({
    uuid: dataset.uuid,
    dataset,
    withState: true,
  });

  const filter = useMemo(() => ({ dataset: data, is_issue: true }), [data]);

  const issues = useNotes({
    filter,
    pageSize: 0,
  });

  const stats = useDatasetStats({
    uuid: dataset.uuid,
  });

  const [pendingDownload, setPendingDownload] = useState<
    "metadata" | "audio" | null
  >(null);

  const handleDownload = useCallback(
    async (includeAudio: boolean) => {
      const mode = includeAudio ? "audio" : "metadata";
      setPendingDownload(mode);
      try {
        await toast.promise(
          api.datasets.exportBioacoustics(dataset.uuid, { includeAudio }),
          {
            loading: includeAudio
              ? "Preparing audio package..."
              : "Preparing metadata...",
            success: "Download ready",
            error: "Failed to export dataset",
          },
        );
      } finally {
        setPendingDownload(null);
      }
    },
    [dataset.uuid],
  );

  const { missing } = useMemo(() => {
    if (state.isLoading || state.data == null)
      return { missing: 0, newRecordings: 0 };
    return state.data.reduce(
      (acc, recording) => {
        if (recording.state == "missing") acc.missing++;
        if (recording.state == "unregistered") acc.newRecordings++;
        return acc;
      },
      { missing: 0, newRecordings: 0 },
    );
  }, [state]);

  const downloadMenu = (
    <Menu as="div" className="relative inline-block text-left">
      <Menu.Button as={Fragment}>
        <Button
          mode="filled"
          variant="primary"
          disabled={pendingDownload !== null}
        >
          <DownloadIcon className="inline-block mr-2 w-4 h-4" />
          {pendingDownload === "audio"
            ? "Preparing audio..."
            : pendingDownload === "metadata"
              ? "Preparing..."
              : "Download"}
        </Button>
      </Menu.Button>
      <Transition
        as={Fragment}
        enter="transition ease-out duration-100"
        enterFrom="transform opacity-0 scale-95"
        enterTo="transform opacity-100 scale-100"
        leave="transition ease-in duration-75"
        leaveFrom="transform opacity-100 scale-100"
        leaveTo="transform opacity-0 scale-95"
      >
        <Menu.Items className="absolute right-0 z-20 mt-2 w-64 origin-top-right rounded-lg border border-stone-200 bg-white shadow-lg focus:outline-none dark:border-stone-700 dark:bg-stone-800">
          <div className="p-2">
            {downloadOptions.map((option) => (
              <Menu.Item key={option.id}>
                {({ active }) => (
                  <button
                    type="button"
                    onClick={() => handleDownload(option.includeAudio)}
                    className={`w-full rounded-md px-3 py-2 text-left text-sm ${
                      active
                        ? "bg-stone-100 dark:bg-stone-700"
                        : "bg-transparent"
                    }`}
                  >
                    <div className="font-semibold">{option.label}</div>
                    <div className="text-xs text-stone-500 dark:text-stone-400">
                      {option.description}
                    </div>
                  </button>
                )}
              </Menu.Item>
            ))}
          </div>
        </Menu.Items>
      </Transition>
    </Menu>
  );

  const recordingSites = stats.data?.recording_sites ?? [];
  const timelineSegments = stats.data?.recording_timeline ?? [];
  const totalDuration = formatDuration(stats.data?.total_duration_seconds);

  const handleClickRecordings = useCallback(() => {
    router.push(`/datasets/${dataset.uuid}/recordings`);
  }, [dataset.uuid, router]);

  return (
    <DatasetOverviewBase
      dataset={data || dataset}
      onClickDatasetRecordings={handleClickRecordings}
      numIssues={issues.total}
      numMissing={missing}
      isLoading={issues.isLoading}
      actionSlot={downloadMenu}
    >
      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-stone-200 p-4 dark:border-stone-700">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <MapIcon className="inline-block h-5 w-5 text-blue-500" />
              <span className="text-sm font-semibold uppercase tracking-wide text-stone-500">
                Recording Sites
              </span>
            </div>
            <span className="text-xs text-stone-500 dark:text-stone-400">
              {stats.isLoading
                ? "Calculating…"
                : recordingSites.length
                  ? `${recordingSites.length} site${recordingSites.length > 1 ? "s" : ""}`
                  : "No locations"}
            </span>
          </div>
          <div className="mt-4">
            {stats.isLoading ? (
              <div className="h-64 w-full animate-pulse rounded-lg bg-stone-100 dark:bg-stone-800" />
            ) : recordingSites.length ? (
              <DatasetSitesMap sites={recordingSites} />
            ) : (
              <p className="text-sm text-stone-500 dark:text-stone-400">
                No geospatial metadata available yet.
              </p>
            )}
          </div>
        </div>
        <div className="rounded-xl border border-stone-200 p-4 dark:border-stone-700">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <CalendarIcon className="inline-block h-5 w-5 text-purple-500" />
              <span className="text-sm font-semibold uppercase tracking-wide text-stone-500">
                Recording Calendar
              </span>
            </div>
            {totalDuration ? (
              <span className="text-xs text-stone-500 dark:text-stone-400">
                {totalDuration} captured
              </span>
            ) : null}
          </div>
          <div className="mt-4">
            {stats.isLoading ? (
              <div className="h-32 w-full animate-pulse rounded-lg bg-stone-100 dark:bg-stone-800" />
            ) : (
              <DatasetRecordingCalendar timeline={timelineSegments} />
            )}
          </div>
        </div>
      </div>
    </DatasetOverviewBase>
  );
}
