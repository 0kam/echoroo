import { useMemo } from "react";

import useActiveUser from "@/app/hooks/api/useActiveUser";
import useMyGroups from "@/app/hooks/api/useMyGroups";

import { Select } from "@/lib/components/inputs";
import type { Option } from "@/lib/components/inputs/Select";
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
} from "@/lib/types";
import type { VisibilityLevel } from "@/lib/schemas";

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
  const { data: myGroups } = useMyGroups();

  const managerGroups = useMemo(() => {
    if (!myGroups?.length || !activeUser) return [];
    return myGroups.filter((group) =>
      group.memberships.some(
        (membership) =>
          membership.user_id === activeUser.id &&
          membership.role === "manager",
      ),
    );
  }, [myGroups, activeUser]);

  const isOwner = useMemo(() => {
    return activeUser?.id === annotationProject.created_by_id;
  }, [activeUser, annotationProject.created_by_id]);

  const visibilityOptions: Option<VisibilityLevel>[] = useMemo(() => {
    const options: Option<VisibilityLevel>[] = [
      { id: "public", label: "🌍 Public", value: "public" },
      { id: "private", label: "🔒 Private", value: "private" },
    ];

    // Only show restricted option if user has manager groups
    if (managerGroups.length > 0) {
      options.splice(1, 0, {
        id: "restricted",
        label: "👥 Restricted",
        value: "restricted",
      });
    }

    return options;
  }, [managerGroups]);

  const baseGroupOptions: Option<number>[] = useMemo(() => {
    const options = managerGroups.map((group) => ({
      id: group.id,
      label: group.name,
      value: group.id,
    }));

    if (
      annotationProject.owner_group_id != null &&
      !options.some((option) => option.value === annotationProject.owner_group_id)
    ) {
      options.push({
        id: annotationProject.owner_group_id,
        label: `Group #${annotationProject.owner_group_id}`,
        value: annotationProject.owner_group_id,
      });
    }

    return options;
  }, [managerGroups, annotationProject.owner_group_id]);

  const groupOptions: Option<number | null>[] = useMemo(
    () => [
      { id: "none", label: "No group", value: null },
      ...baseGroupOptions,
    ],
    [baseGroupOptions],
  );

  const selectedVisibility = useMemo<Option<VisibilityLevel> | undefined>(() => {
    return visibilityOptions.find(
      (option) => option.value === annotationProject.visibility,
    );
  }, [visibilityOptions, annotationProject.visibility]);

  const currentVisibility = selectedVisibility?.value ?? annotationProject.visibility;

  const selectedGroup = useMemo<Option<number | null>>(() => {
    return (
      groupOptions.find(
        (option) => option.value === annotationProject.owner_group_id,
      ) ?? groupOptions[0]
    );
  }, [groupOptions, annotationProject.owner_group_id]);

  const handleVisibilityChange = (value: VisibilityLevel) => {
    const update: AnnotationProjectUpdate = { visibility: value };
    if (value === "restricted") {
      // If switching to restricted, use the current group or the first available group
      if (annotationProject.owner_group_id != null) {
        update.owner_group_id = annotationProject.owner_group_id;
      } else if (baseGroupOptions.length > 0) {
        update.owner_group_id = baseGroupOptions[0].value;
      }
    } else {
      update.owner_group_id = null;
    }
    onChangeAnnotationProject?.(update);
  };

  const handleGroupChange = (value: number | null) => {
    onChangeAnnotationProject?.({ owner_group_id: value });
  };

  return (
    <Card>
      <div className="px-4 sm:px-0">
        <H3>Project Details</H3>
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
                editable
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
                editable
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
                editable
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
              <DescriptionTerm>Visibility</DescriptionTerm>
              <DescriptionData>
                <div className="flex flex-col gap-2">
                  <VisibilityBadge visibility={currentVisibility} />
                  {isOwner ? (
                    selectedVisibility ? (
                      <Select
                        label="Visibility"
                        options={visibilityOptions}
                        selected={selectedVisibility}
                        onChange={handleVisibilityChange}
                      />
                    ) : (
                      <p className="text-sm text-stone-500 dark:text-stone-400">
                        Cannot change visibility: no valid options available
                      </p>
                    )
                  ) : (
                    <p className="text-sm text-stone-500 dark:text-stone-400">
                      Only the project owner can change visibility
                    </p>
                  )}
                </div>
              </DescriptionData>
            </div>
            {currentVisibility === "restricted" && isOwner ? (
              <div className="py-6 px-4 sm:px-0">
                <DescriptionTerm>Group</DescriptionTerm>
                <DescriptionData>
                  <Select
                    label="Group"
                    options={groupOptions}
                    selected={selectedGroup}
                    onChange={handleGroupChange}
                  />
                </DescriptionData>
              </div>
            ) : null}
          </dl>
        )}
      </div>
    </Card>
  );
}
