"use client";

import { AxiosInstance } from "axios";
import { z } from "zod";

// ============================================================================
// Schemas
// ============================================================================

export const DetectionTemporalDataPointSchema = z.object({
  date: z.string(),
  hour: z.number().int().min(0).max(23),
  count: z.number().int().min(0),
});

export const SpeciesTemporalDataSchema = z.object({
  scientific_name: z.string(),
  common_name: z.string().nullable().optional(),
  total_detections: z.number().int(),
  detections: z.array(DetectionTemporalDataPointSchema),
});

export const DetectionTemporalResponseSchema = z.object({
  run_uuid: z.string().uuid(),
  filter_application_uuid: z.string().uuid().nullable().optional(),
  species: z.array(SpeciesTemporalDataSchema),
  date_range: z.tuple([z.string(), z.string()]).nullable().optional(),
});

// ============================================================================
// Types
// ============================================================================

export type DetectionTemporalDataPoint = z.infer<
  typeof DetectionTemporalDataPointSchema
>;
export type SpeciesTemporalData = z.infer<typeof SpeciesTemporalDataSchema>;
export type DetectionTemporalResponse = z.infer<
  typeof DetectionTemporalResponseSchema
>;

// ============================================================================
// API Endpoints
// ============================================================================

const DEFAULT_ENDPOINTS = {
  temporal: "/api/v1/detection_visualization/temporal/",
  temporalInference: "/api/v1/detection_visualization/temporal_inference/",
};

// ============================================================================
// API Registration
// ============================================================================

export function registerDetectionVisualizationAPI(instance: AxiosInstance) {
  /**
   * Get temporal detection data for visualization.
   * Returns detection counts grouped by species, date, and hour.
   */
  async function getTemporalData({
    runUuid,
    filterApplicationUuid,
  }: {
    runUuid: string;
    filterApplicationUuid?: string;
  }): Promise<DetectionTemporalResponse> {
    const params: Record<string, string> = {
      run_uuid: runUuid,
    };
    if (filterApplicationUuid) {
      params.filter_application_uuid = filterApplicationUuid;
    }
    const { data } = await instance.get(DEFAULT_ENDPOINTS.temporal, { params });
    return DetectionTemporalResponseSchema.parse(data);
  }

  /**
   * Get temporal inference batch data for visualization.
   * Returns detection counts grouped by date and hour for a specific inference batch.
   */
  async function getInferenceBatchTemporal({
    batchUuid,
  }: {
    batchUuid: string;
  }): Promise<DetectionTemporalResponse> {
    const params: Record<string, string> = {
      batch_uuid: batchUuid,
    };
    const { data } = await instance.get(DEFAULT_ENDPOINTS.temporalInference, { params });
    return DetectionTemporalResponseSchema.parse(data);
  }

  return {
    getTemporalData,
    getInferenceBatchTemporal,
  };
}
