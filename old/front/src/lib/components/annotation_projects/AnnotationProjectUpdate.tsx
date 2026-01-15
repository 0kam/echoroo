import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import api from "@/app/api";
import useActiveUser from "@/app/hooks/api/useActiveUser";

import Card from "@/lib/components/ui/Card";
import Description, {
  DescriptionData,
  DescriptionTerm,
} from "@/lib/components/ui/Description";
import { H3 } from "@/lib/components/ui/Headings";
import Loading from "@/lib/components/ui/Loading";
import VisibilityBadge from "@/lib/components/ui/VisibilityBadge";

import type {
  AnnotationProject,
  AnnotationProjectUpdate,
  Project,
} from "@/lib/types";

export default function AnnotationProjectUpdateComponent({
  annotationProject,
  isLoading = false,
  onChangeAnnotationProject,
}: {
  annotationProject: AnnotationProject;
  isLoading?: boolean;
  onChangeAnnotationProject?: (data: AnnotationProjectUpdate) => void;
}) {
  const { data: activeUser } = useActiveUser();

  const {
    data: projects = [],
  } = useQuery<Project[]>({
    queryKey: ["metadata", "projects", "all"],
    queryFn: () => api.metadata.projects.list(),
    staleTime: 60_000,
  });

  const project = useMemo(
    () =>
      projects.find(
        (item) => item.project_id === annotationProject.project_id,
      ),
    [projects, annotationProject.project_id],
  );

  const isProjectManager = useMemo(() => {
    if (!project || !activeUser) return false;
    if (activeUser.is_superuser) return true;
    return project.memberships.some(
      (membership) =>
        membership.user_id === activeUser.id &&
        membership.role === "manager",
    );
  }, [project, activeUser]);

  const isOwner = useMemo(
    () => activeUser?.id === annotationProject.created_by_id,
    [activeUser, annotationProject.created_by_id],
  );

  const canEditMetadata = Boolean(
    activeUser && (activeUser.is_superuser || isOwner || isProjectManager),
  );

  return (
    <Card>
      <div className="px-4 sm:px-0 space-y-1">
        <H3>Project Details</H3>
        {!canEditMetadata ? (
          <p className="text-sm text-stone-500 dark:text-stone-400">
            Only the project owner, project managers, or superusers can edit the
            name, description, and instructions.
          </p>
        ) : null}
      </div>
      <div className="mt-6 border-t border-stone-300 dark:border-stone-700">
        {isLoading ? (
          <Loading />
        ) : (
          <dl className="divide-y divide-stone-500">
            <div className="py-6 px-4 sm:px-0">
              <Description
                name="Name"
                value={annotationProject.name}
                onChange={(name) => onChangeAnnotationProject?.({ name })}
                type="text"
                editable={canEditMetadata}
              />
            </div>
            <div className="py-6 px-4 sm:px-0">
              <Description
                name="Description"
                value={annotationProject.description}
                onChange={(description) =>
                  onChangeAnnotationProject?.({ description })
                }
                type="textarea"
                editable={canEditMetadata}
              />
            </div>
            <div className="py-6 px-4 sm:px-0">
              <Description
                name="Annotation Instructions"
                value={annotationProject.annotation_instructions ?? ""}
                onChange={(annotation_instructions) =>
                  onChangeAnnotationProject?.({ annotation_instructions })
                }
                type="textarea"
                editable={canEditMetadata}
              />
            </div>
            <div className="py-6 px-4 sm:px-0">
              <Description
                name="Created On"
                value={annotationProject.created_on}
                type="date"
              />
            </div>
            <div className="py-6 px-4 sm:px-0">
              <DescriptionTerm>Project</DescriptionTerm>
              <DescriptionData>
                <span className="text-sm text-stone-700 dark:text-stone-300">
                  {project?.project_name ?? annotationProject.project_id}
                </span>
              </DescriptionData>
            </div>
            <div className="py-6 px-4 sm:px-0">
              <DescriptionTerm>Dataset</DescriptionTerm>
              <DescriptionData>
                <span className="text-sm text-stone-700 dark:text-stone-300">
                  Dataset ID #{annotationProject.dataset_id}
                </span>
              </DescriptionData>
            </div>
            <div className="py-6 px-4 sm:px-0">
              <DescriptionTerm>Visibility</DescriptionTerm>
              <DescriptionData>
                <div className="flex flex-col gap-2">
                  <VisibilityBadge visibility={annotationProject.visibility} />
                  <p className="text-sm text-stone-500 dark:text-stone-400">
                    Annotation project visibility follows the dataset.
                  </p>
                </div>
              </DescriptionData>
            </div>
          </dl>
        )}
      </div>
    </Card>
  );
}
