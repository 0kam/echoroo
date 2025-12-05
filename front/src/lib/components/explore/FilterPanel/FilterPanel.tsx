"use client";

import { useState, useCallback } from "react";
import { ChevronDown, ChevronRight, X } from "lucide-react";
import classNames from "classnames";

import Button from "@/lib/components/ui/Button";
import type { ExploreFilters, DrawnShape } from "@/app/store/explore";
import LocationFilter from "./LocationFilter";
import TimeFilter from "./TimeFilter";
import MetadataFilter from "./MetadataFilter";

type FilterPanelProps = {
  isOpen: boolean;
  onClose: () => void;
  filters: ExploreFilters;
  onFiltersChange: (filters: Partial<ExploreFilters>) => void;
  onClearAll: () => void;
  /** Whether this panel is used for mobile (slide-out) or desktop (fixed sidebar) */
  isMobile?: boolean;
};

type CollapsibleSectionProps = {
  title: string;
  isOpen: boolean;
  onToggle: () => void;
  children: React.ReactNode;
  hasActiveFilter?: boolean;
};

function CollapsibleSection({
  title,
  isOpen,
  onToggle,
  children,
  hasActiveFilter = false,
}: CollapsibleSectionProps) {
  const sectionId = `section-${title.toLowerCase().replace(/\s+/g, "-")}`;
  const contentId = `${sectionId}-content`;

  return (
    <div className="border-b border-stone-200 dark:border-stone-700">
      <button
        type="button"
        id={sectionId}
        onClick={onToggle}
        aria-expanded={isOpen}
        aria-controls={contentId}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-stone-50 dark:hover:bg-stone-800 transition-colors"
      >
        <span className="flex items-center gap-2">
          <span className="text-sm font-medium text-stone-900 dark:text-stone-100">
            {title}
          </span>
          {hasActiveFilter && (
            <span
              className="w-2 h-2 rounded-full bg-emerald-500"
              aria-label="Filter active"
            />
          )}
        </span>
        {isOpen ? (
          <ChevronDown className="w-4 h-4 text-stone-500" aria-hidden="true" />
        ) : (
          <ChevronRight className="w-4 h-4 text-stone-500" aria-hidden="true" />
        )}
      </button>
      {isOpen && (
        <div id={contentId} role="region" aria-labelledby={sectionId} className="px-4 pb-4">
          {children}
        </div>
      )}
    </div>
  );
}

