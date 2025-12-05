import { AxiosInstance } from "axios";
import { z } from "zod";

import * as schemas from "@/lib/schemas";
import {
  DatasetDatetimePatternSchema,
  DatasetDatetimePatternUpdateSchema,
} from "@/lib/schemas/datasets";
import type * as types from "@/lib/types";

import { GetMany, Page } from "./common";

const DEFAULT_ENDPOINTS = {
  getMany: "/api/v1/datasets/",
  create: "/api/v1/datasets/",
  candidates: "/api/v1/datasets/candidates/",
  candidateInfo: "/api/v1/datasets/candidates/info/",
  state: "/api/v1/datasets/detail/state/",
  get: "/api/v1/datasets/detail/",
  update: "/api/v1/datasets/detail/",
  delete: "/api/v1/datasets/detail/",
  import: "/api/v1/datasets/import/",
  datetimePattern: "/api/v1/datasets/detail/datetime_pattern/",
  parseDatetime: "/api/v1/datasets/detail/parse_datetime/",
  datetimeParseStatus: "/api/v1/datasets/detail/datetime_parse_status/",
  filenameSamples: "/api/v1/datasets/detail/filename_samples/",
  stats: "/api/v1/datasets/detail/stats/",
  exportBioacoustics: "/api/v1/datasets/detail/export/bioacoustics/",
};

export function registerDatasetAPI({
  instance,
  endpoints = DEFAULT_ENDPOINTS,
  baseUrl = "",
}: {
  instance: AxiosInstance;
  endpoints?: typeof DEFAULT_ENDPOINTS;
  baseUrl?: string;
}) {
  async function getMany(
    query: types.GetMany & types.DatasetFilter,
  ): Promise<types.Page<types.Dataset>> {
    const params = GetMany(schemas.DatasetFilterSchema).parse(query);
    const { data } = await instance.get(endpoints.getMany, { params });
    return Page(schemas.DatasetSchema).parse(data);
  }

  async function create(data: types.DatasetCreate): Promise<types.Dataset> {
    const body = schemas.DatasetCreateSchema.parse(data);
    const { data: res } = await instance.post(endpoints.create, body);
    return schemas.DatasetSchema.parse(res);
  }

  async function getCandidates(): Promise<types.DatasetCandidate[]> {
    const { data } = await instance.get(endpoints.candidates);
    return z.array(schemas.DatasetCandidateSchema).parse(data);
  }

  async function inspectCandidate(
    relativePath: string,
  ): Promise<types.DatasetCandidateInfo> {
    const { data } = await instance.get(endpoints.candidateInfo, {
      params: { relative_path: relativePath },
    });
    return schemas.DatasetCandidateInfoSchema.parse(data);
  }

  async function get(uuid: string): Promise<types.Dataset> {
    const { data } = await instance.get(endpoints.get, {
      params: { dataset_uuid: uuid },
    });
    return schemas.DatasetSchema.parse(data);
  }

  async function getDatasetState(
    uuid: string,
  ): Promise<types.RecordingState[]> {
    const { data } = await instance.get(endpoints.state, {
      params: { dataset_uuid: uuid },
    });
    return z.array(schemas.RecordingStateSchema).parse(data);
  }

  async function updateDataset(
    dataset: types.Dataset,
    data: types.DatasetUpdate,
  ): Promise<types.Dataset> {
    const body = schemas.DatasetUpdateSchema.parse(data);
    const { data: res } = await instance.patch(endpoints.update, body, {
      params: { dataset_uuid: dataset.uuid },
    });
    return schemas.DatasetSchema.parse(res);
  }

  async function deleteDataset(dataset: types.Dataset): Promise<types.Dataset> {
    const { data } = await instance.delete(endpoints.delete, {
      params: { dataset_uuid: dataset.uuid },
    });
    return schemas.DatasetSchema.parse(data);
  }

  async function importDataset(
    data: types.DatasetImport,
  ): Promise<types.Dataset> {
    const formData = new FormData();
    const file = data.dataset[0];
    formData.append("dataset", file);
    formData.append("audio_dir", data.audio_dir);
    const { data: res } = await instance.post(endpoints.import, formData);
    return schemas.DatasetSchema.parse(res);
  }

  async function setDatetimePattern(
    uuid: string,
    pattern: types.DatasetDatetimePatternUpdate,
  ): Promise<types.DatasetDatetimePattern> {
    const body = DatasetDatetimePatternUpdateSchema.parse(pattern);
    const { data } = await instance.post(endpoints.datetimePattern, body, {
      params: { dataset_uuid: uuid },
    });
    return DatasetDatetimePatternSchema.parse(data);
  }

  async function parseDatetime(
    uuid: string,
  ): Promise<{ total: number; success: number; failure: number }> {
    const { data } = await instance.post(
      endpoints.parseDatetime,
      {},
      {
        params: { dataset_uuid: uuid },
      },
    );
    return data;
  }

  async function getDatetimeParseStatus(
    uuid: string,
  ): Promise<{ pending: number; success: number; failed: number }> {
    const { data } = await instance.get(endpoints.datetimeParseStatus, {
      params: { dataset_uuid: uuid },
    });
    return data;
  }

  async function getFilenameSamples(
    uuid: string,
    limit: number = 20,
  ): Promise<string[]> {
    const { data } = await instance.get(endpoints.filenameSamples, {
      params: { dataset_uuid: uuid, limit },
    });
    return z.array(z.string()).parse(data);
  }

  async function getStats(uuid: string): Promise<types.DatasetOverviewStats> {
    const { data } = await instance.get(endpoints.stats, {
      params: { dataset_uuid: uuid },
    });
    return schemas.DatasetOverviewStatsSchema.parse(data);
  }

  async function exportBioacoustics(
    uuid: string,
    options: { includeAudio?: boolean } = {},
  ): Promise<void> {
    // Use fetch API to wait for server to prepare the ZIP file.
    // The response headers arrive only after ZIP creation is complete on the server,
    // then we trigger native browser download for efficient streaming to disk.
    const includeAudio = options.includeAudio ?? false;
    const params = new URLSearchParams({
      dataset_uuid: uuid,
      include_audio: String(includeAudio),
    });
    const downloadUrl = `${baseUrl}${endpoints.exportBioacoustics}?${params.toString()}`;

    // Use fetch to wait for the server to prepare the file (ZIP creation).
    // The response headers are sent only after the ZIP file is ready.
    const response = await fetch(downloadUrl, {
      method: "GET",
      credentials: "include",
    });

    if (!response.ok) {
      throw new Error(`Download failed: ${response.statusText}`);
    }

    // Extract filename from Content-Disposition header
    const contentDisposition = response.headers.get("Content-Disposition");
    let filename = "dataset_export.zip";
    if (contentDisposition) {
      const match = contentDisposition.match(/filename="?([^";\n]+)"?/);
      if (match) {
        filename = match[1];
      }
    }

    // Cancel the fetch body (we don't want to download via JS)
    // and trigger native browser download instead
    await response.body?.cancel();

    // Now trigger native browser download - the server will stream the file
    // This opens a new request but the file should be cached/ready on server
    const link = document.createElement("a");
    link.href = downloadUrl;
    link.download = filename;
    link.style.display = "none";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  }

  return {
    getMany,
    create,
    get,
    getState: getDatasetState,
    update: updateDataset,
    delete: deleteDataset,
    import: importDataset,
    getCandidates,
    inspectCandidate,
    setDatetimePattern,
    parseDatetime,
    getDatetimeParseStatus,
    getFilenameSamples,
    getStats,
    exportBioacoustics,
  } as const;
}
