"use client";

import { useQuery } from "@tanstack/react-query";
import classNames from "classnames";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import api from "@/app/api";
import { CheckIcon, CloseIcon } from "@/lib/components/icons";
import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import Empty from "@/lib/components/ui/Empty";
import Loading from "@/lib/components/ui/Loading";
import Tab from "@/lib/components/ui/Tab";
import type { SpeciesFilterResultItem } from "@/lib/types";

// ============================================================================
// Types
// ============================================================================

type TabType = "passed" | "excluded";
type SortField = "species_name" | "detection_count" | "occurrence_probability";
type SortDirection = "asc" | "desc";

interface SortConfig {
  field: SortField;
  direction: SortDirection;
}

interface SpeciesFilterResultsPanelProps {
  runUuid: string;
  applicationUuid: string;
  locale?: string;
  className?: string;
  /** Callback when the user wants to convert to annotation project */
  onConvertToAnnotation?: () => void;
}

// ============================================================================
// Table Row Component
// ============================================================================

function SpeciesRow({
  item,
  isPassed,
}: {
  item: SpeciesFilterResultItem;
  isPassed: boolean;
}) {
  const probabilityPercent =
    item.occurrence_probability !== null
      ? (item.occurrence_probability * 100).toFixed(1)
      : null;

  return (
    <tr className="transition-colors hover:bg-stone-50 dark:hover:bg-stone-800">
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <div
            className={classNames(
              "flex h-5 w-5 shrink-0 items-center justify-center rounded-full",
              isPassed
                ? "bg-emerald-100 dark:bg-emerald-900/40"
                : "bg-red-100 dark:bg-red-900/40",
            )}
          >
            {isPassed ? (
              <CheckIcon className="h-3 w-3 text-emerald-600 dark:text-emerald-400" />
            ) : (
              <CloseIcon className="h-3 w-3 text-red-600 dark:text-red-400" />
            )}
          </div>
          <div className="min-w-0">
            <div className="font-medium text-stone-900 dark:text-stone-100">
              {item.species_name ?? item.gbif_taxon_key}
            </div>
            {item.common_name && (
              <div className="text-xs text-stone-500 dark:text-stone-400">
                {item.common_name}
              </div>
            )}
          </div>
        </div>
      </td>
      <td className="whitespace-nowrap px-4 py-3 text-right">
        {probabilityPercent !== null ? (
          <span
            className={classNames(
              "inline-block rounded px-2 py-0.5 text-sm font-medium",
              parseFloat(probabilityPercent) >= 50
                ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300"
                : parseFloat(probabilityPercent) >= 20
                  ? "bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300"
                  : "bg-stone-100 text-stone-600 dark:bg-stone-800 dark:text-stone-400",
            )}
          >
            {probabilityPercent}%
          </span>
        ) : (
          <span className="text-stone-400 dark:text-stone-500">-</span>
        )}
      </td>
      <td className="whitespace-nowrap px-4 py-3 text-right text-stone-600 dark:text-stone-400">
        {item.detection_count.toLocaleString()}
      </td>
    </tr>
  );
}

// ============================================================================
// Main Component
// ============================================================================

/**
 * Get the browser locale in a format suitable for the API.
 * Converts browser locale (e.g., "ja-JP") to API format (e.g., "ja").
 */
function getBrowserLocale(): string {
  if (typeof navigator === "undefined") return "ja";
  const browserLocale = navigator.language || "ja";
  // Extract base language code (e.g., "ja-JP" -> "ja", "en-US" -> "en_us")
  const [lang, region] = browserLocale.toLowerCase().split("-");
  if (region) {
    return `${lang}_${region}`;
  }
  return lang;
}

