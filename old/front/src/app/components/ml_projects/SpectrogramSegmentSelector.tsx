"use client";

/**
 * AudioSegmentSelector Component
 *
 * Displays a waveform visualization and allows users to select a time segment
 * by dragging on the waveform. Supports audio preview of the selected segment.
 *
 * Uses waveform instead of spectrogram for fast rendering.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Loader2, Pause, Play } from "lucide-react";

import useAudio from "@/lib/hooks/audio/useAudio";
import { scalePixelsToWindow, scaleTimeToViewport } from "@/lib/utils/geometry";
import type { Dimensions, Interval, SpectrogramWindow } from "@/lib/types";

import Button from "@/lib/components/ui/Button";

// Constants for segment validation
const MIN_SEGMENT_DURATION = 1; // seconds
const WARNING_SEGMENT_DURATION = 30; // seconds

export interface SpectrogramSegmentSelectorProps {
  /** The URL to fetch audio from */
  audioUrl: string;
  /** Callback when segment selection changes */
  onSegmentChange: (startTime: number, endTime: number) => void;
  /** Initial start time in seconds */
  initialStartTime?: number;
  /** Initial end time in seconds */
  initialEndTime?: number;
  /** Total duration of the audio in seconds (if known) */
  duration?: number;
  /** Height of the display */
  height?: number;
}

/**
 * Hook for loading audio and generating waveform data
 */
function useWaveformData({
  audioUrl,
  onDurationDetected,
}: {
  audioUrl: string;
  onDurationDetected?: (duration: number) => void;
}) {
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [waveformData, setWaveformData] = useState<Float32Array | null>(null);
  const [duration, setDuration] = useState<number>(0);

  // Use ref to avoid re-running effect when callback changes
  const onDurationDetectedRef = useRef(onDurationDetected);
  onDurationDetectedRef.current = onDurationDetected;

  useEffect(() => {
    if (!audioUrl) return;

    let isCancelled = false;
    let audioContext: AudioContext | null = null;

    async function loadAndAnalyze() {
      setIsLoading(true);
      setError(null);

      try {
        audioContext = new AudioContext();

        const response = await fetch(audioUrl);
        if (!response.ok) {
          throw new Error(`Failed to fetch audio: ${response.status}`);
        }

        const arrayBuffer = await response.arrayBuffer();
        const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);

        if (isCancelled) return;

        const audioDuration = audioBuffer.duration;
        setDuration(audioDuration);
        onDurationDetectedRef.current?.(audioDuration);

        // Generate waveform data (downsampled for display)
        const waveform = generateWaveform(audioBuffer, 2000);
        setWaveformData(waveform);
        setIsLoading(false);
      } catch (err) {
        if (isCancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load audio");
        setIsLoading(false);
      }
    }

    loadAndAnalyze();

    return () => {
      isCancelled = true;
      if (audioContext) {
        audioContext.close();
      }
    };
  }, [audioUrl]);

  return { isLoading, error, waveformData, duration };
}

/**
 * Generate downsampled waveform data from AudioBuffer
 * Returns peak amplitudes for each time bucket
 */
function generateWaveform(audioBuffer: AudioBuffer, numPoints: number): Float32Array {
  const channelData = audioBuffer.getChannelData(0);
  const samplesPerPoint = Math.floor(channelData.length / numPoints);
  const waveform = new Float32Array(numPoints);

  for (let i = 0; i < numPoints; i++) {
    const start = i * samplesPerPoint;
    const end = Math.min(start + samplesPerPoint, channelData.length);

    // Find peak amplitude in this bucket
    let peak = 0;
    for (let j = start; j < end; j++) {
      const abs = Math.abs(channelData[j]);
      if (abs > peak) peak = abs;
    }
    waveform[i] = peak;
  }

  return waveform;
}

