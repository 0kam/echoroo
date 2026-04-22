// Type contracts for SpectrogramViewer split (P2-B refactor).
// These interfaces define the API surface for the upcoming split of
// SpectrogramViewer.svelte into three modules: ChunkManager,
// SpectrogramInteraction, and SpectrogramCanvas.
// Implementation lands in a follow-up PR.

import type { RecordingDetail } from '$lib/types/data';
import type {
  SpectrogramWindow,
  SpectrogramPosition,
  SpectrogramChunk,
  SpectrogramSettings,
  InteractionMode,
} from '$lib/types/audio';

// --- ChunkManager ---

/**
 * Reactive inputs for the chunk manager. Each field is a getter so that
 * consumers (Svelte components) can pass `$state` / derived values without
 * losing reactivity.
 */
export interface ChunkManagerInput {
  recording: () => RecordingDetail;
  projectId: () => string;
  spectrogramSettings: () => SpectrogramSettings;
  viewport: () => SpectrogramWindow;
}

/**
 * Imperative API returned by the chunk manager. Exposes reactive
 * chunk/image collections plus lifecycle helpers.
 */
export interface ChunkManagerApi {
  readonly chunks: SpectrogramChunk[];
  readonly chunkImages: HTMLImageElement[];
  refreshTokenAndRetryErrors(): Promise<void>;
  dispose(): void;
}

// --- SpectrogramInteraction ---

/**
 * A pending zoom-box selection drawn by the user. `start` and `end`
 * are positions in spectrogram coordinates (seconds / Hz).
 */
export interface ZoomBox {
  start: SpectrogramPosition;
  end: SpectrogramPosition;
}

/**
 * Inputs for the interaction hook. Getters keep reactive references
 * alive across the hook's lifetime.
 */
export interface SpectrogramInteractionInput {
  canvas: () => HTMLCanvasElement | undefined;
  containerEl: () => HTMLDivElement | undefined;
  viewport: () => SpectrogramWindow;
  bounds: () => SpectrogramWindow;
  canvasWidth: () => number;
  canvasHeight: () => number;
  spectrogramSettings: () => SpectrogramSettings;
  interactionMode: () => InteractionMode;
  readonly: () => boolean;
  onViewportChange: (vp: SpectrogramWindow) => void;
  onViewportSave?: () => void;
  onSeek?: (time: number) => void;
  onModeChange?: (mode: InteractionMode) => void;
}

/**
 * Imperative API returned by the interaction hook. The parent component
 * wires `handle*` methods to the canvas event props.
 */
export interface SpectrogramInteractionApi {
  readonly mousePos: SpectrogramPosition | null;
  readonly zoomBox: ZoomBox | null;
  readonly isDragging: boolean;
  handleMouseMove(e: MouseEvent): void;
  handleMouseDown(e: MouseEvent): void;
  handleMouseUp(e: MouseEvent): void;
  handleMouseLeave(): void;
  handleDoubleClick(e: MouseEvent): void;
  handleWheel(e: WheelEvent): void;
  handleKeyDown(e: KeyboardEvent): void;
  dispose(): void;
}

// --- SpectrogramCanvas ---

/**
 * Props for the pure presentational canvas component. `canvas` is
 * `$bindable` so the parent can retain a reference for drawing and
 * interaction wiring.
 */
export interface SpectrogramCanvasProps {
  canvas: HTMLCanvasElement | undefined;
  canvasWidth: number;
  canvasHeight: number;
  viewport: SpectrogramWindow;
  bounds: SpectrogramWindow;
  chunks: SpectrogramChunk[];
  chunkImages: HTMLImageElement[];
  currentTime: number;
  mousePos: SpectrogramPosition | null;
  zoomBox: ZoomBox | null;
  interactionMode: InteractionMode;
  spectrogramSettings: SpectrogramSettings;
  /** When true, the canvas loses focusability (tabindex removed) — readonly fixture. */
  readonly?: boolean;
  /** Current drag state — drives the `cursor-grabbing` class. */
  isDragging?: boolean;
  onmousemove?: (e: MouseEvent) => void;
  onmousedown?: (e: MouseEvent) => void;
  onmouseup?: (e: MouseEvent) => void;
  onmouseleave?: (e: MouseEvent) => void;
  ondblclick?: (e: MouseEvent) => void;
  onwheel?: (e: WheelEvent) => void;
  onkeydown?: (e: KeyboardEvent) => void;
}
