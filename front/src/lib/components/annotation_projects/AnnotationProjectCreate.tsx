import { zodResolver } from "@hookform/resolvers/zod";
import { useCallback, useEffect, useMemo } from "react";
import { useForm } from "react-hook-form";

import useActiveUser from "@/app/hooks/api/useActiveUser";
import useMyGroups from "@/app/hooks/api/useMyGroups";

import {
  Group,
  Input,
  Select,
  Submit,
  TextArea,
} from "@/lib/components/inputs";
import type { Option } from "@/lib/components/inputs/Select";

import {
  AnnotationProjectCreateSchema,
  VisibilityLevel,
} from "@/lib/schemas";
import type { AnnotationProjectCreate } from "@/lib/types";

export default function CreateProject({
  onCreateAnnotationProject,
}: {
  onCreateAnnotationProject?: (project: AnnotationProjectCreate) => void;
}) {
  const {
    register,
    handleSubmit,
    setValue,
    watch,
    formState: { errors },
  } = useForm<AnnotationProjectCreate>({
    resolver: zodResolver(AnnotationProjectCreateSchema),
    mode: "onChange",
    defaultValues: {
      visibility: "private",
      owner_group_id: null,
    },
  });

  useEffect(() => {
    register("visibility");
    register("owner_group_id");
  }, [register]);

  const { data: activeUser } = useActiveUser();
  const { data: myGroups, isLoading: groupsLoading } = useMyGroups();

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

  const groupOptions: Option<number | null>[] = useMemo(() => {
    const options = managerGroups.map((group) => ({
      id: group.id,
      label: group.name,
      value: group.id,
    }));
    return [
      {
        id: "none",
        label:
          options.length === 0
            ? "No manager groups available"
            : "Select a group",
        value: null,
        disabled: options.length === 0,
      },
      ...options,
    ];
  }, [managerGroups]);

  const visibilityOptions: Option<VisibilityLevel>[] = useMemo(
    () => [
      {
        id: "public",
        label: "🌍 Public – All authenticated users",
        value: "public",
      },
      {
        id: "restricted",
        label: "👥 Restricted – Selected group members",
        value: "restricted",
      },
      {
        id: "private",
        label: "🔒 Private – Only you",
        value: "private",
      },
    ],
    [],
  );

  const visibility = watch("visibility");
  const ownerGroupId = watch("owner_group_id");

  const selectedVisibility = useMemo<Option<VisibilityLevel>>(() => {
    return (
      visibilityOptions.find((option) => option.value === visibility) ??
      visibilityOptions[2]
    );
  }, [visibilityOptions, visibility]);

  const selectedGroup = useMemo<Option<number | null>>(() => {
    return (
      groupOptions.find((option) => option.value === ownerGroupId) ??
      groupOptions[0]
    );
  }, [groupOptions, ownerGroupId]);

  const handleVisibilityChange = useCallback(
    (value: VisibilityLevel) => {
      setValue("visibility", value, { shouldValidate: true });
      if (value !== "restricted") {
        setValue("owner_group_id", null, { shouldValidate: true });
      }
    },
    [setValue],
  );

  const handleGroupChange = useCallback(
    (value: number | null) => {
      setValue("owner_group_id", value, {
        shouldDirty: true,
        shouldValidate: true,
      });
    },
    [setValue],
  );

  const isRestricted = visibility === "restricted";
  const canCreateRestricted = !isRestricted || managerGroups.length > 0;

  const onSubmit = useCallback(
    (data: AnnotationProjectCreate) => onCreateAnnotationProject?.(data),
    [onCreateAnnotationProject],
  );

  return (
    <form className="flex flex-col gap-4" onSubmit={handleSubmit(onSubmit)}>
      <Group
        label="Name"
        name="name"
        help="Please provide a name for the Annotation Project."
        error={errors.name?.message}
      >
        <Input {...register("name")} />
      </Group>
      <Group
        label="Description"
        name="description"
        help="Describe the purpose of the project"
        error={errors.description?.message}
      >
        <TextArea rows={6} {...register("description")} />
      </Group>
      <Group
        label="Instructions"
        name="annotation_instructions"
        help="Write instructions for annotators."
        error={errors.annotation_instructions?.message}
      >
        <TextArea rows={10} {...register("annotation_instructions")} />
      </Group>
      <Group
        label="Visibility"
        name="visibility"
        help="Control who can see this project"
        error={errors.visibility?.message}
      >
        <Select
          label="Visibility"
          options={visibilityOptions}
          selected={selectedVisibility}
          onChange={handleVisibilityChange}
        />
      </Group>
      {isRestricted ? (
        <Group
          label="Group"
          name="owner_group_id"
          help="Choose which group can access this project"
          error={errors.owner_group_id?.message}
        >
          {groupsLoading ? (
            <p className="text-sm text-stone-500">Loading groups…</p>
          ) : (
            <Select
              label="Group"
              options={groupOptions}
              selected={selectedGroup}
              onChange={handleGroupChange}
            />
          )}
          {managerGroups.length === 0 ? (
            <p className="mt-2 text-xs text-amber-600">
              You must manage a group to create restricted projects.
            </p>
          ) : null}
        </Group>
      ) : null}
      <Submit disabled={!canCreateRestricted}>Create Project</Submit>
    </form>
  );
}
