import { createContext } from "react";

import type { Dataset } from "@/lib/types";

const DatasetContext = createContext<Dataset>({
  id: 0,
  uuid: "",
  name: "",
  description: "",
  created_on: new Date(),
  audio_dir: "",
  recording_count: 0,
  project_id: "",
  visibility: "restricted",
  created_by_id: "",
  primary_site_id: null,
  primary_recorder_id: null,
  license_id: null,
  status: "pending",
  processing_progress: 0,
  processing_error: null,
  total_files: null,
  processed_files: 0,
});

export default DatasetContext;
