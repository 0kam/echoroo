"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import classNames from "classnames";
import { useCallback, useEffect, useMemo, useState } from "react";
import toast from "react-hot-toast";

import api from "@/app/api";
import { LocationIcon, TimeIcon, WarningIcon } from "@/lib/components/icons";
import Checkbox from "@/lib/components/inputs/Checkbox";
import { Group } from "@/lib/components/inputs";
import Slider from "@/lib/components/inputs/Slider";
import Button from "@/lib/components/ui/Button";
import { DialogOverlay } from "@/lib/components/ui/Dialog";
import Loading from "@/lib/components/ui/Loading";
import type {
  SpeciesFilter,
  SpeciesFilterApplication,
  SpeciesFilterApplicationCreate,
} from "@/lib/types";

// ============================================================================
// Props Interface
// ============================================================================

interface ApplySpeciesFilterDialogProps {
  runUuid: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onFilterApplied: (application: SpeciesFilterApplication) => void;
  /** Number of recordings lacking location data (optional) */
  recordingsWithoutLocation?: number;
  /** Total number of recordings (optional) */
  totalRecordings?: number;
}

// ============================================================================
// Status Styles
// ============================================================================

const THRESHOLD_SUGGESTIONS = [
  {
    value: 0.01,
    label: "1%",
    description: "Very permissive (keep rare visitors)",
  },
  {
    value: 0.03,
    label: "3%",
    description: "Recommended (default, balanced filtering)",
  },
  {
    value: 0.1,
    label: "10%",
    description: "Strict (only common species)",
  },
];

// ============================================================================
// Filter Selection Radio Item
// ============================================================================

