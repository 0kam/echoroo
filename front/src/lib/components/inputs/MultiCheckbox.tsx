import { useCallback } from "react";
import Checkbox from "./Checkbox";

export interface MultiCheckboxOption {
  value: string;
  label: string;
}

interface MultiCheckboxProps {
  options: MultiCheckboxOption[];
  selectedValues: string[];
  onChange: (values: string[]) => void;
  disabled?: boolean;
}

export default function MultiCheckbox({
  options,
  selectedValues,
  onChange,
  disabled = false,
}: MultiCheckboxProps) {
  const handleToggle = useCallback(
    (value: string) => {
      if (selectedValues.includes(value)) {
        onChange(selectedValues.filter((v) => v !== value));
      } else {
        onChange([...selectedValues, value]);
      }
    },
    [selectedValues, onChange],
  );

  return (
    <div className="space-y-2">
      {options.map((option) => (
        <label
          key={option.value}
          className="flex items-center gap-2 cursor-pointer hover:bg-stone-50 dark:hover:bg-stone-800 px-2 py-1 rounded"
        >
          <Checkbox
            checked={selectedValues.includes(option.value)}
            onChange={() => handleToggle(option.value)}
            disabled={disabled}
          />
          <span className="text-sm text-stone-900 dark:text-stone-100">
            {option.label}
          </span>
        </label>
      ))}
    </div>
  );
}
