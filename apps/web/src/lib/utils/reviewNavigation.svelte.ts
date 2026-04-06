/**
 * Shared keyboard navigation and audio playback for review grids.
 *
 * Used by both search results review (ResultsPanel) and detection review
 * (DetectionReviewGrid) to eliminate duplicated keyboard handling, audio
 * player management, and selection state logic.
 *
 * Uses Svelte 5 runes ($state) so the file must have the .svelte.ts extension.
 */

import { createAudioPlayer, type AudioPlayer } from '$lib/utils/audioPlayback.svelte';

export interface PlaybackInfo {
  recordingId: string;
  startTime: number;
  endTime: number;
}

export interface ReviewNavigationOptions {
  /** Project ID used to construct audio playback URLs */
  projectId: string;
  /** Total number of items in the current list */
  itemCount: () => number;
  /** Called when confirm is triggered (keyboard C) on the selected item (legacy) */
  onConfirm: (index: number) => void;
  /** Called when reject is triggered (keyboard R) on the selected item (legacy) */
  onReject: (index: number) => void;
  /** Called when agree vote is triggered (keyboard A) on the selected item */
  onAgree?: (index: number) => void;
  /** Called when disagree vote is triggered (keyboard D) on the selected item */
  onDisagree?: (index: number) => void;
  /** Called when unsure vote is triggered (keyboard U) on the selected item */
  onUnsure?: (index: number) => void;
  /** Return recording info for the item at `index` to play audio, or null to skip */
  getPlaybackInfo: (index: number) => PlaybackInfo | null;
  /** Return the DOM element for the item at `index` (for scroll-into-view) */
  getElement: (index: number) => HTMLElement | null;
}

export interface ReviewNavigation {
  /** Currently focused item index */
  readonly selectedIndex: number;
  /** Whether the shared player is currently playing */
  readonly isPlaying: boolean;
  /** Whether the shared player is loading audio */
  readonly isLoadingAudio: boolean;
  /** Index of the item whose audio is playing, or -1 if nothing is playing */
  readonly playingIndex: number;
  /** Set selected index (e.g. when switching tabs or resetting) */
  select: (index: number) => void;
  /** Keydown handler to attach to svelte:window */
  handleKeydown: (e: KeyboardEvent) => void;
  /** Toggle playback for a specific index (used by card play buttons) */
  togglePlay: (index: number) => void;
  /** Stop any ongoing playback */
  stop: () => void;
  /** Clean up resources (call in onDestroy) */
  cleanup: () => void;
}

/**
 * Creates a shared keyboard navigation and audio playback controller.
 *
 * Handles:
 * - Arrow Up/Down (and Left/Right) to navigate between items
 * - Space to toggle audio playback on the selected item
 * - C to confirm the selected item
 * - R to reject the selected item
 * - Auto-scrolls the selected item into view
 * - Skips keyboard handling when focus is inside input/textarea/select
 * - Exposes isPlaying and playingIndex so child cards can sync their play button UI
 */
export function createReviewNavigation(options: ReviewNavigationOptions): ReviewNavigation {
  let selectedIndex = $state(0);
  let playingIndex = $state(-1);

  const player: AudioPlayer = createAudioPlayer(options.projectId);

  function isInputFocused(target: EventTarget | null): boolean {
    if (!target || !(target instanceof HTMLElement)) return false;
    const tag = target.tagName;
    return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
  }

  function scrollIntoView() {
    queueMicrotask(() => {
      options.getElement(selectedIndex)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    });
  }

  function stopPlayback() {
    player.stop();
    playingIndex = -1;
  }

  async function togglePlayAtIndex(index: number) {
    const info = options.getPlaybackInfo(index);
    if (!info) return;

    // If already playing this index, stop
    if (playingIndex === index && player.isPlaying) {
      stopPlayback();
      return;
    }

    // If playing a different index, stop the old one first
    if (player.isPlaying) {
      player.stop();
    }

    playingIndex = index;
    await player.toggle(info.recordingId, info.startTime, info.endTime);

    // The player's 'ended' event sets isPlaying to false but we need to
    // also reset playingIndex. We poll via a microtask after the audio
    // has been started to set up cleanup.
    if (player.isPlaying) {
      waitForPlaybackEnd();
    } else {
      // toggle() returned but audio isn't playing (e.g. failed to load)
      playingIndex = -1;
    }
  }

  /**
   * Periodically check if the player stopped (due to audio ending or error)
   * and reset playingIndex accordingly. This is cheaper than patching the
   * AudioPlayer's internal event listeners.
   */
  function waitForPlaybackEnd() {
    const checkInterval = setInterval(() => {
      if (!player.isPlaying) {
        playingIndex = -1;
        clearInterval(checkInterval);
      }
    }, 100);

    // Safety: clear after 5 minutes max to avoid leaks
    setTimeout(() => clearInterval(checkInterval), 5 * 60 * 1000);
  }

  function handleKeydown(e: KeyboardEvent) {
    if (isInputFocused(e.target)) return;

    const count = options.itemCount();
    if (count === 0) return;

    switch (e.key) {
      case ' ':
        e.preventDefault();
        togglePlayAtIndex(selectedIndex);
        break;

      case 'c':
      case 'C':
        e.preventDefault();
        options.onConfirm(selectedIndex);
        break;

      case 'r':
      case 'R':
        e.preventDefault();
        options.onReject(selectedIndex);
        break;

      case 'a':
      case 'A':
        e.preventDefault();
        options.onAgree?.(selectedIndex);
        break;

      case 'd':
      case 'D':
        e.preventDefault();
        options.onDisagree?.(selectedIndex);
        break;

      case 'u':
      case 'U':
        e.preventDefault();
        options.onUnsure?.(selectedIndex);
        break;

      case 'ArrowDown':
      case 'ArrowRight':
        e.preventDefault();
        stopPlayback();
        selectedIndex = Math.min(selectedIndex + 1, count - 1);
        scrollIntoView();
        break;

      case 'ArrowUp':
      case 'ArrowLeft':
        e.preventDefault();
        stopPlayback();
        selectedIndex = Math.max(selectedIndex - 1, 0);
        scrollIntoView();
        break;

      default:
        return; // Don't call preventDefault for unhandled keys
    }
  }

  function select(index: number) {
    stopPlayback();
    selectedIndex = index;
  }

  function cleanup() {
    stopPlayback();
    player.cleanup();
  }

  return {
    get selectedIndex() {
      return selectedIndex;
    },
    get isPlaying() {
      return player.isPlaying;
    },
    get isLoadingAudio() {
      return player.isLoadingAudio;
    },
    get playingIndex() {
      return playingIndex;
    },
    select,
    handleKeydown,
    togglePlay: togglePlayAtIndex,
    stop: stopPlayback,
    cleanup,
  };
}
