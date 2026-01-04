import { FC, type ReactNode } from "react";

import { DeleteIcon, ToolsIcon } from "@/lib/components/icons";
import TagComponent from "@/lib/components/tags/Tag";
import TagSearchBarBase, {
  type TagSearchBarProps,
} from "@/lib/components/tags/TagSearchBar";
import Button from "@/lib/components/ui/Button";
import Card from "@/lib/components/ui/Card";
import { H4 } from "@/lib/components/ui/Headings";
import Tooltip from "@/lib/components/ui/Tooltip";

import type { Tag } from "@/lib/types";
import { type Color, getTagKey } from "@/lib/utils/tags";

const DEFAULT_COLOR: Color = { color: "stone", level: 3 };

export default function AnnotationTagPalette({
  tags,
  availableTags = [],
  onClick,
  onRemoveTag,
  onClearTags,
  tagColorFn,
  TagSearchBar = TagSearchBarBase,
  projectTagActions,
  ...tagSearchProps
}: {
  tags: Tag[];
  availableTags?: Tag[];
  onClick?: (tag: Tag) => void;
  onRemoveTag?: (tag: Tag) => void;
  onClearTags?: () => void;
  tagColorFn?: (tag: Tag) => Color;
  TagSearchBar?: FC<TagSearchBarProps>;
  projectTagActions?: ReactNode;
} & TagSearchBarProps) {
  const selectedKeys = new Set(tags.map(getTagKey));
  const suggestions = availableTags.filter(
    (tag) => !selectedKeys.has(getTagKey(tag)),
  );
  const effectiveEmptyMessage =
    tagSearchProps.emptyMessage ??
    (availableTags.length === 0
      ? "No project tags available."
      : "No matching project tags.");

  return (
    <Card>
      <H4 className="text-center">
        <Tooltip
          tooltip={
            <div className="w-48 text-center">
              The tags selected here will be automatically attached to newly
              created annotations.
            </div>
          }
          placement="top"
        >
          <ToolsIcon className="inline-block mr-1 w-5 h-5" />
          <span className="cursor-help">Tag Palette</span>
        </Tooltip>
      </H4>
      <div className="flex flex-row gap-2 w-full items-start">
        <Tooltip tooltip="Clear tags" placement="top">
          <Button onClick={onClearTags} mode="text" variant="danger">
            <DeleteIcon className="w-5 h-5" />
          </Button>
        </Tooltip>
        <div className="grow">
          <TagSearchBar
            tags={suggestions}
            tagColorFn={tagColorFn}
            emptyMessage={effectiveEmptyMessage}
            disabled={availableTags.length === 0}
            {...(tagSearchProps as any)}
          />
        </div>
        {projectTagActions}
      </div>
      <div className="flex flex-row flex-wrap gap-1">
        {tags.map((tag) => (
          <TagComponent
            key={`${tag.key}-${tag.value}`}
            tag={tag}
            {...(tagColorFn ? tagColorFn(tag) : DEFAULT_COLOR)}
            onClick={() => onClick?.(tag)}
            onClose={() => onRemoveTag?.(tag)}
          />
        ))}
      </div>
    </Card>
  );
}