function FilterRadioItem({
  filter,
  selected,
  onSelect,
}: {
  filter: SpeciesFilter;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={classNames(
        "w-full text-left p-4 rounded-lg border-2 transition-all",
        selected
          ? "border-emerald-500 bg-emerald-50 dark:bg-emerald-900/20"
          : "border-stone-200 dark:border-stone-700 hover:border-stone-300 dark:hover:border-stone-600",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <div
              className={classNames(
                "w-4 h-4 rounded-full border-2 flex items-center justify-center",
                selected
                  ? "border-emerald-500 bg-emerald-500"
                  : "border-stone-400 dark:border-stone-500",
              )}
            >
              {selected && (
                <div className="w-2 h-2 rounded-full bg-white" />
              )}
            </div>
            <span className="font-medium text-stone-900 dark:text-stone-100">
              {filter.display_name}
            </span>
            <span className="text-xs px-2 py-0.5 rounded-full bg-stone-100 dark:bg-stone-700 text-stone-600 dark:text-stone-400">
              v{filter.version}
            </span>
          </div>
          {filter.description && (
            <p className="mt-1 text-sm text-stone-600 dark:text-stone-400 line-clamp-2 ml-6">
              {filter.description}
            </p>
          )}
          <div className="flex items-center gap-3 mt-2 ml-6">
            {filter.requires_location && (
              <span className="flex items-center gap-1 text-xs text-stone-500 dark:text-stone-400">
                <LocationIcon className="w-3.5 h-3.5" />
                Location
              </span>
            )}
            {filter.requires_date && (
              <span className="flex items-center gap-1 text-xs text-stone-500 dark:text-stone-400">
                <TimeIcon className="w-3.5 h-3.5" />
                Date
              </span>
            )}
            <span className="text-xs px-2 py-0.5 rounded-full bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300">
              {filter.provider}
            </span>
          </div>
        </div>
      </div>
    </button>
  );
}

// ============================================================================
// Location Warning Component
// ============================================================================

function LocationWarning({
  recordingsWithoutLocation,
  totalRecordings,
}: {
  recordingsWithoutLocation: number;
  totalRecordings: number;
}) {
  const percentage = totalRecordings > 0
    ? ((recordingsWithoutLocation / totalRecordings) * 100).toFixed(0)
    : 0;

  return (
    <div className="flex items-start gap-3 p-3 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800">
      <WarningIcon className="w-5 h-5 text-amber-600 dark:text-amber-400 flex-shrink-0 mt-0.5" />
      <div className="flex-1 text-sm">
        <p className="font-medium text-amber-800 dark:text-amber-200">
          Location Data Warning
        </p>
        <p className="text-amber-700 dark:text-amber-300 mt-1">
          {recordingsWithoutLocation} recordings ({percentage}%) lack location
          coordinates. Detections from these recordings will be skipped by the
          filter.
        </p>
      </div>
    </div>
  );
}

// ============================================================================
// Empty State Component
// ============================================================================

function EmptyState({ onClose }: { onClose: () => void }) {
  return (
    <div className="text-center py-8">
      <div className="mx-auto w-12 h-12 rounded-full bg-stone-100 dark:bg-stone-700 flex items-center justify-center mb-4">
        <LocationIcon className="w-6 h-6 text-stone-400" />
      </div>
      <h3 className="text-lg font-medium text-stone-900 dark:text-stone-100 mb-2">
        No species filters available
      </h3>
      <p className="text-sm text-stone-600 dark:text-stone-400 mb-6">
        Contact your administrator to enable geographic occurrence filtering
        for your instance.
      </p>
      <Button variant="secondary" onClick={onClose}>
        Close
      </Button>
    </div>
  );
}

// ============================================================================
// Main Component
// ============================================================================

export default function ApplySpeciesFilterDialog({
  runUuid,
  open,
  onOpenChange,
  onFilterApplied,
  recordingsWithoutLocation = 0,
  totalRecordings = 0,
}: ApplySpeciesFilterDialogProps) {
  // State
  const [selectedFilterSlug, setSelectedFilterSlug] = useState<string | null>(null);
  const [threshold, setThreshold] = useState<number>(0.03);
  const [applyToAll, setApplyToAll] = useState<boolean>(true);

  // Fetch available filters
  const {
    data: filters,
    isLoading: filtersLoading,
    error: filtersError,
  } = useQuery({
    queryKey: ["species_filters"],
    queryFn: () => api.speciesFilters.listFilters(),
    enabled: open,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });

  // Get active filters only
  const activeFilters = useMemo(
    () => filters?.filter((f) => f.is_active) ?? [],
    [filters],
  );

  // Set default filter and threshold when filters load
  useEffect(() => {
    if (activeFilters.length > 0 && !selectedFilterSlug) {
      const firstFilter = activeFilters[0];
      setSelectedFilterSlug(firstFilter.slug);
      setThreshold(firstFilter.default_threshold);
    }
  }, [activeFilters, selectedFilterSlug]);

  // Get selected filter
  const selectedFilter = useMemo(
    () => activeFilters.find((f) => f.slug === selectedFilterSlug),
    [activeFilters, selectedFilterSlug],
  );

  // Apply filter mutation
  const applyMutation = useMutation({
    mutationFn: (data: SpeciesFilterApplicationCreate) =>
      api.speciesFilters.applyFilter(runUuid, data),
    onSuccess: (application) => {
      toast.success("Species filter applied successfully");
      onFilterApplied(application);
      onOpenChange(false);
    },
    onError: (error) => {
      const message =
        error instanceof Error && "response" in error
          ? (error as { response?: { data?: { message?: string } } }).response
              ?.data?.message
          : null;
      toast.error(message || "Failed to apply species filter");
      console.error("Failed to apply species filter:", error);
    },
  });

  // Handlers
  const handleClose = useCallback(() => {
    onOpenChange(false);
  }, [onOpenChange]);

  const handleFilterSelect = useCallback(
    (filter: SpeciesFilter) => {
      setSelectedFilterSlug(filter.slug);
      setThreshold(filter.default_threshold);
    },
    [],
  );

  const handleThresholdChange = useCallback((value: number | number[]) => {
    const val = Array.isArray(value) ? value[0] : value;
    setThreshold(val);
  }, []);

  const handleApply = useCallback(() => {
    if (!selectedFilterSlug) return;

    applyMutation.mutate({
      filter_slug: selectedFilterSlug,
      threshold,
      apply_to_all_detections: applyToAll,
    });
  }, [selectedFilterSlug, threshold, applyToAll, applyMutation]);

  // Show location warning
  const showLocationWarning =
    recordingsWithoutLocation > 0 &&
    selectedFilter?.requires_location;

  return (
    <DialogOverlay
      title="Apply Species Filter"
      isOpen={open}
      onClose={handleClose}
    >
      <div className="w-full max-w-lg">
        <p className="text-sm text-stone-600 dark:text-stone-400 mb-6">
          Filter species detections based on geographic and temporal occurrence
          probability data.
        </p>

        {/* Loading State */}
        {filtersLoading && (
          <div className="flex items-center justify-center py-8">
            <Loading />
          </div>
        )}

        {/* Error State */}
        {filtersError && (
          <div className="text-center py-8 text-red-600 dark:text-red-400">
            Failed to load species filters. Please try again.
          </div>
        )}

        {/* Empty State */}
        {!filtersLoading && !filtersError && activeFilters.length === 0 && (
          <EmptyState onClose={handleClose} />
        )}

        {/* Main Content */}
        {!filtersLoading && !filtersError && activeFilters.length > 0 && (
          <div className="space-y-6">
            {/* Filter Selection */}
            <div>
              <h3 className="text-sm font-medium text-stone-900 dark:text-stone-100 mb-3">
                Select Filter
              </h3>
              <div className="space-y-2">
                {activeFilters.map((filter) => (
                  <FilterRadioItem
                    key={filter.uuid}
                    filter={filter}
                    selected={filter.slug === selectedFilterSlug}
                    onSelect={() => handleFilterSelect(filter)}
                  />
                ))}
              </div>
            </div>

            {/* Threshold Slider */}
            <div>
              <Group
                name="threshold"
                label="Occurrence Threshold"
                help="Species with occurrence probability below this threshold will be excluded."
              >
                <div className="flex items-center gap-4 mt-2">
                  <div className="flex-1">
                    <Slider
                      label="Threshold"
                      minValue={0}
                      maxValue={1}
                      step={0.01}
                      value={threshold}
                      onChange={handleThresholdChange}
                      formatter={(val) => `${(val * 100).toFixed(0)}%`}
                    />
                  </div>
                  <span className="w-12 text-right text-sm font-medium text-stone-900 dark:text-stone-100">
                    {(threshold * 100).toFixed(0)}%
                  </span>
                </div>
              </Group>

              {/* Suggested Thresholds */}
              <div className="mt-3 p-3 rounded-lg bg-stone-50 dark:bg-stone-800/50">
                <p className="text-xs font-medium text-stone-700 dark:text-stone-300 mb-2">
                  Suggested thresholds:
                </p>
                <div className="space-y-1">
                  {THRESHOLD_SUGGESTIONS.map((suggestion) => (
                    <button
                      key={suggestion.value}
                      type="button"
                      onClick={() => setThreshold(suggestion.value)}
                      className={classNames(
                        "w-full text-left text-xs px-2 py-1 rounded transition-colors",
                        threshold === suggestion.value
                          ? "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300"
                          : "hover:bg-stone-100 dark:hover:bg-stone-700 text-stone-600 dark:text-stone-400",
                      )}
                    >
                      <span className="font-medium">{suggestion.label}</span>
                      <span className="ml-2">{suggestion.description}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Apply Scope */}
            <div>
              <h3 className="text-sm font-medium text-stone-900 dark:text-stone-100 mb-3">
                Apply Scope
              </h3>
              <label className="flex items-center gap-3 cursor-pointer">
                <Checkbox
                  checked={applyToAll}
                  onChange={(e) =>
                    setApplyToAll((e.target as HTMLInputElement).checked)
                  }
                  className="w-4 h-4 rounded border-stone-300 dark:border-stone-600 text-emerald-500 focus:ring-emerald-500"
                />
                <span className="text-sm text-stone-700 dark:text-stone-300">
                  Apply to all detections
                </span>
              </label>
              {!applyToAll && (
                <p className="ml-7 mt-1 text-xs text-stone-500 dark:text-stone-400">
                  Only unreviewed detections will be filtered
                </p>
              )}
            </div>

            {/* Location Warning */}
            {showLocationWarning && (
              <LocationWarning
                recordingsWithoutLocation={recordingsWithoutLocation}
                totalRecordings={totalRecordings}
              />
            )}

            {/* Actions */}
            <div className="flex justify-end gap-3 pt-4 border-t border-stone-200 dark:border-stone-700">
              <Button variant="secondary" onClick={handleClose}>
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={handleApply}
                disabled={!selectedFilterSlug || applyMutation.isPending}
              >
                {applyMutation.isPending ? "Applying..." : "Apply Filter"}
              </Button>
            </div>
          </div>
        )}
      </div>
    </DialogOverlay>
  );
}
