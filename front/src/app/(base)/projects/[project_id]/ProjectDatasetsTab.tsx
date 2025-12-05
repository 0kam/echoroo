"use client";

import { useMemo } from "react";

import { Plus, Database as DatabaseIcon, Folder } from "lucide-react";

import useDatasets from "@/app/hooks/api/useDatasets";

import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import Link from "@/lib/components/ui/Link";
import Empty from "@/lib/components/ui/Empty";
import Loading from "@/lib/components/ui/Loading";
import VisibilityBadge from "@/lib/components/ui/VisibilityBadge";

import type { Project, Dataset } from "@/lib/types";

interface ProjectDatasetsTabProps {
  project: Project;
  canEdit: boolean;
  isMember: boolean;
  isManager: boolean;
}

export default function ProjectDatasetsTab({
  project,
  isManager,
}: ProjectDatasetsTabProps) {
  const filter = useMemo(() => ({ project_id__eq: project.project_id }), [project.project_id]);

  const datasets = useDatasets({
    filter,
    pageSize: 1000
  });
  const { items: allDatasets, isLoading } = datasets;

  const projectDatasets = allDatasets ?? [];

  const canCreate = isManager;

  if (isLoading) {
    return <Loading />;
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold">Datasets</h3>
          <p className="text-sm text-stone-600 dark:text-stone-400">
            {projectDatasets.length} dataset
            {projectDatasets.length !== 1 ? "s" : ""} in this project
          </p>
        </div>
        {canCreate && (
          <Link href={`/datasets?project_id=${project.project_id}`}>
            <Button variant="primary" padding="px-3 py-2">
              <Plus className="w-4 h-4 mr-2" />
              New Dataset
            </Button>
          </Link>
        )}
      </div>

      {/* Dataset List */}
      {projectDatasets.length === 0 ? (
        <Empty>
          <Folder className="w-16 h-16 text-stone-400 dark:text-stone-600 mb-4" />
          <p className="text-lg text-stone-600 dark:text-stone-400">
            No datasets in this project yet
          </p>
          {canCreate && (
            <p className="text-sm text-stone-500 dark:text-stone-500 mt-2">
              Create your first dataset to get started
            </p>
          )}
        </Empty>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {projectDatasets.map((dataset: Dataset) => (
            <DatasetCard key={dataset.uuid} dataset={dataset} />
          ))}
        </div>
      )}
    </div>
  );
}

function DatasetCard({ dataset }: { dataset: Dataset }) {
  return (
    <Link href={`/datasets/${dataset.uuid}`}>
      <Card className="p-4 hover:shadow-lg transition-shadow cursor-pointer">
        <div className="flex flex-col h-full">
          {/* Header */}
          <div className="flex items-start justify-between mb-2">
            <div className="flex items-center gap-2 flex-1">
              <DatabaseIcon className="w-5 h-5 text-blue-500 flex-shrink-0" />
              <h4 className="font-semibold text-sm line-clamp-1">
                {dataset.name}
              </h4>
            </div>
            <VisibilityBadge visibility={dataset.visibility} className="text-xs" />
          </div>

          {/* Description */}
          {dataset.description && (
            <p className="text-xs text-stone-600 dark:text-stone-400 mb-3 line-clamp-2">
              {dataset.description}
            </p>
          )}

          {/* Footer */}
          <div className="flex items-center justify-between text-xs text-stone-500 dark:text-stone-400 pt-2 border-t border-stone-200 dark:border-stone-700 mt-auto">
            <span>{dataset.recording_count ?? 0} recordings</span>
            <span>{new Date(dataset.created_on).toLocaleDateString()}</span>
          </div>
        </div>
      </Card>
    </Link>
  );
}
