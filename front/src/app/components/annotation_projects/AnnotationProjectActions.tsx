import { useMemo } from "react";
import toast from "react-hot-toast";

import useAnnotationProject from "@/app/hooks/api/useAnnotationProject";
import useActiveUser from "@/app/hooks/api/useActiveUser";

import AnnotationProjectActionsBase from "@/lib/components/annotation_projects/AnnotationProjectActions";

import type { AnnotationProject } from "@/lib/types";

export default function AnnotationProjectActions({
  annotationProject,
  onDeleteAnnotationProject,
}: {
  annotationProject: AnnotationProject;
  onDeleteAnnotationProject?: () => void;
}) {
  const { data: activeUser } = useActiveUser();
  const { delete: deleteAnnotationProject, download } = useAnnotationProject({
    uuid: annotationProject.uuid,
    annotationProject,
    onDelete: onDeleteAnnotationProject,
  });

  const canDelete = useMemo(() => {
    if (!activeUser) return false;
    return (
      activeUser.is_superuser || activeUser.id === annotationProject.created_by_id
    );
  }, [activeUser, annotationProject.created_by_id]);

  const handleDelete = canDelete
    ? () =>
        toast.promise(deleteAnnotationProject.mutateAsync(annotationProject), {
          loading: "Deleting project...",
          success: "Project deleted",
          error: "Failed to delete project",
        })
    : undefined;

  return (
    <AnnotationProjectActionsBase
      annotationProject={annotationProject}
      canDelete={canDelete}
      onDeleteAnnotationProject={handleDelete}
      onDownloadAnnotationProject={download}
    />
  );
}
