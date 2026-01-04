/**
 * Echoroo Javascript API
 *
 * This file is the entry point for the Echoroo Javascript API.
 * Use the API to interact with the Echoroo backend.
 */
import axios from "axios";

import { registerAnnotationProjectAPI } from "./annotation_projects";
import { registerAnnotationTasksAPI } from "./annotation_tasks";
import { registerAudioAPI } from "./audio";
import { registerAuthAPI } from "./auth";
import { registerAdminUsersAPI } from "./adminUsers";
import { registerClipAnnotationsAPI } from "./clip_annotations";
import { registerClipEvaluationAPI } from "./clip_evaluations";
import { registerClipPredictionsAPI } from "./clip_predictions";
import { registerClipAPI } from "./clips";
import { registerDatasetAPI } from "./datasets";
import { registerEvaluationSetAPI } from "./evaluation_sets";
import { registerEvaluationAPI } from "./evaluations";
import { registerModelRunAPI } from "./model_runs";
import { registerNotesAPI } from "./notes";
import { registerPluginsAPI } from "./plugins";
import { registerRecordingAPI } from "./recordings";
import { registerMetadataAPI } from "./metadata";
import { registerSoundEventAnnotationsAPI } from "./sound_event_annotations";
import { registerSoundEventEvaluationAPI } from "./sound_event_evaluations";
import { registerSoundEventPredictionsAPI } from "./sound_event_predictions";
import { registerSoundEventAPI } from "./sound_events";
import { registerSpeciesAPI } from "./species";
import { registerSpectrogramAPI } from "./spectrograms";
import { registerTagAPI } from "./tags";
import { registerUserAPI } from "./user";
import { registerUserRunAPI } from "./user_runs";
import { registerInferenceAPI } from "./inference";
import { registerMLProjectAPI } from "./ml_projects";
import { registerReferenceSoundAPI } from "./reference_sounds";
import { registerSearchSessionAPI } from "./search_sessions";
import { registerCustomModelAPI } from "./custom_models";
import { registerInferenceBatchAPI } from "./inference_batches";
import { registerFoundationModelAPI } from "./foundation_models";
import { registerSpeciesFiltersAPI } from "./species_filters";
import { registerDetectionVisualizationAPI } from "./detection_visualization";

type APIConfig = {
  baseURL: string;
  withCredentials: boolean;
};

const DEFAULT_CONFIG: APIConfig = {
  baseURL: `${process.env.NEXT_PUBLIC_BACKEND_HOST}`,
  withCredentials: true,
};

/**
 * Create an instance of the Echoroo API.
 */
export default function createAPI(config: APIConfig = DEFAULT_CONFIG) {
  let instance = axios.create(config);
  return {
    annotationProjects: registerAnnotationProjectAPI(instance, {
      baseUrl: config.baseURL,
    }),
    soundEventAnnotations: registerSoundEventAnnotationsAPI(instance),
    clipAnnotations: registerClipAnnotationsAPI(instance),
    audio: registerAudioAPI({ baseUrl: config.baseURL }),
    auth: registerAuthAPI(instance),
    adminUsers: registerAdminUsersAPI(instance),
    clips: registerClipAPI(instance),
    datasets: registerDatasetAPI({ instance, baseUrl: config.baseURL }),
    metadata: registerMetadataAPI(instance),
    evaluationSets: registerEvaluationSetAPI(instance, {
      baseUrl: config.baseURL,
    }),
    notes: registerNotesAPI(instance),
    recordings: registerRecordingAPI(instance),
    soundEvents: registerSoundEventAPI(instance),
    spectrograms: registerSpectrogramAPI({ baseUrl: config.baseURL }),
    tags: registerTagAPI(instance),
    annotationTasks: registerAnnotationTasksAPI(instance),
    user: registerUserAPI(instance),
    plugins: registerPluginsAPI(instance),
    soundEventPredictions: registerSoundEventPredictionsAPI(instance),
    clipPredictions: registerClipPredictionsAPI(instance),
    modelRuns: registerModelRunAPI(instance),
    userRuns: registerUserRunAPI(instance),
    clipEvaluations: registerClipEvaluationAPI(instance),
    soundEventEvaluations: registerSoundEventEvaluationAPI(instance),
    evaluations: registerEvaluationAPI(instance),
    species: registerSpeciesAPI(instance),
    inference: registerInferenceAPI(instance),
    mlProjects: registerMLProjectAPI(instance),
    referenceSounds: registerReferenceSoundAPI(instance),
    searchSessions: registerSearchSessionAPI(instance),
    customModels: registerCustomModelAPI(instance),
    inferenceBatches: registerInferenceBatchAPI(instance),
    foundationModels: registerFoundationModelAPI(instance),
    speciesFilters: registerSpeciesFiltersAPI(instance),
    detectionVisualization: registerDetectionVisualizationAPI(instance),
  } as const;
}
