"use client";

import { notFound, useRouter } from "next/navigation";
import { useCallback, useContext } from "react";

import Pagination from "@/app/components/Pagination";
import AnnotationProjectCreate from "@/app/components/annotation_projects/AnnotationProjectCreate";
import AnnotationProjectImport from "@/app/components/annotation_projects/AnnotationProjectImport";
import useDatasetAnnotationProjects from "@/app/hooks/api/useDatasetAnnotationProjects";

import AnnotationProjectListBase from "@/lib/components/annotation_projects/AnnotationProjectList";
import { AnnotationProjectIcon } from "@/lib/components/icons";
import Search from "@/lib/components/inputs/Search";

import type { AnnotationProject, Dataset } from "@/lib/types";

import DatasetContext from "../context";

/**
 * Dataset Annotation Projects page.
 *
 * Shows all annotation projects that belong to this dataset,
 * with search and pagination functionality.
 */
export default function Page() {
  const router = useRouter();
  const dataset = useContext(DatasetContext);

  const handleClickAnnotationProject = useCallback(
    (project: AnnotationProject) => {
      router.push(`/annotation_projects/${project.uuid}/`);
    },
    [router],
  );

  const handleCreateAnnotationProject = useCallback(
    (project: AnnotationProject) => {
      router.push(`/annotation_projects/${project.uuid}/`);
    },
    [router],
  );

  if (dataset == null) {
    return notFound();
  }

  return (
    <DatasetAnnotationProjectsContent
      dataset={dataset}
      onClickAnnotationProject={handleClickAnnotationProject}
      onCreateAnnotationProject={handleCreateAnnotationProject}
    />
  );
}

/**
 * Inner component to handle the actual list rendering.
 * Separated to allow hooks to be called after the null check.
 */
function DatasetAnnotationProjectsContent({
  dataset,
  onClickAnnotationProject,
  onCreateAnnotationProject,
}: {
  dataset: Dataset;
  onClickAnnotationProject: (project: AnnotationProject) => void;
  onCreateAnnotationProject: (project: AnnotationProject) => void;
}) {
  const { items, pagination, isLoading, filter } = useDatasetAnnotationProjects(
    {
      dataset,
      pageSize: 10,
      onCreateAnnotationProject,
    },
  );

  return (
    <div className="w-full">
      <AnnotationProjectListBase
        annotationProjects={items}
        isLoading={isLoading}
        onClickAnnotationProject={onClickAnnotationProject}
        AnnotationProjectSearch={
          <Search
            label="Search"
            placeholder="Search annotation projects..."
            value={filter.get("search")}
            onChange={(value) => filter.set("search", value as string)}
            onSubmit={filter.submit}
            icon={<AnnotationProjectIcon className="w-4 h-4" />}
          />
        }
        AnnotationProjectCreate={
          <AnnotationProjectCreate
            onCreateAnnotationProject={onCreateAnnotationProject}
          />
        }
        AnnotationProjectImport={
          <AnnotationProjectImport
            onImportAnnotationProject={onCreateAnnotationProject}
          />
        }
        Pagination={<Pagination pagination={pagination} />}
      />
    </div>
  );
}
