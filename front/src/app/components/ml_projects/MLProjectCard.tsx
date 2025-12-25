"use client";

import type { ReactNode } from "react";

import {
  CalendarIcon,
  DatasetIcon,
  ModelIcon,
  SearchIcon,
  AudioIcon,
} from "@/lib/components/icons";
import Button from "@/lib/components/ui/Button";

import type { MLProject, MLProjectStatus } from "@/lib/types";

/**
 * Status badge colors and labels for ML Project status.
 * Matches backend MLProjectStatus enum.
 */
const STATUS_CONFIG: Record<
  MLProjectStatus,
  { label: string; className: string }
> = {
  draft: {
    label: "Draft",
    className: "bg-stone-100 text-stone-600 border-stone-300",
  },
  active: {
    label: "Active",
    className: "bg-blue-100 text-blue-600 border-blue-300",
  },
  training: {
    label: "Training",
    className: "bg-purple-100 text-purple-600 border-purple-300",
  },
  inference: {
    label: "Inference",
    className: "bg-cyan-100 text-cyan-600 border-cyan-300",
  },
  completed: {
    label: "Completed",
    className: "bg-emerald-100 text-emerald-600 border-emerald-300",
  },
  archived: {
    label: "Archived",
    className: "bg-stone-200 text-stone-500 border-stone-400",
  },
};

function Stat({ icon, value, label }: { icon: ReactNode; value: number; label: string }) {
  return (
    <div className="flex flex-row items-center gap-1 text-sm text-stone-500 dark:text-stone-400">
      <span className="w-4 h-4">{icon}</span>
      <span className="font-medium text-stone-700 dark:text-stone-300">{value}</span>
      <span>{label}</span>
    </div>
  );
}

function StatusBadge({ status }: { status: MLProjectStatus }) {
  const config = STATUS_CONFIG[status];
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 text-xs font-medium rounded-full border ${config.className}`}
    >
      {config.label}
    </span>
  );
}

export default function MLProjectCard({
  mlProject,
  onClick,
}: {
  mlProject: MLProject;
  onClick?: () => void;
}) {
  return (
    <div className="w-full">
      <div className="px-4 sm:px-0">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="inline-flex items-center text-base font-semibold leading-7 text-stone-900 dark:text-stone-100">
            <span className="inline-block w-6 h-6 align-middle text-stone-500">
              <ModelIcon className="w-6 h-6" />
            </span>
            <Button
              mode="text"
              align="text-left"
              className="inline-block ml-1"
              onClick={onClick}
            >
              {mlProject.name}
            </Button>
          </h3>
          <StatusBadge status={mlProject.status} />
        </div>
        <p className="mt-1 text-sm whitespace-pre-wrap leading-5 text-stone-600 dark:text-stone-400 line-clamp-2">
          {mlProject.description}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-4 py-3 text-sm">
        {mlProject.dataset && (
          <div className="flex items-center gap-1 text-stone-500 dark:text-stone-400">
            <DatasetIcon className="w-4 h-4" />
            <span className="text-stone-700 dark:text-stone-300">
              {mlProject.dataset.name}
            </span>
          </div>
        )}
        {mlProject.reference_sound_count !== undefined && (
          <Stat
            icon={<AudioIcon className="w-4 h-4" />}
            value={mlProject.reference_sound_count}
            label="references"
          />
        )}
        {mlProject.search_session_count !== undefined && (
          <Stat
            icon={<SearchIcon className="w-4 h-4" />}
            value={mlProject.search_session_count}
            label="sessions"
          />
        )}
        {mlProject.custom_model_count !== undefined && (
          <Stat
            icon={<ModelIcon className="w-4 h-4" />}
            value={mlProject.custom_model_count}
            label="models"
          />
        )}
      </div>
      <div className="flex items-center gap-1 text-xs text-stone-400 dark:text-stone-500">
        <CalendarIcon className="w-4 h-4" />
        <span>Created {mlProject.created_on.toLocaleDateString()}</span>
      </div>
    </div>
  );
}
