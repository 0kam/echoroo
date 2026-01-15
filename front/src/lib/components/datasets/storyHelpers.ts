import type {
  Dataset,
  License,
  Project,
  Recorder,
  Site,
} from "@/lib/types";

export function makeDataset(overrides: Partial<Dataset> = {}): Dataset {
  const timestamp = new Date("2024-01-01T00:00:00Z");

  const project: Project = overrides.project ?? {
    project_id: "prj-demo",
    project_name: "Demo Project",
    url: null,
    description: null,
    target_taxa: null,
    admin_name: "Dr. Demo",
    admin_email: "demo@example.org",
    is_active: true,
    memberships: [],
    created_on: timestamp,
  };

  const site: Site =
    overrides.primary_site ??
    {
      site_id: "site-demo",
      site_name: "Demo Ridge",
      project_id: project.project_id,
      h3_index: "88754e6499fffff",
      images: [],
      center_lat: 35.6895,
      center_lon: 139.6917,
      created_on: timestamp,
    };

  const recorder: Recorder =
    overrides.primary_recorder ??
    {
      recorder_id: "recorder-demo",
      recorder_name: "AudioMoth 1.2.0",
      manufacturer: "Open Acoustic Devices",
      version: "1.2.0",
      usage_count: 3,
      created_on: timestamp,
    };

  const license: License =
    overrides.license ??
    {
      license_id: "cc-by-4.0",
      license_name: "CC-BY 4.0",
      license_link: "https://creativecommons.org/licenses/by/4.0/",
      usage_count: 2,
      created_on: timestamp,
    };

  const base: Dataset = {
    uuid: "00000000-0000-0000-0000-000000000001",
    id: 1,
    name: "Demo Dataset",
    audio_dir: "/data/demo",
    description: "Example dataset used in stories.",
    recording_count: 128,
    created_on: timestamp,
    visibility: "public",
    created_by_id: "00000000-0000-0000-0000-00000000000a",
    project_id: project.project_id,
    primary_site_id: site.site_id,
    primary_recorder_id: recorder.recorder_id,
    license_id: license.license_id,
    doi: null,
    note: null,
    project,
    primary_site: site,
    primary_recorder: recorder,
    license,
    status: "completed",
    processing_progress: 100,
    processing_error: null,
    total_files: 128,
    processed_files: 128,
  };

  return {
    ...base,
    ...overrides,
    project,
    primary_site: site,
    primary_recorder: recorder,
    license,
    created_on: overrides.created_on ?? timestamp,
  };
}
