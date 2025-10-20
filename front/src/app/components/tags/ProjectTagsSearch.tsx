import { useContext, useMemo, type ComponentProps } from "react";

import AnnotationProjectContext from "@/app/contexts/annotationProject";

import TagSearchBarBase, {
  type TagSearchBarProps,
} from "@/lib/components/tags/TagSearchBar";

import { type Tag } from "@/lib/types";

export default function ProjectTagSearch({
  tags: overrideTags,
  ...props
}: ComponentProps<typeof TagSearchBarBase> & { tags?: Tag[] }) {
  const annotationProject = useContext(AnnotationProjectContext);

  const tags = useMemo<Tag[]>(() => {
    if (overrideTags) return overrideTags;
    return annotationProject?.tags ?? [];
  }, [annotationProject?.tags, overrideTags]);

  const suggestions = useMemo(() => tags, [tags]);

  return (
    <TagSearchBarBase
      tags={suggestions}
      canCreate={false}
      emptyMessage={
        suggestions.length
          ? "No matching project tags."
          : "No project tags registered for this project."
      }
      {...(props as TagSearchBarProps)}
    />
  );
}
