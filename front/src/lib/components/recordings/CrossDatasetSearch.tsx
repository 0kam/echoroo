"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import classNames from "classnames";
import { MapContainer, Polygon, TileLayer, Tooltip } from "react-leaflet";
import { gridDisk } from "h3-js";

import useDatasetFilterOptions from "@/app/hooks/ui/useDatasetFilterOptions";

import api from "@/app/api";
import { Group, Input, Select } from "@/lib/components/inputs";
import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import Spinner from "@/lib/components/ui/Spinner";
import VisibilityBadge from "@/lib/components/ui/VisibilityBadge";
import Link from "@/lib/components/ui/Link";
import H3HexPicker from "@/lib/components/maps/H3HexPicker";
import MapViewport from "@/lib/components/maps/MapViewport";
import {
  DEFAULT_MAP_CENTER,
  getH3BoundaryForLeaflet,
  getH3CenterForLeaflet,
} from "@/lib/utils/h3";

import type { Recording } from "@/lib/types";

const DEFAULT_PAGE_SIZE = 50;

type CellBucket = {
  h3Index: string;
  count: number;
  publicCount: number;
  restrictedCount: number;
  datasetCount: number;
};

function timeToSeconds(value: string | null): number | undefined {
  if (!value) return undefined;
  const [h, m] = value.split(":");
  const hours = Number.parseInt(h ?? "0", 10);
  const minutes = Number.parseInt(m ?? "0", 10);
  if (Number.isNaN(hours) || Number.isNaN(minutes)) return undefined;
  return hours * 3600 + minutes * 60;
}

function getRecordingCell(recording: Recording): string | null {
  return (
    recording.h3_index ??
    recording.dataset?.primary_site?.h3_index ??
    null
  );
}

function ResultsMap({
  cells,
  searchCenter,
  highlightedCell,
  onHoverCell,
}: {
  cells: CellBucket[];
  searchCenter: string | null;
  highlightedCell: string | null;
  onHoverCell: (value: string | null) => void;
}) {
  const focus = useMemo<[number, number]>(() => {
    if (searchCenter) {
      return getH3CenterForLeaflet(searchCenter);
    }
    if (cells.length > 0) {
      return getH3CenterForLeaflet(cells[0].h3Index);
    }
    return DEFAULT_MAP_CENTER;
  }, [cells, searchCenter]);

  const zoom = searchCenter || cells.length > 0 ? 6 : 4;

  return (
    <div className="rounded-lg overflow-hidden border border-stone-200 dark:border-stone-700">
      <MapContainer
        center={{ lat: focus[0], lng: focus[1] }}
        zoom={zoom}
        scrollWheelZoom={false}
        style={{ height: 320 }}
      >
        <MapViewport center={{ lat: focus[0], lng: focus[1] }} />
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {cells.map((cell) => {
          const boundary = getH3BoundaryForLeaflet(cell.h3Index);
          const isHighlighted = cell.h3Index === highlightedCell;
          const hasRestricted = cell.restrictedCount > 0;

          return (
            <Polygon
              key={cell.h3Index}
              positions={boundary}
              pathOptions={{
                color: hasRestricted ? "#f59e0b" : "#10b981",
                weight: isHighlighted ? 3 : 1.5,
                fillOpacity: isHighlighted ? 0.35 : 0.2,
              }}
              eventHandlers={{
                mouseover: () => onHoverCell(cell.h3Index),
                mouseout: () => {
                  if (highlightedCell === cell.h3Index) {
                    onHoverCell(null);
                  }
                },
              }}
            >
              <Tooltip sticky>
                <div className="space-y-1">
                  <div className="font-mono text-[11px]">
                    {cell.h3Index}
                  </div>
                  <div className="text-[11px]">
                    録音: {cell.count}
                  </div>
                  <div className="text-[11px]">
                    制限付き: {cell.restrictedCount}
                  </div>
                  <div className="text-[11px]">
                    データセット: {cell.datasetCount}
                  </div>
                </div>
              </Tooltip>
            </Polygon>
          );
        })}
      </MapContainer>
    </div>
  );
}

