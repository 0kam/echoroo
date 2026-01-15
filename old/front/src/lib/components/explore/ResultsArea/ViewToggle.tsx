"use client";

import { Map, Calendar, Table } from "lucide-react";
import classNames from "classnames";

import type { ViewMode } from "@/app/store/explore";

type ViewToggleProps = {
  currentView: ViewMode;
  onViewChange: (view: ViewMode) => void;
};

const views: { id: ViewMode; label: string; icon: React.ReactNode }[] = [
  { id: "map", label: "Map", icon: <Map className="w-4 h-4" /> },
  { id: "timeline", label: "Timeline", icon: <Calendar className="w-4 h-4" /> },
  { id: "table", label: "Table", icon: <Table className="w-4 h-4" /> },
];

export default function ViewToggle({
  currentView,
  onViewChange,
}: ViewToggleProps) {
  return (
    <div className="inline-flex rounded-lg border border-stone-200 dark:border-stone-700 bg-stone-50 dark:bg-stone-800 p-1">
      {views.map((view) => (
        <button
          key={view.id}
          type="button"
          onClick={() => onViewChange(view.id)}
          className={classNames(
            "flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-md transition-colors",
            currentView === view.id
              ? "bg-white dark:bg-stone-700 text-emerald-600 dark:text-emerald-400 shadow-sm"
              : "text-stone-600 dark:text-stone-400 hover:text-stone-900 dark:hover:text-stone-100",
          )}
        >
          {view.icon}
          <span className="hidden sm:inline">{view.label}</span>
        </button>
      ))}
    </div>
  );
}