export default function SpeciesFilterResultsPanel({
  runUuid,
  applicationUuid,
  locale,
  className,
  onConvertToAnnotation,
}: SpeciesFilterResultsPanelProps) {
  const [activeTab, setActiveTab] = useState<TabType>("passed");
  const [sortConfig, setSortConfig] = useState<SortConfig>({
    field: "detection_count",
    direction: "desc",
  });

  // Use provided locale or fall back to browser locale
  const effectiveLocale = locale ?? getBrowserLocale();

  // Fetch filter species results
  const {
    data: results,
    isLoading,
    error,
  } = useQuery({
    queryKey: [
      "foundation_model_run",
      runUuid,
      "filter_application",
      applicationUuid,
      "species",
      effectiveLocale,
    ],
    queryFn: () => api.speciesFilters.getFilterSpecies(runUuid, applicationUuid, effectiveLocale),
  });

  // Get current list based on active tab
  const currentList = useMemo(() => {
    if (!results) return [];
    return activeTab === "passed" ? results.passed : results.excluded;
  }, [results, activeTab]);

  // Sort the list
  const sortedList = useMemo(() => {
    const sorted = [...currentList];
    sorted.sort((a, b) => {
      let aVal: string | number | null;
      let bVal: string | number | null;

      switch (sortConfig.field) {
        case "species_name":
          aVal = (a.species_name ?? a.gbif_taxon_key).toLowerCase();
          bVal = (b.species_name ?? b.gbif_taxon_key).toLowerCase();
          break;
        case "detection_count":
          aVal = a.detection_count;
          bVal = b.detection_count;
          break;
        case "occurrence_probability":
          aVal = a.occurrence_probability ?? -1;
          bVal = b.occurrence_probability ?? -1;
          break;
        default:
          return 0;
      }

      if (aVal < bVal) return sortConfig.direction === "asc" ? -1 : 1;
      if (aVal > bVal) return sortConfig.direction === "asc" ? 1 : -1;
      return 0;
    });
    return sorted;
  }, [currentList, sortConfig]);

  const handleSort = useCallback((field: SortField) => {
    setSortConfig((prev) => ({
      field,
      direction: prev.field === field && prev.direction === "desc" ? "asc" : "desc",
    }));
  }, []);

  const getSortIcon = (field: SortField) => {
    if (sortConfig.field !== field) {
      return <ArrowUpDown className="h-3 w-3 text-stone-400" />;
    }
    return sortConfig.direction === "asc" ? (
      <ArrowUp className="h-3 w-3" />
    ) : (
      <ArrowDown className="h-3 w-3" />
    );
  };

  if (isLoading) {
    return (
      <Card className={className}>
        <div className="flex h-48 items-center justify-center">
          <Loading text="Loading species results..." />
        </div>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className={className}>
        <div className="p-4 text-center text-red-600 dark:text-red-400">
          Failed to load species filter results
        </div>
      </Card>
    );
  }

  if (!results) {
    return null;
  }

  return (
    <Card className={classNames("space-y-4", className)}>
      {/* Header */}
      <div>
        <h3 className="text-sm font-medium text-stone-900 dark:text-stone-100">
          Species Filter Results
        </h3>
        <p className="mt-1 text-xs text-stone-500 dark:text-stone-400">
          {results.total_passed} species passed, {results.total_excluded} species
          excluded
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 border-b border-stone-200 pb-2 dark:border-stone-700">
        <Tab
          active={activeTab === "passed"}
          onClick={() => setActiveTab("passed")}
        >
          <CheckIcon className="h-4 w-4 text-emerald-500" />
          Passed ({results.total_passed})
        </Tab>
        <Tab
          active={activeTab === "excluded"}
          onClick={() => setActiveTab("excluded")}
        >
          <CloseIcon className="h-4 w-4 text-red-500" />
          Excluded ({results.total_excluded})
        </Tab>
      </div>

      {/* Table */}
      {sortedList.length === 0 ? (
        <Empty>
          <p>
            {activeTab === "passed"
              ? "No species passed the filter"
              : "No species were excluded"}
          </p>
        </Empty>
      ) : (
        <div className="overflow-hidden rounded-lg border border-stone-200 dark:border-stone-700">
          <div className="max-h-96 overflow-y-auto">
            <table className="min-w-full divide-y divide-stone-200 dark:divide-stone-700">
              <thead className="sticky top-0 bg-stone-50 dark:bg-stone-800">
                <tr>
                  <th
                    scope="col"
                    className="cursor-pointer px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-stone-500 dark:text-stone-400"
                    onClick={() => handleSort("species_name")}
                  >
                    <div className="flex items-center gap-1">
                      Species
                      {getSortIcon("species_name")}
                    </div>
                  </th>
                  <th
                    scope="col"
                    className="cursor-pointer px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-stone-500 dark:text-stone-400"
                    onClick={() => handleSort("occurrence_probability")}
                  >
                    <div className="flex items-center justify-end gap-1">
                      Occurrence
                      {getSortIcon("occurrence_probability")}
                    </div>
                  </th>
                  <th
                    scope="col"
                    className="cursor-pointer px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-stone-500 dark:text-stone-400"
                    onClick={() => handleSort("detection_count")}
                  >
                    <div className="flex items-center justify-end gap-1">
                      Detections
                      {getSortIcon("detection_count")}
                    </div>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-200 bg-white dark:divide-stone-700 dark:bg-stone-900">
                {sortedList.map((item) => (
                  <SpeciesRow
                    key={item.gbif_taxon_key}
                    item={item}
                    isPassed={activeTab === "passed"}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Convert to Annotation Project Button */}
      {onConvertToAnnotation && (
        <div className="pt-4 border-t border-stone-200 dark:border-stone-700">
          <Button
            mode="filled"
            variant="primary"
            onClick={onConvertToAnnotation}
            className="w-full justify-center"
          >
            Convert to Annotation Project
          </Button>
        </div>
      )}
    </Card>
  );
}
