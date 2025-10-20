import { AxiosInstance } from "axios";

import * as schemas from "@/lib/schemas";
import type * as types from "@/lib/types";

const DEFAULT_ENDPOINTS = {
  audioDir: "/api/v1/setup/audio_dir/",
};

export function registerSetupAPI({
  instance,
  endpoints = DEFAULT_ENDPOINTS,
}: {
  instance: AxiosInstance;
  endpoints?: typeof DEFAULT_ENDPOINTS;
}) {
  async function getAudioDirectory(): Promise<types.AudioDirectory> {
    const { data } = await instance.get(endpoints.audioDir);
    return schemas.AudioDirectorySchema.parse(data);
  }

  async function updateAudioDirectory(
    payload: types.AudioDirectoryUpdate,
  ): Promise<types.AudioDirectory> {
    const body = schemas.AudioDirectoryUpdateSchema.parse(payload);
    const { data } = await instance.post(endpoints.audioDir, body);
    return schemas.AudioDirectorySchema.parse(data);
  }

  return {
    getAudioDirectory,
    updateAudioDirectory,
  } as const;
}
