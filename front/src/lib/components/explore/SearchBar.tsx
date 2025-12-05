"use client";

import { useCallback } from "react";
import { Search, SlidersHorizontal } from "lucide-react";

import Button from "@/lib/components/ui/Button";

type SearchBarProps = {
  value: string;
  onChange: (value: string) => void;
  onSearch: () => void;
  onToggleFilters: () => void;
  isFiltersOpen: boolean;
  resultCount: number;
  isLoading: boolean;
};

export default function SearchBar({
  value,
  onChange,
  onSearch,
  onToggleFilters,
  isFiltersOpen,
  resultCount,
  isLoading,
}: SearchBarProps) {
  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      onSearch();
    },
    [onSearch],
  );

  return (
    <div className="space-y-2">
      <form onSubmit={handleSubmit} className="flex gap-2" role="search">
        {/* Mobile only: Filter toggle button (hidden on desktop lg: 1024px+) */}
        <Button
          mode={isFiltersOpen ? "filled" : "outline"}
          variant={isFiltersOpen ? "primary" : "secondary"}
          padding="px-3 py-2"
          onClick={onToggleFilters}
          type="button"
          className="lg:hidden"
          aria-expanded={isFiltersOpen}
          aria-label={isFiltersOpen ? "Close filters" : "Open filters"}
        >
          <SlidersHorizontal className="w-5 h-5" aria-hidden="true" />
          <span className="hidden sm:inline ml-2">Filters</span>
        </Button>

        <div className="flex-1 relative">
          <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
            <Search className="w-5 h-5 text-stone-400" aria-hidden="true" />
          </div>
          <input
            type="search"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder="Search recordings across all datasets..."
            aria-label="Search recordings"
            className="block w-full pl-10 pr-4 py-2.5 text-sm bg-white dark:bg-stone-900 border border-stone-300 dark:border-stone-600 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 dark:focus:ring-emerald-400 dark:focus:border-emerald-400 placeholder-stone-400"
          />
        </div>

        <Button
          variant="primary"
          padding="px-4 py-2"
          type="submit"
          disabled={isLoading}
          aria-label="Search"
        >
          <Search className="w-5 h-5 sm:mr-2" aria-hidden="true" />
          <span className="hidden sm:inline">Search</span>
        </Button>
      </form>

      <div
        className="text-sm text-stone-500 dark:text-stone-400"
        aria-live="polite"
        aria-atomic="true"
      >
        {isLoading ? (
          "Searching..."
        ) : (
          <>
            Found <span className="font-semibold">{resultCount}</span> recordings
          </>
        )}
      </div>
    </div>
  );
}
