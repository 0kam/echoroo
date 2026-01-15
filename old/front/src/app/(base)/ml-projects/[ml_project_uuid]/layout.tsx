"use client";

/**
 * Layout component for ML Project detail pages.
 *
 * This component fetches ML project information based on the provided UUID
 * from the URL path parameter. It displays a navigation header with tabs
 * and wraps content with MLProjectContext.Provider to provide project data
 * to child components.
 */
import { notFound, useRouter, useParams, useSelectedLayoutSegment } from "next/navigation";
import { type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import toast from "react-hot-toast";
import {
  LayoutDashboard,
  Database,
  Music,
  Search,
  Cpu,
  Play,
  Clock,
  CheckCircle,
  Archive,
} from "lucide-react";

import api from "@/app/api";

import Loading from "@/app/loading";
import SectionTabs from "@/lib/components/navigation/SectionTabs";
import Tab from "@/lib/components/ui/Tab";

import type { MLProjectStatus } from "@/lib/types";

import MLProjectContext from "./context";

// Status badge colors (same as in list page for consistency)
const STATUS_COLORS: Record<MLProjectStatus, string> = {
  setup: "bg-stone-200 text-stone-700 dark:bg-stone-700 dark:text-stone-300",
  searching: "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300",
  labeling: "bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300",
  training: "bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300",
  inference: "bg-cyan-100 text-cyan-700 dark:bg-cyan-900 dark:text-cyan-300",
  review: "bg-indigo-100 text-indigo-700 dark:bg-indigo-900 dark:text-indigo-300",
  completed: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300",
  archived: "bg-stone-300 text-stone-600 dark:bg-stone-600 dark:text-stone-400",
};

function StatusBadge({ status }: { status: MLProjectStatus }) {
  const icons: Record<MLProjectStatus, React.ReactNode> = {
    setup: <Clock className="w-3 h-3" />,
    searching: <Search className="w-3 h-3" />,
    labeling: <Clock className="w-3 h-3" />,
    training: <Cpu className="w-3 h-3" />,
    inference: <Play className="w-3 h-3" />,
    review: <Clock className="w-3 h-3" />,
    completed: <CheckCircle className="w-3 h-3" />,
    archived: <Archive className="w-3 h-3" />,
  };

  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full ${STATUS_COLORS[status]}`}
    >
      {icons[status]}
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

function MLProjectHeader({
  name,
  description,
  status,
}: {
  name: string;
  description: string | null;
  status: MLProjectStatus;
}) {
  return (
    <div className="flex items-center gap-3">
      <span className="text-2xl font-bold">{name}</span>
      <StatusBadge status={status} />
    </div>
  );
}

function MLProjectTabs({ uuid }: { uuid: string }) {
  const router = useRouter();
  const selectedLayoutSegment = useSelectedLayoutSegment();

  return (
    <ul className="flex space-x-4">
      <li>
        <Tab
          active={selectedLayoutSegment === null}
          onClick={() => router.push(`/ml-projects/${uuid}/`)}
        >
          <LayoutDashboard className="w-4 h-4" />
          Overview
        </Tab>
      </li>
      <li>
        <Tab
          active={selectedLayoutSegment === "datasets"}
          onClick={() => router.push(`/ml-projects/${uuid}/datasets/`)}
        >
          <Database className="w-4 h-4" />
          Datasets
        </Tab>
      </li>
      <li>
        <Tab
          active={selectedLayoutSegment === "reference-sounds"}
          onClick={() => router.push(`/ml-projects/${uuid}/reference-sounds/`)}
        >
          <Music className="w-4 h-4" />
          Reference Sounds
        </Tab>
      </li>
      <li>
        <Tab
          active={selectedLayoutSegment === "search"}
          onClick={() => router.push(`/ml-projects/${uuid}/search/`)}
        >
          <Search className="w-4 h-4" />
          Search
        </Tab>
      </li>
      <li>
        <Tab
          active={selectedLayoutSegment === "training"}
          onClick={() => router.push(`/ml-projects/${uuid}/training/`)}
        >
          <Cpu className="w-4 h-4" />
          Custom Models
        </Tab>
      </li>
      <li>
        <Tab
          active={selectedLayoutSegment === "inference"}
          onClick={() => router.push(`/ml-projects/${uuid}/inference/`)}
        >
          <Play className="w-4 h-4" />
          Inference
        </Tab>
      </li>
    </ul>
  );
}

export default function Layout({ children }: { children: ReactNode }) {
  const params = useParams();
  const uuid = params.ml_project_uuid as string;

  if (!uuid) notFound();

  const { data: mlProject, isLoading, isError, error } = useQuery({
    queryKey: ["ml_project", uuid],
    queryFn: () => api.mlProjects.get(uuid),
  });

  if (isLoading) {
    return <Loading />;
  }

  if (isError || mlProject == null) {
    if (isAxiosError(error) && error.response?.status === 404) {
      notFound();
    }
    return (
      <div className="container mx-auto p-8">
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-6">
          <h2 className="text-xl font-bold text-red-700 dark:text-red-400 mb-2">
            Error Loading ML Project
          </h2>
          <p className="text-red-600 dark:text-red-300">
            {error instanceof Error ? error.message : "Unknown error occurred"}
          </p>
        </div>
      </div>
    );
  }

  return (
    <MLProjectContext.Provider value={mlProject}>
      <SectionTabs
        title={
          <MLProjectHeader
            name={mlProject.name}
            description={mlProject.description}
            status={mlProject.status}
          />
        }
        tabs={[<MLProjectTabs key="tabs" uuid={uuid} />]}
      />
      <div className="py-4 px-8">{children}</div>
    </MLProjectContext.Provider>
  );
}
