"use client";

import { useCallback, useEffect, useMemo, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import api from "@/app/api";
import {
  useExploreStore,
  hasActiveFilters,
  type ExploreFilters,
} from "@/app/store/explore";

import SearchBar from "./SearchBar";
import ActiveFilters from "./ActiveFilters";
import { FilterPanel } from "./FilterPanel";
import { ViewToggle, MapView, TimelineView, TableView } from "./ResultsArea";

export default function ExploreLayout() {
  const {
    viewMode,
    filters,
    isFilterPanelOpen,
    page,
    pageSize,
    setViewMode,
    setFilters,
    clearFilters,
    removeFilter,
    toggleFilterPanel,
    setPage,
  } = useExploreStore();

  // Build query parameters from filters
  const queryParams = useMemo(() => {
    const params: Record<string, unknown> = {
      limit: pageSize,
      offset: page * pageSize,
    };

    if (filters.bbox && filters.bbox.length === 4) {
      params.bbox = filters.bbox;
    }

    if (filters.dateStart) {
      params.date_start = filters.dateStart;
    }

    if (filters.dateEnd) {
      params.date_end = filters.dateEnd;
    }

    if (filters.timeStart !== null) {
      params.time_start = filters.timeStart;
    }

    if (filters.timeEnd !== null) {
      params.time_end = filters.timeEnd;
    }

    if (filters.projectIds.length > 0) {
      params.project_ids = filters.projectIds;
    }

    if (filters.siteIds.length > 0) {
      params.site_ids = filters.siteIds;
    }

    if (filters.recorderIds.length > 0) {
      params.recorder_ids = filters.recorderIds;
    }

    return params;
  }, [filters, page, pageSize]);

  // Fetch recordings
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["explore-recordings", queryParams],
    queryFn: () => api.recordings.crossDatasetSearch(queryParams),
    staleTime: 30000, // Cache for 30 seconds
  });

  const recordings = data?.items ?? [];
  const total = data?.total ?? 0;

  const handleSearch = useCallback(() => {
    refetch();
  }, [refetch]);

  const handleFiltersChange = useCallback(
    (newFilters: Partial<ExploreFilters>) => {
      setFilters(newFilters);
    },
    [setFilters],
  );

  const handleRemoveFilter = useCallback(
    (key: keyof ExploreFilters, value?: unknown) => {
      removeFilter(key, value);
    },
    [removeFilter],
  );

  // Handle Escape key to close mobile filter panel
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isFilterPanelOpen) {
        toggleFilterPanel();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isFilterPanelOpen, toggleFilterPanel]);

  // Memoize the view rendering to avoid unnecessary re-renders
  const currentView: ReactNode = useMemo(() => {
    switch (viewMode) {
      case "map":
        return (
          <MapView
            recordings={recordings}
            drawnShape={filters.drawnShape}
            isLoading={isLoading}
          />
        );
      case "timeline":
        return <TimelineView recordings={recordings} isLoading={isLoading} />;
      case "table":
        return (
          <TableView
            recordings={recordings}
            isLoading={isLoading}
            page={page}
            pageSize={pageSize}
            total={total}
            onPageChange={setPage}
          />
        );
      default:
        return null;
    }
  }, [viewMode, recordings, filters.drawnShape, isLoading, page, pageSize, total, setPage]);

  return (
    <div className="min-h-screen">
      {/* Mobile: Filter Panel (Slide-out) - Only visible on mobile */}
      <div className="lg:hidden">
        <FilterPanel
          isOpen={isFilterPanelOpen}
          onClose={toggleFilterPanel}
          filters={filters}
          onFiltersChange={handleFiltersChange}
          onClearAll={clearFilters}
          isMobile={true}
        />
      </div>

      {/* Mobile: Overlay when filter panel is open */}
      {isFilterPanelOpen && (
        <div
          role="presentation"
          aria-hidden="true"
          className="fixed inset-0 bg-black/20 z-[999] lg:hidden"
          onClick={toggleFilterPanel}
        />
      )}

      {/* Desktop: Two-column layout */}
      <div className="flex">
        {/* Desktop: Fixed Sidebar Filter Panel */}
        <aside className="hidden lg:block w-[400px] flex-shrink-0 h-screen sticky top-0 border-r border-stone-200 dark:border-stone-700 bg-white dark:bg-stone-900">
          <FilterPanel
            isOpen={true}
            onClose={() => {}}
            filters={filters}
            onFiltersChange={handleFiltersChange}
            onClearAll={clearFilters}
            isMobile={false}
          />
        </aside>

        {/* Main Content */}
        <main className="flex-1 min-w-0">
          <div className="container mx-auto px-4 py-6 space-y-6 lg:max-w-none">
            {/* Header */}
            <div>
              <h1 className="text-3xl font-bold text-stone-900 dark:text-stone-100">
                Explore Recordings
              </h1>
              <p className="text-stone-600 dark:text-stone-400 mt-1">
                Search and discover audio recordings across all accessible datasets
              </p>
            </div>

            {/* Search Bar */}
            <SearchBar
              value={filters.searchQuery}
              onChange={(value) => setFilters({ searchQuery: value })}
              onSearch={handleSearch}
              onToggleFilters={toggleFilterPanel}
              isFiltersOpen={isFilterPanelOpen}
              resultCount={total}
              isLoading={isLoading}
            />

            {/* Active Filters */}
            {hasActiveFilters(filters) && (
              <ActiveFilters
                filters={filters}
                onRemoveFilter={handleRemoveFilter}
                onClearAll={clearFilters}
              />
            )}

            {/* View Toggle and Results */}
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <ViewToggle currentView={viewMode} onViewChange={setViewMode} />

                {viewMode !== "table" && total > 0 && (
                  <div className="text-sm text-stone-500 dark:text-stone-400">
                    Showing {Math.min(recordings.length, total)} of {total}{" "}
                    recordings
                  </div>
                )}
              </div>

              {/* Results View */}
              {isError ? (
                <div
                  role="alert"
                  className="rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 p-4"
                >
                  <p className="text-sm text-red-600 dark:text-red-400">
                    An error occurred while searching. Please try again or adjust
                    your filters.
                  </p>
                </div>
              ) : (
                currentView
              )}
            </div>

            {/* Help Text */}
            <div className="mt-8 p-4 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg">
              <p className="text-sm text-blue-800 dark:text-blue-300">
                <strong>Tip:</strong> Use the filter panel on the left to refine
                your search. You can draw areas on the map, filter by date and
                time, or select specific projects and sites. Use the view toggle to
                switch between map, timeline, and table views.
              </p>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
