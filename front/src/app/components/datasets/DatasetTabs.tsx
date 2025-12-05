import {
  useRouter,
  useSelectedLayoutSegment,
} from "next/navigation";

import {
  AnnotationProjectIcon,
  DatasetIcon,
  RecordingsIcon,
} from "@/lib/components/icons";
import SectionTabs from "@/lib/components/navigation/SectionTabs";
import Tab from "@/lib/components/ui/Tab";

import type { Dataset } from "@/lib/types";

/**
 * Navigation header component for the dataset pages.
 *
 * This component includes the dataset name as the main heading (H1) and a set
 * of tabs for navigating between different sections of the dataset (e.g.,
 * Overview, Recordings, Annotation Projects).
 *
 * @component
 * @param {Object} props - The component properties.
 * @param {Dataset} props.dataset - The dataset object to display information from.
 */
export default function DatasetTabs({ dataset }: { dataset: Dataset }) {
  const router = useRouter();
  const selectedLayoutSegment = useSelectedLayoutSegment();

  return (
    <SectionTabs
      title={dataset.name}
      tabs={[
        <Tab
          key="overview"
          active={selectedLayoutSegment === null}
          onClick={() => router.push(`/datasets/${dataset.uuid}/`)}
        >
          <DatasetIcon className="w-4 h-4 align-middle" />
          Overview
        </Tab>,
        <Tab
          key="recordings"
          active={selectedLayoutSegment === "recordings"}
          onClick={() =>
            router.push(`/datasets/${dataset.uuid}/recordings/`)
          }
        >
          <RecordingsIcon className="w-4 h-4 align-middle" />
          Recordings
        </Tab>,
        <Tab
          key="annotation_projects"
          active={selectedLayoutSegment === "annotation_projects"}
          onClick={() =>
            router.push(`/datasets/${dataset.uuid}/annotation_projects/`)
          }
        >
          <AnnotationProjectIcon className="w-4 h-4 align-middle" />
          Annotation Projects
        </Tab>,
      ]}
    />
  );
}