export default function FilterPanel({
  isOpen,
  onClose,
  filters,
  onFiltersChange,
  onClearAll,
  isMobile = true,
}: FilterPanelProps) {
  const [openSections, setOpenSections] = useState<Set<string>>(
    new Set(["location"]),
  );

  const toggleSection = useCallback((section: string) => {
    setOpenSections((prev) => {
      const next = new Set(prev);
      if (next.has(section)) {
        next.delete(section);
      } else {
        next.add(section);
      }
      return next;
    });
  }, []);

  const handleLocationChange = useCallback(
    (shape: DrawnShape | null) => {
      onFiltersChange({
        drawnShape: shape,
        bbox: shape?.bounds ?? null,
      });
    },
    [onFiltersChange],
  );

  const handleProjectChange = useCallback(
    (projectId: string) => {
      onFiltersChange({
        projectIds: projectId ? [projectId] : [],
        siteIds: [], // Reset site when project changes
      });
    },
    [onFiltersChange],
  );

  const handleSiteChange = useCallback(
    (siteId: string) => {
      onFiltersChange({
        siteIds: siteId ? [siteId] : [],
      });
    },
    [onFiltersChange],
  );

  const handleRecorderChange = useCallback(
    (recorderId: string) => {
      onFiltersChange({
        recorderIds: recorderId ? [recorderId] : [],
      });
    },
    [onFiltersChange],
  );

  const hasLocationFilter = filters.drawnShape !== null;
  const hasTimeFilter =
    filters.dateStart !== null ||
    filters.dateEnd !== null ||
    filters.timeStart !== null ||
    filters.timeEnd !== null;
  const hasMetadataFilter =
    filters.projectIds.length > 0 ||
    filters.siteIds.length > 0 ||
    filters.recorderIds.length > 0;

  // Map height: 500px for desktop sidebar, 300px for mobile slide-out
  const mapHeight = isMobile ? 300 : 500;

  // Mobile: slide-out panel with transform animation
  // Desktop: static sidebar (no transform, always visible)
  if (isMobile) {
    return (
      <div
        className={classNames(
          "fixed inset-y-0 left-0 z-[1000] w-[400px] max-w-[90vw] bg-white dark:bg-stone-900 border-r border-stone-200 dark:border-stone-700 shadow-lg transform transition-transform duration-300 ease-in-out",
          isOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-stone-200 dark:border-stone-700">
          <h2 className="text-lg font-semibold text-stone-900 dark:text-stone-100">
            Filters
          </h2>
          <div className="flex items-center gap-2">
            <Button
              mode="text"
              padding="px-2 py-1"
              className="text-xs"
              onClick={onClearAll}
            >
              Clear All
            </Button>
            <button
              type="button"
              onClick={onClose}
              className="p-1 rounded-md hover:bg-stone-100 dark:hover:bg-stone-800 transition-colors"
            >
              <X className="w-5 h-5 text-stone-500" />
            </button>
          </div>
        </div>

        {/* Filter Sections */}
        <div className="overflow-y-auto h-[calc(100vh-60px)]">
          <CollapsibleSection
            title="Location"
            isOpen={openSections.has("location")}
            onToggle={() => toggleSection("location")}
            hasActiveFilter={hasLocationFilter}
          >
            <LocationFilter
              value={filters.drawnShape}
              onChange={handleLocationChange}
              height={mapHeight}
            />
          </CollapsibleSection>

          <CollapsibleSection
            title="Time"
            isOpen={openSections.has("time")}
            onToggle={() => toggleSection("time")}
            hasActiveFilter={hasTimeFilter}
          >
            <TimeFilter
              dateStart={filters.dateStart}
              dateEnd={filters.dateEnd}
              timeStart={filters.timeStart}
              timeEnd={filters.timeEnd}
              onDateStartChange={(value) =>
                onFiltersChange({ dateStart: value })
              }
              onDateEndChange={(value) => onFiltersChange({ dateEnd: value })}
              onTimeStartChange={(value) =>
                onFiltersChange({ timeStart: value })
              }
              onTimeEndChange={(value) => onFiltersChange({ timeEnd: value })}
            />
          </CollapsibleSection>

          <CollapsibleSection
            title="Metadata"
            isOpen={openSections.has("metadata")}
            onToggle={() => toggleSection("metadata")}
            hasActiveFilter={hasMetadataFilter}
          >
            <MetadataFilter
              projectIds={filters.projectIds}
              siteIds={filters.siteIds}
              recorderIds={filters.recorderIds}
              onProjectChange={handleProjectChange}
              onSiteChange={handleSiteChange}
              onRecorderChange={handleRecorderChange}
            />
          </CollapsibleSection>
        </div>
      </div>
    );
  }

  // Desktop: fixed sidebar (no transform, always visible)
  return (
    <div className="h-full w-full bg-white dark:bg-stone-900 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-stone-200 dark:border-stone-700 flex-shrink-0">
        <h2 className="text-lg font-semibold text-stone-900 dark:text-stone-100">
          Filters
        </h2>
        <Button
          mode="text"
          padding="px-2 py-1"
          className="text-xs"
          onClick={onClearAll}
        >
          Clear All
        </Button>
      </div>

      {/* Filter Sections */}
      <div className="overflow-y-auto flex-1">
        <CollapsibleSection
          title="Location"
          isOpen={openSections.has("location")}
          onToggle={() => toggleSection("location")}
          hasActiveFilter={hasLocationFilter}
        >
          <LocationFilter
            value={filters.drawnShape}
            onChange={handleLocationChange}
            height={mapHeight}
          />
        </CollapsibleSection>

        <CollapsibleSection
          title="Time"
          isOpen={openSections.has("time")}
          onToggle={() => toggleSection("time")}
          hasActiveFilter={hasTimeFilter}
        >
          <TimeFilter
            dateStart={filters.dateStart}
            dateEnd={filters.dateEnd}
            timeStart={filters.timeStart}
            timeEnd={filters.timeEnd}
            onDateStartChange={(value) =>
              onFiltersChange({ dateStart: value })
            }
            onDateEndChange={(value) => onFiltersChange({ dateEnd: value })}
            onTimeStartChange={(value) =>
              onFiltersChange({ timeStart: value })
            }
            onTimeEndChange={(value) => onFiltersChange({ timeEnd: value })}
          />
        </CollapsibleSection>

        <CollapsibleSection
          title="Metadata"
          isOpen={openSections.has("metadata")}
          onToggle={() => toggleSection("metadata")}
          hasActiveFilter={hasMetadataFilter}
        >
          <MetadataFilter
            projectIds={filters.projectIds}
            siteIds={filters.siteIds}
            recorderIds={filters.recorderIds}
            onProjectChange={handleProjectChange}
            onSiteChange={handleSiteChange}
            onRecorderChange={handleRecorderChange}
          />
        </CollapsibleSection>
      </div>
    </div>
  );
}
