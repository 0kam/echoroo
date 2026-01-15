import { TagsIcon } from "@/lib/components/icons";
import TagList from "@/lib/components/tags/TagList";
import { H2, H3 } from "@/lib/components/ui/Headings";
import Info from "@/lib/components/ui/Info";

import type { AnnotationProject, Color, Tag } from "@/lib/types";

export default function AnnotationProjectTags({
  annotationProject,
  onDeleteTag,
  TagSearchBar,
  tagColorFn,
}: {
  annotationProject: AnnotationProject;
  onDeleteTag?: (tag: Tag) => void;
  TagSearchBar?: JSX.Element;
  tagColorFn?: (tag: Tag) => Color;
}) {
  return (
    <div className="flex flex-col gap-6 p-4">
      <H2>
        <TagsIcon className="inline-block mr-2 w-8 h-8 align-middle" />
        Species Tags
      </H2>
      <p className="text-stone-500">
        Search the GBIF Backbone taxonomy and add the species labels that should
        be available to annotators in this project.
      </p>
      <Info className="mt-2">
        Only taxa registered in GBIF can be selected. Search for the scientific
        name, review the suggestions, and click a result to add it.
      </Info>
      <div className="max-w-xl">{TagSearchBar}</div>
      <div className="flex flex-col gap-2">
        <H3>Tags in this project</H3>
        <p className="text-stone-500">
          <span className="font-bold text-blue-500">
            {(annotationProject.tags ?? []).length.toLocaleString()}
          </span>{" "}
          {annotationProject.tags?.length === 1
            ? "species tag selected."
            : "species tags selected."}
        </p>
        <small className="text-stone-500">
          Click a tag to remove it from the project.
        </small>
        <TagList
          tags={annotationProject.tags ?? []}
          onClick={onDeleteTag}
          tagColorFn={tagColorFn}
        />
      </div>
    </div>
  );
}
