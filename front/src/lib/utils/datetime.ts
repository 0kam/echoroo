type DatetimeComponent = "year" | "month" | "day" | "hour" | "minute" | "second";

interface Selection {
  start: number;
  end: number;
  component: DatetimeComponent;
}

const STRPTIME_CODES: Record<DatetimeComponent, string> = {
  year: "%Y",
  month: "%m",
  day: "%d",
  hour: "%H",
  minute: "%M",
  second: "%S",
};

/**
 * Generate a strptime pattern from user selections.
 *
 * @param filename - The original filename string
 * @param selections - Mapping of datetime components to their selected positions
 * @returns A strptime format string (e.g., "%Y%m%d_%H%M%S")
 */
export function generateStrptimePattern(
  filename: string,
  selections: Record<DatetimeComponent, Selection>
): string {
  // Create an array of all selections sorted by start position
  const sortedSelections = Object.values(selections).sort(
    (a, b) => a.start - b.start
  );

  let pattern = "";
  let lastEnd = 0;

  for (const selection of sortedSelections) {
    // Add literal characters between selections
    if (selection.start > lastEnd) {
      const literalPart = filename.substring(lastEnd, selection.start);
      pattern += literalPart;
    }

    // Add the strptime code for this component
    pattern += STRPTIME_CODES[selection.component];

    lastEnd = selection.end;
  }

  // Add any remaining literal characters after the last selection
  if (lastEnd < filename.length) {
    const extension = filename.substring(lastEnd);
    pattern += extension;
  }

  return pattern;
}

/**
 * Validate that all required datetime components are selected.
 *
 * @param selections - Mapping of datetime components to their selected positions
 * @returns True if at least year, month, day are selected
 */
export function validateDatetimeSelections(
  selections: Partial<Record<DatetimeComponent, Selection>>
): selections is Record<DatetimeComponent, Selection> {
  const requiredComponents: DatetimeComponent[] = ["year", "month", "day"];
  return requiredComponents.every((component) => component in selections);
}

/**
 * Check if selections overlap (which would be invalid).
 *
 * @param selections - Mapping of datetime components to their selected positions
 * @returns True if there are no overlaps
 */
export function checkNoOverlaps(
  selections: Record<DatetimeComponent, Selection>
): boolean {
  const sortedSelections = Object.values(selections).sort(
    (a, b) => a.start - b.start
  );

  for (let i = 0; i < sortedSelections.length - 1; i++) {
    if (sortedSelections[i].end > sortedSelections[i + 1].start) {
      return false;
    }
  }

  return true;
}
