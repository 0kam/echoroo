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
import VisibilityBadge from "@/lib/components/ui/VisibilityBadge";

import type { Dataset, DatasetUpdate } from "@/lib/types";
import type { VisibilityLevel } from "@/lib/schemas";

export default function DatasetUpdateComponent({
  dataset,
  onChangeDataset,
}: {
  dataset: Dataset;
  onChangeDataset?: (dataset: DatasetUpdate) => void;
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
    return activeUser?.id === dataset.created_by_id;
  }, [activeUser, dataset.created_by_id]);

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
      dataset.owner_group_id != null &&
      !options.some((option) => option.value === dataset.owner_group_id)
    ) {
      options.push({
        id: dataset.owner_group_id,
        label: `Group #${dataset.owner_group_id}`,
        value: dataset.owner_group_id,
      });
    }

    return options;
  }, [managerGroups, dataset.owner_group_id]);

  const groupOptions: Option<number | null>[] = useMemo(
    () => [
      { id: "none", label: "No group", value: null },
      ...baseGroupOptions,
    ],
    [baseGroupOptions],
  );

  const selectedVisibility = useMemo<Option<VisibilityLevel> | undefined>(() => {
    return visibilityOptions.find((option) => option.value === dataset.visibility);
  }, [visibilityOptions, dataset.visibility]);

  const currentVisibility = selectedVisibility?.value ?? dataset.visibility;

  const selectedGroup = useMemo<Option<number | null>>(() => {
    return (
      groupOptions.find((option) => option.value === dataset.owner_group_id) ??
      groupOptions[0]
    );
  }, [groupOptions, dataset.owner_group_id]);

  const handleVisibilityChange = (value: VisibilityLevel) => {
    const update: DatasetUpdate = { visibility: value };
    if (value === "restricted") {
      // If switching to restricted, use the current group or the first available group
      if (dataset.owner_group_id != null) {
        update.owner_group_id = dataset.owner_group_id;
      } else if (baseGroupOptions.length > 0) {
        update.owner_group_id = baseGroupOptions[0].value;
      }
    } else {
      update.owner_group_id = null;
    }
    onChangeDataset?.(update);
  };

  const handleGroupChange = (value: number | null) => {
    onChangeDataset?.({ owner_group_id: value });
  };

  return (
    <Card>
      <div className="px-4 sm:px-0">
        <h3 className="text-base font-semibold leading-7 text-stone-900 dark:text-stone-200">
          Dataset Information
        </h3>
      </div>
      <div className="mt-6 border-t border-stone-300 dark:border-stone-700">
        <dl className="divide-y divide-stone-500">
          <div className="py-6 px-4 sm:px-0">
            <Description
              name="Name"
              value={dataset.name}
              onChange={(name) => onChangeDataset?.({ name })}
              type="text"
              editable
            />
          </div>
          <div className="py-6 px-4 sm:px-0">
            <Description
              name="Description"
              value={dataset.description}
              onChange={(description) => onChangeDataset?.({ description })}
              type="textarea"
              editable
            />
          </div>
          <div className="py-6 px-4 sm:px-0">
            <Description
              name="Created On"
              value={dataset.created_on}
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
                    Only the dataset owner can change visibility
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
      </div>
    </Card>
  );
}
