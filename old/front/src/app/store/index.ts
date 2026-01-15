// Global state for the application
import { useEffect, useState } from "react";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import { DEFAULT_SPECTROGRAM_SETTINGS } from "@/lib/constants";

import { type AudioSlice, createAudioSlice } from "./audio";
import { type ClipboardSlice, createClipboardSlice } from "./clipboard";
import { type ColorsSlice, createColorsSlice } from "./colors";
import { type SessionSlice, createSessionSlice } from "./session";
import { type SpectrogramSlice, createSpectrogramSlice } from "./spectrogram";

type Store = SessionSlice &
  ClipboardSlice &
  ColorsSlice &
  SpectrogramSlice &
  AudioSlice;

const STORE_VERSION = 1;
const PREVIOUS_DEFAULT_CMAP = "gray";
const PREVIOUS_DEFAULT_WINDOW_SIZE = 0.025;

const migrate = (persistedState: any, version: number) => {
  if (persistedState == null) {
    return persistedState;
  }

  let nextState = { ...persistedState };

  if (version < STORE_VERSION) {
    const prevSettings = nextState.spectrogramSettings;

    if (prevSettings != null) {
      const updatedSettings = {
        ...DEFAULT_SPECTROGRAM_SETTINGS,
        ...prevSettings,
      };

      if (
        prevSettings.cmap == null ||
        prevSettings.cmap === PREVIOUS_DEFAULT_CMAP
      ) {
        updatedSettings.cmap = DEFAULT_SPECTROGRAM_SETTINGS.cmap;
      }

      if (
        prevSettings.window_size == null ||
        Math.abs(prevSettings.window_size - PREVIOUS_DEFAULT_WINDOW_SIZE) <
          1e-6
      ) {
        updatedSettings.window_size =
          DEFAULT_SPECTROGRAM_SETTINGS.window_size;
      }

      nextState = {
        ...nextState,
        spectrogramSettings: updatedSettings,
      };
    }
  }

  return nextState;
};

const useStore = create<Store>()(
  persist(
    (...a) => ({
      ...createSessionSlice(...a),
      ...createClipboardSlice(...a),
      ...createColorsSlice(...a),
      ...createSpectrogramSlice(...a),
      ...createAudioSlice(...a),
    }),
    {
      name: "echoroo-storage",
      storage: createJSONStorage(() => localStorage),
      version: STORE_VERSION,
      migrate,
    },
  ),
);

export const useHydration = () => {
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    const unsubHydrate = useStore.persist.onHydrate(() => setHydrated(false));

    const unsubFinishHydration = useStore.persist.onFinishHydration(() =>
      setHydrated(true),
    );

    setHydrated(useStore.persist.hasHydrated());

    return () => {
      unsubHydrate();
      unsubFinishHydration();
    };
  }, []);

  return hydrated;
};

export default useStore;
