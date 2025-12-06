/**
 * Types for the DateTimePatternBuilder component
 */

/** Available datetime component types */
export type DateTimeComponentType =
  | "year"
  | "month"
  | "day"
  | "hour"
  | "minute"
  | "second";

/** Represents a selected range in the filename */
export interface DateTimeSelection {
  /** Unique identifier for the selection */
  id: string;
  /** Start index (inclusive) */
  startIndex: number;
  /** End index (exclusive) */
  endIndex: number;
  /** The type of datetime component */
  type: DateTimeComponentType;
  /** The actual text selected */
  text: string;
}

/** Parse result from attempting to parse the filename */
export interface DateTimeParseResult {
  success: boolean;
  date?: Date;
  error?: string;
}

/** Props for the DateTimePatternBuilder component */
export interface DateTimePatternBuilderProps {
  /** Sample filename to parse */
  filename: string;
  /** Initial pattern (optional) */
  initialPattern?: string;
  /** Callback when pattern changes */
  onPatternChange: (pattern: string, patternType: "strptime" | "regex") => void;
  /** Callback when parse result changes */
  onParse?: (result: DateTimeParseResult) => void;
}

/** Character with its position and selection state */
export interface CharacterInfo {
  char: string;
  index: number;
  selection?: DateTimeSelection;
}

/** Component configuration for display */
export interface ComponentConfig {
  type: DateTimeComponentType;
  label: string;
  shortLabel: string;
  strptimeCode: string;
  regexPattern: string;
  regexGroup: string;
  color: string;
  bgColor: string;
  borderColor: string;
  textColor: string;
  hoverBg: string;
}
