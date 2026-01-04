import { AxiosInstance } from "axios";

import * as schemas from "@/lib/schemas";
import type * as types from "@/lib/types";

const DEFAULT_ENDPOINTS = {
  listFilters: "/api/v1/species-filters/",
  applyFilter: "/api/v1/foundation_models/runs/{run_uuid}/species-filter-applications/apply",
  listApplications: "/api/v1/foundation_models/runs/{run_uuid}/species-filter-applications/",
  getApplicationProgress: "/api/v1/foundation_models/runs/{run_uuid}/species-filter-applications/{application_uuid}/progress",
  cancelApplication: "/api/v1/foundation_models/runs/{run_uuid}/species-filter-applications/{application_uuid}/cancel",
  getFilterSpecies: "/api/v1/foundation_models/runs/{run_uuid}/species-filter-applications/{application_uuid}/species",
};

export function registerSpeciesFiltersAPI(
  instance: AxiosInstance,
  {
    endpoints = DEFAULT_ENDPOINTS,
  }: {
    endpoints?: typeof DEFAULT_ENDPOINTS;
  } = {},
) {
  /**
   * List all available species filters.
   */
  async function listFilters(): Promise<types.SpeciesFilter[]> {
    const { data } = await instance.get(endpoints.listFilters);
    return schemas.SpeciesFilterSchema.array().parse(data);
  }

  /**
   * Apply a species filter to a foundation model run.
   */
  async function applyFilter(
    runUuid: string,
    data: types.SpeciesFilterApplicationCreate,
  ): Promise<types.SpeciesFilterApplication> {
    const url = endpoints.applyFilter.replace("{run_uuid}", runUuid);
    const body = schemas.SpeciesFilterApplicationCreateSchema.parse(data);
    const { data: responseData } = await instance.post(url, body);
    return schemas.SpeciesFilterApplicationSchema.parse(responseData);
  }

  /**
   * List all filter applications for a foundation model run.
   */
  async function listApplications(
    runUuid: string,
  ): Promise<types.SpeciesFilterApplication[]> {
    const url = endpoints.listApplications.replace("{run_uuid}", runUuid);
    const { data } = await instance.get(url);
    return schemas.SpeciesFilterApplicationSchema.array().parse(data);
  }

  /**
   * Get the progress of a species filter application.
   */
  async function getApplicationProgress(
    runUuid: string,
    applicationUuid: string,
  ): Promise<types.SpeciesFilterApplicationProgress> {
    const url = endpoints.getApplicationProgress
      .replace("{run_uuid}", runUuid)
      .replace("{application_uuid}", applicationUuid);
    const { data } = await instance.get(url);
    return schemas.SpeciesFilterApplicationProgressSchema.parse(data);
  }

  /**
   * Cancel a running species filter application.
   */
  async function cancelApplication(
    runUuid: string,
    applicationUuid: string,
  ): Promise<types.SpeciesFilterApplication> {
    const url = endpoints.cancelApplication
      .replace("{run_uuid}", runUuid)
      .replace("{application_uuid}", applicationUuid);
    const { data } = await instance.post(url);
    return schemas.SpeciesFilterApplicationSchema.parse(data);
  }

  /**
   * Get species filter results for a completed filter application.
   * @param runUuid - The UUID of the foundation model run
   * @param applicationUuid - The UUID of the filter application
   * @param locale - Optional locale for species common names (e.g., "ja", "en_us")
   */
  async function getFilterSpecies(
    runUuid: string,
    applicationUuid: string,
    locale?: string,
  ): Promise<types.SpeciesFilterResults> {
    const url = endpoints.getFilterSpecies
      .replace("{run_uuid}", runUuid)
      .replace("{application_uuid}", applicationUuid);
    const { data } = await instance.get(url, {
      params: locale ? { locale } : undefined,
    });
    return schemas.SpeciesFilterResultsSchema.parse(data);
  }

  return {
    listFilters,
    applyFilter,
    listApplications,
    getApplicationProgress,
    cancelApplication,
    getFilterSpecies,
  } as const;
}
