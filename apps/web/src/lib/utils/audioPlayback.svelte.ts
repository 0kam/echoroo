/**
 * audioPlayback - Shared audio playback logic for review card components.
 *
 * Provides a factory function that encapsulates the state and actions needed
 * to fetch an authenticated audio clip from the API and play it in-browser.
 * Used by both DetectionCard and SearchResultCard (via ReviewCard).
 */

import { apiClient } from '$lib/api/client';

export interface AudioPlayer {
  readonly isPlaying: boolean;
  readonly isLoadingAudio: boolean;
  toggle(recordingId: string, startTime: number, endTime: number): Promise<void>;
  stop(): void;
  cleanup(): void;
}

/**
 * Creates an audio player bound to a specific project.
 *
 * Returns a reactive object (using Svelte 5 $state runes) that exposes
 * playback state and control methods. Call `cleanup()` in `onDestroy`.
 */
export function createAudioPlayer(projectId: string): AudioPlayer {
  let isPlaying = $state(false);
  let isLoadingAudio = $state(false);

  let audio: HTMLAudioElement | null = null;
  let audioBlobUrl: string | null = null;

  function buildUrl(recordingId: string, startTime: number, endTime: number): string {
    const params = new URLSearchParams({
      start: startTime.toString(),
      end: endTime.toString(),
    });
    return `/web-api/v1/projects/${projectId}/recordings/${recordingId}/playback?${params}`;
  }

  function stop(): void {
    if (audio) {
      audio.pause();
      audio = null;
    }
    if (audioBlobUrl) {
      URL.revokeObjectURL(audioBlobUrl);
      audioBlobUrl = null;
    }
    isPlaying = false;
  }

  function cleanup(): void {
    stop();
  }

  async function toggle(recordingId: string, startTime: number, endTime: number): Promise<void> {
    if (isPlaying) {
      stop();
      return;
    }

    isLoadingAudio = true;
    try {
      const url = buildUrl(recordingId, startTime, endTime);
      const res = await apiClient.fetchRaw(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();

      // Clean up any previous blob URL before creating a new one
      if (audioBlobUrl) URL.revokeObjectURL(audioBlobUrl);
      audioBlobUrl = URL.createObjectURL(blob);

      audio = new Audio(audioBlobUrl);
      audio.addEventListener('ended', () => {
        isPlaying = false;
      });
      audio.addEventListener('error', () => {
        isPlaying = false;
      });

      await audio.play();
      isPlaying = true;
    } catch {
      isPlaying = false;
      stop();
    } finally {
      isLoadingAudio = false;
    }
  }

  return {
    get isPlaying() {
      return isPlaying;
    },
    get isLoadingAudio() {
      return isLoadingAudio;
    },
    toggle,
    stop,
    cleanup,
  };
}