function CellSummaryList({
  cells,
  highlightedCell,
  onHoverCell,
}: {
  cells: CellBucket[];
  highlightedCell: string | null;
  onHoverCell: (value: string | null) => void;
}) {
  if (cells.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-stone-300 dark:border-stone-600 bg-stone-100/70 dark:bg-stone-900/40 p-4 text-sm text-stone-600 dark:text-stone-300">
        空間情報を持つレコーディングはありません。
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-stone-900 dark:text-stone-100">
        結果セル ({cells.length})
      </h3>
      <ul className="max-h-64 overflow-y-auto divide-y divide-stone-200 dark:divide-stone-700 rounded-lg border border-stone-200 dark:border-stone-700 bg-white dark:bg-stone-900">
        {cells.map((cell) => {
          const isActive = cell.h3Index === highlightedCell;
          return (
            <li key={cell.h3Index}>
              <button
                type="button"
                className={classNames(
                  "w-full px-3 py-2 text-left text-xs transition-colors",
                  isActive
                    ? "bg-emerald-100 dark:bg-emerald-900/30"
                    : "hover:bg-stone-100 dark:hover:bg-stone-800",
                )}
                onMouseEnter={() => onHoverCell(cell.h3Index)}
                onMouseLeave={() => {
                  if (highlightedCell === cell.h3Index) {
                    onHoverCell(null);
                  }
                }}
              >
                <div className="font-mono text-[11px] text-stone-600 dark:text-stone-300">
                  {cell.h3Index}
                </div>
                <div className="mt-1 flex flex-wrap gap-3 text-[11px] text-stone-500 dark:text-stone-400">
                  <span>録音: {cell.count}</span>
                  <span>データセット: {cell.datasetCount}</span>
                  <span
                    className={
                      cell.restrictedCount > 0
                        ? "text-amber-600 dark:text-amber-300"
                        : undefined
                    }
                  >
                    制限付き: {cell.restrictedCount}
                  </span>
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export default function CrossDatasetSearch() {
  const [projectId, setProjectId] = useState<string>("");
  const [siteId, setSiteId] = useState<string>("");
  const [recorderId, setRecorderId] = useState<string>("");
  const [targetTaxa, setTargetTaxa] = useState<string>("");
  const [dateStart, setDateStart] = useState<string>("");
  const [dateEnd, setDateEnd] = useState<string>("");
  const [timeStart, setTimeStart] = useState<string>("");
  const [timeEnd, setTimeEnd] = useState<string>("");
  const [h3Center, setH3Center] = useState<string | null>(null);
  const [h3Radius, setH3Radius] = useState<number>(0);
  const [searchParams, setSearchParams] =
    useState<Record<string, unknown> | null>(null);
  const [page, setPage] = useState(0);
  const [highlightedCell, setHighlightedCell] = useState<string | null>(null);

  const { projectOptions, siteOptions, recorderOptions } =
    useDatasetFilterOptions({ projectId });

  useEffect(() => {
    setSiteId("");
  }, [projectId]);

  const computedH3Cells = useMemo(() => {
    if (!h3Center) return [];
    return Array.from(new Set(gridDisk(h3Center, h3Radius)));
  }, [h3Center, h3Radius]);

  const buildQuery = useCallback(() => {
    const params: Record<string, unknown> = {};
    if (computedH3Cells.length > 0) {
      params.h3_cells = computedH3Cells;
    }
    if (dateStart) params.date_start = dateStart;
    if (dateEnd) params.date_end = dateEnd;
    const startSeconds = timeToSeconds(timeStart);
    const endSeconds = timeToSeconds(timeEnd);
    if (typeof startSeconds === "number") params.time_start = startSeconds;
    if (typeof endSeconds === "number") params.time_end = endSeconds;
    if (projectId) params.project_ids = [projectId];
    if (siteId) params.site_ids = [siteId];
    if (recorderId) params.recorder_ids = [recorderId];
    if (targetTaxa.trim()) {
      params.target_taxa = targetTaxa
        .split(",")
        .map((value) => value.trim())
        .filter(Boolean);
    }
    params.limit = DEFAULT_PAGE_SIZE;
    params.offset = 0;
    return params;
  }, [
    computedH3Cells,
    dateEnd,
    dateStart,
    projectId,
    recorderId,
    siteId,
    targetTaxa,
    timeEnd,
    timeStart,
  ]);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["cross-dataset-search", searchParams],
    queryFn: () => {
      if (!searchParams) {
        return Promise.resolve({ items: [], total: 0, limit: 0, offset: 0 });
      }
      return api.recordings.crossDatasetSearch(searchParams);
    },
    enabled: Boolean(searchParams),
  });

  const handleSearch = () => {
    const params = buildQuery();
    setPage(0);
    setHighlightedCell(null);
    setSearchParams(params);
  };

  const recordings = data?.items ?? [];
  const total = data?.total ?? 0;

  const cellBuckets = useMemo<CellBucket[]>(() => {
    const bucketMap = new Map<
      string,
      {
        count: number;
        publicCount: number;
        restrictedCount: number;
        datasetIds: Set<string>;
      }
    >();

    recordings.forEach((recording) => {
      const cell = getRecordingCell(recording);
      if (!cell) return;

      if (!bucketMap.has(cell)) {
        bucketMap.set(cell, {
          count: 0,
          publicCount: 0,
          restrictedCount: 0,
          datasetIds: new Set<string>(),
        });
      }

      const bucket = bucketMap.get(cell)!;
      bucket.count += 1;

      const visibility = recording.dataset?.visibility ?? "public";
      if (visibility === "restricted") {
        bucket.restrictedCount += 1;
      } else {
        bucket.publicCount += 1;
      }

      if (recording.dataset?.uuid) {
        bucket.datasetIds.add(recording.dataset.uuid);
      }
    });

    return Array.from(bucketMap.entries()).map(([h3Index, bucket]) => ({
      h3Index,
      count: bucket.count,
      publicCount: bucket.publicCount,
      restrictedCount: bucket.restrictedCount,
      datasetCount: bucket.datasetIds.size,
    }));
  }, [recordings]);

  const sortedCells = useMemo(
    () => [...cellBuckets].sort((a, b) => b.count - a.count),
    [cellBuckets],
  );

  useEffect(() => {
    if (cellBuckets.length === 0 && highlightedCell !== null) {
      setHighlightedCell(null);
    }
  }, [cellBuckets.length, highlightedCell]);

  useEffect(() => {
    if (
      !isLoading &&
      searchParams &&
      page > 0 &&
      recordings.length === 0 &&
      total > 0
    ) {
      setPage(0);
      setSearchParams((prev) =>
        prev ? { ...prev, offset: 0 } : prev,
      );
    }
  }, [isLoading, page, recordings.length, searchParams, total]);

  const showingStart =
    total === 0 ? 0 : page * DEFAULT_PAGE_SIZE + 1;
  const showingEnd =
    total === 0
      ? 0
      : Math.min(total, page * DEFAULT_PAGE_SIZE + recordings.length);
  const canGoPrev = page > 0;
  const canGoNext = showingEnd < total;

  const handlePrevPage = () => {
    if (!searchParams || !canGoPrev) return;
    const nextPage = page - 1;
    setPage(nextPage);
    setHighlightedCell(null);
    setSearchParams((prev) =>
      prev ? { ...prev, offset: nextPage * DEFAULT_PAGE_SIZE } : prev,
    );
  };

  const handleNextPage = () => {
    if (!searchParams || !canGoNext) return;
    const nextPage = page + 1;
    setPage(nextPage);
    setHighlightedCell(null);
    setSearchParams((prev) =>
      prev ? { ...prev, offset: nextPage * DEFAULT_PAGE_SIZE } : prev,
    );
  };

  const projectSelected =
    projectOptions.find((option) => option.value === projectId) ??
    projectOptions[0]!;
  const siteSelected =
    siteOptions.find((option) => option.value === siteId) ??
    siteOptions[0]!;
  const recorderSelected =
    recorderOptions.find((option) => option.value === recorderId) ??
    recorderOptions[0]!;

  return (
    <div className="grid gap-6 lg:grid-cols-[360px,1fr]">
      <Card className="space-y-4 p-4">
        <div className="space-y-3">
          <h2 className="text-base font-semibold text-stone-900 dark:text-stone-100">
            空間フィルター
          </h2>
          <H3HexPicker
            value={h3Center ?? undefined}
            onChange={setH3Center}
            height={260}
          />
          <Group
            label="検索半径"
            name="h3_radius"
            help="中心セルからの距離 (k-ring)"
          >
            <input
              type="range"
              min={0}
              max={2}
              value={h3Radius}
              onChange={(event) =>
                setH3Radius(Number.parseInt(event.target.value, 10))
              }
              className="w-full"
            />
            <p className="text-xs text-stone-500 dark:text-stone-400">
              {h3Radius === 0
                ? "中心セルのみ"
                : `中心から ${h3Radius} ステップ (${computedH3Cells.length} セル)`}
            </p>
          </Group>
        </div>

        <div className="space-y-3">
          <h2 className="text-base font-semibold text-stone-900 dark:text-stone-100">
            メタデータフィルター
          </h2>
          <Group label="Project" name="project_id">
            <Select
              label="Project"
              options={projectOptions}
              selected={projectSelected}
              onChange={setProjectId}
              placement="bottom-start"
            />
          </Group>
          <Group label="Site" name="site_id">
            <Select
              label="Site"
              options={siteOptions}
              selected={siteSelected}
              onChange={setSiteId}
              placement="bottom-start"
            />
          </Group>
          <Group label="Recorder" name="recorder_id">
            <Select
              label="Recorder"
              options={recorderOptions}
              selected={recorderSelected}
              onChange={setRecorderId}
              placement="bottom-start"
            />
          </Group>
          <Group
            label="Target taxa"
            name="target_taxa"
            help="カンマ区切りで入力"
          >
            <Input
              value={targetTaxa}
              onChange={(event) => setTargetTaxa(event.target.value)}
              placeholder="birds, bats"
            />
          </Group>
        </div>

        <div className="space-y-3">
          <h2 className="text-base font-semibold text-stone-900 dark:text-stone-100">
            時間フィルター
          </h2>
          <Group label="開始日" name="date_start">
            <Input
              type="date"
              value={dateStart}
              onChange={(event) => setDateStart(event.target.value)}
            />
          </Group>
          <Group label="終了日" name="date_end">
            <Input
              type="date"
              value={dateEnd}
              onChange={(event) => setDateEnd(event.target.value)}
            />
          </Group>
          <Group label="開始時刻" name="time_start">
            <Input
              type="time"
              value={timeStart}
              onChange={(event) => setTimeStart(event.target.value)}
            />
          </Group>
          <Group label="終了時刻" name="time_end">
            <Input
              type="time"
              value={timeEnd}
              onChange={(event) => setTimeEnd(event.target.value)}
            />
          </Group>
        </div>

        <div className="flex justify-end">
          <Button
            variant="primary"
            onClick={handleSearch}
            disabled={
              computedH3Cells.length === 0 &&
              !projectId &&
              !siteId &&
              !dateStart &&
              !dateEnd &&
              !timeStart &&
              !timeEnd &&
              !targetTaxa &&
              !recorderId
            }
          >
            検索
          </Button>
        </div>
      </Card>

      <Card className="p-4 space-y-4">
        <div>
          <h2 className="text-base font-semibold text-stone-900 dark:text-stone-100">
            検索結果
          </h2>
          <p className="text-xs text-stone-500 dark:text-stone-400">
            {searchParams
              ? `該当件数: ${total}`
              : "フィルターを設定して検索してください"}
          </p>
        </div>

        {isLoading ? (
          <div className="flex justify-center py-16">
            <Spinner />
          </div>
        ) : isError ? (
          <p className="text-sm text-red-600 dark:text-red-400">
            検索に失敗しました。フィルターを確認してください。
          </p>
        ) : recordings.length === 0 ? (
          <p className="text-sm text-stone-500 dark:text-stone-400">
            検索条件に一致するレコーディングはありません。
          </p>
        ) : (
          <>
            <div className="grid gap-4 xl:grid-cols-[minmax(260px,320px),1fr]">
              <ResultsMap
                cells={cellBuckets}
                searchCenter={h3Center}
                highlightedCell={highlightedCell}
                onHoverCell={setHighlightedCell}
              />
              <CellSummaryList
                cells={sortedCells}
                highlightedCell={highlightedCell}
                onHoverCell={setHighlightedCell}
              />
            </div>

            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-stone-200 dark:divide-stone-800 text-sm">
                <thead className="bg-stone-100 dark:bg-stone-800">
                  <tr>
                    <th className="px-3 py-2 text-left font-semibold">
                      ファイル
                    </th>
                    <th className="px-3 py-2 text-left font-semibold hidden lg:table-cell">
                      Dataset
                    </th>
                    <th className="px-3 py-2 text-left font-semibold hidden md:table-cell">
                      日時
                    </th>
                    <th className="px-3 py-2 text-left font-semibold hidden md:table-cell">
                      H3
                    </th>
                    <th className="px-3 py-2 text-right font-semibold hidden lg:table-cell">
                      Duration
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-stone-200 dark:divide-stone-800">
                  {recordings.map((recording) => {
                    const dataset = recording.dataset;
                    const project = dataset?.project;
                    const cell = getRecordingCell(recording);
                    const isActive =
                      highlightedCell !== null &&
                      cell !== null &&
                      highlightedCell === cell;

                    return (
                      <tr
                        key={recording.uuid}
                        className={classNames(
                          "bg-white dark:bg-stone-900 transition-colors",
                          isActive &&
                            "outline outline-2 outline-emerald-400/70 outline-offset-0",
                        )}
                        onMouseEnter={() => {
                          if (cell) {
                            setHighlightedCell(cell);
                          }
                        }}
                        onMouseLeave={() => {
                          if (cell && highlightedCell === cell) {
                            setHighlightedCell(null);
                          }
                        }}
                      >
                        <td className="px-3 py-2 font-mono text-xs">
                          {recording.path}
                        </td>
                        <td className="px-3 py-2 hidden lg:table-cell align-top">
                          {dataset ? (
                            <div className="flex flex-col gap-1">
                              {dataset.uuid ? (
                                <Link
                                  href={`/datasets/${dataset.uuid}/`}
                                  className="font-semibold text-emerald-600 dark:text-emerald-300 hover:underline"
                                >
                                  {dataset.name}
                                </Link>
                              ) : (
                                <span className="font-semibold text-stone-900 dark:text-stone-100">
                                  {dataset.name}
                                </span>
                              )}
                              <div className="flex flex-wrap items-center gap-2 text-xs text-stone-500 dark:text-stone-400">
                                <VisibilityBadge
                                  visibility={dataset.visibility}
                                />
                                <span>
                                  {project?.project_name ??
                                    dataset.project?.project_name ??
                                    dataset.project_id}
                                </span>
                              </div>
                              {dataset.primary_site?.site_name ? (
                                <div className="text-xs text-stone-500 dark:text-stone-400">
                                  {dataset.primary_site.site_name}
                                </div>
                              ) : null}
                            </div>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td className="px-3 py-2 hidden md:table-cell">
                          {recording.datetime
                            ? new Date(recording.datetime).toLocaleString()
                            : recording.date
                              ? new Date(recording.date).toLocaleDateString()
                              : "—"}
                        </td>
                        <td className="px-3 py-2 hidden md:table-cell font-mono text-xs">
                          {cell ?? "—"}
                        </td>
                        <td className="px-3 py-2 hidden lg:table-cell text-right">
                          {recording.duration
                            ? `${recording.duration.toFixed(1)}s`
                            : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="flex items-center justify-between text-xs text-stone-500 dark:text-stone-400">
              <span>
                表示:{" "}
                {recordings.length === 0
                  ? "0"
                  : `${showingStart}–${showingEnd}`}{" "}
                / {total}
              </span>
              <div className="flex gap-2">
                <Button
                  mode="text"
                  padding="px-2 py-1"
                  disabled={!searchParams || !canGoPrev}
                  onClick={handlePrevPage}
                >
                  前へ
                </Button>
                <Button
                  mode="text"
                  padding="px-2 py-1"
                  disabled={!searchParams || !canGoNext}
                  onClick={handleNextPage}
                >
                  次へ
                </Button>
              </div>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
