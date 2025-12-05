"use client";

import { X, MapPin, Calendar, Clock, Folder, Navigation, Radio } from "lucide-react";

import type { ExploreFilters } from "@/app/store/explore";
import { hasActiveFilters } from "@/app/store/explore";

type ActiveFiltersProps = {
  filters: ExploreFilters;
  onRemoveFilter: (key: keyof ExploreFilters, value?: unknown) => void;
  onClearAll: () => void;
};

type FilterChipProps = {
  icon: React.ReactNode;
  label: string;
  onRemove: () => void;
};

function FilterChip({ icon, label, onRemove }: FilterChipProps) {
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 rounded-full text-xs font-medium">
      <span aria-hidden="true">{icon}</span>
      <span className="max-w-32 truncate">{label}</span>
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove filter: ${label}`}
        className="ml-0.5 p-0.5 rounded-full hover:bg-emerald-200 dark:hover:bg-emerald-800 transition-colors focus:outline-none focus:ring-2 focus:ring-emerald-500"
      >
        <X className="w-3 h-3" aria-hidden="true" />
      </button>
    </span>
  );
}

function formatDateRange(start: string | null, end: string | null): string {
  if (start && end) {
    return `${start} - ${end}`;
  }
  if (start) {
    return `From ${start}`;
  }
  if (end) {
    return `Until ${end}`;
  }
  return "";
}

function formatTimeRange(
  start: number | null,
  end: number | null,
): string {
  const formatTime = (seconds: number) => {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
  };

  if (start !== null && end !== null) {
    return `${formatTime(start)} - ${formatTime(end)}`;
  }
  if (start !== null) {
    return `From ${formatTime(start)}`;
  }
  if (end !== null) {
    return `Until ${formatTime(end)}`;
  }
  return "";
}

export default function ActiveFilters({
  filters,
  onRemoveFilter,
  onClearAll,
}: ActiveFiltersProps) {
  if (!hasActiveFilters(filters)) {
    return null;
  }

  const chips: React.ReactNode[] = [];

  // Location filter
  if (filters.drawnShape) {
    const shapeLabel =
      filters.drawnShape.type === "rectangle"
        ? "Selected Area"
        : filters.drawnShape.type === "circle"
          ? "Circle Area"
          : "Polygon Area";
    chips.push(
      <FilterChip
        key="location"
        icon={<MapPin className="w-3 h-3" />}
        label={shapeLabel}
        onRemove={() => onRemoveFilter("drawnShape")}
      />,
    );
  }

  // Date range filter
  if (filters.dateStart || filters.dateEnd) {
    chips.push(
      <FilterChip
        key="date"
        icon={<Calendar className="w-3 h-3" />}
        label={formatDateRange(filters.dateStart, filters.dateEnd)}
        onRemove={() => {
          onRemoveFilter("dateStart");
          onRemoveFilter("dateEnd");
        }}
      />,
    );
  }

  // Time of day filter
  if (filters.timeStart !== null || filters.timeEnd !== null) {
    chips.push(
      <FilterChip
        key="time"
        icon={<Clock className="w-3 h-3" />}
        label={formatTimeRange(filters.timeStart, filters.timeEnd)}
        onRemove={() => {
          onRemoveFilter("timeStart");
          onRemoveFilter("timeEnd");
        }}
      />,
    );
  }

  // Project filter
  if (filters.projectIds.length > 0) {
    chips.push(
      <FilterChip
        key="project"
        icon={<Folder className="w-3 h-3" />}
        label={`Project: ${filters.projectIds[0]}`}
        onRemove={() => onRemoveFilter("projectIds")}
      />,
    );
  }

  // Site filter
  if (filters.siteIds.length > 0) {
    chips.push(
      <FilterChip
        key="site"
        icon={<Navigation className="w-3 h-3" />}
        label={`Site: ${filters.siteIds[0]}`}
        onRemove={() => onRemoveFilter("siteIds")}
      />,
    );
  }

  // Recorder filter
  if (filters.recorderIds.length > 0) {
    chips.push(
      <FilterChip
        key="recorder"
        icon={<Radio className="w-3 h-3" />}
        label={`Recorder: ${filters.recorderIds[0]}`}
        onRemove={() => onRemoveFilter("recorderIds")}
      />,
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs text-stone-500 dark:text-stone-400">
        Active filters:
      </span>
      {chips}
      <button
        type="button"
        onClick={onClearAll}
        className="text-xs text-stone-500 dark:text-stone-400 hover:text-stone-700 dark:hover:text-stone-200 underline"
      >
        Clear all
      </button>
    </div>
  );
}
