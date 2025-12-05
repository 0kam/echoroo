// Explore page state management
import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

export type ViewMode = "map" | "timeline" | "table";

export type DrawnShape = {
  type: "rectangle" | "circle" | "polygon";
  bounds: number[]; // [minLon, minLat, maxLon, maxLat] for bbox
  center?: [number, number]; // For circle
  radius?: number; // For circle (in meters)
  coordinates?: [number, number][]; // For polygon
};

export type ExploreFilters = {
  // Spatial filters
  drawnShape: DrawnShape | null;
  bbox: number[] | null; // [minLon, minLat, maxLon, maxLat]

  // Time filters
  dateStart: string | null;
  dateEnd: string | null;
  timeStart: number | null; // Seconds since midnight
  timeEnd: number | null;

  // Metadata filters
  projectIds: string[];
  siteIds: string[];
  recorderIds: string[];

  // Tag filters
  tags: Array<{ key: string; value: string }>;

  // Search query
  searchQuery: string;
};

export type ExploreState = {
  // View mode
  viewMode: ViewMode;

  // Filters
  filters: ExploreFilters;

  // Filter panel state (used for mobile slide-out panel only)
  // On desktop (lg: 1024px+), the filter panel is always visible as a fixed sidebar
  isFilterPanelOpen: boolean;

  // Pagination
  page: number;
  pageSize: number;

  // Actions
  setViewMode: (mode: ViewMode) => void;
  setFilters: (filters: Partial<ExploreFilters>) => void;
  clearFilters: () => void;
  removeFilter: (filterKey: keyof ExploreFilters, value?: unknown) => void;
  toggleFilterPanel: () => void;
  setPage: (page: number) => void;
  setPageSize: (size: number) => void;
};

const DEFAULT_FILTERS: ExploreFilters = {
  drawnShape: null,
  bbox: null,
  dateStart: null,
  dateEnd: null,
  timeStart: null,
  timeEnd: null,
  projectIds: [],
  siteIds: [],
  recorderIds: [],
  tags: [],
  searchQuery: "",
};

export const useExploreStore = create<ExploreState>()(
  persist(
    (set) => ({
      viewMode: "map",
      filters: DEFAULT_FILTERS,
      isFilterPanelOpen: false,
      page: 0,
      pageSize: 50,

      setViewMode: (mode) => set({ viewMode: mode }),

      setFilters: (newFilters) =>
        set((state) => ({
          filters: { ...state.filters, ...newFilters },
          page: 0, // Reset page when filters change
        })),

      clearFilters: () =>
        set({
          filters: DEFAULT_FILTERS,
          page: 0,
        }),

      removeFilter: (filterKey, value) =>
        set((state) => {
          const current = state.filters[filterKey];

          if (Array.isArray(current) && value !== undefined) {
            // Remove specific value from array
            if (filterKey === "tags") {
              const tagValue = value as { key: string; value: string };
              return {
                filters: {
                  ...state.filters,
                  tags: state.filters.tags.filter(
                    (t) => !(t.key === tagValue.key && t.value === tagValue.value),
                  ),
                },
                page: 0,
              };
            }
            return {
              filters: {
                ...state.filters,
                [filterKey]: (current as unknown[]).filter((v) => v !== value),
              },
              page: 0,
            };
          }

          // Reset to default for non-array filters
          return {
            filters: {
              ...state.filters,
              [filterKey]: DEFAULT_FILTERS[filterKey],
            },
            page: 0,
          };
        }),

      toggleFilterPanel: () =>
        set((state) => ({ isFilterPanelOpen: !state.isFilterPanelOpen })),

      setPage: (page) => set({ page }),

      setPageSize: (pageSize) => set({ pageSize, page: 0 }),
    }),
    {
      name: "explore-storage",
      storage: createJSONStorage(() => sessionStorage),
      partialize: (state) => ({
        viewMode: state.viewMode,
        filters: state.filters,
        isFilterPanelOpen: state.isFilterPanelOpen,
        pageSize: state.pageSize,
      }),
    },
  ),
);

// Selector hooks for better performance
export const useExploreViewMode = () => useExploreStore((state) => state.viewMode);
export const useExploreFilters = () => useExploreStore((state) => state.filters);
export const useExploreFilterPanel = () =>
  useExploreStore((state) => state.isFilterPanelOpen);
export const useExplorePagination = () =>
  useExploreStore((state) => ({ page: state.page, pageSize: state.pageSize }));

// Utility to check if any filters are active
export const hasActiveFilters = (filters: ExploreFilters): boolean => {
  return (
    filters.drawnShape !== null ||
    filters.bbox !== null ||
    filters.dateStart !== null ||
    filters.dateEnd !== null ||
    filters.timeStart !== null ||
    filters.timeEnd !== null ||
    filters.projectIds.length > 0 ||
    filters.siteIds.length > 0 ||
    filters.recorderIds.length > 0 ||
    filters.tags.length > 0 ||
    filters.searchQuery.trim() !== ""
  );
};
