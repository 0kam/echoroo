import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";

import useDatasetAnnotationProjects from "@/app/hooks/api/useDatasetAnnotationProjects";

import DatasetAnnotationProjectsSummaryBase from "@/lib/components/datasets/DatasetAnnotationProjectsSummary";
import AnnotationProjectCreateForm from "@/lib/components/annotation_projects/AnnotationProjectCreate";
import { DialogOverlay } from "@/lib/components/ui/Dialog";

import type * as types from "@/lib/types";

export default function DatasetAnnotationProjectsSummary({
  dataset,
  canCreate = false,
}: {
  dataset: types.Dataset;
  canCreate?: boolean;
}) {
  const router = useRouter();
  const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false);

  const { items, total, isLoading, create } = useDatasetAnnotationProjects({
    dataset,
    pageSize: 10,
    onCreateAnnotationProject: (project) => {
      setIsCreateDialogOpen(false);
      router.push(`/annotation_projects/${project.uuid}/`);
    },
  });

  const handleClickProject = useCallback(
    (project: types.AnnotationProject) => {
      router.push(`/annotation_projects/${project.uuid}/`);
    },
    [router],
  );

  const handleCreateProject = useCallback(() => {
    setIsCreateDialogOpen(true);
  }, []);

  const handleCreateSubmit = useCallback(
    async (data: types.AnnotationProjectCreate) => {
      // Ensure dataset_id is set to this dataset
      if (dataset.id == null) {
        return;
      }
      await create.mutateAsync({
        ...data,
        dataset_id: dataset.id,
      });
    },
    [create, dataset.id],
  );

  // Only allow create if dataset has an id
  const canCreateProject = canCreate && dataset.id != null;

  return (
    <>
      <DatasetAnnotationProjectsSummaryBase
        annotationProjects={items}
        total={total}
        isLoading={isLoading}
        datasetUuid={dataset.uuid}
        onClickProject={handleClickProject}
        onCreateProject={handleCreateProject}
        canCreate={canCreateProject}
      />
      {dataset.id != null && (
        <DialogOverlay
          title="Create Annotation Project"
          isOpen={isCreateDialogOpen}
          onClose={() => setIsCreateDialogOpen(false)}
        >
          {({ close }) => (
            <div className="w-96">
              <AnnotationProjectCreateForm
                defaultDatasetId={dataset.id}
                onCreateAnnotationProject={async (data) => {
                  await handleCreateSubmit(data);
                  close();
                }}
              />
            </div>
          )}
        </DialogOverlay>
      )}
    </>
  );
}
