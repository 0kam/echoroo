import classNames from "classnames";

import Button from "@/lib/components/ui/Button";

export type VisibilityFilterValue = "" | "public" | "restricted";

const VISIBILITY_OPTIONS: readonly {
  label: string;
  value: VisibilityFilterValue;
}[] = [
  { label: "All visibility", value: "" },
  { label: "Public only", value: "public" },
  { label: "Restricted only", value: "restricted" },
];

export default function VisibilityFilterChips({
  value,
  onChange,
  disabled = false,
  className,
}: {
  value: VisibilityFilterValue;
  onChange: (value: VisibilityFilterValue) => void;
  disabled?: boolean;
  className?: string;
}) {
  const handleClick = (next: VisibilityFilterValue) => {
    if (disabled) return;
    if (next === "") {
      onChange("");
      return;
    }
    onChange(next === value ? "" : next);
  };

  return (
    <div className={classNames("flex flex-wrap gap-2", className)}>
      {VISIBILITY_OPTIONS.map((option) => {
        const isActive = option.value === value || (option.value === "" && value === "");
        return (
          <Button
            key={option.value || "all"}
            variant={isActive ? "primary" : "secondary"}
            mode={isActive ? "filled" : "outline"}
            padding="px-3 py-1.5"
            onClick={() => handleClick(option.value)}
            disabled={disabled}
          >
            {option.label}
          </Button>
        );
      })}
    </div>
  );
}