export default function SpectrogramSegmentSelector({
  audioUrl,
  onSegmentChange,
  initialStartTime = 0,
  initialEndTime,
  duration: externalDuration,
  height = 150,
}: SpectrogramSegmentSelectorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // Selection state
  const [selection, setSelection] = useState<Interval | null>(
    initialEndTime != null
      ? { min: initialStartTime, max: initialEndTime }
      : null,
  );
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState<number | null>(null);
  const [dimensions, setDimensions] = useState<Dimensions>({
    width: 600,
    height,
  });

  // Audio duration
  const [audioDuration, setAudioDuration] = useState<number>(
    externalDuration || 30,
  );

  // Load waveform
  const { isLoading, error, waveformData, duration: detectedDuration } =
    useWaveformData({
      audioUrl,
      onDurationDetected: (d) => {
        setAudioDuration(d);
        // Set default selection if not provided
        if (selection == null) {
          const defaultEnd = Math.min(5, d);
          setSelection({ min: 0, max: defaultEnd });
          onSegmentChange(0, defaultEnd);
        }
      },
    });

  // Use detected duration if available
  const effectiveDuration = detectedDuration || externalDuration || audioDuration;

  // Viewport for time mapping
  const viewport: SpectrogramWindow = useMemo(
    () => ({
      time: { min: 0, max: effectiveDuration },
      freq: { min: 0, max: 1 }, // Not used for waveform
    }),
    [effectiveDuration],
  );

  // Audio playback
  const audio = useAudio({
    url: audioUrl,
    onTimeUpdate: (time) => {
      // Stop at end of selection
      if (selection && time >= selection.max) {
        audio.pause();
        audio.seek(selection.min);
      }
    },
  });

  // Handle container resize
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setDimensions({
          width: entry.contentRect.width,
          height,
        });
      }
    });

    observer.observe(container);
    return () => observer.disconnect();
  }, [height]);

  // Draw waveform and selection overlay
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    // Set canvas size
    canvas.width = dimensions.width;
    canvas.height = dimensions.height;

    // Clear canvas
    ctx.fillStyle = "#1c1917"; // stone-900
    ctx.fillRect(0, 0, dimensions.width, dimensions.height);

    // Draw waveform if available
    if (waveformData) {
      const centerY = dimensions.height / 2;
      const maxHeight = dimensions.height * 0.8;

      // Draw waveform as filled area
      ctx.beginPath();
      ctx.moveTo(0, centerY);

      for (let i = 0; i < waveformData.length; i++) {
        const x = (i / waveformData.length) * dimensions.width;
        const amplitude = waveformData[i] * maxHeight / 2;
        ctx.lineTo(x, centerY - amplitude);
      }

      // Top half done, now bottom half (mirror)
      for (let i = waveformData.length - 1; i >= 0; i--) {
        const x = (i / waveformData.length) * dimensions.width;
        const amplitude = waveformData[i] * maxHeight / 2;
        ctx.lineTo(x, centerY + amplitude);
      }

      ctx.closePath();
      ctx.fillStyle = "#3b82f6"; // blue-500
      ctx.fill();

      // Draw center line
      ctx.beginPath();
      ctx.moveTo(0, centerY);
      ctx.lineTo(dimensions.width, centerY);
      ctx.strokeStyle = "#64748b"; // slate-500
      ctx.lineWidth = 1;
      ctx.stroke();
    } else if (isLoading) {
      // Show loading state
      ctx.fillStyle = "#78716c"; // stone-500
      ctx.font = "14px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(
        "Loading audio...",
        dimensions.width / 2,
        dimensions.height / 2,
      );
    } else if (error) {
      // Show error state
      ctx.fillStyle = "#ef4444"; // red-500
      ctx.font = "14px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(
        `Error: ${error}`,
        dimensions.width / 2,
        dimensions.height / 2,
      );
    }

    // Draw selection overlay
    if (selection && waveformData) {
      const startX = scaleTimeToViewport(selection.min, viewport, dimensions.width);
      const endX = scaleTimeToViewport(selection.max, viewport, dimensions.width);

      // Darken non-selected areas
      ctx.fillStyle = "rgba(0, 0, 0, 0.6)";
      ctx.fillRect(0, 0, startX, dimensions.height);
      ctx.fillRect(endX, 0, dimensions.width - endX, dimensions.height);

      // Draw selection border
      ctx.strokeStyle = "#10b981"; // emerald-500
      ctx.lineWidth = 2;
      ctx.strokeRect(startX, 0, endX - startX, dimensions.height);

      // Draw handles
      ctx.fillStyle = "#10b981";
      ctx.fillRect(startX - 3, 0, 6, dimensions.height);
      ctx.fillRect(endX - 3, 0, 6, dimensions.height);
    }

    // Draw current playback position
    if (audio.isPlaying && selection) {
      const playX = scaleTimeToViewport(
        audio.currentTime,
        viewport,
        dimensions.width,
      );
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(playX, 0);
      ctx.lineTo(playX, dimensions.height);
      ctx.stroke();
    }

    // Draw time axis
    ctx.fillStyle = "#a8a29e"; // stone-400
    ctx.font = "11px sans-serif";
    ctx.textAlign = "center";

    const numTicks = Math.min(10, Math.max(2, Math.floor(effectiveDuration)));
    for (let i = 0; i <= numTicks; i++) {
      const time = (i / numTicks) * effectiveDuration;
      const x = scaleTimeToViewport(time, viewport, dimensions.width);
      ctx.fillText(`${time.toFixed(1)}s`, x, dimensions.height - 4);
    }
  }, [
    waveformData,
    selection,
    dimensions,
    viewport,
    isLoading,
    error,
    audio.isPlaying,
    audio.currentTime,
    effectiveDuration,
  ]);

  // Mouse/touch event handlers
  const getTimeFromEvent = useCallback(
    (e: React.MouseEvent | React.TouchEvent): number => {
      const canvas = canvasRef.current;
      if (!canvas) return 0;

      const rect = canvas.getBoundingClientRect();
      const clientX =
        "touches" in e ? e.touches[0].clientX : e.clientX;
      const x = clientX - rect.left;

      const position = scalePixelsToWindow(
        { x, y: 0 },
        viewport,
        dimensions,
      );

      return Math.max(0, Math.min(effectiveDuration, position.time));
    },
    [viewport, dimensions, effectiveDuration],
  );

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      const time = getTimeFromEvent(e);
      setIsDragging(true);
      setDragStart(time);
      setSelection({ min: time, max: time });
    },
    [getTimeFromEvent],
  );

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (!isDragging || dragStart === null) return;

      const time = getTimeFromEvent(e);
      const min = Math.min(dragStart, time);
      const max = Math.max(dragStart, time);
      setSelection({ min, max });
    },
    [isDragging, dragStart, getTimeFromEvent],
  );

  const handleMouseUp = useCallback(() => {
    if (!isDragging || selection === null) return;

    setIsDragging(false);
    setDragStart(null);

    // Ensure minimum duration
    let { min, max } = selection;
    if (max - min < MIN_SEGMENT_DURATION) {
      max = Math.min(effectiveDuration, min + MIN_SEGMENT_DURATION);
      if (max - min < MIN_SEGMENT_DURATION) {
        min = Math.max(0, max - MIN_SEGMENT_DURATION);
      }
      setSelection({ min, max });
    }

    onSegmentChange(min, max);
  }, [isDragging, selection, effectiveDuration, onSegmentChange]);

  const handleTouchStart = useCallback(
    (e: React.TouchEvent) => {
      const time = getTimeFromEvent(e);
      setIsDragging(true);
      setDragStart(time);
      setSelection({ min: time, max: time });
    },
    [getTimeFromEvent],
  );

  const handleTouchMove = useCallback(
    (e: React.TouchEvent) => {
      if (!isDragging || dragStart === null) return;

      const time = getTimeFromEvent(e);
      const min = Math.min(dragStart, time);
      const max = Math.max(dragStart, time);
      setSelection({ min, max });
    },
    [isDragging, dragStart, getTimeFromEvent],
  );

  const handleTouchEnd = useCallback(() => {
    handleMouseUp();
  }, [handleMouseUp]);

  // Play selected segment
  const handlePlaySelection = useCallback(() => {
    if (!selection) return;

    if (audio.isPlaying) {
      audio.pause();
    } else {
      audio.seek(selection.min);
      audio.play();
    }
  }, [selection, audio]);

  // Validation messages
  const validationMessage = useMemo(() => {
    if (!selection) return null;

    const dur = selection.max - selection.min;
    if (dur < MIN_SEGMENT_DURATION) {
      return {
        type: "error" as const,
        message: `Segment must be at least ${MIN_SEGMENT_DURATION} second(s)`,
      };
    }
    if (dur > WARNING_SEGMENT_DURATION) {
      return {
        type: "warning" as const,
        message: `Segment is longer than ${WARNING_SEGMENT_DURATION} seconds. Consider selecting a shorter segment.`,
      };
    }
    return null;
  }, [selection]);

  return (
    <div className="space-y-3">
      {/* Waveform canvas */}
      <div
        ref={containerRef}
        className="relative w-full rounded-lg overflow-hidden border border-stone-300 dark:border-stone-600"
        style={{ height }}
      >
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-stone-900/50 z-10">
            <Loader2 className="w-8 h-8 animate-spin text-emerald-500" />
          </div>
        )}
        <canvas
          ref={canvasRef}
          className="w-full h-full cursor-crosshair"
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseUp}
          onTouchStart={handleTouchStart}
          onTouchMove={handleTouchMove}
          onTouchEnd={handleTouchEnd}
        />
      </div>

      {/* Selection info and controls */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          {selection && (
            <>
              <div className="text-sm text-stone-600 dark:text-stone-400">
                <span className="font-medium">Start:</span>{" "}
                {selection.min.toFixed(2)}s
              </div>
              <div className="text-sm text-stone-600 dark:text-stone-400">
                <span className="font-medium">End:</span>{" "}
                {selection.max.toFixed(2)}s
              </div>
              <div className="text-sm text-stone-600 dark:text-stone-400">
                <span className="font-medium">Duration:</span>{" "}
                {(selection.max - selection.min).toFixed(2)}s
              </div>
            </>
          )}
        </div>

        <Button
          variant="secondary"
          onClick={handlePlaySelection}
          disabled={!selection || isLoading}
        >
          {audio.isPlaying ? (
            <>
              <Pause className="w-4 h-4 mr-2" />
              Pause
            </>
          ) : (
            <>
              <Play className="w-4 h-4 mr-2" />
              Preview
            </>
          )}
        </Button>
      </div>

      {/* Validation message */}
      {validationMessage && (
        <div
          className={`flex items-center gap-2 text-sm ${
            validationMessage.type === "error"
              ? "text-red-500"
              : "text-yellow-500"
          }`}
        >
          <AlertTriangle className="w-4 h-4" />
          {validationMessage.message}
        </div>
      )}

      {/* Instructions */}
      <p className="text-xs text-stone-500 dark:text-stone-400">
        Click and drag on the waveform to select a time segment. The green
        highlighted area shows your selection.
      </p>
    </div>
  );
}
