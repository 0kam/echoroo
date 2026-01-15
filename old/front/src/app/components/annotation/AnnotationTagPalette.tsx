import { useCallback } from "react";
import toast from "react-hot-toast";

import useClipAnnotation from "@/app/hooks/api/useClipAnnotation";

import useStore from "@/app/store";

import AnnotationTagPaletteBase from "@/lib/components/annotation/AnnotationTagPalette";
import AddTagButton from "@/lib/components/tags/AddTagButton";

import type { ClipAnnotation, Tag } from "@/lib/types";

import ProjectTagSearch from "../tags/ProjectTagsSearch";

export default function AnnotationTagPalette({
  clipAnnotation,
  tags,
  availableTags,
  onAddTag,
  onRemoveTag,
}: {
  clipAnnotation?: ClipAnnotation;
  tags: Tag[];
  availableTags: Tag[];
  onAddTag?: (tag: Tag) => void;
  onRemoveTag?: (tag: Tag) => void;
}) {
  const tagColorFn = useStore((state) => state.getTagColor);

  const { addClipAnnotationTag } = useClipAnnotation({
    uuid: clipAnnotation?.uuid || "",
    clipAnnotation: clipAnnotation || undefined,
    enabled: clipAnnotation != null,
  });

  const handleProjectTagAdded = useCallback(
    (tag: Tag) => {
      onAddTag?.(tag);
      toast.success("Tag added to project.");
    },
    [onAddTag],
  );

  const projectTagActions = (
    <AddTagButton
      text="Search GBIF"
      variant="primary"
      TagSearchBar={ProjectTagSearch}
      onSelectTag={handleProjectTagAdded}
    />
  );

  return (
    <AnnotationTagPaletteBase
      tags={tags}
      availableTags={availableTags}
      tagColorFn={tagColorFn}
      onSelectTag={onAddTag}
      onRemoveTag={onRemoveTag}
      projectTagActions={projectTagActions}
      onClick={(tag) =>
        addClipAnnotationTag.mutate(tag, {
          onSuccess: () => toast.success("Tag added."),
        })
      }
    />
  );
}
