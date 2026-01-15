import { useMemo } from "react";
import { useImmerReducer } from "use-immer";

import { DEFAULT_SPECTROGRAM_SETTINGS } from "@/lib/constants";
import { COLORMAPS, SCALES, WINDOWS } from "@/lib/schemas";
import type { SpectrogramSettings } from "@/lib/types";

/**
 * Custom hook to manage spectrogram settings.
 */
export default function useSpectrogramSettings({
  initialSettings = DEFAULT_SPECTROGRAM_SETTINGS,
}: {
  /** The initial values for the spectrogram settings. */
  initialSettings?: SpectrogramSettings;
}): SpectrogramSettingsInterface {
  const reducer = useMemo(
    () =>
      createSpectrogramSettingsReducer({
        initial: initialSettings,
      }),
    [initialSettings],
  );
  const [settings, dispatch] = useImmerReducer(reducer, initialSettings);
  return {
    settings,
    dispatch,
  };
}

/**
 * Types of actions that can be dispatched to update the spectrogram settings.
 */
export type SpectrogramSettingsAction =
  | { type: "setAll"; settings: SpectrogramSettings }
  | { type: "setWindowSize"; windowSize: number }
  | { type: "setOverlap"; overlap: number }
  | { type: "setScale"; scale: (typeof SCALES)[number] }
  | { type: "setWindow"; window: (typeof WINDOWS)[number] }
  | { type: "setDBRange"; min?: number; max?: number }
  | { type: "setColormap"; colormap: (typeof COLORMAPS)[number] }
  | { type: "setTimeScale"; timeScale: number }
  | { type: "setFreqScale"; freqScale: number }
  | { type: "setHeight"; height: number }
  | { type: "togglePCEN" }
  | { type: "toggleNormalize" }
  | { type: "reset" };

/**
 * Creates a reducer function to manage spectrogram settings.
 */
function createSpectrogramSettingsReducer({
  initial,
}: {
  /** The initial spectrogram settings. */
  initial: SpectrogramSettings;
}) {
  return function spectrogramSettingsReducer(
    draft: SpectrogramSettings,
    action: SpectrogramSettingsAction,
  ) {
    switch (action.type) {
      case "setAll": {
        return action.settings;
      }
      case "setWindowSize": {
        if (action.windowSize <= 0) {
          throw new Error("Window size must be greater than 0");
        }
        draft.window_size = action.windowSize;
        break;
      }
      case "setOverlap": {
        if (action.overlap <= 0 || action.overlap >= 1) {
          throw new Error("Overlap must be between 0 and 1");
        }
        draft.overlap = action.overlap;
        break;
      }
      case "setScale": {
        if (!SCALES.includes(action.scale)) {
          throw new Error(
            `Invalid spectrogram scale, must be one of ${SCALES.join(", ")}`,
          );
        }
        draft.scale = action.scale;
        break;
      }
      case "setWindow": {
        if (!WINDOWS.includes(action.window as any)) {
          throw new Error(
            `Invalid window type, must be one of ${WINDOWS.join(", ")}`,
          );
        }
        draft.window = action.window;
        break;
      }
      case "setDBRange": {
        if (
          action.min != null &&
          action.max != null &&
          action.min >= action.max
        ) {
          throw new Error("Minimum dB must be less than maximum dB");
        }
        if (action.min != null) draft.min_dB = action.min;
        if (action.max != null) draft.max_dB = action.max;
        break;
      }
      case "setColormap": {
        if (!COLORMAPS.includes(action.colormap as any)) {
          throw new Error(
            `Invalid colormap, must be one of ${COLORMAPS.join(", ")}`,
          );
        }
        draft.cmap = action.colormap;
        break;
      }
      case "setTimeScale": {
        if (action.timeScale < 1.0 || action.timeScale > 10) {
          throw new Error("Time scale must be between 1.0 and 10");
        }
        draft.time_scale = action.timeScale;
        break;
      }
      case "setFreqScale": {
        if (action.freqScale <= 0.1 || action.freqScale > 10) {
          throw new Error("Frequency scale must be between 0.1 and 10");
        }
        draft.freq_scale = action.freqScale;
        break;
      }
      case "setHeight": {
        if (action.height <= 0) {
          throw new Error("Height must be greater than 0");
        }
        draft.height = action.height;
        break;
      }
      case "togglePCEN": {
        draft.pcen = !draft.pcen;
        break;
      }
      case "toggleNormalize": {
        draft.normalize = !draft.normalize;
        break;
      }
      case "reset": {
        return initial;
      }
      default: {
        // @ts-ignore
        throw Error("Unknown action: " + action.type);
      }
    }
  };
}

/**
 * Interface for the spectrogram settings hook.
 */
export type SpectrogramSettingsInterface = {
  /** The current spectrogram settings. */
  settings: SpectrogramSettings;
  dispatch: (action: SpectrogramSettingsAction) => void;
};
