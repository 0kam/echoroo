import DetailLayout from "@/lib/components/layouts/Detail";

/**
  * DatasetDetail component renders the detailed view of a dataset.
  * It uses the DetailLayout component to structure the layout.
  */
export default function DatasetDetail(props: {
  /** The component for updating the dataset. */
  DatasetUpdate: JSX.Element;
  /** The component for dataset actions. */
  DatasetActions: JSX.Element;
  /** The component for displaying the dataset overview. */
  DatasetOverview: JSX.Element;
  /** The component for displaying dataset metadata summary. */
  DatasetMetadataSummary?: JSX.Element;
  /** The component for displaying the dataset notes summary. */
  DatasetNotesSummary: JSX.Element;
  /** The component for displaying the annotation projects summary. */
  DatasetAnnotationProjectsSummary?: JSX.Element;
}) {
  return (
    <DetailLayout
      Actions={props.DatasetActions}
      SideBar={props.DatasetUpdate}
      MainContent={
        <div className="grid grid-cols-2 gap-8">
          <div className="col-span-2 space-y-6">
            {props.DatasetOverview}
            {props.DatasetMetadataSummary ?? null}
          </div>
          <div className="col-span-1">
            {props.DatasetNotesSummary}
          </div>
          <div className="col-span-1">
            {props.DatasetAnnotationProjectsSummary ?? null}
          </div>
        </div>
      }
    />
  );
}
