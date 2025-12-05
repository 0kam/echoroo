import { useMemo, type ComponentProps } from "react";

import {
  AddIcon,
  AnnotationProjectIcon,
  NextIcon,
} from "@/lib/components/icons";
import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import { H3 } from "@/lib/components/ui/Headings";
import Link from "@/lib/components/ui/Link";
import Loading from "@/lib/components/ui/Loading";
import VisibilityBadge from "@/lib/components/ui/VisibilityBadge";

import type * as types from "@/lib/types";

/**
 * Component to display a summary of annotation projects for a dataset.
 *
 * Shows up to 3 recent projects with a "View All" link and "Create New" button.
 */
export default function DatasetAnnotationProjectsSummary({
  isLoading = false,
  ...props
}: {
  isLoading?: boolean;
} & ComponentProps<typeof AnnotationProjectsSummary>) {
  return (
    <Card>
      <H3>
        <AnnotationProjectIcon className="inline-block mr-2 w-6 h-6 text-emerald-500" />
        Annotation Projects
      </H3>
      {isLoading ? <Loading /> : <AnnotationProjectsSummary {...props} />}
    </Card>
  );
}

/**
 * Inner component displaying the list of annotation projects.
 */
function AnnotationProjectsSummary({
  annotationProjects,
  total = 0,
  maxProjects = 3,
  datasetUuid,
  onClickProject,
  onCreateProject,
  canCreate = false,
}: {
  annotationProjects: types.AnnotationProject[];
  total?: number;
  maxProjects?: number;
  datasetUuid: string;
  onClickProject?: (project: types.AnnotationProject) => void;
  onCreateProject?: () => void;
  canCreate?: boolean;
}) {
  const displayedProjects = useMemo(
    () => annotationProjects.slice(0, maxProjects),
    [annotationProjects, maxProjects],
  );

  const viewAllUrl = `/datasets/${datasetUuid}/annotation_projects`;

  if (displayedProjects.length === 0) {
    return (
      <NoAnnotationProjects
        datasetUuid={datasetUuid}
        onCreateProject={onCreateProject}
        canCreate={canCreate}
      />
    );
  }

  return (
    <>
      <ul className="flex flex-col gap-2 p-2 rounded-md border divide-y divide-dashed divide-stone-300 dark:border-stone-800 dark:divide-stone-800">
        {displayedProjects.map((project) => (
          <AnnotationProjectItem
            key={project.uuid}
            project={project}
            onClick={() => onClickProject?.(project)}
          />
        ))}
      </ul>
      <div className="flex flex-row justify-between items-center mt-2">
        <Link
          href={viewAllUrl}
          mode="text"
          variant="primary"
          padding="p-1"
          className="text-sm"
        >
          View All ({total})
          <NextIcon className="w-4 h-4 ml-1" />
        </Link>
        {canCreate && (
          <Button
            mode="text"
            variant="primary"
            padding="p-1"
            onClick={onCreateProject}
          >
            <AddIcon className="w-4 h-4 mr-1" />
            Create New
          </Button>
        )}
      </div>
    </>
  );
}

/**
 * Single annotation project item in the summary list.
 */
function AnnotationProjectItem({
  project,
  onClick,
}: {
  project: types.AnnotationProject;
  onClick?: () => void;
}) {
  return (
    <li className="pt-2 first:pt-0">
      <button
        onClick={onClick}
        className="w-full text-left hover:bg-stone-100 dark:hover:bg-stone-800 rounded p-1 -m-1 transition-colors"
      >
        <div className="flex flex-row items-center gap-2">
          <AnnotationProjectIcon className="w-4 h-4 text-stone-500 flex-shrink-0" />
          <span className="font-medium text-stone-900 dark:text-stone-100 truncate">
            {project.name}
          </span>
          <VisibilityBadge visibility={project.visibility} />
        </div>
        <p className="text-sm text-stone-600 dark:text-stone-400 line-clamp-1 mt-1 ml-6">
          {project.description}
        </p>
      </button>
    </li>
  );
}

/**
 * Empty state when no annotation projects exist.
 */
function NoAnnotationProjects({
  datasetUuid,
  onCreateProject,
  canCreate = false,
}: {
  datasetUuid: string;
  onCreateProject?: () => void;
  canCreate?: boolean;
}) {
  return (
    <div className="flex flex-col items-center gap-3 py-4 text-center">
      <AnnotationProjectIcon className="w-12 h-12 text-stone-400" />
      <p className="text-stone-500 dark:text-stone-400">
        No annotation projects yet
      </p>
      {canCreate && (
        <Button mode="outline" variant="primary" onClick={onCreateProject}>
          <AddIcon className="w-4 h-4 mr-2" />
          Create Annotation Project
        </Button>
      )}
      <Link
        href={`/datasets/${datasetUuid}/annotation_projects`}
        mode="text"
        variant="secondary"
        padding="p-1"
        className="text-sm"
      >
        Go to Annotation Projects
        <NextIcon className="w-4 h-4 ml-1" />
      </Link>
    </div>
  );
}
