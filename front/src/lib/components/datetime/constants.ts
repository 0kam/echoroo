import type { ComponentConfig, DateTimeComponentType } from "./types";

/** Configuration for each datetime component type */
export const COMPONENT_CONFIGS: Record<DateTimeComponentType, ComponentConfig> =
  {
    year: {
      type: "year",
      label: "Year",
      shortLabel: "Y",
      strptimeCode: "%Y",
      regexPattern: "(\\d{4})",
      regexGroup: "Y",
      color: "emerald",
      bgColor: "bg-emerald-100 dark:bg-emerald-900/50",
      borderColor: "border-emerald-500",
      textColor: "text-emerald-700 dark:text-emerald-300",
      hoverBg: "hover:bg-emerald-200 dark:hover:bg-emerald-800/50",
    },
    month: {
      type: "month",
      label: "Month",
      shortLabel: "M",
      strptimeCode: "%m",
      regexPattern: "(\\d{2})",
      regexGroup: "m",
      color: "blue",
      bgColor: "bg-blue-100 dark:bg-blue-900/50",
      borderColor: "border-blue-500",
      textColor: "text-blue-700 dark:text-blue-300",
      hoverBg: "hover:bg-blue-200 dark:hover:bg-blue-800/50",
    },
    day: {
      type: "day",
      label: "Day",
      shortLabel: "D",
      strptimeCode: "%d",
      regexPattern: "(\\d{2})",
      regexGroup: "d",
      color: "violet",
      bgColor: "bg-violet-100 dark:bg-violet-900/50",
      borderColor: "border-violet-500",
      textColor: "text-violet-700 dark:text-violet-300",
      hoverBg: "hover:bg-violet-200 dark:hover:bg-violet-800/50",
    },
    hour: {
      type: "hour",
      label: "Hour",
      shortLabel: "H",
      strptimeCode: "%H",
      regexPattern: "(\\d{2})",
      regexGroup: "H",
      color: "amber",
      bgColor: "bg-amber-100 dark:bg-amber-900/50",
      borderColor: "border-amber-500",
      textColor: "text-amber-700 dark:text-amber-300",
      hoverBg: "hover:bg-amber-200 dark:hover:bg-amber-800/50",
    },
    minute: {
      type: "minute",
      label: "Minute",
      shortLabel: "m",
      strptimeCode: "%M",
      regexPattern: "(\\d{2})",
      regexGroup: "M",
      color: "teal",
      bgColor: "bg-teal-100 dark:bg-teal-900/50",
      borderColor: "border-teal-500",
      textColor: "text-teal-700 dark:text-teal-300",
      hoverBg: "hover:bg-teal-200 dark:hover:bg-teal-800/50",
    },
    second: {
      type: "second",
      label: "Second",
      shortLabel: "S",
      strptimeCode: "%S",
      regexPattern: "(\\d{2})",
      regexGroup: "S",
      color: "rose",
      bgColor: "bg-rose-100 dark:bg-rose-900/50",
      borderColor: "border-rose-500",
      textColor: "text-rose-700 dark:text-rose-300",
      hoverBg: "hover:bg-rose-200 dark:hover:bg-rose-800/50",
    },
  };

/** Order for component type options in popover */
export const COMPONENT_ORDER: DateTimeComponentType[] = [
  "year",
  "month",
  "day",
  "hour",
  "minute",
  "second",
];

/** Characters that should be treated as literal separators */
export const SEPARATOR_CHARS = ["_", "-", " ", ".", "/", ":"];
